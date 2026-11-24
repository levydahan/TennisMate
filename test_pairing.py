import itertools
import json
import os
import random
import unittest

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("SECRET_KEY", "test")

from pairing import (
    _extract_pair_stats,
    generate_second_hour,
    generate_tennis_teams,
    get_all_partitions,
)
from schedule import draw_rematch, draw_teams

SIX = ["אבירם", "רועי", "חן", "יגאל", "עידן", "לוי"]
FIVE = ["אבירם", "רועי", "חן", "יגאל", "לוי"]

HISTORY = [
    {"date": "2026-10-26", "pairs": [("אבירם", "רועי"), ("חן", "יגאל"), ("עידן", "לוי"),
                                      ("אבירם", "חן"), ("רועי", "עידן"), ("יגאל", "לוי")]},
    {"date": "2026-11-02", "pairs": [("אבירם", "עידן"), ("רועי", "יגאל"), ("חן", "לוי"),
                                      ("אבירם", "לוי"), ("רועי", "חן"), ("יגאל", "עידן")]},
    {"date": "2026-11-09", "pairs": [("אבירם", "רועי"), ("חן", "עידן"), ("יגאל", "לוי"),
                                      ("אבירם", "יגאל"), ("רועי", "לוי"), ("חן", "עידן")]},
    {"date": "2026-11-16", "pairs": [("אבירם", "חן"), ("רועי", "עידן"), ("יגאל", "לוי"),
                                      ("אבירם", "עידן"), ("רועי", "יגאל"), ("חן", "לוי")]},
]


def oracle_score(pairs, history):
    """Independent re-implementation of the spec's 3-tier key (dict-based, like the reference)."""
    ordered = sorted(history, key=lambda s: s["date"])
    recent2 = ordered[-2:]
    recent5 = ordered[-5:]
    cooldown = window = 0
    last = -1
    for pair in pairs:
        key = tuple(sorted(pair))
        pair_last = -1
        for idx, session in enumerate(ordered):
            if key in {tuple(sorted(p)) for p in session["pairs"]}:
                pair_last = idx
        for session in recent2:
            cooldown += sum(1 for p in session["pairs"] if tuple(sorted(p)) == key)
        for session in recent5:
            window += sum(1 for p in session["pairs"] if tuple(sorted(p)) == key)
        last = max(last, pair_last)
    return (cooldown, window, last)


def random_history(rng, players, sessions):
    history = []
    for i in range(sessions):
        shuffled = players[:]
        rng.shuffle(shuffled)
        pairs = [(shuffled[0], shuffled[1]), (shuffled[2], shuffled[3]), (shuffled[4], shuffled[5])]
        history.append({"date": f"2026-01-{i + 1:02d}", "pairs": pairs})
    rng.shuffle(history)  # input order must not matter
    return history


class PartitionAndStatsTests(unittest.TestCase):
    def test_partition_counts(self):
        self.assertEqual(len(list(get_all_partitions(SIX))), 15)
        self.assertEqual(len(list(get_all_partitions(SIX[:4]))), 3)

    def test_120_valid_evenings(self):
        rounds = list(get_all_partitions(SIX))
        evenings = [(a, b) for a in rounds for b in rounds if set(a).isdisjoint(b)]
        self.assertEqual(len(evenings), 120)

    def test_pairs_are_normalised(self):
        history = [{"date": "2026-01-01", "pairs": [("b", "a")]},
                   {"date": "2026-01-02", "pairs": [("a", "b")]}]
        cooldown, window, last = _extract_pair_stats(["a", "b", "c"], history, 2, 5)
        self.assertEqual(cooldown[("a", "b")], 2)
        self.assertEqual(window[("a", "b")], 2)
        self.assertEqual(last[("a", "b")], 1)

    def test_metrics_use_chronological_windows(self):
        sessions = [{"date": f"2026-01-{i:02d}", "pairs": [("a", "b")]} for i in range(1, 8)]
        sessions[0]["pairs"] = [("a", "c")]  # oldest session
        history = list(reversed(sessions))  # unsorted input
        cooldown, window, last = _extract_pair_stats(["a", "b", "c"], history, 2, 5)
        self.assertEqual(cooldown[("a", "b")], 2)  # last 2 sessions
        self.assertEqual(window[("a", "b")], 5)  # last 5 sessions
        self.assertEqual(last[("a", "b")], 6)  # newest index
        self.assertEqual(last[("a", "c")], 0)  # only in the oldest session
        self.assertEqual(window[("a", "c")], 0)  # outside the 5-session window
        self.assertEqual(last[("b", "c")], -1)  # never played together

    def test_players_not_attending_are_ignored(self):
        history = [{"date": "2026-01-01", "pairs": [("a", "zzz")]}]
        cooldown, _, last = _extract_pair_stats(["a", "b"], history, 2, 5)
        self.assertNotIn(("a", "zzz"), cooldown)
        self.assertEqual(last[("a", "b")], -1)


