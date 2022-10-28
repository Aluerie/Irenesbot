from __future__ import annotations

from typing import TYPE_CHECKING

from discord import Embed
from discord.ext import commands

if TYPE_CHECKING:
    from .utils.bot import AluBot, Context


class BetaTest(commands.Cog):
    def __init__(self, bot):
        self.bot: AluBot = bot

    def cog_unload(self):
        return

    @commands.hybrid_command()
    async def allu(self, ctx: Context):
        em = Embed(
            description=f'[Replay](https://dota2://matchid=668282480)'
        )
        await ctx.reply(embed=em)


async def setup(bot):
    if bot.yen:
        await bot.add_cog(BetaTest(bot))
