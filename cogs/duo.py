import discord
from discord.ext import commands

from storage.sqlite_db import (
    get_match_history,
    get_match_players,
    get_player_name
)


class Duo(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(
        name="듀오랭킹",
        description="같은 팀으로 가장 많이 승리한 듀오를 확인합니다."
    )
    async def duo_ranking(
        self,
        interaction: discord.Interaction
    ):
        duo_records = {}

        matches = get_match_history(100000)

        for match in matches:
            players = get_match_players(
                match["id"]
            )

            winner_team = match["winner"]

            winner_players = [
                str(player["discord_id"])
                for player in players
                if player["team"] == winner_team
            ]

            for i in range(len(winner_players)):
                for j in range(i + 1, len(winner_players)):

                    duo = tuple(
                        sorted([
                            winner_players[i],
                            winner_players[j]
                        ])
                    )

                    duo_records[duo] = (
                        duo_records.get(duo, 0) + 1
                    )

        if not duo_records:
            await interaction.response.send_message(
                "❌ 듀오 승리 기록이 없습니다."
            )
            return

        best_duo = max(
            duo_records,
            key=duo_records.get
        )

        win_count = duo_records[best_duo]

        player1_id = best_duo[0]
        player2_id = best_duo[1]

        player1_name = get_player_name(player1_id)
        player2_name = get_player_name(player2_id)

        embed = discord.Embed(
            title="🤝 듀오 랭킹"
        )

        embed.add_field(
            name="🥇 최고의 듀오",
            value=(
                f"<@{player1_id}> · {player1_name}\n"
                f"<@{player2_id}> · {player2_name}"
            ),
            inline=False
        )

        embed.add_field(
            name="🏆 함께 승리",
            value=f"{win_count}승",
            inline=False
        )

        await interaction.response.send_message(
            embed=embed
        )

    @discord.app_commands.command(
        name="무패듀오",
        description="한 번도 패배하지 않은 듀오를 확인합니다."
    )
    async def undefeated_duo(
        self,
        interaction: discord.Interaction
    ):
        duo_records = {}

        matches = get_match_history(100000)

        for match in matches:
            players = get_match_players(
                match["id"]
            )

            for team_name in ["red", "blue"]:

                team_players = [
                    str(player["discord_id"])
                    for player in players
                    if player["team"] == team_name
                ]

                won = match["winner"] == team_name

                for i in range(len(team_players)):
                    for j in range(i + 1, len(team_players)):

                        duo = tuple(
                            sorted([
                                team_players[i],
                                team_players[j]
                            ])
                        )

                        if duo not in duo_records:
                            duo_records[duo] = {
                                "wins": 0,
                                "games": 0
                            }

                        duo_records[duo]["games"] += 1

                        if won:
                            duo_records[duo]["wins"] += 1

        candidates = {
            duo: record
            for duo, record in duo_records.items()
            if (
                record["games"] >= 3
                and record["wins"] == record["games"]
            )
        }

        if not candidates:
            await interaction.response.send_message(
                "❌ 3경기 이상 함께 플레이한 무패 듀오가 없습니다."
            )
            return

        best_duo = max(
            candidates,
            key=lambda duo: candidates[duo]["games"]
        )

        games = candidates[best_duo]["games"]

        player1_id = best_duo[0]
        player2_id = best_duo[1]

        player1_name = get_player_name(player1_id)
        player2_name = get_player_name(player2_id)

        embed = discord.Embed(
            title="🛡️ 무패 듀오"
        )

        embed.add_field(
            name="🏅 무패 듀오",
            value=(
                f"<@{player1_id}> · {player1_name}\n"
                f"<@{player2_id}> · {player2_name}"
            ),
            inline=False
        )

        embed.add_field(
            name="🔥 기록",
            value=f"{games}전 {games}승 (100%)",
            inline=False
        )

        await interaction.response.send_message(
            embed=embed
        )

    @discord.app_commands.command(
        name="듀오승률",
        description="승률이 가장 높은 듀오를 확인합니다."
    )
    async def duo_winrate(
        self,
        interaction: discord.Interaction
    ):
        duo_records = {}

        matches = get_match_history(100000)

        for match in matches:

            players = get_match_players(
                match["id"]
            )

            for team_name in ["red", "blue"]:

                team_players = [
                    str(player["discord_id"])
                    for player in players
                    if player["team"] == team_name
                ]

                won = (
                    match["winner"] == team_name
                )

                for i in range(len(team_players)):
                    for j in range(i + 1, len(team_players)):

                        duo = tuple(
                            sorted([
                                team_players[i],
                                team_players[j]
                            ])
                        )

                        if duo not in duo_records:
                            duo_records[duo] = {
                                "wins": 0,
                                "games": 0
                            }

                        duo_records[duo]["games"] += 1

                        if won:
                            duo_records[duo]["wins"] += 1

        if not duo_records:
            await interaction.response.send_message(
                "❌ 듀오 경기 기록이 없습니다."
            )
            return

        best_duo = max(
            duo_records,
            key=lambda duo: (
                duo_records[duo]["wins"]
                / duo_records[duo]["games"],
                duo_records[duo]["games"]
            )
        )

        wins = duo_records[best_duo]["wins"]
        games = duo_records[best_duo]["games"]

        win_rate = round(
            wins / games * 100,
            1
        )

        player1_id = best_duo[0]
        player2_id = best_duo[1]

        player1_name = get_player_name(player1_id)
        player2_name = get_player_name(player2_id)

        embed = discord.Embed(
            title="🤝 듀오 승률 랭킹"
        )

        embed.add_field(
            name="🥇 최고의 듀오",
            value=(
                f"<@{player1_id}> · {player1_name}\n"
                f"<@{player2_id}> · {player2_name}"
            ),
            inline=False
        )

        embed.add_field(
            name="📈 승률",
            value=f"{win_rate}% ({wins}승 / {games}경기)",
            inline=False
        )

        await interaction.response.send_message(
            embed=embed
        )


async def setup(bot):
    await bot.add_cog(Duo(bot))