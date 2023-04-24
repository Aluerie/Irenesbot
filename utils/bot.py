from __future__ import annotations

import datetime
import logging
import os
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Union

import discord
from aiohttp import ClientSession
from asyncpg import Pool
from asyncpraw import Reddit
from discord import app_commands
from discord.ext import commands
from dota2.client import Dota2Client
from github import Github
from steam.client import SteamClient
from tweepy.asynchronous import AsyncClient as TwitterAsyncClient

import config as cfg
from cogs import get_extensions
from utils.const.community import CommunityGuild

from .context import Context
from .imgtools import ImgToolsClient
from .jsonconfig import PrefixConfig
from .twitch import TwitchClient
from .var import Clr
from .const.hideout import HideoutGuild

if TYPE_CHECKING:
    from discord.abc import Snowflake

    from cogs.reminders import Reminder

    AppCommandStore = Dict[str, app_commands.AppCommand]  # name: AppCommand

log = logging.getLogger(__name__)


class AluBot(commands.Bot):
    bot_app_info: discord.AppInfo
    dota: Dota2Client
    github: Github
    imgtools: ImgToolsClient
    launch_time: datetime.datetime
    session: ClientSession
    pool: Pool
    prefixes: PrefixConfig
    reddit: Reddit
    steam: SteamClient
    tree: MyCommandTree
    twitch: TwitchClient
    twitter: TwitterAsyncClient
    user: discord.ClientUser

    def __init__(self, test=False):
        main_prefix = '~' if test else '$'
        self.main_prefix = main_prefix
        super().__init__(
            command_prefix=self.get_pre,
            activity=discord.Streaming(name=f"\N{PURPLE HEART} /help /setup", url='https://www.twitch.tv/aluerie'),
            intents=discord.Intents(  # if you ever struggle with it - try `discord.Intents.all()`
                guilds=True,
                members=True,
                bans=True,
                emojis_and_stickers=True,
                voice_states=True,
                presences=True,
                messages=True,
                reactions=True,
                message_content=True,
            ),
            allowed_mentions=discord.AllowedMentions(roles=True, replied_user=False, everyone=False),  # .none()
            tree_cls=MyCommandTree,
        )
        self.client_id: int = cfg.TEST_DISCORD_CLIENT_ID if test else cfg.DISCORD_CLIENT_ID
        self.test: bool = test
        self.app_commands: Dict[str, int] = {}
        self.odota_ratelimit: Dict[str, int] = {'monthly': -1, 'minutely': -1}

        self.repo = 'https://github.com/Aluerie/AluBot'

    async def setup_hook(self) -> None:
        self.session = s = ClientSession()
        self.imgtools = ImgToolsClient(session=s)

        self.prefixes = PrefixConfig(self.pool)
        self.bot_app_info = await self.application_info()

        # ensure temp folder
        # todo: maybe remove the concept of temp folder - don't save .mp3 file
        #  for now it is only used in tts.py for mp3 file
        Path("./.temp/").mkdir(parents=True, exist_ok=True)

        os.environ["JISHAKU_NO_DM_TRACEBACK"] = "True"
        os.environ["JISHAKU_NO_UNDERSCORE"] = "True"
        os.environ["JISHAKU_HIDE"] = "True"  # need to be before loading jsk

        for ext in get_extensions(self.test):
            try:
                await self.load_extension(ext)
            except Exception as e:
                log.exception(f'Failed to load extension {ext}.')
                raise e

    def get_pre(self, bot: AluBot, message: discord.Message) -> Iterable[str]:
        if message.guild is None:
            prefix = self.main_prefix
        else:
            prefix = self.prefixes.get(message.guild.id, self.main_prefix)
        return commands.when_mentioned_or(prefix, "/")(bot, message)

    async def on_ready(self):
        if not hasattr(self, 'launch_time'):
            self.launch_time = discord.utils.utcnow()
        log.info(f'Logged in as {self.user}')

    async def close(self) -> None:
        await super().close()
        if hasattr(self, 'session'):
            await self.session.close()
        if hasattr(self, 'twitch'):
            pass
            await self.twitch.close()

    async def my_start(self) -> None:
        token = cfg.TEST_TOKEN if self.test else cfg.MAIN_TOKEN
        token = cfg.MAIN_TOKEN
        await super().start(token, reconnect=True)

    async def get_context(self, origin: Union[discord.Interaction, discord.Message], /, *, cls=Context) -> Context:
        return await super().get_context(origin, cls=cls)

    @property
    def owner(self) -> discord.User:
        return self.bot_app_info.owner

    def ini_steam_dota(self) -> None:
        if not hasattr(self, 'steam') or not hasattr(self, 'dota'):
            self.steam = SteamClient()
            self.dota = Dota2Client(self.steam)
            self.steam_dota_login()

    def steam_dota_login(self) -> None:
        if self.steam.connected is False:
            log.debug(f"dota2info: client.connected {self.steam.connected}")
            if self.test:
                steam_login, steam_password = (
                    cfg.STEAM_TEST_LGN,
                    cfg.STEAM_TEST_PSW,
                )
            else:
                steam_login, steam_password = (
                    cfg.STEAM_MAIN_LGN,
                    cfg.STEAM_MAIN_PSW,
                )

            if self.steam.login(username=steam_login, password=steam_password):
                self.steam.change_status(persona_state=7)
                log.info('We successfully logged invis mode into Steam')
                self.dota.launch()
            else:
                log.warning('Logging into Steam failed')
                return

    def ini_github(self) -> None:
        if not hasattr(self, 'github'):
            self.github = Github(cfg.GIT_PERSONAL_TOKEN)

    def ini_reddit(self) -> None:
        if not hasattr(self, 'reddit'):
            self.reddit = Reddit(
                client_id=cfg.REDDIT_CLIENT_ID,
                client_secret=cfg.REDDIT_CLIENT_SECRET,
                password=cfg.REDDIT_PASSWORD,
                user_agent=cfg.REDDIT_USER_AGENT,
                username=cfg.REDDIT_USERNAME,
            )

    async def ini_twitch(self) -> None:
        if not hasattr(self, 'twitch'):
            self.twitch = TwitchClient(cfg.TWITCH_TOKEN)
            await self.twitch.connect()

    def ini_twitter(self) -> None:
        if not hasattr(self, 'twitter'):
            self.twitter = TwitterAsyncClient(cfg.TWITTER_BEARER_TOKEN)

    def update_odota_ratelimit(self, headers) -> None:
        monthly = headers.get('X-Rate-Limit-Remaining-Month')
        minutely = headers.get('X-Rate-Limit-Remaining-Minute')
        if monthly is not None or minutely is not None:
            self.odota_ratelimit = {'monthly': monthly, 'minutely': minutely}

    @property
    def reminder(self) -> Optional[Reminder]:
        return self.get_cog('Reminder')  # type: ignore

    async def send_traceback(
        self,
        error: Exception,
        destination: Optional[discord.TextChannel] = None,
        *,
        where: str = 'not specified',
        embed: Optional[discord.Embed] = None,
        verbosity: int = 10,
        mention: bool = True,
    ) -> None:
        """Function to send traceback into the discord channel.
        Parameters
        -----------
        error: :class: Exception
            Exception that is going to be sent to the `destination`
        destination:
            where to send the traceback message
        where:
            Just a text prompt to include into the default embed
            about where exactly error happened
            if `embed` is specified then this is ignored essentially
        embed:
            When specifying `where` is not enough
            you can make the whole embed instead of using default embed `where`
        verbosity:
            A parameter for `traceback.format_exception()`
        mention: bool
            if True then the message will mention the bot owner
        Returns
        --------
        None
        """

        ch: discord.TextChannel = destination or self.hideout.spam

        etype, value, trace = type(error), error, error.__traceback__
        traceback_content = "".join(traceback.format_exception(etype, value, trace, verbosity)).replace(
            "``", "`\u200b`"
        )

        paginator = commands.Paginator(prefix='```python')
        for line in traceback_content.split('\n'):
            paginator.add_line(line)

        e = embed or discord.Embed(colour=Clr.error).set_author(name=where)
        content = self.owner.mention if mention else ''
        await ch.send(content=content, embed=e)

        for page in paginator.pages:
            await ch.send(page)

    # SHORTCUTS ########################################################################################################
    
    @property
    def hideout(self) -> HideoutGuild:
        return HideoutGuild(self)
    
    @property
    def community(self) -> CommunityGuild:
        return CommunityGuild(self)


