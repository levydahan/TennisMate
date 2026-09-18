"""Israel-time game schedule and enrollment windows."""

from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

import random

from players import canonical_player

TZ = ZoneInfo("Asia/Jerusalem")
GAME_TIME = time(20, 0)
DRAW_TIME = time(19, 59)
HOUR_BEFORE_TIME = time(19, 0)
REMATCH_TIME = time(21, 0)
PAY_REMIND_TIME = time(21, 1)
GAME_END_TIME = time(22, 1)
ENROLL_OPEN_TIME = time(21, 30)
ENROLL_CLOSE_TIME = time(22, 0)
MAX_PLAYERS = 6
FIELD_COST_NIS = 60
TEAM_LETTERS = "אבגדהו"
FORBIDDEN_TEAMMATES = (
    frozenset({"יגאל", "רועי"}),
)

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


MATCH_WEEKDAYS = {spec["weekday"] for spec in SLOTS.values()}


def is_match_day(now: datetime | None = None) -> bool:
    """True on Sunday and Wednesday in Israel time."""
    now = now_il() if now is None else now
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)
    return now.weekday() in MATCH_WEEKDAYS


def todays_match_game_at(now: datetime | None = None) -> datetime | None:
    now = now_il() if now is None else now
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)
    if not is_match_day(now):
        return None
    return datetime.combine(now.date(), GAME_TIME, tzinfo=TZ)


def next_game_at(now: datetime | None = None) -> datetime:
    """Soonest Sunday or Wednesday 20:00 that has not started yet."""
    now = now_il() if now is None else now
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)
    candidates = []
    for spec in SLOTS.values():
        days_ahead = (spec["weekday"] - now.weekday()) % 7
        dt = datetime.combine(now.date() + timedelta(days=days_ahead), GAME_TIME, tzinfo=TZ)
        if now >= dt:
            dt += timedelta(days=7)
        candidates.append(dt)
    return min(candidates)


def banner_should_flash(now: datetime | None = None) -> bool:
    """Flash only on match day until the game ends at 22:01."""
    now = now_il() if now is None else now
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)
    if not is_match_day(now):
        return False
    return now < datetime.combine(now.date(), GAME_END_TIME, tzinfo=TZ)


def banner_target(now: datetime | None = None) -> dict:
    """Yellow-banner target for the nearest upcoming game cycle.

    Before that day's enrollment opens: count down to enroll start.
    After enrollment is open: count down to kickoff (20:00).
    During 20:00–22:01: the match is in progress.
    After 22:01 the board rolls to the next cycle.
    """
    now = now_il() if now is None else now
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)

    upcoming = [get_slot_state(key, now) for key in SLOTS]
    upcoming = [item for item in upcoming if not item["is_ended"]]
    upcoming.sort(key=lambda item: item["game_at"])
    target = upcoming[0]
    base = {
        "slot": target["slot"],
        "label_he": target["label_he"],
        "game_at": target["game_at"],
        "game_at_he": target["game_at_he"],
    }
    if target["is_past"] and not target["is_ended"]:
        return {**base, "mode": "in_progress", "at": target["game_at"], "at_he": target["game_at_he"]}
    if target["is_open"]:
        return {**base, "mode": "game", "at": target["game_at"], "at_he": target["game_at_he"]}
    return {**base, "mode": "enroll", "at": target["open_at"], "at_he": target["open_at_he"]}


def format_dt_he(dt: datetime) -> str:
    return f"{DAYS_HE[dt.weekday()]} {dt.strftime('%d.%m.%Y')} בשעה {dt.strftime('%H:%M')}"


def draw_teams(players: list, rng: random.Random | None = None) -> list[dict]:
    """Shuffle players and pair them into teams of 2. A leftover player is a team of 1."""
    return _pick_pairing(players, rng or random.Random())


def _pair_chunks(players: list) -> list[list]:
    chunks = []
    i = 0
    while i < len(players):
        chunks.append(players[i : i + 2])
        i += 2
    return chunks


def _chunks_to_teams(chunks: list[list]) -> list[dict]:
    teams = []
    for chunk in chunks:
        teams.append({
            "label": f"קבוצה {TEAM_LETTERS[len(teams)]}",
            "players": chunk,
        })
    return teams


def _pair_key(chunk: list) -> frozenset | None:
    ids = [player["id"] for player in chunk]
    if len(ids) == 2:
        return frozenset(ids)
    return None


def forbidden_pairs(teams: list | None) -> set[frozenset]:
    keys = set()
    for team in teams or []:
        key = _pair_key(team.get("players") or [])
        if key:
            keys.add(key)
    return keys


def _player_name(player: dict) -> str:
    raw = player.get("name") or ""
    return canonical_player(raw) or raw


def _name_pair_key(chunk: list) -> frozenset | None:
    names = [_player_name(player) for player in chunk]
    if len(names) == 2:
        return frozenset(names)
    return None


def blocked_teammate_pairs(chunks: list[list]) -> int:
    return sum(
        1
        for chunk in chunks
        if (key := _name_pair_key(chunk)) and key in FORBIDDEN_TEAMMATES
    )


