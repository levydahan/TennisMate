"""History-aware team selection for 5 or 6 players.

Pairs are chosen so that teammates who played together recently are avoided:
each candidate is scored by (blocked teammates, repeats in the last
``cooldown_sessions``, repeats in the last ``window_sessions``, how recently the
most recent repeat happened) and the lowest score wins. Ties are broken randomly.
"""

import itertools
import random
from typing import Any, Iterable

Pair = tuple[str, str]


def get_all_partitions(players: list[str]):
    """Yield every way to split an even-sized player list into pairs."""
    if not players:
        yield []
        return
    first = players[0]
    for i in range(1, len(players)):
        pair = tuple(sorted((first, players[i])))
        remaining = players[1:i] + players[i + 1 :]
        for rest in get_all_partitions(remaining):
            yield [pair] + rest


def _extract_pair_stats(
    players: list[str],
    history: list[dict[str, Any]],
    cooldown_sessions: int,
    window_sessions: int,
) -> tuple[dict[Pair, int], dict[Pair, int], dict[Pair, int]]:
    """Scan history and return three metrics for every possible pair:

    1. times paired in the last ``cooldown_sessions`` sessions (default 2)
    2. times paired in the last ``window_sessions`` sessions (default 5)
    3. index of the latest session they played together (-1 if never)
    """
    sorted_history = sorted(history, key=lambda s: s["date"])
    total = len(sorted_history)
    cooldown_start = total - cooldown_sessions if cooldown_sessions > 0 else total
    window_start = total - window_sessions if window_sessions > 0 else total

    all_possible_pairs = [tuple(sorted(p)) for p in itertools.combinations(players, 2)]
    count_cooldown = {p: 0 for p in all_possible_pairs}
    count_window = {p: 0 for p in all_possible_pairs}
    last_seen_idx = {p: -1 for p in all_possible_pairs}

    for idx, session in enumerate(sorted_history):
        for p1, p2 in session["pairs"]:
            pair = tuple(sorted((p1, p2)))
            if pair in last_seen_idx:
                last_seen_idx[pair] = idx
                if idx >= cooldown_start:
                    count_cooldown[pair] += 1
                if idx >= window_start:
                    count_window[pair] += 1

    return count_cooldown, count_window, last_seen_idx


def _score(
    pairs: Iterable[Pair],
    count_cooldown: dict[Pair, int],
    count_window: dict[Pair, int],
    last_seen_idx: dict[Pair, int],
) -> tuple[int, int, int]:
    pairs = list(pairs)
    return (
        sum(count_cooldown[p] for p in pairs),
        sum(count_window[p] for p in pairs),
        max((last_seen_idx[p] for p in pairs), default=-1),
    )


def _best(options: list[tuple[tuple, Any]], rng: random.Random):
    best_score = min(score for score, _ in options)
    return rng.choice([item for score, item in options if score == best_score])


def generate_tennis_teams(
    today_players: list[str],
    history: list[dict[str, Any]],
    cooldown_sessions: int = 2,
    window_sessions: int = 5,
    rng: random.Random | None = None,
) -> dict[str, Any]:
    """Pick teams using the pair history.

    - 6 players: 3 pairs for hour 1 + 3 entirely different pairs for hour 2.
    - 5 players: 2 opening pairs + 1 player who waits outside first.

    ``history`` is a list of ``{"date": ..., "pairs": [(a, b), ...]}``.
    """
    num_players = len(today_players)
    if num_players not in (5, 6):
        raise ValueError(f"Only 5 or 6 players are supported (got {num_players}).")
    rng = rng or random.Random()

    count_cooldown, count_window, last_seen_idx = _extract_pair_stats(
        today_players, history, cooldown_sessions, window_sessions
    )

    def score(pairs):
        return _score(pairs, count_cooldown, count_window, last_seen_idx)

    if num_players == 6:
        all_rounds = list(get_all_partitions(today_players))
        evenings = []
        for hour1 in all_rounds:
            set_h1 = set(hour1)
            for hour2 in all_rounds:
                if set_h1.isdisjoint(hour2):
                    evenings.append((score(hour1 + hour2), (hour1, hour2)))
        chosen_h1, chosen_h2 = _best(evenings, rng)
        return {"mode": "6_players", "hour_1": chosen_h1, "hour_2": chosen_h2}

    options = []
    for bench_player in today_players:
        active_4 = [p for p in today_players if p != bench_player]
        for opening_pairs in get_all_partitions(active_4):
            options.append((score(opening_pairs), (opening_pairs, bench_player)))
    chosen_opening, waiting_player = _best(options, rng)
    return {
        "mode": "5_players",
        "opening_pairs": chosen_opening,
        "waiting_first": waiting_player,
    }


def generate_second_hour(
    today_players: list[str],
    hour1_pairs: list[Pair],
    history: list[dict[str, Any]],
    cooldown_sessions: int = 2,
    window_sessions: int = 5,
    rng: random.Random | None = None,
) -> list[Pair]:
    """Pick the 3 hour-2 pairs (6 players only) given the hour-1 pairs.

    Hour 2 never repeats an hour-1 pair. The whole evening (hour 1 + hour 2) is
    scored with the same key as ``generate_tennis_teams``; because the best
    evening is the best hour-2 for its own hour 1, this keeps the result
    identical to choosing the evening in one step.
    """
    if len(today_players) != 6:
        raise ValueError("A second hour is only generated for 6 players.")
    rng = rng or random.Random()
    count_cooldown, count_window, last_seen_idx = _extract_pair_stats(
        today_players, history, cooldown_sessions, window_sessions
    )
    hour1 = [tuple(sorted(p)) for p in hour1_pairs]
    hour1_set = set(hour1)

    options = []
    for hour2 in get_all_partitions(today_players):
        if hour1_set.isdisjoint(hour2):
            score = _score(hour1 + hour2, count_cooldown, count_window, last_seen_idx)
            options.append((score, hour2))
    return _best(options, rng)


def explain_pairs(
    players: list[str],
    pairs: list[Pair],
    history: list[dict[str, Any]],
    cooldown_sessions: int = 2,
    window_sessions: int = 5,
) -> dict[str, Any]:
    """Per-pair facts behind a draw, for showing to players.

    ``sessions_ago`` is 0 for the most recent session, 1 for the one before, and
    ``None`` when the pair has never played together.
    """
    count_cooldown, count_window, last_seen_idx = _extract_pair_stats(
        players, history, cooldown_sessions, window_sessions
    )
    total = len(history)
    items = []
    for first, second in pairs:
        key = tuple(sorted((first, second)))
        last = last_seen_idx.get(key, -1)
        items.append({
            "names": [first, second],
            "cooldown": count_cooldown.get(key, 0),
            "window": count_window.get(key, 0),
            "sessions_ago": (total - 1 - last) if last >= 0 else None,
        })
    return {
        "history_sessions": total,
        "cooldown_sessions": cooldown_sessions,
        "window_sessions": window_sessions,
        "pairs": items,
    }
