import os
import tempfile
import unittest

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "test"

from app import Enrollment, app, db


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
        for i in range(6):
            res = self.client.post("/api/join", json={"slot": "sunday", "name": f"שחקן {i+1}"})
            data = res.get_json()
            self.assertTrue(data["ok"], data)
            self.assertFalse(data["waitlisted"])

        res = self.client.post("/api/join", json={"slot": "sunday", "name": "מחכה"})
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["waitlisted"])
        self.assertEqual(len(data["games"][0]["waiting"]), 1)

        first_id = data["games"][0]["roster"][0]["id"]
        res = self.client.post("/api/admin/remove", json={"id": first_id})
        data = res.get_json()
        self.assertTrue(data["ok"])
        names = [p["name"] for p in data["games"][0]["roster"]]
        self.assertIn("מחכה", names)
        self.assertEqual(data["games"][0]["waiting"], [])
        self.assertEqual(data["games"][0]["share"], 10)

    def test_public_cannot_remove_players(self):
        self._login_admin()
        self.client.post("/api/join", json={"slot": "sunday", "name": "דני"})
        player_id = self.client.get("/api/state").get_json()["games"][0]["roster"][0]["id"]
        self.client.post("/api/admin/logout", json={})
        res = self.client.post("/api/admin/remove", json={"id": player_id})
        self.assertEqual(res.status_code, 401)
        names = [p["name"] for p in self.client.get("/api/state").get_json()["games"][0]["roster"]]
        self.assertEqual(names, ["דני"])

    def test_field_cost_splits(self):
        self._login_admin()
        self.client.post("/api/join", json={"slot": "sunday", "name": "אביב"})
        self.client.post("/api/join", json={"slot": "sunday", "name": "ברק"})
        data = self.client.get("/api/state").get_json()
        self.assertEqual(data["games"][0]["share"], 30)
        self.assertEqual(data["games"][0]["field_cost"], 60)

    def test_choose_booker_from_roster(self):
        self._login_admin()
        self.client.post("/api/join", json={"slot": "sunday", "name": "אביב"})
        self.client.post("/api/join", json={"slot": "sunday", "name": "ברק"})
        self.client.post("/api/admin/logout", json={})
        roster = self.client.get("/api/state").get_json()["games"][0]["roster"]
        res = self.client.post("/api/booker", json={"slot": "sunday", "player_id": roster[1]["id"]})
        data = res.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["games"][0]["booker_name"], "ברק")


if __name__ == "__main__":
    unittest.main()
