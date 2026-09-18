import unittest
from datetime import datetime

import random

from schedule import TZ, banner_should_flash, banner_target, draw_rematch, draw_teams, forbidden_pairs, get_slot_state


class SundayEnrollmentTests(unittest.TestCase):
    def test_closed_before_thursday_2130(self):
        now = datetime(2026, 8, 27, 21, 29, tzinfo=TZ)
        state = get_slot_state("sunday", now)
        self.assertFalse(state["is_open"])
        self.assertEqual(state["week_key"], "2026-08-30")

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

    def test_still_open_after_game_start(self):
        now = datetime(2026, 8, 30, 20, 0, tzinfo=TZ)
        state = get_slot_state("sunday", now)
        self.assertTrue(state["is_open"])
        self.assertTrue(state["is_past"])
        self.assertFalse(state["is_ended"])
        self.assertEqual(state["week_key"], "2026-08-30")
        self.assertIn("22:00", state["status_detail"])

    def test_enroll_closes_at_2200(self):
        still = get_slot_state("sunday", datetime(2026, 8, 30, 21, 59, tzinfo=TZ))
        self.assertTrue(still["is_open"])
        closed = get_slot_state("sunday", datetime(2026, 8, 30, 22, 0, tzinfo=TZ))
        self.assertFalse(closed["is_open"])
        self.assertTrue(closed["is_past"])
        self.assertFalse(closed["is_ended"])

    def test_teams_not_ready_before_1959(self):
        now = datetime(2026, 8, 30, 19, 58, tzinfo=TZ)
        state = get_slot_state("sunday", now)
        self.assertTrue(state["is_open"])
        self.assertFalse(state["teams_ready"])

    def test_stays_on_same_week_until_2201(self):
        now = datetime(2026, 8, 30, 22, 0, tzinfo=TZ)
        state = get_slot_state("sunday", now)
        self.assertEqual(state["week_key"], "2026-08-30")
        self.assertTrue(state["is_past"])
        self.assertFalse(state["is_ended"])

    def test_rolls_to_next_week_at_2201(self):
        now = datetime(2026, 8, 30, 22, 1, tzinfo=TZ)
        state = get_slot_state("sunday", now)
        self.assertEqual(state["week_key"], "2026-09-06")
        self.assertEqual(state["prev_week_key"], "2026-08-30")
        self.assertFalse(state["is_open"])
        self.assertFalse(state["is_ended"])
        self.assertFalse(state["is_past"])


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

    def test_still_open_wednesday_after_kickoff(self):
        now = datetime(2026, 8, 26, 20, 0, tzinfo=TZ)
        state = get_slot_state("wednesday", now)
        self.assertTrue(state["is_open"])
        self.assertTrue(state["is_past"])

    def test_closes_wednesday_2200(self):
        now = datetime(2026, 8, 26, 22, 0, tzinfo=TZ)
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

    def test_yigal_and_roy_never_paired(self):
        names = ["לוי", "שירן", "אבירם", "יגאל", "עידן", "רועי"]
        players = [{"id": i, "name": name} for i, name in enumerate(names)]
        blocked = frozenset({"יגאל", "רועי"})
        for seed in range(40):
            hour1 = draw_teams(players, random.Random(seed))
            pairs1 = {
                frozenset(p["name"] for p in team["players"])
                for team in hour1
                if len(team["players"]) == 2
            }
            self.assertNotIn(blocked, pairs1, seed)
            hour2 = draw_rematch(players, hour1, random.Random(seed + 100))
            pairs2 = {
                frozenset(p["name"] for p in team["players"])
                for team in hour2
                if len(team["players"]) == 2
            }
            self.assertNotIn(blocked, pairs2, seed)

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
        after_end = datetime(2026, 8, 30, 22, 1, tzinfo=TZ)
        self.assertEqual(next_game_at(after_end), datetime(2026, 9, 2, 20, 0, tzinfo=TZ))

    def test_banner_stops_flashing_at_2201(self):
        sunday_afternoon = datetime(2026, 8, 30, 16, 0, tzinfo=TZ)
        sunday_after = datetime(2026, 8, 30, 22, 1, tzinfo=TZ)
        friday = datetime(2026, 8, 28, 14, 0, tzinfo=TZ)
        self.assertTrue(banner_should_flash(sunday_afternoon))
        self.assertFalse(banner_should_flash(sunday_after))
        self.assertFalse(banner_should_flash(friday))

    def test_banner_counts_to_enroll_before_window(self):
        now = datetime(2026, 8, 27, 12, 0, tzinfo=TZ)
        target = banner_target(now)
        self.assertEqual(target["mode"], "enroll")
        self.assertEqual(target["label_he"], "יום ראשון")
        self.assertIn("21:30", target["at_he"])

    def test_banner_counts_to_kickoff_after_enroll_opens(self):
        now = datetime(2026, 8, 27, 21, 30, tzinfo=TZ)
        target = banner_target(now)
        self.assertEqual(target["mode"], "game")
        self.assertEqual(target["label_he"], "יום ראשון")
        self.assertIn("20:00", target["at_he"])

    def test_banner_in_progress_during_match(self):
        now = datetime(2026, 8, 30, 20, 30, tzinfo=TZ)
        target = banner_target(now)
        self.assertEqual(target["mode"], "in_progress")
        self.assertTrue(banner_should_flash(now))

    def test_banner_after_2201_switches_to_next_enroll(self):
        now = datetime(2026, 8, 30, 22, 1, tzinfo=TZ)
        target = banner_target(now)
        self.assertEqual(target["mode"], "enroll")
        self.assertEqual(target["label_he"], "יום רביעי")
        self.assertFalse(banner_should_flash(now))

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
