"""Israel-time game schedule and enrollment windows."""

from datetime import date, datetime, timedelta, time
from zoneinfo import ZoneInfo

import random

from pairing import generate_second_hour, generate_tennis_teams
from players import canonical_player

TZ = ZoneInfo("Asia/Jerusalem")
GAME_TIME = time(20, 0)
DRAW_TIME = time(12, 0)
HOUR_BEFORE_TIME = time(19, 0)
REMATCH_TIME = time(12, 0)
PAY_REMIND_TIME = time(21, 1)
GAME_END_TIME = time(22, 1)
ENROLL_OPEN_TIME = time(21, 30)
ENROLL_CLOSE_TIME = time(22, 0)
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


MATCH_WEEKDAYS = {spec["weekday"] for spec in SLOTS.values()}


def parse_game_time(raw: str | None) -> time | None:
    """Parse HH:MM. Returns None if empty or invalid."""
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value[:5], "%H:%M").time()
    except ValueError:
        return None


def end_dt_for(play_date: date, kickoff: time | None = None) -> datetime:
    """Game-end instant for a play date. Custom kickoff lasts 2h01m."""
    kickoff = kickoff or GAME_TIME
    if kickoff == GAME_TIME:
        return datetime.combine(play_date, GAME_END_TIME, tzinfo=TZ)
    return datetime.combine(play_date, kickoff, tzinfo=TZ) + timedelta(hours=2, minutes=1)


def kickoff_bundle(play_date: date, kickoff: time | None = None) -> dict:
    """Kickoff and derived clocks (draw, rematch, enroll close, end)."""
    kickoff = kickoff or GAME_TIME
    game_dt = datetime.combine(play_date, kickoff, tzinfo=TZ)
    draw_dt = datetime.combine(play_date, DRAW_TIME, tzinfo=TZ)
    rematch_dt = datetime.combine(play_date, REMATCH_TIME, tzinfo=TZ)
    if kickoff == GAME_TIME:
        return {
            "game_dt": game_dt,
            "game_end_dt": datetime.combine(play_date, GAME_END_TIME, tzinfo=TZ),
            "enroll_close_dt": datetime.combine(play_date, ENROLL_CLOSE_TIME, tzinfo=TZ),
            "draw_dt": draw_dt,
            "rematch_dt": rematch_dt,
        }
    return {
        "game_dt": game_dt,
        "game_end_dt": game_dt + timedelta(hours=2, minutes=1),
        "enroll_close_dt": game_dt + timedelta(hours=2),
        "draw_dt": draw_dt,
        "rematch_dt": rematch_dt,
    }


def is_match_day(
    now: datetime | None = None,
    date_overrides: dict | None = None,
    time_overrides: dict | None = None,
) -> bool:
    """True on a day that currently has a Sunday or Wednesday game, including reschedules."""
    now = now_il() if now is None else now
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)
    for slot_key in SLOTS:
        state = get_slot_state(slot_key, now, date_overrides, time_overrides)
        game_day = datetime.fromisoformat(state["game_at"]).astimezone(TZ).date()
        if now.date() == game_day and not state["is_ended"]:
            return True
    return False


def todays_match_game_at(
    now: datetime | None = None,
    date_overrides: dict | None = None,
    time_overrides: dict | None = None,
) -> datetime | None:
    now = now_il() if now is None else now
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)
    for slot_key in SLOTS:
        state = get_slot_state(slot_key, now, date_overrides, time_overrides)
        game_dt = datetime.fromisoformat(state["game_at"])
        if game_dt.astimezone(TZ).date() == now.date() and not state["is_ended"]:
            return game_dt
    return None


def next_game_at(
    now: datetime | None = None,
    date_overrides: dict | None = None,
    time_overrides: dict | None = None,
) -> datetime:
    """Soonest game kickoff that has not started yet."""
    now = now_il() if now is None else now
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)
    candidates = []
    for slot_key in SLOTS:
        state = get_slot_state(slot_key, now, date_overrides, time_overrides)
        game_dt = datetime.fromisoformat(state["game_at"])
        if now < game_dt:
            candidates.append(game_dt)
        else:
            nxt = date.fromisoformat(state["week_key"]) + timedelta(days=7)
            candidates.append(datetime.combine(nxt, GAME_TIME, tzinfo=TZ))
    return min(candidates)


