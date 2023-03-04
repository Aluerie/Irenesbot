from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List

import asyncpg
from discord.ext import commands, tasks
from pyot.core.exceptions import NotFound, ServerError
from pyot.utils.lol import champion

from utils.lol.const import SOLO_RANKED_5v5_QUEUE_ENUM, platform_to_region

from ._models import LiveMatch

# need to import the last because in import above we activate 'lol' model
from pyot.models import lol  # isort: skip

if TYPE_CHECKING:
    from utils.bot import AluBot

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


class LoLNotifs(commands.Cog):
    def __init__(self, bot: AluBot):
        self.bot: AluBot = bot
        self.live_matches: List[LiveMatch] = []
        self.all_live_match_ids: List[int] = []

    async def cog_load(self) -> None:
        await self.bot.ini_twitch()
        self.lolfeed_notifs.add_exception_type(asyncpg.InternalServerError)
        self.lolfeed_notifs.start()

    def cog_unload(self) -> None:
        self.lolfeed_notifs.stop()  # .cancel()

    async def fill_live_matches(self):
        self.live_matches, self.all_live_match_ids = [], []

        query = 'SELECT DISTINCT(unnest(lolfeed_champ_ids)) FROM guilds'
        fav_champ_ids = [r for r, in await self.bot.pool.fetch(query)]  # row.unnest

        live_fav_player_ids = await self.bot.twitch.get_live_lol_player_ids(pool=self.bot.pool)

        query = f""" SELECT a.id, account, platform, display_name, player_id, twitch_id, last_edited
                    FROM lol_accounts a
                    JOIN lol_players p
                    ON a.player_id = p.id
                    WHERE player_id=ANY($1)
                """
        for r in await self.bot.pool.fetch(query, live_fav_player_ids):
            try:
                live_game = await lol.spectator.CurrentGame(summoner_id=r.id, platform=r.platform).get()
            except NotFound:
                log.debug(f'Player {r.display_name} is not in the game on acc {r.account}')
                continue
            except ServerError:
                log.debug(f'ServerError `lolfeed.py`: {r.account} {r.platform} {r.display_name}')
                continue
                # e = Embed(colour=Clr.error)
                # e.description = f'ServerError `lolfeed.py`: {row.name} {row.platform} {row.accname}'
                # await self.bot.get_channel(Cid.spam_me).send(embed=e)  # content=umntn(Uid.alu)

            if not hasattr(live_game, 'queue_id') or live_game.queue_id != SOLO_RANKED_5v5_QUEUE_ENUM:
                continue
            self.all_live_match_ids.append(live_game.id)
            p = next((x for x in live_game.participants if x.summoner_id == r.id), None)
            if p and p.champion_id in fav_champ_ids and r.last_edited != live_game.id:
                query = """ SELECT lolfeed_ch_id 
                            FROM guilds
                            WHERE $1=ANY(lolfeed_champ_ids) 
                                AND $2=ANY(lolfeed_stream_ids)
                                AND NOT lolfeed_ch_id=ANY(
                                    SELECT channel_id
                                    FROM lol_messages
                                    WHERE match_id=$3
                                )     
                        """
                channel_ids = [i for i, in await self.bot.pool.fetch(query, p.champion_id, r.player_id, live_game.id)]
                if channel_ids:
                    log.debug(f'LF | {r.display_name} - {await champion.key_by_id(p.champion_id)}')
                    self.live_matches.append(
                        LiveMatch(
                            match_id=live_game.id,
                            platform=p.platform,  # type: ignore
                            account_name=p.summoner_name,
                            start_time=round(live_game.start_time_millis / 1000),
                            champ_id=p.champion_id,
                            all_champ_ids=[player.champion_id for player in live_game.participants],
                            twitch_id=r.twitch_id,
                            spells=p.spells,
                            runes=p.runes,
                            channel_ids=channel_ids,
                            account_id=p.summoner_id,
                        )
                    )

    async def send_notifications(self, match: LiveMatch):
        log.debug("LF | Sending LoLFeed notification")
        for ch_id in match.channel_ids:
            if (ch := self.bot.get_channel(ch_id)) is None:
                log.debug("LF | The channel is None")
                continue

            em, img_file = await match.notif_embed_and_file(self.bot)
            log.debug('LF | Successfully made embed+file')
            em.title = f"{ch.guild.owner.name}'s fav champ + player spotted"
            msg = await ch.send(embed=em, file=img_file)

            query = """ INSERT INTO lol_matches (id, region, platform)
                        VALUES ($1, $2, $3)
                        ON CONFLICT DO NOTHING 
                    """
            await self.bot.pool.execute(query, match.match_id, platform_to_region(match.platform), match.platform)
            query = """ INSERT INTO lol_messages
                        (message_id, channel_id, match_id, champ_id) 
                        VALUES ($1, $2, $3, $4)
                    """
            await self.bot.pool.execute(query, msg.id, ch.id, match.match_id, match.champ_id)
            query = 'UPDATE lol_accounts SET last_edited=$1 WHERE id=$2'
            await self.bot.pool.execute(query, match.match_id, match.account_id)

    async def declare_matches_finished(self):
        query = """ UPDATE lol_matches 
                    SET is_finished=TRUE
                    WHERE NOT id=ANY($1)
                    AND lol_matches.is_finished IS DISTINCT FROM TRUE
                """
        await self.bot.pool.execute(query, self.all_live_match_ids)

    @tasks.loop(seconds=59)
    async def lolfeed_notifs(self):
        log.debug(f'LF | --- Task is starting now ---')
        await self.fill_live_matches()
        for match in self.live_matches:
            await self.send_notifications(match)
        await self.declare_matches_finished()
        log.debug(f'LF | --- Task is finished ---')

    @lolfeed_notifs.before_loop
    async def before(self):
        await self.bot.wait_until_ready()

    @lolfeed_notifs.error
    async def lolfeed_notifs_error(self, error):
        await self.bot.send_traceback(error, where='LoLFeed Notifs')
        # self.lolfeed.restart()


async def setup(bot):
    await bot.add_cog(LoLNotifs(bot))