"""Explicit integration checks: python -m unittest discover -s tests -p auth_postgres_checks.py.

Tests use the real configured PostgreSQL and roll back their fixtures. The race
check briefly commits one synthetic identity, then deletes it in finally.
"""
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import re
import secrets
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from app import create_app
from auth_service import AuthService, current_website_origin, digest, website_origin
from lottery import DrawError
from storage import PostgresStore


class TransactionStore:
    def __init__(self, connection):
        self.connection_value = connection

    @contextmanager
    def connection(self):
        yield self.connection_value


class AuthChecks(unittest.TestCase):
    def setUp(self):
        self.outer = PostgresStore().connection()
        self.conn = self.outer.__enter__()
        def cleanup():
            self.conn.rollback()
            self.outer.__exit__(None, None, None)
        self.addCleanup(cleanup)
        self.auth = AuthService(TransactionStore(self.conn))
        self.uid = '9' + ''.join(str(secrets.randbelow(10)) for _ in range(18))

    def link(self):
        link = self.auth.issue_link(self.uid, 'Auth check', 'http://127.0.0.1:5000')
        return link, parse_qs(urlsplit(link).fragment)['token'][0]

    def test_link_is_opaque_hashed_and_only_once(self):
        link, token = self.link()
        self.assertNotIn(self.uid, link)
        self.assertEqual(urlsplit(link).query, '')
        saved = self.conn.execute('SELECT token_hash FROM onmyoji_shards.login_tokens WHERE token_hash=%s', (digest(token),)).fetchone()
        self.assertIsNotNone(saved)
        self.assertNotEqual(saved[0], token)
        login = self.auth.consume_link(token)
        self.assertEqual(self.auth.current(login)['discord_user_id'], self.uid)
        with self.assertRaises(DrawError):
            self.auth.consume_link(token)

    def test_reissue_invalidates_old_link_and_preserves_identity(self):
        _, old = self.link()
        _, new = self.link()
        with self.assertRaises(DrawError):
            self.auth.consume_link(old)
        self.assertEqual(self.auth.current(self.auth.consume_link(new))['discord_user_id'], self.uid)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM onmyoji_shards.player_identities WHERE provider='discord' AND external_subject=%s", (self.uid,)).fetchone()[0], 1)

    def test_expired_link_and_inactive_player_are_denied(self):
        _, token = self.link()
        self.conn.execute("UPDATE onmyoji_shards.login_tokens SET expires_at=now()-interval '1 minute' WHERE token_hash=%s", (digest(token),))
        with self.assertRaises(DrawError):
            self.auth.consume_link(token)
        _, token = self.link()
        self.conn.execute('UPDATE onmyoji_shards.players SET is_active=false WHERE id=(SELECT player_id FROM onmyoji_shards.login_tokens WHERE token_hash=%s)', (digest(token),))
        with self.assertRaises(DrawError):
            self.auth.consume_link(token)

    def test_password_requires_magic_link_and_logout_revokes(self):
        _, token = self.link()
        with self.assertRaises(DrawError):
            self.auth.login_password(self.uid, 'long-password-before-setup')
        magic = self.auth.consume_link(token)
        self.auth.set_password(magic, 'a-long-test-password-123')
        web = self.auth.login_password(self.uid, 'a-long-test-password-123')
        self.assertFalse(self.auth.current(web)['can_set_password'])
        with self.assertRaises(DrawError):
            self.auth.set_password(web, 'another-long-test-password')
        with self.assertRaises(DrawError):
            self.auth.login_password(self.uid, 'wrong-password')
        self.auth.logout(web)
        self.assertIsNone(self.auth.current(web))
        self.auth.set_password(magic, 'new-long-password-456')
        with self.assertRaises(DrawError):
            self.auth.login_password(self.uid, 'a-long-test-password-123')

    def test_expired_magic_cannot_reset_and_reset_revokes_other_sessions(self):
        _, token = self.link()
        magic = self.auth.consume_link(token)
        self.auth.set_password(magic, 'a-long-test-password-123')
        web = self.auth.login_password(self.uid, 'a-long-test-password-123')
        self.auth.set_password(magic, 'new-long-password-456')
        self.assertIsNone(self.auth.current(web))
        self.conn.execute("UPDATE onmyoji_shards.web_sessions SET created_at=now()-interval '16 minutes' WHERE token_hash=%s", (digest(magic),))
        with self.assertRaises(DrawError):
            self.auth.set_password(magic, 'yet-another-long-password')

    def test_rate_limit_applies(self):
        for _ in range(3):
            self.auth.rate_limit(self.uid, limit=3)
        with self.assertRaises(DrawError) as error:
            self.auth.rate_limit(self.uid, limit=3)
        self.assertEqual(error.exception.status, 429)

    def test_web_csrf_session_rotation_and_no_get_consumption(self):
        _, token = self.link()
        app = create_app(auth_service=self.auth)
        client = app.test_client()
        page = client.get('/login')
        csrf = re.search(r'name="csrf-token" content="([^"]+)"', page.get_data(as_text=True)).group(1)
        self.assertEqual(client.post('/api/auth/discord-link', json={'token': token}).status_code, 403)
        response = client.post('/api/auth/discord-link', json={'token': token}, headers={'X-CSRF-Token': csrf})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['redirect'], '/account')
        self.assertEqual(client.get('/shards').headers['Location'], '/account')
        self.assertEqual(client.get('/api/auth/me').json['user']['discord_user_id'], self.uid)
        self.assertEqual(client.post('/api/auth/password', json={'password':'a-long-test-password-123', 'confirm_password':'a-long-test-password-123'}, headers={'X-CSRF-Token':csrf}).status_code, 403)
        with client.session_transaction() as state:
            new_csrf = state['csrf']
        self.assertNotEqual(new_csrf, csrf)
        self.assertEqual(client.post('/api/auth/password', json={'password':'a-long-test-password-123','confirm_password':'a-long-test-password-123'}, headers={'X-CSRF-Token':new_csrf}).status_code, 200)
        logged = self.auth.login_password(self.uid, 'a-long-test-password-123')
        self.assertTrue(self.auth.current(logged)['password_set'])
        response = client.post('/api/auth/password-login', json={'username':self.uid,'password':'a-long-test-password-123'}, headers={'X-CSRF-Token':new_csrf})
        self.assertEqual(response.json['redirect'], '/shards')
        other = app.test_client()
        self.assertIsNone(other.get('/api/auth/me').json['user'])
        for path in ('/', '/shards', '/account'):
            self.assertEqual(other.get(path).headers['Location'], '/login')
        for path in ('/api/draws', '/api/health', '/api/shards/catalog'):
            self.assertEqual(other.get(path).status_code, 401)
        self.assertEqual(other.get('/api/shards/jobs/anything').status_code, 401)
        self.assertNotIn(token, page.get_data(as_text=True))

    def test_origin_uses_current_environment(self):
        with patch.dict('os.environ', {'WEBSITE_URL':'','RENDER':'true','RENDER_EXTERNAL_URL':'https://current-example.onrender.com'}):
            self.assertEqual(current_website_origin(), 'https://current-example.onrender.com')
        for bad in ('//evil.test', 'https://good.test@evil.test/path', 'https://good.test/?token=x', 'javascript:alert(1)'):
            with self.assertRaises(DrawError):
                website_origin(bad)


class ConcurrentConsumptionCheck(unittest.TestCase):
    def test_only_one_concurrent_consumer_succeeds(self):
        auth = AuthService()
        uid = '8' + ''.join(str(secrets.randbelow(10)) for _ in range(18))
        link = auth.issue_link(uid, 'Disposable auth race check', 'http://127.0.0.1:5000')
        token = parse_qs(urlsplit(link).fragment)['token'][0]
        try:
            def consume(_):
                try:
                    auth.consume_link(token)
                    return True
                except DrawError:
                    return False
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(consume, range(2)))
            self.assertEqual(results.count(True), 1)
        finally:
            with PostgresStore().connection() as conn:
                conn.execute("DELETE FROM onmyoji_shards.players WHERE id IN (SELECT player_id FROM onmyoji_shards.player_identities WHERE provider='discord' AND external_subject=%s)", (uid,))


if __name__ == '__main__':
    unittest.main()
