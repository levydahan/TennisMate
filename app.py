import os
import hmac
import json
from datetime import date, datetime, timezone
from functools import wraps

from flask import Flask, jsonify, render_template, request, send_from_directory, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from players import FIXED_PLAYERS, canonical_player, normalize_name
from reminders import (
    build_hour_before_message,
    build_pay_message,
    hour_before_is_due,
    next_hour_before_at,
    next_pay_reminder_at,
    reminder_is_due,
)
from schedule import (
    FIELD_COST_NIS,
    GAME_TIME,
    MAX_PLAYERS,
    TZ,
    draw_teams,
    draw_rematch,
    format_dt_he,
    get_slot_state,
    is_match_day,
    now_il,
    todays_match_game_at,
)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "tennismate-dev-secret")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = bool(os.environ.get("RENDER"))

os.makedirs(app.instance_path, exist_ok=True)

database_url = (
    os.environ.get("DATABASE_URL", "")
    .strip()
    .strip('"')
    .strip("'")
    .replace("\n", "")
    .replace("\r", "")
)
_using_postgres = False
if database_url:
    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg2://" + database_url[len("postgres://") :]
        _using_postgres = True
    elif database_url.startswith("postgresql+psycopg2://"):
        _using_postgres = True
    elif database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg2://" + database_url[len("postgresql://") :]
        _using_postgres = True
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    if _using_postgres:
        engine_opts = {"pool_pre_ping": True, "pool_recycle": 300}
        if "sslmode=" not in database_url:
            # Internal Render URLs have no SSL; External URLs do. "allow" tries
            # a plain connection first, then SSL — so gunicorn can start either way.
            engine_opts["connect_args"] = {"sslmode": "allow", "connect_timeout": 8}
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = engine_opts
else:
    data_dir = os.environ.get("DATA_DIR", app.instance_path)
    os.makedirs(data_dir, exist_ok=True)
    db_path = os.path.join(data_dir, "tennis.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"

PERSISTENT_DB = bool(database_url)

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
    teams2_json = db.Column(db.Text, nullable=True)
    teams2_ids = db.Column(db.String(200), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("slot", "week_key", name="uq_settings_slot_week"),
    )


class PushSubscription(db.Model):
    __tablename__ = "push_subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    endpoint = db.Column(db.Text, nullable=False, unique=True)
    p256dh = db.Column(db.String(200), nullable=False)
    auth = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class PayReminderLog(db.Model):
    __tablename__ = "pay_reminder_logs"

    id = db.Column(db.Integer, primary_key=True)
    slot = db.Column(db.String(20), nullable=False)
    week_key = db.Column(db.String(16), nullable=False)
    sent_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint("slot", "week_key", name="uq_pay_reminder_slot_week"),
    )


class HourBeforeLog(db.Model):
    __tablename__ = "hour_before_logs"

    id = db.Column(db.Integer, primary_key=True)
    slot = db.Column(db.String(20), nullable=False)
    week_key = db.Column(db.String(16), nullable=False)
    sent_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint("slot", "week_key", name="uq_hour_before_slot_week"),
    )


class AppSetting(db.Model):
    __tablename__ = "app_settings"

    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text, nullable=False)


_db_ready = False


def init_db():
    global _db_ready
    if _db_ready:
        return
    with app.app_context():
        db.create_all()
        _ensure_schema()
    _db_ready = True


def _ensure_schema():
    inspector = inspect(db.engine)
    if "enrollments" in inspector.get_table_names():
        columns = {col["name"] for col in inspector.get_columns("enrollments")}
        if "paid" not in columns:
            default_sql = "FALSE" if db.engine.dialect.name == "postgresql" else "0"
            with db.engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE enrollments ADD COLUMN paid BOOLEAN DEFAULT {default_sql}"))
    if "game_settings" in inspector.get_table_names():
        columns = {col["name"] for col in inspector.get_columns("game_settings")}
        with db.engine.begin() as conn:
            if "teams2_json" not in columns:
                conn.execute(text("ALTER TABLE game_settings ADD COLUMN teams2_json TEXT"))
            if "teams2_ids" not in columns:
                conn.execute(text("ALTER TABLE game_settings ADD COLUMN teams2_ids VARCHAR(200)"))


