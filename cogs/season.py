import discord
from discord.ext import commands
from datetime import datetime

from utils.rating import get_rating_tier

from storage.sqlite_db import (
    create_season,
    get_active_season,
    get_all_seasons,
    end_active_season,
    get_season_match_count,
    get_season_player_count,
    get_season_player_stats,
    get_all_season_player_stats,
    get_player_name,
    save_season_result,
    get_all_season_results
)

from utils.permissions import (
    is_admin,
    send_admin_only_message
)

class Season(commands.Cog):

    def __init__(self, bot):
        self.bot = bot



    @discord.app_commands.command(
        name="역대우승",
        description="역대 시즌 우승자를 확인합니다."
    )
    async def all_time_champions(
        self,
        interaction: discord.Interaction
    ):
        results = get_all_season_results()

        if not results:
            await interaction.response.send_message(
                "❌ 저장된 시즌 우승 기록이 없습니다.",
                ephemeral=True
            )
            return

        seasons = {
            season["id"]: season
            for season in get_all_seasons()
        }

        message = ""

        # 오래된 시즌부터 표시
        for result in reversed(results):
            season_id = result["season_id"]

            season = seasons.get(season_id)

            if season is None:
                season_name = f"시즌 {season_id}"
            else:
                season_name = season["season_name"]

            champion_id = result["champion_id"]

            champion_name = (
                get_player_name(champion_id)
                if champion_id
                else "기록 없음"
            )

            message += (
                f"🏆 **{season_name}**\n"
                f"👑 {champion_name}\n"
            )

            if champion_id:
                message += f"<@{champion_id}>\n"

            message += "\n"

        embed = discord.Embed(
            title="🏆 역대 시즌 우승자",
            description=message
        )

        await interaction.response.send_message(
            embed=embed
        )

    @discord.app_commands.command(
        name="시즌결과",
        description="종료된 시즌의 결과를 확인합니다."
    )
    async def season_result(
        self,
        interaction: discord.Interaction,
        시즌번호: int
    ):
        seasons = get_all_seasons()
    
        season = next(
            (
                s
                for s in seasons
                if s["id"] == 시즌번호
            ),
            None
        )
    
        if season is None:
            await interaction.response.send_message(
                "❌ 해당 시즌을 찾을 수 없습니다.",
                   ephemeral=True
            )
            return
    
        ranking = get_all_season_player_stats(
            시즌번호
        )
    
        ranking = [
            player
            for player in ranking
            if player["wins"] + player["losses"] > 0
        ]
    
        if not ranking:
            await interaction.response.send_message(
                "❌ 해당 시즌의 기록이 없습니다.",
                ephemeral=True
            )
            return
        ranking = sorted(
            ranking,
            key=lambda player: (
                player["rating"],
                player["wins"],
                    player["losses"]
            ),
            reverse=True
        )
    
        champion = ranking[0]
    
        runner_up = (
            ranking[1]
            if len(ranking) >= 2
            else None
        )
    
        third_place = (
            ranking[2]
            if len(ranking) >= 3
            else None
        )
    
        season_mvp = max(
            ranking,
            key=lambda player: (
                player.get("mvp", 0),
                player["rating"]
            )
        )
    
        best_streak = max(
            ranking,
            key=lambda player: (
                player.get("best_win_streak", 0),
                player["wins"],
                player["rating"]
            )
        )
    
        best_winrate = max(
            ranking,
            key=lambda player: (
                (
                    player["wins"]
                    / (
                        player["wins"]
                        + player["losses"]
                    )
                ),
                player["wins"],
                player["rating"]
            )
        )
    
        most_games = max(
            ranking,
            key=lambda player: (
                player["wins"]
                + player["losses"],
                player["wins"],
                player["rating"]
            )
        )
    
        match_count = get_season_match_count(
            시즌번호
        )
    
        player_count = get_season_player_count(
            시즌번호
        )
    
        def player_name(player):
            return (
                player.get("discord_nickname")
                or get_player_name(
                    player["discord_id"]
                )
            )
        total_games = (
            best_winrate["wins"]
            + best_winrate["losses"]
        )
    
        win_rate = round(
            best_winrate["wins"]
            / total_games
            * 100,
            1
        )
    
        embed = discord.Embed(
            title=f"🏆 {season['season_name']} 시즌 결과",
            description="시즌 최종 결과"
        )
    
        embed.add_field(
            name="👑 시즌 챔피언",
            value=(
                f"**{player_name(champion)}**\n"
                f"⭐ {champion['rating']}점\n"
                f"🏆 {champion['wins']}승 {champion['losses']}패"
            ),
            inline=False
        )
    
        if runner_up:
            embed.add_field(
                name="🥈 시즌 2위",
                value=(
                    f"**{player_name(runner_up)}**\n"
                    f"⭐ {runner_up['rating']}점"
                ),
                inline=True
            )
    
        if third_place:
            embed.add_field(
                name="🥉 시즌 3위",
                value=(
                    f"**{player_name(third_place)}**\n"
                    f"⭐ {third_place['rating']}점"
                ),
                inline=True
            )
    
        embed.add_field(
            name="🏅 시즌 MVP",
            value=(
                f"{player_name(season_mvp)}\n"
                f"{season_mvp['mvp']}회"
            ),
            inline=False
        )
    
        embed.add_field(
            name="🔥 최고 연승",
            value=(
                f"{player_name(best_streak)}\n"
                f"{best_streak['best_win_streak']}연승"
            ),
            inline=True
        )
    
        embed.add_field(
            name="📈 최고 승률",
            value=(
                f"{player_name(best_winrate)}\n"
                f"{win_rate}%"
            ),
            inline=True
        )
    
        embed.add_field(
            name="🎮 최다 출전",
            value=(
                f"{player_name(most_games)}\n"
                f"{most_games['wins'] + most_games['losses']}경기"
            ),
            inline=True
        )
    
        embed.add_field(
            name="📊 시즌 통계",
            value=(
                f"총 경기 : {match_count}경기\n"
                f"참가자 : {player_count}명"
            ),
            inline=False
        )
    
        embed.add_field(
            name="🗓️ 시즌 기간",
            value=(
                f"시작 : {season['started_at']}\n"
                f"종료 : {season['ended_at'] or '진행중'}"
            ),
            inline=False
        )
    
        await interaction.response.send_message(
            embed=embed
        )

    @discord.app_commands.command(
        name="시즌종료",
        description="현재 시즌을 종료하고 최종 결과를 발표합니다."
    )
    async def end_season(
        self,
        interaction: discord.Interaction
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        active = get_active_season()

        if active is None:
            await interaction.response.send_message(
                "❌ 현재 진행 중인 시즌이 없습니다.",
                ephemeral=True
            )
            return

        season_id = active["id"]

        ranking = get_all_season_player_stats(
            season_id
        )

        ranking = [
            player
            for player in ranking
            if player["wins"] + player["losses"] > 0
        ]

        match_count = get_season_match_count(
            season_id
        )

        player_count = get_season_player_count(
            season_id
        )

        ended_at = datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        )

        if not ranking:
            ended = end_active_season(
                ended_at
            )

            if not ended:
                await interaction.response.send_message(
                    "❌ 시즌 종료 처리에 실패했습니다.",
                    ephemeral=True
                )
                return

            embed = discord.Embed(
                title=f"🏁 {active['season_name']} 시즌 종료",
                description=(
                    "시즌이 종료되었습니다.\n"
                    "이번 시즌에는 등록된 경기 기록이 없습니다."
                )
            )

            embed.add_field(
                name="🗓️ 시작일",
                value=active["started_at"],
                inline=True
            )

            embed.add_field(
                name="🏁 종료일",
                value=ended_at,
                inline=True
            )

            await interaction.response.send_message(
                embed=embed
            )
            return

        rating_ranking = sorted(
            ranking,
            key=lambda player: (
                player["rating"],
                player["wins"],
                -player["losses"]
            ),
            reverse=True
        )

        champion = rating_ranking[0]

        runner_up = (
            rating_ranking[1]
            if len(rating_ranking) >= 2
            else None
        )

        third_place = (
            rating_ranking[2]
            if len(rating_ranking) >= 3
            else None
        )

        season_mvp = max(
            ranking,
            key=lambda player: (
                player.get("mvp", 0),
                player["rating"],
                player["wins"]
            )
        )

        best_streak_player = max(
            ranking,
            key=lambda player: (
                player.get("best_win_streak", 0),
                player["wins"],
                player["rating"]
            )
        )

        best_winrate_player = max(
            ranking,
            key=lambda player: (
                player["wins"]
                / (
                    player["wins"]
                    + player["losses"]
                ),
                player["wins"],
                player["rating"]
            )
        )

        most_games_player = max(
            ranking,
            key=lambda player: (
                player["wins"] + player["losses"],
                player["wins"],
                player["rating"]
            )
        )

        best_winrate_total = (
            best_winrate_player["wins"]
            + best_winrate_player["losses"]
        )

        best_winrate_percent = round(
            best_winrate_player["wins"]
            / best_winrate_total
            * 100,
            1
        )

        most_games_total = (
            most_games_player["wins"]
            + most_games_player["losses"]
        )

        def player_name(player):
            return (
                player.get("discord_nickname")
                or get_player_name(
                    str(player["discord_id"])
                )
            )

        save_season_result(
            season_id=season_id,
            champion_id=str(
                champion["discord_id"]
            ),
            runner_up_id=(
                str(runner_up["discord_id"])
                if runner_up is not None
                else None
            ),
            third_id=(
                str(third_place["discord_id"])
                if third_place is not None
                else None
            ),
            mvp_id=str(
                season_mvp["discord_id"]
            ),
            best_win_streak_id=str(
                best_streak_player["discord_id"]
            ),
            best_win_streak=best_streak_player.get(
                "best_win_streak",
                0
            ),
            best_winrate_id=str(
                best_winrate_player["discord_id"]
            ),
            best_winrate=best_winrate_percent,
            most_games_id=str(
                most_games_player["discord_id"]
            ),
            most_games=most_games_total
        )

        ended = end_active_season(
            ended_at
        )

        if not ended:
            await interaction.response.send_message(
                "❌ 시즌 종료 처리에 실패했습니다.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"🏆 {active['season_name']} 시즌 종료",
            description="시즌 최종 결과가 확정되었습니다."
        )

        embed.add_field(
            name="👑 시즌 챔피언",
            value=(
                f"**{player_name(champion)}**\n"
                f"⭐ {champion['rating']}점\n"
                f"🏆 {champion['wins']}승 "
                f"{champion['losses']}패"
            ),
            inline=False
        )

        if runner_up is not None:
            embed.add_field(
                name="🥈 시즌 2위",
                value=(
                    f"**{player_name(runner_up)}**\n"
                    f"⭐ {runner_up['rating']}점\n"
                    f"🏆 {runner_up['wins']}승 "
                    f"{runner_up['losses']}패"
                ),
                inline=True
            )

        if third_place is not None:
            embed.add_field(
                name="🥉 시즌 3위",
                value=(
                    f"**{player_name(third_place)}**\n"
                    f"⭐ {third_place['rating']}점\n"
                    f"🏆 {third_place['wins']}승 "
                    f"{third_place['losses']}패"
                ),
                inline=True
            )

        embed.add_field(
            name="🏅 시즌 MVP",
            value=(
                f"**{player_name(season_mvp)}**\n"
                f"MVP {season_mvp.get('mvp', 0)}회"
            ),
            inline=False
        )

        embed.add_field(
            name="🔥 최고 연승",
            value=(
                f"**{player_name(best_streak_player)}**\n"
                f"{best_streak_player.get('best_win_streak', 0)}연승"
            ),
            inline=True
        )

        embed.add_field(
            name="📈 최고 승률",
            value=(
                f"**{player_name(best_winrate_player)}**\n"
                f"{best_winrate_percent}%\n"
                f"{best_winrate_player['wins']}승 "
                f"{best_winrate_player['losses']}패"
            ),
            inline=True
        )

        embed.add_field(
            name="🎮 최다 출전",
            value=(
                f"**{player_name(most_games_player)}**\n"
                f"{most_games_total}경기"
            ),
            inline=True
        )

        embed.add_field(
            name="📊 시즌 규모",
            value=(
                f"총 경기: {match_count}경기\n"
                f"참가자: {player_count}명"
            ),
            inline=True
        )

        embed.add_field(
            name="🗓️ 시즌 기간",
            value=(
                f"시작: {active['started_at']}\n"
                f"종료: {ended_at}"
            ),
            inline=False
        )

        await interaction.response.send_message(
            embed=embed
        )

    @discord.app_commands.command(
        name="시즌레이팅변동",
        description="현재 시즌 레이팅 변동 랭킹을 확인합니다."
    )
    async def season_rating_change(
        self,
        interaction: discord.Interaction
    ):
        active = get_active_season()

        if active is None:
            await interaction.response.send_message(
                "❌ 현재 진행 중인 시즌이 없습니다.",
                ephemeral=True
            )
            return

        ranking = get_all_season_player_stats(
            active["id"]
        )

        ranking = [
            player
            for player in ranking
            if player["wins"] + player["losses"] > 0
        ]

        if not ranking:
            await interaction.response.send_message(
                "❌ 현재 시즌 경기 기록이 없습니다.",
                ephemeral=True
            )
            return

        ranking = sorted(
            ranking,
            key=lambda player: (
                player["rating"] - 1000,
                player["wins"] + player["losses"],
                player["wins"]
            ),
            reverse=True
        )

        medals = ["🥇", "🥈", "🥉"]
        message = ""

        for index, player in enumerate(
            ranking,
            start=1
        ):
            if index <= 3:
                icon = medals[index - 1]
            else:
                icon = f"{index}."

            user_id = str(player["discord_id"])

            player_name = (
                player.get("discord_nickname")
                or get_player_name(user_id)
            )

            rating = player["rating"]
            difference = rating - 1000
            total = player["wins"] + player["losses"]

            if difference > 0:
                change_text = f"📈 +{difference}점"
            elif difference < 0:
                change_text = f"📉 {difference}점"
            else:
                change_text = "➖ 0점"

            message += (
                f"{icon} **{player_name}**\n"
                f"{change_text}\n"
                f"⭐ 현재 {rating}점 | "
                f"🎮 {total}경기\n\n"
            )

        await interaction.response.send_message(
            f"📊 **{active['season_name']} 시즌 레이팅 변동 랭킹**\n\n"
            f"{message}"
        )

    @discord.app_commands.command(
        name="시즌패배랭킹",
        description="현재 시즌 패배 횟수 랭킹을 확인합니다."
    )
    async def season_loss_ranking(
        self,
        interaction: discord.Interaction
    ):
        active = get_active_season()

        if active is None:
            await interaction.response.send_message(
                "❌ 현재 진행 중인 시즌이 없습니다.",
                ephemeral=True
            )
            return

        ranking = get_all_season_player_stats(
            active["id"]
        )

        ranking = [
            player
            for player in ranking
            if player["wins"] + player["losses"] > 0
        ]

        if not ranking:
            await interaction.response.send_message(
                "❌ 현재 시즌 경기 기록이 없습니다.",
                ephemeral=True
            )
            return

        ranking = sorted(
            ranking,
            key=lambda player: (
                player["losses"],
                player["wins"] + player["losses"],
                -player["rating"]
            ),
            reverse=True
        )

        medals = ["🥇", "🥈", "🥉"]
        message = ""

        for index, player in enumerate(
            ranking,
            start=1
        ):
            if index <= 3:
                icon = medals[index - 1]
            else:
                icon = f"{index}."

            user_id = str(
                player["discord_id"]
            )

            player_name = (
                player.get("discord_nickname")
                or get_player_name(user_id)
            )

            total = (
                player["wins"]
                + player["losses"]
            )

            message += (
                f"{icon} **{player_name}**\n"
                f"💀 {player['losses']}패\n"
                f"🎮 {total}경기 | "
                f"🏆 {player['wins']}승 | "
                f"⭐ {player['rating']}점\n\n"
            )

        await interaction.response.send_message(
            f"💀 **{active['season_name']} 시즌 패배 랭킹**\n\n"
            f"{message}"
        )

    @discord.app_commands.command(
        name="시즌연패랭킹",
        description="현재 시즌 연패 랭킹을 확인합니다."
    )
    async def season_lose_streak_ranking(
        self,
        interaction: discord.Interaction
    ):
        active = get_active_season()

        if active is None:
            await interaction.response.send_message(
                "❌ 현재 진행 중인 시즌이 없습니다.",
                ephemeral=True
            )
            return

        ranking = get_all_season_player_stats(
            active["id"]
        )

        ranking = [
            player
            for player in ranking
            if player["wins"] + player["losses"] > 0
        ]

        if not ranking:
            await interaction.response.send_message(
                "❌ 현재 시즌 경기 기록이 없습니다.",
                ephemeral=True
            )
            return

        ranking = sorted(
            ranking,
            key=lambda player: (
                player.get("lose_streak", 0),
                player.get("losses", 0),
                -player.get("rating", 1000)
            ),
            reverse=True
        )

        medals = ["🥇", "🥈", "🥉"]
        message = ""

        for index, player in enumerate(
            ranking,
            start=1
        ):
            if index <= 3:
                icon = medals[index - 1]
            else:
                icon = f"{index}."

            user_id = str(
                player["discord_id"]
            )

            player_name = (
                player.get("discord_nickname")
                or get_player_name(user_id)
            )

            message += (
                f"{icon} **{player_name}**\n"
                f"❄️ 현재 "
                f"{player.get('lose_streak', 0)}연패\n"
                f"💀 {player['losses']}패 | "
                f"⭐ {player['rating']}점\n\n"
            )

        await interaction.response.send_message(
            f"❄️ **{active['season_name']} 시즌 연패 랭킹**\n\n"
            f"{message}"
        )

    @discord.app_commands.command(
        name="시즌연승랭킹",
        description="현재 시즌 최고 연승 랭킹을 확인합니다."
    )
    async def season_streak_ranking(
        self,
        interaction: discord.Interaction
    ):
        active = get_active_season()

        if active is None:
            await interaction.response.send_message(
                "❌ 현재 진행 중인 시즌이 없습니다.",
                ephemeral=True
            )
            return

        ranking = get_all_season_player_stats(
            active["id"]
        )

        ranking = [
            player
            for player in ranking
            if player["wins"] + player["losses"] > 0
        ]

        if not ranking:
            await interaction.response.send_message(
                "❌ 현재 시즌 경기 기록이 없습니다.",
                ephemeral=True
            )
            return

        ranking = sorted(
            ranking,
            key=lambda player: (
                player.get("best_win_streak", 0),
                player.get("wins", 0),
                player.get("rating", 1000)
            ),
            reverse=True
        )

        medals = ["🥇", "🥈", "🥉"]
        message = ""

        for index, player in enumerate(
            ranking,
            start=1
        ):
            if index <= 3:
                icon = medals[index - 1]
            else:
                icon = f"{index}."

            user_id = str(
                player["discord_id"]
            )

            player_name = (
                player.get("discord_nickname")
                or get_player_name(user_id)
            )

            message += (
                f"{icon} **{player_name}**\n"
                f"🔥 최고 "
                f"{player.get('best_win_streak', 0)}연승\n"
                f"🏆 {player['wins']}승 "
                f"{player['losses']}패 | "
                f"⭐ {player['rating']}점\n\n"
            )

        await interaction.response.send_message(
            f"🔥 **{active['season_name']} 시즌 연승 랭킹**\n\n"
            f"{message}"
        )

    @discord.app_commands.command(
        name="시즌최다출전",
        description="현재 시즌 최다 출전 랭킹을 확인합니다."
    )
    async def season_most_games(
        self,
        interaction: discord.Interaction
    ):
        active = get_active_season()

        if active is None:
            await interaction.response.send_message(
                "❌ 현재 진행 중인 시즌이 없습니다.",
                ephemeral=True
            )
            return

        ranking = get_all_season_player_stats(
            active["id"]
        )

        ranking = [
            player
            for player in ranking
            if player["wins"] + player["losses"] > 0
        ]

        if not ranking:
            await interaction.response.send_message(
                "❌ 현재 시즌 경기 기록이 없습니다.",
                ephemeral=True
            )
            return

        ranking = sorted(
            ranking,
            key=lambda player: (
                player["wins"] + player["losses"],
                player["wins"],
                player["rating"]
            ),
            reverse=True
        )

        medals = ["🥇", "🥈", "🥉"]
        message = ""

        for index, player in enumerate(
            ranking,
            start=1
        ):
            if index <= 3:
                icon = medals[index - 1]
            else:
                icon = f"{index}."

            total = (
                player["wins"]
                + player["losses"]
            )

            user_id = str(
                player["discord_id"]
            )

            player_name = (
                player.get("discord_nickname")
                or get_player_name(user_id)
            )

            message += (
                f"{icon} **{player_name}**\n"
                f"🎮 {total}경기\n"
                f"🏆 {player['wins']}승 "
                f"{player['losses']}패\n"
                f"⭐ {player['rating']}점\n\n"
            )

        await interaction.response.send_message(
            f"🎮 **{active['season_name']} 시즌 최다 출전 랭킹**\n\n"
            f"{message}"
        )

    @discord.app_commands.command(
        name="시즌승수랭킹",
        description="현재 시즌 승리 횟수 랭킹을 확인합니다."
    )
    async def season_win_ranking(
        self,
        interaction: discord.Interaction
    ):
        active = get_active_season()

        if active is None:
            await interaction.response.send_message(
                "❌ 현재 진행 중인 시즌이 없습니다.",
                ephemeral=True
            )
            return

        ranking = get_all_season_player_stats(
            active["id"]
        )

        ranking = [
            player
            for player in ranking
            if player["wins"] + player["losses"] > 0
        ]

        if not ranking:
            await interaction.response.send_message(
                "❌ 현재 시즌 경기 기록이 없습니다.",
                ephemeral=True
            )
            return

        ranking = sorted(
            ranking,
            key=lambda player: (
                player["wins"],
                player["rating"]
            ),
            reverse=True
        )

        medals = ["🥇", "🥈", "🥉"]
        message = ""

        for index, player in enumerate(
            ranking,
            start=1
        ):
            if index <= 3:
                icon = medals[index - 1]
            else:
                icon = f"{index}."

            total = (
                player["wins"]
                + player["losses"]
            )

            user_id = str(
                player["discord_id"]
            )

            player_name = (
                player.get("discord_nickname")
                or get_player_name(user_id)
            )

            message += (
                f"{icon} **{player_name}**\n"
                f"🏆 {player['wins']}승\n"
                f"🎮 {total}경기 | "
                f"⭐ {player['rating']}점\n\n"
            )

        await interaction.response.send_message(
            f"🏆 **{active['season_name']} 시즌 승수 랭킹**\n\n"
            f"{message}"
        )

    @discord.app_commands.command(
        name="시즌승률랭킹",
        description="현재 시즌 승률 랭킹을 확인합니다."
    )
    async def season_winrate_ranking(
        self,
        interaction: discord.Interaction
    ):
        active = get_active_season()

        if active is None:
            await interaction.response.send_message(
                "❌ 현재 진행 중인 시즌이 없습니다.",
                ephemeral=True
            )
            return

        ranking = get_all_season_player_stats(
            active["id"]
        )

        ranking = [
            player
            for player in ranking
            if player["wins"] + player["losses"] > 0
        ]

        if not ranking:
            await interaction.response.send_message(
                "❌ 현재 시즌 경기 기록이 없습니다.",
                ephemeral=True
            )
            return

        ranking = sorted(
            ranking,
            key=lambda player: (
                player["wins"]
                / (
                    player["wins"]
                    + player["losses"]
                ),
                player["wins"],
                player["rating"]
            ),
            reverse=True
        )

        medals = ["🥇", "🥈", "🥉"]
        message = ""

        for index, player in enumerate(
            ranking,
            start=1
        ):
            if index <= 3:
                icon = medals[index - 1]
            else:
                icon = f"{index}."

            total = (
                player["wins"]
                + player["losses"]
            )

            win_rate = round(
                player["wins"]
                / total
                * 100,
                1
            )

            user_id = str(
                player["discord_id"]
            )

            player_name = (
                player.get("discord_nickname")
                or get_player_name(user_id)
            )

            message += (
                f"{icon} **{player_name}**\n"
                f"📈 {win_rate}%\n"
                f"🏆 {player['wins']}승 "
                f"{player['losses']}패\n"
                f"⭐ {player['rating']}점\n\n"
            )

        await interaction.response.send_message(
            f"📈 **{active['season_name']} 시즌 승률 랭킹**\n\n"
            f"{message}"
        )

    @discord.app_commands.command(
        name="시즌mvp랭킹",
        description="현재 시즌 MVP 횟수 랭킹을 확인합니다."
    )
    async def season_mvp_ranking(
        self,
        interaction: discord.Interaction
    ):
        active = get_active_season()

        if active is None:
            await interaction.response.send_message(
                "❌ 현재 진행 중인 시즌이 없습니다.",
                ephemeral=True
            )
            return

        ranking = get_all_season_player_stats(
            active["id"]
        )

        ranking = [
            player
            for player in ranking
            if player["wins"] + player["losses"] > 0
        ]

        if not ranking:
            await interaction.response.send_message(
                "❌ 현재 시즌 경기 기록이 없습니다.",
                ephemeral=True
            )
            return

        ranking = sorted(
            ranking,
            key=lambda player: (
                player.get("mvp", 0),
                player.get("rating", 1000)
            ),
            reverse=True
        )

        medals = ["🥇", "🥈", "🥉"]
        message = ""

        for index, player in enumerate(
            ranking,
            start=1
        ):
            if index <= 3:
                icon = medals[index - 1]
            else:
                icon = f"{index}."

            user_id = str(
                player["discord_id"]
            )

            player_name = (
                player.get("discord_nickname")
                or get_player_name(user_id)
            )

            total = (
                player["wins"]
                + player["losses"]
            )

            message += (
                f"{icon} **{player_name}**\n"
                f"🏆 MVP {player.get('mvp', 0)}회\n"
                f"🎮 {total}경기 | "
                f"⭐ {player['rating']}점\n\n"
            )

        await interaction.response.send_message(
            f"🏆 **{active['season_name']} 시즌 MVP 랭킹**\n\n"
            f"{message}"
        )

    @discord.app_commands.command(
        name="시즌랭킹",
        description="현재 시즌 레이팅 랭킹을 확인합니다."
    )
    async def season_ranking(
        self,
        interaction: discord.Interaction
    ):
        active = get_active_season()

        if active is None:
            await interaction.response.send_message(
                "❌ 진행 중인 시즌이 없습니다.",
                ephemeral=True
            )
            return

        ranking = get_all_season_player_stats(
            active["id"]
        )

        ranking = [
            player
            for player in ranking
            if player["wins"] + player["losses"] > 0
        ]

        if not ranking:
            await interaction.response.send_message(
                "아직 시즌 데이터가 없습니다.",
                ephemeral=True
            )
            return

        ranking = sorted(
            ranking,
            key=lambda player: (
                player["rating"],
                player["wins"],
                -player["losses"]
            ),
            reverse=True
        )

        medals = ["🥇", "🥈", "🥉"]
        message = ""

        for index, player in enumerate(
            ranking,
            start=1
        ):
            if index <= 3:
                icon = medals[index - 1]
            else:
                icon = f"{index}."

            total = (
                player["wins"]
                + player["losses"]
            )

            win_rate = round(
                player["wins"] / total * 100,
                1
            )

            player_name = (
                player.get("discord_nickname")
                or get_player_name(
                    str(player["discord_id"])
                )
            )

            message += (
                f"{icon} **{player_name}**\n"
                f"⭐ {player['rating']}점\n"
                f"🏆 {player['wins']}승 "
                f"{player['losses']}패 "
                f"({win_rate}%)\n\n"
            )

        await interaction.response.send_message(
            f"🏆 **{active['season_name']} 시즌 랭킹**\n\n"
            f"{message}"
        )

    @discord.app_commands.command(
        name="시즌전적",
        description="현재 시즌의 플레이어 전적을 확인합니다."
    )
    @discord.app_commands.describe(
        유저="시즌 전적을 확인할 유저"
    )
    async def season_record(
        self,
        interaction: discord.Interaction,
        유저: discord.Member
    ):
        active = get_active_season()

        if active is None:
            await interaction.response.send_message(
                "❌ 현재 진행 중인 시즌이 없습니다.",
                ephemeral=True
            )
            return

        user_id = str(유저.id)

        season_profile = get_season_player_stats(
            active["id"],
            user_id
        )

        if season_profile is None:
            await interaction.response.send_message(
                f"❌ {유저.display_name}님의 현재 시즌 전적이 없습니다.",
                ephemeral=True
            )
            return

        ranking = get_all_season_player_stats(
            active["id"]
        )

        ranking = sorted(
            ranking,
            key=lambda player: player["rating"],
            reverse=True
        )

        rank = next(
            (
                index
                for index, player in enumerate(
                    ranking,
                    start=1
                )
                if str(player["discord_id"]) == user_id
            ),
            None
        )

        wins = season_profile["wins"]
        losses = season_profile["losses"]
        total = wins + losses

        if total == 0:
            win_rate = 0
        else:
            win_rate = round(
                wins / total * 100,
                1
            )

        win_streak = season_profile["win_streak"]
        lose_streak = season_profile["lose_streak"]

        if win_streak > 0:
            current_streak = f"🔥 현재 {win_streak}연승"

        elif lose_streak > 0:
            current_streak = f"❄️ 현재 {lose_streak}연패"

        else:
            current_streak = "➖ 없음"

        rating = season_profile["rating"]
        rating_tier = get_rating_tier(rating)

        embed = discord.Embed(
            title=f"🏆 {active['season_name']} 시즌 전적"
        )

        embed.add_field(
            name="👤 플레이어",
            value=유저.mention,
            inline=False
        )

        embed.add_field(
            name="⭐ 시즌 레이팅",
            value=(
                f"{rating}점\n"
                f"{rating_tier}"
            ),
            inline=False
        )

        embed.add_field(
            name="🏆 시즌 전적",
            value=f"{wins}승 {losses}패",
            inline=True
        )

        embed.add_field(
            name="📈 시즌 승률",
            value=f"{win_rate}%",
            inline=True
        )

        embed.add_field(
            name="🔥 연승 / 연패",
            value=current_streak,
            inline=False
        )

        embed.add_field(
            name="🏅 최고 연승",
            value=f"{season_profile['best_win_streak']}연승",
            inline=True
        )

        embed.add_field(
            name="🏆 시즌 MVP",
            value=f"{season_profile['mvp']}회",
            inline=True
        )

        embed.add_field(
            name="🥇 시즌 랭킹",
            value=(
                f"{rank}위"
                if rank is not None
                else "순위 없음"
            ),
            inline=False
        )

        await interaction.response.send_message(
            embed=embed
        )

    @discord.app_commands.command(
        name="시즌목록",
        description="역대 시즌 목록을 확인합니다."
    )
    async def season_list(
        self,
        interaction: discord.Interaction
    ):
        seasons = get_all_seasons()

        if not seasons:
            await interaction.response.send_message(
                "❌ 생성된 시즌이 없습니다.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🏆 역대 시즌 목록"
        )

        for season in seasons:

            if season["is_active"]:
                status = "🟢 진행중"
            else:
                status = "⚪ 종료"

            started = season["started_at"][:10]

            ended = (
                season["ended_at"][:10]
                if season["ended_at"]
                else "-"
            )

            embed.add_field(
                name=(
                    f"시즌 {season['id']} · "
                    f"{season['season_name']}"
                ),
                value=(
                    f"{status}\n"
                    f"📅 시작 : {started}\n"
                    f"🏁 종료 : {ended}"
                ),
                inline=False
            )

        await interaction.response.send_message(
            embed=embed
        )

    @discord.app_commands.command(
        name="시즌목록",
        description="역대 시즌 목록을 확인합니다."
    )
    async def season_list(
        self,
        interaction: discord.Interaction
    ):
        seasons = get_all_seasons()

        if not seasons:
            await interaction.response.send_message(
                "❌ 생성된 시즌이 없습니다.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🏆 역대 시즌 목록"
        )

        for season in seasons:

            if season["is_active"]:
                status = "🟢 진행중"
            else:
                status = "⚪ 종료"

            started = season["started_at"][:10]

            ended = (
                season["ended_at"][:10]
                if season["ended_at"]
                else "-"
            )

            embed.add_field(
                name=(
                    f"시즌 {season['id']} · "
                    f"{season['season_name']}"
                ),
                value=(
                    f"{status}\n"
                    f"📅 시작 : {started}\n"
                    f"🏁 종료 : {ended}"
                ),
                inline=False
            )

        await interaction.response.send_message(
            embed=embed
        )

    @discord.app_commands.command(
        name="시즌정보",
        description="현재 진행 중인 시즌 정보를 확인합니다."
    )
    async def season_info(
        self,
        interaction: discord.Interaction
    ):
        active = get_active_season()

        if active is None:
            await interaction.response.send_message(
                "❌ 현재 진행 중인 시즌이 없습니다.",
                ephemeral=True
            )
            return

        season_id = active["id"]

        match_count = get_season_match_count(
            season_id
        )

        player_count = get_season_player_count(
            season_id
        )

        embed = discord.Embed(
            title="🏆 현재 시즌 정보"
        )

        embed.add_field(
            name="📛 시즌명",
            value=active["season_name"],
            inline=False
        )

        embed.add_field(
            name="🗓️ 시작일",
            value=active["started_at"],
            inline=False
        )

        embed.add_field(
            name="🏁 종료일",
            value="진행 중",
            inline=False
        )

        embed.add_field(
            name="🎮 경기 수",
            value=f"{match_count}경기",
            inline=True
        )

        embed.add_field(
            name="👥 참가자 수",
            value=f"{player_count}명",
            inline=True
        )

        await interaction.response.send_message(
            embed=embed
        )

    @discord.app_commands.command(
        name="시즌시작",
        description="새 시즌을 시작합니다."
    )
    async def start_season(
        self,
        interaction: discord.Interaction,
        시즌명: str
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        active = get_active_season()

        if active:
            await interaction.response.send_message(
                f"❌ 현재 진행 중인 시즌이 있습니다.\n"
                f"({active['season_name']})",
                ephemeral=True
            )
            return

        create_season(
            시즌명,
            datetime.now().strftime("%Y-%m-%d %H:%M")
        )

        await interaction.response.send_message(
            f"🏆 **{시즌명}** 시즌이 시작되었습니다!"
        )
    
    


async def setup(bot):
    await bot.add_cog(Season(bot))