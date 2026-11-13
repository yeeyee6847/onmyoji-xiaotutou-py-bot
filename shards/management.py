import uuid

from lottery import DrawError
from shards.accounts import account_id
from storage import PostgresStore
from shards.reservations import guard_quantity


class FragmentManagement:
    def __init__(self, store=None):
        self.store = store if store is not None else PostgresStore()

    def delete(self, player_id, payload):
        if not isinstance(payload, dict):
            raise DrawError('资料格式不正确。')
        account = account_id(payload.get('game_account_id'))
        identity = account_id(payload.get('shikigami_id'))
        target = payload.get('target')
        if target not in ('offers', 'wants'):
            raise DrawError('请选择提供或想要。')
        with self.store.connection() as conn:
            owner = conn.execute('''SELECT id FROM onmyoji_shards.game_accounts
             WHERE id=%s AND player_id=%s AND is_active FOR UPDATE''', (account, player_id)).fetchone()
            if not owner:
                raise DrawError('找不到你的游戏账号。', 404)
            guard_quantity(conn, account, identity, target, 0)
            conn.execute('''DELETE FROM onmyoji_shards.fragment_current
             WHERE game_account_id=%s AND shikigami_id=%s AND target=%s''', (account, identity, target))
        return dict(deleted=True)

    def write(self, player_id, payload):
        if not isinstance(payload,dict):
            raise DrawError('资料格式不正确。')
        account = account_id(payload.get('game_account_id'))
        rows = payload.get('items')
        if not isinstance(rows,list) or not 1 <= len(rows) <= 200:
            raise DrawError('请填写 1–200 条碎片记录。')
        checked=[]; seen=set()
        for row in rows:
            if not isinstance(row,dict): raise DrawError('碎片记录格式不正确。')
            identity=account_id(row.get('shikigami_id')); target=row.get('target'); quantity=row.get('quantity')
            if target not in ('offers','wants') or type(quantity) is not int or not 0<=quantity<=99999:
                raise DrawError('请选择提供或想要，数量为 0–99999 的整数。')
            if (identity,target) in seen: raise DrawError('同一清单内式神重复。')
            seen.add((identity,target));checked.append((identity,target,quantity))
        with self.store.connection() as conn:
            owner=conn.execute('SELECT id FROM onmyoji_shards.game_accounts WHERE id=%s AND player_id=%s AND is_active FOR UPDATE',(account,player_id)).fetchone()
            if not owner: raise DrawError('找不到你的游戏账号。',404)
            ids=list({r[0] for r in checked})
            if len(conn.execute('SELECT id FROM onmyoji_shards.shikigami WHERE id=ANY(%s::uuid[]) AND is_active',(ids,)).fetchall())!=len(ids):
                raise DrawError('式神不存在或已停用。')
            for identity,target,quantity in checked:
                guard_quantity(conn,account,identity,target,quantity)
                conn.execute('''INSERT INTO onmyoji_shards.fragment_current(game_account_id,shikigami_id,target,quantity)
                 VALUES (%s,%s,%s,%s) ON CONFLICT(game_account_id,shikigami_id,target)
                 DO UPDATE SET quantity=EXCLUDED.quantity,updated_at=clock_timestamp()''',(account,identity,target,quantity))
        return dict(saved=True,count=len(checked))

    def search(self, shikigami_id=None, target=None, server='', mine=None, account=None,rarity=None):
        if target not in (None,'','offers','wants'): raise DrawError('无效的碎片分类。')
        conditions=['a.is_active','p.is_active','s.is_active'];params=[]
        if rarity:
            if rarity not in ('SSR','SP','UR','COLLAB'):raise DrawError('无效的 Rarity。')
            conditions.append('s.rarity=%s');params.append(rarity)
        for clause,value in [('c.shikigami_id=%s',account_id(shikigami_id) if shikigami_id else None),
                             ('c.target=%s',target or None),('a.player_id=%s',mine),('a.id=%s',account_id(account) if account else None)]:
            if value is not None:conditions.append(clause);params.append(value)
        if mine is None: conditions.append('c.quantity-coalesce(r.reserved,0)>0')
        if server:
            if len(server)>80:raise DrawError('服务器搜索最多 80 字。')
            conditions.append('strpos(lower(a.server_name),lower(%s))>0');params.append(server)
        with self.store.connection() as conn:
            rows=conn.execute('''SELECT c.shikigami_id::text,s.name,s.rarity,c.target,c.quantity,
             a.id::text,a.nickname,a.server_name,p.display_name,c.updated_at,coalesce(r.reserved,0)
             FROM onmyoji_shards.fragment_current c JOIN onmyoji_shards.game_accounts a ON a.id=c.game_account_id
             JOIN onmyoji_shards.players p ON p.id=a.player_id JOIN onmyoji_shards.shikigami s ON s.id=c.shikigami_id
             LEFT JOIN (SELECT game_account_id,shikigami_id,target,sum(quantity) AS reserved FROM onmyoji_shards.trade_reservations
              GROUP BY game_account_id,shikigami_id,target) r ON r.game_account_id=c.game_account_id AND r.shikigami_id=c.shikigami_id AND r.target=c.target
             WHERE '''+' AND '.join(conditions)+''' ORDER BY s.display_order DESC NULLS LAST,c.target,c.quantity DESC,a.id LIMIT 1000''',params).fetchall()
        return [dict(shikigami_id=r[0],name=r[1],rarity=r[2],target=r[3],quantity=r[4] if mine else r[4]-r[10],reserved=r[10],available=r[4]-r[10],game_account_id=r[5],
                     nickname=r[6],server_name=r[7],player_name=r[8],updated_at=r[9].isoformat()) for r in rows]

    def totals(self):
        with self.store.connection() as conn:
            rows=conn.execute('''SELECT c.shikigami_id::text,c.target,sum(c.quantity-coalesce(r.reserved,0)),sum(coalesce(r.reserved,0))
             FROM onmyoji_shards.fragment_current c JOIN onmyoji_shards.game_accounts a ON a.id=c.game_account_id
             JOIN onmyoji_shards.players p ON p.id=a.player_id
             LEFT JOIN (SELECT game_account_id,shikigami_id,target,sum(quantity) AS reserved FROM onmyoji_shards.trade_reservations
              GROUP BY game_account_id,shikigami_id,target) r ON r.game_account_id=c.game_account_id AND r.shikigami_id=c.shikigami_id AND r.target=c.target
             WHERE a.is_active AND p.is_active
             GROUP BY c.shikigami_id,c.target''').fetchall()
        result={}
        for identity,target,total,reserved in rows:
            entry=result.setdefault(identity,dict(offers=0,wants=0));entry[target]=int(total)
            if reserved:entry[target+'_reserved']=int(reserved)
        return result
