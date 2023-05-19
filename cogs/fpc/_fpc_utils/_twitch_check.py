from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from discord.ext import commands, tasks

if TYPE_CHECKING:
    from utils import AluBot


class TwitchAccountCheckBase(commands.Cog):
    def __init__(self, bot: AluBot, table_name: str, day: int):
        self.bot: AluBot = bot
        self.table_name: str = table_name
        self.day: int = day
        # self.__cog_name__ = f'TwitchAccCheckCog for {table_name}'
        self.check_acc_renames.start()

    @tasks.loop(time=datetime.time(hour=12, minute=11, tzinfo=datetime.timezone.utc))
    async def check_acc_renames(self):
        if datetime.datetime.now(datetime.timezone.utc).day != self.day:
            return

        query = f'SELECT id, twitch_id, display_name FROM {self.table_name} WHERE twitch_id IS NOT NULL'
        rows = await self.bot.pool.fetch(query)

        for row in rows:
            display_name = await self.bot.twitch.name_by_twitch_id(row.twitch_id)
            if display_name != row.display_name:
                query = f'UPDATE {self.table_name} SET display_name=$1, name_lower=$2 WHERE id=$3'
                await self.bot.pool.execute(query, display_name, display_name.lower(), row.id)

    @check_acc_renames.before_loop
    async def before(self):
        await self.bot.wait_until_ready()