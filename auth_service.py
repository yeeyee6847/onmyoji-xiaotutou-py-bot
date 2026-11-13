"""Shared PostgreSQL authentication for the web and Discord bot; no Flask dependency."""
import hashlib
import os
import re
import secrets
from urllib.parse import urlsplit

from werkzeug.security import check_password_hash, generate_password_hash

from lottery import DrawError
from storage import PostgresStore


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def discord_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{15,20}', value):
        raise DrawError('请输入有效的 Discord user ID。')
    return value


def valid_token(value):
    return isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', value) is not None


def website_origin(value):
    parsed = urlsplit(value)
    if (parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/') or not parsed.netloc
            or (parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1')))):
        raise DrawError('请将 WEBSITE_URL 设置为网站的 HTTPS 域名；本机可用 http://127.0.0.1:5000。', 503)
    return value.rstrip('/')


def current_website_origin():
    """Render supplies its external URL; a separate bot can override WEBSITE_URL."""
    origin = os.getenv('WEBSITE_URL') or os.getenv('RENDER_EXTERNAL_URL')
    if not origin:
        if os.getenv('RENDER') == 'true':
            raise DrawError('当前部署没有网站地址，请设置 WEBSITE_URL。', 503)
        host = os.getenv('HOST') or '127.0.0.1'
        if host in ('0.0.0.0', '::'):
            host = '127.0.0.1'
        origin = 'http://' + host + ':' + (os.getenv('PORT') or '5000')
    return website_origin(origin)


class AuthService:
    def __init__(self, store=None):
        self.store = store if store is not None else PostgresStore()

    def issue_link(self, user_id, display_name, origin):
        """Call only with interaction.user.id verified by Discord, never a web-supplied ID."""
        user_id = discord_id(str(user_id))
        origin = website_origin(origin)
        name = str(display_name).strip()[:80] or user_id
        token = secrets.token_urlsafe(32)
        with self.store.connection() as conn:
            # Serialize identity creation and replacement of pending links for this Discord user.
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', ('discord:' + user_id,))
            identity = conn.execute('''SELECT p.id, p.is_active FROM onmyoji_shards.player_identities i
                JOIN onmyoji_shards.players p ON p.id=i.player_id
                WHERE i.provider='discord' AND i.external_subject=%s''', (user_id,)).fetchone()
            if identity is None:
                player_id = conn.execute('INSERT INTO onmyoji_shards.players(display_name) VALUES (%s) RETURNING id', (name,)).fetchone()[0]
                conn.execute('''INSERT INTO onmyoji_shards.player_identities(player_id,provider,external_subject)
                    VALUES (%s,'discord',%s)''', (player_id, user_id))
            else:
                player_id, active = identity
                if not active:
                    raise DrawError('此账号已停用。', 403)
                conn.execute('UPDATE onmyoji_shards.players SET display_name=%s WHERE id=%s',(name,player_id))
            conn.execute('''UPDATE onmyoji_shards.login_tokens SET used_at=now()
                WHERE player_id=%s AND used_at IS NULL''', (player_id,))
            conn.execute('''INSERT INTO onmyoji_shards.login_tokens(token_hash,player_id,expires_at)
                VALUES (%s,%s,now()+interval '10 minutes')''', (digest(token), player_id))
        return origin + '/login#token=' + token

    def _session(self, conn, player_id, method):
        token = secrets.token_urlsafe(32)
        conn.execute('''INSERT INTO onmyoji_shards.web_sessions(token_hash,player_id,auth_method,expires_at)
            VALUES (%s,%s,%s,now()+interval '7 days')''', (digest(token), player_id, method))
        return token

    def consume_link(self, token):
        if not valid_token(token):
            raise DrawError('链接无效、已使用或已过期，请在 Discord 重新执行 /login。', 400)
        with self.store.connection() as conn:
            row = conn.execute('''UPDATE onmyoji_shards.login_tokens t SET used_at=now()
                FROM onmyoji_shards.players p
                WHERE t.token_hash=%s AND t.player_id=p.id AND p.is_active
                  AND t.used_at IS NULL AND t.expires_at>now()
                RETURNING t.player_id''', (digest(token),)).fetchone()
            if not row:
                raise DrawError('链接无效、已使用或已过期，请在 Discord 重新执行 /login。', 400)
            return self._session(conn, row[0], 'discord_link')

    def current(self, token):
        if not valid_token(token):
            return None
        with self.store.connection() as conn:
            row = conn.execute('''SELECT p.id::text,p.display_name,p.role,i.external_subject,
                EXISTS(SELECT 1 FROM onmyoji_shards.password_credentials c WHERE c.player_id=p.id),
                (NOT EXISTS(SELECT 1 FROM onmyoji_shards.password_credentials c WHERE c.player_id=p.id)
                 OR (s.auth_method='discord_link' AND s.created_at>now()-interval '15 minutes'))
                FROM onmyoji_shards.web_sessions s
                JOIN onmyoji_shards.players p ON p.id=s.player_id
                JOIN onmyoji_shards.player_identities i ON i.player_id=p.id AND i.provider='discord'
                WHERE s.token_hash=%s AND s.expires_at>now() AND p.is_active''', (digest(token),)).fetchone()
        if row is None:
            return None
        return dict(id=row[0], display_name=row[1], role=row[2], discord_user_id=row[3],
                    password_set=row[4], can_set_password=row[5])

    def rate_limit(self, key, limit=10):
        # Separate committed transaction: failed authentication must not roll back its counter.
        with self.store.connection() as conn:
            attempts = conn.execute('''INSERT INTO onmyoji_shards.login_rate_limits(key_hash,attempts,resets_at)
                VALUES (%s,1,now()+interval '15 minutes') ON CONFLICT(key_hash) DO UPDATE
                SET attempts=CASE WHEN login_rate_limits.resets_at<=now() THEN 1 ELSE login_rate_limits.attempts+1 END,
                    resets_at=CASE WHEN login_rate_limits.resets_at<=now() THEN now()+interval '15 minutes' ELSE login_rate_limits.resets_at END
                RETURNING attempts''', (digest(key),)).fetchone()[0]
        if attempts > limit:
            raise DrawError('尝试次数太多，请 15 分钟后重试，或使用 Discord /login。', 429)

    def login_password(self, user_id, password):
        invalid = DrawError('Discord user ID 或密码不正确；尚未设置密码请使用 Discord /login。', 401)
        if not isinstance(user_id, str) or not re.fullmatch(r'[0-9]{15,20}', user_id):
            raise invalid
        if not isinstance(password, str) or not 1 <= len(password) <= 128:
            raise invalid
        self.rate_limit('user:' + user_id)
        with self.store.connection() as conn:
            # Password writes lock the player too, so an old password cannot open a session during reset.
            row = conn.execute('''SELECT p.id FROM onmyoji_shards.players p
                JOIN onmyoji_shards.player_identities i ON i.player_id=p.id AND i.provider='discord'
                WHERE i.external_subject=%s AND p.is_active FOR UPDATE OF p''', (user_id,)).fetchone()
            credential = conn.execute('SELECT password_hash FROM onmyoji_shards.password_credentials WHERE player_id=%s', (row[0],)).fetchone() if row else None
            if credential is None:
                # Do comparable password work even for an unknown or uninitialized account.
                generate_password_hash(password, method='scrypt')
                raise invalid
            if not check_password_hash(credential[0], password):
                raise invalid
            return self._session(conn, row[0], 'password')

    def set_password(self, token, password):
        if not valid_token(token):
            raise DrawError('请先通过 Discord /login 登录。', 401)
        if not isinstance(password, str) or not 8 <= len(password) <= 128:
            raise DrawError('密码长度需要 8–128 个字符。')
        hashed = generate_password_hash(password, method='scrypt')
        with self.store.connection() as conn:
            row = conn.execute('''SELECT p.id FROM onmyoji_shards.web_sessions s
                JOIN onmyoji_shards.players p ON p.id=s.player_id
                WHERE s.token_hash=%s AND s.expires_at>now() AND p.is_active
                FOR UPDATE OF p''', (digest(token),)).fetchone()
            if not row:
                raise DrawError('请先登录。',401)
            # Re-read after the player lock, so a concurrent first setup cannot bypass reset checks.
            allowed=conn.execute('''SELECT (NOT EXISTS(SELECT 1 FROM onmyoji_shards.password_credentials c WHERE c.player_id=s.player_id)
              OR (s.auth_method='discord_link' AND s.created_at>now()-interval '15 minutes'))
              FROM onmyoji_shards.web_sessions s WHERE s.token_hash=%s AND s.expires_at>now()''',(digest(token),)).fetchone()
            if not allowed or not allowed[0]:
                raise DrawError('重设已有密码需要最近 15 分钟内通过 Discord /login 登录。',403)
            conn.execute('''INSERT INTO onmyoji_shards.password_credentials(player_id,password_hash)
                VALUES (%s,%s) ON CONFLICT(player_id) DO UPDATE
                SET password_hash=EXCLUDED.password_hash,updated_at=now()''', (row[0], hashed))
            conn.execute('DELETE FROM onmyoji_shards.web_sessions WHERE player_id=%s AND token_hash<>%s', (row[0], digest(token)))
            conn.execute('UPDATE onmyoji_shards.login_tokens SET used_at=now() WHERE player_id=%s AND used_at IS NULL', (row[0],))

    def logout(self, token):
        if valid_token(token):
            with self.store.connection() as conn:
                conn.execute('DELETE FROM onmyoji_shards.web_sessions WHERE token_hash=%s', (digest(token),))
