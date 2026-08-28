import unittest
from datetime import datetime

import random

from schedule import TZ, draw_teams, get_slot_state


class SundayEnrollmentTests(unittest.TestCase):
    def test_closed_before_thursday_2130(self):
        now = datetime(2026, 8, 27, 21, 29, tzinfo=TZ)
        state = get_slot_state("sunday", now)
        self.assertFalse(state["is_open"])
        self.assertEqual(state["week_key"], "2026-08-23")

    def test_opens_thursday_2130(self):
        now = datetime(2026, 8, 27, 21, 30, tzinfo=TZ)
        state = get_slot_state("sunday", now)
        self.assertTrue(state["is_open"])
        self.assertEqual(state["week_key"], "2026-08-30")

    def test_still_open_sunday_evening(self):
        now = datetime(2026, 8, 30, 19, 59, tzinfo=TZ)
        state = get_slot_state("sunday", now)
        self.assertTrue(state["is_open"])
        self.assertTrue(state["teams_ready"])

    def test_teams_not_ready_before_1959(self):
        now = datetime(2026, 8, 30, 19, 58, tzinfo=TZ)
        state = get_slot_state("sunday", now)
        self.assertTrue(state["is_open"])
        self.assertFalse(state["teams_ready"])

    def test_closes_at_game_start(self):
        now = datetime(2026, 8, 30, 20, 0, tzinfo=TZ)
        state = get_slot_state("sunday", now)
        self.assertFalse(state["is_open"])
        self.assertTrue(state["is_past"])
        self.assertEqual(state["week_key"], "2026-08-30")


class WednesdayEnrollmentTests(unittest.TestCase):
    def test_opens_monday_2130(self):
        now = datetime(2026, 8, 24, 21, 30, tzinfo=TZ)
        state = get_slot_state("wednesday", now)
        self.assertTrue(state["is_open"])
        self.assertEqual(state["week_key"], "2026-08-26")

    def test_closed_monday_before_open(self):
        now = datetime(2026, 8, 24, 21, 29, tzinfo=TZ)
        state = get_slot_state("wednesday", now)
        self.assertFalse(state["is_open"])

    def test_closes_wednesday_2000(self):
        now = datetime(2026, 8, 26, 20, 0, tzinfo=TZ)
        state = get_slot_state("wednesday", now)
        self.assertFalse(state["is_open"])
        self.assertTrue(state["is_past"])


class TeamDrawTests(unittest.TestCase):
    def test_six_players_three_pairs(self):
        players = [{"id": i, "name": f"p{i}"} for i in range(6)]
        teams = draw_teams(players, random.Random(1))
        self.assertEqual(len(teams), 3)
        self.assertTrue(all(len(team["players"]) == 2 for team in teams))
        self.assertEqual({p["id"] for team in teams for p in team["players"]}, set(range(6)))

    def test_five_players_has_a_single(self):
        players = [{"id": i, "name": f"p{i}"} for i in range(5)]
        teams = draw_teams(players, random.Random(2))
        sizes = sorted(len(team["players"]) for team in teams)
        self.assertEqual(sizes, [1, 2, 2])

    def test_one_player_is_a_team_of_one(self):
        teams = draw_teams([{"id": 1, "name": "alone"}], random.Random(3))
        self.assertEqual(len(teams), 1)
        self.assertEqual(len(teams[0]["players"]), 1)


if __name__ == "__main__":
    unittest.main()
