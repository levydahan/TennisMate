import os
import tempfile
import unittest

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "test"

from app import Enrollment, GameSettings, app, db
from players import FIXED_PLAYERS


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
        for game in data["games"]:
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
        reset = self.client.post("/api/reset-password", json={"email": "levi@example.com"})
        reset_data = reset.get_json()
        self.assertTrue(reset_data["ok"], reset_data)
        self.assertTrue(reset_data["new_password"])
        self.client.post("/api/logout", json={})
        login = self.client.post("/api/login", json={
            "email": "levi@example.com",
            "password": reset_data["new_password"],
        })
        self.assertTrue(login.get_json()["ok"])

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
        state = self.client.get("/api/state").get_json()
        self.assertEqual(state["pay_warning"], "הלו הלו לא שילמת למשחקת תשלם עכשיו")
        self.assertEqual(state["unpaid"]["enrollment_id"], enrollment_id)
        blocked = self.client.post("/api/join", json={"slot": "sunday"})
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(blocked.get_json()["message"], "הלו הלו לא שילמת למשחקת תשלם עכשיו")
        paid = self.client.post("/api/me/paid", json={"id": enrollment_id})
        self.assertTrue(paid.get_json()["ok"])
        self.assertIsNone(paid.get_json()["unpaid"])
        self.assertIsNone(paid.get_json()["pay_warning"])

    def test_ended_game_card_goes_to_bottom(self):
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
        games = self.client.get("/api/state").get_json()["games"]
        ended = [game for game in games if game.get("is_ended")]
        upcoming = [game for game in games if not game.get("is_ended")]
        self.assertTrue(ended)
        self.assertTrue(upcoming)
        self.assertLess(
            max(i for i, game in enumerate(games) if not game.get("is_ended")),
            min(i for i, game in enumerate(games) if game.get("is_ended")),
        )
        self.assertEqual(ended[0]["status_he"], "המשחק הסתיים")
        self.assertIn("לוי", [p["name"] for p in ended[0]["roster"]])

    def test_state_exposes_banner_flash(self):
        from schedule import banner_should_flash
        data = self.client.get("/api/state").get_json()
        self.assertIn("banner_flash", data)
        self.assertEqual(data["banner_flash"], banner_should_flash())
        self.assertIn("next_game_at_he", data)

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
        self._login_admin()
        self.client.post("/api/join", json={"slot": "sunday", "name": "לוי"})
        self.client.post("/api/join", json={"slot": "sunday", "name": "שירן"})
        self.client.post("/api/admin/logout", json={})
        roster = self._game(self.client.get("/api/state").get_json(), "sunday")["roster"]
        res = self.client.post("/api/booker", json={"slot": "sunday", "player_id": roster[1]["id"]})
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(self._game(data, "sunday")["booker_name"], "שירן")

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


if __name__ == "__main__":
    unittest.main()
