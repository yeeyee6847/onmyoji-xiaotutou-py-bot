"""Game-account ownership and confirmed OCR imports, shared with future bot commands."""
import uuid

from psycopg.types.json import Jsonb

from lottery import DrawError
from storage import PostgresStore


def account_id(value):
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise DrawError('请选择有效的游戏账号。') from None


def record(row):
    return dict(id=str(row[0]), nickname=row[1], server_name=row[2])


class GameAccounts:
    def __init__(self, store=None):
        self.store = store if store is not None else PostgresStore()

    def list(self, player_id):
        with self.store.connection() as conn:
            rows = conn.execute('''SELECT id,nickname,server_name FROM onmyoji_shards.game_accounts
                WHERE player_id=%s AND is_active ORDER BY created_at,id''', (player_id,)).fetchall()
        return [record(row) for row in rows]

    def create(self, player_id, payload):
        if not isinstance(payload, dict):
            raise DrawError('账号资料格式不正确。')
        name, server = payload.get('nickname'), payload.get('server_name', '')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise DrawError('游戏账号名字需要 1–80 个字符。')
        if not isinstance(server, str) or len(server.strip()) > 80:
            raise DrawError('服务器名称最多 80 个字符。')
        name, server = name.strip(), server.strip() or '未指定'
        with self.store.connection() as conn:
            # Names are globally unique, including across owners and servers.
            conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(lower(%s),0))',('game-account:'+name,))
            owner = conn.execute('SELECT id FROM onmyoji_shards.players WHERE id=%s AND is_active FOR UPDATE', (player_id,)).fetchone()
            if not owner:
                raise DrawError('账号已失效，请重新登录。', 401)
            exists = conn.execute('''SELECT 1 FROM onmyoji_shards.game_accounts
                WHERE lower(btrim(nickname))=lower(%s)''', (name,)).fetchone()
            if exists:
                raise DrawError('这个游戏账号名字已被使用，请换一个名字。', 409)
            row = conn.execute('''INSERT INTO onmyoji_shards.game_accounts(player_id,nickname,server_name)
                VALUES (%s,%s,%s) RETURNING id,nickname,server_name''', (player_id, name, server)).fetchone()
        return record(row)

    def owned(self, player_id, value):
        value = account_id(value)
        with self.store.connection() as conn:
            row = conn.execute('''SELECT id,nickname,server_name FROM onmyoji_shards.game_accounts
                WHERE id=%s AND player_id=%s AND is_active''', (value, player_id)).fetchone()
        if not row:
            raise DrawError('找不到你的游戏账号，请重新选择。', 404)
        return record(row)

    def save_import(self, player_id, job):
        if job['source'] != 'upload':
            raise DrawError('演示资料不能写入账号。')
        rows = [r for r in job['rows'] if r['included']]
        if job['status'] != 'done' or not rows or any(not r['confirmed'] for r in rows):
            raise DrawError('请先核对并确认所有保留的碎片记录。', 409)
        ids = [account_id(r['shikigami_id']) for r in rows]
        targets = [r.get('target', 'offers') for r in rows]
        if any(t not in ('offers','wants') for t in targets):
            raise DrawError('请确认每条记录是可提供还是想要的碎片。', 409)
        if len(set(zip(targets,ids))) != len(ids):
            raise DrawError('同一清单内式神重复，请排除或更正；提供与想要可以包含同一式神。', 409)
        if any(type(r['quantity']) is not int or not 0 <= r['quantity'] <= 99999 for r in rows):
            raise DrawError('碎片数量需要为 0–99999 的整数。')
        with self.store.connection() as conn:
            # Recheck ownership at save time, not only when uploading.
            owner = conn.execute('''SELECT id FROM onmyoji_shards.game_accounts
                WHERE id=%s AND player_id=%s AND is_active FOR UPDATE''', (job['game_account']['id'], player_id)).fetchone()
            if not owner:
                raise DrawError('找不到你的游戏账号。', 404)
            active = conn.execute('SELECT id FROM onmyoji_shards.shikigami WHERE id=ANY(%s::uuid[]) AND is_active', (ids,)).fetchall()
            if len(active) != len(set(ids)):
                raise DrawError('图鉴已变更，请重新核对。', 409)
            import_ids = {}
            for target in ('offers','wants'):
                group = [r for r in rows if r.get('target','offers') == target]
                if not group:
                    continue
                import_id = job['id'] if target == 'offers' else str(uuid.uuid5(uuid.UUID(job['id']), 'wants'))
                import_ids[target] = import_id
                inserted = conn.execute('''INSERT INTO onmyoji_shards.fragment_imports
                    (id,game_account_id,source,target,original_filename,status,engine_name)
                    VALUES (%s,%s,'web',%s,%s,'confirmed','RapidOCR + manual review')
                    ON CONFLICT(id) DO NOTHING RETURNING id''',
                    (import_id, owner[0], target, job['filename'])).fetchone()
                if not inserted:
                    existing = conn.execute('SELECT game_account_id,status,target FROM onmyoji_shards.fragment_imports WHERE id=%s', (import_id,)).fetchone()
                    if str(existing[0]) != job['game_account']['id'] or existing[1:] != ('confirmed',target):
                        raise DrawError('记录状态已改变，请重新上传。', 409)
                    continue
                for row in group:
                    from shards.reservations import guard_quantity
                    guard_quantity(conn,owner[0],row['shikigami_id'],target,row['quantity'])
                    conn.execute('''INSERT INTO onmyoji_shards.fragment_import_rows
                    (import_id,row_number,raw_name,raw_quantity,shikigami_id,quantity,
                     name_confidence,quantity_confidence,bbox,included,confirmed)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,true,true)''',
                    (import_id, row['index'], row['raw_name'], row['raw_quantity'], row['shikigami_id'], row['quantity'],
                     row['name_confidence'], row['quantity_confidence'], Jsonb(row['bbox'])))
                    conn.execute('''INSERT INTO onmyoji_shards.fragment_current(game_account_id,shikigami_id,target,quantity)
                     VALUES (%s,%s,%s,%s) ON CONFLICT(game_account_id,shikigami_id,target)
                     DO UPDATE SET quantity=EXCLUDED.quantity,updated_at=clock_timestamp()''',
                     (owner[0],row['shikigami_id'],target,row['quantity']))
        return dict(import_id=next(iter(import_ids.values())), import_ids=import_ids, saved=True)

    def fragments(self, player_id, value):
        value = self.owned(player_id, value)['id']
        from shards.management import FragmentManagement
        return FragmentManagement(self.store).search(mine=player_id,account=value)
