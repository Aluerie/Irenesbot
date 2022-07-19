from __future__ import annotations
from typing import TYPE_CHECKING, Optional

from steam.core.msg import MsgProto
from steam.enums import emsg
from steam.steamid import SteamID, EType
import vdf

from discord import Embed, TextChannel, app_commands
from discord.ext import commands, tasks

from utils import database as db
from utils import dota as d2
from utils.checks import is_guild_owner, is_trustee
from utils.var import *
from utils.imgtools import img_to_file, url_to_img
from utils.format import display_relativehmstime
from utils.distools import send_traceback, send_pages_list
from utils.mysteam import sd_login
from cogs.twitch import TwitchStream, get_dota_streams, get_twtv_id, twitch_by_id

import re
from PIL import Image, ImageOps, ImageDraw, ImageFont
from datetime import datetime, timezone, time

if TYPE_CHECKING:
    from utils.context import Context


import logging
log = logging.getLogger('root')
lobbyids = set()
to_be_posted = {}


async def try_to_find_games(bot, ses):
    log.info("TryToFindGames dota2info")
    global to_be_posted, lobbyids
    to_be_posted = {}
    lobbyids = set()
    fav_hero_ids = []
    for row in ses.query(db.ga):
        fav_hero_ids += row.dotafeed_hero_ids
    fav_hero_ids = list(set(fav_hero_ids))

    sd_login(bot.steam, bot.dota, bot.steam_lgn, bot.steam_psw)

    # @dota.on('ready')
    def ready_function():
        log.info("ready_function dota2info")
        bot.dota.request_top_source_tv_games(lobby_ids=list(lobbyids))

    # @dota.on('top_source_tv_games')
    def response(result):
        log.info(f"top_source_tv_games resp ng: {result.num_games} sg: {result.specific_games}")
        if result.specific_games:
            friendids = [row.friendid for row in ses.query(db.d.friendid)]
            for match in result.game_list:  # games
                our_persons = [x for x in match.players if x.account_id in friendids and x.hero_id in fav_hero_ids]
                for person in our_persons:
                    user = ses.query(db.d).filter_by(friendid=person.account_id).first()
                    if user.lastposted != match.match_id:
                        to_be_posted[user.name] = {
                            'matchid': match.match_id,
                            'st_time': match.activate_time,
                            'streamer': user.name,
                            'twtv_id': user.twtv_id,
                            'heroid': person.hero_id,
                            'hero_ids': [x.hero_id for x in match.players],
                        }
            log.info(f'to_be_posted {to_be_posted}')
        bot.dota.emit('top_games_response')

    proto_msg = MsgProto(emsg.EMsg.ClientRichPresenceRequest)
    proto_msg.header.routing_appid = 570
    steamids = [row.id for row in ses.query(db.d).filter(db.d.twtv_id.in_(get_dota_streams())).all()]
    # print(steamids)
    proto_msg.body.steamid_request.extend(steamids)
    resp = bot.steam.send_message_and_wait(proto_msg, emsg.EMsg.ClientRichPresenceInfo, timeout=8)
    if resp is None:
        print('resp is None, hopefully everything else will be fine tho;')
        return
    for item in resp.rich_presence:
        if rp_bytes := item.rich_presence_kv:
            # steamid = item.steamid_user
            rp = vdf.binary_loads(rp_bytes)['RP']
            # print(rp)
            if lobby_id := int(rp.get('WatchableGameID', 0)):
                if rp.get('param0', 0) == '#DOTA_lobby_type_name_ranked':
                    if await d2.id_by_npcname(rp.get('param2', '#')[1:]) in fav_hero_ids:  # that's npcname
                        lobbyids.add(lobby_id)

    # print(lobbyids)
    log.info(f'lobbyids {lobbyids}')
    # dota.on('ready', ready_function)
    bot.dota.once('top_source_tv_games', response)
    ready_function()
    bot.dota.wait_event('top_games_response', timeout=8)


