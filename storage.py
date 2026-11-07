import copy
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
import psycopg
from psycopg.types.json import Jsonb

from lottery import DrawError

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")


class PostgresStore:
    @contextmanager
    def connection(self):
        url = os.getenv("DATABASE_URL", "")
        if not url:
            raise DrawError("缺少 DATABASE_URL，请在 .env 中设置 Supabase PostgreSQL 连接串。", 503)
        try:
            with psycopg.connect(url, sslmode="require", connect_timeout=8,
                                 prepare_threshold=None, options="-c statement_timeout=10000") as conn:
                yield conn
        except psycopg.errors.UndefinedTable:
            raise DrawError("抽奖表尚未建立，请运行 python manage.py init-db。", 503) from None
        except psycopg.Error:
            # 驱动异常可能含连接凭证，不向前端或日志输出原始异常。
            raise DrawError("无法访问 Supabase，请检查连接串、网络和数据库权限。", 503) from None

    def initialize(self):
        with self.connection() as conn:
            conn.execute((ROOT / "schema.sql").read_text(encoding="utf-8"))

    def health(self):
        with self.connection() as conn:
            conn.execute("SELECT 1 FROM lottery_app.draws LIMIT 1")
        return True

    def create(self, state):
        with self.connection() as conn:
            conn.execute("INSERT INTO lottery_app.draws (id, state) VALUES (%s, %s)",
                         (state["id"], Jsonb(state)))
        return state

    def get(self, draw_id):
        with self.connection() as conn:
            row = conn.execute("SELECT state FROM lottery_app.draws WHERE id = %s", (draw_id,)).fetchone()
            if row is None:
                raise DrawError("找不到这场抽奖。", 404)
            return row[0]

    def mutate(self, draw_id, action):
        with self.connection() as conn:
            row = conn.execute("SELECT state FROM lottery_app.draws WHERE id = %s FOR UPDATE", (draw_id,)).fetchone()
            if row is None:
                raise DrawError("找不到这场抽奖。", 404)
            state = action(row[0])
            conn.execute("UPDATE lottery_app.draws SET state = %s WHERE id = %s", (Jsonb(state), draw_id))
            return state

    def list(self):
        with self.connection() as conn:
            rows = conn.execute("SELECT state FROM lottery_app.draws ORDER BY created_at DESC LIMIT 100").fetchall()
            return [r[0] for r in rows]


class PracticeStore:
    """试玩只在内存保留两小时，与 PostgreSQL 完全隔离。"""
    def __init__(self):
        self.items = {}
        self.lock = threading.RLock()

    def create(self, state, owner):
        with self.lock:
            now = time.monotonic()
            self.items = {k: v for k, v in self.items.items() if v[2] > now}
            if len(self.items) >= 500:
                raise DrawError("试玩次数过多，请稍后再试。", 429)
            self.items[state["id"]] = (copy.deepcopy(state), owner, now + 7200)
        return state

    def get(self, draw_id, owner):
        with self.lock:
            item = self.items.get(draw_id)
            if not item or item[1] != owner or item[2] < time.monotonic():
                raise DrawError("试玩已过期，请重新开始。", 404)
            return copy.deepcopy(item[0])

    def mutate(self, draw_id, owner, action):
        with self.lock:
            state = action(self.get(draw_id, owner))
            self.items[draw_id] = (copy.deepcopy(state), owner, time.monotonic() + 7200)
            return state
