import os
import re
import runpy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import create_app, server_address


class DeploymentTests(unittest.TestCase):
    def test_render_requires_persistent_session_secret(self):
        with patch.dict(os.environ, {"RENDER": "true", "FLASK_SECRET_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "FLASK_SECRET_KEY"):
                create_app()

    def test_public_pages_and_lottery_need_no_login(self):
        store = SimpleNamespace(health=lambda: True, list=lambda: [])
        with patch.dict(os.environ, {"RENDER": "true", "FLASK_SECRET_KEY": "test-session-key"}):
            app = create_app(store)
        client = app.test_client()
        for path in ("/", "/api/draws", "/api/health", "/static/app.js"):
            with self.subTest(path=path):
                response = client.get(path, base_url="https://localhost")
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("WWW-Authenticate", response.headers)
                response.close()
        # 同一位匿名访客可以取得会话并实际完成一次试玩。
        client = app.test_client()
        response = client.get("/", base_url="https://localhost")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Secure", response.headers["Set-Cookie"])
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])
        token = re.search(r'name="csrf-token" content="([^"]+)"', response.get_data(as_text=True)).group(1)
        headers = {"X-CSRF-Token": token}
        created = client.post("/api/draws", base_url="https://localhost", headers=headers, json={
            "title": "Public trial", "host": "Visitor", "prize": "Gift", "practice": True,
            "mode": "instant", "scheduled_at": "2020-01-01T00:00:00+00:00",
            "participants": [{"name": "A", "number": 1}, {"name": "B", "number": 2}]})
        self.assertEqual(created.status_code, 201)
        base = f'/api/draws/{created.json["id"]}'
        for action in ("start", "select", "reveal"):
            response = client.post(base + "/" + action, base_url="https://localhost", headers=headers,
                                   json={"practice": True, "index": 0})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["status"], "completed")

    def test_legacy_admin_password_does_not_enable_login(self):
        with patch.dict(os.environ, {"RENDER": "true", "FLASK_SECRET_KEY": "test-session-key", "ADMIN_PASSWORD": "old-setting"}):
            app = create_app()
        response = app.test_client().get("/", base_url="https://localhost")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("WWW-Authenticate", response.headers)

    def test_healthcheck_has_no_authentication_or_cookie(self):
        with patch.dict(os.environ, {"RENDER": "true", "FLASK_SECRET_KEY": "test-session-key"}):
            app = create_app()
        response = app.test_client().get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok"})
        self.assertNotIn("Set-Cookie", response.headers)

    def test_render_host_and_port_and_local_default(self):
        with patch.dict(os.environ, {"RENDER": "true", "HOST": "", "PORT": "12345"}):
            self.assertEqual(server_address(), ("0.0.0.0", 12345))
        with patch.dict(os.environ, {"RENDER": "true", "HOST": "", "PORT": ""}):
            self.assertEqual(server_address(), ("0.0.0.0", 10000))
        with patch.dict(os.environ, {"RENDER": "", "HOST": "", "PORT": ""}):
            self.assertEqual(server_address(), ("127.0.0.1", 5000))

    def test_render_ignores_local_host_override(self):
        with patch.dict(os.environ, {"RENDER": "true", "HOST": "127.0.0.1", "PORT": "12345"}):
            self.assertEqual(server_address(), ("0.0.0.0", 12345))

    def test_render_starts_without_local_secret_files(self):
        with patch.dict(os.environ, {"RENDER": "true", "FLASK_SECRET_KEY": "test-session-key"}):
            with patch.object(Path, "mkdir", side_effect=PermissionError("No local storage")):
                app = create_app()
        self.assertEqual(app.test_client().get("/healthz").status_code, 200)

    def test_render_does_not_load_local_dotenv(self):
        with patch.dict(os.environ, {"RENDER": "true"}), patch("dotenv.load_dotenv") as load:
            runpy.run_path(str(Path(__file__).resolve().parents[1] / "storage.py"))
        load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
