import discord
from discord.ext import commands

from storage.sqlite_db import (
    get_match_history,
    get_match_players,
    get_player_name
)


class Stats(commands.Cog):

    def __init__(self, bot):
        self.bot = bot


async def setup(bot):
    await bot.add_cog(Stats(bot))