async def better_thumbnail(session, stream, hero_ids, heroname):
    img = await url_to_img(session, stream.preview_url)
    width, height = img.size
    rectangle = Image.new("RGB", (width, 70), '#9678b6')
    ImageDraw.Draw(rectangle)
    img.paste(rectangle)

    for count, heroId in enumerate(hero_ids):
        hero_img = await url_to_img(session, await d2.iconurl_by_id(heroId))
        # h_width, h_height = heroImg.size
        hero_img = hero_img.resize((62, 35))
        hero_img = ImageOps.expand(hero_img, border=(0, 3, 0, 0), fill=Clr.dota_colour_map.get(count))
        extra_space = 0 if count < 5 else 20
        img.paste(hero_img, (count * 62 + extra_space, 0))

    font = ImageFont.truetype('./media/Inter-Black-slnt=0.ttf', 33)
    draw = ImageDraw.Draw(img)
    text = f'{stream.display_name} - {heroname}'
    w2, h2 = draw.textsize(text, font=font)
    draw.text(((width - w2) / 2, 35), text, font=font, align="center")
    return img


class DotaFeed(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.dotafeed.start()

    async def send_the_embed(self, tbp, session):
        log.info("sending dota 2 embed")
        match_id, streamer, heroid, hero_ids, twtv_id = \
            tbp['matchid'], tbp['streamer'], tbp['heroid'], tbp['hero_ids'], tbp['twtv_id']
        long_ago = datetime.now(timezone.utc).timestamp() - tbp['st_time']

        twitch = TwitchStream(streamer)
        heroname = await d2.name_by_id(heroid)
        image_name = f'{streamer.replace("_", "")}-playing-{heroname.replace(" ", "")}.png'
        img_file = img_to_file(await better_thumbnail(self.bot.ses, twitch, hero_ids, heroname), filename=image_name)

        em = Embed(
            colour=Clr.prpl,
            url=twitch.url,
            description=
            f'`/match {match_id}` started {display_relativehmstime(long_ago)}\n' 
            f'{f"[TwtvVOD]({link})" if (link := twitch.last_vod_link(time_ago=long_ago)) is not None else ""}'
            f'/[Dotabuff](https://www.dotabuff.com/matches/{match_id})'
            f'/[Opendota](https://www.opendota.com/matches/{match_id})'
            f'/[Stratz](https://stratz.com/matches/{match_id})'
        ).set_image(
            url=f'attachment://{image_name}'
        ).set_thumbnail(
            url=await d2.iconurl_by_id(heroid)
        ).set_author(
            name=f'{twitch.display_name} - {heroname}',
            url=twitch.url,
            icon_url=twitch.logo_url
        )

        for row in db.session.query(db.ga):
            if heroid in row.dotafeed_hero_ids and twtv_id in row.dotafeed_stream_ids:
                ch: TextChannel = self.bot.get_channel(row.dotafeed_ch_id)
                em.title = f"{ch.guild.owner.name}'s fav hero + fav stream spotted !"
                msg = await ch.send(embed=em, file=img_file)
                if ch.is_news():
                    await msg.publish()

        for row in session.query(db.d).filter_by(name=streamer):
            row.lastposted = match_id
        return 1

    @tasks.loop(seconds=59)
    async def dotafeed(self):
        with db.session_scope() as ses:
            await try_to_find_games(self.bot, ses)
            for key in to_be_posted:
                await self.send_the_embed(to_be_posted[key], ses)

    @dotafeed.before_loop
    async def before(self):
        log.info("dotafeed before loop wait")
        await self.bot.wait_until_ready()

    @dotafeed.error
    async def dotafeed_error(self, error):
        # TODO: write if isinstance(RunTimeError): be silent else do send_traceback or something,
        #  probably declare your own error type
        await send_traceback(error, self.bot, embed=Embed(colour=Clr.error, title='Error in dotafeed'))
        # self.dotafeed.restart()


class AddStreamFlags(commands.FlagConverter, case_insensitive=True):
    twitch: str
    steam: str


class RemoveStreamFlags(commands.FlagConverter, case_insensitive=True):
    twitch: str
    steam: Optional[str]


class DotaFeedTools(commands.Cog, name='Dota 2'):
    """
    Commands to set up fav hero + fav stream notifs.

    These commands allow you to choose streamers from our database as your favorite \
    (or you can request adding them if they are missing) and choose your favorite Dota 2 heroes. \
    The bot will send messages in a chosen channel when your fav streamer picks your fav hero.

    **Tutorial**
    1. Set channel with
    `$dota channel set #channel`
    2. Add fav streams, i.e.
    `$dota stream add gorgc, bububu`
    3. Add missing streams to `$dota database list`, i.e.
    `$dota database add twitch: cr1tdota steam: 76561197986172872`
    Only trustees can use `database add`. Others should `$dota database request` their fav streams.
    4. Add fav heroes, i.e.
    `$dota hero add Dark Willow, Mirana, Anti-Mage`
    5. Use `remove` counterpart commands to `add` to edit out streams/heroes
    *Pro-Tip.* As shown for multiple hero/stream add/remove commands - use commas to separate names
    6. Ready ! More info below
    """

    def __init__(self, bot):
        self.bot = bot
        self.help_emote = Ems.DankLove

    @is_guild_owner()
    @commands.hybrid_group()
    @app_commands.default_permissions(administrator=True)
    async def dota(self, ctx: Context):
        """Group command about Dota 2, for actual commands use it together with subcommands"""
        await ctx.scnf()

    @is_guild_owner()
    @dota.group()
    async def channel(self, ctx: Context):
        """Group command about Dota 2, for actual commands use it together with subcommands"""
        await ctx.scnf()

    @is_guild_owner()
    @channel.command(
        name='set',
        usage='[channel=curr]'
    )
    @app_commands.describe(channel='Choose channel for Dota2Feed notifications')
    async def channel_set(self, ctx: Context, channel: Optional[TextChannel] = None):
        """
        Set channel to be the Dota2Feed notifications channel.
        """
        channel = channel or ctx.channel
        if not channel.permissions_for(ctx.guild.me).send_messages:
            em = Embed(
                colour=Clr.error,
                description='I do not have permissions to send messages in that channel :('
            )
            return await ctx.reply(embed=em)

        db.set_value(db.ga, ctx.guild.id, dotafeed_ch_id=channel.id)
        em = Embed(
            colour=Clr.prpl,
            description=f'Channel {channel.mention} is set to be the DotaFeed channel for this server'
        )
        await ctx.reply(embed=em)

    @is_guild_owner()
    @channel.command(
        name='disable',
        description='Disable Dota2Feed functionality.'
    )
    async def channel_disable(self, ctx: Context):
        """
        Stop getting Dota2Feed notifications. \
        Data about fav heroes/streamers won't be affected.
        """
        ch_id = db.get_value(db.ga, ctx.guild.id, 'dotafeed_ch_id')
        ch = self.bot.get_channel(ch_id)
        if ch is None:
            em = Embed(
                colour=Clr.error,
                description=f'DotaFeed channel is not set or already was reset'
            )
            return await ctx.reply(embed=em)
        db.set_value(db.ga, ctx.guild.id, dotafeed_ch_id=None)
        em = Embed(
            colour=Clr.prpl,
            description=f'Channel {ch.mention} is set to be the DotaFeed channel for this server.'
        )
        await ctx.reply(embed=em)

    @is_guild_owner()
    @channel.command(name='check')
    async def channel_check(self, ctx: Context):
        """
        Check if a Dota2Feed channel was set in this server.
        """
        ch_id = db.get_value(db.ga, ctx.guild.id, 'dotafeed_ch_id')
        ch = self.bot.get_channel(ch_id)
        if ch is None:
            em = Embed(
                colour=Clr.prpl,
                description=f'DotaFeed channel is not currently set.'
            )
            return await ctx.reply(embed=em)
        else:
            em = Embed(
                colour=Clr.prpl,
                description=f'DotaFeed channel is currently set to {ch.mention}.'
            )
            return await ctx.reply(embed=em)

    @is_guild_owner()
    @dota.group(aliases=['db'])
    async def database(self, ctx: Context):
        """Group command about Dota 2, for actual commands use it together with subcommands"""
        await ctx.scnf()

    @is_guild_owner()
    @database.command(name='list')
    async def database_list(self, ctx: Context):
        """
        List of all streamers in database \
        available for Dota2Feed feature.
        """
        await ctx.defer()

        ss_dict = dict()
        for row in db.session.query(db.d):
            key = f"● [**{row.name}**](https://www.twitch.tv/{row.name})"
            if key not in ss_dict:
                ss_dict[key] = []
            ss_dict[key].append(
                f"`{row.id}` - `{row.friendid}`| "
                f"[Steam](https://steamcommunity.com/profiles/{row.id})"
                f"/[Dotabuff](https://www.dotabuff.com/players/{row.friendid})"
            )

        ans_array = [f"{k}\n {chr(10).join(ss_dict[k])}" for k in ss_dict]
        ans_array = sorted(list(set(ans_array)), key=str.casefold)

        await send_pages_list(
            ctx,
            ans_array,
            split_size=10,
            colour=Clr.prpl,
            title="List of Dota 2 Streams in Database",
            footer_text=f'With love, {ctx.guild.me.display_name}'
        )

    @staticmethod
    def field_info_str(twitch, steamid, friendid):
        return  \
            f"[**{twitch}**](https://www.twitch.tv/{twitch})\n" \
            f"`{steamid}` - `{friendid}`| " \
            f"[Steam](https://steamcommunity.com/profiles/{steamid})" \
            f"/[Dotabuff](https://www.dotabuff.com/players/{friendid})"

    @staticmethod
    async def get_steam_id_and_64(ctx: Context, steam: str):
        steam = SteamID(steam)
        if steam.type != EType.Individual:
            steam = SteamID.from_url(steam)

        if steam is None or (hasattr(steam, 'type') and steam.type != EType.Individual):
            em = Embed(
                colour=Clr.error,
                description=
                f'Error checking steam profile for {steam}.\n '
                f'Check if your `steam` flag is correct steam id in either 64/32/3/2/friendid representations '
                f'or just give steam profile link to the bot.'
            )
            await ctx.reply(embed=em, ephemeral=True)
            return None, None

        return steam.as_64, steam.id

    @staticmethod
    async def get_check_twitch_id(ctx: Context, twitch: str):
        twtv_id = get_twtv_id(twitch.lower())
        if twtv_id is None:
            em = Embed(
                colour=Clr.error,
                description=f'Error checking stream {twitch}.\n User either does not exist or is banned.'
            )
            await ctx.reply(embed=em, ephemeral=True)
            return None

        return twtv_id

    @is_trustee()
    @database.command(
        name='add',
        usage='twitch: <twitch_name> steam: <steamid>',
        description='Add stream to the database.'
    )
    @app_commands.describe(
        twitch='twitch.tv stream name',
        steam='either steamid in any of 64/32/3/2 versions, friendid or just steam profile link'
    )
    async def database_add(self, ctx: Context, *, flags: AddStreamFlags):
        """
        Add stream to the database.
        • `<twitch_name>` is twitch.tv stream name
        • `<steamid>` is either steamid in any of 64/32/3/2 versions, friendid or just steam profile link.
        """
        await ctx.defer()

        twtv_id = await self.get_check_twitch_id(ctx, flags.twitch.lower())
        if twtv_id is None:
            return

        steamid, friendid = await self.get_steam_id_and_64(ctx, flags.steam)
        if steamid is None:
            return

        if (user := db.session.query(db.d).filter_by(id=steamid).first()) is not None:
            em = Embed(
                colour=Clr.error
                ).add_field(
                name=f'This steam account is already in the database',
                value=
                f'It is marked as [{user.name}](https://www.twitch.tv/{user.name})\'s account.\n\n'
                f'Did you mean to use `$dota stream add {user.name}` to add the stream into your fav list?'
            )
            return await ctx.reply(embed=em, ephemeral=True)

        db.add_row(db.d, steamid, name=flags.twitch.lower(), friendid=friendid, twtv_id=twtv_id)
        em = Embed(
            colour=Clr.prpl
        ).add_field(
            name=f'Successfully added the account to the database',
            value=self.field_info_str(flags.twitch.lower(), steamid, friendid)
        )
        await ctx.reply(embed=em)
        em.colour = MP.green(shade=200)
        em.set_author(name=ctx.author, icon_url=ctx.author.avatar.url)
        await self.bot.get_channel(Cid.global_logs).send(embed=em)

    @is_trustee()
    @database.command(
        name='remove',
        usage='twitch: <twitch_name> steam: <steamid>'
    )
    @app_commands.describe(
        twitch='twitch.tv stream name',
        steam='either steamid in any of 64/32/3/2 versions, friendid or just steam profile link'
    )
    async def database_remove(self, ctx: Context, *, flags: RemoveStreamFlags):
        """
        Remove stream from database.
        """
        await ctx.defer()

        map_dict = {'name': flags.twitch.lower()}
        if flags.steam:
            steamid, friendid = await self.get_steam_id_and_64(ctx, flags.steam)
            if steamid is None:
                return
            map_dict['id'] = steamid

        success = []
        with db.session_scope() as ses:
            query = ses.query(db.d).filter_by(**map_dict)
            for row in query:
                success.append(
                    {
                        'name': row.name,
                        'id': row.id,
                        'friendid': row.friendid
                    }
                )
            query.delete()
        if success:
            em = Embed(
                colour=Clr.prpl,
            ).add_field(
                name='Successfully removed account(-s) from the database',
                value=
                '\n'.join(self.field_info_str(x['name'], x['id'], x['friendid']) for x in success)
            )
            await ctx.reply(embed=em)

            em.colour = MP.red(shade=200)
            em.set_author(name=ctx.author, icon_url=ctx.author.avatar.url)
            await self.bot.get_channel(Cid.global_logs).send(embed=em)
        else:
            em = Embed(
                colour=Clr.error
            ).add_field(
                name='There is no account in the database like that',
                value=', '.join([f'{k}: {v}' for k, v in flags.__dict__.items()])
            )
            await ctx.reply(embed=em)

    @is_guild_owner()
    @database.command(
        name='request',
        usage='twitch: <twitch_name> steam: <steamid>',
        description='Request streamer to be added into a database.'
    )
    @app_commands.describe(
        twitch='twitch.tv stream name',
        steam='either steamid in any of 64/32/3/2 versions, friendid or just steam profile link'
    )
    async def database_request(self, ctx: Context, *, flags: AddStreamFlags):
        """
        Request streamer to be added into a database. \
        This will send a request message into Aluerie's personal logs channel.
        """
        await ctx.defer()

        twtv_id = await self.get_check_twitch_id(ctx, flags.twitch.lower())
        if twtv_id is None:
            return

        steamid, friendid = self.get_steam_id_and_64(ctx, flags.steam)
        if steamid is None:
            return

        warn_em = Embed(
            colour=Clr.prpl,
            title='Confirmation Prompt',
            description=
            f'Are you sure you want to request this streamer steam account to be added into the database?\n'
            f'This information will be sent to Aluerie. Please, double check before confirming.'
        ).add_field(
            name='Request to add an account into the database',
            value=self.field_info_str(flags.twitch.lower(), steamid, friendid)
        )
        confirm = await ctx.prompt(embed=warn_em)
        if not confirm:
            return await ctx.send('Aborting...', delete_after=5.0)

        warn_em.colour = MP.orange(shade=200)
        warn_em.description = ''
        warn_em.set_author(name=ctx.author, icon_url=ctx.author.avatar.url)
        warn_em.add_field(
            name='Command',
            value=f'`$dota stream add twitch: {flags.twitch.lower()} steam: {steamid}`'
        )
        await self.bot.get_channel(Cid.global_logs).send(embed=warn_em)

    @is_guild_owner()
    @dota.group(aliases=['streamer'])
    async def stream(self, ctx: Context):
        """Group command about Dota 2, for actual commands use it together with subcommands"""
        await ctx.scnf()

    @staticmethod
    async def stream_add_remove(ctx, twitch_names, mode):
        twitch_list = set(db.get_value(db.ga, ctx.guild.id, 'dotafeed_stream_ids'))

        success = []
        fail = []
        already = []

        for name in re.split('; |, |,', twitch_names):
            streamer = db.session.query(db.d).filter_by(name=name.lower()).first()
            if streamer is None:
                fail.append(f'`{name}`')
            else:
                if mode == 'add':
                    if streamer.twtv_id in twitch_list:
                        already.append(f'`{name}`')
                    else:
                        twitch_list.add(streamer.twtv_id)
                        success.append(f'`{name}`')
                elif mode == 'remov':
                    if streamer.twtv_id not in twitch_list:
                        already.append(f'`{name}`')
                    else:
                        twitch_list.remove(streamer.twtv_id)
                        success.append(f'`{name}`')
        db.set_value(db.ga, ctx.guild.id, dotafeed_stream_ids=list(twitch_list))

        if len(success):
            em = Embed(
                colour=Clr.prpl
            ).add_field(
                name=f'Successfully {mode}ed following streamers: \n',
                value=", ".join(success)
            )
            await ctx.reply(embed=em)
        if len(already):
            em = Embed(
                colour=MP.orange(shade=500)
            ).add_field(
                name=f'Stream(-s) already {"not" if mode=="remov" else ""} in fav list',
                value=", ".join(already)
            )
            await ctx.reply(embed=em)
        if len(fail):
            em = Embed(
                colour=Clr.error
            ).add_field(
                name='Could not find streamers in the database from these names:',
                value=", ".join(fail)
            ).set_footer(
                text=
                'Check your argument or '
                'consider adding (for trustees)/requesting such streamer with '
                '`$dota database add/request twitch: <twitch_name> steam: <steamid>`'
            )
            await ctx.reply(embed=em)

    @is_guild_owner()
    @stream.command(
        name='add',
        usage='<twitch_name(-s)>'
    )
    @app_commands.describe(twitch_names='Name(-s) of twitch streams')
    async def stream_add(self, ctx: Context, *, twitch_names: str):
        """
        Add twitch stream(-s) to the list of your fav Dota 2 streamers.
        """
        await self.stream_add_remove(ctx, twitch_names, mode='add')

    @is_guild_owner()
    @stream.command(
        name='remove',
        usage='<twitch_name(-s)>'
    )
    @app_commands.describe(twitch_names='Name(-s) of twitch streams')
    async def stream_remove(self, ctx: Context, *, twitch_names: str):
        """
        Remove twitch stream(-s) from the list of your fav Dota 2 streamers.
        """
        await self.stream_add_remove(ctx, twitch_names, mode='remov')

    @is_guild_owner()
    @stream.command(name='list')
    async def stream_list(self, ctx: Context):
        """
        Show current list of fav streams.
        """
        twtvid_list = db.get_value(db.ga, ctx.guild.id, 'dotafeed_stream_ids')
        names_list = [row.name for row in db.session.query(db.d).filter(db.d.twtv_id.in_(twtvid_list)).all()]

        ans_array = [f"[{name}](https://www.twitch.tv/{name})" for name in names_list]
        ans_array = sorted(list(set(ans_array)), key=str.casefold)
        embed = Embed(
            color=Clr.prpl,
            title='List of fav dota 2 streamers',
            description="\n".join(ans_array)
        )
        await ctx.reply(embed=embed)

    @is_guild_owner()
    @dota.group()
    async def hero(self, ctx: Context):
        """Group command about Dota 2, for actual commands use it together with subcommands"""
        await ctx.scnf()

    @staticmethod
    async def hero_add_remove(ctx, hero_names, mode):
        hero_list = set(db.get_value(db.ga, ctx.guild.id, 'dotafeed_hero_ids'))
        success = []
        fail = []
        already = []
        for name in re.split('; |, |,', hero_names):
            try:
                if (hero_id := await d2.id_by_name(name)) is not None:
                    hero_name = f'`{await d2.name_by_id(hero_id)}`'
                    if mode == 'add':
                        if hero_id in hero_list:
                            already.append(hero_name)
                        else:
                            hero_list.add(hero_id)
                            success.append(hero_name)
                    elif mode == 'remov':
                        if hero_id not in hero_id:
                            already.append(hero_name)
                        else:
                            hero_list.remove(hero_id)
                            success.append(hero_name)

            except KeyError:
                fail.append(f'`{name}`')

        db.set_value(db.ga, ctx.guild.id, dotafeed_hero_ids=list(hero_list))

        if len(success):
            em = Embed(
                colour=Clr.prpl
            ).add_field(
                name=f'Successfully {mode}ed following heroes',
                value=", ".join(success)
            )
            await ctx.reply(embed=em)
        if len(already):
            em = Embed(
                colour=MP.orange(shade=500)
            ).add_field(
                name=f'Hero(-s) already {"not" if mode=="remov" else ""} in fav list',
                value=", ".join(already)
            )
        if len(fail):
            em = Embed(
                colour=Clr.error
            ).add_field(
                name='Could not recognize Dota 2 heroes from these names',
                value=", ".join(fail)
            ).set_footer(
                text='You can look in $help for help in hero names'
            )
            await ctx.reply(embed=em)

    @is_guild_owner()
    @hero.command(
        name='add',
        usage='<hero_name(-s)>',
        description='Add hero(-es) to your fav heroes list.'
    )
    @app_commands.describe(hero_names='Name(-s) from Dota 2 Hero grid')
    async def hero_add(self, ctx: commands.Context, *, hero_names: str):
        """
        Add hero(-es) to your fav heroes list. \
        Use names from Dota 2 hero grid. For example,
        • `Anti-Mage` (letter case does not matter) and not `Magina`;
        • `Queen of Pain` and not `QoP`.
        At last you can find proper name [here](https://api.opendota.com/api/constants/heroes) with Ctrl+F \
        under one of `"localized_name"`
        """
        await self.hero_add_remove(ctx, hero_names, mode='add')

    @is_guild_owner()
    @hero.command(
        name='remove',
        usage='<hero_name(-s)>'
    )
    @app_commands.describe(hero_names='Name(-s) from Dota 2 Hero grid')
    async def hero_remove(self, ctx: commands.Context, *, hero_names: str):
        """
        Remove hero(-es) from your fav heroes list.
        """
        await self.hero_add_remove(ctx, hero_names, mode='remov')

    @staticmethod
    async def hero_add_remove_error(ctx: Context, error):
        if isinstance(error.original, KeyError):
            ctx.error_handled = True
            em = Embed(
                colour=Clr.error,
                description=
                f'Looks like there is no hero with name `{error.original}`. '

            ).set_author(
                name='HeroNameNotFound'
            )
            await ctx.send(embed=em)

    @hero_add.error
    async def hero_remove_error(self, ctx: Context, error):
        await self.hero_add_remove_error(ctx, error)

    @hero_remove.error
    async def hero_remove_error(self, ctx: Context, error):
        await self.hero_add_remove_error(ctx, error)

    @is_guild_owner()
    @hero.command(name='list')
    async def hero_list(self, ctx: Context):
        """
        Show current list of fav heroes.
        """
        hero_list = db.get_value(db.ga, ctx.guild.id, 'dotafeed_hero_ids')
        answer = [f'`{await d2.name_by_id(h_id)} - {h_id}`' for h_id in hero_list]
        answer.sort()
        em = Embed(
            color=Clr.prpl,
            title='List of fav dota 2 heroes',
            description='\n'.join(answer)
        )
        await ctx.reply(embed=em)


class DotaAccCheck(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.check_acc_renames.start()

    @tasks.loop(time=time(hour=12, minute=11, tzinfo=timezone.utc))
    async def check_acc_renames(self):
        with db.session_scope() as ses:
            for row in ses.query(db.d):
                name = twitch_by_id(row.twtv_id)
                if name != row.name:
                    row.name = name

    @check_acc_renames.before_loop
    async def before(self):
        log.info("check_acc_renames before the loop")
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(DotaFeed(bot))
    await bot.add_cog(DotaFeedTools(bot))
    if datetime.now(timezone.utc).day == 16:
        await bot.add_cog(DotaAccCheck(bot))