# Do not block gunicorn import on Postgres. Render marks the deploy failed if
# the process dies before it binds to $PORT.
if not _using_postgres:
    try:
        init_db()
    except Exception:
        app.logger.exception("Database setup will retry on the first request")


@app.before_request
def _ensure_db():
    if _db_ready:
        return
    try:
        init_db()
    except Exception:
        app.logger.exception("Database unavailable")
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "message": "מסד הנתונים לא זמין. בדקו את DATABASE_URL ב-Render."}), 503


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            return jsonify({"ok": False, "message": "נדרשת הרשאת מנהל"}), 401
        return fn(*args, **kwargs)

    return wrapper


def sync_slot(slot: str) -> dict:
    """Return the current game cycle. Past enrollments are kept forever."""
    return get_slot_state(slot)


def week_label(week_key: str) -> str:
    day = date.fromisoformat(week_key)
    return format_dt_he(datetime.combine(day, GAME_TIME, tzinfo=TZ))


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


def ensure_teams(
    slot: str, week_key: str, roster: list[dict], teams_ready: bool, rematch_ready: bool = False
) -> tuple[list | None, list | None]:
    settings = get_settings(slot, week_key)
    if not teams_ready:
        if settings.teams_json or settings.teams_ids or settings.teams2_json or settings.teams2_ids:
            settings.teams_json = None
            settings.teams_ids = None
            settings.teams2_json = None
            settings.teams2_ids = None
            db.session.commit()
        return None, None
    ids = roster_fingerprint(roster)
    if settings.teams_json and settings.teams_ids == ids:
        hour1 = json.loads(settings.teams_json)
    else:
        hour1 = draw_teams(roster) if roster else []
        settings.teams_json = json.dumps(hour1, ensure_ascii=False)
        settings.teams_ids = ids
        settings.teams2_json = None
        settings.teams2_ids = None
        db.session.commit()
    hour2 = None
    if rematch_ready and hour1:
        if settings.teams2_json and settings.teams2_ids == ids:
            hour2 = json.loads(settings.teams2_json)
        else:
            hour2 = draw_rematch(roster, hour1) if roster else []
            settings.teams2_json = json.dumps(hour2, ensure_ascii=False)
            settings.teams2_ids = ids
            db.session.commit()
    elif settings.teams2_json or settings.teams2_ids:
        settings.teams2_json = None
        settings.teams2_ids = None
        db.session.commit()
    return hour1, hour2


def players_payload(slot: str, week_key: str, teams_ready: bool, rematch_ready: bool = False) -> dict:
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
    teams, teams2 = ensure_teams(slot, week_key, roster, teams_ready, rematch_ready)
    return {
        "roster": roster,
        "waiting": waiting,
        "squad": squad_for(roster, waiting),
        "count": n,
        "spots_left": max(MAX_PLAYERS - n, 0),
        "share": share,
        "field_cost": FIELD_COST_NIS,
        "booker_id": settings.booker_id,
        "booker_name": booker["name"] if booker else None,
        "teams": teams,
        "teams2": teams2,
    }


def squad_for(roster: list[dict], waiting: list[dict]) -> list[dict]:
    by_name = {}
    for player in roster:
        canon = canonical_player(player["name"])
        if canon:
            by_name[canon] = {**player, "name": canon, "status": "arrived"}
    for player in waiting:
        canon = canonical_player(player["name"])
        if canon:
            by_name[canon] = {**player, "name": canon, "status": "waitlist"}
    squad = []
    for name in FIXED_PLAYERS:
        row = by_name.get(name)
        if row:
            squad.append({"name": name, "status": row["status"], "id": row["id"], "paid": row.get("paid", False)})
        else:
            squad.append({"name": name, "status": "out", "id": None, "paid": False})
    return squad


