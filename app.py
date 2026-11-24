import os
import hmac
import json
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from functools import wraps

from flask import Flask, g, jsonify, render_template, request, send_from_directory, session
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from pairing import explain_pairs
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
    DAYS_HE,
    FIELD_COST_NIS,
    GAME_END_TIME,
    GAME_TIME,
    MAX_PLAYERS,
    SLOTS,
    TZ,
    banner_should_flash,
    banner_target,
    draw_teams,
    draw_rematch,
    end_dt_for,
    format_dt_he,
    get_slot_state,
    is_match_day,
    kickoff_bundle,
    next_game_at,
    now_il,
    parse_game_time,
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
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=60)
app.config["MAX_CONTENT_LENGTH"] = 400 * 1024

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "0508716669")
PAY_WARNING = "הלו הלו לא שילמת למשחקת תשלם עכשיו"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def bit_pay_phone() -> str:
    """Digits-only Bit receive number from env. Empty if unset."""
    return "".join(ch for ch in os.environ.get("BIT_PAY_PHONE", "") if ch.isdigit())

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
    user_id = db.Column(db.Integer, nullable=True, index=True)
    joined_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        db.UniqueConstraint("slot", "week_key", "name_key", name="uq_slot_week_name"),
    )


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    avatar = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))


class GameSettings(db.Model):
    __tablename__ = "game_settings"

    id = db.Column(db.Integer, primary_key=True)
    slot = db.Column(db.String(20), nullable=False)
    week_key = db.Column(db.String(16), nullable=False)
    booker_id = db.Column(db.Integer, nullable=True)
    booker_custom = db.Column(db.String(80), nullable=True)
    game_date = db.Column(db.String(16), nullable=True)
    game_time = db.Column(db.String(8), nullable=True)
    location = db.Column(db.String(120), nullable=True)
    nav_address = db.Column(db.String(200), nullable=True)
    field_cost = db.Column(db.Integer, nullable=True)
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
        if "user_id" not in columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE enrollments ADD COLUMN user_id INTEGER"))
    if "game_settings" in inspector.get_table_names():
        columns = {col["name"] for col in inspector.get_columns("game_settings")}
        with db.engine.begin() as conn:
            if "teams2_json" not in columns:
                conn.execute(text("ALTER TABLE game_settings ADD COLUMN teams2_json TEXT"))
            if "teams2_ids" not in columns:
                conn.execute(text("ALTER TABLE game_settings ADD COLUMN teams2_ids VARCHAR(200)"))
            if "booker_custom" not in columns:
                conn.execute(text("ALTER TABLE game_settings ADD COLUMN booker_custom VARCHAR(80)"))
            if "game_date" not in columns:
                conn.execute(text("ALTER TABLE game_settings ADD COLUMN game_date VARCHAR(16)"))
            if "game_time" not in columns:
                conn.execute(text("ALTER TABLE game_settings ADD COLUMN game_time VARCHAR(8)"))
            if "location" not in columns:
                conn.execute(text("ALTER TABLE game_settings ADD COLUMN location VARCHAR(120)"))
            if "nav_address" not in columns:
                conn.execute(text("ALTER TABLE game_settings ADD COLUMN nav_address VARCHAR(200)"))
            if "field_cost" not in columns:
                conn.execute(text("ALTER TABLE game_settings ADD COLUMN field_cost INTEGER"))
    if "users" in inspector.get_table_names():
        columns = {col["name"] for col in inspector.get_columns("users")}
        if "avatar" not in columns:
            with db.engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN avatar TEXT"))


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


def normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def current_user() -> User | None:
    uid = session.get("user_id")
    if not uid:
        return None
    return db.session.get(User, uid)


def serialize_user(user: User | None) -> dict | None:
    if not user:
        return None
    return {"id": user.id, "email": user.email, "name": user.name, "avatar": user.avatar}


def booker_users() -> list[dict]:
    rows = User.query.order_by(User.name.asc(), User.id.asc()).all()
    return [
        {"id": row.id, "name": canonical_player(row.name) or row.name}
        for row in rows
    ]


def login_user(user: User) -> None:
    session["user_id"] = user.id
    session.permanent = True


def name_taken(name: str, exclude_id: int | None = None) -> bool:
    _, name_key = normalize_name(name)
    for row in User.query.all():
        if exclude_id is not None and row.id == exclude_id:
            continue
        if normalize_name(row.name)[1] == name_key:
            return True
    return False


def pay_warning_text(debt: dict | None) -> str | None:
    """One Hebrew nag, including the unpaid game's date."""
    if not debt:
        return None
    try:
        day = date.fromisoformat(debt["week_key"])
        date_he = day.strftime("%d.%m.%Y")
    except (KeyError, ValueError):
        date_he = ""
    label = debt.get("label_he") or SLOTS.get(debt.get("slot"), {}).get("label_he", "")
    when = f"{label} {date_he}".strip()
    if when:
        return f"הלו הלו לא שילמת למשחק של {when} תשלם עכשיו"
    return PAY_WARNING


