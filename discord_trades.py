"""Discord exchange notifications, persistent buttons, and fragment search."""
import asyncio
import os
import uuid

import discord
from discord import app_commands
from discord.ext import commands,tasks

from auth_service import current_website_origin
from lottery import DrawError
from shards.catalog import PostgresCatalog
from shards.management import FragmentManagement
from shards.trades import Trades
from shards.vision import recognition_name
from storage import PostgresStore


class TradeDecision(discord.ui.DynamicItem[discord.ui.Button],template=r'trade:(?P<action>accept|reject):(?P<id>[a-f0-9-]{36})'):
    def __init__(self,identity,action):
        self.identity,self.action=identity,action
        super().__init__(discord.ui.Button(label='接受交換' if action=='accept' else '拒絕交換',
            style=discord.ButtonStyle.success if action=='accept' else discord.ButtonStyle.danger,custom_id=f'trade:{action}:{identity}'))

    @classmethod
    async def from_custom_id(cls,interaction,item,match):return cls(match['id'],match['action'])

    async def callback(self,interaction):
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:
            service=Trades();player=await asyncio.to_thread(service.discord_player,str(interaction.user.id))
            result=await asyncio.to_thread(service.action,player,self.identity,self.action)
            await interaction.followup.send('已處理：'+result['status']+'。完成交換請到網站由雙方確認。',ephemeral=True)
        except DrawError as error:await interaction.followup.send(str(error),ephemeral=True)
        except Exception:await interaction.followup.send('暫時無法處理，請到網站查看交換狀態。',ephemeral=True)


