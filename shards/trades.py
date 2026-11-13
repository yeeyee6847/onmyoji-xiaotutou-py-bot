import uuid
from psycopg.types.json import Jsonb

from lottery import DrawError
from shards.accounts import account_id
from shards.reservations import reserved
from storage import PostgresStore


class Trades:
    def __init__(self,store=None):self.store=store if store is not None else PostgresStore()

    def partners(self, player):
        with self.store.connection() as c:
            rows=c.execute('''SELECT a.id::text,a.nickname,a.server_name,p.display_name
             FROM onmyoji_shards.game_accounts a JOIN onmyoji_shards.players p ON p.id=a.player_id
             WHERE a.is_active AND p.is_active AND a.player_id<>%s
             AND EXISTS (SELECT 1 FROM onmyoji_shards.fragment_current f
              JOIN onmyoji_shards.shikigami s ON s.id=f.shikigami_id AND s.is_active
              WHERE f.game_account_id=a.id AND f.target='offers' AND f.quantity>coalesce(
               (SELECT sum(r.quantity) FROM onmyoji_shards.trade_reservations r WHERE
                r.game_account_id=a.id AND r.shikigami_id=f.shikigami_id AND r.target='offers'),0))
             ORDER BY p.display_name,a.nickname,a.id''',(player,)).fetchall()
        return [dict(id=r[0],nickname=r[1],server_name=r[2],player_name=r[3]) for r in rows]

    def discord_player(self,discord_id):
        with self.store.connection() as c:
            row=c.execute("SELECT p.id::text FROM onmyoji_shards.players p JOIN onmyoji_shards.player_identities i ON i.player_id=p.id WHERE i.provider='discord' AND i.external_subject=%s AND p.is_active",(str(discord_id),)).fetchone()
        if not row:raise DrawError('请先使用 /login 注册并登录网站。',403)
        return row[0]

    def _accounts(self,c,ids):
        rows=c.execute('''SELECT a.id::text,a.player_id::text FROM onmyoji_shards.game_accounts a
         JOIN onmyoji_shards.players p ON p.id=a.player_id WHERE a.id=ANY(%s::uuid[]) AND a.is_active AND p.is_active
         ORDER BY a.id FOR UPDATE OF a''',(list(ids),)).fetchall()
        if len(rows)!=2:raise DrawError('游戏账号不存在或已停用。',409)
        return dict(rows)

    def _items(self,c,trade):
        return c.execute('''SELECT i.direction,i.shikigami_id::text,i.quantity,s.name FROM onmyoji_shards.trade_items i
         JOIN onmyoji_shards.shikigami s ON s.id=i.shikigami_id WHERE i.trade_id=%s ORDER BY i.direction,i.shikigami_id''',(trade,)).fetchall()

    def _event(self,c,trade,event,recipients):
        c.execute('INSERT INTO onmyoji_shards.trade_outbox(trade_id,event,recipients) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING',(trade,event,Jsonb(recipients)))

    def _stock(self,c,account,shikigami,target):
        row=c.execute('SELECT quantity FROM onmyoji_shards.fragment_current WHERE game_account_id=%s AND shikigami_id=%s AND target=%s',(account,shikigami,target)).fetchone()
        return (row[0] if row else 0)-reserved(c,account,shikigami,target)

    def create(self,player,payload):
        if not isinstance(payload,dict):raise DrawError('交换格式不正确。')
        own,other=account_id(payload.get('game_account_id')),account_id(payload.get('other_account_id'))
        if own==other:raise DrawError('不能与自己交换。')
        lines=payload.get('items');checked=[];seen=set()
        if not isinstance(lines,list) or not 2<=len(lines)<=40:raise DrawError('请填写双方各至少一项，最多 40 项。')
        for item in lines:
            if not isinstance(item,dict):raise DrawError('交换项目格式不正确。')
            direction=item.get('direction');identity=account_id(item.get('shikigami_id'));quantity=item.get('quantity')
            if direction not in ('give','receive') or type(quantity) is not int or not 1<=quantity<=99999:raise DrawError('请填写双方提供的式神与正整数数量。')
            if (direction,identity) in seen:raise DrawError('同一方提供的式神重复。')
            seen.add((direction,identity));checked.append((direction,identity,quantity))
        if {r[0] for r in checked}!={'give','receive'}:raise DrawError('双方都需要填写提供的碎片。')
        with self.store.connection() as c:
            accounts=self._accounts(c,[own,other])
            if accounts[own]!=player:raise DrawError('只能使用自己的游戏账号。',403)
            if accounts[other]==player:raise DrawError('不能与自己的其他账号交换。')
            if len(c.execute("SELECT DISTINCT player_id FROM onmyoji_shards.player_identities WHERE provider='discord' AND player_id=ANY(%s::uuid[])",([player,accounts[other]],)).fetchall())!=2:
                raise DrawError('双方需要绑定 Discord 账号。')
            ids=list({r[1] for r in checked})
            if len(c.execute('SELECT id FROM onmyoji_shards.shikigami WHERE id=ANY(%s::uuid[]) AND is_active',(ids,)).fetchall())!=len(ids):raise DrawError('式神不存在或已停用。')
            for direction,identity,quantity in checked:
                if self._stock(c,own if direction=='give' else other,identity,'offers')<quantity:raise DrawError('可提供数量不足或已被预留，请刷新后重试。',409)
            trade=str(uuid.uuid4())
            c.execute('''INSERT INTO onmyoji_shards.trades(id,requester_id,recipient_id,requester_account,recipient_account)
             VALUES (%s,%s,%s,%s,%s)''',(trade,player,accounts[other],own,other))
            for direction,identity,quantity in checked:c.execute('INSERT INTO onmyoji_shards.trade_items VALUES (%s,%s,%s,%s)',(trade,direction,identity,quantity))
            self._event(c,trade,'requested',[accounts[other]])
        return dict(id=trade,status='pending')

    def action(self,player,identity,action):
        identity=account_id(identity)
        if action not in ('accept','reject','cancel','confirm'):raise DrawError('无效的交换操作。')
        with self.store.connection() as c:
            row=c.execute('''SELECT requester_id::text,recipient_id::text,requester_account::text,recipient_account::text,
             status,requester_confirmed,recipient_confirmed FROM onmyoji_shards.trades WHERE id=%s FOR UPDATE''',(identity,)).fetchone()
            if not row:raise DrawError('找不到交换。',404)
            sender,recipient,a,b,status,ca,cb=row
            if player not in (sender,recipient):raise DrawError('只有交换当事人可以操作。',403)
            if action in ('accept','reject') and player!=recipient:raise DrawError('只有收到申请的玩家可以接受或拒绝。',403)
            if (action=='accept' and status=='accepted') or (action=='reject' and status=='rejected') or (action=='cancel' and status=='cancelled') or (action=='confirm' and status=='completed'):
                return dict(id=identity,status=status)
            if status not in ('pending','accepted'):raise DrawError('交换已经结束。',409)
            if action in ('accept','reject') and status!='pending':raise DrawError('申请已处理。',409)
            if action=='confirm' and status!='accepted':raise DrawError('请先等待对方接受申请。',409)
            if action in ('accept','confirm'):
                accounts=self._accounts(c,[a,b])
                if accounts[a]!=sender or accounts[b]!=recipient:raise DrawError('账号归属已变更。',409)
            items=self._items(c,identity)
            if action=='accept':
                for direction,shiki,qty,_ in items:
                    giver,receiver=(a,b) if direction=='give' else (b,a)
                    if self._stock(c,giver,shiki,'offers')<qty:raise DrawError('碎片数量不足，不能接受；请取消或重新申请。',409)
                    c.execute('INSERT INTO onmyoji_shards.trade_reservations VALUES (%s,%s,%s,%s,%s)',(identity,giver,shiki,'offers',qty))
                    wanted=min(qty,max(0,self._stock(c,receiver,shiki,'wants')))
                    if wanted:c.execute('INSERT INTO onmyoji_shards.trade_reservations VALUES (%s,%s,%s,%s,%s)',(identity,receiver,shiki,'wants',wanted))
                status='accepted';self._event(c,identity,'accepted',[sender])
            elif action in ('cancel','reject'):
                # Account locks serialize releasing reservations with quantity edits and other accepts.
                c.execute('SELECT id FROM onmyoji_shards.game_accounts WHERE id=ANY(%s::uuid[]) ORDER BY id FOR UPDATE',([a,b],))
                c.execute('DELETE FROM onmyoji_shards.trade_reservations WHERE trade_id=%s',(identity,))
                status='cancelled' if action=='cancel' else 'rejected';self._event(c,identity,status,[recipient if player==sender else sender])
            else:
                ca=ca or player==sender;cb=cb or player==recipient
                if ca and cb:
                    reservations=c.execute('SELECT game_account_id,shikigami_id,target,quantity FROM onmyoji_shards.trade_reservations WHERE trade_id=%s',(identity,)).fetchall()
                    if not reservations:raise DrawError('预留记录缺失，请联系管理员。',409)
                    expected={(a if direction=='give' else b,shiki):qty for direction,shiki,qty,_ in items}
                    actual={(str(account),str(shiki)):qty for account,shiki,target,qty in reservations if target=='offers'}
                    if expected!=actual:raise DrawError('交换预留记录不完整，请联系管理员。',409)
                    for account,shiki,target,qty in reservations:
                        if self._stock(c,account,shiki,target)<0:raise DrawError('库存低于预留数量，请联系管理员。',409)
                        changed=c.execute('''UPDATE onmyoji_shards.fragment_current SET quantity=quantity-%s,updated_at=clock_timestamp()
                         WHERE game_account_id=%s AND shikigami_id=%s AND target=%s AND quantity>=%s''',(qty,account,shiki,target,qty))
                        if changed.rowcount!=1:raise DrawError('预留库存已变更，请联系管理员。',409)
                    c.execute('DELETE FROM onmyoji_shards.trade_reservations WHERE trade_id=%s',(identity,))
                    status='completed';self._event(c,identity,'completed',[sender,recipient])
                else:self._event(c,identity,'confirmed-'+player,[recipient if player==sender else sender])
            c.execute('UPDATE onmyoji_shards.trades SET status=%s,requester_confirmed=%s,recipient_confirmed=%s,updated_at=now() WHERE id=%s',(status,ca,cb,identity))
        return dict(id=identity,status=status)

    def listing(self,player=None,mine=False,identity=None,shikigami_id=None):
        conditions=[];args=[]
        if identity:conditions.append('t.id=%s');args.append(account_id(identity))
        elif mine:conditions.append('(t.requester_id=%s OR t.recipient_id=%s)');args.extend([player,player])
        else:conditions.append("t.status='accepted'")
        if shikigami_id:
            conditions.append('EXISTS(SELECT 1 FROM onmyoji_shards.trade_items ti WHERE ti.trade_id=t.id AND ti.shikigami_id=%s)');args.append(account_id(shikigami_id))
        with self.store.connection() as c:
            rows=c.execute('''SELECT t.id::text,t.status,t.requester_id::text,t.recipient_id::text,
             p.display_name,q.display_name,a.nickname,b.nickname,t.requester_confirmed,t.recipient_confirmed,t.created_at,
             t.requester_account::text,t.recipient_account::text,
             (SELECT o.status FROM onmyoji_shards.trade_outbox o WHERE o.trade_id=t.id ORDER BY o.id DESC LIMIT 1)
             FROM onmyoji_shards.trades t JOIN onmyoji_shards.players p ON p.id=t.requester_id
             JOIN onmyoji_shards.players q ON q.id=t.recipient_id JOIN onmyoji_shards.game_accounts a ON a.id=t.requester_account
             JOIN onmyoji_shards.game_accounts b ON b.id=t.recipient_account WHERE '''+' AND '.join(conditions)+" ORDER BY CASE WHEN t.status IN ('pending','accepted') THEN 0 ELSE 1 END,t.created_at DESC LIMIT 200",args).fetchall()
            result=[]
            for r in rows:
                involved=player in (r[2],r[3])
                if identity and not involved and r[1]!='accepted':raise DrawError('没有权限查看此申请。',403)
                result.append(dict(id=r[0],status=r[1],requester_name=r[4],recipient_name=r[5],requester_account_name=r[6],recipient_account_name=r[7],
                 requester_confirmed=r[8],recipient_confirmed=r[9],created_at=r[10].isoformat(),
                 notification_status=r[13] if involved else None,
                 my_side='requester' if player==r[2] else 'recipient' if player==r[3] else None,
                 requester_account=r[11],recipient_account=r[12],items=[dict(direction=i[0],shikigami_id=i[1],quantity=i[2],name=i[3]) for i in self._items(c,r[0])]))
        return result

    def retry_notification(self,player,identity):
        identity=account_id(identity)
        with self.store.connection() as c:
            row=c.execute('SELECT requester_id::text,recipient_id::text FROM onmyoji_shards.trades WHERE id=%s',(identity,)).fetchone()
            if not row or player not in row:raise DrawError('只能重试自己的交换通知。',403)
            c.execute("UPDATE onmyoji_shards.trade_outbox SET status='pending',attempts=0,next_attempt_at=now(),last_error=NULL WHERE trade_id=%s AND status='failed'",(identity,))
        return dict(queued=True)

    def notification(self,identity):
        with self.store.connection() as c:
            r=c.execute('''SELECT requester_id::text,recipient_id::text,notification_threads,status FROM onmyoji_shards.trades WHERE id=%s''',(identity,)).fetchone()
            if not r:raise DrawError('交换不存在。',404)
            ids=[]
            for player in r[:2]:
                d=c.execute("SELECT external_subject FROM onmyoji_shards.player_identities WHERE provider='discord' AND player_id=%s ORDER BY id LIMIT 1",(player,)).fetchone()
                if not d:raise DrawError('Discord 身份不存在。',409)
                ids.append(d[0])
        return dict(discord_ids=ids,player_ids=list(r[:2]),threads=r[2],status=r[3])
