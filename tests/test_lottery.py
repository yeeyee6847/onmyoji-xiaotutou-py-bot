import copy
import re
import threading
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from app import create_app
from lottery import DrawError, new_draw, public_state, reveal_card, select_card, start_draw


def settings(mode="elimination"):
    return {"title": "週末的小確幸", "host": "小兔", "prize": "奶茶",
            "scheduled_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            "mode": mode, "participants": [
                {"name": "小月", "number": 7}, {"name": "阿茶", "number": 23},
                {"name": "小白", "number": 88}]}


class MemoryStore:
    def __init__(self):
        self.items = {}
        self.lock = threading.RLock()
        self.calls = 0

    def health(self):
        return True

    def create(self, state):
        self.calls += 1
        self.items[state["id"]] = copy.deepcopy(state)

    def get(self, draw_id):
        if draw_id not in self.items:
            raise DrawError("找不到这场抽奖。", 404)
        return copy.deepcopy(self.items[draw_id])

    def mutate(self, draw_id, action):
        with self.lock:
            state = action(self.get(draw_id))
            self.items[draw_id] = copy.deepcopy(state)
            self.calls += 1
            return state

    def list(self):
        return list(copy.deepcopy(self.items).values())


class LotteryTests(unittest.TestCase):
    def test_duplicate_numbers_rejected(self):
        data = settings()
        data["participants"][1]["number"] = 7
        with self.assertRaises(DrawError):
            new_draw(data)

    def test_invalid_numbers_and_names_rejected(self):
        for number in [0, 101, True, 2.3, "7", None]:
            data = settings()
            data["participants"][0]["number"] = number
            with self.subTest(number=number), self.assertRaises(DrawError):
                new_draw(data)
        data = settings()
        data["participants"][1]["name"] = " 小月 "
        with self.assertRaises(DrawError):
            new_draw(data)

    def test_all_participants_preserved_but_card_mapping_hidden(self):
        state = new_draw(settings())
        self.assertEqual({p["number"] for p in state["cards"]}, {7, 23, 88})
        self.assertTrue(all(c["person"] is None for c in public_state(state)["cards"]))

    def test_elimination_last_survivor_wins(self):
        state = start_draw(new_draw(settings()))
        expected = copy.deepcopy(state["cards"][2])
        for index in [0, 1]:
            select_card(state, index)
            reveal_card(state, index)
        self.assertEqual(state["winner"], expected)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(len(state["revealed"]), 2)

    def test_instant_first_card_wins_and_cannot_continue(self):
        state = start_draw(new_draw(settings("instant")))
        expected = copy.deepcopy(state["cards"][1])
        select_card(state, 1)
        reveal_card(state, 1)
        self.assertEqual(state["winner"], expected)
        with self.assertRaises(DrawError):
            select_card(state, 0)

    def test_selection_locks_other_cards_without_eliminating(self):
        state = start_draw(new_draw(settings()))
        select_card(state, 0)
        self.assertEqual(state["revealed"], [])
        self.assertIsNone(state["winner"])
        with self.assertRaises(DrawError):
            select_card(state, 1)
        visible = public_state(state)
        self.assertIsNotNone(visible["cards"][0]["person"])
        self.assertIsNone(visible["cards"][1]["person"])

    def test_reveal_retry_is_idempotent(self):
        state = start_draw(new_draw(settings("instant")))
        select_card(state, 0)
        reveal_card(state, 0)
        first = copy.deepcopy(state)
        reveal_card(state, 0)
        self.assertEqual(state, first)

    def test_unselected_card_cannot_be_revealed(self):
        state = start_draw(new_draw(settings()))
        with self.assertRaises(DrawError):
            reveal_card(state, 0)

    def test_future_draw_blocked_except_practice(self):
        data = settings()
        data["scheduled_at"] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        with self.assertRaises(DrawError):
            start_draw(new_draw(data))
        self.assertEqual(start_draw(new_draw(data, practice=True))["status"], "active")

    def test_two_people_elimination(self):
        data = settings()
        data["participants"] = data["participants"][:2]
        state = start_draw(new_draw(data))
        select_card(state, 0)
        reveal_card(state, 0)
        self.assertEqual(state["winner"], state["cards"][1])


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.app = create_app(self.store)
        self.app.testing = True
        self.client = self.app.test_client()
        html = self.client.get("/").get_data(as_text=True)
        self.token = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)

    def post(self, path, data):
        return self.client.post(path, json=data, headers={"X-CSRF-Token": self.token})

    def test_csrf_and_bad_payload(self):
        self.assertEqual(self.client.post("/api/draws", json=settings()).status_code, 403)
        self.assertEqual(self.post("/api/draws", []).status_code, 400)
        self.assertEqual(self.post("/api/draws", {**settings(), "practice": "false"}).status_code, 400)

    def test_practice_full_flow_never_touches_database(self):
        response = self.post("/api/draws", {**settings(), "practice": True})
        self.assertEqual(response.status_code, 201)
        state = response.json
        base = f'/api/draws/{state["id"]}'
        self.post(base + "/start", {"practice": True})
        for index in [0, 1]:
            self.post(base + "/select", {"practice": True, "index": index})
            response = self.post(base + "/reveal", {"practice": True, "index": index})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "completed")
        self.assertEqual(self.store.calls, 0)
        self.assertEqual(self.store.list(), [])
        self.assertEqual(self.client.get(base + "?practice=1").status_code, 200)

    def test_formal_persists_settings_selection_and_winner(self):
        state = self.post("/api/draws", settings("instant")).json
        base = f'/api/draws/{state["id"]}'
        self.post(base + "/start", {})
        selected = self.post(base + "/select", {"index": 1}).json
        self.assertIsNotNone(selected["cards"][1]["person"])
        self.assertEqual(self.client.get(base).json["selected"], 1)
        response = self.post(base + "/reveal", {"index": 1})
        self.assertEqual(response.json["status"], "completed")
        self.assertEqual(self.store.get(state["id"])["winner"], response.json["winner"])
        self.assertEqual(len(self.client.get("/api/draws").json), 1)

    def test_other_session_cannot_read_practice(self):
        state = self.post("/api/draws", {**settings(), "practice": True}).json
        other = self.app.test_client()
        self.assertEqual(other.get(f'/api/draws/{state["id"]}?practice=1').status_code, 404)

    def test_practice_restart_reshuffles_and_keeps_rounds_independent(self):
        orders = iter([(2, 1, 0), (1, 2, 0)])

        def arrange(cards):
            original = cards[:]
            cards[:] = [original[i] for i in next(orders)]

        with patch("lottery.secrets.SystemRandom") as random:
            random.return_value.shuffle.side_effect = arrange
            payload = {**settings(), "practice": True}
            first = self.post("/api/draws", payload).json
            first_base = f'/api/draws/{first["id"]}'
            self.post(first_base + "/start", {"practice": True})
            selected = self.post(first_base + "/select", {"practice": True, "index": 0}).json
            self.assertEqual(selected["cards"][0]["person"]["number"], 88)

            second = self.post("/api/draws", payload).json
            self.assertNotEqual(first["id"], second["id"])
            self.assertEqual(second["status"], "ready")
            self.assertEqual(second["revealed"], [])
            self.assertIsNone(second["selected"])
            self.assertIsNone(second["winner"])
            self.assertEqual(second["participants"], first["participants"])
            self.assertTrue(all(card["person"] is None for card in second["cards"]))
            second_base = f'/api/draws/{second["id"]}'
            self.post(second_base + "/start", {"practice": True})
            selected = self.post(second_base + "/select", {"practice": True, "index": 0}).json
            self.assertEqual(selected["cards"][0]["person"]["number"], 23)
            self.assertEqual(random.return_value.shuffle.call_count, 2)
            # 开新局和刷新都不能改变旧局的号码位置。
            restored = self.client.get(first_base + "?practice=1").json
            self.assertEqual(restored["cards"][0]["person"]["number"], 88)
            self.assertEqual(restored["selected"], 0)
            self.assertEqual(self.store.calls, 0)

    def test_unknown_and_invalid_ids(self):
        self.assertEqual(self.client.get("/api/draws/not-a-uuid").status_code, 404)
        state = self.post("/api/draws", settings()).json
        self.assertEqual(self.post(f'/api/draws/{state["id"]}/reveal', {"index": True}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
