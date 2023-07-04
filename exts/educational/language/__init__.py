from utils.const import Emote

from .._base import EducationalCog
from .translation import TranslateCog


class Languages(
    TranslateCog,
    EducationalCog,
    emote=Emote.bedNerdge,
):
    """Languages"""


async def setup(bot):
    await bot.add_cog(Languages(bot))