def unpaid_debt(user: User | None, now: datetime | None = None) -> dict | None:
    """Roster seat on a fully ended game that the player never marked paid.

    Waitlist, games that have not started, and games still in progress
    (20:00–22:01 Israel) never produce a nag.
    """
    if not user:
        return None
    now = now_il() if now is None else now
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)
    rows = Enrollment.query.filter_by(is_waitlist=False, paid=False, user_id=user.id).all()
    if not rows:
        _, name_key = normalize_name(user.name)
        rows = Enrollment.query.filter(
            Enrollment.is_waitlist.is_(False),
            Enrollment.paid.is_(False),
            Enrollment.user_id.is_(None),
            Enrollment.name_key == name_key,
        ).all()
    debts = []
    for row in rows:
        if row.is_waitlist or row.paid:
            continue
        try:
            game_date = date.fromisoformat(row.week_key)
        except ValueError:
            continue
        settings = GameSettings.query.filter_by(slot=row.slot, week_key=row.week_key).first()
        raw = (getattr(settings, "game_date", None) or "").strip()
        if raw:
            try:
                game_date = date.fromisoformat(raw)
            except ValueError:
                pass
        kickoff = parse_game_time(getattr(settings, "game_time", None)) or GAME_TIME
        clocks = kickoff_bundle(game_date, kickoff)
        start_dt = clocks["game_dt"]
        end_dt = clocks["game_end_dt"]
        if now < end_dt:
            continue
        if now < start_dt:
            continue
        n = Enrollment.query.filter_by(slot=row.slot, week_key=row.week_key, is_waitlist=False).count()
        share = round(game_field_cost(settings) / n, 2) if n else None
        debts.append({
            "enrollment_id": row.id,
            "slot": row.slot,
            "week_key": row.week_key,
            "label_he": SLOTS.get(row.slot, {}).get("label_he", row.slot),
            "game_at_he": week_label(row.week_key),
            "share": share,
        })
    if not debts:
        return None
    debts.sort(key=lambda item: item["week_key"], reverse=True)
    return debts[0]


def owns_enrollment(row: Enrollment, user: User) -> bool:
    if row.user_id is not None:
        return row.user_id == user.id
    return row.name_key == normalize_name(user.name)[1]


def game_field_cost(settings: GameSettings | None) -> int:
    if settings is not None and settings.field_cost is not None:
        return int(settings.field_cost)
    return FIELD_COST_NIS


def game_location(settings: GameSettings | None) -> str | None:
    loc = (getattr(settings, "location", None) or "").strip()
    return loc or None


def game_nav_address(settings: GameSettings | None) -> str | None:
    addr = (getattr(settings, "nav_address", None) or "").strip()
    return addr or None


def load_game_overrides() -> dict:
    cached = getattr(g, "game_overrides", None)
    if cached is not None:
        return cached
    mapping = {"dates": {}, "times": {}}
    try:
        rows = GameSettings.query.all()
    except Exception:
        g.game_overrides = mapping
        return mapping
    for row in rows:
        key = (row.slot, row.week_key)
        raw = (row.game_date or "").strip()
        if raw:
            try:
                mapping["dates"][key] = date.fromisoformat(raw)
            except ValueError:
                pass
        kickoff = parse_game_time(row.game_time)
        if kickoff:
            mapping["times"][key] = kickoff
    g.game_overrides = mapping
    return mapping


def load_date_overrides() -> dict:
    return load_game_overrides()["dates"]


def load_time_overrides() -> dict:
    return load_game_overrides()["times"]


def clear_date_overrides_cache():
    for attr in ("date_overrides", "game_overrides"):
        if hasattr(g, attr):
            delattr(g, attr)


def sync_slot(slot: str, now: datetime | None = None) -> dict:
    """Return the current game cycle. Past enrollments are kept forever."""
    return get_slot_state(slot, now, load_date_overrides(), load_time_overrides())


def week_label(week_key: str, settings: GameSettings | None = None) -> str:
    play_day = date.fromisoformat(week_key)
    kickoff = GAME_TIME
    if settings:
        raw = (settings.game_date or "").strip()
        if raw:
            try:
                play_day = date.fromisoformat(raw)
            except ValueError:
                pass
        kickoff = parse_game_time(settings.game_time) or GAME_TIME
    return format_dt_he(datetime.combine(play_day, kickoff, tzinfo=TZ))


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


def resolve_booker(settings: GameSettings | None, roster: list[dict]) -> tuple[int | None, str | None]:
    if not settings:
        return None, None
    by_id = {player["id"]: player for player in roster}
    if settings.booker_id and settings.booker_id in by_id:
        player = by_id[settings.booker_id]
        return player["id"], player["name"]
    custom = (settings.booker_custom or "").strip()
    if not custom:
        return None, None
    display = canonical_player(custom) or custom
    match = next((player for player in roster if player["name"] == display), None)
    if match:
        return match["id"], match["name"]
    return None, display


def _team_name_pairs(teams_json: str | None) -> list[tuple[str, str]]:
    """Two-player teams from a stored draw, as name pairs."""
    if not teams_json:
        return []
    try:
        teams = json.loads(teams_json)
    except ValueError:
        return []
    pairs = []
    for team in teams or []:
        names = [
            canonical_player(player.get("name") or "") or player.get("name") or ""
            for player in team.get("players") or []
        ]
        if len(names) == 2 and all(names):
            pairs.append((names[0], names[1]))
    return pairs


def pairing_history(slot: str, week_key: str) -> list[dict]:
    """Past sessions (date + pairs that played) for the pairing algorithm.

    Built from the teams stored for earlier games, both slots together,
    excluding the game being drawn and anything after it.
    """
    history = []
    rows = GameSettings.query.filter(GameSettings.week_key < week_key).all()
    for row in rows:
        pairs = _team_name_pairs(row.teams_json) + _team_name_pairs(row.teams2_json)
        if pairs:
            history.append({"date": row.week_key, "pairs": pairs})
    return history


def _team_names(team: dict) -> list[str]:
    return [
        canonical_player(player.get("name") or "") or (player.get("name") or "")
        for player in team.get("players") or []
    ]


