import importlib.util
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock,patch

HAS_DISCORD=bool(importlib.util.find_spec('discord'))
if HAS_DISCORD:
    from discord_trades import TradeNotifications,TradeDecision


class FakeDM:
    def __init__(self):self.messages=[];self.send=AsyncMock(side_effect=self.record)
    async def record(self,text,**kwargs):self.messages.insert(0,SimpleNamespace(content=text,author=SimpleNamespace(id=99)))
    async def history(self,limit):
        for row in self.messages[:limit]:yield row


@unittest.skipUnless(HAS_DISCORD,'Install requirements-bot.txt for Discord tests')
class TradeBotChecks(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.a='11111111-1111-4111-8111-111111111111';self.b='22222222-2222-4222-8222-222222222222'
        self.id='33333333-3333-4333-8333-333333333333';self.dm=FakeDM()
        self.user=SimpleNamespace(create_dm=AsyncMock(return_value=self.dm))
        self.bot=SimpleNamespace(user=SimpleNamespace(id=99),fetch_user=AsyncMock(return_value=self.user),fetch_channel=AsyncMock())
        self.cog=TradeNotifications.__new__(TradeNotifications);self.cog.bot=self.bot
        self.route=dict(discord_ids=['111111111111111111','222222222222222222'],player_ids=[self.a,self.b],threads={},status='pending')
        detail=dict(requester_name='A',requester_account_name='A account',recipient_name='B',recipient_account_name='B account',items=[dict(direction='give',name='Test',quantity=3)])
        self.cog.service=SimpleNamespace(notification=Mock(return_value=self.route),discord_player=Mock(return_value=self.a),listing=Mock(return_value=[detail]))
        self.env=patch.dict('os.environ',{'DISCORD_TRADE_MODE':'dm','WEBSITE_URL':'https://example.test'});self.env.start();self.addCleanup(self.env.stop)

    async def test_request_only_recipient_gets_message_and_retry_deduplicates(self):
        row=(1,self.id,'requested',[self.b]);await self.cog.deliver(row)
        self.bot.fetch_user.assert_awaited_once_with(222222222222222222)
        view=self.dm.send.call_args.kwargs['view'];self.assertEqual(len(view.children),2)
        self.bot.fetch_channel.assert_not_awaited()
        await self.cog.deliver(row);self.assertEqual(self.dm.send.await_count,1)

    async def test_rejection_only_initiator_gets_message(self):
        self.route['status']='rejected';await self.cog.deliver((2,self.id,'rejected',[self.a]))
        self.bot.fetch_user.assert_awaited_once_with(111111111111111111)
        self.assertIn('拒絕',self.dm.send.call_args.args[0]);self.assertEqual(len(self.dm.send.call_args.kwargs['view'].children),0)

    async def test_dm_failure_never_falls_back_to_public_channel(self):
        self.user.create_dm.side_effect=PermissionError('DM blocked')
        with self.assertRaises(PermissionError):await self.cog.deliver((1,self.id,'requested',[self.b]))
        self.bot.fetch_channel.assert_not_awaited();self.dm.send.assert_not_awaited()

    async def test_persistent_button_has_stable_trade_and_action(self):
        button=TradeDecision(self.id,'accept')
        self.assertEqual(button.item.custom_id,'trade:accept:'+self.id)


if __name__=='__main__':unittest.main()
