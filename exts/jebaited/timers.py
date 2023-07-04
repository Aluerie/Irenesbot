from __future__ import annotations

from typing import TYPE_CHECKING

from discord.ext import commands

from ._base import JebaitedCog

if TYPE_CHECKING:
    from utils import AluBot, AluContext


class Timers(JebaitedCog):
    async def cog_load(self) -> None:
        pass

    async def cog_unload(self) -> None:
        pass

    @commands.hybrid_group()
    async def timer(self, ctx: AluContext):
        '''new timer'''
        await ctx.scnf()

    @timer.command()
    async def create(self, ctx: AluContext, category: str, frequency: str, probability: float):
        pass

    @commands.Cog.listener()  # Yep, that's the best name I came up with.
    async def on_timer_timer_complete(self):
        pass


async def setup(bot: AluBot):
    await bot.add_cog(Timers(bot))
