from __future__ import annotations

from typing import TYPE_CHECKING

import orjson
from pulsefire.clients import CDragonClient, MerakiCDNClient, RiotAPIClient
from pulsefire.middlewares import http_error_middleware, json_response_middleware, rate_limiter_middleware
from pulsefire.ratelimiters import RiotAPIRateLimiter

import config

from .storage import ItemIcons, RuneIcons, SummonerSpellIcons

if TYPE_CHECKING:
    from bot import AluBot


class LeagueClient(RiotAPIClient):
    def __init__(self, bot: AluBot) -> None:
        super().__init__(
            default_headers={"X-Riot-Token": config.RIOT_API_KEY},
            default_queries={},
            middlewares=[
                json_response_middleware(orjson.loads),
                http_error_middleware(),
                rate_limiter_middleware(RiotAPIRateLimiter()),
            ],
        )
        self.cdragon = CDragonClient(
            default_params={"patch": "latest", "locale": "default"},
            middlewares=[
                json_response_middleware(orjson.loads),
                http_error_middleware(),
            ],
        )
        self.meraki = MerakiCDNClient(
            middlewares=[
                json_response_middleware(orjson.loads),
                http_error_middleware(),
            ],
        )
        self.champions = ""
        self.item_icons = ItemIcons(bot)
        self.rune_icons = RuneIcons(bot)
        self.summoner_spell_icons = SummonerSpellIcons(bot)

    async def start(self) -> None:
        """Start all sub-clients and sub-storages needed for my League Client."""
        # clients
        await self.__aenter__()
        await self.cdragon.__aenter__()
        await self.meraki.__aenter__()

        # caches
        self.item_icons.start()
        self.rune_icons.start()
        self.summoner_spell_icons.start()

    async def close(self) -> None:
        # clients
        await self.__aexit__()
        await self.cdragon.__aexit__()
        await self.meraki.__aexit__()

        # caches
        self.item_icons.close()
        self.rune_icons.close()
        self.summoner_spell_icons.close()