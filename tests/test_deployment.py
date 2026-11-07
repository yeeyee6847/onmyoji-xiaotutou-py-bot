import base64
import os
import runpy
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app, server_address


class DeploymentTests(unittest.TestCase):
    def test_render_requires_persistent_secret_and_admin_password(self):
        for missing in ("FLASK_SECRET_KEY", "ADMIN_PASSWORD"):
            values = {"RENDER": "true", "FLASK_SECRET_KEY": "test-session-key", "ADMIN_PASSWORD": "test-password"}
            values[missing] = ""
            with self.subTest(missing=missing), patch.dict(os.environ, values):
                with self.assertRaisesRegex(RuntimeError, missing):
                    create_app()

    def test_admin_authentication_protects_pages_and_api(self):
        with patch.dict(os.environ, {"RENDER": "true", "FLASK_SECRET_KEY": "test-session-key", "ADMIN_PASSWORD": "test-password"}):
            app = create_app()
        client = app.test_client()
        for path in ("/", "/api/draws", "/api/health", "/static/app.js"):
            with self.subTest(path=path):
                response = client.get(path, base_url="https://localhost")
                self.assertEqual(response.status_code, 401)
                self.assertIn("Basic", response.headers["WWW-Authenticate"])
        for auth in ("admin:wrong", "wrong:test-password", "admin:密碼錯誤"):
            encoded = base64.b64encode(auth.encode()).decode()
            self.assertEqual(client.get("/", headers={"Authorization": f"Basic {encoded}"}).status_code, 401)
        encoded = base64.b64encode(b"admin:test-password").decode()
        response = client.get("/", base_url="https://localhost", headers={"Authorization": f"Basic {encoded}"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Secure", response.headers["Set-Cookie"])
        self.assertIn("HttpOnly", response.headers["Set-Cookie"])

    def test_healthcheck_has_no_authentication_or_cookie(self):
        with patch.dict(os.environ, {"RENDER": "true", "FLASK_SECRET_KEY": "test-session-key", "ADMIN_PASSWORD": "test-password"}):
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
        with patch.dict(os.environ, {"RENDER": "true", "FLASK_SECRET_KEY": "test-session-key", "ADMIN_PASSWORD": "test-password"}):
            with patch.object(Path, "mkdir", side_effect=PermissionError("No local storage")):
                app = create_app()
        self.assertEqual(app.test_client().get("/healthz").status_code, 200)

    def test_render_does_not_load_local_dotenv(self):
        with patch.dict(os.environ, {"RENDER": "true"}), patch("dotenv.load_dotenv") as load:
            runpy.run_path(str(Path(__file__).resolve().parents[1] / "storage.py"))
        load.assert_not_called()


if __name__ == "__main__":
    unittest.main()
