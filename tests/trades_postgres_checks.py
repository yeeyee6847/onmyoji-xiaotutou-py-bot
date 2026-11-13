from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import secrets
import unittest

from lottery import DrawError
from shards.accounts import GameAccounts
from shards.management import FragmentManagement
from shards.trades import Trades
from storage import PostgresStore


class SavepointStore:
    def __init__(self,c):self.c=c
    @contextmanager
    def connection(self):
        with self.c.transaction():yield self.c


def fixture(c):
    players=[]
    for name in ('Trade check A','Trade check B','Trade observer'):
        p=str(c.execute('INSERT INTO onmyoji_shards.players(display_name) VALUES (%s) RETURNING id',(name,)).fetchone()[0]);players.append(p)
        uid='6'+''.join(str(secrets.randbelow(10)) for _ in range(18))
        c.execute("INSERT INTO onmyoji_shards.player_identities(player_id,provider,external_subject) VALUES (%s,'discord',%s)",(p,uid))
    store=SavepointStore(c);accounts=GameAccounts(store);stock=FragmentManagement(store)
    a=accounts.create(players[0],dict(nickname='A'));b=accounts.create(players[1],dict(nickname='B'))
    shiki=[r[0] for r in c.execute('SELECT id::text FROM onmyoji_shards.shikigami WHERE is_active ORDER BY id LIMIT 2').fetchall()]
    for p,account,offer,want,qty in [(players[0],a,shiki[0],shiki[1],10),(players[1],b,shiki[1],shiki[0],12)]:
        stock.write(p,dict(game_account_id=account['id'],items=[dict(shikigami_id=offer,target='offers',quantity=qty),dict(shikigami_id=want,target='wants',quantity=7)]))
    return players,a,b,shiki


class TradeChecks(unittest.TestCase):
    def setUp(self):
        self.outer=PostgresStore().connection();self.c=self.outer.__enter__()
        def cleanup():self.c.rollback();self.outer.__exit__(None,None,None)
        self.addCleanup(cleanup)
        self.players,self.a,self.b,self.shiki=fixture(self.c)
        self.service=Trades(SavepointStore(self.c));self.stock=FragmentManagement(SavepointStore(self.c))
        self.baseline_offers=self.stock.totals()[self.shiki[0]]['offers']-10

    def create(self,give=4,receive=3):
        return self.service.create(self.players[0],dict(game_account_id=self.a['id'],other_account_id=self.b['id'],items=[dict(direction='give',shikigami_id=self.shiki[0],quantity=give),dict(direction='receive',shikigami_id=self.shiki[1],quantity=receive)]))['id']

    def quantity(self,account,shiki):return self.c.execute("SELECT quantity FROM onmyoji_shards.fragment_current WHERE game_account_id=%s AND shikigami_id=%s AND target='offers'",(account,shiki)).fetchone()[0]

    def test_accept_reserves_and_both_confirm_deduct_exactly_once(self):
        trade=self.create();self.assertEqual(self.c.execute('SELECT count(*) FROM onmyoji_shards.trade_reservations WHERE trade_id=%s',(trade,)).fetchone()[0],0)
        self.service.action(self.players[1],trade,'accept');self.service.action(self.players[1],trade,'accept')
        self.assertEqual(self.stock.totals()[self.shiki[0]]['offers'],self.baseline_offers+6)
        self.assertEqual(self.quantity(self.a['id'],self.shiki[0]),10)
        self.assertEqual(self.service.action(self.players[0],trade,'confirm')['status'],'accepted')
        self.assertEqual(self.quantity(self.a['id'],self.shiki[0]),10)
        self.assertEqual(self.service.action(self.players[1],trade,'confirm')['status'],'completed')
        self.service.action(self.players[1],trade,'confirm')
        self.assertEqual(self.quantity(self.a['id'],self.shiki[0]),6)
        self.assertEqual(self.quantity(self.b['id'],self.shiki[1]),9)
        self.assertEqual(self.c.execute('SELECT count(*) FROM onmyoji_shards.trade_reservations WHERE trade_id=%s',(trade,)).fetchone()[0],0)
        with self.assertRaises(DrawError):self.service.action(self.players[0],trade,'cancel')

    def test_cancel_after_one_confirmation_releases_without_deducting(self):
        trade=self.create();self.service.action(self.players[1],trade,'accept');self.service.action(self.players[0],trade,'confirm')
        self.service.action(self.players[1],trade,'cancel');self.service.action(self.players[0],trade,'cancel')
        self.assertEqual(self.stock.totals()[self.shiki[0]]['offers'],self.baseline_offers+10)
        self.assertEqual(self.quantity(self.a['id'],self.shiki[0]),10)
        self.assertEqual(self.c.execute('SELECT count(*) FROM onmyoji_shards.trade_reservations WHERE trade_id=%s',(trade,)).fetchone()[0],0)

    def test_only_recipient_can_accept_or_reject_and_notifications_are_targeted(self):
        trade=self.create()
        self.assertEqual(self.c.execute("SELECT recipients FROM onmyoji_shards.trade_outbox WHERE trade_id=%s AND event='requested'",(trade,)).fetchone()[0],[self.players[1]])
        for actor in (self.players[0],self.players[2]):
            with self.assertRaises(DrawError):self.service.action(actor,trade,'accept')
        with self.assertRaises(DrawError):self.service.listing(self.players[2],identity=trade)
        self.service.action(self.players[1],trade,'reject')
        self.assertEqual(self.c.execute("SELECT recipients FROM onmyoji_shards.trade_outbox WHERE trade_id=%s AND event='rejected'",(trade,)).fetchone()[0],[self.players[0]])
        self.assertEqual(self.service.listing(self.players[2]),[])

    def test_quantity_updates_cannot_overwrite_reserved(self):
        trade=self.create();self.service.action(self.players[1],trade,'accept')
        with self.assertRaises(DrawError):self.stock.write(self.players[0],dict(game_account_id=self.a['id'],items=[dict(shikigami_id=self.shiki[0],target='offers',quantity=3)]))
        self.stock.write(self.players[0],dict(game_account_id=self.a['id'],items=[dict(shikigami_id=self.shiki[0],target='offers',quantity=8)]))
        self.assertEqual(self.stock.totals()[self.shiki[0]]['offers'],self.baseline_offers+4)
        self.assertEqual(len(self.service.listing(self.players[2],shikigami_id=self.shiki[0])),1)

    def test_reserved_record_cannot_be_deleted_until_cancelled(self):
        trade=self.create();self.service.action(self.players[1],trade,'accept')
        for player,account,shiki,target in [
            (self.players[0],self.a['id'],self.shiki[0],'offers'),
            (self.players[0],self.a['id'],self.shiki[1],'wants'),
        ]:
            with self.assertRaises(DrawError) as error:
                self.stock.delete(player,dict(game_account_id=account,shikigami_id=shiki,target=target))
            self.assertEqual(error.exception.status,409)
        self.assertEqual(self.quantity(self.a['id'],self.shiki[0]),10)
        self.service.action(self.players[0],trade,'cancel')
        self.stock.delete(self.players[0],dict(game_account_id=self.a['id'],shikigami_id=self.shiki[0],target='offers'))
        self.assertEqual(self.stock.search(mine=self.players[0],account=self.a['id'],target='offers'),[])

    def test_failed_accept_rolls_back_all_reservations(self):
        first=self.create();second=self.create(2,11)
        self.service.action(self.players[1],first,'accept')
        with self.assertRaises(DrawError):self.service.action(self.players[1],second,'accept')
        self.assertEqual(self.c.execute('SELECT count(*) FROM onmyoji_shards.trade_reservations WHERE trade_id=%s',(second,)).fetchone()[0],0)
        self.assertEqual(self.service.listing(self.players[0],identity=second)[0]['status'],'pending')

    def test_own_accounts_and_malformed_quantities_rejected(self):
        with self.assertRaises(DrawError):self.service.create(self.players[1],dict(game_account_id=self.a['id'],other_account_id=self.b['id'],items=[]))
        with self.assertRaises(DrawError):self.create(0,2)
        with self.assertRaises(DrawError):self.service.action(self.players[0],'bad-uuid','accept')