def draw_explanation(
    roster: list[dict], teams: list | None, teams2: list | None, history: list[dict]
) -> dict | None:
    """Why this draw was chosen, in terms of the pair history."""
    if not teams:
        return None
    names = [canonical_player(player["name"]) or player["name"] for player in roster]
    hour1 = [_team_names(team) for team in teams]
    waiting = next((n[0] for n in hour1 if len(n) == 1), None)
    why = {
        "players": len(roster),
        "waiting": waiting,
        "hour1": explain_pairs(names, [tuple(n) for n in hour1 if len(n) == 2], history),
        "hour2": None,
    }
    if teams2:
        hour2 = [_team_names(team) for team in teams2]
        why["hour2"] = explain_pairs(names, [tuple(n) for n in hour2 if len(n) == 2], history)
    return why


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
        hour1 = draw_teams(roster, history=pairing_history(slot, week_key)) if roster else []
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
            hour2 = (
                draw_rematch(roster, hour1, history=pairing_history(slot, week_key))
                if roster
                else []
            )
            settings.teams2_json = json.dumps(hour2, ensure_ascii=False)
            settings.teams2_ids = ids
            db.session.commit()
    elif settings.teams2_json or settings.teams2_ids:
        settings.teams2_json = None
        settings.teams2_ids = None
        db.session.commit()
    return hour1, hour2