# ######################################################################################################################
# ########################################### MY COMMAND APP TREE ######################################################
# ######################################################################################################################


# Credits to @Soheab
# https://gist.github.com/Soheab/fed903c25b1aae1f11a8ca8c33243131#file-bot_subclass
class MyCommandTree(app_commands.CommandTree):
    """Custom Command tree class to set up slash cmds mentions

    The class makes the tree store app_commands.AppCommand
    to access later for mentioning or anything
    """

    def __init__(self, client: AluBot):
        super().__init__(client=client)
        self._global_app_commands: AppCommandStore = {}
        # guild_id: AppCommandStore
        self._guild_app_commands: Dict[int, AppCommandStore] = {}

    def find_app_command_by_names(
        self,
        *qualified_name: str,
        guild: Optional[Union[Snowflake, int]] = None,
    ) -> Optional[app_commands.AppCommand]:
        commands_dict = self._global_app_commands
        if guild:
            guild_id = guild.id if not isinstance(guild, int) else guild
            guild_commands = self._guild_app_commands.get(guild_id, {})
            if not guild_commands and self.fallback_to_global:
                commands_dict = self._global_app_commands
            else:
                commands_dict = guild_commands

        for cmd_name, cmd in commands_dict.items():
            if any(name in qualified_name for name in cmd_name.split()):
                return cmd

        return None

    def get_app_command(
        self,
        value: Union[str, int],
        guild: Optional[Union[Snowflake, int]] = None,
    ) -> Optional[app_commands.AppCommand]:
        def search_dict(d: AppCommandStore) -> Optional[app_commands.AppCommand]:
            for cmd_name, cmd in d.items():
                if value == cmd_name or (str(value).isdigit() and int(value) == cmd.id):
                    return cmd
            return None

        if guild:
            guild_id = guild.id if not isinstance(guild, int) else guild
            guild_commands = self._guild_app_commands.get(guild_id, {})
            if not self.fallback_to_global:
                return search_dict(guild_commands)
            else:
                return search_dict(guild_commands) or search_dict(self._global_app_commands)
        else:
            return search_dict(self._global_app_commands)

    @staticmethod
    def _unpack_app_commands(commands: List[app_commands.AppCommand]) -> AppCommandStore:
        ret: AppCommandStore = {}

        def unpack_options(
            options: List[Union[app_commands.AppCommand, app_commands.AppCommandGroup, app_commands.Argument]]
        ):
            for option in options:
                if isinstance(option, app_commands.AppCommandGroup):
                    ret[option.qualified_name] = option  # type: ignore
                    unpack_options(option.options)  # type: ignore

        for command in commands:
            ret[command.name] = command
            unpack_options(command.options)  # type: ignore

        return ret

    async def _update_cache(
        self, commands: List[app_commands.AppCommand], guild: Optional[Union[Snowflake, int]] = None
    ) -> None:
        # because we support both int and Snowflake
        # we need to convert it to a Snowflake like object if it's an int
        _guild: Optional[Snowflake] = None
        if guild is not None:
            if isinstance(guild, int):
                _guild = discord.Object(guild)
            else:
                _guild = guild

        if _guild:
            self._guild_app_commands[_guild.id] = self._unpack_app_commands(commands)
        else:
            self._global_app_commands = self._unpack_app_commands(commands)

    async def fetch_command(self, command_id: int, /, *, guild: Optional[Snowflake] = None) -> app_commands.AppCommand:
        res = await super().fetch_command(command_id, guild=guild)
        await self._update_cache([res], guild=guild)
        return res

    async def fetch_commands(self, *, guild: Optional[Snowflake] = None) -> List[app_commands.AppCommand]:
        res = await super().fetch_commands(guild=guild)
        await self._update_cache(res, guild=guild)
        return res

    def clear_app_commands_cache(self, *, guild: Optional[Snowflake]) -> None:
        if guild:
            self._guild_app_commands.pop(guild.id, None)
        else:
            self._global_app_commands = {}

    def clear_commands(
        self,
        *,
        guild: Optional[Snowflake],
        type: Optional[discord.AppCommandType] = None,
        clear_app_commands_cache: bool = True,
    ) -> None:
        super().clear_commands(guild=guild)
        if clear_app_commands_cache:
            self.clear_app_commands_cache(guild=guild)

    async def sync(self, *, guild: Optional[Snowflake] = None) -> List[app_commands.AppCommand]:
        res = await super().sync(guild=guild)
        await self._update_cache(res, guild=guild)
        return res