def attendance_stats() -> dict:
    """Arrival and court-booker history for finished games, per fixed player."""
    spark_max = 16
    tallies = {
        name: {
            "name": name,
            "arrived": 0,
            "missed": 0,
            "booked": 0,
            "arrival_history": [],
            "booker_history": [],
        }
        for name in FIXED_PLAYERS
    }
    finished = []
    for slot in ("sunday", "wednesday"):
        current = get_slot_state(slot)
        week_keys = [
            row[0]
            for row in (
                db.session.query(Enrollment.week_key)
                .filter(Enrollment.slot == slot)
                .distinct()
                .all()
            )
        ]
        for week_key in week_keys:
            if week_key == current["week_key"] and not current["is_past"]:
                continue
            rows = Enrollment.query.filter_by(slot=slot, week_key=week_key, is_waitlist=False).all()
            if not rows:
                continue
            arrived_names = set()
            roster_by_id = {}
            for row in rows:
                canon = canonical_player(row.name)
                if not canon:
                    continue
                arrived_names.add(canon)
                roster_by_id[row.id] = canon
            settings = GameSettings.query.filter_by(slot=slot, week_key=week_key).first()
            booker_name = None
            if settings and settings.booker_id:
                booker_name = roster_by_id.get(settings.booker_id)
            finished.append((week_key, slot, arrived_names, booker_name))

    finished.sort(key=lambda item: (item[0], item[1]))
    for _week_key, _slot, arrived_names, booker_name in finished:
        for name in FIXED_PLAYERS:
            row = tallies[name]
            arrived = name in arrived_names
            row["arrived" if arrived else "missed"] += 1
            row["arrival_history"].append(1 if arrived else 0)
            booked = booker_name == name
            if booked:
                row["booked"] += 1
            row["booker_history"].append(1 if booked else 0)

    players = []
    for name in FIXED_PLAYERS:
        row = tallies[name]
        total = row["arrived"] + row["missed"]
        row["not_booked"] = max(total - row["booked"], 0)
        if len(row["arrival_history"]) > spark_max:
            row["arrival_history"] = row["arrival_history"][-spark_max:]
            row["booker_history"] = row["booker_history"][-spark_max:]
        players.append(row)
    return {"games": len(finished), "players": players}


def history_for_slot(slot: str, current_week_key: str) -> list[dict]:
    week_keys = [
        row[0]
        for row in (
            db.session.query(Enrollment.week_key)
            .filter(Enrollment.slot == slot, Enrollment.week_key != current_week_key)
            .distinct()
            .order_by(Enrollment.week_key.desc())
            .limit(12)
            .all()
        )
    ]
    history = []
    for week_key in week_keys:
        rows = (
            Enrollment.query.filter_by(slot=slot, week_key=week_key)
            .order_by(Enrollment.is_waitlist.asc(), Enrollment.joined_at.asc(), Enrollment.id.asc())
            .all()
        )
        roster = [serialize_player(row) for row in rows if not row.is_waitlist]
        waiting = [serialize_player(row) for row in rows if row.is_waitlist]
        if not roster and not waiting:
            continue
        settings = GameSettings.query.filter_by(slot=slot, week_key=week_key).first()
        teams = None
        teams2 = None
        booker_name = None
        if settings:
            if settings.teams_json:
                teams = json.loads(settings.teams_json)
            if getattr(settings, "teams2_json", None):
                teams2 = json.loads(settings.teams2_json)
            if settings.booker_id:
                booker = next((p for p in roster if p["id"] == settings.booker_id), None)
                booker_name = booker["name"] if booker else None
        n = len(roster)
        history.append({
            "week_key": week_key,
            "game_at_he": week_label(week_key),
            "roster": roster,
            "waiting": waiting,
            "count": n,
            "share": round(FIELD_COST_NIS / n, 2) if n else None,
            "booker_name": booker_name,
            "teams": teams,
            "teams2": teams2,
        })
    return history


def serialize_player(row: Enrollment) -> dict:
    return {
        "id": row.id,
        "name": canonical_player(row.name) or row.name,
        "is_waitlist": row.is_waitlist,
        "paid": row.paid,
        "joined_at": row.joined_at.isoformat() if row.joined_at else None,
    }