def players_payload(
    slot: str, week_key: str, teams_ready: bool, rematch_ready: bool = False, me: User | None = None
) -> dict:
    rows = (
        Enrollment.query.filter_by(slot=slot, week_key=week_key)
        .order_by(Enrollment.is_waitlist.asc(), Enrollment.joined_at.asc(), Enrollment.id.asc())
        .all()
    )
    roster = [serialize_player(row, me) for row in rows if not row.is_waitlist]
    waiting = [serialize_player(row, me) for row in rows if row.is_waitlist]
    settings = get_settings(slot, week_key)
    roster_ids = {player["id"] for player in roster}
    if settings.booker_id and settings.booker_id not in roster_ids:
        settings.booker_id = None
        db.session.commit()
    n = len(roster)
    cost = game_field_cost(settings)
    share = round(cost / n, 2) if n else None
    booker_id, booker_name = resolve_booker(settings, roster)
    teams, teams2 = ensure_teams(slot, week_key, roster, teams_ready, rematch_ready)
    teams_why = (
        draw_explanation(roster, teams, teams2, pairing_history(slot, week_key)) if teams else None
    )
    return {
        "roster": roster,
        "waiting": waiting,
        "squad": squad_for(roster, waiting),
        "count": n,
        "spots_left": max(MAX_PLAYERS - n, 0),
        "share": share,
        "field_cost": cost,
        "location": game_location(settings),
        "nav_address": game_nav_address(settings),
        "booker_id": booker_id,
        "booker_name": booker_name,
        "teams": teams,
        "teams2": teams2,
        "teams_why": teams_why,
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


def known_stat_names() -> list[str]:
    names = list(FIXED_PLAYERS)
    seen = {normalize_name(name)[1] for name in names}
    extras = [row[0] for row in db.session.query(Enrollment.name).distinct().all()]
    extras += [row[0] for row in db.session.query(User.name).distinct().all()]
    for raw in extras:
        canon = canonical_player(raw) or raw
        key = normalize_name(canon)[1]
        if key and key not in seen:
            seen.add(key)
            names.append(canon)
    return names


def attendance_stats() -> dict:
    """Arrival and court-booker history for finished games."""
    spark_max = 16
    names = known_stat_names()
    tallies = {
        name: {
            "name": name,
            "arrived": 0,
            "missed": 0,
            "booked": 0,
            "arrival_history": [],
            "booker_history": [],
        }
        for name in names
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
            booker_id, booker_name = resolve_booker(settings, [
                {"id": row.id, "name": roster_by_id[row.id]}
                for row in rows
                if row.id in roster_by_id
            ])
            if booker_name:
                booker_name = canonical_player(booker_name) or booker_name
            finished.append((week_key, slot, arrived_names, booker_name))

    finished.sort(key=lambda item: (item[0], item[1]))
    for _week_key, _slot, arrived_names, booker_name in finished:
        for name in names:
            row = tallies[name]
            arrived = name in arrived_names
            row["arrived" if arrived else "missed"] += 1
            row["arrival_history"].append(1 if arrived else 0)
            booked = booker_name == name
            if booked:
                row["booked"] += 1
            row["booker_history"].append(1 if booked else 0)

    players = []
    for name in names:
        row = tallies[name]
        total = row["arrived"] + row["missed"]
        row["not_booked"] = max(total - row["booked"], 0)
        if len(row["arrival_history"]) > spark_max:
            row["arrival_history"] = row["arrival_history"][-spark_max:]
            row["booker_history"] = row["booker_history"][-spark_max:]
        players.append(row)
    return {"games": len(finished), "players": players}


def my_stats(me: User | None) -> dict | None:
    """Personal attendance, payments, and court bookings for the logged-in player."""
    if not me:
        return None
    my_name = canonical_player(me.name) or me.name
    created = me.created_at
    if created and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    arrived = 0
    missed = 0
    booked = 0
    paid_total = 0.0
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
            settings = GameSettings.query.filter_by(slot=slot, week_key=week_key).first()
            play_day = date.fromisoformat(week_key)
            raw = (getattr(settings, "game_date", None) or "").strip()
            if raw:
                try:
                    play_day = date.fromisoformat(raw)
                except ValueError:
                    pass
            kickoff = parse_game_time(getattr(settings, "game_time", None)) or GAME_TIME
            game_dt = datetime.combine(play_day, kickoff, tzinfo=TZ)
            if created and game_dt < created.astimezone(TZ):
                continue
            rows = Enrollment.query.filter_by(slot=slot, week_key=week_key, is_waitlist=False).all()
            if not rows:
                continue
            share = game_field_cost(settings) / len(rows)
            mine = next(
                (
                    row
                    for row in rows
                    if (row.user_id and row.user_id == me.id)
                    or (canonical_player(row.name) or row.name) == my_name
                ),
                None,
            )
            roster = [{"id": row.id, "name": canonical_player(row.name) or row.name} for row in rows]
            booker_id, booker_name = resolve_booker(settings, roster)
            is_booker = bool(mine and (booker_id == mine.id or booker_name == my_name))
            if mine:
                arrived += 1
                if mine.paid or is_booker:
                    paid_total += share
                if is_booker:
                    booked += 1
            else:
                missed += 1
    return {
        "arrived": arrived,
        "missed": missed,
        "booked": booked,
        "paid_total": round(paid_total, 2),
    }


def history_for_slot(slot: str, current_week_key: str, exclude: str | None = None) -> list[dict]:
    skip = {current_week_key}
    if exclude:
        skip.add(exclude)
    week_keys = [
        row[0]
        for row in (
            db.session.query(Enrollment.week_key)
            .filter(Enrollment.slot == slot, ~Enrollment.week_key.in_(skip))
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
        if settings:
            if settings.teams_json:
                teams = json.loads(settings.teams_json)
            if getattr(settings, "teams2_json", None):
                teams2 = json.loads(settings.teams2_json)
        _booker_id, booker_name = resolve_booker(settings, roster)
        n = len(roster)
        cost = game_field_cost(settings)
        history.append({
            "week_key": week_key,
            "game_at_he": week_label(week_key, settings),
            "roster": roster,
            "waiting": waiting,
            "count": n,
            "share": round(cost / n, 2) if n else None,
            "field_cost": cost,
            "location": game_location(settings),
            "nav_address": game_nav_address(settings),
            "booker_name": booker_name,
            "teams": teams,
            "teams2": teams2,
        })
    return history


def avatar_map() -> dict[int, str]:
    cached = getattr(g, "avatar_map", None)
    if cached is not None:
        return cached
    mapping = {
        user.id: user.avatar
        for user in User.query.filter(User.avatar.isnot(None)).all()
        if user.avatar
    }
    g.avatar_map = mapping
    return mapping


def serialize_player(row: Enrollment, me: User | None = None) -> dict:
    is_me = bool(me and owns_enrollment(row, me))
    return {
        "id": row.id,
        "name": canonical_player(row.name) or row.name,
        "is_waitlist": row.is_waitlist,
        "paid": row.paid,
        "user_id": row.user_id,
        "is_me": is_me,
        "avatar": avatar_map().get(row.user_id) if row.user_id else None,
        "joined_at": row.joined_at.isoformat() if row.joined_at else None,
    }


def ended_game_payload(slot: str, week_key: str, me: User | None = None) -> dict:
    play_day = date.fromisoformat(week_key)
    settings = GameSettings.query.filter_by(slot=slot, week_key=week_key).first()
    raw = (getattr(settings, "game_date", None) or "").strip()
    if raw:
        try:
            play_day = date.fromisoformat(raw)
        except ValueError:
            play_day = date.fromisoformat(week_key)
    kickoff = parse_game_time(getattr(settings, "game_time", None)) or GAME_TIME
    clocks = kickoff_bundle(play_day, kickoff)
    game_dt = clocks["game_dt"]
    game_end_dt = clocks["game_end_dt"]
    players = players_payload(slot, week_key, True, True, me)
    return {
        "slot": slot,
        "label_he": DAYS_HE[play_day.weekday()],
        "week_key": week_key,
        "game_date": play_day.isoformat(),
        "date_override": play_day.isoformat() != week_key,
        "game_time": kickoff.strftime("%H:%M"),
        "time_override": kickoff != GAME_TIME,
        "prev_week_key": None,
        "game_at": game_dt.isoformat(),
        "game_end_at": game_end_dt.isoformat(),
        "open_at": None,
        "draw_at": None,
        "rematch_at": None,
        "game_at_he": format_dt_he(game_dt),
        "game_end_at_he": format_dt_he(game_end_dt),
        "open_at_he": None,
        "draw_at_he": None,
        "rematch_at_he": None,
        "is_open": False,
        "is_past": True,
        "is_ended": True,
        "teams_ready": True,
        "rematch_ready": True,
        "status_he": "המשחק הסתיים",
        "status_detail": "הרשימה נשמרת",
        "max_players": MAX_PLAYERS,
        **players,
        "history": [],
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


def _provided_cron_secret() -> str:
    header = (request.headers.get("X-Cron-Secret") or "").strip()
    if header:
        return header
    auth = (request.headers.get("Authorization") or "").strip()
    if auth:
        kind, _, rest = auth.partition(" ")
        if kind.lower() == "bearer" and rest.strip():
            return rest.strip()
        return auth
    return (request.args.get("secret") or "").strip()


def _cron_authorized() -> bool:
    expected = os.environ.get("CRON_SECRET", "").strip()
    provided = _provided_cron_secret()
    if not expected:
        return not os.environ.get("RENDER")
    if not provided:
        return False
    return hmac.compare_digest(provided, expected)


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
        state = get_slot_state(slot, now, load_date_overrides())
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
        message = build_pay_message(
            state["label_he"], players["share"], names, players.get("field_cost")
        )
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
    overrides = load_date_overrides()
    times = load_time_overrides()
    if not hour_before_is_due(now, force=force, date_overrides=overrides, time_overrides=times):
        return {"ok": True, "sent": [], "skipped": [{"reason": "not_due"}]}
    slot = None
    state = None
    for key in ("sunday", "wednesday"):
        candidate = get_slot_state(key, now, overrides, times)
        game_day = datetime.fromisoformat(candidate["game_at"]).astimezone(TZ).date()
        if game_day == now.date() and not candidate["is_ended"]:
            slot = key
            state = candidate
            break
    if not slot and force:
        slot = "sunday"
        state = get_slot_state(slot, now, overrides, times)
    if not slot:
        return {"ok": True, "sent": [], "skipped": [{"reason": "not_match_day"}]}
    already = HourBeforeLog.query.filter_by(slot=slot, week_key=state["week_key"]).first()
    if already and not force:
        return {"ok": True, "sent": [], "skipped": [{"slot": slot, "reason": "already_sent"}]}
    time_he = datetime.fromisoformat(state["game_at"]).astimezone(TZ).strftime("%H:%M")
    message = build_hour_before_message(state["label_he"], time_he)
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
    me = current_user()
    debt = unpaid_debt(me)
    overrides = load_date_overrides()
    upcoming_games = []
    ended_games = []
    for slot in ("sunday", "wednesday"):
        state = sync_slot(slot)
        players = players_payload(
            slot, state["week_key"], state["teams_ready"], state.get("rematch_ready", False), me
        )
        upcoming_games.append({
            **state,
            **players,
            "history": history_for_slot(slot, state["week_key"], exclude=state.get("prev_week_key")),
        })
        prev = state.get("prev_week_key")
        if prev:
            ended_games.append(ended_game_payload(slot, prev, me))
    upcoming_games.sort(key=lambda game: game["game_at"])
    ended_games.sort(key=lambda game: game["game_at"], reverse=True)
    if debt:
        have = {(game["slot"], game["week_key"]) for game in upcoming_games + ended_games}
        if (debt["slot"], debt["week_key"]) not in have:
            ended_games.append(ended_game_payload(debt["slot"], debt["week_key"], me))
            ended_games.sort(key=lambda game: game["game_at"], reverse=True)
    times = load_time_overrides()
    nxt = next_pay_reminder_at(date_overrides=overrides, time_overrides=times)
    hour_before = next_hour_before_at(date_overrides=overrides, time_overrides=times)
    match_at = todays_match_game_at(date_overrides=overrides, time_overrides=times)
    upcoming = next_game_at(date_overrides=overrides, time_overrides=times)
    target = banner_target(date_overrides=overrides, time_overrides=times)
    warning = pay_warning_text(debt)
    return {
        "now": now_il().isoformat(),
        "is_admin": bool(session.get("is_admin")),
        "user": serialize_user(me),
        "unpaid": debt,
        "pay_warning": warning,
        "persistent": PERSISTENT_DB,
        "games": upcoming_games,
        "past_games": ended_games,
        "players": FIXED_PLAYERS,
        "users": booker_users(),
        "stats": attendance_stats(),
        "my_stats": my_stats(me),
        "enrollment_open": any(game.get("is_open") for game in upcoming_games),
        "vapid_public_key": vapid_public_key(),
        "pay_reminder_at": nxt.isoformat(),
        "pay_reminder_at_he": format_dt_he(nxt),
        "hour_before_at": hour_before.isoformat(),
        "hour_before_at_he": format_dt_he(hour_before),
        "is_match_day": is_match_day(date_overrides=overrides, time_overrides=times),
        "banner_flash": banner_should_flash(date_overrides=overrides, time_overrides=times),
        "banner_mode": target["mode"],
        "banner_at": target["at"],
        "banner_at_he": target["at_he"],
        "banner_label_he": target["label_he"],
        "banner_game_at_he": target["game_at_he"],
        "match_game_at": match_at.isoformat() if match_at else None,
        "next_game_at": upcoming.isoformat(),
        "next_game_at_he": format_dt_he(upcoming),
        "next_game_label_he": DAYS_HE[upcoming.weekday()],
        "bit_phone": bit_pay_phone() or None,
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


@app.post("/api/register")
def api_register():
    data = request.get_json(silent=True) or {}
    email = normalize_email(data.get("email"))
    password = str(data.get("password") or "")
    name = canonical_player(data.get("name") or "") or " ".join(str(data.get("name") or "").split())
    if not EMAIL_RE.match(email):
        return jsonify({"ok": False, "message": "אימייל לא תקין"}), 400
    if len(password) < 6:
        return jsonify({"ok": False, "message": "הסיסמה חייבת לפחות 6 תווים"}), 400
    if not name:
        return jsonify({"ok": False, "message": "יש להזין שם"}), 400
    if name_taken(name):
        return jsonify({"ok": False, "message": "השם כבר תפוס"}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({"ok": False, "message": "האימייל כבר רשום"}), 400
    user = User(email=email, password_hash=generate_password_hash(password), name=name)
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify({"ok": False, "message": "האימייל כבר רשום"}), 400
    login_user(user)
    payload = public_state()
    payload.update({"ok": True, "message": f"נרשמת · שלום {user.name}"})
    return jsonify(payload)


@app.post("/api/login")
def api_login():
    data = request.get_json(silent=True) or {}
    email = normalize_email(data.get("email"))
    password = str(data.get("password") or "")
    if not email:
        return jsonify({"ok": False, "message": "יש להזין אימייל"}), 400
    if not EMAIL_RE.match(email):
        return jsonify({"ok": False, "message": "אימייל לא תקין"}), 400
    if not password:
        return jsonify({"ok": False, "message": "יש להזין סיסמה"}), 400
    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"ok": False, "message": "אימייל או סיסמה שגויים"}), 401
    login_user(user)
    payload = public_state()
    payload.update({"ok": True, "message": f"שלום {user.name}"})
    return jsonify(payload)


@app.post("/api/logout")
def api_logout():
    session.pop("user_id", None)
    payload = public_state()
    payload.update({"ok": True, "message": "התנתקת"})
    return jsonify(payload)


@app.post("/api/reset-password")
def api_reset_password():
    data = request.get_json(silent=True) or {}
    email = normalize_email(data.get("email"))
    if not email:
        return jsonify({"ok": False, "message": "יש להזין אימייל"}), 400
    if not EMAIL_RE.match(email):
        return jsonify({"ok": False, "message": "אימייל לא תקין"}), 400
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({"ok": False, "message": "האימייל לא נמצא"}), 404
    new_password = str(data.get("password") or data.get("new_password") or "").strip()
    generated = False
    if not new_password:
        new_password = "tm-" + secrets.token_hex(4)
        generated = True
    elif len(new_password) < 6:
        return jsonify({"ok": False, "message": "הסיסמה החדשה קצרה מדי"}), 400
    user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    login_user(user)
    payload = public_state()
    payload.update({
        "ok": True,
        "message": "הסיסמה אופסה. שמרו אותה — אין מייל אישור.",
        "new_password": new_password,
        "generated": generated,
    })
    return jsonify(payload)


@app.post("/api/me/paid")
def api_me_paid():
    user = current_user()
    if not user:
        return jsonify({"ok": False, "message": "יש להתחבר"}), 401
    data = request.get_json(silent=True) or {}
    row = db.session.get(Enrollment, data.get("id"))
    if not row or not owns_enrollment(row, user):
        return jsonify({"ok": False, "message": "אפשר לסמן תשלום רק לעצמך"}), 403
    if row.is_waitlist:
        return jsonify({"ok": False, "message": "רשימת המתנה לא משלמת"}), 400
    row.paid = True
    if row.user_id is None:
        row.user_id = user.id
    db.session.commit()
    payload = public_state()
    payload.update({"ok": True, "message": "סומן כשולם"})
    return jsonify(payload)


AVATAR_PREFIXES = ("data:image/jpeg;base64,", "data:image/png;base64,", "data:image/webp;base64,")
AVATAR_MAX_CHARS = 80_000


@app.post("/api/me/avatar")
def api_me_avatar():
    user = current_user()
    if not user:
        return jsonify({"ok": False, "message": "יש להתחבר"}), 401
    data = request.get_json(silent=True) or {}
    image = data.get("image")
    if image in (None, ""):
        user.avatar = None
        db.session.commit()
        payload = public_state()
        payload.update({"ok": True, "message": "התמונה הוסרה"})
        return jsonify(payload)
    if not isinstance(image, str) or not image.startswith(AVATAR_PREFIXES):
        return jsonify({"ok": False, "message": "יש להעלות תמונת jpg או png"}), 400
    if len(image) > AVATAR_MAX_CHARS:
        return jsonify({"ok": False, "message": "התמונה גדולה מדי"}), 400
    user.avatar = image
    db.session.commit()
    payload = public_state()
    payload.update({"ok": True, "message": "התמונה עודכנה"})
    return jsonify(payload)


@app.post("/api/join")
def api_join():
    data = request.get_json(silent=True) or {}
    slot = (data.get("slot") or "").strip()
    is_admin = bool(session.get("is_admin"))
    user = current_user()

    if slot not in ("sunday", "wednesday"):
        return jsonify({"ok": False, "message": "משחק לא תקין"}), 400

    if user:
        name = user.name
        user_id = user.id
        if not is_admin:
            debt = unpaid_debt(user)
            if debt:
                warning = pay_warning_text(debt)
                payload = public_state()
                payload.update({"ok": False, "message": warning, "pay_warning": warning})
                return jsonify(payload), 400
    elif is_admin:
        name = canonical_player(data.get("name") or "") or " ".join(str(data.get("name") or "").split())
        user_id = None
        if not name:
            return jsonify({"ok": False, "message": "יש להזין שם"}), 400
    else:
        return jsonify({"ok": False, "message": "יש להתחבר כדי להירשם"}), 401

    _, name_key = normalize_name(name)

    state = sync_slot(slot)
    if not state["is_open"] and not is_admin:
        return jsonify({"ok": False, "message": "ההרשמה סגורה כרגע"}), 400

    existing = Enrollment.query.filter_by(
        slot=slot, week_key=state["week_key"], name_key=name_key
    ).first()
    if existing:
        if existing.user_id is None and user_id:
            existing.user_id = user_id
            db.session.commit()
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
        user_id=user_id,
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


@app.post("/api/leave")
def api_leave():
    user = current_user()
    if not user:
        return jsonify({"ok": False, "message": "יש להתחבר"}), 401
    data = request.get_json(silent=True) or {}
    slot = (data.get("slot") or "").strip()
    if slot not in ("sunday", "wednesday"):
        return jsonify({"ok": False, "message": "משחק לא תקין"}), 400
    state = sync_slot(slot)
    if not state["is_open"]:
        return jsonify({"ok": False, "message": "אפשר לבטל הרשמה רק כשההרשמה פתוחה"}), 400
    rows = Enrollment.query.filter_by(slot=slot, week_key=state["week_key"]).all()
    row = next((item for item in rows if owns_enrollment(item, user)), None)
    if not row:
        return jsonify({"ok": False, "message": "אתה לא רשום למשחק"}), 400
    was_waitlist = row.is_waitlist
    name = row.name
    settings = GameSettings.query.filter_by(slot=slot, week_key=state["week_key"]).first()
    if settings and settings.booker_id == row.id:
        settings.booker_id = None
        settings.booker_custom = None
    db.session.delete(row)
    db.session.flush()
    promoted = None
    if not was_waitlist:
        promoted = _promote_first_waitlisted(slot, state["week_key"])
    db.session.commit()
    message = "ההרשמה בוטלה"
    if promoted:
        message += f" · {promoted} עלה מההמתנה"
    payload = public_state()
    payload.update({"ok": True, "message": message})
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


TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def resolve_admin_game(data: dict) -> tuple[str, str, bool] | tuple[None, str, int]:
    slot = (data.get("slot") or "").strip()
    if slot not in ("sunday", "wednesday"):
        return None, "משחק לא תקין", 400
    current = sync_slot(slot)
    raw_week = " ".join(str(data.get("week_key") or "").split())
    if not raw_week or raw_week == current["week_key"]:
        return slot, current["week_key"], True
    try:
        date.fromisoformat(raw_week)
    except ValueError:
        return None, "שבוע לא תקין", 400
    return slot, raw_week, False


def parse_admin_cost(raw) -> int | None | bool:
    if raw in (None, ""):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return False
    if value < 1 or value > 999:
        return False
    return value


def apply_game_settings(settings: GameSettings, slot: str, week_key: str, data: dict, is_current: bool):
    scheduled = date.fromisoformat(week_key)
    chosen = date.fromisoformat(settings.game_date) if settings.game_date else scheduled
    kickoff = parse_game_time(settings.game_time) or GAME_TIME

    if "date" in data:
        raw = " ".join(str(data.get("date") or "").split())
        if not raw or raw == week_key:
            settings.game_date = None
            chosen = scheduled
        else:
            try:
                chosen = date.fromisoformat(raw)
            except ValueError:
                return "תאריך לא תקין", 400
            if abs((chosen - scheduled).days) > 21:
                return "אפשר להזיז את המשחק עד 21 יום", 400
            if is_current:
                other = "wednesday" if slot == "sunday" else "sunday"
                other_day = date.fromisoformat(sync_slot(other)["game_date"])
                if chosen == other_day:
                    return "התאריך תפוס על ידי המשחק השני", 400
            settings.game_date = chosen.isoformat()

    if "time" in data:
        raw_time = " ".join(str(data.get("time") or "").split())
        if not raw_time or raw_time[:5] == "20:00":
            settings.game_time = None
            kickoff = GAME_TIME
        else:
            stamp = raw_time[:5]
            if not TIME_RE.match(stamp):
                return "שעה לא תקינה", 400
            settings.game_time = stamp
            kickoff = datetime.strptime(stamp, "%H:%M").time()

    if is_current and now_il() >= end_dt_for(chosen, kickoff):
        return "אי אפשר לבחור מועד שכבר הסתיים", 400

    if "location" in data:
        loc = " ".join(str(data.get("location") or "").split())
        settings.location = loc[:120].strip() or None

    if "nav_address" in data:
        addr = " ".join(str(data.get("nav_address") or "").split())
        settings.nav_address = addr[:200].strip() or None

    if "field_cost" in data:
        cost = parse_admin_cost(data.get("field_cost"))
        if cost is False:
            return "מחיר לא תקין", 400
        settings.field_cost = None if cost in (None, FIELD_COST_NIS) else cost

    return None, None


def settings_message(settings: GameSettings, week_key: str) -> str:
    play_day = date.fromisoformat(settings.game_date) if settings.game_date else date.fromisoformat(week_key)
    kickoff = parse_game_time(settings.game_time) or GAME_TIME
    when = format_dt_he(datetime.combine(play_day, kickoff, tzinfo=TZ))
    bits = [when]
    if settings.location:
        bits.append(settings.location)
    if settings.field_cost:
        bits.append(f"{settings.field_cost} ₪")
    return "המגרש עודכן · " + " · ".join(bits)


@app.post("/api/admin/game-date")
@admin_required
def admin_game_date():
    data = request.get_json(silent=True) or {}
    resolved = resolve_admin_game(data)
    if resolved[0] is None:
        return jsonify({"ok": False, "message": resolved[1]}), resolved[2]
    slot, week_key, is_current = resolved
    settings = get_settings(slot, week_key)
    error, status = apply_game_settings(settings, slot, week_key, {"date": data.get("date")}, is_current)
    if error:
        db.session.rollback()
        return jsonify({"ok": False, "message": error}), status
    db.session.commit()
    clear_date_overrides_cache()
    payload = public_state()
    if settings.game_date:
        play_day = date.fromisoformat(settings.game_date)
        kickoff = parse_game_time(settings.game_time) or GAME_TIME
        payload.update({"ok": True, "message": f"המשחק עבר ל־{format_dt_he(datetime.combine(play_day, kickoff, tzinfo=TZ))}"})
    else:
        payload.update({"ok": True, "message": "תאריך המשחק חזר לברירת המחדל"})
    return jsonify(payload)


@app.post("/api/admin/game-settings")
@admin_required
def admin_game_settings():
    data = request.get_json(silent=True) or {}
    resolved = resolve_admin_game(data)
    if resolved[0] is None:
        return jsonify({"ok": False, "message": resolved[1]}), resolved[2]
    slot, week_key, is_current = resolved
    settings = get_settings(slot, week_key)
    reset = bool(data.get("reset"))
    payload_fields = (
        {"date": "", "time": "", "location": "", "nav_address": "", "field_cost": ""}
        if reset
        else data
    )
    error, status = apply_game_settings(settings, slot, week_key, payload_fields, is_current)
    if error:
        db.session.rollback()
        return jsonify({"ok": False, "message": error}), status
    db.session.commit()
    clear_date_overrides_cache()
    payload = public_state()
    if reset or (
        not settings.game_date
        and not settings.game_time
        and not settings.location
        and not settings.nav_address
        and settings.field_cost is None
    ):
        payload.update({"ok": True, "message": "פרטי המגרש חזרו לברירת המחדל"})
    else:
        payload.update({"ok": True, "message": settings_message(settings, week_key)})
    return jsonify(payload)


def resolve_booker_week(data: dict) -> tuple[str, str, bool] | tuple[None, str, int]:
    slot = (data.get("slot") or "").strip()
    if slot not in ("sunday", "wednesday"):
        return None, "משחק לא תקין", 400
    current = sync_slot(slot)
    raw_week = " ".join(str(data.get("week_key") or "").split())
    if not raw_week or raw_week == current["week_key"]:
        return slot, current["week_key"], bool(current.get("is_ended"))
    try:
        date.fromisoformat(raw_week)
    except ValueError:
        return None, "שבוע לא תקין", 400
    return slot, raw_week, True


@app.post("/api/booker")
def api_booker():
    is_admin = bool(session.get("is_admin"))
    if not current_user() and not is_admin:
        return jsonify({"ok": False, "message": "יש להתחבר כדי לבחור מזמין"}), 401
    data = request.get_json(silent=True) or {}
    resolved = resolve_booker_week(data)
    if resolved[0] is None:
        return jsonify({"ok": False, "message": resolved[1]}), resolved[2]
    slot, week_key, is_ended = resolved
    if is_ended and not is_admin:
        return jsonify({"ok": False, "message": "אפשר לבחור מזמין רק למשחק שעוד לא הסתיים"}), 403

    settings = get_settings(slot, week_key)
    raw_user = data.get("user_id")
    if raw_user not in (None, "", False):
        try:
            user_id = int(raw_user)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "message": "יש לבחור שחקן"}), 400
        user = db.session.get(User, user_id)
        if not user:
            return jsonify({"ok": False, "message": "המשתמש לא נמצא"}), 404
        display = canonical_player(user.name) or user.name
        row = Enrollment.query.filter_by(
            slot=slot, week_key=week_key, user_id=user.id, is_waitlist=False
        ).first()
        if not row:
            _, name_key = normalize_name(user.name)
            row = Enrollment.query.filter_by(
                slot=slot, week_key=week_key, name_key=name_key, is_waitlist=False
            ).first()
        settings.booker_id = row.id if row else None
        settings.booker_custom = None if row else display
        db.session.commit()
        payload = public_state()
        payload.update({"ok": True, "message": f"{display} יזמין את המגרש"})
        return jsonify(payload)

    player_id = data.get("player_id")
    if player_id in ("", False):
        player_id = None
    if player_id is not None:
        try:
            player_id = int(player_id)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "message": "יש לבחור שחקן"}), 400
    custom = " ".join(str(data.get("name") or "").split())
    if len(custom) > 80:
        custom = custom[:80].strip()

    if player_id:
        row = db.session.get(Enrollment, player_id)
        if (
            not row
            or row.slot != slot
            or row.week_key != week_key
            or row.is_waitlist
        ):
            return jsonify({"ok": False, "message": "יש לבחור שחקן שנרשם למשחק"}), 400
        settings.booker_id = row.id
        settings.booker_custom = None
        db.session.commit()
        payload = public_state()
        payload.update({"ok": True, "message": f"{row.name} יזמין את המגרש"})
        return jsonify(payload)

    if custom:
        display = canonical_player(custom) or custom
        roster = Enrollment.query.filter_by(
            slot=slot, week_key=week_key, is_waitlist=False
        ).all()
        match = next(
            (row for row in roster if (canonical_player(row.name) or row.name) == display),
            None,
        )
        settings.booker_id = match.id if match else None
        settings.booker_custom = None if match else display
        db.session.commit()
        payload = public_state()
        payload.update({"ok": True, "message": f"{display} יזמין את המגרש"})
        return jsonify(payload)

    settings.booker_id = None
    settings.booker_custom = None
    db.session.commit()
    payload = public_state()
    payload.update({"ok": True, "message": "בוטל מזמין המגרש"})
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


def _cron_force() -> bool:
    body = request.get_json(silent=True) or {}
    return request.args.get("force") == "1" or bool(body.get("force"))


@app.route("/api/cron/pay-reminder", methods=["GET", "POST"])
def cron_pay_reminder():
    if not _cron_authorized():
        return jsonify({"ok": False, "message": "אין הרשאה"}), 401
    force = _cron_force()
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


@app.route("/api/cron/hour-before", methods=["GET", "POST"])
def cron_hour_before():
    if not _cron_authorized():
        return jsonify({"ok": False, "message": "אין הרשאה"}), 401
    hour = run_hour_before_reminders(force=_cron_force())
    result = {
        "ok": True,
        "sent": list(hour.get("sent") or []),
        "skipped": list(hour.get("skipped") or []),
        "hour_before": hour,
    }
    if result["sent"]:
        result["message"] = result["sent"][0]["body"]
    else:
        result["message"] = "אין תזכורת כרגע"
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
