"""discord.py extension: await bot.load_extension('discord_login')."""
import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from auth_service import AuthService, current_website_origin
from lottery import DrawError


class WebsiteLogin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.auth = AuthService()

    @app_commands.command(name='login', description='取得网站的一次性登入连结 / Get a one-time website login link')
    @app_commands.checks.cooldown(1, 30, key=lambda interaction: interaction.user.id)
    async def login(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            link = await asyncio.to_thread(self.auth.issue_link, str(interaction.user.id),
                                           interaction.user.display_name, current_website_origin())
            view = discord.ui.View(timeout=600)
            view.add_item(discord.ui.Button(label='登入网站', style=discord.ButtonStyle.link, url=link))
            await interaction.followup.send(
                '这是你的专属登入连结，10 分钟内有效、只能使用一次。重新执行 /login 会使旧连结失效。\n'
                '请勿转发：任何取得连结的人都能登入你的账号。登入后可设置网站密码。',
                view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        except DrawError as error:
            await interaction.followup.send(str(error), ephemeral=True)
        except Exception:
            # Never print interaction payloads, DB exceptions or bearer links.
            await interaction.followup.send('暂时无法产生登入连结，请稍后重试。', ephemeral=True)

    @login.error
    async def login_error(self, interaction, error):
        text = '请稍等 30 秒再执行 /login。' if isinstance(error, app_commands.CommandOnCooldown) else '登入指令暂时无法使用。'
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)


async def setup(bot):
    await bot.add_cog(WebsiteLogin(bot))