def banner_should_flash(
    now: datetime | None = None,
    date_overrides: dict | None = None,
    time_overrides: dict | None = None,
) -> bool:
    """Flash only on match day until that game's end clock."""
    now = now_il() if now is None else now
    if now.tzinfo is None:
        now = now.replace(tzinfo=TZ)
    else:
        now = now.astimezone(TZ)
    if not is_match_day(now, date_overrides, time_overrides):
        return False
    game_at = todays_match_game_at(now, date_overrides, time_overrides)
    if not game_at:
        return False
    local = game_at.astimezone(TZ)
    kickoff = local.time().replace(second=0, microsecond=0)
    return now < end_dt_for(local.date(), kickoff)


def banner_target(
    now: datetime | None = None,
    date_overrides: dict | None = None,
    time_overrides: dict | None = None,
) -> dict:
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

    upcoming = [get_slot_state(key, now, date_overrides, time_overrides) for key in SLOTS]
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


def draw_teams(
    players: list,
    rng: random.Random | None = None,
    history: list[dict] | None = None,
) -> list[dict]:
    """Pair players into teams of 2 for the first hour.

    With 5 or 6 players the history-based algorithm in ``pairing`` is used: pairs
    that played together recently are avoided. With 5 players only the opening
    lineup is chosen (2 pairs + the single player who waits first). Any other
    head-count falls back to a random pairing. ``history`` is a list of
    ``{"date": ..., "pairs": [(name, name), ...]}``.
    """
    rng = rng or random.Random()
    by_name = _players_by_unique_name(players) if len(players) in (5, 6) else None
    if by_name is None:
        return _pick_pairing(players, rng)
    result = generate_tennis_teams(
        list(by_name), history or [], rng=rng
    )
    if result["mode"] == "6_players":
        pairs = result["hour_1"]
        chunks = [[by_name[a], by_name[b]] for a, b in pairs]
    else:
        chunks = [[by_name[a], by_name[b]] for a, b in result["opening_pairs"]]
        chunks.append([by_name[result["waiting_first"]]])
    return _chunks_to_teams(chunks)


def _players_by_unique_name(players: list) -> dict[str, dict] | None:
    """Map canonical name -> player, or None if two players share a name."""
    by_name = {}
    for player in players:
        name = _player_name(player)
        if name in by_name:
            return None
        by_name[name] = player
    return by_name


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


def _pick_pairing(players: list, rng: random.Random, hour1_teams: list | None = None) -> list[dict]:
    if len(players) < 2:
        leftover = list(players)
        rng.shuffle(leftover)
        return _chunks_to_teams(_pair_chunks(leftover))
    forbidden = forbidden_pairs(hour1_teams)
    candidates = list(generate_pairings(players))
    rng.shuffle(candidates)

    def score(chunks: list[list]) -> int:
        return sum(1 for chunk in chunks if (key := _pair_key(chunk)) and key in forbidden)

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


def draw_rematch(
    players: list,
    hour1_teams: list | None,
    rng: random.Random | None = None,
    history: list[dict] | None = None,
) -> list[dict]:
    """Second-hour teams: no first-hour partners are repeated.

    With 6 players the history-based algorithm picks 3 completely new pairs.
    With 5 players there is no second-hour draw (games rotate by results), so an
    empty list is returned. Other head-counts fall back to a random pairing that
    avoids first-hour partners whenever any alternative exists.
    """
    rng = rng or random.Random()
    if len(players) == 5:
        return []
    by_name = _players_by_unique_name(players) if len(players) == 6 else None
    if by_name is not None:
        hour1_pairs = _hour1_name_pairs(hour1_teams, set(by_name))
        if hour1_pairs is not None:
            pairs = generate_second_hour(
                list(by_name), hour1_pairs, history or [], rng=rng
            )
            return _chunks_to_teams([[by_name[a], by_name[b]] for a, b in pairs])
    return _pick_pairing(players, rng, hour1_teams)