class TradeRaceCheck(unittest.TestCase):
    def test_competing_acceptances_cannot_reserve_same_stock_twice(self):
        with PostgresStore().connection() as c:
            players,a,b,shiki=fixture(c);service=Trades(SavepointStore(c));ids=[]
            for _ in range(2):ids.append(service.create(players[0],dict(game_account_id=a['id'],other_account_id=b['id'],items=[dict(direction='give',shikigami_id=shiki[0],quantity=7),dict(direction='receive',shikigami_id=shiki[1],quantity=6)]))['id'])
            # Never deliver synthetic test notifications if a real bot is running concurrently.
            c.execute("UPDATE onmyoji_shards.trade_outbox SET status='sent' WHERE trade_id=ANY(%s::uuid[])",(ids,))
        try:
            def accept(identity):
                try:
                    with PostgresStore().connection() as c:
                        Trades(SavepointStore(c)).action(players[1],identity,'accept')
                        c.execute("UPDATE onmyoji_shards.trade_outbox SET status='sent' WHERE trade_id=%s",(identity,))
                    return True
                except DrawError:return False
            with ThreadPoolExecutor(max_workers=2) as pool:out=list(pool.map(accept,ids))
            self.assertEqual(out.count(True),1)
            with PostgresStore().connection() as c:
                self.assertEqual(c.execute("SELECT sum(quantity) FROM onmyoji_shards.trade_reservations WHERE game_account_id=%s AND target='offers'",(a['id'],)).fetchone()[0],7)
        finally:
            with PostgresStore().connection() as c:
                c.execute('DELETE FROM onmyoji_shards.trades WHERE id=ANY(%s::uuid[])',(ids,))
                c.execute('DELETE FROM onmyoji_shards.players WHERE id=ANY(%s::uuid[])',(players,))


if __name__=='__main__':unittest.main()
