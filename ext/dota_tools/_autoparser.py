from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import vdf
from steam.core.msg import MsgProto
from steam.enums import emsg

from ext.fpc_notifications.dota._opendota import OpendotaRequestMatch
from utils import AluCog, aluloop

if TYPE_CHECKING:
    from bot import AluBot

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


class OpenDotaAutoParser(AluCog):
    """Requesting OpenDota parse automatically after match ends.

    Yes, a bit dirty and dishonourable since they provide it as a paid feature while I hack it in.
    """

    def __init__(self, bot: AluBot, *args, **kwargs) -> None:
        super().__init__(bot, *args, **kwargs)
        self.active_matches: list[int] = []
        self.lobby_ids: set[int] = set()

        self.matches_to_parse: list[int] = []
        self.opendota_req_cache: dict[int, OpendotaRequestMatch] = {}

        self.steam_ids: list[int]

    async def cog_load(self) -> None:
        await self.bot.initialize_dota()

        @self.bot.dota.on("top_source_tv_games")  # type: ignore
        def autoparse_response(result) -> None:
            if result.specific_games:
                # remember the quirk that
                # result.specific_games = my friends games
                # not result.specific_games = top100 mmr games
                m_ids = [m.match_id for m in result.game_list]
                self.matches_to_parse = list(dict.fromkeys([m_id for m_id in self.active_matches if m_id not in m_ids]))
                self.active_matches += list(dict.fromkeys([m_id for m_id in m_ids if m_id not in self.active_matches]))
                log.debug(f"to parse {self.matches_to_parse} active {self.active_matches}")
                self.bot.dota.emit("autoparse_top_games_response")

        query = "SELECT steam_id FROM autoparse"
        self.steam_ids = [r for (r,) in await self.bot.pool.fetch(query)]

        self.autoparse_task.start()

    async def cog_unload(self) -> None:
        self.autoparse_task.cancel()

    async def get_active_matches(self) -> None:
        self.lobby_ids = set()

        proto_msg = MsgProto(emsg.EMsg.ClientRichPresenceRequest)
        proto_msg.header.routing_appid = 570  # type: ignore

        proto_msg.body.steamid_request.extend(self.steam_ids)  # type: ignore
        resp = self.bot.steam.send_message_and_wait(proto_msg, emsg.EMsg.ClientRichPresenceInfo, timeout=8)
        if resp is None:
            print("resp is None, hopefully everything else will be fine tho;")
            return
        for item in resp.rich_presence:
            if rp_bytes := item.rich_presence_kv:
                rp = vdf.binary_loads(rp_bytes)["RP"]
                if lobby_id := int(rp.get("WatchableGameID", 0)):
                    self.lobby_ids.add(lobby_id)

        # print(self.lobby_ids)
        # dota.on('ready', ready_function)
        if self.lobby_ids:
            self.bot.dota.request_top_source_tv_games(lobby_ids=list(self.lobby_ids))
            self.bot.dota.wait_event("autoparse_top_games_response", timeout=8)
        else:
            self.matches_to_parse = self.active_matches

    @aluloop(seconds=59)
    async def autoparse_task(self) -> None:
        await self.get_active_matches()
        for match_id in self.matches_to_parse:
            if match_id not in self.opendota_req_cache:
                self.opendota_req_cache[match_id] = OpendotaRequestMatch(match_id)

            cache_item: OpendotaRequestMatch = self.opendota_req_cache[match_id]

            await cache_item.workflow(self.bot)
            # print(cache_item)
            if cache_item.dict_ready:
                self.opendota_req_cache.pop(match_id)
                self.active_matches.remove(match_id)


async def setup(bot: AluBot) -> None:
    await bot.add_cog(OpenDotaAutoParser(bot))