import os
import hmac
import json
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, jsonify, render_template, request, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from schedule import FIELD_COST_NIS, MAX_PLAYERS, draw_teams, get_slot_state, now_il

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "tennismate-dev-secret")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("RENDER"))

os.makedirs(app.instance_path, exist_ok=True)

database_url = os.environ.get("DATABASE_URL", "").strip()
if database_url:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
else:
    db_path = os.path.join(app.instance_path, "tennis.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "0508716669")

db = SQLAlchemy(app)


class Enrollment(db.Model):
    __tablename__ = "enrollments"

    id = db.Column(db.Integer, primary_key=True)
    slot = db.Column(db.String(20), nullable=False, index=True)
    week_key = db.Column(db.String(16), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)
    name_key = db.Column(db.String(80), nullable=False)
    is_waitlist = db.Column(db.Boolean, nullable=False, default=False)
    paid = db.Column(db.Boolean, nullable=False, default=False)
    joined_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint("slot", "week_key", "name_key", name="uq_slot_week_name"),
    )


class GameSettings(db.Model):
    __tablename__ = "game_settings"

    id = db.Column(db.Integer, primary_key=True)
    slot = db.Column(db.String(20), nullable=False)
    week_key = db.Column(db.String(16), nullable=False)
    booker_id = db.Column(db.Integer, nullable=True)
    teams_json = db.Column(db.Text, nullable=True)
    teams_ids = db.Column(db.String(200), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("slot", "week_key", name="uq_settings_slot_week"),
    )


def init_db():
    with app.app_context():
        db.create_all()
        _ensure_schema()


def _ensure_schema():
    inspector = inspect(db.engine)
    if "enrollments" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("enrollments")}
    if "paid" not in columns:
        with db.engine.begin() as conn:
            conn.execute(text("ALTER TABLE enrollments ADD COLUMN paid BOOLEAN DEFAULT 0"))


init_db()


def normalize_name(raw: str) -> tuple[str, str]:
    name = " ".join((raw or "").split())
    return name, name.casefold()


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify({"ok": False, "message": "נדרשת הרשאת מנהל"}), 401
        return fn(*args, **kwargs)

    return wrapper


def sync_slot(slot: str) -> dict:
    state = get_slot_state(slot)
    stale_players = Enrollment.query.filter(
        Enrollment.slot == slot,
        Enrollment.week_key != state["week_key"],
    )
    stale_settings = GameSettings.query.filter(
        GameSettings.slot == slot,
        GameSettings.week_key != state["week_key"],
    )
    changed = False
    if stale_players.count():
        stale_players.delete(synchronize_session=False)
        changed = True
    if stale_settings.count():
        stale_settings.delete(synchronize_session=False)
        changed = True
    if changed:
        db.session.commit()
    return state


def get_settings(slot: str, week_key: str) -> GameSettings:
    row = GameSettings.query.filter_by(slot=slot, week_key=week_key).first()
    if row:
        return row
    row = GameSettings(slot=slot, week_key=week_key)
    db.session.add(row)
    db.session.commit()
    return row


def roster_fingerprint(roster: list[dict]) -> str:
    return ",".join(str(player["id"]) for player in roster)


def ensure_teams(slot: str, week_key: str, roster: list[dict], teams_ready: bool) -> list | None:
    settings = get_settings(slot, week_key)
    if not teams_ready:
        if settings.teams_json or settings.teams_ids:
            settings.teams_json = None
            settings.teams_ids = None
            db.session.commit()
        return None
    ids = roster_fingerprint(roster)
    if settings.teams_json and settings.teams_ids == ids:
        return json.loads(settings.teams_json)
    teams = draw_teams(roster) if roster else []
    settings.teams_json = json.dumps(teams, ensure_ascii=False)
    settings.teams_ids = ids
    db.session.commit()
    return teams


