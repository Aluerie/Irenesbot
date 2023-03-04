"""
These cogs are about my private one-person server
and provide features for only me
"""

from .channel_watcher import DropsWatcher, EventPassWatcher
from .personal import PersonalCommands

PERSONAL_COGS = (
    DropsWatcher,
    EventPassWatcher,
    PersonalCommands,
)


async def setup(bot):
    for C in PERSONAL_COGS:
        await bot.add_cog(C(bot))