class TradeNotifications(commands.Cog):
    def __init__(self,bot):
        self.bot=bot;self.service=Trades();self.worker.start()

    def cog_unload(self):self.worker.cancel();self.bot.remove_dynamic_items(TradeDecision)

    def claim(self):
        with PostgresStore().connection() as c:
            token=str(uuid.uuid4())
            row=c.execute('''UPDATE onmyoji_shards.trade_outbox SET status='sending',attempts=attempts+1,
             lease_until=now()+interval '3 minutes',lease_token=%s WHERE id=(SELECT id FROM onmyoji_shards.trade_outbox
             WHERE attempts<8 AND next_attempt_at<=now() AND (status IN ('pending','failed') OR (status='sending' AND lease_until<now()))
             ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING id,trade_id::text,event,recipients''',(token,)).fetchone()
        return (row,token) if row else (None,None)

    def acknowledge(self,row,token,error=None):
        with PostgresStore().connection() as c:
            c.execute('''UPDATE onmyoji_shards.trade_outbox SET status=%s,last_error=%s,lease_until=NULL,
             next_attempt_at=now()+interval '1 minute' WHERE id=%s AND lease_token=%s''',
             ('failed' if error else 'sent',error,row[0],token))

    async def deliver(self,row):
        _,identity,event,receivers=row
        routing=await asyncio.to_thread(self.service.notification,identity)
        # Private notification rendering reads party-visible detail with one verified participant ID.
        requester=await asyncio.to_thread(self.service.discord_player,routing['discord_ids'][0])
        trade=(await asyncio.to_thread(self.service.listing,requester,False,identity))[0]
        statuses={'requested':'收到交換申請','accepted':'對方已接受，碎片已預留','rejected':'交換申請已被拒絕',
                  'cancelled':'交換已取消，預留已釋放','completed':'雙方確認完成，碎片已扣除'}
        label=statuses.get(event,'其中一方已確認完成，等待另一方確認')
        safe=lambda value:discord.utils.escape_mentions(discord.utils.escape_markdown(value))
        lines=[f'**{label}**',f'{safe(trade["requester_name"])}（{safe(trade["requester_account_name"])}） ↔ {safe(trade["recipient_name"])}（{safe(trade["recipient_account_name"])}）']
        for item in trade['items']:lines.append(f'{"發起方提供" if item["direction"]=="give" else "對方提供"}：{safe(item["name"])} × {item["quantity"]}')
        marker=f'通知編號 {row[0]}';lines.extend([f'目前狀態：{routing["status"]}',current_website_origin()+'/trades',marker])
        # User-supplied names are plain text; no unsolicited @everyone or role mentions.
        text='\n'.join(lines)[:1600]+'\n'+current_website_origin()+'/trades\n'+marker
        view=discord.ui.View(timeout=None)
        if event=='requested' and routing['status']=='pending':
            view.add_item(TradeDecision(identity,'accept'));view.add_item(TradeDecision(identity,'reject'))
        mode=os.getenv('DISCORD_TRADE_MODE','')
        targets=[]
        recipient_ids=[uid for player,uid in zip(routing['player_ids'],routing['discord_ids']) if player in receivers]
        if not recipient_ids:raise DrawError('No valid notification recipient.')
        if mode=='private_thread':
            parent=await self.bot.fetch_channel(int(os.environ['DISCORD_TRADE_CHANNEL_ID']))
            if not isinstance(parent,discord.TextChannel):raise DrawError('Trade channel must be a guild text channel.')
            for uid in recipient_ids:
                thread=None;thread_id=routing['threads'].get(uid)
                if thread_id:
                    thread=await self.bot.fetch_channel(int(thread_id))
                    if not isinstance(thread,discord.Thread) or thread.type!=discord.ChannelType.private_thread or thread.parent_id!=parent.id:
                        raise DrawError('Private trade thread is invalid.')
                    if thread.archived:await thread.edit(archived=False)
                if thread is None:
                    thread=await parent.create_thread(name='交換通知-'+identity,type=discord.ChannelType.private_thread,invitable=False,auto_archive_duration=1440)
                    with PostgresStore().connection() as c:c.execute('''UPDATE onmyoji_shards.trades SET notification_threads=jsonb_set(notification_threads,ARRAY[%s]::text[],to_jsonb(%s::text)) WHERE id=%s''',(uid,str(thread.id),identity))
                await thread.add_user(discord.Object(id=int(uid)));targets.append(thread)
        elif mode=='dm':
            for uid in recipient_ids:
                user=await self.bot.fetch_user(int(uid));targets.append(await user.create_dm())
        else:raise DrawError('Choose DISCORD_TRADE_MODE before enabling notifications.')
        for target in targets:
            # Handles a successful send followed by a lost DB acknowledgement in most retries.
            duplicate=False
            async for message in target.history(limit=30):
                if message.author.id==self.bot.user.id and marker in message.content:duplicate=True;break
            if not duplicate:await target.send(text,view=view,allowed_mentions=discord.AllowedMentions.none())

    @tasks.loop(seconds=5)
    async def worker(self):
        if os.getenv('DISCORD_TRADE_MODE') not in ('private_thread','dm'):return
        row=None;token=None
        try:
            row,token=await asyncio.to_thread(self.claim)
            if row:
                try:await asyncio.wait_for(self.deliver(row),timeout=120)
                except Exception as error:await asyncio.to_thread(self.acknowledge,row,token,type(error).__name__)
                else:await asyncio.to_thread(self.acknowledge,row,token)
        except Exception:
            # Lease expiration permits retry after outages; do not leak DB or Discord request payloads.
            pass

    @worker.before_loop
    async def before_worker(self):await self.bot.wait_until_ready()

    @app_commands.command(name='fragments',description='按 Rarity 與式神名字搜尋誰有可交換碎片')
    @app_commands.choices(rarity=[app_commands.Choice(name=r,value=r) for r in ('SSR','SP','UR','COLLAB')])
    @app_commands.checks.cooldown(1,5,key=lambda i:i.user.id)
    async def fragments(self,interaction:discord.Interaction,rarity:app_commands.Choice[str],name:str):
        await interaction.response.defer(ephemeral=True,thinking=True)
        try:
            records=await asyncio.to_thread(PostgresCatalog().list)
            query=recognition_name(name)
            matches=[r for r in records if r['rarity']==rarity.value and any(query==recognition_name(v) for v in [r['name'],r.get('name_simplified'),*r['aliases']] if v)]
            if len(matches)!=1:
                suggestions=[r['name'] for r in records if r['rarity']==rarity.value and any(query in recognition_name(v) for v in [r['name'],r.get('name_simplified')] if v)]
                await interaction.followup.send('請選擇完整式神名字。候選：'+('、'.join(suggestions[:15]) or '沒有符合的式神'),ephemeral=True);return
            rows=await asyncio.to_thread(FragmentManagement().search,shikigami_id=matches[0]['id'],target='offers')
            lines=[f'**{matches[0]["name"]} · {rarity.value}**（不包含已預留數量）']
            lines += [f'{r["player_name"]} · {r["nickname"]} · {r["server_name"]}：{r["quantity"]}' for r in rows[:20]]
            if not rows:lines.append('目前沒有人可提供。')
            if len(rows)>20:lines.append('更多結果請到網站搜索。')
            lines.append(current_website_origin()+'/search-fragments?shikigami_id='+matches[0]['id'])
            await interaction.followup.send('\n'.join(lines)[:1900],ephemeral=True,allowed_mentions=discord.AllowedMentions.none())
        except DrawError as error:await interaction.followup.send(str(error),ephemeral=True)
        except Exception:await interaction.followup.send('暫時無法搜尋，請稍後重試。',ephemeral=True)

    @fragments.autocomplete('name')
    async def names(self,interaction,current):
        try:
            rarity=interaction.namespace.rarity;query=recognition_name(current)
            records=await asyncio.to_thread(PostgresCatalog().list)
            return [app_commands.Choice(name=r['name'],value=r['name']) for r in records if r['rarity']==rarity and any(query in recognition_name(v) for v in [r['name'],r.get('name_simplified')] if v)][:25]
        except Exception:return []

    @fragments.error
    async def search_error(self,interaction,error):
        text='請稍等幾秒再搜尋。'
        if interaction.response.is_done():await interaction.followup.send(text,ephemeral=True)
        else:await interaction.response.send_message(text,ephemeral=True)


async def setup(bot):
    bot.add_dynamic_items(TradeDecision)
    await bot.add_cog(TradeNotifications(bot))
