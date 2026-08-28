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
        self.assertEqual(len(data["games"][0]["waiting"]), 1)

        first_id = data["games"][0]["roster"][0]["id"]
        res = self.client.post("/api/admin/remove", json={"id": first_id})
        data = res.get_json()
        self.assertTrue(data["ok"])
        names = [p["name"] for p in data["games"][0]["roster"]]
        self.assertIn(waiting_name, names)
        self.assertEqual(data["games"][0]["waiting"], [])
        self.assertEqual(data["games"][0]["share"], 10)

    def test_unknown_name_cannot_join(self):
        res = self.client.post("/api/join", json={"slot": "sunday", "name": "דני"})
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.get_json()["ok"])

    def test_public_cannot_remove_players(self):
        self._login_admin()
        self.client.post("/api/join", json={"slot": "sunday", "name": "לוי"})
        player_id = self.client.get("/api/state").get_json()["games"][0]["roster"][0]["id"]
        self.client.post("/api/admin/logout", json={})
        res = self.client.post("/api/admin/remove", json={"id": player_id})
        self.assertEqual(res.status_code, 401)
        names = [p["name"] for p in self.client.get("/api/state").get_json()["games"][0]["roster"]]
        self.assertEqual(names, ["לוי"])

    def test_field_cost_splits(self):
        self._login_admin()
        self.client.post("/api/join", json={"slot": "sunday", "name": "לוי"})
        self.client.post("/api/join", json={"slot": "sunday", "name": "שירן"})
        data = self.client.get("/api/state").get_json()
        self.assertEqual(data["games"][0]["share"], 30)
        self.assertEqual(data["games"][0]["field_cost"], 60)

    def test_choose_booker_from_roster(self):
        self._login_admin()
        self.client.post("/api/join", json={"slot": "sunday", "name": "לוי"})
        self.client.post("/api/join", json={"slot": "sunday", "name": "שירן"})
        self.client.post("/api/admin/logout", json={})
        roster = self.client.get("/api/state").get_json()["games"][0]["roster"]
        res = self.client.post("/api/booker", json={"slot": "sunday", "player_id": roster[1]["id"]})
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["games"][0]["booker_name"], "שירן")

    def test_keeps_previous_week_enrollments(self):
        self._login_admin()
        current = self.client.get("/api/state").get_json()["games"][0]["week_key"]
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
        self.assertNotIn("לוי", [p["name"] for p in data["games"][0]["roster"]])
        history_names = [p["name"] for h in data["games"][0]["history"] for p in h["roster"]]
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
        current = self.client.get("/api/state").get_json()["games"][0]["week_key"]
        with app.app_context():
            db.session.add(Enrollment(
                slot="sunday",
                week_key=current,
                name="עידו",
                name_key="עידו",
                is_waitlist=False,
            ))
            db.session.commit()
        sunday = self.client.get("/api/state").get_json()["games"][0]
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

    def test_cron_pay_reminder_unauthorized_on_render(self):
        old = os.environ.get("RENDER")
        os.environ["RENDER"] = "1"
        try:
            res = self.client.get("/api/cron/pay-reminder")
            self.assertEqual(res.status_code, 401)
        finally:
            if old is None:
                os.environ.pop("RENDER", None)
            else:
                os.environ["RENDER"] = old


if __name__ == "__main__":
    unittest.main()
