import unittest
from datetime import datetime

import random

from schedule import TZ, draw_rematch, draw_teams, forbidden_pairs, get_slot_state


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

    def test_rematch_avoids_first_hour_partners(self):
        players = [{"id": i, "name": f"p{i}"} for i in range(6)]
        hour1 = [
            {"label": "א", "players": [players[0], players[1]]},
            {"label": "ב", "players": [players[2], players[3]]},
            {"label": "ג", "players": [players[4], players[5]]},
        ]
        hour2 = draw_rematch(players, hour1, random.Random(4))
        self.assertEqual(len(hour2), 3)
        self.assertEqual(forbidden_pairs(hour1) & forbidden_pairs(hour2), set())

    def test_two_players_must_repeat(self):
        players = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        hour1 = draw_teams(players, random.Random(1))
        hour2 = draw_rematch(players, hour1, random.Random(2))
        self.assertEqual(forbidden_pairs(hour1), forbidden_pairs(hour2))

    def test_rematch_ready_at_2100(self):
        before = get_slot_state("sunday", datetime(2026, 8, 30, 20, 59, tzinfo=TZ))
        self.assertTrue(before["teams_ready"])
        self.assertFalse(before["rematch_ready"])
        after = get_slot_state("sunday", datetime(2026, 8, 30, 21, 0, tzinfo=TZ))
        self.assertTrue(after["rematch_ready"])


class PayReminderScheduleTests(unittest.TestCase):
    def test_due_at_2101_after_game(self):
        from reminders import next_pay_reminder_at, reminder_is_due

        before = datetime(2026, 8, 30, 21, 0, tzinfo=TZ)
        state = get_slot_state("sunday", before)
        self.assertTrue(state["is_past"])
        self.assertFalse(reminder_is_due(state, before))

        after = datetime(2026, 8, 30, 21, 1, tzinfo=TZ)
        state = get_slot_state("sunday", after)
        self.assertTrue(reminder_is_due(state, after))

        nxt = next_pay_reminder_at(datetime(2026, 8, 28, 14, 0, tzinfo=TZ))
        self.assertEqual(nxt.hour, 21)
        self.assertEqual(nxt.minute, 1)
        self.assertEqual(nxt.weekday(), 6)


class MatchDayTests(unittest.TestCase):
    def test_sunday_and_wednesday_are_match_days(self):
        from schedule import is_match_day
        self.assertTrue(is_match_day(datetime(2026, 8, 30, 12, 0, tzinfo=TZ)))
        self.assertTrue(is_match_day(datetime(2026, 8, 26, 8, 0, tzinfo=TZ)))
        self.assertFalse(is_match_day(datetime(2026, 8, 28, 14, 0, tzinfo=TZ)))

    def test_next_game_is_soonest_sunday_or_wednesday(self):
        from schedule import next_game_at
        friday = datetime(2026, 8, 28, 14, 0, tzinfo=TZ)
        self.assertEqual(next_game_at(friday), datetime(2026, 8, 30, 20, 0, tzinfo=TZ))
        sunday_night = datetime(2026, 8, 30, 20, 1, tzinfo=TZ)
        nxt = next_game_at(sunday_night)
        self.assertEqual(nxt, datetime(2026, 9, 2, 20, 0, tzinfo=TZ))
        wed_morning = datetime(2026, 8, 26, 10, 0, tzinfo=TZ)
        self.assertEqual(next_game_at(wed_morning), datetime(2026, 8, 26, 20, 0, tzinfo=TZ))

    def test_hour_before_window(self):
        from reminders import hour_before_is_due
        sunday_1830 = datetime(2026, 8, 30, 18, 30, tzinfo=TZ)
        sunday_1900 = datetime(2026, 8, 30, 19, 0, tzinfo=TZ)
        sunday_2000 = datetime(2026, 8, 30, 20, 0, tzinfo=TZ)
        friday = datetime(2026, 8, 28, 19, 0, tzinfo=TZ)
        self.assertFalse(hour_before_is_due(sunday_1830))
        self.assertTrue(hour_before_is_due(sunday_1900))
        self.assertFalse(hour_before_is_due(sunday_2000))
        self.assertFalse(hour_before_is_due(friday))


if __name__ == "__main__":
    unittest.main()
