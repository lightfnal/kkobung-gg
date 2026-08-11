from discord.ext import commands


def get_join_cog(
    bot: commands.Bot
):
    return bot.get_cog("Join")