def players_payload(slot: str, week_key: str, teams_ready: bool) -> dict:
    rows = (
        Enrollment.query.filter_by(slot=slot, week_key=week_key)
        .order_by(Enrollment.is_waitlist.asc(), Enrollment.joined_at.asc(), Enrollment.id.asc())
        .all()
    )
    roster = [serialize_player(row) for row in rows if not row.is_waitlist]
    waiting = [serialize_player(row) for row in rows if row.is_waitlist]
    settings = get_settings(slot, week_key)
    roster_ids = {player["id"] for player in roster}
    if settings.booker_id and settings.booker_id not in roster_ids:
        settings.booker_id = None
        db.session.commit()
    n = len(roster)
    share = round(FIELD_COST_NIS / n, 2) if n else None
    booker = next((player for player in roster if player["id"] == settings.booker_id), None)
    teams = ensure_teams(slot, week_key, roster, teams_ready)
    return {
        "roster": roster,
        "waiting": waiting,
        "count": n,
        "spots_left": max(MAX_PLAYERS - n, 0),
        "share": share,
        "field_cost": FIELD_COST_NIS,
        "booker_id": settings.booker_id,
        "booker_name": booker["name"] if booker else None,
        "teams": teams,
    }


def serialize_player(row: Enrollment) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "is_waitlist": row.is_waitlist,
        "paid": row.paid,
        "joined_at": row.joined_at.isoformat() if row.joined_at else None,
    }


def public_state() -> dict:
    games = []
    for slot in ("sunday", "wednesday"):
        state = sync_slot(slot)
        players = players_payload(slot, state["week_key"], state["teams_ready"])
        games.append({**state, **players})
    return {
        "now": now_il().isoformat(),
        "is_admin": bool(session.get("is_admin")),
        "games": games,
        "max_players": MAX_PLAYERS,
        "field_cost": FIELD_COST_NIS,
    }


@app.route("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def api_state():
    return jsonify(public_state())


@app.get("/health")
def health():
    return jsonify({"ok": True})


@app.post("/api/join")
def api_join():
    data = request.get_json(silent=True) or {}
    slot = (data.get("slot") or "").strip()
    name, name_key = normalize_name(data.get("name") or "")
    is_admin = bool(session.get("is_admin"))

    if slot not in ("sunday", "wednesday"):
        return jsonify({"ok": False, "message": "משחק לא תקין"}), 400
    if not name or len(name) < 2:
        return jsonify({"ok": False, "message": "נא להזין שם מלא"}), 400
    if len(name) > 80:
        return jsonify({"ok": False, "message": "השם ארוך מדי"}), 400

    state = sync_slot(slot)
    if not state["is_open"] and not is_admin:
        return jsonify({"ok": False, "message": "ההרשמה סגורה כרגע"}), 400

    existing = Enrollment.query.filter_by(
        slot=slot, week_key=state["week_key"], name_key=name_key
    ).first()
    if existing:
        if existing.is_waitlist:
            return jsonify({"ok": False, "message": "אתה כבר ברשימת ההמתנה"}), 400
        return jsonify({"ok": False, "message": "אתה כבר רשום למשחק"}), 400

    roster_count = Enrollment.query.filter_by(
        slot=slot, week_key=state["week_key"], is_waitlist=False
    ).count()
    waitlisted = roster_count >= MAX_PLAYERS
    row = Enrollment(
        slot=slot,
        week_key=state["week_key"],
        name=name,
        name_key=name_key,
        is_waitlist=waitlisted,
    )
    db.session.add(row)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "השם כבר רשום למשחק"}), 400

    if waitlisted:
        message = f"{name} נוסף לרשימת ההמתנה"
    else:
        message = f"{name} נרשם למשחק"

    payload = public_state()
    payload.update({"ok": True, "message": message, "waitlisted": waitlisted})
    return jsonify(payload)