class SixPlayerTests(unittest.TestCase):
    def test_structure(self):
        res = generate_tennis_teams(SIX, HISTORY, rng=random.Random(1))
        self.assertEqual(res["mode"], "6_players")
        self.assertEqual(len(res["hour_1"]), 3)
        self.assertEqual(len(res["hour_2"]), 3)
        self.assertEqual({p for pair in res["hour_1"] for p in pair}, set(SIX))
        self.assertEqual({p for pair in res["hour_2"] for p in pair}, set(SIX))
        self.assertTrue(set(res["hour_1"]).isdisjoint(res["hour_2"]))

    def test_chosen_evening_is_optimal(self):
        rounds = list(get_all_partitions(SIX))
        for seed in range(15):
            rng = random.Random(seed)
            history = random_history(rng, SIX, rng.randint(0, 8))
            best = min(
                oracle_score(a + b, history)
                for a in rounds for b in rounds if set(a).isdisjoint(b)
            )
            res = generate_tennis_teams(SIX, history, rng=random.Random(seed))
            self.assertEqual(oracle_score(res["hour_1"] + res["hour_2"], history), best, seed)

    def test_sample_history_best_score(self):
        # The last 2 sessions cover 10 of 15 pairs, so an evening (6 pairs) must repeat one.
        for seed in range(10):
            res = generate_tennis_teams(SIX, HISTORY, rng=random.Random(seed))
            self.assertEqual(oracle_score(res["hour_1"] + res["hour_2"], HISTORY), (1, 7, 2))

    def test_zero_cooldown_repeats_when_possible(self):
        history = HISTORY[-1:]  # one session: 9 fresh pairs exist
        for seed in range(10):
            res = generate_tennis_teams(SIX, history, rng=random.Random(seed))
            self.assertEqual(oracle_score(res["hour_1"] + res["hour_2"], history)[0], 0)

    def test_ties_are_broken_randomly(self):
        seen = {
            json.dumps(generate_tennis_teams(SIX, [], rng=random.Random(seed))["hour_1"])
            for seed in range(30)
        }
        self.assertGreater(len(seen), 1)

    def test_second_hour_matches_joint_optimum(self):
        rounds = list(get_all_partitions(SIX))
        for seed in range(15):
            rng = random.Random(seed)
            history = random_history(rng, SIX, rng.randint(0, 8))
            best = min(
                oracle_score(a + b, history)
                for a in rounds for b in rounds if set(a).isdisjoint(b)
            )
            res = generate_tennis_teams(SIX, history, rng=random.Random(seed))
            hour2 = generate_second_hour(SIX, res["hour_1"], history, rng=random.Random(seed))
            self.assertEqual(oracle_score(res["hour_1"] + hour2, history), best, seed)
            self.assertTrue(set(res["hour_1"]).isdisjoint(hour2))

class FivePlayerTests(unittest.TestCase):
    def test_opening_lineup_only(self):
        res = generate_tennis_teams(FIVE, HISTORY, rng=random.Random(1))
        self.assertEqual(res["mode"], "5_players")
        self.assertNotIn("hour_1", res)
        self.assertNotIn("hour_2", res)
        self.assertEqual(len(res["opening_pairs"]), 2)
        playing = {p for pair in res["opening_pairs"] for p in pair}
        self.assertEqual(playing | {res["waiting_first"]}, set(FIVE))
        self.assertNotIn(res["waiting_first"], playing)

    def test_opening_lineup_is_optimal(self):
        for seed in range(15):
            rng = random.Random(seed)
            history = random_history(rng, FIVE + ["לוי2"], rng.randint(0, 8))
            best = min(
                oracle_score(pairs, history)
                for bench in FIVE
                for pairs in get_all_partitions([p for p in FIVE if p != bench])
            )
            res = generate_tennis_teams(FIVE, history, rng=random.Random(seed))
            self.assertEqual(oracle_score(res["opening_pairs"], history), best, seed)

    def test_rejects_other_sizes(self):
        with self.assertRaises(ValueError):
            generate_tennis_teams(SIX[:4], HISTORY)
        with self.assertRaises(ValueError):
            generate_tennis_teams(SIX + ["x"], HISTORY)


