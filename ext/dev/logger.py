from __future__ import annotations

import asyncio
import datetime
import logging
import textwrap
from typing import TYPE_CHECKING, Any, override

import discord
from discord.ext import tasks

from config import SPAM_LOGS_WEBHOOK
from utils import const, formats

from ._base import DevBaseCog

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bot import AluBot

log = logging.getLogger(__name__)


class LoggingHandler(logging.Handler):
    """Extra logging handler to output info/warning/errors to a discord webhook.

    * Just remember that `log.info` and above calls go spammed in a discord webhook so plan them accordingly.
    * `log.debug` do not so use primarily them for debug logs
    """

    def __init__(self, cog: LoggerViaWebhook) -> None:
        self.cog: LoggerViaWebhook = cog
        super().__init__(logging.INFO)

    @override
    def filter(self, record: logging.LogRecord) -> bool:
        return True  # record.name in ('discord.gateway')

    @override
    def emit(self, record: logging.LogRecord) -> None:
        self.cog.add_record(record)


class LoggerViaWebhook(DevBaseCog):
    # TODO: ADD MORE STUFF
    AVATAR_MAPPING: Mapping[str, str] = {
        "discord.gateway": "https://i.imgur.com/4PnCKB3.png",
        "discord.ext.tasks": "https://em-content.zobj.net/source/microsoft/378/alarm-clock_23f0.png",
        "bot.bot": "https://assets-global.website-files.com/6257adef93867e50d84d30e2/636e0a6a49cf127bf92de1e2_icon_clyde_blurple_RGB.png",
        "send_dota_fpc": "https://i.imgur.com/67ipDvY.png",
        "edit_dota_fpc": "https://i.imgur.com/nkcvMa2.png",
        "ext.dev.sync": "https://em-content.zobj.net/source/microsoft/378/counterclockwise-arrows-button_1f504.png",
        "utils.dota.valvepythondota2": "https://i.imgur.com/D96bMgG.png",
        "utils.dota.dota2client": "https://i.imgur.com/D96bMgG.png",
        "exc_manager": "https://em-content.zobj.net/source/microsoft/378/sos-button_1f198.png",
        "twitchio.ext.eventsub.ws": const.Logo.Twitch,
        # "https://em-content.zobj.net/source/microsoft/378/swan_1f9a2.png",
        "ext.fpc.lol.notifications": const.Logo.Lol,
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._logging_queue = asyncio.Queue()

    @override
    async def cog_load(self) -> None:
        self.logging_worker.start()

    @override
    def cog_unload(self) -> None:
        self.logging_worker.cancel()

    @discord.utils.cached_property
    def logger_webhook(self) -> discord.Webhook:
        return discord.Webhook.from_url(url=SPAM_LOGS_WEBHOOK, session=self.bot.session)

    def add_record(self, record: logging.LogRecord) -> None:
        self._logging_queue.put_nowait(record)

    async def send_log_record(self, record: logging.LogRecord) -> None:
        attributes = {
            "INFO": "\N{INFORMATION SOURCE}\ufe0f",
            "WARNING": "\N{WARNING SIGN}\ufe0f",
            "ERROR": "\N{CROSS MARK}",
        }

        emoji = attributes.get(record.levelname, "\N{WHITE QUESTION MARK ORNAMENT}")
        # the time is there so the MM:SS is more clear. Discord stacks messages from the same webhook user
        # so if logger sends at 23:01 and 23:02 it will be hard to understand the time difference
        dt = datetime.datetime.fromtimestamp(record.created, datetime.UTC)
        msg = textwrap.shorten(f"{emoji} {formats.format_dt(dt, style="T")} {record.message}", width=1995)
        avatar_url = self.AVATAR_MAPPING.get(record.name, discord.utils.MISSING)

        # Discord doesn't allow Webhooks names to contain "discord";
        # so if the record.name comes from discord.py library - it gonna block it
        # thus we replace letters: "c" is cyrillic, "o" is greek.
        username = record.name.replace("discord", "disсοrd")  # cSpell: ignore disсοrd  # noqa: RUF003
        await self.logger_webhook.send(msg, username=username, avatar_url=avatar_url)

    @tasks.loop(seconds=0.0)
    async def logging_worker(self) -> None:
        record = await self._logging_queue.get()
        await self.send_log_record(record)


async def setup(bot: AluBot) -> None:
    cog = LoggerViaWebhook(bot)
    await bot.add_cog(cog)
    bot.logging_handler = handler = LoggingHandler(cog)
    logging.getLogger().addHandler(handler)


async def teardown(bot: AluBot) -> None:
    logging.getLogger().removeHandler(bot.logging_handler)
    del bot.logging_handler