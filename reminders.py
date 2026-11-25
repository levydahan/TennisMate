"""Pay-reminder copy and next 21:01 fire time (Israel)."""

from datetime import date, datetime, timedelta

from schedule import (
    COURT_BOOK_TIME,
    COURT_BOOK_WEEKDAY,
    FIELD_COST_NIS,
    HOUR_BEFORE_TIME,
    PAY_REMIND_TIME,
    SLOTS,
    TZ,
    format_dt_he,
    get_slot_state,
    now_il,
    todays_match_game_at,
)


def format_share(share) -> str:
    if share is None:
        return ""
    value = float(share)
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}"


def pay_remind_at(week_key: str) -> datetime:
    return datetime.combine(date.fromisoformat(week_key), PAY_REMIND_TIME, tzinfo=TZ)


def next_named_at(
    clock,
    now: datetime | None = None,
    date_overrides: dict | None = None,
    time_overrides: dict | None = None,
) -> datetime:
    now = now_il() if now is None else now
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)
    candidates = []
    for slot_key in SLOTS:
        state = get_slot_state(slot_key, now, date_overrides, time_overrides)
        game_at = datetime.fromisoformat(state["game_at"]).astimezone(TZ)
        if clock == HOUR_BEFORE_TIME:
            dt = game_at - timedelta(hours=1)
        elif clock == PAY_REMIND_TIME:
            dt = game_at + timedelta(hours=1, minutes=1)
        else:
            dt = datetime.combine(game_at.date(), clock, tzinfo=TZ)
        if dt <= now:
            nxt = date.fromisoformat(state["week_key"]) + timedelta(days=7)
            dt = datetime.combine(nxt, clock, tzinfo=TZ)
        candidates.append(dt)
    return min(candidates)


def next_pay_reminder_at(
    now: datetime | None = None,
    date_overrides: dict | None = None,
    time_overrides: dict | None = None,
) -> datetime:
    return next_named_at(PAY_REMIND_TIME, now, date_overrides, time_overrides)


def next_hour_before_at(
    now: datetime | None = None,
    date_overrides: dict | None = None,
    time_overrides: dict | None = None,
) -> datetime:
    return next_named_at(HOUR_BEFORE_TIME, now, date_overrides, time_overrides)


def build_pay_message(
    label_he: str, share: float, names: list[str], field_cost: int | None = None
) -> dict:
    amount = format_share(share)
    n = len(names)
    cost = FIELD_COST_NIS if field_cost is None else field_cost
    body = (
        f"המשחק ב{label_he} הסתיים. "
        f"כל שחקן משלם {amount} ₪ "
        f"({cost} ₪ ÷ {n})."
    )
    return {
        "title": "תזכורת תשלום · טניסמייט",
        "body": body,
        "share": share,
        "share_he": f"{amount} ₪",
        "count": n,
        "names": names,
        "label_he": label_he,
    }


def reminder_is_due(state: dict, now: datetime | None = None, force: bool = False) -> bool:
    now = now_il() if now is None else now
    if force:
        return True
    if not state.get("is_past"):
        return False
    game_at = state.get("game_at")
    if game_at:
        start = datetime.fromisoformat(game_at).astimezone(TZ)
        return now >= start + timedelta(hours=1, minutes=1)
    day = date.fromisoformat(state["week_key"])
    return now >= datetime.combine(day, PAY_REMIND_TIME, tzinfo=TZ)


def hour_before_is_due(
    now: datetime | None = None,
    force: bool = False,
    date_overrides: dict | None = None,
    time_overrides: dict | None = None,
) -> bool:
    now = now_il() if now is None else now
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)
    game_at = todays_match_game_at(now, date_overrides, time_overrides)
    if force:
        return True
    if not game_at:
        return False
    ping_at = game_at - timedelta(hours=1)
    return ping_at <= now < game_at


def build_hour_before_message(label_he: str, time_he: str = "20:00") -> dict:
    return {
        "title": "המשחק בעוד שעה · טניסמייט",
        "body": f"המשחק ב{label_he} מתחיל ב־{time_he}. סמנו הגעה אם עוד לא.",
        "kind": "hour_before",
        "label_he": label_he,
    }


def next_court_book_at(now: datetime | None = None) -> datetime:
    now = now_il() if now is None else now
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)
    days_ahead = (COURT_BOOK_WEEKDAY - now.weekday()) % 7
    candidate = datetime.combine(now.date() + timedelta(days=days_ahead), COURT_BOOK_TIME, tzinfo=TZ)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def court_book_week_key(now: datetime | None = None) -> str:
    ping = next_court_book_at(now)
    # If we are currently inside Thursday's send window, use today.
    now = now_il() if now is None else now
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)
    if now.weekday() == COURT_BOOK_WEEKDAY:
        return now.date().isoformat()
    return ping.date().isoformat()


def court_book_is_due(now: datetime | None = None, force: bool = False) -> bool:
    now = now_il() if now is None else now
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)
    if force:
        return True
    if now.weekday() != COURT_BOOK_WEEKDAY:
        return False
    ping = datetime.combine(now.date(), COURT_BOOK_TIME, tzinfo=TZ)
    return ping <= now < ping + timedelta(hours=1)


def build_court_book_message() -> dict:
    return {
        "title": "הזמנת מגרש · טניסמייט",
        "body": "יום חמישי 11:00 · הזמינו עכשיו מגרש בלזוז למשחקים הקרובים.",
        "kind": "court_book",
    }
