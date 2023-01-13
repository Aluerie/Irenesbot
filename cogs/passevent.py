from __future__ import annotations
from typing import TYPE_CHECKING

import datetime

import discord
from discord.ext import commands, tasks

from .utils.var import Uid

if TYPE_CHECKING:
    from .utils.bot import AluBot

start_errors = 948936198733328425
game_feed = 966316773869772860


class PassEvent(commands.Cog):
    def __init__(self, bot: AluBot):
        self.bot: AluBot = bot
        self.lastupdated = datetime.datetime.now(datetime.timezone.utc)
        self.crashed: bool = True

    async def cog_load(self) -> None:
        self.botcheck.start()

    async def cog_unload(self) -> None:
        self.botcheck.cancel()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.channel.id == game_feed:
            self.lastupdated = datetime.datetime.now(datetime.timezone.utc)
            self.crashed = False
        if message.channel.id == start_errors:
            self.crashed = True

    @tasks.loop(hours=2)
    async def botcheck(self):
        if self.crashed:
            return
        if datetime.datetime.now(datetime.timezone.utc) - self.lastupdated > datetime.timedelta(minutes=40):
            await self.bot.get_channel(start_errors).send(
                content=f'<@{Uid.alu}> I think the bot crashed but did not even send the message'
            )

    @botcheck.before_loop
    async def before(self):
        await self.bot.wait_until_ready()


async def setup(bot: AluBot):
    await bot.add_cog(PassEvent(bot))
