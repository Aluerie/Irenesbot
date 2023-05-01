from __future__ import annotations

import re
from typing import TYPE_CHECKING

import discord
import feedparser
from bs4 import BeautifulSoup
from discord.ext import tasks

from utils import AluCog, Clr, Sid
from utils.lol.const import LOL_LOGO

if TYPE_CHECKING:
    pass


class Insider(AluCog):
    def cog_load(self) -> None:
        self.insider_checker.start()

    def cog_unload(self) -> None:
        self.insider_checker.cancel()

    @tasks.loop(minutes=10)
    async def insider_checker(self):
        url = "https://blogs.windows.com/windows-insider/feed/"
        rss = feedparser.parse(url)

        for entry in rss.entries:
            if re.findall(r'23[0-9]{3}', entry.title):  # dev entry check
                p = entry
                break
        else:
            return

        query = """ UPDATE botinfo 
                        SET insider_version=$1
                        WHERE id=$2 
                        AND insider_version IS DISTINCT FROM $1
                        RETURNING True
                    """
        val = await self.bot.pool.fetchval(query, p.title, Sid.community)
        if not val:
            return

        e = discord.Embed(title=p.title, url=p.link, colour=0x0179D4)
        e.set_image(
            url='https://blogs.windows.com/wp-content/themes/microsoft-stories-theme/img/theme/windows-placeholder.jpg'
        )
        msg = await self.hideout.repost.send(embed=e)
        # await msg.publish()

    @insider_checker.before_loop
    async def before(self):
        await self.bot.wait_until_ready()


class LoLCom(AluCog):
    async def cog_load(self) -> None:
        self.patch_checker.start()

    async def cog_unload(self) -> None:
        self.patch_checker.cancel()

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
        val = await self.bot.pool.fetchval(query, new_patch_href, Sid.community)
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

        # maybe use ('a' ,{'class': 'skins cboxElement'})
        img_url = patch_soup.find('h2', id='patch-patch-highlights').find_next('a').get('href')  # type: ignore # TODO:FIX
        e = discord.Embed(title=content_if_property('og:title'), url=patch_url, colour=Clr.rspbrry())
        e.description = content_if_property("og:description")
        e.set_image(url=img_url)
        e.set_thumbnail(url=content_if_property('og:image'))
        e.set_author(name='League of Legends', icon_url=LOL_LOGO)
        await self.bot.hideout.repost.send(embed=e)

    @patch_checker.before_loop
    async def before(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(Insider(bot))
    await bot.add_cog(LoLCom(bot))
