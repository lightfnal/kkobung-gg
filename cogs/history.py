import discord
from discord.ext import commands

from storage.sqlite_db import (
    get_match_history,
    get_match,
    get_match_players
)


class History(commands.Cog):

    def __init__(self, bot):
        self.bot = bot


    @discord.app_commands.command(
        name="내전기록",
        description="최근 내전 기록을 확인합니다."
    )
    async def match_history_command(
        self,
        interaction: discord.Interaction
    ):
        history = get_match_history(10)

        if not history:
            await interaction.response.send_message(
                "❌ 저장된 경기 기록이 없습니다.",
                ephemeral=True
            )
            return

        message = ""

        for match in history:
            winner = (
                "🔴 레드팀"
                if match["winner"] == "red"
                else "🔵 블루팀"
            )

            message += (
                f"**#{match['id']}** · {winner} 승리\n"
                f"🕒 {match['match_date']}\n\n"
            )

        embed = discord.Embed(
            title="📜 최근 내전 기록",
            description=message
        )

        await interaction.response.send_message(
            embed=embed
        )

    @discord.app_commands.command(
        name="내전기록상세",
        description="특정 경기의 상세 정보를 확인합니다."
    )
    @discord.app_commands.describe(
        경기번호="확인할 경기 번호"
    )
    async def match_detail(
        self,
        interaction: discord.Interaction,
        경기번호: int
    ):
        match = get_match(경기번호)

        if match is None:
            await interaction.response.send_message(
                "❌ 해당 경기를 찾을 수 없습니다.",
                ephemeral=True
            )
            return

        players = get_match_players(경기번호)

        red_players = [
            player
            for player in players
            if player["team"] == "red"
        ]

        blue_players = [
            player
            for player in players
            if player["team"] == "blue"
        ]

        red = "\n\n".join(
            (
                f"**{player['position']}** - "
                f"<@{player['discord_id']}>\n"
                f"⭐ {player['rating_before']} → "
                f"{player['rating_after']} "
                f"({player['rating_change']:+})"
            )
            for player in red_players
        )

        blue = "\n\n".join(
            (
                f"**{player['position']}** - "
                f"<@{player['discord_id']}>\n"
                f"⭐ {player['rating_before']} → "
                f"{player['rating_after']} "
                f"({player['rating_change']:+})"
            )
            for player in blue_players
        )

        winner = (
            "🔴 레드팀"
            if match["winner"] == "red"
            else "🔵 블루팀"
        )

        mvp_id = match.get("mvp_discord_id")

        mvp = (
            f"<@{mvp_id}>"
            if mvp_id
            else "없음"
        )

        embed = discord.Embed(
            title=f"📜 {경기번호}번째 경기"
        )

        embed.add_field(
            name="🕒 경기 시간",
            value=match["match_date"],
            inline=False
        )

        embed.add_field(
            name="🏆 승리팀",
            value=winner,
            inline=False
        )

        embed.add_field(
            name="🏅 MVP",
            value=mvp,
            inline=False
        )

        embed.add_field(
            name="🔴 레드팀",
            value=red or "기록 없음",
            inline=True
        )

        embed.add_field(
            name="🔵 블루팀",
            value=blue or "기록 없음",
            inline=True
        )

        await interaction.response.send_message(
            embed=embed
        )

    @discord.app_commands.command(
        name="최근경기",
        description="최근 경기 결과를 확인합니다."
    )
    async def recent_match(
        self,
        interaction: discord.Interaction
    ):
        history = get_match_history(1)

        if not history:
            await interaction.response.send_message(
                "❌ 최근 경기 기록이 없습니다.",
                ephemeral=True
            )
            return

        match = history[0]
        match_id = match["id"]

        players = get_match_players(match_id)

        red_players = [
            player
            for player in players
            if player["team"] == "red"
        ]

        blue_players = [
            player
            for player in players
            if player["team"] == "blue"
        ]

        red = "\n".join(
            (
                f"**{player['position']}** - "
                f"<@{player['discord_id']}>"
            )
            for player in red_players
        )

        blue = "\n".join(
            (
                f"**{player['position']}** - "
                f"<@{player['discord_id']}>"
            )
            for player in blue_players
        )

        winner = (
            "🔴 레드팀"
            if match["winner"] == "red"
            else "🔵 블루팀"
        )

        mvp_id = match["mvp_discord_id"]

        mvp = (
            f"<@{mvp_id}>"
            if mvp_id
            else "없음"
        )

        embed = discord.Embed(
            title="📜 최근 경기"
        )

        embed.add_field(
            name="🕒 경기 시간",
            value=match["match_date"],
            inline=False
        )

        embed.add_field(
            name="🏆 승리팀",
            value=winner,
            inline=False
        )

        embed.add_field(
            name="🏅 MVP",
            value=mvp,
            inline=False
        )

        embed.add_field(
            name="🔴 레드팀",
            value=red or "기록 없음",
            inline=True
        )

        embed.add_field(
            name="🔵 블루팀",
            value=blue or "기록 없음",
            inline=True
        )

        await interaction.response.send_message(
            embed=embed
        )


async def setup(bot):
    await bot.add_cog(History(bot))