def _players(names):
    return [{"id": i, "name": name} for i, name in enumerate(names)]


def _names(teams):
    return [tuple(p["name"] for p in team["players"]) for team in teams]


class ScheduleIntegrationTests(unittest.TestCase):
    def test_draw_teams_six_uses_history(self):
        teams = draw_teams(_players(SIX), random.Random(1), HISTORY)
        self.assertEqual(len(teams), 3)
        self.assertTrue(all(len(t["players"]) == 2 for t in teams))
        hour2 = draw_rematch(_players(SIX), teams, random.Random(2), HISTORY)
        pairs = [tuple(sorted(p)) for p in _names(teams) + _names(hour2)]
        self.assertEqual(len(set(pairs)), 6)  # no pair repeated between hours
        self.assertEqual(oracle_score(pairs, HISTORY), (1, 7, 2))  # the optimum for this history

    def test_draw_teams_five_has_single_waiter(self):
        teams = draw_teams(_players(FIVE), random.Random(1), HISTORY)
        self.assertEqual(sorted(len(t["players"]) for t in teams), [1, 2, 2])
        self.assertEqual(len(teams[-1]["players"]), 1)

    def test_five_players_have_no_second_hour(self):
        players = _players(FIVE)
        teams = draw_teams(players, random.Random(1), HISTORY)
        self.assertEqual(draw_rematch(players, teams, random.Random(2), HISTORY), [])

    def test_history_avoids_recent_partners(self):
        # Everyone just played the same pairs; a new draw must not repeat them.
        recent = [{"date": "2026-01-01", "pairs": [(SIX[0], SIX[1]), (SIX[2], SIX[3]), (SIX[4], SIX[5])]}]
        for seed in range(20):
            teams = draw_teams(_players(SIX), random.Random(seed), recent)
            played = {frozenset(p) for p in _names(teams)}
            self.assertTrue(played.isdisjoint({frozenset(p) for p in recent[0]["pairs"]}), seed)

    def test_other_sizes_still_work(self):
        for n in (1, 2, 3, 4):
            teams = draw_teams(_players(SIX[:n]), random.Random(1), HISTORY)
            self.assertEqual(sum(len(t["players"]) for t in teams), n)

    def test_duplicate_names_fall_back(self):
        players = _players(["a", "a", "b", "c", "d", "e"])
        teams = draw_teams(players, random.Random(1), HISTORY)
        self.assertEqual(sum(len(t["players"]) for t in teams), 6)


class AppHistoryTests(unittest.TestCase):
    def setUp(self):
        from app import app, db

        self.app, self.db = app, db
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()

    def tearDown(self):
        self.db.session.remove()
        self.db.drop_all()
        self.ctx.pop()

    def _team(self, *names):
        return {"label": "x", "players": [{"id": i, "name": n} for i, n in enumerate(names)]}

    def test_history_comes_from_earlier_stored_draws_only(self):
        from app import GameSettings, pairing_history

        past = GameSettings(
            slot="sunday",
            week_key="2026-11-08",
            teams_json=json.dumps([self._team("אבירם", "רועי"), self._team("חן")], ensure_ascii=False),
            teams2_json=json.dumps([self._team("חן", "אבירם")], ensure_ascii=False),
        )
        current = GameSettings(
            slot="sunday",
            week_key="2026-11-15",
            teams_json=json.dumps([self._team("לוי", "עידן")], ensure_ascii=False),
        )
        self.db.session.add_all([past, current])
        self.db.session.commit()

        history = pairing_history("sunday", "2026-11-15")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["date"], "2026-11-08")
        self.assertEqual(
            sorted(tuple(sorted(p)) for p in history[0]["pairs"]),
            sorted([tuple(sorted(("אבירם", "רועי"))), tuple(sorted(("חן", "אבירם")))]),
        )  # singles are skipped, hour 2 is included

    def test_ensure_teams_end_to_end_uses_stored_history(self):
        from app import GameSettings, ensure_teams

        names = ["לוי", "שירן", "אבירם", "עידן", "חן", "מושיקו"]
        roster = [{"id": i + 1, "name": n} for i, n in enumerate(names)]
        last = [("לוי", "שירן"), ("אבירם", "עידן"), ("חן", "מושיקו")]
        self.db.session.add(
            GameSettings(
                slot="sunday",
                week_key="2026-11-08",
                teams_json=json.dumps(
                    [{"label": "x", "players": [{"id": 0, "name": a}, {"id": 1, "name": b}]} for a, b in last],
                    ensure_ascii=False,
                ),
            )
        )
        self.db.session.commit()

        hour1, hour2 = ensure_teams("sunday", "2026-11-15", roster, True, True)
        pairs1 = {frozenset(p["name"] for p in t["players"]) for t in hour1}
        pairs2 = {frozenset(p["name"] for p in t["players"]) for t in hour2}
        self.assertEqual(len(pairs1), 3)
        self.assertEqual(len(pairs2), 3)
        self.assertTrue(pairs1.isdisjoint(pairs2))
        self.assertTrue((pairs1 | pairs2).isdisjoint({frozenset(p) for p in last}))

    def test_ensure_teams_five_players_has_no_second_hour(self):
        from app import ensure_teams

        roster = [{"id": i + 1, "name": n} for i, n in enumerate(FIVE)]
        hour1, hour2 = ensure_teams("sunday", "2026-11-15", roster, True, True)
        self.assertEqual(sorted(len(t["players"]) for t in hour1), [1, 2, 2])
        self.assertEqual(hour2, [])


