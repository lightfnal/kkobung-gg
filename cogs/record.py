import discord
from discord.ext import commands
from storage.sqlite_db import (
    get_player,
    get_all_players,
    get_recent_matches,
    get_match_history,
    get_match_players,
    get_player_name
)


class Record(commands.Cog):


    @discord.app_commands.command(
        name="같이한전적",
        description="같은 팀으로 플레이한 전적을 확인합니다."
    )
    @discord.app_commands.describe(
        유저1="첫 번째 플레이어",
        유저2="두 번째 플레이어"
    )
    async def duo_record(
        self,
        interaction: discord.Interaction,
        유저1: discord.Member,
        유저2: discord.Member
    ):
        user1 = str(유저1.id)
        user2 = str(유저2.id)

        if user1 == user2:
            await interaction.response.send_message(
                "❌ 서로 다른 두 유저를 선택해주세요.",
                ephemeral=True
            )
            return

        wins = 0
        losses = 0

        matches = get_match_history(100000)

        for match in matches:
            players = get_match_players(
                match["id"]
            )

            red_players = {
                str(player["discord_id"])
                for player in players
                if player["team"] == "red"
            }

            blue_players = {
                str(player["discord_id"])
                for player in players
                if player["team"] == "blue"
            }

            same_red_team = (
                user1 in red_players
                and user2 in red_players
            )

            same_blue_team = (
                user1 in blue_players
                and user2 in blue_players
            )

            if not (
                same_red_team
                or same_blue_team
            ):
                continue

            won = (
                (
                    same_red_team
                    and match["winner"] == "red"
                )
                or
                (
                    same_blue_team
                    and match["winner"] == "blue"
                )
            )

            if won:
                wins += 1
            else:
                losses += 1

        total = wins + losses

        if total == 0:
            await interaction.response.send_message(
                "❌ 함께 플레이한 기록이 없습니다.",
                ephemeral=True
            )
            return

        win_rate = round(
            wins / total * 100,
            1
        )

        embed = discord.Embed(
            title="🤝 같이한 전적"
        )

        embed.add_field(
            name="플레이어",
            value=(
                f"{유저1.mention}\n"
                f"{유저2.mention}"
            ),
            inline=False
        )

        embed.add_field(
            name="전적",
            value=f"{wins}승 {losses}패",
            inline=True
        )

        embed.add_field(
            name="승률",
            value=f"{win_rate}%",
            inline=True
        )

        embed.add_field(
            name="총 경기",
            value=f"{total}경기",
            inline=False
        )

        await interaction.response.send_message(
            embed=embed
        )

    @discord.app_commands.command(
        name="먹잇감",
        description="가장 많이 승리한 상대를 확인합니다."
    )
    @discord.app_commands.describe(
        유저="먹잇감을 확인할 유저"
    )
    async def favorite_opponent(
        self,
        interaction: discord.Interaction,
        유저: discord.Member
    ):
        user_id = str(유저.id)

        wins_by_opponent = {}

        matches = get_match_history(100000)

        for match in matches:
            players = get_match_players(
                match["id"]
            )

            red_players = [
                str(player["discord_id"])
                for player in players
                if player["team"] == "red"
            ]

            blue_players = [
                str(player["discord_id"])
                for player in players
                if player["team"] == "blue"
            ]

            if user_id in red_players:
                user_team = "red"
                enemy_players = blue_players

            elif user_id in blue_players:
                user_team = "blue"
                enemy_players = red_players

            else:
                continue

            if match["winner"] != user_team:
                continue

            for enemy_id in enemy_players:
                wins_by_opponent[enemy_id] = (
                    wins_by_opponent.get(enemy_id, 0) + 1
                )

        if not wins_by_opponent:
            await interaction.response.send_message(
                "❌ 승리한 상대가 없습니다.",
                ephemeral=True
            )
            return

        favorite_id = max(
            wins_by_opponent,
            key=wins_by_opponent.get
        )

        user_wins = 0
        user_losses = 0

        for match in matches:
            players = get_match_players(
                match["id"]
            )

            red_players = {
                str(player["discord_id"])
                for player in players
                if player["team"] == "red"
            }

            blue_players = {
                str(player["discord_id"])
                for player in players
                if player["team"] == "blue"
            }

            user_red = user_id in red_players
            user_blue = user_id in blue_players

            favorite_red = favorite_id in red_players
            favorite_blue = favorite_id in blue_players

            faced_each_other = (
                (user_red and favorite_blue)
                or
                (user_blue and favorite_red)
            )

            if not faced_each_other:
                continue

            user_won = (
                (
                    user_red
                    and match["winner"] == "red"
                )
                or
                (
                    user_blue
                    and match["winner"] == "blue"
                )
            )

            if user_won:
                user_wins += 1
            else:
                user_losses += 1

        total = user_wins + user_losses

        if total == 0:
            await interaction.response.send_message(
                "❌ 먹잇감과의 맞대결 기록을 찾을 수 없습니다.",
                ephemeral=True
            )
            return

        user_rate = round(
            user_wins / total * 100,
            1
        )

        favorite_name = get_player_name(
            favorite_id
        )

        embed = discord.Embed(
            title=f"🍖 {유저.display_name}님의 먹잇감"
        )

        embed.add_field(
            name="🎯 가장 많이 이긴 상대",
            value=(
                f"<@{favorite_id}>\n"
                f"{favorite_name}"
            ),
            inline=False
        )

        embed.add_field(
            name="총 승리",
            value=f"{user_wins}승",
            inline=False
        )

        embed.add_field(
            name=유저.display_name,
            value=f"{user_wins}승 {user_losses}패",
            inline=True
        )

        embed.add_field(
            name=favorite_name,
            value=f"{user_losses}승 {user_wins}패",
            inline=True
        )

        embed.add_field(
            name="📈 내 승률",
            value=f"{user_rate}%",
            inline=False
        )

        await interaction.response.send_message(
            embed=embed
        )

    @discord.app_commands.command(
        name="천적",
        description="가장 많이 패배한 상대를 확인합니다."
    )
    @discord.app_commands.describe(
        유저="천적을 확인할 유저"
    )
    async def nemesis(
        self,
        interaction: discord.Interaction,
        유저: discord.Member
    ):
        user_id = str(유저.id)

        losses_by_opponent = {}

        matches = get_match_history(100000)

        for match in matches:
            players = get_match_players(
                match["id"]
            )

            red_players = [
                str(player["discord_id"])
                for player in players
                if player["team"] == "red"
            ]

            blue_players = [
                str(player["discord_id"])
                for player in players
                if player["team"] == "blue"
            ]

            if user_id in red_players:
                user_team = "red"
                enemy_players = blue_players

            elif user_id in blue_players:
                user_team = "blue"
                enemy_players = red_players

            else:
                continue

            if match["winner"] == user_team:
                continue

            for enemy_id in enemy_players:
                losses_by_opponent[enemy_id] = (
                    losses_by_opponent.get(enemy_id, 0) + 1
                )

        if not losses_by_opponent:
            await interaction.response.send_message(
                "❌ 패배한 상대가 없습니다.",
                ephemeral=True
            )
            return

        nemesis_id = max(
            losses_by_opponent,
            key=losses_by_opponent.get
        )

        user_wins = 0
        user_losses = 0

        for match in matches:
            players = get_match_players(
                match["id"]
            )

            red_players = {
                str(player["discord_id"])
                for player in players
                if player["team"] == "red"
            }

            blue_players = {
                str(player["discord_id"])
                for player in players
                if player["team"] == "blue"
            }

            user_red = user_id in red_players
            user_blue = user_id in blue_players

            nemesis_red = nemesis_id in red_players
            nemesis_blue = nemesis_id in blue_players

            faced_each_other = (
                (user_red and nemesis_blue)
                or
                (user_blue and nemesis_red)
            )

            if not faced_each_other:
                continue

            user_won = (
                (
                    user_red
                    and match["winner"] == "red"
                )
                or
                (
                    user_blue
                    and match["winner"] == "blue"
                )
            )

            if user_won:
                user_wins += 1
            else:
                user_losses += 1

        total = user_wins + user_losses

        if total == 0:
            await interaction.response.send_message(
                "❌ 천적과의 맞대결 기록을 찾을 수 없습니다.",
                ephemeral=True
            )
            return

        user_rate = round(
            user_wins / total * 100,
            1
        )

        nemesis_name = get_player_name(
            nemesis_id
        )

        embed = discord.Embed(
            title=f"💀 {유저.display_name}님의 천적"
        )

        embed.add_field(
            name="😈 가장 많이 진 상대",
            value=(
                f"<@{nemesis_id}>\n"
                f"{nemesis_name}"
            ),
            inline=False
        )

        embed.add_field(
            name="총 패배",
            value=f"{user_losses}패",
            inline=False
        )

        embed.add_field(
            name=유저.display_name,
            value=f"{user_wins}승 {user_losses}패",
            inline=True
        )

        embed.add_field(
            name=nemesis_name,
            value=f"{user_losses}승 {user_wins}패",
            inline=True
        )

        embed.add_field(
            name="📉 내 승률",
            value=f"{user_rate}%",
            inline=False
        )

        await interaction.response.send_message(
            embed=embed
        )

    @discord.app_commands.command(
        name="라이벌",
        description="가장 많이 맞붙은 상대를 확인합니다."
    )
    @discord.app_commands.describe(
        유저="라이벌을 확인할 유저"
    )
    async def rival(
        self,
        interaction: discord.Interaction,
        유저: discord.Member
    ):
        user_id = str(유저.id)

        opponents = {}

        matches = get_match_history(100000)

        for match in matches:
            players = get_match_players(
                match["id"]
            )

            red_players = [
                str(player["discord_id"])
                for player in players
                if player["team"] == "red"
            ]

            blue_players = [
                str(player["discord_id"])
                for player in players
                if player["team"] == "blue"
            ]

            if user_id in red_players:
                enemy_players = blue_players

            elif user_id in blue_players:
                enemy_players = red_players

            else:
                continue

            for enemy_id in enemy_players:
                opponents[enemy_id] = (
                    opponents.get(enemy_id, 0) + 1
                )

        if not opponents:
            await interaction.response.send_message(
                "❌ 맞붙은 상대가 없습니다.",
                ephemeral=True
            )
            return

        rival_id = max(
            opponents,
            key=opponents.get
        )

        match_count = opponents[rival_id]

        user_wins = 0
        rival_wins = 0

        for match in matches:
            players = get_match_players(
                match["id"]
            )

            red_players = {
                str(player["discord_id"])
                for player in players
                if player["team"] == "red"
            }

            blue_players = {
                str(player["discord_id"])
                for player in players
                if player["team"] == "blue"
            }

            user_red = user_id in red_players
            user_blue = user_id in blue_players

            rival_red = rival_id in red_players
            rival_blue = rival_id in blue_players

            faced_each_other = (
                (user_red and rival_blue)
                or
                (user_blue and rival_red)
            )

            if not faced_each_other:
                continue

            user_won = (
                (
                    user_red
                    and match["winner"] == "red"
                )
                or
                (
                    user_blue
                    and match["winner"] == "blue"
                )
            )

            if user_won:
                user_wins += 1
            else:
                rival_wins += 1

        total = user_wins + rival_wins

        if total == 0:
            await interaction.response.send_message(
                "❌ 라이벌과의 맞대결 기록을 찾을 수 없습니다.",
                ephemeral=True
            )
            return

        user_rate = round(
            user_wins / total * 100,
            1
        )

        rival_name = get_player_name(
            rival_id
        )

        embed = discord.Embed(
            title=f"⚔️ {유저.display_name}님의 라이벌"
        )

        embed.add_field(
            name="🥊 가장 많이 만난 상대",
            value=(
                f"<@{rival_id}>\n"
                f"{rival_name}"
            ),
            inline=False
        )

        embed.add_field(
            name="총 맞대결",
            value=f"{total}경기",
            inline=False
        )

        embed.add_field(
            name=유저.display_name,
            value=f"{user_wins}승 {rival_wins}패",
            inline=True
        )

        embed.add_field(
            name=rival_name,
            value=f"{rival_wins}승 {user_wins}패",
            inline=True
        )

        embed.add_field(
            name="📈 내 승률",
            value=f"{user_rate}%",
            inline=False
        )

        await interaction.response.send_message(
            embed=embed
        )

    @discord.app_commands.command(
        name="상대전적",
        description="두 플레이어의 상대 전적을 확인합니다."
    )
    @discord.app_commands.describe(
        유저1="첫 번째 플레이어",
        유저2="두 번째 플레이어"
    )
    async def head_to_head(
        self,
        interaction: discord.Interaction,
        유저1: discord.Member,
        유저2: discord.Member
    ):
        user1 = str(유저1.id)
        user2 = str(유저2.id)

        if user1 == user2:
            await interaction.response.send_message(
                "❌ 서로 다른 두 유저를 선택해주세요.",
                ephemeral=True
            )
            return

        user1_wins = 0
        user2_wins = 0
        total = 0

        matches = get_match_history(100000)

        for match in matches:
            players = get_match_players(
                match["id"]
            )

            red_players = {
                str(player["discord_id"])
                for player in players
                if player["team"] == "red"
            }

            blue_players = {
                str(player["discord_id"])
                for player in players
                if player["team"] == "blue"
            }

            user1_red = user1 in red_players
            user1_blue = user1 in blue_players

            user2_red = user2 in red_players
            user2_blue = user2 in blue_players

            faced_each_other = (
                (user1_red and user2_blue)
                or
                (user1_blue and user2_red)
            )

            if not faced_each_other:
                continue

            total += 1

            user1_won = (
                (
                    user1_red
                    and match["winner"] == "red"
                )
                or
                (
                    user1_blue
                    and match["winner"] == "blue"
                )
            )

            if user1_won:
                user1_wins += 1
            else:
                user2_wins += 1

        if total == 0:
            await interaction.response.send_message(
                f"❌ {유저1.display_name}님과 "
                f"{유저2.display_name}님이 맞붙은 기록이 없습니다."
            )
            return

        user1_rate = round(
            user1_wins / total * 100,
            1
        )

        user2_rate = round(
            user2_wins / total * 100,
            1
        )

        if user1_wins > user2_wins:
            advantage = (
                f"🔥 {유저1.display_name} 우세"
            )

        elif user2_wins > user1_wins:
            advantage = (
                f"🔥 {유저2.display_name} 우세"
            )

        else:
            advantage = "⚖️ 동률"

        embed = discord.Embed(
            title="⚔️ 상대전적",
            description=advantage
        )

        embed.add_field(
            name=유저1.display_name,
            value=(
                f"🏆 {user1_wins}승 {user2_wins}패\n"
                f"📈 승률 {user1_rate}%"
            ),
            inline=True
        )

        embed.add_field(
            name=유저2.display_name,
            value=(
                f"🏆 {user2_wins}승 {user1_wins}패\n"
                f"📈 승률 {user2_rate}%"
            ),
            inline=True
        )

        embed.add_field(
            name="총 맞대결",
            value=f"{total}경기",
            inline=False
        )

        await interaction.response.send_message(
            embed=embed
        )

    @discord.app_commands.command(
        name="최근전적",
        description="플레이어의 최근 경기 기록을 확인합니다."
    )
    @discord.app_commands.describe(
        유저="최근 전적을 확인할 유저"
    )
    async def recent_record(
        self,
        interaction: discord.Interaction,
        유저: discord.Member
    ):
        user_id = str(유저.id)

        records = get_recent_matches(user_id)

        if not records:
            await interaction.response.send_message(
                "최근 경기 기록이 없습니다.",
                ephemeral=True
            )
            return

        result_list = []
        wins = 0
        losses = 0

        for record in records:
            won = record["winner"] == record["team"]

            if won:
                wins += 1
                result = "✅ 승리"
            else:
                losses += 1
                result = "❌ 패배"

            result_list.append(
                f"{result} ({record['rating_change']:+})"
            )

        embed = discord.Embed(
            title=f"📊 {유저.display_name} 최근전적"
        )

        embed.description = "\n".join(
            f"{index}. {result}"
            for index, result in enumerate(
                result_list,
                start=1
            )
        )

        embed.add_field(
            name="최근 성적",
            value=f"{wins}승 {losses}패",
            inline=False
        )

        await interaction.response.send_message(
            embed=embed
        )

    @discord.app_commands.command(
        name="전적",
        description="플레이어의 전적을 확인합니다."
    )
    @discord.app_commands.describe(
        유저="전적을 확인할 유저"
    )
    async def player_record(
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
        rating_tier = self.get_rating_tier(rating)

        win_streak = profile["win_streak"]
        lose_streak = profile["lose_streak"]
        best_win_streak = profile["best_win_streak"]
        mvp_count = profile["mvp"]

        tier = profile["tier"]
        main_position = profile["main_position"]
        sub_position = profile["sub_position"]

        ranking = sorted(
            get_all_players(),
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

        total = wins + losses

        if total == 0:
            win_rate = 0
        else:
            win_rate = round(
                wins / total * 100,
                1
            )

        if win_streak > 0:
            streak = f"🔥 현재 {win_streak}연승"
        elif lose_streak > 0:
            streak = f"❄️ 현재 {lose_streak}연패"
        else:
            streak = "➖ 없음"

        embed = discord.Embed(
            title=f"📊 {유저.display_name}님의 전적"
        )

        embed.add_field(
            name="⭐ 레이팅",
            value=f"{rating}\n{rating_tier}",
            inline=False
        )

        embed.add_field(
            name="🏆 티어",
            value=tier or "미등록",
            inline=False
        )

        embed.add_field(
            name="🎯 포지션",
            value=(
                f"주 : {main_position or '-'}\n"
                f"부 : {sub_position or '-'}"
            ),
            inline=False
        )

        embed.add_field(
            name="🏆 전적",
            value=f"{wins}승 {losses}패",
            inline=False
        )

        embed.add_field(
            name="📈 승률",
            value=f"{win_rate}%",
            inline=False
        )

        embed.add_field(
            name="🔥 연승 / 연패",
            value=streak,
            inline=False
        )

        embed.add_field(
            name="🏅 최고 연승",
            value=f"{best_win_streak}연승",
            inline=False
        )

        embed.add_field(
            name="🏆 MVP",
            value=f"{mvp_count}회",
            inline=False
        )

        embed.add_field(
            name="🥇 서버 랭킹",
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

    def __init__(self, bot):
        
        self.bot = bot

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


async def setup(bot):
    await bot.add_cog(Record(bot))