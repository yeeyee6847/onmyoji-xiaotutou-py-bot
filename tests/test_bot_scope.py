import importlib.util
import unittest
from unittest.mock import AsyncMock,patch

HAS_DISCORD=bool(importlib.util.find_spec('discord'))
if HAS_DISCORD:
    from discord_bot import LoginBot


@unittest.skipUnless(HAS_DISCORD,'Install requirements-bot.txt')
class BotScopeChecks(unittest.IsolatedAsyncioTestCase):
    async def check_scope(self,guild):
        bot=LoginBot()
        async with bot:
            bot.http.upsert_global_command=AsyncMock()
            bot.http.upsert_guild_command=AsyncMock()
            bot.tree.sync=AsyncMock()
            with patch.dict('os.environ',{'WEBSITE_URL':'http://127.0.0.1:5000','DISCORD_GUILD_ID':guild}):
                await bot.setup_hook()
            bot.tree.sync.assert_not_awaited()
            active=bot.http.upsert_guild_command if guild else bot.http.upsert_global_command
            inactive=bot.http.upsert_global_command if guild else bot.http.upsert_guild_command
            self.assertEqual(active.await_count,2)
            inactive.assert_not_awaited()
            self.assertEqual({call.args[-1]['name'] for call in active.await_args_list},{'login','fragments'})

    async def test_default_registers_only_global(self):await self.check_scope('')
    async def test_explicit_guild_registers_only_that_guild(self):await self.check_scope('123456789012345678')
