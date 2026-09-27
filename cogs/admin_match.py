import logging

import discord
from discord.ext import commands

from services.player_service import PlayerService

from storage.sqlite_db import (
    get_last_match,
    get_match_players,
    get_match,
    delete_last_match,
    delete_match_only,
    update_season_player_stats,
    begin_transaction,
    commit_transaction,
    rollback_transaction
)

from utils.cog_helper import get_join_cog
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
        name="경기복구",
        description="누락된 BO3 2·3세트 결과를 정상 경기 처리로 복구합니다."
    )
    @discord.app_commands.describe(
        이세트_mvp="2세트 MVP (블루팀 승리)",
        삼세트_mvp="3세트 MVP (레드팀 승리)"
    )
    async def recover_match(
        self,
        interaction: discord.Interaction,
        이세트_mvp: discord.Member,
        삼세트_mvp: discord.Member
    ):
        """특정 누락 사고의 2·3세트를 기존 정상 처리 경로로 복구합니다.

        최초 실행은 1세트 완료(레드 1:0), 중단 후 재실행은
        2세트 완료(1:1) 상태에서만 허용합니다. 기존 1세트는 수정하지
        않으며, 실제 기록은 Match.process_match_result가 담당합니다.
        """
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
                이세트_mvp,
                삼세트_mvp
            )

    async def _recover_match_locked(
        self,
        interaction: discord.Interaction,
        join_cog,
        match_cog,
        room,
        second_mvp: discord.Member,
        third_mvp: discord.Member
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

        red_ids = {
            str(user_id)
            for user_id in room.current_teams.get("red", {}).values()
        }
        blue_ids = {
            str(user_id)
            for user_id in room.current_teams.get("blue", {}).values()
        }
        player_ids = red_ids | blue_ids
        second_mvp_id = str(second_mvp.id)
        third_mvp_id = str(third_mvp.id)

        if second_mvp_id not in player_ids or third_mvp_id not in player_ids:
            await interaction.response.send_message(
                "❌ 두 MVP 모두 현재 시리즈 참가자여야 합니다.",
                ephemeral=True
            )
            return

        score = dict(room.series_score)
        game = int(room.series_game)
        initial_state = score == {"red": 1, "blue": 0} and game == 1
        resumable_state = score == {"red": 1, "blue": 1} and game == 2

        if not initial_state and not resumable_state:
            await interaction.response.send_message(
                "❌ 안전 조건이 맞지 않아 중단했습니다.\n"
                f"현재 상태: 레드 {score.get('red', 0)} : "
                f"{score.get('blue', 0)} 블루 / 완료 {game}세트",
                ephemeral=True
            )
            return

        last_match = get_last_match(room_id=room.room_id)

        if last_match is None:
            await interaction.response.send_message(
                "❌ 기존 1세트 경기 기록을 찾을 수 없습니다.",
                ephemeral=True
            )
            return

        last_players = get_match_players(last_match["id"])
        recorded_ids = {
            str(player["discord_id"])
            for player in last_players
        }

        if recorded_ids != player_ids:
            await interaction.response.send_message(
                "❌ 최근 경기 참가자와 현재 팀 구성이 달라 중단했습니다.",
                ephemeral=True
            )
            return

        if initial_state and last_match["winner"] != "red":
            await interaction.response.send_message(
                "❌ 최근 기록이 1세트 레드 승리와 일치하지 않습니다.",
                ephemeral=True
            )
            return

        if resumable_state and (
            last_match["winner"] != "blue"
            or str(last_match["mvp_discord_id"]) != second_mvp_id
        ):
            await interaction.response.send_message(
                "❌ 기록된 2세트 결과가 지정한 블루 승/MVP와 달라 중단했습니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        try:
            if initial_state:
                previous_match_id = last_match["id"]
                room.match_in_progress = True
                join_cog.save_rooms_state()

                await match_cog.process_match_result(
                    interaction,
                    "blue",
                    second_mvp_id,
                    room
                )

                second_match = get_last_match(room_id=room.room_id)
                if (
                    second_match is None
                    or second_match["id"] == previous_match_id
                    or second_match["winner"] != "blue"
                    or str(second_match["mvp_discord_id"]) != second_mvp_id
                    or room.series_score != {"red": 1, "blue": 1}
                    or int(room.series_game) != 2
                ):
                    raise RuntimeError("2세트 결과 검증에 실패했습니다.")

            room.match_in_progress = True
            join_cog.save_rooms_state()

            await match_cog.process_match_result(
                interaction,
                "red",
                third_mvp_id,
                room
            )

            third_match = get_last_match(room_id=room.room_id)
            if (
                third_match is None
                or third_match["winner"] != "red"
                or str(third_match["mvp_discord_id"]) != third_mvp_id
            ):
                raise RuntimeError("3세트 결과 검증에 실패했습니다.")

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
            "2세트: 🔵 블루 승 / "
            f"MVP {second_mvp.mention}\n"
            "3세트: 🔴 레드 승 / "
            f"MVP {third_mvp.mention}\n"
            "최종 결과: 🔴 레드 2 : 1 블루",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(
        AdminMatch(bot)
    )
