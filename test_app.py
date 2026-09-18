import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "test"

from app import Enrollment, GameSettings, app, db
from players import FIXED_PLAYERS
from schedule import TZ


class JoinAndWaitlistTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + self.tmp.name
        app.config["TESTING"] = True
        self.ctx = app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        self.client = app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _login_admin(self):
        res = self.client.post("/api/admin/login", json={"password": "0508716669"})
        self.assertTrue(res.get_json()["ok"])

    def _game(self, data, slot="sunday", ended=False):
        pool = list(data.get("past_games") or []) if ended else list(data.get("games") or [])
        for game in pool:
            if game["slot"] == slot and bool(game.get("is_ended")) == ended:
                return game
        for game in list(data.get("games") or []) + list(data.get("past_games") or []):
            if game["slot"] == slot and bool(game.get("is_ended")) == ended:
                return game
        return None

    def test_seventh_player_goes_to_waitlist_and_promotes(self):
        self._login_admin()
        for name in FIXED_PLAYERS[:6]:
            res = self.client.post("/api/join", json={"slot": "sunday", "name": name})
            data = res.get_json()
            self.assertTrue(data["ok"], data)
            self.assertFalse(data["waitlisted"])

        waiting_name = FIXED_PLAYERS[6]
        res = self.client.post("/api/join", json={"slot": "sunday", "name": waiting_name})
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["waitlisted"])
        sunday = self._game(data, "sunday")
        self.assertEqual(len(sunday["waiting"]), 1)

        first_id = sunday["roster"][0]["id"]
        res = self.client.post("/api/admin/remove", json={"id": first_id})
        data = res.get_json()
        self.assertTrue(data["ok"])
        sunday = self._game(data, "sunday")
        names = [p["name"] for p in sunday["roster"]]
        self.assertIn(waiting_name, names)
        self.assertEqual(sunday["waiting"], [])
        self.assertEqual(sunday["share"], 10)

    def test_join_requires_login(self):
        res = self.client.post("/api/join", json={"slot": "sunday"})
        self.assertEqual(res.status_code, 401)
        self.assertFalse(res.get_json()["ok"])

    def test_player_can_leave_own_enrollment(self):
        created = self.client.post("/api/register", json={
            "email": "leave@example.com",
            "password": "secret1",
            "name": "עזיבה",
        })
        self.assertTrue(created.get_json()["ok"], created.get_json())
        self.client.post("/api/logout", json={})
        denied = self.client.post("/api/leave", json={"slot": "sunday"})
        self.assertEqual(denied.status_code, 401)
        self.client.post("/api/login", json={
            "email": "leave@example.com",
            "password": "secret1",
        })
        missing = self.client.post("/api/leave", json={"slot": "sunday"})
        self.assertEqual(missing.status_code, 400)
        joined = self.client.post("/api/join", json={"slot": "sunday"})
        data = joined.get_json()
        self.assertTrue(data["ok"], data)
        sunday = self._game(data, "sunday")
        self.assertTrue(any(p.get("is_me") for p in sunday["roster"] + sunday["waiting"]))
        left = self.client.post("/api/leave", json={"slot": "sunday"})
        left_data = left.get_json()
        self.assertTrue(left_data["ok"], left_data)
        sunday = self._game(left_data, "sunday")
        self.assertFalse(any(p.get("is_me") for p in sunday["roster"] + sunday["waiting"]))

    def test_player_can_upload_and_clear_avatar(self):
        self.client.post("/api/register", json={
            "email": "photo@example.com",
            "password": "secret1",
            "name": "תמונה",
        })
        tiny = (
            "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
            "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/2wBDAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEB"
            "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQH/wAARCAABAAEDAREAAhEBAxEB/8QAFQABAQAA"
            "AAAAAAAAAAAAAAAABv/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKwD/2Q=="
        )
        denied = self.client.post("/api/me/avatar", json={"image": "not-an-image"})
        self.assertEqual(denied.status_code, 400)
        uploaded = self.client.post("/api/me/avatar", json={"image": tiny})
        data = uploaded.get_json()
        self.assertTrue(data["ok"], data)
        self.assertTrue(data["user"]["avatar"].startswith("data:image/jpeg"))
        cleared = self.client.post("/api/me/avatar", json={"image": ""})
        self.assertTrue(cleared.get_json()["ok"])
        self.assertIsNone(cleared.get_json()["user"]["avatar"])

    def test_register_login_and_reset_password(self):
        created = self.client.post("/api/register", json={
            "email": "levi@example.com",
            "password": "secret1",
            "name": "לוי",
        })
        data = created.get_json()
        self.assertTrue(data["ok"], data)
        self.assertEqual(data["user"]["email"], "levi@example.com")
        self.client.post("/api/logout", json={})
        denied = self.client.post("/api/login", json={
            "email": "levi@example.com",
            "password": "wrong-password",
        })
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(denied.get_json()["message"], "אימייל או סיסמה שגויים")
        reset = self.client.post("/api/reset-password", json={"email": "levi@example.com"})
        reset_data = reset.get_json()
        self.assertTrue(reset_data["ok"], reset_data)
        self.assertTrue(reset_data["new_password"])
        self.client.post("/api/logout", json={})
        login = self.client.post("/api/login", json={
            "email": "levi@example.com",
            "password": reset_data["new_password"],
        })
        login_data = login.get_json()
        self.assertTrue(login_data["ok"])
        self.assertIn("my_stats", login_data)
        self.assertEqual(login_data["my_stats"]["arrived"], 0)
        self.assertEqual(login_data["my_stats"]["missed"], 0)
        self.assertEqual(login_data["my_stats"]["booked"], 0)
        self.assertEqual(login_data["my_stats"]["paid_total"], 0)
        self.assertIn("enrollment_open", login_data)

    def test_auth_error_messages_are_hebrew(self):
        bad_email = self.client.post("/api/register", json={
            "email": "not-an-email",
            "password": "secret1",
            "name": "לוי",
        })
        self.assertEqual(bad_email.status_code, 400)
        self.assertEqual(bad_email.get_json()["message"], "אימייל לא תקין")
        short = self.client.post("/api/register", json={
            "email": "ok@example.com",
            "password": "123",
            "name": "לוי",
        })
        self.assertEqual(short.get_json()["message"], "הסיסמה חייבת לפחות 6 תווים")
        exists = self.client.post("/api/register", json={
            "email": "ok@example.com",
            "password": "secret1",
            "name": "לוי",
        })
        self.assertTrue(exists.get_json()["ok"])
        again = self.client.post("/api/register", json={
            "email": "ok@example.com",
            "password": "secret1",
            "name": "דוד",
        })
        self.assertEqual(again.get_json()["message"], "האימייל כבר רשום")
        empty = self.client.post("/api/login", json={"email": "", "password": "secret1"})
        self.assertEqual(empty.get_json()["message"], "יש להזין אימייל")
        missing = self.client.post("/api/reset-password", json={"email": "nobody@example.com"})
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.get_json()["message"], "האימייל לא נמצא")

    def test_unpaid_blocks_next_enroll_and_shows_warning(self):
        created = self.client.post("/api/register", json={
            "email": "levi@example.com",
            "password": "secret1",
            "name": "לוי",
        })
        user_id = created.get_json()["user"]["id"]
        with app.app_context():
            db.session.add(Enrollment(
                slot="sunday",
                week_key="2020-01-05",
                name="לוי",
                name_key="לוי",
                user_id=user_id,
                is_waitlist=False,
                paid=False,
            ))
            db.session.commit()
            enrollment_id = Enrollment.query.filter_by(week_key="2020-01-05").first().id
        warning = "הלו הלו לא שילמת למשחק של יום ראשון 05.01.2020 תשלם עכשיו"
        state = self.client.get("/api/state").get_json()
        self.assertEqual(state["pay_warning"], warning)
        self.assertEqual(state["unpaid"]["enrollment_id"], enrollment_id)
        self.assertTrue(any(
            game["week_key"] == "2020-01-05" for game in state["past_games"]
        ))
        self.assertTrue(all(not game.get("is_ended") for game in state["games"]))
        blocked = self.client.post("/api/join", json={"slot": "sunday"})
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(blocked.get_json()["message"], warning)
        paid = self.client.post("/api/me/paid", json={"id": enrollment_id})
        self.assertTrue(paid.get_json()["ok"])
        self.assertIsNone(paid.get_json()["unpaid"])
        self.assertIsNone(paid.get_json()["pay_warning"])

    def test_waitlist_and_open_game_do_not_nag(self):
        from datetime import datetime
        from app import User, unpaid_debt
        from schedule import TZ, get_slot_state

        created = self.client.post("/api/register", json={
            "email": "levi@example.com",
            "password": "secret1",
            "name": "לוי",
        })
        user_id = created.get_json()["user"]["id"]
        current = get_slot_state("sunday")["week_key"]
        with app.app_context():
            db.session.add(Enrollment(
                slot="sunday",
                week_key=current,
                name="לוי",
                name_key="לוי",
                user_id=user_id,
                is_waitlist=False,
                paid=False,
            ))
            db.session.add(Enrollment(
                slot="sunday",
                week_key="2020-01-05",
                name="לוי",
                name_key="לוי",
                user_id=user_id,
                is_waitlist=True,
                paid=False,
            ))
            db.session.commit()
            user = db.session.get(User, user_id)
            self.assertIsNone(unpaid_debt(user))
            self.assertIsNone(unpaid_debt(user, datetime(2026, 8, 30, 21, 0, tzinfo=TZ)))
        state = self.client.get("/api/state").get_json()
        self.assertIsNone(state["unpaid"])
        self.assertIsNone(state["pay_warning"])

    def test_unpaid_only_after_game_ended(self):
        from datetime import datetime
        from app import User, unpaid_debt
        from schedule import TZ

        created = self.client.post("/api/register", json={
            "email": "levi@example.com",
            "password": "secret1",
            "name": "לוי",
        })
        user_id = created.get_json()["user"]["id"]
        with app.app_context():
            db.session.add(Enrollment(
                slot="sunday",
                week_key="2026-08-30",
                name="לוי",
                name_key="לוי",
                user_id=user_id,
                is_waitlist=False,
                paid=False,
            ))
            db.session.commit()
            user = db.session.get(User, user_id)
            self.assertIsNone(unpaid_debt(user, datetime(2026, 8, 30, 19, 59, tzinfo=TZ)))
            self.assertIsNone(unpaid_debt(user, datetime(2026, 8, 30, 21, 0, tzinfo=TZ)))
            debt = unpaid_debt(user, datetime(2026, 8, 30, 22, 1, tzinfo=TZ))
            self.assertIsNotNone(debt)
            self.assertEqual(debt["week_key"], "2026-08-30")

    def test_ended_games_go_to_past_games(self):
        from schedule import get_slot_state
        sunday = get_slot_state("sunday")
        prev = sunday.get("prev_week_key")
        self.assertTrue(prev)
        with app.app_context():
            db.session.add(Enrollment(
                slot="sunday",
                week_key=prev,
                name="לוי",
                name_key="לוי",
                is_waitlist=False,
            ))
            db.session.commit()
        data = self.client.get("/api/state").get_json()
        games = data["games"]
        past = data["past_games"]
        self.assertTrue(all(not game.get("is_ended") for game in games))
        self.assertTrue(past)
        self.assertTrue(all(game.get("is_ended") for game in past))
        sunday_past = next(game for game in past if game["slot"] == "sunday")
        self.assertEqual(sunday_past["status_he"], "המשחק הסתיים")
        self.assertIn("לוי", [p["name"] for p in sunday_past["roster"]])

    def test_state_exposes_banner_flash(self):
        from schedule import banner_should_flash
        data = self.client.get("/api/state").get_json()
        self.assertIn("banner_flash", data)
        self.assertEqual(data["banner_flash"], banner_should_flash())
        self.assertIn("next_game_at_he", data)
        self.assertIn("banner_mode", data)
        self.assertIn(data["banner_mode"], ("enroll", "game", "in_progress"))
        self.assertIn("past_games", data)

    def test_public_cannot_remove_players(self):
        self._login_admin()
        self.client.post("/api/join", json={"slot": "sunday", "name": "לוי"})
        player_id = self._game(self.client.get("/api/state").get_json(), "sunday")["roster"][0]["id"]
        self.client.post("/api/admin/logout", json={})
        res = self.client.post("/api/admin/remove", json={"id": player_id})
        self.assertEqual(res.status_code, 401)
        names = [p["name"] for p in self._game(self.client.get("/api/state").get_json(), "sunday")["roster"]]
        self.assertEqual(names, ["לוי"])

    def test_field_cost_splits(self):
        self._login_admin()
        self.client.post("/api/join", json={"slot": "sunday", "name": "לוי"})
        self.client.post("/api/join", json={"slot": "sunday", "name": "שירן"})
        data = self.client.get("/api/state").get_json()
        sunday = self._game(data, "sunday")
        self.assertEqual(sunday["share"], 30)
        self.assertEqual(sunday["field_cost"], 60)

    def test_choose_booker_from_roster(self):
        self.client.post("/api/register", json={
            "email": "booker1@example.com",
            "password": "secret1",
            "name": "מזמין אחד",
        })
        self.client.post("/api/join", json={"slot": "sunday"})
        self.client.post("/api/logout", json={})
        self.client.post("/api/register", json={
            "email": "booker2@example.com",
            "password": "secret1",
            "name": "מזמין שני",
        })
        self.client.post("/api/join", json={"slot": "sunday"})
        users = {u["name"]: u["id"] for u in self.client.get("/api/state").get_json()["users"]}
        res = self.client.post("/api/booker", json={"slot": "sunday", "user_id": users["מזמין אחד"]})
        data = res.get_json()
        self.assertTrue(data["ok"], data)
        sunday = self._game(data, "sunday")
        self.assertEqual(sunday["booker_name"], "מזמין אחד")
        self.assertIsNotNone(sunday["booker_id"])

    def test_choose_custom_booker_name(self):
        denied = self.client.post("/api/booker", json={"slot": "sunday", "name": "דני המזמין"})
        self.assertEqual(denied.status_code, 401)
        self.client.post("/api/register", json={
            "email": "custombooker@example.com",
            "password": "secret1",
            "name": "בוחר מזמין",
        })
        res = self.client.post("/api/booker", json={"slot": "sunday", "name": "דני המזמין"})
        data = res.get_json()
        self.assertTrue(data["ok"], data)
        sunday = self._game(data, "sunday")
        self.assertIsNone(sunday["booker_id"])
        self.assertEqual(sunday["booker_name"], "דני המזמין")
        self._login_admin()
        self.client.post("/api/join", json={"slot": "sunday", "name": "שירן"})
        aliased = self.client.post("/api/booker", json={"slot": "sunday", "name": "שירן בר גיל"})
        sunday = self._game(aliased.get_json(), "sunday")
        self.assertEqual(sunday["booker_name"], "שירן")
        cleared = self.client.post("/api/booker", json={"slot": "sunday", "name": ""})
        self.assertIsNone(self._game(cleared.get_json(), "sunday")["booker_name"])

    def test_logged_in_user_can_pick_any_registered_booker(self):
        self.client.post("/api/register", json={
            "email": "offroster@example.com",
            "password": "secret1",
            "name": "לא במשחק",
        })
        self.client.post("/api/logout", json={})
        self.client.post("/api/register", json={
            "email": "picker@example.com",
            "password": "secret1",
            "name": "בוחר מהרשימה",
        })
        users = {u["name"]: u["id"] for u in self.client.get("/api/state").get_json()["users"]}
        self.assertEqual(set(users), {"בוחר מהרשימה", "לא במשחק"})
        res = self.client.post("/api/booker", json={"slot": "sunday", "user_id": users["לא במשחק"]})
        data = res.get_json()
        self.assertTrue(data["ok"], data)
        sunday = self._game(data, "sunday")
        self.assertEqual(sunday["booker_name"], "לא במשחק")
        self.assertIsNone(sunday["booker_id"])

    def test_keeps_previous_week_enrollments(self):
        self._login_admin()
        current = self._game(self.client.get("/api/state").get_json(), "sunday")["week_key"]
        from datetime import date, timedelta
        prev = (date.fromisoformat(current) - timedelta(days=7)).isoformat()
        with app.app_context():
            db.session.add(Enrollment(
                slot="sunday",
                week_key=prev,
                name="לוי",
                name_key="לוי",
                is_waitlist=False,
            ))
            db.session.add(Enrollment(
                slot="sunday",
                week_key=prev,
                name="שירן",
                name_key="שירן",
                is_waitlist=False,
            ))
            db.session.commit()
        data = self.client.get("/api/state").get_json()
        sunday = self._game(data, "sunday")
        self.assertNotIn("לוי", [p["name"] for p in sunday["roster"]])
        ended = self._game(data, "sunday", ended=True)
        history_names = [p["name"] for h in sunday["history"] for p in h["roster"]]
        if ended:
            history_names += [p["name"] for p in ended["roster"]]
        self.assertIn("לוי", history_names)
        stats = {p["name"]: p for p in data["stats"]["players"]}
        self.assertGreaterEqual(data["stats"]["games"], 1)
        self.assertEqual([p["name"] for p in data["stats"]["players"]], list(FIXED_PLAYERS))
        self.assertEqual(stats["לוי"]["arrived"], 1)
        self.assertEqual(stats["שירן"]["arrived"], 1)
        self.assertEqual(stats["אבירם"]["missed"], 1)
        self.assertEqual(stats["לוי"]["arrival_history"], [1])
        self.assertEqual(stats["אבירם"]["arrival_history"], [0])
        self.assertEqual(stats["לוי"]["booked"], 0)
        self.assertEqual(stats["לוי"]["booker_history"], [0])

    def test_squad_lists_fixed_names_and_alias(self):
        self._login_admin()
        current = self._game(self.client.get("/api/state").get_json(), "sunday")["week_key"]
        with app.app_context():
            db.session.add(Enrollment(
                slot="sunday",
                week_key=current,
                name="עידו",
                name_key="עידו",
                is_waitlist=False,
            ))
            db.session.commit()
        sunday = self._game(self.client.get("/api/state").get_json(), "sunday")
        self.assertEqual(len(sunday["squad"]), 9)
        idan = next(p for p in sunday["squad"] if p["name"] == "עידן")
        self.assertEqual(idan["status"], "arrived")
        self.assertIn("עידן", [p["name"] for p in sunday["roster"]])
        arrived = [p["name"] for p in sunday["squad"] if p["status"] == "arrived"]
        missed = [p["name"] for p in sunday["squad"] if p["status"] == "out"]
        self.assertIn("עידן", arrived)
        self.assertIn("שירן", missed)

    def test_stats_track_booker_history(self):
        self._login_admin()
        current = self.client.get("/api/state").get_json()["games"][0]["week_key"]
        from datetime import date, timedelta
        prev = (date.fromisoformat(current) - timedelta(days=7)).isoformat()
        with app.app_context():
            levi = Enrollment(
                slot="sunday",
                week_key=prev,
                name="לוי",
                name_key="לוי",
                is_waitlist=False,
            )
            shiran = Enrollment(
                slot="sunday",
                week_key=prev,
                name="שירן",
                name_key="שירן",
                is_waitlist=False,
            )
            db.session.add_all([levi, shiran])
            db.session.flush()
            settings = GameSettings.query.filter_by(slot="sunday", week_key=prev).first()
            if settings:
                settings.booker_id = shiran.id
            else:
                db.session.add(GameSettings(slot="sunday", week_key=prev, booker_id=shiran.id))
            db.session.commit()
        data = self.client.get("/api/state").get_json()
        stats = {p["name"]: p for p in data["stats"]["players"]}
        self.assertEqual(len(data["stats"]["players"]), 9)
        self.assertEqual(stats["שירן"]["booked"], 1)
        self.assertEqual(stats["שירן"]["booker_history"], [1])
        self.assertEqual(stats["לוי"]["booked"], 0)
        self.assertEqual(stats["לוי"]["booker_history"], [0])
        self.assertEqual(stats["לוי"]["arrived"], 1)
        self.assertEqual(stats["עידן"]["missed"], 1)
        self.assertEqual(stats["עידן"]["not_booked"], 1)

    def test_stats_merge_name_aliases(self):
        self._login_admin()
        current = self.client.get("/api/state").get_json()["games"][0]["week_key"]
        from datetime import date, timedelta
        pairs = [
            ("עידן", "עידן רזון"),
            ("שירן", "שירן בר גיל"),
            ("אבירם", "אבירם עמר"),
            ("חן", "חן שעשוע"),
        ]
        with app.app_context():
            for index, (short, full) in enumerate(pairs):
                week_a = (date.fromisoformat(current) - timedelta(days=14 + index)).isoformat()
                week_b = (date.fromisoformat(current) - timedelta(days=7 + index)).isoformat()
                db.session.add(Enrollment(
                    slot="sunday", week_key=week_a, name=short, name_key=short, is_waitlist=False,
                ))
                db.session.add(Enrollment(
                    slot="sunday", week_key=week_b, name=full, name_key=full, is_waitlist=False,
                ))
            db.session.commit()
        data = self.client.get("/api/state").get_json()
        names = [p["name"] for p in data["stats"]["players"]]
        stats = {p["name"]: p for p in data["stats"]["players"]}
        for short, full in pairs:
            self.assertIn(short, names)
            self.assertNotIn(full, names)
            self.assertGreaterEqual(stats[short]["arrived"], 2)

    def test_pay_reminder_skips_empty_and_sends_share(self):
        empty = self.client.post("/api/admin/pay-reminder", json={})
        self.assertEqual(empty.status_code, 401)
        self._login_admin()
        empty = self.client.post("/api/admin/pay-reminder", json={})
        self.assertTrue(empty.get_json()["ok"])
        self.assertEqual(empty.get_json()["sent"], [])
        self.client.post("/api/join", json={"slot": "sunday", "name": "לוי"})
        self.client.post("/api/join", json={"slot": "sunday", "name": "שירן"})
        res = self.client.post("/api/admin/pay-reminder", json={})
        data = res.get_json()
        self.assertTrue(data["ok"], data)
        self.assertEqual(len(data["sent"]), 1)
        self.assertEqual(data["sent"][0]["share"], 30)
        self.assertIn("30 ₪", data["sent"][0]["body"])
        self.assertIn("לוי", data["sent"][0]["names"])

    def test_state_exposes_bit_phone(self):
        old = os.environ.get("BIT_PAY_PHONE")
        os.environ["BIT_PAY_PHONE"] = "050-123-4567"
        try:
            data = self.client.get("/api/state").get_json()
            self.assertEqual(data["bit_phone"], "0501234567")
        finally:
            if old is None:
                os.environ.pop("BIT_PAY_PHONE", None)
            else:
                os.environ["BIT_PAY_PHONE"] = old

    def test_cron_pay_reminder_unauthorized_on_render(self):
        old = os.environ.get("RENDER")
        os.environ["RENDER"] = "1"
        try:
            res = self.client.get("/api/cron/pay-reminder")
            self.assertEqual(res.status_code, 401)
            hour = self.client.get("/api/cron/hour-before")
            self.assertEqual(hour.status_code, 401)
        finally:
            if old is None:
                os.environ.pop("RENDER", None)
            else:
                os.environ["RENDER"] = old

    def test_cron_accepts_bearer_header_and_query_secret(self):
        old_render = os.environ.get("RENDER")
        old_secret = os.environ.get("CRON_SECRET")
        os.environ["RENDER"] = "1"
        os.environ["CRON_SECRET"] = "test-cron-secret"
        try:
            denied = self.client.get("/api/cron/pay-reminder")
            self.assertEqual(denied.status_code, 401)
            bearer = self.client.get(
                "/api/cron/pay-reminder",
                headers={"Authorization": "Bearer test-cron-secret"},
            )
            self.assertEqual(bearer.status_code, 200, bearer.get_json())
            self.assertTrue(bearer.get_json()["ok"])
            query = self.client.get("/api/cron/hour-before?secret=test-cron-secret")
            self.assertEqual(query.status_code, 200, query.get_json())
            header = self.client.get(
                "/api/cron/pay-reminder",
                headers={"X-Cron-Secret": "test-cron-secret"},
            )
            self.assertEqual(header.status_code, 200, header.get_json())
        finally:
            if old_render is None:
                os.environ.pop("RENDER", None)
            else:
                os.environ["RENDER"] = old_render
            if old_secret is None:
                os.environ.pop("CRON_SECRET", None)
            else:
                os.environ["CRON_SECRET"] = old_secret

    def test_only_admin_can_move_game_date(self):
        frozen = datetime(2026, 8, 27, 22, 0, tzinfo=TZ)
        with patch("schedule.now_il", return_value=frozen), patch("app.now_il", return_value=frozen):
            denied = self.client.post("/api/admin/game-date", json={"slot": "sunday", "date": "2026-08-31"})
            self.assertEqual(denied.status_code, 401)
            player = self.client.post("/api/register", json={
                "email": "date@example.com",
                "password": "secret1",
                "name": "שחקן תאריך",
            })
            self.assertTrue(player.get_json()["ok"], player.get_json())
            still = self.client.post("/api/admin/game-date", json={"slot": "sunday", "date": "2026-08-31"})
            self.assertEqual(still.status_code, 401)
            self.assertFalse(self.client.get("/api/state").get_json()["is_admin"])
            self._login_admin()
            state = self.client.get("/api/state").get_json()
            self.assertTrue(state["is_admin"])
            sunday = self._game(state, "sunday")
            self.assertEqual(sunday["week_key"], "2026-08-30")
            self.assertEqual(sunday["game_date"], "2026-08-30")
            moved = self.client.post("/api/admin/game-date", json={"slot": "sunday", "date": "2026-08-31"})
            data = moved.get_json()
            self.assertTrue(data["ok"], data)
            sunday = self._game(data, "sunday")
            self.assertEqual(sunday["week_key"], "2026-08-30")
            self.assertEqual(sunday["game_date"], "2026-08-31")
            self.assertTrue(sunday["date_override"])
            self.assertEqual(sunday["label_he"], "יום שני")
            self.client.post("/api/join", json={"slot": "sunday", "name": "לוי"})
            row = Enrollment.query.filter_by(slot="sunday", week_key="2026-08-30").one()
            self.assertEqual(row.week_key, "2026-08-30")
            settings = GameSettings.query.filter_by(slot="sunday", week_key="2026-08-30").one()
            self.assertEqual(settings.game_date, "2026-08-31")
            clash = self.client.post("/api/admin/game-date", json={"slot": "sunday", "date": "2026-09-02"})
            self.assertEqual(clash.status_code, 400)
            reset = self.client.post("/api/admin/game-date", json={"slot": "sunday", "date": ""})
            sunday = self._game(reset.get_json(), "sunday")
            self.assertTrue(reset.get_json()["ok"])
            self.assertEqual(sunday["game_date"], "2026-08-30")
            self.assertFalse(sunday["date_override"])


if __name__ == "__main__":
    unittest.main()
