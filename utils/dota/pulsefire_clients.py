from __future__ import annotations

import collections
import random
import time
from typing import TYPE_CHECKING

import orjson
from pulsefire.clients import BaseClient
from pulsefire.middlewares import http_error_middleware, json_response_middleware, rate_limiter_middleware
from pulsefire.ratelimiters import BaseRateLimiter

try:
    import config
except ImportError:
    import sys

    sys.path.append("D:/LAPTOP/AluBot")
    import config

if TYPE_CHECKING:
    from pulsefire.invocation import Invocation

    from . import schemas

__all__ = ("OpenDotaClient", "StratzClient")


class DotaAPIsRateLimiter(BaseRateLimiter):
    """Dota 2 APIs rate limiter.

    This rate limiter can be served stand-alone for centralized rate limiting.
    """

    _index: dict[tuple[str, int, *tuple[str]], tuple[int, int, float, float, float]] = collections.defaultdict(
        lambda: (0, 0, 0, 0, 0)
    )

    def __init__(self) -> None:
        self._track_syncs: dict[str, tuple[float, list]] = {}
        self.rate_limits_string: str = "Not Set Yet"
        self.rate_limits_ratio: float = 1.0

    async def acquire(self, invocation: Invocation) -> float:
        wait_for = 0
        pinging_targets = []
        requesting_targets = []
        request_time = time.time()
        for target in [
            ("app", 0, invocation.params.get("region", ""), invocation.method, invocation.urlformat),
            ("app", 1, invocation.params.get("region", ""), invocation.method, invocation.urlformat),
        ]:
            count, limit, expire, latency, pinged = self._index[target]
            pinging = pinged and request_time - pinged < 10
            if pinging:
                wait_for = max(wait_for, 0.1)
            elif request_time > expire:
                pinging_targets.append(target)
            elif request_time > expire - latency * 1.1 + 0.01 or count >= limit:
                wait_for = max(wait_for, expire - request_time)
            else:
                requesting_targets.append(target)
        if wait_for <= 0:
            if pinging_targets:
                self._track_syncs[invocation.uid] = (request_time, pinging_targets)
                for pinging_target in pinging_targets:
                    self._index[pinging_target] = (0, 0, 0, 0, time.time())
                wait_for = -1
            for requesting_target in requesting_targets:
                count, *values = self._index[requesting_target]
                self._index[requesting_target] = (count + 1, *values)  # type: ignore

        return wait_for

    async def synchronize(self, invocation: Invocation, headers: dict[str, str]) -> None:
        response_time = time.time()
        request_time, pinging_targets = self._track_syncs.pop(invocation.uid, [None, None])
        if request_time is None:
            return

        if random.random() < 0.1:
            for prev_uid, (prev_request_time, _) in self._track_syncs.items():
                if response_time - prev_request_time > 600:
                    self._track_syncs.pop(prev_uid, None)

        try:
            header_limits, header_counts = self.analyze_headers(headers)
        except KeyError:
            for pinging_target in pinging_targets:  # type: ignore
                self._index[pinging_target] = (0, 0, 0, 0, 0)
            return
        for scope, idx, *subscopes in pinging_targets:  # type: ignore
            if idx >= len(header_limits[scope]):
                self._index[(scope, idx, *subscopes)] = (0, 10**10, response_time + 3600, 0, 0)  # type: ignore
                continue
            self._index[(scope, idx, *subscopes)] = (  # type: ignore
                header_counts[scope][idx][0],
                header_limits[scope][idx][0],
                header_limits[scope][idx][1] + response_time,
                response_time - request_time,
                0,
            )

    def analyze_headers(self, headers):
        raise NotImplementedError


class OpenDotaAPIRateLimiter(DotaAPIsRateLimiter):
    def analyze_headers(self, headers):
        self.rate_limits_string = "\n".join(
            [f"{timeframe}: " f"{headers[f'X-Rate-Limit-Remaining-{timeframe}']}" for timeframe in ("Minute", "Day")]
        )
        self.rate_limits_ratio = int(headers["X-Rate-Limit-Remaining-Day"]) / 2000

        header_limits = {
            "app": [[60, 60], [2000, 60 * 60 * 24]],
        }
        header_counts = {
            "app": [
                [int(headers[f"X-Rate-Limit-Remaining-{name}"]), period]
                for name, period in [("Minute", 60), ("Day", 60 * 60 * 24)]
            ]
        }
        return header_limits, header_counts


