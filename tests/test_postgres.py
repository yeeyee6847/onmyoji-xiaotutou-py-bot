"""显式运行的真实 Supabase 集成检查；整个事务最终回滚，不留下测试记录。"""
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from lottery import new_draw, reveal_card, select_card, start_draw, update_draw
from storage import PostgresStore


class PostgresIntegrationTests(unittest.TestCase):
    def test_real_database_roundtrip_rolled_back(self):
        real = PostgresStore()
        with real.connection() as connection:
            with connection.transaction(force_rollback=True):
                class TransactionStore(PostgresStore):
                    @contextmanager
                    def connection(self):
                        yield connection
                store = TransactionStore()
                test_ids = []
                for mode in ("instant", "elimination"):
                    state = new_draw({"title": "Integration test (rolled back)", "host": "test",
                        "prize": "test", "mode": mode,
                        "scheduled_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                        "participants": [{"name": "A", "number": 1}, {"name": "B", "number": 100}]})
                    store.create(state)
                    test_ids.append(state["id"])
                    created_at = state['created_at']
                    edited = store.mutate(state['id'], lambda s: update_draw(s, {**s, 'title': 'Edited test (rolled back)'}))
                    self.assertEqual(edited['id'], state['id'])
                    self.assertEqual(edited['created_at'], created_at)
                    self.assertEqual(store.get(state['id'])['title'], 'Edited test (rolled back)')
                    count = connection.execute('SELECT count(*) FROM lottery_app.draws WHERE id = %s', (state['id'],)).fetchone()[0]
                    self.assertEqual(count, 1)
                    store.mutate(state["id"], start_draw)
                    store.mutate(state["id"], lambda s: select_card(s, 0))
                    self.assertEqual(store.get(state["id"])["selected"], 0)
                    final = store.mutate(state["id"], lambda s: reveal_card(s, 0))
                    expected = state["cards"][0 if mode == "instant" else 1]
                    self.assertEqual(final["winner"], expected)
                    self.assertEqual(store.get(state["id"])["status"], "completed")
                    retry = store.mutate(state["id"], lambda s: reveal_card(s, 0))
                    self.assertEqual(retry, final)
            # 测试插入必须已经回滚。
            for row_id in test_ids:
                self.assertIsNone(connection.execute("SELECT id FROM lottery_app.draws WHERE id = %s", (row_id,)).fetchone())


if __name__ == "__main__":
    unittest.main()
