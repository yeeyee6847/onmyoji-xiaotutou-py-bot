"""Optional standalone bot. Existing bots should load the discord_login extension instead."""
import os

import discord
from discord.ext import commands

from auth_service import current_website_origin


class LoginBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=discord.Intents.default())

    async def setup_hook(self):
        current_website_origin()  # Fail before registering commands if deployment configuration is missing.
        await self.load_extension('discord_login')
        await self.load_extension('discord_trades')
        guild_id = os.getenv('DISCORD_GUILD_ID')
        for command in self.tree.get_commands():
            payload=command.to_dict(self.tree)
            if guild_id:
                guild = discord.Object(id=int(guild_id))
                self.tree.copy_global_to(guild=guild)
                await self.http.upsert_guild_command(self.application_id, guild.id, payload)
            else:
                await self.http.upsert_global_command(self.application_id, payload)
            
        print("Slash commands registered in one scope only.",flush=True)


if __name__ == '__main__':
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        raise SystemExit('请先在 .env 或服务环境中设置 DISCORD_TOKEN。')
    LoginBot().run(token)