class StratzAPIRateLimiter(DotaAPIsRateLimiter):
    def analyze_headers(self, headers):
        self.rate_limits_string = "\n".join(
            [
                f"{timeframe}: "
                f"{headers[f'X-RateLimit-Remaining-{timeframe}']}/{headers[f'X-RateLimit-Limit-{timeframe}']}"
                for timeframe in ("Second", "Minute", "Hour", "Day")
            ]
        )
        self.rate_limits_ratio = int(headers["X-RateLimit-Remaining-Day"]) / int(headers["X-RateLimit-Limit-Day"])

        periods = [
            ("Second", 1),
            ("Minute", 60),
            ("Hour", 60 * 60),
            ("Day", 60 * 60 * 24),
        ]
        header_limits = {"app": [[int(headers[f"X-RateLimit-Limit-{name}"]), period] for name, period in periods]}
        header_counts = {"app": [[int(headers[f"X-RateLimit-Remaining-{name}"]), period] for name, period in periods]}
        return header_limits, header_counts


class OpenDotaClient(BaseClient):
    def __init__(self) -> None:
        self.rate_limiter = OpenDotaAPIRateLimiter()
        super().__init__(
            base_url="https://api.opendota.com/api",
            default_params={},
            default_headers={},
            default_queries={},
            middlewares=[
                json_response_middleware(orjson.loads),
                http_error_middleware(),
                rate_limiter_middleware(self.rate_limiter),
            ],
        )

    async def get_match(self, *, match_id: int) -> schemas.OpenDotaAPISchema.Match:
        return await self.invoke("GET", f"/matches/{match_id}")  # type: ignore

    async def request_parse(self, *, match_id: int) -> schemas.OpenDotaAPISchema.ParseJob:
        return await self.invoke("POST", f"/request/{match_id}")  # type: ignore


class StratzClient(BaseClient):
    def __init__(self) -> None:
        self.rate_limiter = StratzAPIRateLimiter()
        super().__init__(
            base_url="https://api.stratz.com/graphql",
            default_params={},
            default_headers={
                "Authorization": f"Bearer {config.STRATZ_BEARER_TOKEN}",
                "Content-Type": "application/json",
            },
            default_queries={},
            middlewares=[
                json_response_middleware(orjson.loads),
                http_error_middleware(),
                rate_limiter_middleware(self.rate_limiter),
            ],
        )

    async def get_fpc_match_to_edit(
        self, *, match_id: int, friend_id: int
    ) -> schemas.StratzGraphQLQueriesSchema.GetFPCMatchToEdit.ResponseDict:
        query = """
        query GetFPCMatchToEdit ($match_id: Long!, $friend_id: Long!) {
            match(id: $match_id) {
                players(steamAccountId: $friend_id) {
                    item0Id
                    item1Id
                    item2Id
                    item3Id
                    item4Id
                    item5Id
                    neutral0Id
                    playbackData {
                        purchaseEvents {
                            time
                            itemId
                        }
                    }
                    stats {
                        matchPlayerBuffEvent {
                            itemId
                        }
                    }
                }
            }
        }
        """
        json = {"query": query, "variables": {"match_id": match_id, "friend_id": friend_id}}
        return await self.invoke("POST", "")  # type: ignore


if __name__ == "__main__":
    import asyncio
    import pprint

    # OPENDOTA
    async def test_opendota_get_match():
        async with OpenDotaClient() as opendota_client:
            match = await opendota_client.get_match(match_id=7543594334)
            # player = match["players"][5]
            # pprint.pprint(list(player.keys()))
            # pprint.pprint(player["account_id"])
            for item in ["players", "teamfights", "radiant_xp_adv", "radiant_gold_adv", "picks_bans"]:
                match.pop(item, None)  # type: ignore
            # pprint.pprint(match.keys())
            # pprint.pprint(match)
        print(opendota_client.rate_limiter.rate_limits_string)

    async def test_opendota_request_parse():
        async with OpenDotaClient() as opendota_client:
            job = await opendota_client.request_parse(match_id=7543594334)
            # pprint.pprint(job)

    # STRATZ
    async def test_stratz_get_match():
        async with StratzClient() as stratz_client:
            match_id = 7549006442
            friend_id = 159020918
            match = await stratz_client.get_fpc_match_to_edit(match_id=match_id, friend_id=friend_id)
            print(match["data"]["match"]["players"][0]["item3Id"])

        print(stratz_client.rate_limiter.rate_limits_string)

    asyncio.run(test_opendota_get_match())