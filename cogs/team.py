import discord
from discord.ext import commands

from storage.sqlite_db import (
    get_match_history,
    get_match_players,
    get_player_name
)


class Team(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(
        name="베스트팀",
        description="가장 많이 승리한 팀 조합을 확인합니다."
    )
    async def best_team(
        self,
        interaction: discord.Interaction
    ):
        team_records = {}

        matches = get_match_history(100000)

        for match in matches:
            players = get_match_players(
                match["id"]
            )

            for team_name in ["red", "blue"]:

                team = tuple(
                    sorted(
                        str(player["discord_id"])
                        for player in players
                        if player["team"] == team_name
                    )
                )

                if not team:
                    continue

                if team not in team_records:
                    team_records[team] = {
                        "wins": 0,
                        "games": 0
                    }

                team_records[team]["games"] += 1

                if match["winner"] == team_name:
                    team_records[team]["wins"] += 1

        if not team_records:
            await interaction.response.send_message(
                "❌ 팀 데이터가 없습니다.",
                ephemeral=True
            )
            return

        best_team_ids = max(
            team_records,
            key=lambda team: (
                team_records[team]["wins"],
                team_records[team]["games"]
            )
        )

        wins = team_records[best_team_ids]["wins"]
        games = team_records[best_team_ids]["games"]
        losses = games - wins

        win_rate = round(
            wins / games * 100,
            1
        )

        members = "\n".join(
            (
                f"<@{user_id}> · "
                f"{get_player_name(user_id)}"
            )
            for user_id in best_team_ids
        )

        embed = discord.Embed(
            title="🏆 베스트 팀"
        )

        embed.add_field(
            name="👥 팀원",
            value=members,
            inline=False
        )

        embed.add_field(
            name="📊 전적",
            value=(
                f"{games}전 {wins}승 {losses}패\n"
                f"승률 {win_rate}%"
            ),
            inline=False
        )

        await interaction.response.send_message(
            embed=embed
        )


async def setup(bot):
    await bot.add_cog(Team(bot))