import discord
from discord.ext import commands
from contextlib import AsyncExitStack

from config import (
    MAX_PLAYERS,
    PLACEMENT_GAMES,
    MMR_EARLY_GAMES
)

from utils.mmr import (
    get_mmr_k_factor,
    get_initial_hidden_mmr
)

from utils.permissions import (
    is_admin,
    send_admin_only_message
)

from services.player_service import PlayerService

from utils.cog_helper import get_join_cog

from storage.sqlite_db import (
    get_match_history,
    get_match_players,
    get_player_name,
    get_player_mmr_history
)


class AdminPlayer(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(
        name="테스트참가자생성",
        description="테스트용 참가자 10명을 생성합니다."
    )
    async def create_test_players(
        self,
        interaction: discord.Interaction
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not await join_cog.require_room(
            interaction
        ):
            return

        room = join_cog.active_room

        async with room.operation_lock:
            await self._create_test_players_locked(
                interaction
            )

    async def _create_test_players_locked(
        self,
        interaction: discord.Interaction
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not await join_cog.require_room(
            interaction
        ):
            return

        active_room = join_cog.active_room

        if (
            active_room.current_teams is not None
            or active_room.match_in_progress
            or active_room.mvp_vote_in_progress
            or active_room.match_transaction_active
        ):
            await interaction.response.send_message(
                "❌ 팀이 생성됐거나 경기를 처리 중일 때는 "
                "테스트 참가자를 추가할 수 없습니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        try:
            room_number = int(
                join_cog.active_room.room_id
            )

        except (
            TypeError,
            ValueError
        ):
            await interaction.followup.send(
                "❌ 테스트 참가자를 생성할 수 없는 "
                "내전 방 번호입니다.",
                ephemeral=True
            )
            return

        test_id_start = (
            900000000000000000
            + (room_number - 1) * 10
        )

        test_players = [
            ("테스트탑", "TOP", "JUNGLE"),
            ("테스트정글", "JUNGLE", "TOP"),
            ("테스트미드", "MID", "SUPPORT"),
            ("테스트원딜", "ADC", "SUPPORT"),
            ("테스트서폿", "SUPPORT", "ADC"),
            ("테스트6", "TOP", "MID"),
            ("테스트7", "JUNGLE", "MID"),
            ("테스트8", "MID", "ADC"),
            ("테스트9", "ADC", "TOP"),
            ("테스트10", "SUPPORT", "MID")
        ]

        available_slots = max(
            0,
            MAX_PLAYERS - len(active_room.players)
        )

        selected_indexes = []

        for index in range(
            len(test_players)
        ):
            user_id = str(
                test_id_start + index
            )

            # 이미 이 방에 있는 테스트 참가자는
            # 인원 증가 없이 프로필만 갱신합니다.
            if user_id in active_room.players:
                selected_indexes.append(
                    index
                )
                continue

            if available_slots <= 0:
                continue

            selected_indexes.append(
                index
            )

            available_slots -= 1

        if not selected_indexes:
            await interaction.followup.send(
                "❌ 현재 내전 방의 참가자가 이미 "
                f"{MAX_PLAYERS}명입니다.",
                ephemeral=True
            )
            return

        # 고정 테스트 ID가 다른 내전 방에 참가 중인지
        # 실제 생성 전에 모두 확인합니다.
        for index in selected_indexes:
            user_id = str(
                test_id_start + index
            )

            other_room = (
                join_cog.room_manager
                .find_player_room(
                    user_id
                )
            )

            if (
                other_room is not None
                and other_room
                is not join_cog.active_room
            ):
                await interaction.followup.send(
                    "❌ 테스트 참가자가 다른 내전에 "
                    "이미 참가 중입니다.\n"
                    f"현재 참가 중인 방: "
                    f"**{other_room.room_name}**\n"
                    "해당 방에서 `/테스트초기화`를 "
                    "먼저 실행해주세요.",
                    ephemeral=True
                )
                return

        created_count = 0
        updated_count = 0

        for index in selected_indexes:
            name, main, sub = (
                test_players[index]
            )

            user_id = str(
                test_id_start + index
            )

            profile = {
                "discord_nickname": name,
                "riot_name": name,
                "tier": "플래티넘",
                "main_position": main,
                "sub_position": sub,
                "rating": 1000,
                "wins": 0,
                "losses": 0,
                "win_streak": 0,
                "lose_streak": 0,
                "best_win_streak": 0,
                "mvp": 0
            }

            existing = PlayerService.get(
                user_id
            )

            if existing is None:
                PlayerService.create(
                    user_id,
                    profile
                )
                created_count += 1
            else:
                PlayerService.update(
                    user_id,
                    profile
                )
                updated_count += 1

            join_cog.players[user_id] = {
                "nickname": name
            }

        join_cog.save_rooms_state()

        join_cog.reload_profiles()

        await interaction.followup.send(
            "✅ 테스트 참가자 생성 완료!\n"
            f"새로 생성: {created_count}명\n"
            f"기존 갱신: {updated_count}명\n"
            f"현재 참가자: "
            f"{len(join_cog.players)}/{MAX_PLAYERS}명",
            ephemeral=True
        )



    @discord.app_commands.command(
        name="테스트초기화",
        description="테스트 참가자를 삭제합니다."
    )
    async def reset_test_players(
        self,
        interaction: discord.Interaction
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not await join_cog.require_room(
            interaction
        ):
            return

        room = join_cog.active_room

        async with room.operation_lock:
            await self._reset_test_players_locked(
                interaction
            )

    async def _reset_test_players_locked(
        self,
        interaction: discord.Interaction
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not await join_cog.require_room(
            interaction
        ):
            return

        room = join_cog.active_room

        if (
            room.current_teams is not None
            or room.match_in_progress
            or room.mvp_vote_in_progress
            or room.match_transaction_active
        ):
            await interaction.response.send_message(
                "❌ 팀이 생성됐거나 경기를 처리 중일 때는 "
                "테스트 참가자를 초기화할 수 없습니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        try:
            room_number = int(
                join_cog.active_room.room_id
            )

        except (
            TypeError,
            ValueError
        ):
            await interaction.followup.send(
                "❌ 테스트 참가자를 초기화할 수 없는 "
                "내전 방 번호입니다.",
                ephemeral=True
            )
            return

        test_id_start = (
            900000000000000000
            + (room_number - 1) * 10
        )

        test_ids = [
            str(test_id_start + index)
            for index in range(10)
        ]

        delete_count = 0

        for user_id in test_ids:
            if user_id in join_cog.players:
                del join_cog.players[user_id]

            # 다른 내전 방에서도 사용하지 않는
            # 테스트 프로필만 완전히 삭제합니다.
            other_room = (
                join_cog.room_manager
                .find_player_room(
                    user_id
                )
            )

            if (
                other_room is None
                and PlayerService.get(
                    user_id
                ) is not None
            ):
                PlayerService.delete(
                    user_id
                )
                delete_count += 1


        join_cog.current_teams = None
        join_cog.last_team_signature = None
        join_cog.match_in_progress = False
        join_cog.reload_profiles()
        join_cog.save_rooms_state()

        await interaction.followup.send(
            "✅ 테스트 참가자 초기화 완료",
            ephemeral=True
        )

    @discord.app_commands.command(
        name="참가자삭제",
        description="관리자가 내전 참가자 명단에서 유저를 제거합니다."
    )
    async def remove_participant(
        self,
        interaction: discord.Interaction,
        discord_id: str
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not await join_cog.require_room(
            interaction
        ):
            return

        room = join_cog.active_room

        async with room.operation_lock:
            if (
                room.current_teams is not None
                or room.match_in_progress
                or room.mvp_vote_in_progress
                or room.match_transaction_active
            ):
                await interaction.response.send_message(
                    "❌ 팀이 생성됐거나 경기를 처리 중일 때는 "
                    "참가자를 삭제할 수 없습니다.",
                    ephemeral=True
                )
                return

            await interaction.response.defer(
                ephemeral=True
            )

            user_id = discord_id.strip()

            if user_id not in room.players:
                await interaction.followup.send(
                    "❌ 해당 ID의 유저는 현재 참가 중이 아닙니다.",
                    ephemeral=True
                )
                return

            player_name = room.players[user_id].get(
                "nickname",
                "알 수 없음"
            )

            del room.players[user_id]

            join_cog.save_rooms_state()

            await interaction.followup.send(
                f"✅ **{player_name}**님을 참가자 명단에서 제거했습니다.\n"
                f"현재 참가자: "
                f"{len(room.players)}/{MAX_PLAYERS}명",
                ephemeral=True
            )


    @discord.app_commands.command(
        name="상대전적테스트",
        description="테스트 참가자 ID로 상대 전적을 확인합니다."
    )
    async def head_to_head_test(
        self,
        interaction: discord.Interaction,
        유저1_id: str,
        유저2_id: str
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        user1 = 유저1_id.strip()
        user2 = 유저2_id.strip()

        if user1 == user2:
            await interaction.response.send_message(
                "❌ 서로 다른 두 ID를 입력해주세요.",
                ephemeral=True
            )
            return

        if (
            PlayerService.get(user1) is None
            or PlayerService.get(user2) is None
        ):
            await interaction.response.send_message(
                "❌ 등록되지 않은 테스트 참가자 ID가 있습니다.",
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
                "❌ 두 참가자가 맞붙은 기록이 없습니다.",
                ephemeral=True
            )
            return

        user1_name = get_player_name(user1)
        user2_name = get_player_name(user2)

        user1_rate = round(
            user1_wins / total * 100,
            1
        )

        user2_rate = round(
            user2_wins / total * 100,
            1
        )

        embed = discord.Embed(
            title="🧪 테스트 상대전적"
        )

        embed.add_field(
            name=user1_name,
            value=(
                f"🏆 {user1_wins}승 {user2_wins}패\n"
                f"📈 승률 {user1_rate}%"
            ),
            inline=True
        )

        embed.add_field(
            name=user2_name,
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
        name="프로필삭제",
        description="관리자가 플레이어의 프로필을 삭제합니다."
    )
    async def delete_profile(
        self,
        interaction: discord.Interaction,
        player: discord.Member
    ):
        if not is_admin(interaction):
            await send_admin_only_message(
                interaction
            )
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        rooms = sorted(
            join_cog.room_manager.get_rooms(),
            key=lambda room: str(room.room_id)
        )

        async with AsyncExitStack() as lock_stack:
            for room in rooms:
                await lock_stack.enter_async_context(
                    room.operation_lock
                )

            await self._delete_profile_locked(
                interaction,
                player
            )

    async def _delete_profile_locked(
        self,
        interaction: discord.Interaction,
        player: discord.Member
    ):
        if not is_admin(interaction):
            await send_admin_only_message(
                interaction
            )
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        user_id = str(player.id)

        profile = PlayerService.get(
            user_id
        )

        if profile is None:
            await interaction.response.send_message(
                "❌ 해당 플레이어의 프로필이 없습니다.",
                ephemeral=True
            )
            return

        player_rooms = [
            room
            for room in join_cog.room_manager.get_rooms()
            if user_id in room.players
        ]

        busy_player_rooms = [
            room
            for room in player_rooms
            if (
                room.current_teams is not None
                or room.match_in_progress
                or room.mvp_vote_in_progress
                or room.match_transaction_active
            )
        ]

        if busy_player_rooms:
            busy_room_names = ", ".join(
                room.room_name
                for room in busy_player_rooms
            )

            await interaction.response.send_message(
                "❌ 해당 플레이어가 참가한 내전의 "
                "팀이 이미 생성됐거나 경기를 처리 중입니다.\n"
                f"진행 중인 방: **{busy_room_names}**\n"
                "내전이 완전히 종료된 뒤 삭제해주세요.",
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        PlayerService.delete(
            user_id
        )

        removed_from_room = False

        # 프로필이 삭제된 사용자를 모든 내전 방에서 제거합니다.
        for room in (
            join_cog.room_manager.get_rooms()
        ):
            if user_id in room.players:
                del room.players[user_id]
                removed_from_room = True

        if removed_from_room:
            join_cog.save_rooms_state()

        join_cog.reload_profiles()

        await interaction.followup.send(
            f"✅ {player.mention}님의 프로필을 삭제했습니다.",
            ephemeral=True
        )

    @discord.app_commands.command(
        name="전적초기화",
        description="모든 플레이어의 공개 레이팅과 전적을 초기화합니다."
    )
    @discord.app_commands.describe(
        확인문구="실행하려면 '전체초기화'를 입력하세요."
    )
    async def reset_records(
        self,
        interaction: discord.Interaction,
        확인문구: str
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        if 확인문구.strip() != "전체초기화":
            await interaction.response.send_message(
                "❌ 전적 초기화를 취소했습니다.\n"
                "실행하려면 확인 문구에 `전체초기화`를 "
                "정확히 입력해주세요.",
                ephemeral=True
            )
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        rooms = sorted(
            join_cog.room_manager.get_rooms(),
            key=lambda room: str(room.room_id)
        )

        async with AsyncExitStack() as lock_stack:
            for room in rooms:
                await lock_stack.enter_async_context(
                    room.operation_lock
                )

            await self._reset_records_locked(
                interaction,
                확인문구
            )

    async def _reset_records_locked(
        self,
        interaction: discord.Interaction,
        확인문구: str
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        if 확인문구.strip() != "전체초기화":
            await interaction.response.send_message(
                "❌ 전적 초기화를 취소했습니다.\n"
                "실행하려면 확인 문구에 `전체초기화`를 "
                "정확히 입력해주세요.",
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.followup.send(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        busy_rooms = [
            room
            for room in join_cog.room_manager.get_rooms()
            if (
                room.match_in_progress
                or room.mvp_vote_in_progress
                or room.match_transaction_active
            )
        ]

        if busy_rooms:
            busy_room_names = ", ".join(
                room.room_name
                for room in busy_rooms
            )

            await interaction.followup.send(
                "❌ 진행 중인 내전이 있어 전체 전적을 "
                "초기화할 수 없습니다.\n"
                f"진행 중인 방: **{busy_room_names}**\n"
                "모든 내전의 경기 및 결과 처리가 끝난 뒤 "
                "다시 실행해주세요.",
                ephemeral=True
            )
            return

        players = PlayerService.get_all()

        if not players:
            await interaction.followup.send(
                "❌ 초기화할 플레이어가 없습니다.",
                ephemeral=True
            )
            return

        for profile in players:
            user_id = str(
                profile["discord_id"]
            )

            profile["rating"] = 1000
            profile["wins"] = 0
            profile["losses"] = 0
            profile["win_streak"] = 0
            profile["lose_streak"] = 0
            profile["best_win_streak"] = 0
            profile["mvp"] = 0

            PlayerService.update_stats(
                user_id,
                profile
            )

        join_cog.reload_profiles()

        await interaction.followup.send(
            "✅ 모든 플레이어의 공개 레이팅과 전적을 초기화했습니다.\n"
            f"적용 인원: **{len(players)}명**\n"
            "Hidden MMR과 배치 경기 기록은 유지됩니다.",
            ephemeral=True
        )

    @discord.app_commands.command(
        name="레이팅수정",
        description="관리자가 플레이어의 레이팅을 수정합니다."
    )
    async def edit_rating(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        rating: int
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        user_id = str(player.id)

        if rating < 0 or rating > 5000:
            await interaction.response.send_message(
                "❌ 레이팅은 0~5000 사이만 입력할 수 있습니다.",
                ephemeral=True
            )
            return

        profile_row = PlayerService.get(
            user_id
        )

        if profile_row is None:
            await interaction.response.send_message(
                "❌ 등록된 프로필이 없습니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        player_room = (
            join_cog.room_manager
            .find_player_room(
                user_id
            )
        )

        async def apply_edit():
            profile = dict(
                profile_row
            )
            profile["rating"] = rating

            PlayerService.update_stats(
                user_id,
                profile
            )

            join_cog.reload_profiles()

            await interaction.followup.send(
                f"✅ {player.mention}님의 레이팅을 "
                f"**{rating}점**으로 변경했습니다.",
                ephemeral=True
            )

        if player_room is None:
            await apply_edit()
            return

        async with player_room.operation_lock:
            if (
                player_room.current_teams is not None
                or player_room.match_in_progress
                or player_room.mvp_vote_in_progress
                or player_room.match_transaction_active
            ):
                await interaction.followup.send(
                    "❌ 해당 플레이어가 참가한 내전의 "
                    "팀이 이미 생성됐거나 경기 결과를 "
                    "처리 중입니다.\n"
                    "내전이 완전히 종료된 뒤 수정해주세요.",
                    ephemeral=True
                )
                return

            await apply_edit()

    @discord.app_commands.command(
        name="mmr수정",
        description="관리자가 플레이어의 Hidden MMR을 직접 수정합니다."
    )
    async def edit_mmr(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        hidden_mmr: int
    ):
        if not is_admin(interaction):
            await send_admin_only_message(
                interaction
            )
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        # 비정상적으로 너무 낮거나 높은 값 입력 방지
        if hidden_mmr < 0 or hidden_mmr > 5000:
            await interaction.response.send_message(
                "❌ Hidden MMR은 0~5000 사이만 "
                "입력할 수 있습니다.",
                ephemeral=True
            )
            return

        user_id = str(
            player.id
        )

        profile_row = PlayerService.get(
            user_id
        )

        if profile_row is None:
            await interaction.response.send_message(
                "❌ 해당 플레이어의 프로필이 없습니다.",
                ephemeral=True
            )
            return

        # 해당 선수가 참가한 방에서 팀이 생성됐거나
        # 경기가 진행 중이면 MMR 수정을 막습니다.
        player_room = (
            join_cog.room_manager
            .find_player_room(
                user_id
            )
        )

        async def apply_edit():
            profile = dict(
                profile_row
            )

            old_hidden_mmr = profile.get(
                "hidden_mmr",
                profile.get(
                    "rating",
                    1000
                )
            )

            profile["hidden_mmr"] = (
                hidden_mmr
            )

            PlayerService.update_stats(
                user_id,
                profile
            )

            join_cog.reload_profiles()

            mmr_change = (
                hidden_mmr
                - old_hidden_mmr
            )

            await interaction.response.send_message(
                f"✅ {player.mention}님의 Hidden MMR을 "
                "수정했습니다.\n\n"
                f"기존 MMR: **{old_hidden_mmr}점**\n"
                f"새 MMR: **{hidden_mmr}점**\n"
                f"변경량: **{mmr_change:+d}점**\n\n"
                "배치 완료 경기 수와 공개 레이팅은 "
                "변경되지 않았습니다.",
                ephemeral=True
            )

        if player_room is None:
            await apply_edit()
            return

        async with player_room.operation_lock:
            if (
                player_room.current_teams is not None
                or player_room.match_in_progress
                or player_room.mvp_vote_in_progress
                or player_room.match_transaction_active
            ):
                await interaction.response.send_message(
                    "❌ 해당 플레이어가 참가한 내전의 "
                    "팀이 이미 생성됐거나 경기 결과를 "
                    "처리 중입니다.\n"
                    "내전이 완전히 종료된 뒤 수정해주세요.",
                    ephemeral=True
                )
                return

            await apply_edit()

    @discord.app_commands.command(
        name="mmr초기화",
        description="선수의 Hidden MMR을 라이엇 티어 기준으로 초기화합니다."
    )
    async def reset_mmr(
        self,
        interaction: discord.Interaction,
        player: discord.Member
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        user_id = str(
            player.id
        )

        profile_row = PlayerService.get(
            user_id
        )

        if profile_row is None:
            await interaction.response.send_message(
                "❌ 해당 플레이어의 프로필이 없습니다.",
                ephemeral=True
            )
            return

        player_room = (
            join_cog.room_manager
            .find_player_room(
                user_id
            )
        )

        async def apply_reset():
            profile = dict(
                profile_row
            )

            old_hidden_mmr = profile.get(
                "hidden_mmr",
                profile.get(
                    "rating",
                    1000
                )
            )

            old_placement_games = profile.get(
                "placement_games",
                0
            )

            riot_tier = profile.get(
                "tier",
                "언랭크"
            )

            new_hidden_mmr = get_initial_hidden_mmr(
                riot_tier
            )

            profile["hidden_mmr"] = (
                new_hidden_mmr
            )

            profile["placement_games"] = 0

            PlayerService.update_stats(
                user_id,
                profile
            )

            join_cog.reload_profiles()

            await interaction.response.send_message(
                f"✅ {player.mention}님의 Hidden MMR을 "
                f"라이엇 티어 기준으로 초기화했습니다.\n\n"
                f"기준 티어: **{riot_tier}**\n"
                f"기존 MMR: **{old_hidden_mmr}점**\n"
                f"새 MMR: **{new_hidden_mmr}점**\n"
                f"기존 완료 경기: **{old_placement_games}경기**\n"
                f"배치 진행: **0/{PLACEMENT_GAMES}경기**",
                ephemeral=True
            )

        if player_room is None:
            await apply_reset()
            return

        async with player_room.operation_lock:
            if (
                player_room.current_teams is not None
                or player_room.match_in_progress
                or player_room.mvp_vote_in_progress
                or player_room.match_transaction_active
            ):
                await interaction.response.send_message(
                    "❌ 해당 플레이어가 참가한 내전의 "
                    "팀이 이미 생성됐거나 경기 결과를 "
                    "처리 중입니다.\n"
                    "내전이 완전히 종료된 뒤 초기화해주세요.",
                    ephemeral=True
                )
                return

            await apply_reset()

    @discord.app_commands.command(
        name="mmr확인",
        description="관리자가 플레이어의 Hidden MMR을 확인합니다."
    )
    async def check_mmr(
        self,
        interaction: discord.Interaction,
        player: discord.Member
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        profile_row = PlayerService.get(
            str(player.id)
        )

        if profile_row is None:
            await interaction.response.send_message(
                "❌ 해당 플레이어의 프로필이 없습니다.",
                ephemeral=True
            )
            return

        profile = dict(
            profile_row
        )

        rating = profile.get(
            "rating",
            1000
        )

        hidden_mmr = profile.get(
            "hidden_mmr",
            rating
        )

        placement_games = profile.get(
            "placement_games",
            0
        )

        k_factor = get_mmr_k_factor(
            placement_games
        )

        if placement_games < PLACEMENT_GAMES:
            mmr_phase = (
                f"배치 구간 "
                f"({placement_games}/{PLACEMENT_GAMES})"
            )

            remaining_games = (
                PLACEMENT_GAMES
                - placement_games
            )

            phase_detail = (
                f"배치 완료까지 {remaining_games}경기 남음"
            )

        elif placement_games < MMR_EARLY_GAMES:
            mmr_phase = (
                f"초기 안정화 구간 "
                f"({placement_games}/{MMR_EARLY_GAMES})"
            )

            remaining_games = (
                MMR_EARLY_GAMES
                - placement_games
            )

            phase_detail = (
                f"일반 구간까지 {remaining_games}경기 남음"
            )

        else:
            mmr_phase = "일반 구간"
            phase_detail = "MMR 변동이 안정화된 상태"

        embed = discord.Embed(
            title="🔒 관리자 Hidden MMR 조회",
            description=(
                f"대상: {player.mention}\n"
                f"닉네임: **{profile.get('discord_nickname', player.display_name)}**"
            ),
            color=discord.Color.dark_grey()
        )

        embed.add_field(
            name="공개 레이팅",
            value=f"**{rating}점**",
            inline=True
        )

        embed.add_field(
            name="Hidden MMR",
            value=f"**{hidden_mmr}점**",
            inline=True
        )

        embed.add_field(
            name="완료 경기",
            value=f"**{placement_games}경기**",
            inline=True
        )

        embed.add_field(
            name="MMR 적용 구간",
            value=(
                f"**{mmr_phase}**\n"
                f"{phase_detail}"
            ),
            inline=False
        )

        embed.add_field(
            name="다음 경기 K값",
            value=f"**K = {k_factor}**",
            inline=False
        )

        embed.set_footer(
            text="이 정보는 관리자에게만 표시됩니다."
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )       

    @discord.app_commands.command(
        name="mmr기록",
        description="관리자가 플레이어의 최근 Hidden MMR 변동을 확인합니다."
    )
    async def mmr_history(
        self,
        interaction: discord.Interaction,
        player: discord.Member
    ):
        if not is_admin(interaction):
            await send_admin_only_message(
                interaction
            )
            return

        profile_row = PlayerService.get(
            str(player.id)
        )

        if profile_row is None:
            await interaction.response.send_message(
                "❌ 해당 플레이어의 프로필이 없습니다.",
                ephemeral=True
            )
            return

        records = get_player_mmr_history(
            discord_id=str(player.id),
            limit=5
        )

        if not records:
            await interaction.response.send_message(
                f"ℹ️ {player.mention}님의 "
                "저장된 MMR 경기 기록이 없습니다.",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title="🔒 관리자 Hidden MMR 기록",
            description=(
                f"대상: {player.mention}\n"
                "최근 5경기 기록입니다."
            ),
            color=discord.Color.gold()
        )

        for row in records:
            record = dict(
                row
            )

            result_text = (
                "승리"
                if record["won"]
                else "패배"
            )

            mmr_change = record[
                "hidden_mmr_change"
            ]

            embed.add_field(
                name=(
                    f"경기 #{record['match_id']} · "
                    f"{record['match_date']}"
                ),
                value=(
                    f"결과: **{result_text}**\n"
                    f"MMR: **{record['hidden_mmr_before']} → "
                    f"{record['hidden_mmr_after']} "
                    f"({mmr_change:+d})**\n"
                    f"완료 경기: "
                    f"**{record['placement_games_before']} → "
                    f"{record['placement_games_after']}**"
                ),
                inline=False
            )

        embed.set_footer(
            text="이 정보는 관리자에게만 표시됩니다."
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

async def setup(bot):
    await bot.add_cog(AdminPlayer(bot))