def _pick_pairing(players: list, rng: random.Random, hour1_teams: list | None = None) -> list[dict]:
    if len(players) < 2:
        leftover = list(players)
        rng.shuffle(leftover)
        return _chunks_to_teams(_pair_chunks(leftover))
    forbidden = forbidden_pairs(hour1_teams)
    candidates = list(generate_pairings(players))
    rng.shuffle(candidates)

    def score(chunks: list[list]) -> tuple[int, int]:
        repeats = sum(1 for chunk in chunks if (key := _pair_key(chunk)) and key in forbidden)
        return (blocked_teammate_pairs(chunks), repeats)

    return _chunks_to_teams(min(candidates, key=score))


def _even_pairings(players: list):
    if not players:
        yield []
        return
    first = players[0]
    for i in range(1, len(players)):
        partner = players[i]
        remaining = players[1:i] + players[i + 1 :]
        for rest in _even_pairings(remaining):
            yield [[first, partner]] + rest


def generate_pairings(players: list):
    players = list(players)
    n = len(players)
    if n == 0:
        yield []
        return
    if n % 2 == 1:
        for i, leftover in enumerate(players):
            rest = players[:i] + players[i + 1 :]
            for pairing in _even_pairings(rest):
                yield pairing + [[leftover]]
        return
    yield from _even_pairings(players)


def draw_rematch(players: list, hour1_teams: list | None, rng: random.Random | None = None) -> list[dict]:
    """Pair again, avoiding first-hour partners whenever any alternative exists."""
    return _pick_pairing(players, rng or random.Random(), hour1_teams)


def get_slot_state(slot_key: str, now: datetime | None = None) -> dict:
    """Return the visible upcoming game cycle for a slot.

    Enrollment windows:
      Sunday game    — Thursday 21:30 until Sunday 22:00
      Wednesday game — Monday 21:30 until Wednesday 22:00

    The displayed week rolls to the next occurrence at 22:01 Israel time.
    The just-ended week is exposed as prev_week_key.
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
    this_week_end = datetime.combine(this_week_date, GAME_END_TIME, tzinfo=TZ)

    if now >= this_week_end:
        week_date = this_week_date + timedelta(days=7)
        prev_week_date = this_week_date
    else:
        week_date = this_week_date
        prev_week_date = this_week_date - timedelta(days=7)

    game_dt = datetime.combine(week_date, GAME_TIME, tzinfo=TZ)
    game_end_dt = datetime.combine(week_date, GAME_END_TIME, tzinfo=TZ)
    enroll_close_dt = datetime.combine(week_date, ENROLL_CLOSE_TIME, tzinfo=TZ)
    open_dt = datetime.combine(
        week_date - timedelta(days=spec["open_days_before"]),
        ENROLL_OPEN_TIME,
        tzinfo=TZ,
    )
    prev_end_dt = datetime.combine(prev_week_date, GAME_END_TIME, tzinfo=TZ)

    is_open = open_dt <= now < enroll_close_dt
    is_ended = now >= game_end_dt
    is_past = now >= game_dt

    draw_dt = datetime.combine(week_date, DRAW_TIME, tzinfo=TZ)
    rematch_dt = datetime.combine(week_date, REMATCH_TIME, tzinfo=TZ)
    teams_ready = now >= draw_dt
    rematch_ready = now >= rematch_dt

    if is_open:
        status_he = "ההרשמה פתוחה"
        status_detail = f"פתוחה עד {format_dt_he(enroll_close_dt)}"
    elif is_ended:
        status_he = "המשחק הסתיים"
        status_detail = f"הרשמה חדשה ב־{format_dt_he(open_dt)}"
    elif is_past:
        status_he = "המשחק התחיל"
        status_detail = f"מסתיים ב־{format_dt_he(game_end_dt)}"
    else:
        status_he = "ההרשמה סגורה"
        status_detail = f"תיפתח ב־{format_dt_he(open_dt)}"

    return {
        "slot": slot_key,
        "label_he": spec["label_he"],
        "week_key": week_date.isoformat(),
        "prev_week_key": prev_week_date.isoformat() if now >= prev_end_dt else None,
        "game_at": game_dt.isoformat(),
        "game_end_at": game_end_dt.isoformat(),
        "open_at": open_dt.isoformat(),
        "draw_at": draw_dt.isoformat(),
        "rematch_at": rematch_dt.isoformat(),
        "game_at_he": format_dt_he(game_dt),
        "game_end_at_he": format_dt_he(game_end_dt),
        "open_at_he": format_dt_he(open_dt),
        "draw_at_he": format_dt_he(draw_dt),
        "rematch_at_he": format_dt_he(rematch_dt),
        "is_open": is_open,
        "is_past": is_past,
        "is_ended": is_ended,
        "teams_ready": teams_ready,
        "rematch_ready": rematch_ready,
        "status_he": status_he,
        "status_detail": status_detail,
        "max_players": MAX_PLAYERS,
        "field_cost": FIELD_COST_NIS,
    }
