from __future__ import annotations

import asyncio
import datetime
import logging
import time
from typing import TYPE_CHECKING, TypedDict

import aiohttp
import discord
from discord.ext import commands

from utils import aluloop, const

from .._base import BaseNotifications
from ._models import (
    DotaFPCMatchToEditWithOpenDota,
    DotaFPCMatchToEditWithStratz,
    DotaFPCMatchToSend,
    MatchToEditNotCounted,
)

if TYPE_CHECKING:
    # from steam.ext.dota2 import LiveMatch # VALVE_SWITCH
    from utils.dota import LiveMatch

    from bot import AluBot
    from utils import AluContext

    class AnalyzeGetPlayerIDsQueryRow(TypedDict):
        twitch_live_only: bool
        player_ids: list[int]

    class FindMatchesToEditQueryRow(TypedDict):
        match_id: int
        friend_id: int
        hero_id: int
        channel_message_tuples: list[tuple[int, int]]

    class AnalyzeTopSourceResponsePlayerQueryRow(TypedDict):
        player_id: int
        display_name: str
        twitch_id: int

    class MatchToEditSubDict(TypedDict):
        hero_id: int
        loop_count: int
        edited_with_opendota: bool
        edited_with_stratz: bool
        channel_message_tuples: list[tuple[int, int]]

    type MatchToEdit = dict[tuple[int, int], MatchToEditSubDict]

    from utils.dota import schemas


send_log = logging.getLogger("send_dota_fpc")
send_log.setLevel(logging.INFO)

edit_log = logging.getLogger("edit_dota_fpc")
edit_log.setLevel(logging.DEBUG)