class SeasonSimulationTests(unittest.TestCase):
    """Many weeks through the app's own ensure_teams, storing and re-reading history."""

    def setUp(self):
        from app import app, db

        self.app, self.db = app, db
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()

    def tearDown(self):
        self.db.session.remove()
        self.db.drop_all()
        self.ctx.pop()

    @staticmethod
    def _pairs(teams):
        return {tuple(sorted(p["name"] for p in t["players"])) for t in teams if len(t["players"]) == 2}

    def _season(self, seed, weeks, use_history):
        from datetime import date, timedelta

        from app import GameSettings, ensure_teams
        from players import FIXED_PLAYERS

        # Fresh database per season: week dates and roster ids repeat across seasons.
        self.db.drop_all()
        self.db.create_all()
        rng = random.Random(seed)
        sessions = []
        for w in range(weeks):
            week_key = (date(2026, 1, 4) + timedelta(days=7 * w)).isoformat()
            n = 5 if rng.random() < 0.25 else 6
            attendees = rng.sample(FIXED_PLAYERS, n)
            roster = [{"id": i + 1, "name": name} for i, name in enumerate(attendees)]
            if use_history:
                hour1, hour2 = ensure_teams("sunday", week_key, roster, True, True)
            else:
                hour1 = draw_teams(roster, random.Random(rng.random()))
                hour2 = draw_rematch(roster, hour1, random.Random(rng.random()))
            pairs1, pairs2 = self._pairs(hour1), self._pairs(hour2 or [])
            self.assertEqual(sorted(p["name"] for t in hour1 for p in t["players"]), sorted(attendees))
            if n == 6:
                self.assertEqual((len(pairs1), len(pairs2)), (3, 3))
                self.assertTrue(pairs1.isdisjoint(pairs2), (seed, w))
            else:
                self.assertEqual(sorted(len(t["players"]) for t in hour1), [1, 2, 2])
                self.assertEqual(hour2, [])
            sessions.append(pairs1 | pairs2)
        repeats = [len(sessions[w] & (sessions[w - 1] | sessions[w - 2])) for w in range(2, weeks)]
        return sum(repeats) / len(repeats)

    def test_history_beats_random_over_a_season(self):
        algo = [self._season(seed, 30, True) for seed in range(5)]
        baseline = [self._season(seed, 30, False) for seed in range(5)]
        self.assertLess(sum(algo) / 5, sum(baseline) / 5 / 3)

    def test_stored_draw_is_stable_and_follows_roster_changes(self):
        from app import ensure_teams
        from players import FIXED_PLAYERS

        roster = [{"id": i + 1, "name": n} for i, n in enumerate(FIXED_PLAYERS[:6])]
        first = ensure_teams("sunday", "2026-03-01", roster, True, True)
        self.assertEqual(first, ensure_teams("sunday", "2026-03-01", roster, True, True))
        self.assertEqual(ensure_teams("sunday", "2026-03-01", roster, False, False), (None, None))

        changed = roster[:5] + [{"id": 99, "name": FIXED_PLAYERS[7]}]
        hour1, _ = ensure_teams("sunday", "2026-03-01", changed, True, True)
        self.assertEqual(
            sorted(p["name"] for t in hour1 for p in t["players"]),
            sorted(p["name"] for p in changed),
        )


if __name__ == "__main__":
    unittest.main()
