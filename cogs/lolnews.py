from __future__ import annotations

import asyncio
import traceback
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup
from discord import Embed
from discord.ext import commands, tasks

from .utils.format import block_function
from .utils.links import replace_tco_links, move_link_to_title
from .utils.var import Cid, umntn, Sid, Uid, Img, Clr

if TYPE_CHECKING:
    from discord import Message
    from .utils.bot import AluBot


class CopypasteLeague(commands.Cog):
    def __init__(self, bot):
        self.bot: AluBot = bot
        self.patch_checker.start()

    def cog_unload(self) -> None:
        self.patch_checker.cancel()

    blocked_words = [  # todo: make this into rules from database type of thing
        'Free Champion Rotation',
        'PlayRuneterra',
        'RiotForge',
        'TFT',
        'Teamfight Tactics',
        'Mortdog',
        'Champion & Skin Sale',
        'Champion &amp; Skin Sale',
        'prime gaming',
        'wildrift',
        'Wild Rift',
        'entwuhoo',  # tft dev account
        'RiotExis',  # legends of runeterra
        'RiotZephyreal',  # merch
        'davetron',  # LoR
        'infinitystudioc'  # merch
    ]

    whitelist_words = [
        # ' Notes',
    ]

    @commands.Cog.listener()
    async def on_message(self, msg: Message):
        try:
            if msg.channel.id == Cid.copylol_ff20:  # todo CHANGE
                if block_function(msg.content, self.blocked_words, self.whitelist_words):
                    return

                embeds = None  # TODO: if they start using actual bots then this wont work
                content = msg.content
                if "https://twitter.com" in msg.content:
                    await asyncio.sleep(2)
                    #  answer = await msg.channel.fetch_message(int(msg.id))
                    embeds = [await replace_tco_links(self.bot.session, item) for item in msg.embeds]
                    embeds = [move_link_to_title(embed) for embed in embeds]
                    content = ''

                files = [await item.to_file() for item in msg.attachments]
                msg = await self.bot.get_channel(Cid.lol_news).send(content=content, embeds=embeds, files=files)
                await msg.publish()
        except Exception as e:
            error_message = traceback.format_exc()
            await self.bot.get_channel(Cid.spam_me).send(
                f'{umntn(Uid.alu)} Something went wrong with #league-news copypaste\n'
                f'```python\n{error_message}```')

    @tasks.loop(minutes=15)
    async def patch_checker(self):

        url = "https://www.leagueoflegends.com/en-us/news/tags/patch-notes/"
        async with self.bot.session.get(url) as resp:
            soup = BeautifulSoup(await resp.read(), 'html.parser')

        new_patch_href = soup.find_all("li")[0].a.get('href')

        query = """ UPDATE botinfo 
                    SET lol_patch=$1
                    WHERE id=$2 
                    AND lol_patch IS DISTINCT FROM $1
                    RETURNING True
                """
        val = await self.bot.pool.fetchval(query, new_patch_href, Sid.alu)
        if not val:
            return

        patch_url = f'https://www.leagueoflegends.com{new_patch_href}'
        async with self.bot.session.get(patch_url) as resp:
            patch_soup = BeautifulSoup(await resp.read(), 'html.parser')
        metas = patch_soup.find_all('meta')

        def content_if_property(html_property: str):
            for meta in metas:
                if meta.attrs.get('property', None) == html_property:
                    return meta.attrs.get('content', None)
            return None
        em = Embed(
            colour=Clr.rspbrry,
            description=content_if_property("og:description"),
            title=content_if_property('og:title'),
            url=patch_url
        ).set_image(
            url=content_if_property('og:image')
        ).set_author(
            icon_url=Img.league,
            name='League of Legends'
        )
        msg = await self.bot.get_channel(Cid.lol_news).send(embed=em)
        await msg.publish()

    @patch_checker.before_loop
    async def before(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(CopypasteLeague(bot))