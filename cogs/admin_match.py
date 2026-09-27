import logging
from typing import Literal, Optional

import discord
from discord.ext import commands

from config import MAX_PLAYERS

from services.player_service import PlayerService

from storage.sqlite_db import (
    get_last_match,
    get_match_players,
    get_match,
    get_player,
    delete_last_match,
    delete_match_only,
    update_season_player_stats,
    begin_transaction,
    commit_transaction,
    rollback_transaction
)

from utils.cog_helper import get_join_cog
from views.join_view import JoinView
from utils.permissions import (
    is_admin,
    send_admin_only_message
)


logger = logging.getLogger(__name__)


class AdminMatch(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(
        name="경기강제종료",
        description="관리자가 진행 중인 경기를 강제로 종료합니다."
    )
    async def force_end_match(
        self,
        interaction: discord.Interaction
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(self.bot)

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not await join_cog.require_room(interaction):
            return

        room = join_cog.active_room

        async with room.operation_lock:
            await self._force_end_match_locked(
                interaction,
                room
            )

    async def _force_end_match_locked(
        self,
        interaction: discord.Interaction,
        room
    ):
        join_cog = get_join_cog(self.bot)

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not room.match_in_progress:
            await interaction.response.send_message(
                "❌ 현재 진행 중인 경기가 없습니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        logger.warning(
            "경기 강제 종료 시작 | 방=%s | 시리즈ID=%s | 경기ID=%s",
            room.room_id,
            getattr(room, "current_series_id", None),
            getattr(room, "current_match_id", None)
        )

        room.invalidate_game_views()

        room.match_in_progress = False
        room.mvp_vote_in_progress = False

        room.match_transaction_active = False
        room.match_transaction_committed = False

        room.transaction_series_score = None
        room.transaction_series_game = None

        room.pending_match_token = None
        room.pending_series_score = None
        room.pending_series_game = None

        room.clear_current_match_id()

        join_cog.save_rooms_state()

        output_message, used_fallback = (
            await join_cog.send_output_message(
                room=room,
                fallback_channel=interaction.channel,
                content=(
                    f"⚠️ **{room.room_name} · 진행 중인 "
                    "경기를 강제로 종료했습니다.**\n"
                    f"방 번호: **{room.room_id}**\n\n"
                    "레이팅 및 전적 변화는 적용되지 않았습니다.\n"
                    "현재 팀과 시리즈 점수는 유지됩니다.\n"
                    f"<#{room.channel_id}>에서 `/경기시작`으로 "
                    "다시 시작할 수 있습니다."
                )
            )
        )

        if output_message is None:
            confirmation_message = (
                "✅ 경기 상태는 강제로 종료했습니다.\n"
                "⚠️ 다만 종료 안내 메시지는 전송하지 못했습니다."
            )

        elif used_fallback:
            confirmation_message = (
                "✅ 경기를 강제로 종료했습니다.\n"
                "⚠️ 공용 진행 채널에 접근할 수 없어 "
                "현재 모집 채널에 안내를 표시했습니다."
            )

        elif output_message.channel.id == interaction.channel_id:
            confirmation_message = (
                "✅ 경기를 강제로 종료하고 현재 채널에 "
                "안내를 표시했습니다."
            )

        else:
            confirmation_message = (
                "✅ 경기를 강제로 종료하고 공용 진행 "
                "채널에 안내를 표시했습니다.\n"
                f"진행 채널: <#{output_message.channel.id}>"
            )

        logger.warning(
            "경기 강제 종료 완료 | 방=%s | 시리즈ID=%s",
            room.room_id,
            getattr(room, "current_series_id", None)
        )

        await interaction.followup.send(
            confirmation_message,
            ephemeral=True
        )

    @discord.app_commands.command(
        name="경기기록만삭제",
        description="관리자가 경기 전적 변화 없이 경기 기록만 삭제합니다."
    )
    @discord.app_commands.describe(
        경기번호="삭제할 경기 번호"
    )
    async def delete_match_record_only(
        self,
        interaction: discord.Interaction,
        경기번호: int
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(self.bot)

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not await join_cog.require_room(interaction):
            return

        room = join_cog.active_room

        async with room.operation_lock:
            await self._delete_match_record_only_locked(
                interaction,
                경기번호,
                room
            )

    async def _delete_match_record_only_locked(
        self,
        interaction: discord.Interaction,
        경기번호: int,
        room
    ):
        join_cog = get_join_cog(self.bot)

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if room.match_transaction_active:
            await interaction.response.send_message(
                "❌ 현재 이 내전 방에서 경기 결과를 "
                "처리하고 있습니다.\n"
                "잠시 후 다시 시도해주세요.",
                ephemeral=True
            )
            return

        match = get_match(경기번호)

        if match is None:
            await interaction.response.send_message(
                "❌ 해당 경기 기록이 없습니다.",
                ephemeral=True
            )
            return

        match_room_id = match.get("room_id")

        if (
            match_room_id is None
            or str(match_room_id) != str(room.room_id)
        ):
            await interaction.response.send_message(
                "❌ 현재 내전 방의 경기 기록이 아닙니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        deleted = delete_match_only(경기번호)

        if not deleted:
            raise RuntimeError(
                "경기 기록 삭제에 실패했습니다."
            )

        logger.warning(
            "경기 기록만 삭제 | 방=%s | DB경기번호=%s | "
            "시리즈ID=%s | 경기ID=%s",
            room.room_id,
            경기번호,
            match.get("series_id"),
            match.get("room_match_id")
        )

        output_message, used_fallback = (
            await join_cog.send_output_message(
                room=room,
                fallback_channel=interaction.channel,
                content=(
                    f"🗑️ **{room.room_name} · 경기 기록 삭제**\n"
                    f"방 번호: **{room.room_id}**\n"
                    f"삭제된 경기: **#{경기번호}**\n\n"
                    "경기 기록만 삭제했으며 레이팅과 "
                    "승패 기록은 변경하지 않았습니다."
                )
            )
        )

        if output_message is None:
            confirmation_message = (
                "✅ 경기 기록은 삭제했습니다.\n"
                "⚠️ 다만 삭제 안내 메시지는 전송하지 못했습니다."
            )

        elif used_fallback:
            confirmation_message = (
                "✅ 경기 기록을 삭제했습니다.\n"
                "⚠️ 공용 진행 채널에 접근할 수 없어 "
                "현재 모집 채널에 안내를 표시했습니다."
            )

        elif output_message.channel.id == interaction.channel_id:
            confirmation_message = (
                "✅ 경기 기록을 삭제하고 현재 채널에 "
                "안내를 표시했습니다."
            )

        else:
            confirmation_message = (
                "✅ 경기 기록을 삭제하고 공용 진행 "
                "채널에 안내를 표시했습니다.\n"
                f"진행 채널: <#{output_message.channel.id}>"
            )

        await interaction.followup.send(
            confirmation_message,
            ephemeral=True
        )

    @discord.app_commands.command(
        name="경기취소",
        description="가장 최근 경기 결과를 취소합니다."
    )
    async def cancel_match(
        self,
        interaction: discord.Interaction
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(self.bot)

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not await join_cog.require_room(interaction):
            return

        room = join_cog.active_room

        async with room.operation_lock:
            await self._cancel_match_locked(
                interaction,
                room
            )

    async def _cancel_match_locked(
        self,
        interaction: discord.Interaction,
        room
    ):
        join_cog = get_join_cog(self.bot)

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if room.match_transaction_active:
            await interaction.response.send_message(
                "❌ 현재 이 내전 방에서 경기 결과를 "
                "처리하고 있습니다.\n"
                "잠시 후 다시 시도해주세요.",
                ephemeral=True
            )
            return

        if room.match_in_progress:
            await interaction.response.send_message(
                "❌ 현재 경기가 진행 중입니다.\n"
                "진행 중인 경기를 먼저 정상 종료하거나 "
                "`/경기강제종료`로 종료해주세요.",
                ephemeral=True
            )
            return

        if room.mvp_vote_in_progress:
            await interaction.response.send_message(
                "❌ MVP 투표가 진행 중일 때는 "
                "이전 경기 결과를 취소할 수 없습니다.",
                ephemeral=True
            )
            return

        last_match = get_last_match(
            room_id=room.room_id
        )

        if last_match is None:
            await interaction.response.send_message(
                "❌ 취소할 경기 기록이 없습니다.",
                ephemeral=True
            )
            return

        match_id = last_match["id"]
        season_id = last_match.get("season_id")

        match_players = get_match_players(match_id)

        if not match_players:
            await interaction.response.send_message(
                "❌ 최근 경기의 선수 기록을 찾을 수 없습니다.",
                ephemeral=True
            )
            return

        room.match_transaction_active = True
        room.match_transaction_committed = False

        join_cog.save_rooms_state()

        await interaction.response.defer(
            ephemeral=True
        )

        transaction_started = False
        transaction_committed = False

        try:
            begin_transaction()
            transaction_started = True

            for match_player in match_players:
                user_id = str(
                    match_player["discord_id"]
                )

                profile_row = PlayerService.get(
                    user_id
                )

                if profile_row is None:
                    continue

                profile = dict(profile_row)

                profile["rating"] = (
                    match_player["rating_before"]
                )

                if (
                    match_player.get("hidden_mmr_before")
                    is not None
                ):
                    profile["hidden_mmr"] = (
                        match_player["hidden_mmr_before"]
                    )

                if (
                    match_player.get("placement_games_before")
                    is not None
                ):
                    profile["placement_games"] = (
                        match_player["placement_games_before"]
                    )

                profile["win_streak"] = match_player.get(
                    "win_streak_before",
                    0
                )

                profile["lose_streak"] = match_player.get(
                    "lose_streak_before",
                    0
                )

                profile["best_win_streak"] = match_player.get(
                    "best_win_streak_before",
                    0
                )

                if match_player["won"] == 1:
                    profile["wins"] = max(
                        0,
                        profile["wins"] - 1
                    )
                else:
                    profile["losses"] = max(
                        0,
                        profile["losses"] - 1
                    )

                PlayerService.update_stats(
                    user_id,
                    profile,
                    auto_commit=False
                )

                if (
                    season_id is not None
                    and match_player.get("season_rating_before")
                    is not None
                ):
                    season_stats = {
                        "rating": match_player[
                            "season_rating_before"
                        ],
                        "wins": match_player[
                            "season_wins_before"
                        ],
                        "losses": match_player[
                            "season_losses_before"
                        ],
                        "win_streak": match_player[
                            "season_win_streak_before"
                        ],
                        "lose_streak": match_player[
                            "season_lose_streak_before"
                        ],
                        "best_win_streak": match_player[
                            "season_best_win_streak_before"
                        ],
                        "mvp": match_player[
                            "season_mvp_before"
                        ]
                    }

                    update_season_player_stats(
                        season_id,
                        user_id,
                        season_stats,
                        auto_commit=False
                    )

            mvp_id = last_match.get(
                "mvp_discord_id"
            )

            if mvp_id is not None:
                mvp_profile_row = PlayerService.get(
                    str(mvp_id)
                )

                if mvp_profile_row is not None:
                    mvp_profile = dict(
                        mvp_profile_row
                    )

                    mvp_profile["mvp"] = max(
                        0,
                        mvp_profile["mvp"] - 1
                    )

                    PlayerService.update_stats(
                        str(mvp_id),
                        mvp_profile,
                        auto_commit=False
                    )

            deleted = delete_last_match(
                room_id=room.room_id,
                auto_commit=False
            )

            if not deleted:
                raise RuntimeError(
                    "경기 기록 삭제에 실패했습니다."
                )

            commit_transaction()

            transaction_started = False
            transaction_committed = True

            room.match_transaction_committed = True

            join_cog.reload_profiles()

            logger.warning(
                "경기 결과 취소 완료 | 방=%s | DB경기번호=%s | "
                "시리즈ID=%s | 경기ID=%s",
                room.room_id,
                match_id,
                last_match.get("series_id"),
                last_match.get("room_match_id")
            )

            output_message, used_fallback = (
                await join_cog.send_output_message(
                    room=room,
                    fallback_channel=interaction.channel,
                    content=(
                        f"↩️ **{room.room_name} · 경기 결과 취소**\n"
                        f"방 번호: **{room.room_id}**\n"
                        f"취소된 경기: **#{match_id}**\n\n"
                        "전체 및 시즌 레이팅, Hidden MMR, "
                        "배치 경기 수, 승패, 연승·연패, "
                        "MVP 기록이 복구되었습니다."
                    )
                )
            )

            if output_message is None:
                confirmation_message = (
                    "✅ 경기 결과는 정상적으로 취소했습니다.\n"
                    "⚠️ 다만 취소 안내 메시지는 전송하지 "
                    "못했습니다."
                )

            elif used_fallback:
                confirmation_message = (
                    "✅ 경기 결과를 취소했습니다.\n"
                    "⚠️ 공용 진행 채널에 접근할 수 없어 "
                    "현재 모집 채널에 안내를 표시했습니다."
                )

            elif output_message.channel.id == interaction.channel_id:
                confirmation_message = (
                    "✅ 경기 결과를 취소하고 현재 채널에 "
                    "안내를 표시했습니다."
                )

            else:
                confirmation_message = (
                    "✅ 경기 결과를 취소하고 공용 진행 "
                    "채널에 안내를 표시했습니다.\n"
                    f"진행 채널: <#{output_message.channel.id}>"
                )

            await interaction.followup.send(
                confirmation_message,
                ephemeral=True
            )

        except Exception as error:
            if transaction_started:
                rollback_transaction()
                transaction_started = False

            logger.exception(
                "경기 취소 트랜잭션 오류: %r",
                error
            )

            if transaction_committed:
                error_message = (
                    "⚠️ 경기 취소 데이터는 정상적으로 "
                    "저장됐지만 안내 처리 중 오류가 "
                    "발생했습니다."
                )
            else:
                error_message = (
                    "❌ 경기 결과 취소 중 오류가 발생했습니다.\n"
                    "모든 데이터 변경을 취소했으므로 "
                    "선수 기록은 변경되지 않았습니다."
                )

            try:
                await interaction.followup.send(
                    error_message,
                    ephemeral=True
                )

            except discord.HTTPException:
                pass

        finally:
            room.match_transaction_active = False
            room.match_transaction_committed = False

            join_cog.save_rooms_state()

    @discord.app_commands.command(
        name="관리자일괄참가",
        description="관리자가 선택한 10명을 내전 방에 한 번에 참가시킵니다."
    )
    async def admin_bulk_join(
        self,
        interaction: discord.Interaction,
        참가자1: discord.Member,
        참가자2: discord.Member,
        참가자3: discord.Member,
        참가자4: discord.Member,
        참가자5: discord.Member,
        참가자6: discord.Member,
        참가자7: discord.Member,
        참가자8: discord.Member,
        참가자9: discord.Member,
        참가자10: discord.Member
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(self.bot)
        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not await join_cog.require_room(interaction):
            return

        members = [
            참가자1, 참가자2, 참가자3, 참가자4, 참가자5,
            참가자6, 참가자7, 참가자8, 참가자9, 참가자10
        ]
        member_ids = [str(member.id) for member in members]

        if len(set(member_ids)) != MAX_PLAYERS:
            await interaction.response.send_message(
                "❌ 서로 다른 10명을 선택해주세요.",
                ephemeral=True
            )
            return

        missing_profiles = [
            member.mention
            for member in members
            if get_player(str(member.id)) is None
        ]
        if missing_profiles:
            await interaction.response.send_message(
                "❌ 프로필이 없는 참가자가 있습니다: "
                + ", ".join(missing_profiles),
                ephemeral=True
            )
            return

        room = join_cog.active_room

        async with join_cog.room_manager.management_lock:
            async with room.operation_lock:
                if (
                    room.match_in_progress
                    or room.mvp_vote_in_progress
                    or room.match_transaction_active
                    or room.current_teams is not None
                ):
                    await interaction.response.send_message(
                        "❌ 진행 중인 경기나 생성된 팀이 있어 명단을 복구할 수 없습니다.",
                        ephemeral=True
                    )
                    return

                if room.players:
                    await interaction.response.send_message(
                        "❌ 현재 참가 명단이 비어 있지 않습니다. 기존 명단을 먼저 확인해주세요.",
                        ephemeral=True
                    )
                    return

                occupied = []
                for member in members:
                    other_room = join_cog.room_manager.find_player_room(
                        str(member.id)
                    )
                    if other_room is not None and other_room is not room:
                        occupied.append(
                            f"{member.mention}({other_room.room_name})"
                        )

                if occupied:
                    await interaction.response.send_message(
                        "❌ 다른 내전에 참가 중인 선수가 있습니다: "
                        + ", ".join(occupied),
                        ephemeral=True
                    )
                    return

                room.players = {
                    str(member.id): {"nickname": member.display_name}
                    for member in members
                }
                room.series_score = {"red": 0, "blue": 0}
                room.series_game = 0
                room.last_team_signature = None
                join_cog.save_rooms_state()

        await interaction.response.send_message(
            "✅ 관리자 일괄 참가가 완료되었습니다.\n"
            + "\n".join(
                f"{index}. {member.mention}"
                for index, member in enumerate(members, start=1)
            )
            + "\n\n이제 `/관리자팀생성`을 실행해주세요.",
            ephemeral=True
        )

    @discord.app_commands.command(
        name="관리자팀생성",
        description="모집창 없이 현재 참가자 10명으로 팀을 생성합니다."
    )
    async def admin_generate_teams(
        self,
        interaction: discord.Interaction
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(self.bot)
        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not await join_cog.require_room(interaction):
            return

        room = join_cog.active_room
        if len(room.players) != MAX_PLAYERS:
            await interaction.response.send_message(
                f"❌ 참가자가 {MAX_PLAYERS}명이어야 합니다. "
                f"현재 {len(room.players)}/{MAX_PLAYERS}명입니다.",
                ephemeral=True
            )
            return

        view = JoinView(join_cog)
        await view.generate_teams(interaction)

    @discord.app_commands.command(
        name="관리자팀지정",
        description="관리자가 레드·블루팀의 선수와 포지션을 직접 지정합니다."
    )
    async def admin_assign_teams(
        self,
        interaction: discord.Interaction,
        레드_top: discord.Member,
        레드_jungle: discord.Member,
        레드_mid: discord.Member,
        레드_adc: discord.Member,
        레드_support: discord.Member,
        블루_top: discord.Member,
        블루_jungle: discord.Member,
        블루_mid: discord.Member,
        블루_adc: discord.Member,
        블루_support: discord.Member
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(self.bot)
        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not await join_cog.require_room(interaction):
            return

        room = join_cog.active_room
        red_members = [
            레드_top, 레드_jungle, 레드_mid, 레드_adc, 레드_support
        ]
        blue_members = [
            블루_top, 블루_jungle, 블루_mid, 블루_adc, 블루_support
        ]
        selected_ids = {
            str(member.id)
            for member in red_members + blue_members
        }

        if len(selected_ids) != MAX_PLAYERS:
            await interaction.response.send_message(
                "❌ 서로 다른 10명을 각 팀과 포지션에 지정해주세요.",
                ephemeral=True
            )
            return

        if selected_ids != set(room.players.keys()):
            await interaction.response.send_message(
                "❌ 팀에 지정한 10명이 현재 참가 명단과 정확히 일치해야 합니다.",
                ephemeral=True
            )
            return

        async with room.operation_lock:
            if (
                room.match_in_progress
                or room.mvp_vote_in_progress
                or room.match_transaction_active
            ):
                await interaction.response.send_message(
                    "❌ 진행 중인 경기 처리가 있어 팀을 지정할 수 없습니다.",
                    ephemeral=True
                )
                return

            positions = ["TOP", "JUNGLE", "MID", "ADC", "SUPPORT"]
            room.current_teams = {
                "red": {
                    position: str(member.id)
                    for position, member in zip(positions, red_members)
                },
                "blue": {
                    position: str(member.id)
                    for position, member in zip(positions, blue_members)
                }
            }
            room.last_team_signature = None
            join_cog.save_rooms_state()

        await interaction.response.send_message(
            "✅ 관리자 팀 지정이 완료되었습니다.\n\n"
            "🔴 레드팀\n"
            + "\n".join(
                f"{position}: {member.mention}"
                for position, member in zip(positions, red_members)
            )
            + "\n\n🔵 블루팀\n"
            + "\n".join(
                f"{position}: {member.mention}"
                for position, member in zip(positions, blue_members)
            ),
            ephemeral=True
        )

    @discord.app_commands.command(
        name="관리자경기결과",
        description="MVP 투표 없이 관리자가 승리팀과 MVP를 직접 기록합니다."
    )
    async def admin_match_result(
        self,
        interaction: discord.Interaction,
        승리팀: Literal["레드", "블루"],
        mvp: discord.Member
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(self.bot)
        match_cog = self.bot.get_cog("Match")
        if join_cog is None or match_cog is None:
            await interaction.response.send_message(
                "❌ 경기 처리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not await join_cog.require_room(interaction):
            return

        room = join_cog.active_room
        async with room.operation_lock:
            if room.mvp_vote_in_progress:
                await interaction.response.send_message(
                    "❌ 이미 MVP 투표가 진행 중입니다.",
                    ephemeral=True
                )
                return

            if room.match_transaction_active:
                await interaction.response.send_message(
                    "❌ 현재 경기 결과를 처리 중입니다.",
                    ephemeral=True
                )
                return

            if not room.match_in_progress or room.current_teams is None:
                await interaction.response.send_message(
                    "❌ 먼저 팀을 생성하고 `/경기시작`을 실행해주세요.",
                    ephemeral=True
                )
                return

            player_ids = {
                str(user_id)
                for team in room.current_teams.values()
                for user_id in team.values()
            }
            if str(mvp.id) not in player_ids:
                await interaction.response.send_message(
                    "❌ MVP는 현재 경기 참가자만 선택할 수 있습니다.",
                    ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True)
            winner = "red" if 승리팀 == "레드" else "blue"

            try:
                previous_match = get_last_match(room_id=room.room_id)
                previous_match_id = (
                    previous_match["id"]
                    if previous_match is not None
                    else None
                )
                await match_cog.process_match_result(
                    interaction,
                    winner,
                    str(mvp.id),
                    room
                )
                saved_match = get_last_match(room_id=room.room_id)
                if (
                    saved_match is None
                    or saved_match["id"] == previous_match_id
                    or saved_match["winner"] != winner
                    or str(saved_match["mvp_discord_id"]) != str(mvp.id)
                ):
                    raise RuntimeError("관리자 경기 결과 검증에 실패했습니다.")

            except Exception:
                logger.exception(
                    "관리자 경기 결과 처리 실패 | 방=%s",
                    room.room_id
                )
                if room.match_transaction_active:
                    rollback_transaction()
                    room.match_transaction_active = False
                    room.match_transaction_committed = False
                    if room.transaction_series_score is not None:
                        room.series_score = dict(room.transaction_series_score)
                    if room.transaction_series_game is not None:
                        room.series_game = room.transaction_series_game
                    room.pending_match_token = None
                    room.pending_series_score = None
                    room.pending_series_game = None
                room.match_in_progress = False
                join_cog.save_rooms_state()
                await interaction.followup.send(
                    "❌ 경기 결과 처리 중 오류가 발생했습니다. 로그를 확인해주세요.",
                    ephemeral=True
                )
                return

            await interaction.followup.send(
                "✅ 관리자 경기 결과 처리가 완료되었습니다.\n"
                f"승리팀: {승리팀}\nMVP: {mvp.mention}",
                ephemeral=True
            )

    @discord.app_commands.command(
        name="경기복구",
        description="누락된 BO3 결과를 선택한 세트부터 정상 처리로 복구합니다."
    )
    @discord.app_commands.describe(
        시작세트="복구를 시작할 세트",
        일세트_mvp="1세트 MVP (레드팀 승리)",
        이세트_mvp="2세트 MVP (블루팀 승리)",
        삼세트_mvp="3세트 MVP (레드팀 승리)"
    )
    async def recover_match(
        self,
        interaction: discord.Interaction,
        시작세트: Literal["1세트", "2세트", "3세트"],
        일세트_mvp: Optional[discord.Member] = None,
        이세트_mvp: Optional[discord.Member] = None,
        삼세트_mvp: Optional[discord.Member] = None
    ):
        """선택한 시작 세트부터 기존 정상 경기 처리 경로로 복구합니다."""
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(self.bot)
        match_cog = self.bot.get_cog("Match")

        if join_cog is None or match_cog is None:
            await interaction.response.send_message(
                "❌ 경기 처리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not await join_cog.require_room(interaction):
            return

        room = join_cog.active_room

        async with room.operation_lock:
            await self._recover_match_locked(
                interaction,
                join_cog,
                match_cog,
                room,
                시작세트,
                일세트_mvp,
                이세트_mvp,
                삼세트_mvp
            )

    async def _recover_match_locked(
        self,
        interaction: discord.Interaction,
        join_cog,
        match_cog,
        room,
        start_set: str,
        first_mvp: Optional[discord.Member],
        second_mvp: Optional[discord.Member],
        third_mvp: Optional[discord.Member]
    ):
        if room.match_transaction_active:
            await interaction.response.send_message(
                "❌ 현재 경기 결과를 처리 중입니다. 잠시 후 다시 시도해주세요.",
                ephemeral=True
            )
            return

        if room.mvp_vote_in_progress or room.match_in_progress:
            await interaction.response.send_message(
                "❌ 진행 중인 경기 또는 MVP 투표가 있어 복구할 수 없습니다.",
                ephemeral=True
            )
            return

        if room.current_teams is None:
            await interaction.response.send_message(
                "❌ 복구할 팀 정보가 없습니다.",
                ephemeral=True
            )
            return

        player_ids = {
            str(user_id)
            for team in room.current_teams.values()
            for user_id in team.values()
        }
        if len(player_ids) != MAX_PLAYERS:
            await interaction.response.send_message(
                "❌ 현재 팀 구성이 정확히 10명이 아닙니다.",
                ephemeral=True
            )
            return

        all_results = [
            ("1세트", "red", first_mvp),
            ("2세트", "blue", second_mvp),
            ("3세트", "red", third_mvp)
        ]
        start_index = {
            "1세트": 0,
            "2세트": 1,
            "3세트": 2
        }[start_set]
        results_to_apply = all_results[start_index:]
        missing_mvp_sets = [
            set_name
            for set_name, _, mvp_member in results_to_apply
            if mvp_member is None
        ]
        if missing_mvp_sets:
            await interaction.response.send_message(
                "❌ 복구할 세트의 MVP를 모두 선택해주세요: "
                + ", ".join(missing_mvp_sets),
                ephemeral=True
            )
            return

        invalid_mvp_sets = [
            set_name
            for set_name, _, mvp_member in results_to_apply
            if str(mvp_member.id) not in player_ids
        ]
        if invalid_mvp_sets:
            await interaction.response.send_message(
                "❌ 현재 팀 참가자가 아닌 MVP가 있습니다: "
                + ", ".join(invalid_mvp_sets),
                ephemeral=True
            )
            return

        expected_states = {
            "1세트": ({"red": 0, "blue": 0}, 0),
            "2세트": ({"red": 1, "blue": 0}, 1),
            "3세트": ({"red": 1, "blue": 1}, 2)
        }
        expected_score, expected_game = expected_states[start_set]
        current_score = dict(room.series_score)
        current_game = int(room.series_game)
        reset_state = (
            current_score == {"red": 0, "blue": 0}
            and current_game == 0
        )

        if (current_score, current_game) != (expected_score, expected_game):
            if start_index == 0 or not reset_state:
                await interaction.response.send_message(
                    "❌ 선택한 시작 세트와 현재 시리즈 상태가 다릅니다.\n"
                    f"현재 상태: 레드 {current_score.get('red', 0)} : "
                    f"{current_score.get('blue', 0)} 블루 / "
                    f"완료 {current_game}세트",
                    ephemeral=True
                )
                return

            # `/경기종료`로 메모리 상태가 초기화된 경우에는 DB의
            # 마지막 완료 세트를 확인한 뒤 시작 직전 점수만 복원합니다.
            last_match = get_last_match(room_id=room.room_id)
            if last_match is None:
                await interaction.response.send_message(
                    "❌ 시작 세트 이전의 경기 기록을 찾을 수 없습니다.",
                    ephemeral=True
                )
                return

            recorded_ids = {
                str(player["discord_id"])
                for player in get_match_players(last_match["id"])
            }
            previous_set = all_results[start_index - 1]
            _, previous_winner, previous_mvp = previous_set
            previous_mvp_matches = (
                previous_mvp is None
                or str(last_match["mvp_discord_id"])
                == str(previous_mvp.id)
            )
            if (
                recorded_ids != player_ids
                or last_match["winner"] != previous_winner
                or not previous_mvp_matches
            ):
                await interaction.response.send_message(
                    "❌ 최근 DB 기록이 선택한 시작 세트의 직전 결과와 "
                    "일치하지 않습니다.",
                    ephemeral=True
                )
                return

            room.series_score = dict(expected_score)
            room.series_game = expected_game
            join_cog.save_rooms_state()

        await interaction.response.defer(ephemeral=True)

        completed_lines = []
        try:
            previous_match = get_last_match(room_id=room.room_id)
            previous_match_id = (
                previous_match["id"]
                if previous_match is not None
                else None
            )

            for set_name, winner, mvp_member in results_to_apply:
                mvp_id = str(mvp_member.id)
                room.match_in_progress = True
                join_cog.save_rooms_state()

                await match_cog.process_match_result(
                    interaction,
                    winner,
                    mvp_id,
                    room
                )

                saved_match = get_last_match(room_id=room.room_id)
                if (
                    saved_match is None
                    or saved_match["id"] == previous_match_id
                    or saved_match["winner"] != winner
                    or str(saved_match["mvp_discord_id"]) != mvp_id
                ):
                    raise RuntimeError(
                        f"{set_name} 결과 검증에 실패했습니다."
                    )

                previous_match_id = saved_match["id"]
                team_icon = "🔴 레드" if winner == "red" else "🔵 블루"
                completed_lines.append(
                    f"{set_name}: {team_icon} 승 / MVP {mvp_member.mention}"
                )

        except Exception:
            logger.exception(
                "BO3 누락 경기 복구 실패 | 방=%s",
                room.room_id
            )

            if room.match_transaction_active:
                rollback_transaction()
                room.match_transaction_active = False
                room.match_transaction_committed = False

                if room.transaction_series_score is not None:
                    room.series_score = dict(room.transaction_series_score)

                if room.transaction_series_game is not None:
                    room.series_game = room.transaction_series_game

                room.pending_match_token = None
                room.pending_series_score = None
                room.pending_series_game = None

            room.match_in_progress = False
            join_cog.save_rooms_state()

            await interaction.followup.send(
                "❌ 경기 복구 중 오류가 발생했습니다. "
                "현재 상태를 보존했으므로 로그를 확인한 뒤 다시 시도해주세요.",
                ephemeral=True
            )
            return

        await interaction.followup.send(
            "✅ 경기 복구가 완료되었습니다.\n"
            + "\n".join(completed_lines)
            + "\n최종 결과: 🔴 레드 2 : 1 블루",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(
        AdminMatch(bot)
    )
