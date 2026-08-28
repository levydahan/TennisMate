"""Israel-time game schedule and enrollment windows."""

from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import random

TZ = ZoneInfo("Asia/Jerusalem")
GAME_TIME = time(20, 0)
DRAW_TIME = time(19, 59)
ENROLL_OPEN_TIME = time(21, 30)
MAX_PLAYERS = 6
FIELD_COST_NIS = 60
TEAM_LETTERS = "אבגדהו"

DAYS_HE = [
    "יום שני",
    "יום שלישי",
    "יום רביעי",
    "יום חמישי",
    "יום שישי",
    "יום שבת",
    "יום ראשון",
]

SLOTS = {
    "sunday": {
        "weekday": 6,
        "open_days_before": 3,
        "label_he": "יום ראשון",
    },
    "wednesday": {
        "weekday": 2,
        "open_days_before": 2,
        "label_he": "יום רביעי",
    },
}


def now_il() -> datetime:
    return datetime.now(TZ)


def format_dt_he(dt: datetime) -> str:
    return f"{DAYS_HE[dt.weekday()]} {dt.strftime('%d.%m.%Y')} בשעה {dt.strftime('%H:%M')}"


def draw_teams(players: list, rng: random.Random | None = None) -> list[dict]:
    """Shuffle players and pair them into teams of 2. A leftover player is a team of 1."""
    rng = rng or random.Random()
    shuffled = list(players)
    rng.shuffle(shuffled)
    teams = []
    i = 0
    while i < len(shuffled):
        chunk = shuffled[i : i + 2]
        teams.append({
            "label": f"קבוצה {TEAM_LETTERS[len(teams)]}",
            "players": chunk,
        })
        i += 2
    return teams


def get_slot_state(slot_key: str, now: datetime | None = None) -> dict:
    """Return the visible game cycle for a slot.

    Enrollment:
      Sunday game    — Thursday 21:30 until Sunday 20:00
      Wednesday game — Monday 21:30 until Wednesday 20:00

    The roster stays visible after the game, and is cleared when the next
    enrollment window opens (new week_key).
    """
    if slot_key not in SLOTS:
        raise ValueError(f"unknown slot: {slot_key}")

    now = now_il() if now is None else now
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)

    spec = SLOTS[slot_key]
    game_weekday = spec["weekday"]

    days_ahead = (game_weekday - now.weekday()) % 7
    this_week_date = now.date() + timedelta(days=days_ahead)
    this_week_dt = datetime.combine(this_week_date, GAME_TIME, tzinfo=TZ)

    if now >= this_week_dt:
        next_date = this_week_date + timedelta(days=7)
        next_dt = this_week_dt + timedelta(days=7)
    else:
        next_date = this_week_date
        next_dt = this_week_dt

    next_open = datetime.combine(
        next_date - timedelta(days=spec["open_days_before"]),
        ENROLL_OPEN_TIME,
        tzinfo=TZ,
    )

    if now >= next_open:
        week_date = next_date
        game_dt = next_dt
        open_dt = next_open
        is_open = now < next_dt
        is_past = False
    else:
        week_date = next_date - timedelta(days=7)
        game_dt = next_dt - timedelta(days=7)
        open_dt = next_open
        is_open = False
        is_past = now >= game_dt

    draw_dt = datetime.combine(week_date, DRAW_TIME, tzinfo=TZ)
    teams_ready = now >= draw_dt

    if is_open:
        status_he = "ההרשמה פתוחה"
        status_detail = f"פתוחה עד {format_dt_he(game_dt)}"
    elif is_past:
        status_he = "המשחק הסתיים"
        status_detail = f"הרשימה תתאפס ב־{format_dt_he(open_dt)}"
    else:
        status_he = "ההרשמה סגורה"
        status_detail = f"תיפתח ב־{format_dt_he(open_dt)}"

    return {
        "slot": slot_key,
        "label_he": spec["label_he"],
        "week_key": week_date.isoformat(),
        "game_at": game_dt.isoformat(),
        "open_at": open_dt.isoformat(),
        "draw_at": draw_dt.isoformat(),
        "game_at_he": format_dt_he(game_dt),
        "open_at_he": format_dt_he(open_dt),
        "draw_at_he": format_dt_he(draw_dt),
        "is_open": is_open,
        "is_past": is_past,
        "teams_ready": teams_ready,
        "status_he": status_he,
        "status_detail": status_detail,
        "max_players": MAX_PLAYERS,
        "field_cost": FIELD_COST_NIS,
    }
