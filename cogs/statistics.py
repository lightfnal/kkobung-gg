import discord
from discord.ext import commands

from storage.sqlite_db import (
    get_player,
    get_total_match_count,
    get_player_rank
)

class Statistics(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(
        name="통계",
        description="플레이어의 종합 통계를 확인합니다."
    )
    @discord.app_commands.describe(
        유저="통계를 확인할 유저"
       )
    async def statistics(
        self,
        interaction: discord.Interaction,
        유저: discord.Member
    ):
        user_id = str(유저.id)

        profile = get_player(user_id)

        if profile is None:
            await interaction.response.send_message(
                "❌ 등록된 프로필이 없습니다.",
                ephemeral=True
            )
            return

        wins = profile["wins"]
        losses = profile["losses"]
        rating = profile["rating"]

        total = wins + losses

        if total == 0:
            win_rate = 0
        else:
            win_rate = round(
                wins / total * 100,
                1
            )

        rank, total_players = get_player_rank(
            user_id
        )

        rank_text = (
            f"{rank}위 / {total_players}명"
            if rank is not None
            else f"순위 없음 / {total_players}명"
        )

        embed = discord.Embed(
            title=f"📊 {유저.display_name} 종합 통계"
        )

        embed.add_field(
            name="⭐ 현재 레이팅",
            value=f"{rating}점",
            inline=True
        )

        embed.add_field(
            name="🥇 서버 순위",
            value=rank_text,
            inline=True
        )

        embed.add_field(
            name="🎮 총 경기",
            value=f"{get_total_match_count(user_id)}경기",
            inline=True
        )

        embed.add_field(
            name="🏆 승패",
            value=f"{wins}승 {losses}패",
            inline=True
        )

        embed.add_field(
            name="📈 승률",
            value=f"{win_rate}%",
            inline=True
        )

        embed.add_field(
            name="🏅 MVP",
            value=f"{profile['mvp']}회",
            inline=True
        )

        embed.add_field(
            name="🔥 최고 연승",
            value=f"{profile['best_win_streak']}연승",
            inline=True
        )

        embed.add_field(
            name="🔥 현재 연승",
            value=f"{profile['win_streak']}연승",
            inline=True
        )

        embed.add_field(
            name="❄️ 현재 연패",
            value=f"{profile['lose_streak']}연패",
            inline=True
        )

        await interaction.response.send_message(
            embed=embed
        )


async def setup(bot):
    await bot.add_cog(Statistics(bot))