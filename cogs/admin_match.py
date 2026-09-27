import logging

import discord
from discord.ext import commands


logger = logging.getLogger(__name__)

from utils.permissions import (
    is_admin,
    send_admin_only_message
)

from utils.cog_helper import get_join_cog

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

from services.player_service import PlayerService


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
            await self._force_end_match_locked(
                interaction
            )

    async def _force_end_match_locked(
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

        if not room.match_in_progress:
            await interaction.response.send_message(
                "❌ 현재 진행 중인 경기가 없습니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer(
            ephemeral=True
        )

        room.match_transaction_active = True
        room.match_transaction_committed = False

        join_cog.save_rooms_state()

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

        join_cog.save_rooms_state()

        output_message, used_fallback = (
            await join_cog.send_output_message(
                room=room,
                fallback_channel=interaction.channel,
                content=(
                    f"⚠️ **{room.room_name} · 진행 중인 "
                    "경기를 강제로 종료했습니다.**\n"
                    f"방 번호: **{room.room_id}**\n\n"
                    "레이팅 및 전적 변화는 적용되지 않았습니다."
                )
            )
        )

        if output_message is None:
            confirmation_message = (
                "✅ 경기 상태는 강제로 종료했습니다.\n"
                "⚠️ 다만 종료 안내 메시지는 전송하지 "
                "못했습니다."
            )

        elif used_fallback:
            confirmation_message = (
                "✅ 경기를 강제로 종료했습니다.\n"
                "⚠️ 공용 진행 채널에 접근할 수 없어 "
                "현재 모집 채널에 안내를 표시했습니다."
            )

        else:
            confirmation_message = (
                "✅ 경기를 강제로 종료하고 공용 진행 "
                "채널에 안내를 표시했습니다."
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
            await self._delete_match_record_only_locked(
                interaction,
                경기번호
            )

    async def _delete_match_record_only_locked(
        self,
        interaction: discord.Interaction,
        경기번호: int
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

        if room.match_transaction_active:
            await interaction.response.send_message(
                "❌ 현재 이 내전 방에서 경기 결과를 "
                "처리하고 있습니다.\n"
                "잠시 후 다시 시도해주세요.",
                ephemeral=True
            )
            return

        match = get_match(
            경기번호
        )

        if match is None:
            await interaction.response.send_message(
                "❌ 해당 경기 기록이 없습니다.",
                ephemeral=True
            )
            return

        match_room_id = match["room_id"]

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

        deleted = delete_match_only(
            경기번호
        )

        if not deleted:
            raise RuntimeError(
                "경기 기록 삭제에 실패했습니다."
            )

        output_message, used_fallback = (
            await join_cog.send_output_message(
                room=room,
                fallback_channel=interaction.channel,
                content=(
                    f"🗑️ **{room.room_name} · 경기 기록 "
                    "삭제**\n"
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
                "⚠️ 다만 삭제 안내 메시지는 전송하지 "
                "못했습니다."
            )

        elif used_fallback:
            confirmation_message = (
                "✅ 경기 기록을 삭제했습니다.\n"
                "⚠️ 공용 진행 채널에 접근할 수 없어 "
                "현재 모집 채널에 안내를 표시했습니다."
            )

        else:
            confirmation_message = (
                "✅ 경기 기록을 삭제하고 공용 진행 "
                "채널에 안내를 표시했습니다."
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
            await self._cancel_match_locked(
                interaction
            )

    async def _cancel_match_locked(
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
        season_id = last_match["season_id"]

        match_players = get_match_players(
            match_id
        )

        if not match_players:
            await interaction.response.send_message(
                "❌ 최근 경기의 선수 기록을 찾을 수 없습니다.",
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

                profile = dict(
                    profile_row
                )

                profile["rating"] = (
                    match_player["rating_before"]
                )

                # 새 MMR 기록이 존재하는 경기만 복구합니다.
                # 기존 경기 기록은 값이 NULL이므로 현재 MMR을 유지합니다.
                if match_player["hidden_mmr_before"] is not None:
                    profile["hidden_mmr"] = (
                        match_player["hidden_mmr_before"]
                    )

                if match_player["placement_games_before"] is not None:
                    profile["placement_games"] = (
                        match_player["placement_games_before"]
                    )

                profile["win_streak"] = (
                    match_player["win_streak_before"]
                )

                profile["lose_streak"] = (
                    match_player["lose_streak_before"]
                )

                profile["best_win_streak"] = (
                    match_player["best_win_streak_before"]
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

                # 새 시즌 복구 기록이 있는 경기만 시즌 전적을 되돌립니다.
                if (
                    season_id is not None
                    and match_player["season_rating_before"] is not None
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

            mvp_id = last_match[
                "mvp_discord_id"
            ]

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


            output_message, used_fallback = (
                await join_cog.send_output_message(
                    room=room,
                    fallback_channel=interaction.channel,
                    content=(
                        f"↩️ **{room.room_name} · 경기 결과 "
                        "취소**\n"
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

            else:
                confirmation_message = (
                    "✅ 경기 결과를 취소하고 공용 진행 "
                    "채널에 안내를 표시했습니다."
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



async def setup(bot):
    await bot.add_cog(AdminMatch(bot))