def _promote_first_waitlisted(slot: str, week_key: str) -> str | None:
    nxt = (
        Enrollment.query.filter_by(slot=slot, week_key=week_key, is_waitlist=True)
        .order_by(Enrollment.joined_at.asc(), Enrollment.id.asc())
        .first()
    )
    if not nxt:
        return None
    nxt.is_waitlist = False
    return nxt.name


@app.post("/api/admin/login")
def admin_login():
    data = request.get_json(silent=True) or {}
    password = str(data.get("password") or "")
    if not hmac.compare_digest(password, ADMIN_PASSWORD):
        return jsonify({"ok": False, "message": "סיסמה שגויה"}), 401
    session["is_admin"] = True
    payload = public_state()
    payload.update({"ok": True, "message": "התחברת כמנהל"})
    return jsonify(payload)


@app.post("/api/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    payload = public_state()
    payload.update({"ok": True, "message": "התנתקת"})
    return jsonify(payload)


@app.post("/api/admin/remove")
@admin_required
def admin_remove():
    data = request.get_json(silent=True) or {}
    player_id = data.get("id")
    row = db.session.get(Enrollment, player_id)
    if not row:
        return jsonify({"ok": False, "message": "שחקן לא נמצא"}), 404

    slot = row.slot
    week_key = row.week_key
    was_waitlist = row.is_waitlist
    name = row.name
    db.session.delete(row)
    db.session.flush()
    promoted = None
    if not was_waitlist:
        promoted = _promote_first_waitlisted(slot, week_key)
    db.session.commit()

    message = f"{name} הוסר"
    if promoted:
        message += f" · {promoted} עלה מההמתנה"
    payload = public_state()
    payload.update({"ok": True, "message": message})
    return jsonify(payload)


@app.post("/api/admin/paid")
@admin_required
def admin_paid():
    data = request.get_json(silent=True) or {}
    row = db.session.get(Enrollment, data.get("id"))
    if not row:
        return jsonify({"ok": False, "message": "שחקן לא נמצא"}), 404
    row.paid = bool(data.get("paid"))
    db.session.commit()
    payload = public_state()
    payload.update({"ok": True, "message": "עודכן תשלום"})
    return jsonify(payload)


@app.post("/api/booker")
def api_booker():
    data = request.get_json(silent=True) or {}
    slot = (data.get("slot") or "").strip()
    player_id = data.get("player_id")
    if slot not in ("sunday", "wednesday"):
        return jsonify({"ok": False, "message": "משחק לא תקין"}), 400

    state = sync_slot(slot)
    settings = get_settings(slot, state["week_key"])
    if not player_id:
        settings.booker_id = None
        db.session.commit()
        payload = public_state()
        payload.update({"ok": True, "message": "בוטל מזמין המגרש"})
        return jsonify(payload)

    row = db.session.get(Enrollment, player_id)
    if (
        not row
        or row.slot != slot
        or row.week_key != state["week_key"]
        or row.is_waitlist
    ):
        return jsonify({"ok": False, "message": "יש לבחור שחקן שנרשם למשחק"}), 400

    settings.booker_id = row.id
    db.session.commit()
    payload = public_state()
    payload.update({"ok": True, "message": f"{row.name} יזמין את המגרש"})
    return jsonify(payload)


@app.post("/api/admin/clear")
@admin_required
def admin_clear():
    data = request.get_json(silent=True) or {}
    slot = (data.get("slot") or "").strip()
    if slot not in ("sunday", "wednesday"):
        return jsonify({"ok": False, "message": "משחק לא תקין"}), 400
    state = sync_slot(slot)
    Enrollment.query.filter_by(slot=slot, week_key=state["week_key"]).delete(
        synchronize_session=False
    )
    GameSettings.query.filter_by(slot=slot, week_key=state["week_key"]).delete(
        synchronize_session=False
    )
    db.session.commit()
    payload = public_state()
    payload.update({"ok": True, "message": "הרשימה נוקתה"})
    return jsonify(payload)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