class DotaFPCNotifications(BaseNotifications):
    def __init__(self, bot: AluBot, *args, **kwargs):
        super().__init__(bot, prefix="dota", *args, **kwargs)
        # Send Matches related attrs
        self.live_match_ids: list[int] = []
        self.death_counter: int = 0

        # Edit Matches related attrs
        self.allow_editing_matches: bool = True
        self.matches_to_edit: MatchToEdit = {}

    async def cog_load(self) -> None:
        # maybe asyncpg.PostgresConnectionError too
        # self.task_to_send_dota_fpc_messages.add_exception_type(asyncpg.InternalServerError)
        self.task_to_send_notifications.clear_exception_types()
        self.task_to_send_notifications.start()

        self.task_to_edit_messages.clear_exception_types()

        self.daily_ratelimit_report.start()
        return await super().cog_load()

    async def cog_unload(self) -> None:
        self.task_to_send_notifications.cancel()
        self.task_to_edit_messages.cancel()
        self.daily_ratelimit_report.stop()
        return await super().cog_unload()

    async def convert_player_id_to_friend_id(self, player_ids: list[int]) -> list[int]:
        query = "SELECT friend_id FROM dota_accounts WHERE player_id=ANY($1)"
        return [f for f, in await self.bot.pool.fetch(query, player_ids)]

    async def analyze_top_source_response(self, live_matches: list[LiveMatch]):
        query = "SELECT DISTINCT character_id FROM dota_favourite_characters"
        favourite_hero_ids: list[int] = [r for r, in await self.bot.pool.fetch(query)]

        query = """
            SELECT twitch_live_only, ARRAY_AGG(player_id) player_ids
            FROM dota_favourite_players p
            JOIN dota_settings s ON s.guild_id = p.guild_id
            WHERE s.enabled = TRUE
            GROUP by twitch_live_only
        """
        player_id_rows: list[AnalyzeGetPlayerIDsQueryRow] = await self.bot.pool.fetch(query)

        friend_id_cache: dict[bool, list[int]] = {True: [], False: []}
        for row in player_id_rows:
            if row["twitch_live_only"]:
                # need to check what streamers are live
                twitch_live_player_ids = await self.get_twitch_live_player_ids(
                    const.Twitch.DOTA_GAME_CATEGORY_ID, row["player_ids"]
                )
                friend_id_cache[True] = await self.convert_player_id_to_friend_id(twitch_live_player_ids)
            else:
                friend_id_cache[False] = await self.convert_player_id_to_friend_id(row["player_ids"])

        for match in live_matches:
            for twitch_live_only, friend_ids in friend_id_cache.items():
                our_players = [p for p in match.players if p.id in friend_ids and p.hero.id in favourite_hero_ids]
                for player in our_players:
                    account_id = player.id
                    hero_id = player.hero.id

                    query = """
                        SELECT player_id, display_name, twitch_id 
                        FROM dota_players 
                        WHERE player_id=(SELECT player_id FROM dota_accounts WHERE friend_id=$1)
                    """
                    user: AnalyzeTopSourceResponsePlayerQueryRow = await self.bot.pool.fetchrow(query, account_id)
                    query = """
                        SELECT s.channel_id, s.spoil
                        FROM dota_favourite_characters c
                        JOIN dota_favourite_players p on c.guild_id = p.guild_id
                        JOIN dota_settings s on s.guild_id = c.guild_id
                        WHERE character_id=$1 
                            AND p.player_id=$2
                            AND NOT s.channel_id = ANY(
                                SELECT channel_id 
                                FROM dota_messages 
                                WHERE match_id = $3 AND friend_id=$4
                            )
                            AND s.twitch_live_only = $5
                            AND s.enabled = TRUE;
                    """

                    channel_spoil_tuples: list[tuple[int, bool]] = [
                        (channel_id, spoil)
                        for channel_id, spoil in await self.bot.pool.fetch(
                            query,
                            hero_id,
                            user["player_id"],
                            match.id,
                            account_id,
                            twitch_live_only,
                        )
                    ]

                    if channel_spoil_tuples:
                        hero_name = await self.bot.dota_cache.hero.name_by_id(hero_id)
                        send_log.debug("%s - %s", user["display_name"], hero_name)
                        match_to_send = DotaFPCMatchToSend(
                            self.bot,
                            match_id=match.id,
                            friend_id=account_id,
                            start_time=match.start_time,
                            player_name=user["display_name"],
                            twitch_id=user["twitch_id"],
                            hero_id=hero_id,
                            hero_ids=[hero.id for hero in match.heroes],
                            server_steam_id=match.server_steam_id,
                            hero_name=hero_name,
                        )
                        # SENDING
                        start_time = time.perf_counter()
                        await self.send_match(match_to_send, channel_spoil_tuples)
                        send_log.debug("Sending took %.5f secs", time.perf_counter() - start_time)

    @aluloop(seconds=59)
    async def task_to_send_notifications(self):
        send_log.debug(f"--- Task to send Dota2 FPC Notifications is starting now ---")

        # REQUESTING
        start_time = time.perf_counter()
        try:
            live_matches = await self.bot.dota.top_live_matches()
        except asyncio.TimeoutError:
            self.death_counter += 1
            await self.hideout.spam.send(f"Dota 2 Game Coordinator is dying: count {self.death_counter}")
            # nothing to "mark_matches_to_edit" so let's return
            return
        else:
            self.death_counter = 0

        top_source_end_time = time.perf_counter() - start_time
        send_log.debug("Requesting took %.5f secs with %s results", top_source_end_time, len(live_matches))

        # ANALYZING
        start_time = time.perf_counter()
        await self.analyze_top_source_response(live_matches)
        send_log.debug("Analyzing took %.5f secs", time.perf_counter() - start_time)

        # another mini-death condition
        if len(live_matches) < 100:
            # this means it returned 90, 80, ..., or even 0 matches. But it did respond.
            # still can ruin further logic
            await self.hideout.spam.send(f"Dota 2 Game Coordinator only fetched {len(live_matches)} matches")
            return

        # START EDITING TASK IF NEEDED
        if self.allow_editing_matches:
            self.live_match_ids = [match.id for match in live_matches]
            if self.task_to_edit_messages.is_running():
                # no need to check - wait till it's done.
                return
            else:
                # if we are here - it means self.matches_to_edit is empty
                start_time = time.perf_counter()
                query = "SELECT match_id FROM dota_messages WHERE NOT match_id=ANY($1)"
                match_ids_to_mark = [match_id for match_id, in await self.bot.pool.fetch(query, self.live_match_ids)]

                if match_ids_to_mark:
                    # we have messages to mark to edit
                    self.task_to_edit_messages.start()
                    send_log.debug(
                        "Marking took %.5f secs - %s matches to edit",
                        time.perf_counter() - start_time,
                        len(match_ids_to_mark),
                    )
        send_log.debug(f"--- Task is finished ---")

    # POST MATCH EDITS
    async def edit_with_opendota(
        self, match_id: int, friend_id: int, hero_id: int, channel_message_tuples: list[tuple[int, int]]
    ) -> bool:
        try:
            opendota_match = await self.bot.opendota_client.get_match(match_id=match_id)
        except aiohttp.ClientResponseError as exc:
            edit_log.debug("OpenDota API Response Not OK with status %s", exc.status)
            return False

        if "radiant_win" not in opendota_match:
            # Somebody abandoned before the first blood or so -> game didn't count
            # thus "radiant_win" key is not present
            edit_log.debug("Opendota: match %s did not count. Deleting the match.", match_id)
            not_counted_match_to_edit = MatchToEditNotCounted(self.bot)
            await self.edit_match(not_counted_match_to_edit, channel_message_tuples, pop=True)
            await self.cleanup_match_to_edit(match_id, friend_id)
            return True

        for player in opendota_match["players"]:
            if player["hero_id"] == hero_id:
                opendota_player = player
                break
        else:
            raise RuntimeError(f"Somehow the player {friend_id} is not in the match {match_id}")

        match_to_edit_with_opendota = DotaFPCMatchToEditWithOpenDota(self.bot, player=opendota_player)
        await self.edit_match(match_to_edit_with_opendota, channel_message_tuples)
        return True

    async def edit_with_stratz(
        self, match_id: int, friend_id: int, channel_message_tuples: list[tuple[int, int]]
    ) -> bool:
        try:
            stratz_data = await self.bot.stratz_client.get_fpc_match_to_edit(match_id=match_id, friend_id=friend_id)
        except aiohttp.ClientResponseError as exc:
            edit_log.debug("Stratz API Response Not OK with status %s", exc.status)
            return False

        if stratz_data["data"]["match"] is None:
            # if somebody abandons in draft but we managed to send the game out
            # then parser will fail and declare None
            edit_log.debug("Stratz: match %s did not count. Deleting the match.", match_id)
            return True

        # we are ready to send the notification
        fpc_match_to_edit = DotaFPCMatchToEditWithStratz(self.bot, data=stratz_data)
        await self.edit_match(fpc_match_to_edit, channel_message_tuples, pop=True)
        return True

    async def cleanup_match_to_edit(self, match_id: int, friend_id: int):
        """Remove match from `self.matches_to_edit` and database."""
        self.matches_to_edit.pop((match_id, friend_id))
        query = "DELETE FROM dota_messages WHERE match_id=$1 AND friend_id=$2"
        await self.bot.pool.execute(query, match_id, friend_id)

    async def mark_matches_to_edit(self):
        query = """
            SELECT match_id, friend_id, hero_id, ARRAY_AGG ((channel_id, message_id)) channel_message_tuples
            FROM dota_messages
            WHERE NOT match_id=ANY($1)
            GROUP BY match_id, friend_id, hero_id
        """
        current_match_to_edit_ids = [key[0] for key in self.matches_to_edit]

        finished_match_rows: list[FindMatchesToEditQueryRow] = await self.bot.pool.fetch(
            query, current_match_to_edit_ids + self.live_match_ids
        )

        for match_row in finished_match_rows:
            self.matches_to_edit[(match_row["match_id"], match_row["friend_id"])] = {
                "hero_id": match_row["hero_id"],
                "channel_message_tuples": match_row["channel_message_tuples"],
                "loop_count": 0,
                "edited_with_opendota": False,
                "edited_with_stratz": False,
            }

    @aluloop(minutes=5)
    async def task_to_edit_messages(self):
        """Task responsible for editing Dota FPC Messages with PostMatch Result data

        The data is featured from Opendota/Stratz.
        """

        edit_log.debug("*** Starting Task to Edit Dota FPC Messages ***")

        # MARKING GAMES
        await self.mark_matches_to_edit()

        for tuple_uuid in list(self.matches_to_edit):
            match_id, friend_id = tuple_uuid

            self.matches_to_edit[tuple_uuid]["loop_count"] += 1
            match_to_edit = self.matches_to_edit[tuple_uuid]
            edit_log.debug("Editing match %s friend %s loop %s", match_id, friend_id, match_to_edit["loop_count"])

            if match_to_edit["loop_count"] == 1:
                # skip the first iteration so OpenDota can catch-up on the data in next 5 minutes.
                # usually it's obviously behind Game Coordinator so first loop always fails anyway
                continue
            elif match_to_edit["loop_count"] > 15:
                # we had enough of fails with this match, let's move on.
                await self.cleanup_match_to_edit(match_id, friend_id)
                await self.hideout.spam.send(f"Failed to edit the match {match_id} with Opendota or Stratz.")
            else:
                # let's try editing
                # OPENDOTA
                if not match_to_edit["edited_with_opendota"]:
                    match_to_edit["edited_with_opendota"] = await self.edit_with_opendota(
                        match_id, friend_id, match_to_edit["hero_id"], match_to_edit["channel_message_tuples"]
                    )
                    edit_log.debug("Edited with OpenDota: %s", match_to_edit["edited_with_opendota"])
                # STRATZ
                elif not match_to_edit["edited_with_stratz"]:
                    match_to_edit["edited_with_stratz"] = await self.edit_with_stratz(
                        match_id, friend_id, match_to_edit["channel_message_tuples"]
                    )
                    edit_log.debug("Edited with Stratz: %s", match_to_edit["edited_with_stratz"])

                if match_to_edit["edited_with_stratz"] and match_to_edit["edited_with_opendota"]:
                    await self.cleanup_match_to_edit(match_id, friend_id)
                    edit_log.info("Success: after %s loops we edited the message", match_to_edit["loop_count"])

        edit_log.debug("*** Finished Task to Edit Dota FPC Messages ***")

    @task_to_edit_messages.after_loop
    async def stop_editing_task(self):
        if not self.matches_to_edit:
            # nothing more to analyze
            self.task_to_edit_messages.cancel()

        if self.task_to_edit_messages.failed():
            # in case of Exception let's disallow the task at all
            self.allow_editing_matches = False

    # STRATZ RATE LIMITS

    def get_ratelimit_embed(self) -> discord.Embed:
        return (
            discord.Embed(colour=discord.Colour.blue(), title="Daily Remaining RateLimits")
            .add_field(
                name="Stratz",
                value=self.bot.stratz_client.rate_limiter.rate_limits_string,
            )
            .add_field(
                name="OpenDota",
                value=self.bot.opendota_client.rate_limiter.rate_limits_string,
            )
        )

    @commands.command(hidden=True)
    async def ratelimits(self, ctx: AluContext):
        """Send OpenDota/Stratz rate limit numbers"""
        await ctx.reply(embed=self.get_ratelimit_embed())

    @aluloop(time=datetime.time(hour=23, minute=55, tzinfo=datetime.timezone.utc))
    async def daily_ratelimit_report(self):
        """Send information about Stratz daily limit to spam logs.

        Stratz has daily ratelimit of 10000 requests and it's kinda scary one, if parsing requests fail a lot.
        This is why we also send @mention if ratelimit is critically low.
        """
        content = ""
        for ratio in [
            self.bot.stratz_client.rate_limiter.rate_limits_ratio,
            self.bot.opendota_client.rate_limiter.rate_limits_ratio,
        ]:
            if ratio < 0.1:
                content = f"<@{self.bot.owner_id}>"

        await self.hideout.daily_report.send(content=content, embed=self.get_ratelimit_embed())


async def setup(bot):
    await bot.add_cog(DotaFPCNotifications(bot))