# ######################################################################################################################
# ############################################# LOGGING MAGIC ##########################################################
# ######################################################################################################################


class MyColourFormatter(logging.Formatter):
    # ANSI codes are a bit weird to decipher if you're unfamiliar with them, so here's a refresher
    # It starts off with a format like \x1b[XXXm where XXX is a semicolon separated list of commands
    # The important ones here relate to colour.
    # 30-37 are black, red, green, yellow, blue, magenta, cyan and white in that order
    # 40-47 are the same except for the background
    # 90-97 are the same but "bright" foreground
    # 100-107 are the same as the bright ones but for the background.
    # 1 means bold, 2 means dim, 0 means reset, and 4 means underline.

    LEVEL_COLOURS = [
        (logging.DEBUG, '\x1b[40;1m'),
        (logging.INFO, '\x1b[34;1m'),
        (logging.WARNING, '\x1b[33;1m'),
        (logging.ERROR, '\x1b[31m'),
        (logging.CRITICAL, '\x1b[41m'),
    ]

    FORMATS = {
        level: logging.Formatter(
            f'\x1b[37;1m%(asctime)s\x1b[0m | {colour}%(levelname)-7s\x1b[0m | '
            f'\x1b[35m%(name)-23s\x1b[0m | %(lineno)-4d | %(funcName)-30s | %(message)s',
            '%H:%M:%S %d/%m',
        )
        for level, colour in LEVEL_COLOURS
    }

    def format(self, record):
        formatter = self.FORMATS.get(record.levelno)
        if formatter is None:
            formatter = self.FORMATS[logging.DEBUG]

        # Override the traceback to always print in red
        if record.exc_info:
            text = formatter.formatException(record.exc_info)
            record.exc_text = f'\x1b[31m{text}\x1b[0m'

        output = formatter.format(record)

        # Remove the cache layer
        record.exc_text = None
        return output


def get_log_fmt(handler: logging.Handler):
    if (
        isinstance(handler, logging.StreamHandler)
        and discord.utils.stream_supports_colour(handler.stream)
        and not isinstance(handler, RotatingFileHandler)
    ):  # force file handler fmt into `else`
        formatter = MyColourFormatter()
    else:
        formatter = logging.Formatter(
            '{asctime} | {levelname:<7} | {name:<23} | {lineno:<4} | {funcName:<30} | {message}',
            '%H:%M:%S %d/%m',
            style='{',
        )

    return formatter
