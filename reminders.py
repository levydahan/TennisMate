"""Pay-reminder copy and next 21:01 fire time (Israel)."""

from datetime import date, datetime, timedelta

from schedule import (
    FIELD_COST_NIS,
    HOUR_BEFORE_TIME,
    PAY_REMIND_TIME,
    SLOTS,
    TZ,
    format_dt_he,
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


def next_named_at(clock, now: datetime | None = None) -> datetime:
    now = now_il() if now is None else now
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)
    candidates = []
    for spec in SLOTS.values():
        days_ahead = (spec["weekday"] - now.weekday()) % 7
        day = now.date() + timedelta(days=days_ahead)
        dt = datetime.combine(day, clock, tzinfo=TZ)
        if dt <= now:
            dt += timedelta(days=7)
        candidates.append(dt)
    return min(candidates)


def next_pay_reminder_at(now: datetime | None = None) -> datetime:
    return next_named_at(PAY_REMIND_TIME, now)


def next_hour_before_at(now: datetime | None = None) -> datetime:
    return next_named_at(HOUR_BEFORE_TIME, now)


def build_pay_message(label_he: str, share: float, names: list[str]) -> dict:
    amount = format_share(share)
    n = len(names)
    body = (
        f"המשחק ב{label_he} הסתיים. "
        f"כל שחקן משלם {amount} ₪ "
        f"({FIELD_COST_NIS} ₪ ÷ {n})."
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
    return now >= pay_remind_at(state["week_key"])


def hour_before_is_due(now: datetime | None = None, force: bool = False) -> bool:
    now = now_il() if now is None else now
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)
    game_at = todays_match_game_at(now)
    if force:
        return True
    if not game_at:
        return False
    ping_at = datetime.combine(now.date(), HOUR_BEFORE_TIME, tzinfo=TZ)
    return ping_at <= now < game_at


def build_hour_before_message(label_he: str) -> dict:
    return {
        "title": "המשחק בעוד שעה · טניסמייט",
        "body": f"המשחק ב{label_he} מתחיל ב־20:00. סמנו הגעה אם עוד לא.",
        "kind": "hour_before",
        "label_he": label_he,
    }
