import asyncio
import logging
import copy
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
    rollback_transaction,
    get_match_champion_progress
)

from utils.cog_helper import get_join_cog
from views.join_view import (
    JoinView,
    TeamModeView,
    refresh_match_controls_at_bottom
)
from utils.permissions import (
    is_admin,
    send_admin_only_message,
    is_match_operator,
    send_match_operator_only_message
)
from services.tournament_service import reopen_fixture


logger = logging.getLogger(__name__)


class AdminMatch(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self._guild_commands_synced = False

    @discord.app_commands.command(
        name="단판재편성",
        description="현재 BO5를 여기서 끝내고 같은 10명으로 매 판 팀을 다시 편성합니다."
    )
    async def start_single_draft_mode(self, interaction: discord.Interaction):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(self.bot)
        if join_cog is None or not await join_cog.require_room(interaction):
            return

        room = join_cog.active_room
        await interaction.response.defer(ephemeral=True, thinking=True)

        if room.team_generation_lock.locked():
            await interaction.followup.send(
                "⏳ 팀 편성·경매·드래프트가 진행 중입니다. 끝난 뒤 다시 실행해주세요.",
                ephemeral=True
            )
            return

        try:
            await asyncio.wait_for(
                room.team_generation_lock.acquire(),
                timeout=0.5
            )
        except asyncio.TimeoutError:
            await interaction.followup.send(
                "⏳ 팀 편성 작업이 시작됐습니다. 잠시 뒤 다시 실행해주세요.",
                ephemeral=True
            )
            return

        operation_lock_acquired = False
        state_snapshot = None
        try:
            await asyncio.wait_for(room.operation_lock.acquire(), timeout=5)
            operation_lock_acquired = True

            if room.single_draft_mode_active:
                await interaction.followup.send(
                    "이미 연속 단판 재편성 모드입니다. 모집창의 `🎲 팀 생성` 버튼을 눌러주세요.",
                    ephemeral=True
                )
                return
            if room.tournament_id is not None:
                await interaction.followup.send(
                    "❌ 미니컵 대진 경기는 단판 재편성 모드로 전환할 수 없습니다.",
                    ephemeral=True
                )
                return
            if room.match_in_progress or room.match_transaction_active or room.pending_match_token is not None:
                await interaction.followup.send(
                    "❌ 먼저 현재 경기 결과 저장을 마쳐주세요.",
                    ephemeral=True
                )
                return
            if room.mvp_vote_in_progress:
                await interaction.followup.send(
                    "❌ MVP 투표가 끝난 뒤 단판 재편성을 시작해주세요.",
                    ephemeral=True
                )
                return
            if room.series_game > 0:
                previous_match = get_last_match(room.room_id)
                if previous_match is not None:
                    progress = get_match_champion_progress(previous_match["id"])
                    if (
                        progress["total_count"] > 0
                        and progress["completed_count"] < progress["total_count"]
                    ):
                        missing = progress["total_count"] - progress["completed_count"]
                        await interaction.followup.send(
                            f"⏳ 직전 경기의 챔피언 입력이 {missing}명 남았습니다. "
                            "입력을 마친 뒤 단판 재편성을 시작해주세요.",
                            ephemeral=True
                        )
                        return
            if room.current_teams is None or room.series_game < 1:
                await interaction.followup.send(
                    "❌ BO5 세트 결과가 한 번 이상 저장된 진행 중인 내전에서 사용할 수 있습니다.",
                    ephemeral=True
                )
                return
            if room.player_limit != MAX_PLAYERS or len(room.players) != MAX_PLAYERS:
                await interaction.followup.send(
                    f"❌ 참가자 {MAX_PLAYERS}명이 모두 유지된 10인 내전에서만 사용할 수 있습니다.",
                    ephemeral=True
                )
                return
            recruit_view = room.current_recruit_view

            previous_control = room.current_match_control_view
            previous_score = dict(room.series_score)
            previous_game_count = room.series_game
            state_snapshot = {
                "single_draft_mode_active": room.single_draft_mode_active,
                "current_teams": room.current_teams,
                "current_balance_prediction": room.current_balance_prediction,
                "series_score": dict(room.series_score),
                "series_game": room.series_game,
                "match_in_progress": room.match_in_progress,
                "ended_series_snapshot": room.ended_series_snapshot,
                "current_recruit_view": room.current_recruit_view,
                "current_match_control_view": room.current_match_control_view,
                "recruit_closed": (
                    recruit_view.recruit_closed
                    if recruit_view is not None else None
                ),
                "team_generating": (
                    recruit_view.team_generating
                    if recruit_view is not None else None
                ),
                "button_disabled": [
                    item.disabled
                    for item in recruit_view.children
                    if isinstance(item, discord.ui.Button)
                ] if recruit_view is not None else None,
            }

            # Keep all ten registered players. Only discard the current BO5
            # teams and score so the next match starts as an independent game.
            room.single_draft_mode_active = True
            room.current_teams = None
            room.current_balance_prediction = None
            room.series_score = {"red": 0, "blue": 0}
            room.series_game = 0
            room.match_in_progress = False
            room.ended_series_snapshot = None
            room.current_match_control_view = None
            if recruit_view is not None:
                recruit_view.recruit_closed = True
                recruit_view.team_generating = False
                for item in recruit_view.children:
                    if isinstance(item, discord.ui.Button):
                        item.disabled = item.custom_id not in (
                            "inhouse_list",
                            "inhouse_reset",
                            "inhouse_make_teams"
                        )
                recruit_view.make_teams_button.disabled = False
            else:
                # The recruitment View itself is not persisted across process
                # restarts. Rebuild it while holding the room operation lock.
                recruit_view = JoinView(join_cog)
                room.current_recruit_view = recruit_view
                recruit_view.recruit_closed = True
                for item in recruit_view.children:
                    if isinstance(item, discord.ui.Button):
                        item.disabled = item.custom_id not in (
                            "inhouse_list",
                            "inhouse_reset",
                            "inhouse_make_teams"
                        )
                recruit_view.make_teams_button.disabled = False
            join_cog.save_rooms_state()

        except asyncio.TimeoutError:
            await interaction.followup.send(
                "⏳ 이 방에서 다른 처리가 진행 중입니다. 아무 상태도 바꾸지 않았으니 잠시 후 다시 실행해주세요.",
                ephemeral=True
            )
            return
        except Exception:
            logger.exception("연속 단판 재편성 시작 실패 | 방=%s", room.room_id)
            if state_snapshot is not None:
                room.single_draft_mode_active = state_snapshot["single_draft_mode_active"]
                room.current_teams = state_snapshot["current_teams"]
                room.current_balance_prediction = state_snapshot["current_balance_prediction"]
                room.series_score = state_snapshot["series_score"]
                room.series_game = state_snapshot["series_game"]
                room.match_in_progress = state_snapshot["match_in_progress"]
                room.ended_series_snapshot = state_snapshot["ended_series_snapshot"]
                room.current_recruit_view = state_snapshot["current_recruit_view"]
                room.current_match_control_view = state_snapshot["current_match_control_view"]
                if recruit_view is not None:
                    recruit_view.recruit_closed = state_snapshot["recruit_closed"]
                    recruit_view.team_generating = state_snapshot["team_generating"]
                    button_states = iter(state_snapshot["button_disabled"])
                    for item in recruit_view.children:
                        if isinstance(item, discord.ui.Button):
                            item.disabled = next(button_states)
                try:
                    join_cog.save_rooms_state()
                except Exception:
                    logger.exception(
                        "연속 단판 전환 실패 후 상태 복구 저장도 실패 | 방=%s",
                        room.room_id
                    )
            await interaction.followup.send(
                "❌ 단판 재편성을 시작하지 못했습니다. 방 상태는 Render 로그에서 확인해주세요.",
                ephemeral=True
            )
            return
        finally:
            if operation_lock_acquired:
                room.operation_lock.release()
            room.team_generation_lock.release()

        if recruit_view.message is None:
            # A restart loses Discord View objects, while the roster and mode
            # are persisted. Recreate the fixed-roster control message on demand.
            try:
                recruit_view.message = await interaction.followup.send(
                    embed=recruit_view.create_embed(),
                    view=recruit_view,
                    ephemeral=False,
                    wait=True
                )
            except discord.HTTPException:
                logger.exception("재시작 후 연속 단판 모집창 복구 실패 | 방=%s", room.room_id)
        else:
            try:
                await recruit_view.message.edit(
                    embed=recruit_view.create_embed(),
                    view=recruit_view
                )
            except discord.HTTPException:
                logger.exception("연속 단판 모집창 갱신 실패 | 방=%s", room.room_id)

        if previous_control is not None:
            previous_control.stop()
            if previous_control.team_message is not None:
                try:
                    await previous_control.team_message.edit(view=None)
                except discord.HTTPException:
                    logger.info(
                        "단판 재편성 전 기존 경기 버튼 제거 실패 | 방=%s",
                        room.room_id
                    )

        try:
            await join_cog.send_output_message(
                room=room,
                fallback_channel=interaction.channel,
                content=(
                    f"🔄 **{room.room_name} · 연속 단판 재편성 시작**\n"
                    f"중단한 BO5 점수: 🔴 {previous_score['red']} : "
                    f"{previous_score['blue']} 🔵 · 저장된 경기 {previous_game_count}판\n"
                    "이미 등록된 경기 기록은 유지하고, 같은 10명으로 다음 판 팀을 다시 편성합니다.\n"
                    "매 경기 결과는 독립 단판으로 기록됩니다. 종료하려면 "
                    "`/내전초기화종료`를 실행해주세요."
                )
            )
        except Exception:
            logger.exception("연속 단판 재편성 안내 전송 실패 | 방=%s", room.room_id)

        await interaction.followup.send(
            "BO5를 현재 판에서 마무리했습니다. 다음 편성 방식을 선택하세요.",
            view=TeamModeView(recruit_view),
            ephemeral=True
        )

    @commands.Cog.listener()
    async def on_ready(self):
        """전역 명령 전파를 기다리지 않고 현재 서버에 즉시 반영합니다."""
        if self._guild_commands_synced:
            return

        self._guild_commands_synced = True

        for guild in self.bot.guilds:
            try:
                self.bot.tree.copy_global_to(guild=guild)
                synced = await self.bot.tree.sync(guild=guild)
                logger.info(
                    "서버 슬래시 명령어 즉시 동기화 완료 | "
                    "서버=%s(%s) | 명령어=%s개",
                    guild.name,
                    guild.id,
                    len(synced)
                )
                for command in synced:
                    logger.info(
                        "서버 동기화 명령어 | 서버=%s | /%s",
                        guild.id,
                        command.name
                    )
            except Exception:
                logger.exception(
                    "서버 슬래시 명령어 즉시 동기화 실패 | "
                    "서버=%s(%s)",
                    guild.name,
                    guild.id
                )

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
        name="경기삭제",
        description="경기 번호를 지정해 해당 경기 결과와 레이팅 반영을 취소합니다."
    )
    @discord.app_commands.describe(
        경기번호="삭제할 경기 번호 (해당 방의 가장 최근 경기만 가능)"
    )
    async def delete_match_by_number(
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
            match = get_match(경기번호)

            if match is None:
                await interaction.response.send_message(
                    "❌ 해당 경기 기록이 없습니다.",
                    ephemeral=True
                )
                return

            if str(match.get("room_id")) != str(room.room_id):
                await interaction.response.send_message(
                    "❌ 현재 내전 방의 경기 기록이 아닙니다.",
                    ephemeral=True
                )
                return

            latest_match = get_last_match(room_id=room.room_id)

            if latest_match is None:
                await interaction.response.send_message(
                    "❌ 이 내전 방에 삭제할 경기 기록이 없습니다.",
                    ephemeral=True
                )
                return

            if int(latest_match["id"]) != int(경기번호):
                await interaction.response.send_message(
                    "❌ 레이팅과 전적을 정확히 복구하려면 해당 방의 "
                    "가장 최근 경기만 삭제할 수 있습니다.\n"
                    f"삭제를 요청한 경기: **#{경기번호}**\n"
                    f"현재 가장 최근 경기: **#{latest_match['id']}**\n"
                    "뒤에 진행된 경기부터 차례대로 삭제한 뒤 다시 시도해주세요.",
                    ephemeral=True
                )
                return

            await self._cancel_match_locked(
                interaction,
                room
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

    async def reopen_match_result(
        self,
        interaction,
        match_id,
        room,
        control_view,
        result_message
    ):
        """취소 후 같은 세트의 레드/블루 승리 버튼을 다시 엽니다."""
        if not is_match_operator(interaction):
            await send_match_operator_only_message(interaction)
            return

        join_cog = get_join_cog(self.bot)
        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        async with room.operation_lock:
            await self._cancel_match_locked(
                interaction,
                room,
                reopen_context={
                    "control_view": control_view,
                    "team_message": control_view.team_message,
                    "result_message": result_message
                },
                expected_match_id=match_id
            )

    async def _cancel_match_locked(
        self,
        interaction: discord.Interaction,
        room,
        reopen_context=None,
        expected_match_id=None
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

        if (
            expected_match_id is not None
            and int(last_match["id"]) != int(expected_match_id)
        ):
            await interaction.response.send_message(
                "❌ 이 결과 뒤에 다른 경기가 저장되어 다시 열 수 없습니다. "
                "레이팅을 안전하게 복구하려면 최신 결과부터 차례로 취소해주세요.",
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

            reopen_warning = ""
            if reopen_context is not None:
                control_view = reopen_context["control_view"]
                room.players = copy.deepcopy(
                    control_view.players_snapshot
                )
                room.current_teams = copy.deepcopy(
                    control_view.teams_snapshot
                )
                room.series_score = dict(
                    control_view.series_score_snapshot
                )
                room.series_game = control_view.series_game_snapshot
                room.tournament_id = getattr(
                    control_view, "tournament_id_snapshot", None
                )
                room.tournament_fixture_no = getattr(
                    control_view, "tournament_fixture_no_snapshot", None
                )
                if room.tournament_id and room.tournament_fixture_no:
                    try:
                        reopen_fixture(
                            room.tournament_id,
                            room.tournament_fixture_no
                        )
                    except Exception:
                        logger.exception(
                            "결과 취소 후 미니컵 대진표 되돌리기 실패 | 대회=%s | 경기=%s",
                            room.tournament_id,
                            room.tournament_fixture_no
                        )
                        reopen_warning += (
                            "\n⚠️ 대진표 되돌리기에도 실패했습니다. "
                            "대회 상태를 확인해주세요."
                        )
                room.match_in_progress = True
                room.mvp_vote_in_progress = False
                control_view.teams_reference = room.current_teams
                join_cog.activate_room(room)

                try:
                    await refresh_match_controls_at_bottom(
                        join_cog,
                        room,
                        reopen_context["team_message"],
                        control_view,
                        stage="reselect"
                    )
                except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                    logger.exception(
                        "승리팀 재선택 버튼을 원래 메시지에 복구하지 못함 | 방=%s",
                        room.room_id
                    )
                    reopen_warning = (
                        "\n⚠️ 원래 팀 메시지에 버튼을 다시 붙이지 못했습니다. "
                        "경기 상태는 복구했으니 관리자에게 알려주세요."
                    )

                result_message = reopen_context.get("result_message")
                if result_message is not None:
                    try:
                        await result_message.edit(
                            content=(
                                f"↩️ **경기 #{match_id} 결과가 취소되었습니다.**\n"
                                "승리팀을 다시 선택할 수 있도록 원래 팀 안내 메시지의 "
                                "버튼을 열었습니다."
                            ),
                            embed=None,
                            view=None
                        )
                    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                        logger.info(
                            "취소된 결과 카드의 챔피언 입력 버튼 제거 실패 | 경기=%s",
                            match_id
                        )

                join_cog.save_rooms_state()

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
                        "배치 경기 수, 승패, 연승·연패 기록이 복구되었습니다."
                        + (
                            "\n해당 세트의 승리팀 선택을 다시 열었습니다. "
                            "원래 팀 안내 메시지에서 레드팀 또는 블루팀 승리를 선택해주세요."
                            if reopen_context is not None else ""
                        )
                        + reopen_warning
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
        description="관리자가 선택한 실제 선수들을 내전 방에 한 번에 참가시킵니다."
    )
    async def admin_bulk_join(
        self,
        interaction: discord.Interaction,
        참가자1: discord.Member,
        참가자2: Optional[discord.Member] = None,
        참가자3: Optional[discord.Member] = None,
        참가자4: Optional[discord.Member] = None,
        참가자5: Optional[discord.Member] = None,
        참가자6: Optional[discord.Member] = None,
        참가자7: Optional[discord.Member] = None,
        참가자8: Optional[discord.Member] = None,
        참가자9: Optional[discord.Member] = None,
        참가자10: Optional[discord.Member] = None
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

        members = [member for member in [
            참가자1, 참가자2, 참가자3, 참가자4, 참가자5,
            참가자6, 참가자7, 참가자8, 참가자9, 참가자10
        ] if member is not None]
        member_ids = [str(member.id) for member in members]

        if len(set(member_ids)) != len(member_ids):
            await interaction.response.send_message(
                "❌ 같은 참가자를 두 번 선택할 수 없습니다.",
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
            + "\n\n빈 자리는 `/테스트참가자생성`으로 채울 수 있습니다.",
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
        name="관리자팀id지정",
        description="실제·테스트 참가자의 Discord ID로 팀과 포지션을 지정합니다."
    )
    async def admin_assign_teams_by_id(
        self,
        interaction: discord.Interaction,
        레드_top: str,
        레드_jungle: str,
        레드_mid: str,
        레드_adc: str,
        레드_support: str,
        블루_top: str,
        블루_jungle: str,
        블루_mid: str,
        블루_adc: str,
        블루_support: str
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

        def normalize_id(value):
            normalized = value.strip()
            if normalized.startswith("<@") and normalized.endswith(">"):
                normalized = normalized[2:-1]
            if normalized.startswith("!"):
                normalized = normalized[1:]
            return normalized

        red_ids = [
            normalize_id(value)
            for value in [
                레드_top, 레드_jungle, 레드_mid, 레드_adc, 레드_support
            ]
        ]
        blue_ids = [
            normalize_id(value)
            for value in [
                블루_top, 블루_jungle, 블루_mid, 블루_adc, 블루_support
            ]
        ]
        selected_ids = set(red_ids + blue_ids)
        room = join_cog.active_room

        if (
            len(selected_ids) != MAX_PLAYERS
            or not all(user_id.isdigit() for user_id in selected_ids)
        ):
            await interaction.response.send_message(
                "❌ 서로 다른 10개의 Discord ID 또는 멘션을 입력해주세요.",
                ephemeral=True
            )
            return

        if selected_ids != set(room.players.keys()):
            missing = set(room.players.keys()) - selected_ids
            unknown = selected_ids - set(room.players.keys())
            details = []
            if missing:
                details.append("누락: " + ", ".join(sorted(missing)))
            if unknown:
                details.append("명단에 없음: " + ", ".join(sorted(unknown)))
            await interaction.response.send_message(
                "❌ 입력한 ID 10개가 현재 참가 명단과 일치하지 않습니다.\n"
                + "\n".join(details),
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
                "red": dict(zip(positions, red_ids)),
                "blue": dict(zip(positions, blue_ids))
            }
            room.last_team_signature = None
            join_cog.save_rooms_state()

        await interaction.response.send_message(
            "✅ ID 기반 팀 지정이 완료되었습니다.\n\n"
            "🔴 레드팀\n"
            + "\n".join(
                f"{position}: <@{user_id}> (`{user_id}`)"
                for position, user_id in zip(positions, red_ids)
            )
            + "\n\n🔵 블루팀\n"
            + "\n".join(
                f"{position}: <@{user_id}> (`{user_id}`)"
                for position, user_id in zip(positions, blue_ids)
            ),
            ephemeral=True
        )

    @discord.app_commands.command(
        name="경기복구",
        description="누락된 BO5 결과를 선택한 세트부터 정상 처리로 복구합니다."
    )
    async def recover_match(
        self,
        interaction: discord.Interaction,
        시작세트: Literal["1세트", "2세트", "3세트", "4세트", "5세트"]
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
                시작세트
            )

    async def _recover_match_locked(
        self,
        interaction: discord.Interaction,
        join_cog,
        match_cog,
        room,
        start_set: str
    ):
        if room.match_transaction_active:
            await interaction.response.send_message(
                "❌ 현재 경기 결과를 처리 중입니다. 잠시 후 다시 시도해주세요.",
                ephemeral=True
            )
            return

        if room.mvp_vote_in_progress or room.match_in_progress:
            await interaction.response.send_message(
                "❌ 진행 중인 경기가 있어 복구할 수 없습니다.",
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

        # 복구 전용 기본 기록 순서입니다. 저장된 DB 경기와 참가자 검증 후
        # 선택한 세트부터 정상 경기 결과 처리 경로를 다시 실행합니다.
        all_results = [
            ("1세트", "red"),
            ("2세트", "blue"),
            ("3세트", "red"),
            ("4세트", "blue"),
            ("5세트", "red")
        ]
        start_index = {
            "1세트": 0,
            "2세트": 1,
            "3세트": 2,
            "4세트": 3,
            "5세트": 4
        }[start_set]
        results_to_apply = all_results[start_index:]
        expected_states = {
            "1세트": ({"red": 0, "blue": 0}, 0),
            "2세트": ({"red": 1, "blue": 0}, 1),
            "3세트": ({"red": 1, "blue": 1}, 2),
            "4세트": ({"red": 2, "blue": 1}, 3),
            "5세트": ({"red": 2, "blue": 2}, 4)
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
            _, previous_winner = previous_set
            if (
                recorded_ids != player_ids
                or last_match["winner"] != previous_winner
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

            for set_name, winner in results_to_apply:
                room.match_in_progress = True
                join_cog.save_rooms_state()

                await match_cog.process_match_result(
                    interaction,
                    winner,
                    room
                )

                saved_match = get_last_match(room_id=room.room_id)
                if (
                    saved_match is None
                    or saved_match["id"] == previous_match_id
                    or saved_match["winner"] != winner
                ):
                    raise RuntimeError(
                        f"{set_name} 결과 검증에 실패했습니다."
                    )

                previous_match_id = saved_match["id"]
                team_icon = "🔴 레드" if winner == "red" else "🔵 블루"
                completed_lines.append(
                    f"{set_name}: {team_icon} 승"
                )

        except Exception:
            logger.exception(
                "BO5 누락 경기 복구 실패 | 방=%s",
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
            + "\n최종 결과: 🔴 레드 3 : 2 블루 (복구 기본 기록 순서 기준)",
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(
        AdminMatch(bot)
    )