def _b64url(raw: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _ensure_vapid_keys() -> tuple[str, str] | tuple[None, None]:
    public = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    private = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    if public and private:
        return public, private
    row_pub = db.session.get(AppSetting, "vapid_public")
    row_priv = db.session.get(AppSetting, "vapid_private")
    if row_pub and row_priv:
        return row_pub.value, row_priv.value
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
    except ImportError:
        return None, None
    key = ec.generate_private_key(ec.SECP256R1())
    from cryptography.hazmat.primitives import serialization
    private_bytes = key.private_numbers().private_value.to_bytes(32, "big")
    public_bytes = key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    public = _b64url(public_bytes)
    private = _b64url(private_bytes)
    db.session.merge(AppSetting(key="vapid_public", value=public))
    db.session.merge(AppSetting(key="vapid_private", value=private))
    db.session.commit()
    return public, private


def vapid_public_key() -> str | None:
    try:
        public, _private = _ensure_vapid_keys()
    except Exception:
        app.logger.exception("VAPID key setup failed")
        return None
    return public


def _cron_authorized() -> bool:
    expected = os.environ.get("CRON_SECRET", "").strip()
    provided = (request.headers.get("X-Cron-Secret") or request.args.get("secret") or "").strip()
    if expected:
        return hmac.compare_digest(provided, expected)
    return not os.environ.get("RENDER")


def dispatch_web_push(message: dict) -> int:
    public, private = _ensure_vapid_keys()
    if not public or not private:
        return 0
    try:
        from pywebpush import webpush
    except ImportError:
        return 0
    sent = 0
    for row in PushSubscription.query.all():
        try:
            webpush(
                subscription_info={
                    "endpoint": row.endpoint,
                    "keys": {"p256dh": row.p256dh, "auth": row.auth},
                },
                data=json.dumps({
                    "title": message["title"],
                    "body": message["body"],
                }, ensure_ascii=False),
                vapid_private_key=private,
                vapid_claims={"sub": "mailto:tennismate@localhost"},
            )
            sent += 1
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                db.session.delete(row)
            else:
                app.logger.warning("Web push failed: %s", exc)
    db.session.commit()
    return sent


def run_pay_reminders(force: bool = False) -> dict:
    now = now_il()
    sent = []
    skipped = []
    for slot in ("sunday", "wednesday"):
        state = get_slot_state(slot, now)
        players = players_payload(slot, state["week_key"], state["teams_ready"], state.get("rematch_ready", False))
        roster = players["roster"]
        if not roster:
            skipped.append({"slot": slot, "reason": "empty"})
            continue
        if not reminder_is_due(state, now, force=force):
            skipped.append({"slot": slot, "reason": "not_due"})
            continue
        already = PayReminderLog.query.filter_by(slot=slot, week_key=state["week_key"]).first()
        if already and not force:
            skipped.append({"slot": slot, "reason": "already_sent"})
            continue
        names = [canonical_player(p["name"]) or p["name"] for p in roster]
        message = build_pay_message(state["label_he"], players["share"], names)
        pushed = dispatch_web_push(message)
        if not already:
            db.session.add(PayReminderLog(slot=slot, week_key=state["week_key"]))
            db.session.commit()
        sent.append({
            **message,
            "slot": slot,
            "week_key": state["week_key"],
            "pushed": pushed,
        })
    return {"ok": True, "sent": sent, "skipped": skipped}


def run_hour_before_reminders(force: bool = False) -> dict:
    now = now_il()
    if not hour_before_is_due(now, force=force):
        return {"ok": True, "sent": [], "skipped": [{"reason": "not_due"}]}
    if now.weekday() == 6:
        slot = "sunday"
    elif now.weekday() == 2:
        slot = "wednesday"
    else:
        slot = "sunday" if force else None
    if not slot:
        return {"ok": True, "sent": [], "skipped": [{"reason": "not_match_day"}]}
    state = get_slot_state(slot, now)
    already = HourBeforeLog.query.filter_by(slot=slot, week_key=state["week_key"]).first()
    if already and not force:
        return {"ok": True, "sent": [], "skipped": [{"slot": slot, "reason": "already_sent"}]}
    message = build_hour_before_message(state["label_he"])
    pushed = dispatch_web_push(message)
    if not already:
        db.session.add(HourBeforeLog(slot=slot, week_key=state["week_key"]))
        db.session.commit()
    return {
        "ok": True,
        "sent": [{**message, "slot": slot, "week_key": state["week_key"], "pushed": pushed}],
        "skipped": [],
    }


def public_state() -> dict:
    games = []
    for slot in ("sunday", "wednesday"):
        state = sync_slot(slot)
        players = players_payload(slot, state["week_key"], state["teams_ready"], state.get("rematch_ready", False))
        games.append({
            **state,
            **players,
            "history": history_for_slot(slot, state["week_key"]),
        })
    nxt = next_pay_reminder_at()
    hour_before = next_hour_before_at()
    match_at = todays_match_game_at()
    return {
        "now": now_il().isoformat(),
        "is_admin": bool(session.get("is_admin")),
        "persistent": PERSISTENT_DB,
        "games": games,
        "players": FIXED_PLAYERS,
        "stats": attendance_stats(),
        "vapid_public_key": vapid_public_key(),
        "pay_reminder_at": nxt.isoformat(),
        "pay_reminder_at_he": format_dt_he(nxt),
        "hour_before_at": hour_before.isoformat(),
        "hour_before_at_he": format_dt_he(hour_before),
        "is_match_day": is_match_day(),
        "match_game_at": match_at.isoformat() if match_at else None,
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
    name = canonical_player(data.get("name") or "")
    is_admin = bool(session.get("is_admin"))

    if slot not in ("sunday", "wednesday"):
        return jsonify({"ok": False, "message": "משחק לא תקין"}), 400
    if not name:
        return jsonify({"ok": False, "message": "יש לבחור שם מרשימת השחקנים"}), 400
    _, name_key = normalize_name(name)

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


@app.get("/sw.js")
def service_worker():
    response = send_from_directory(app.static_folder, "sw.js")
    response.headers["Content-Type"] = "application/javascript; charset=utf-8"
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/manifest.webmanifest")
def web_manifest():
    return send_from_directory(app.static_folder, "manifest.webmanifest")


@app.post("/api/push/subscribe")
def push_subscribe():
    data = request.get_json(silent=True) or {}
    sub = data.get("subscription") or data
    endpoint = (sub.get("endpoint") or "").strip()
    keys = sub.get("keys") or {}
    p256dh = (keys.get("p256dh") or "").strip()
    auth = (keys.get("auth") or "").strip()
    if not endpoint or not p256dh or not auth:
        return jsonify({"ok": False, "message": "הרשמת התראות לא תקינה"}), 400
    row = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if row:
        row.p256dh = p256dh
        row.auth = auth
    else:
        db.session.add(PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth))
    db.session.commit()
    return jsonify({"ok": True, "message": "תזכורות התשלום הופעלו"})


@app.route("/api/cron/pay-reminder", methods=["GET", "POST"])
def cron_pay_reminder():
    if not _cron_authorized():
        return jsonify({"ok": False, "message": "אין הרשאה"}), 401
    body = request.get_json(silent=True) or {}
    force = request.args.get("force") == "1" or bool(body.get("force"))
    pay = run_pay_reminders(force=force)
    hour = run_hour_before_reminders(force=False)
    sent = list(hour.get("sent") or []) + list(pay.get("sent") or [])
    result = {
        "ok": True,
        "sent": sent,
        "skipped": list(hour.get("skipped") or []) + list(pay.get("skipped") or []),
        "hour_before": hour,
        "pay": pay,
    }
    if sent:
        result["message"] = sent[0]["body"]
    elif not force:
        result["message"] = "אין תזכורת כרגע"
    else:
        result["message"] = "אין שחקנים במגרש, אין מה לשלוח"
    return jsonify(result)


@app.post("/api/admin/pay-reminder")
@admin_required
def admin_pay_reminder():
    result = run_pay_reminders(force=True)
    if result["sent"]:
        result["message"] = result["sent"][0]["body"]
    else:
        result["message"] = "אין שחקנים במגרש, אין מה לשלוח"
    result["ok"] = True
    return jsonify(result)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
