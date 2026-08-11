import discord
from discord.ext import commands
from storage.sqlite_db import get_all_players


class Ranking(commands.Cog):


    @discord.app_commands.command(
        name="승수랭킹",
        description="승리가 많은 순으로 랭킹을 확인합니다."
    )
    async def win_ranking(
        self,
        interaction: discord.Interaction
    ):
        ranking = sorted(
            get_all_players(),
            key=lambda x: x["wins"],
            reverse=True
        )

        medals = ["🥇", "🥈", "🥉"]
        message = ""

        for i, profile in enumerate(ranking, start=1):

            if i <= 3:
                icon = medals[i - 1]
            else:
                icon = f"{i}."

            message += (
                f"{icon} **{profile['discord_nickname']}**\n"
                f"🏆 {profile['wins']}승\n\n"
            )

        await interaction.response.send_message(
            f"🏆 **승수 랭킹**\n\n{message}"
        )

    @discord.app_commands.command(
        name="패배랭킹",
        description="패배가 많은 순으로 랭킹을 확인합니다."
    )
    async def lose_ranking(
        self,
        interaction: discord.Interaction
    ):
        ranking = sorted(
            get_all_players(),
            key=lambda x: x["losses"],
            reverse=True
        )

        medals = ["🥇", "🥈", "🥉"]
        message = ""

        for i, profile in enumerate(ranking, start=1):

            if i <= 3:
                icon = medals[i - 1]
            else:
                icon = f"{i}."

            message += (
                f"{icon} **{profile['discord_nickname']}**\n"
                f"💀 {profile['losses']}패\n\n"
            )

        await interaction.response.send_message(
            f"💀 **패배 랭킹**\n\n{message}"
        )

    @discord.app_commands.command(
        name="승률랭킹",
        description="승률 랭킹을 확인합니다."
    )
    async def winrate_ranking(
        self,
        interaction: discord.Interaction
    ):
        if not self.profiles:
            await interaction.response.send_message(
                "등록된 프로필이 없습니다."
            )
            return

        ranking = sorted(
            get_all_players(),
            key=lambda x: (
                x["wins"] / (x["wins"] + x["losses"])
                if (x["wins"] + x["losses"]) > 0
                else 0
            ),
            reverse=True
        )

        medals = ["🥇", "🥈", "🥉"]
        message = ""

        for i, profile in enumerate(ranking, start=1):

            if i <= 3:
                icon = medals[i - 1]
            else:
                icon = f"{i}."

            total = profile["wins"] + profile["losses"]

            if total == 0:
                win_rate = 0
            else:
                win_rate = round(profile["wins"] / total * 100, 1)

            message += (
                f"{icon} **{profile['discord_nickname']}**\n"
                f"📈 승률 {win_rate}% "
                f"({profile['wins']}승 {profile['losses']}패)\n\n"
            )

        await interaction.response.send_message(
            f"📈 **승률 랭킹**\n\n{message}"
        )

    @discord.app_commands.command(
        name="연승랭킹",
        description="최고 연승 랭킹을 확인합니다."
    )
    async def streak_ranking(
        self,
        interaction: discord.Interaction
    ):

        ranking = sorted(
            get_all_players(),
            key=lambda x: x.get("best_win_streak", 0),
            reverse=True
        )

        medals = ["🥇", "🥈", "🥉"]
        message = ""

        for i, profile in enumerate(ranking, start=1):

            if i <= 3:
                icon = medals[i - 1]
            else:
                icon = f"{i}."

            message += (
                f"{icon} **{profile['discord_nickname']}**\n"
                f"🔥 최고 {profile.get('best_win_streak', 0)}연승\n\n"
            )

        await interaction.response.send_message(
            f"🔥 **최고 연승 랭킹**\n\n{message}"
        )

    @discord.app_commands.command(
        name="연패랭킹",
        description="현재 연패 랭킹을 확인합니다."
    )
    async def lose_streak_ranking(
        self,
        interaction: discord.Interaction
    ):
        ranking = get_all_players()

        if not ranking:
            await interaction.response.send_message(
                "등록된 프로필이 없습니다."
            )
            return

        ranking = sorted(
            ranking,
            key=lambda x: x.get("lose_streak", 0),
            reverse=True
        )

        medals = ["🥇", "🥈", "🥉"]
        message = ""

        for i, profile in enumerate(ranking, start=1):

            if i <= 3:
                icon = medals[i - 1]
            else:
                icon = f"{i}."

            message += (
                f"{icon} **{profile['discord_nickname']}**\n"
                f"❄️ 현재 {profile.get('lose_streak', 0)}연패\n\n"
            )

        await interaction.response.send_message(
            f"❄️ **현재 연패 랭킹**\n\n{message}"
        )

    @discord.app_commands.command(
        name="mvp랭킹",
        description="MVP 횟수 랭킹을 확인합니다."
    )
    async def mvp_ranking(
        self,
        interaction: discord.Interaction
    ):
        ranking = get_all_players()

        if not ranking:
            await interaction.response.send_message(
                "등록된 프로필이 없습니다."
            )
            return

        ranking = sorted(
            ranking,
            key=lambda x: x.get("mvp", 0),
            reverse=True
        )

        medals = ["🥇", "🥈", "🥉"]
        message = ""

        for i, profile in enumerate(ranking, start=1):

            if i <= 3:
                icon = medals[i - 1]
            else:
                icon = f"{i}."

            message += (
                f"{icon} **{profile['discord_nickname']}**\n"
                f"🏆 MVP {profile.get('mvp', 0)}회\n\n"
            )

        await interaction.response.send_message(
            f"🏆 **MVP 랭킹**\n\n{message}"
        )

    @discord.app_commands.command(
        name="최다출전",
        description="가장 많은 경기를 플레이한 랭킹을 확인합니다."
    )
    async def most_games(
        self,
        interaction: discord.Interaction
    ):
        ranking = get_all_players()

        if not ranking:
            await interaction.response.send_message(
                "등록된 프로필이 없습니다."
            )
            return

        ranking = sorted(
            ranking,
            key=lambda x: x["wins"] + x["losses"],
            reverse=True
        )

        medals = ["🥇", "🥈", "🥉"]
        message = ""

        for i, profile in enumerate(ranking, start=1):

            if i <= 3:
                icon = medals[i - 1]
            else:
                icon = f"{i}."

            total = (
                profile["wins"]
                + profile["losses"]
            )

            message += (
                f"{icon} **{profile['discord_nickname']}**\n"
                f"🎮 {total}경기 "
                f"({profile['wins']}승 {profile['losses']}패)\n\n"
            )

        await interaction.response.send_message(
            f"🎮 **최다 출전 랭킹**\n\n{message}"
        )

    @discord.app_commands.command(
        name="전적순위",
        description="레이팅과 전적을 함께 확인합니다."
    )
    async def ranking_detail(
        self,
        interaction: discord.Interaction
    ):
        ranking = get_all_players()

        if not ranking:
            await interaction.response.send_message(
                "등록된 프로필이 없습니다."
            )
            return

        ranking = sorted(
            ranking,
            key=lambda x: x["rating"],
            reverse=True
        )

        medals = ["🥇", "🥈", "🥉"]
        message = ""

        for i, profile in enumerate(ranking, start=1):

            if i <= 3:
                icon = medals[i - 1]
            else:
                icon = f"{i}."

            message += (
                f"{icon} **{profile['discord_nickname']}**\n"
                f"⭐ {profile['rating']}점 | "
                f"🏆 {profile['wins']}승 {profile['losses']}패\n\n"
            )

        await interaction.response.send_message(
            f"📊 **전적 순위**\n\n{message}"
        )

    @discord.app_commands.command(
        name="랭킹",
        description="내전 레이팅 랭킹을 확인합니다."
    )
    async def ranking(
        self,
        interaction: discord.Interaction
    ):

        ranking = get_all_players()

        if not ranking:
            await interaction.response.send_message(
                "등록된 프로필이 없습니다."
            )
            return

        ranking = sorted(
            ranking,
            key=lambda x: x["rating"],
            reverse=True
        )

        message = ""

        medals = ["🥇", "🥈", "🥉"]

        for i, profile in enumerate(ranking, start=1):

            rating_tier = self.get_rating_tier(
                profile["rating"]
            )

            if i <= 3:
                icon = medals[i - 1]
            else:
                icon = f"{i}."

            message += (
                f"{icon} **{profile['discord_nickname']}**\n"
                f"⭐ {profile['rating']}점\n"
                f"{rating_tier}\n\n"
            )

        await interaction.response.send_message(
            f"🏆 **내전 랭킹**\n\n{message}"
        )

    def get_rating_tier(self, rating):

        if rating >= 2000:
            return "🔥 Challenger"

        elif rating >= 1800:
            return "👑 Master"

        elif rating >= 1600:
            return "💎 Diamond"

        elif rating >= 1400:
            return "🥇 Platinum"

        elif rating >= 1200:
            return "🥈 Gold"

        elif rating >= 1000:
            return "🥉 Silver"

        else:
            return "🔰 Bronze"

    def __init__(self, bot):
        self.bot = bot


async def setup(bot):
    await bot.add_cog(Ranking(bot))