def _hour1_name_pairs(hour1_teams: list | None, names: set[str]) -> list[tuple[str, str]] | None:
    """First-hour pairs by name, or None if they are not a full split of ``names``."""
    pairs = []
    for team in hour1_teams or []:
        members = [_player_name(player) for player in team.get("players") or []]
        if len(members) != 2:
            return None
        pairs.append((members[0], members[1]))
    flat = [name for pair in pairs for name in pair]
    if len(flat) != len(names) or set(flat) != names:
        return None
    return pairs


def get_slot_state(
    slot_key: str,
    now: datetime | None = None,
    date_overrides: dict | None = None,
    time_overrides: dict | None = None,
) -> dict:
    """Return the visible upcoming game cycle for a slot.

    Enrollment windows:
      Sunday game    — Thursday 21:30 until game day 22:00
      Wednesday game — Monday 21:30 until game day 22:00

    The displayed week rolls to the next occurrence at 22:01 Israel time.
    The just-ended week is exposed as prev_week_key.
    Managers can move a cycle to another calendar date or kickoff time;
    enrollments stay on week_key.
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
    overrides = date_overrides or {}
    times = time_overrides or {}

    def kickoff_of(week_iso: str) -> time:
        return times.get((slot_key, week_iso)) or GAME_TIME

    days_ahead = (game_weekday - now.weekday()) % 7
    this_week_date = now.date() + timedelta(days=days_ahead)
    this_actual = overrides.get((slot_key, this_week_date.isoformat()), this_week_date)
    this_week_end = end_dt_for(this_actual, kickoff_of(this_week_date.isoformat()))

    if now >= this_week_end:
        week_date = this_week_date + timedelta(days=7)
        prev_week_date = this_week_date
    else:
        week_date = this_week_date
        prev_week_date = this_week_date - timedelta(days=7)

    game_date = week_date
    prev_actual = overrides.get((slot_key, prev_week_date.isoformat()))
    if prev_actual is not None and now < end_dt_for(prev_actual, kickoff_of(prev_week_date.isoformat())):
        week_date = prev_week_date
        prev_week_date = week_date - timedelta(days=7)
        game_date = prev_actual
    else:
        cur_actual = overrides.get((slot_key, week_date.isoformat()))
        cur_kick = kickoff_of(week_date.isoformat())
        if cur_actual is not None:
            if now >= end_dt_for(cur_actual, cur_kick):
                week_date = week_date + timedelta(days=7)
                prev_week_date = week_date - timedelta(days=7)
                nxt_actual = overrides.get((slot_key, week_date.isoformat()))
                game_date = nxt_actual if nxt_actual is not None else week_date
            else:
                game_date = cur_actual

    kickoff = kickoff_of(week_date.isoformat())
    clocks = kickoff_bundle(game_date, kickoff)
    game_dt = clocks["game_dt"]
    game_end_dt = clocks["game_end_dt"]
    enroll_close_dt = clocks["enroll_close_dt"]
    draw_dt = clocks["draw_dt"]
    rematch_dt = clocks["rematch_dt"]
    open_dt = datetime.combine(
        week_date - timedelta(days=spec["open_days_before"]),
        ENROLL_OPEN_TIME,
        tzinfo=TZ,
    )
    prev_end_dt = end_dt_for(
        overrides.get((slot_key, prev_week_date.isoformat()), prev_week_date),
        kickoff_of(prev_week_date.isoformat()),
    )

    is_open = open_dt <= now < enroll_close_dt
    is_ended = now >= game_end_dt
    is_past = now >= game_dt

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
        "label_he": DAYS_HE[game_date.weekday()],
        "week_key": week_date.isoformat(),
        "game_date": game_date.isoformat(),
        "date_override": game_date != week_date,
        "game_time": kickoff.strftime("%H:%M"),
        "time_override": kickoff != GAME_TIME,
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
