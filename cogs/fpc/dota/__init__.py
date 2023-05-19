from utils import const

from .notifs import DotaNotifs
from .postmatch import DotaPostMatchEdit
from .settings import DotaNotifsSettings
from .twitch_check import DotaTwitchAccountCheck


class Dota2FPC(DotaNotifs, DotaPostMatchEdit, DotaNotifsSettings, DotaTwitchAccountCheck, emote=const.Emote.DankLove):
    """
    Dota 2 - Favourite player+character combo notifications.
    """

    pass


async def setup(bot):
    await bot.add_cog(Dota2FPC(bot))
