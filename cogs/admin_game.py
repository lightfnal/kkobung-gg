import asyncio
import logging
import math
import os
import time
import copy

from datetime import datetime
from pathlib import Path

import discord
from discord.ext import commands

from utils.permissions import (
    is_admin,
    is_match_operator,
    send_admin_only_message,
    send_match_operator_only_message
)

from utils.cog_helper import get_join_cog
from services.tournament_service import (
    get_fixture,
    release_fixture,
    resolve_fixture,
)
from storage.sqlite_db import get_last_match
from views.join_view import EndSeriesConfirmView, SeriesRecoveryView
from config import (
    BOT_NAME,
    VERSION
)
from storage.paths import (
    BACKUP_DIR,
    DATA_DIR,
    LOG_DIR
)
from storage.sqlite_db import (
    check_database_integrity,
    get_database_schema_version,
    get_operations_event_count,
    get_operations_events
)
from storage.schema_migrations import CURRENT_SCHEMA_VERSION


logger = logging.getLogger(__name__)


def format_duration(total_seconds):
    total_seconds = max(0, int(total_seconds))
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []

    if days:
        parts.append(f"{days}일")
    if hours or days:
        parts.append(f"{hours}시간")
    if minutes or hours or days:
        parts.append(f"{minutes}분")
    parts.append(f"{seconds}초")
    return " ".join(parts)


def format_file_size(path):
    try:
        size = Path(path).stat().st_size
    except OSError:
        return "없음"

    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f}MB"
    return f"{size / 1024:.1f}KB"


def find_latest_file(directory, pattern):
    try:
        files = list(Path(directory).glob(pattern))
        return max(
            files,
            key=lambda path: path.stat().st_mtime,
            default=None
        )
    except OSError:
        return None


def describe_file_time(path):
    if path is None:
        return "없음"

    try:
        modified = datetime.fromtimestamp(
            path.stat().st_mtime
        )
        return modified.strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return "확인 실패"


def describe_datetime(value):
    if value is None:
        return "기록 없음"
    return value.strftime("%Y-%m-%d %H:%M:%S")


class AdminGame(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(
        name="시스템점검",
        description="봇, DB, 저장 경로와 내전방 상태를 점검합니다."
    )
    async def system_check(
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

        await interaction.response.defer(
            ephemeral=True
        )

        try:
            integrity_ok, integrity_result = (
                check_database_integrity()
            )
        except Exception as error:
            integrity_ok = False
            integrity_result = (
                "검사 실행 실패: "
                f"{type(error).__name__}"
            )

        data_dir_ready = (
            DATA_DIR.exists()
            and DATA_DIR.is_dir()
        )
        backup_dir_ready = (
            BACKUP_DIR.exists()
            and BACKUP_DIR.is_dir()
        )

        try:
            schema_version = get_database_schema_version()
            schema_ready = (
                schema_version == CURRENT_SCHEMA_VERSION
            )
        except Exception:
            schema_version = "확인 실패"
            schema_ready = False

        started_monotonic = getattr(
            self.bot,
            "started_monotonic",
            time.monotonic()
        )
        uptime = format_duration(
            time.monotonic() - started_monotonic
        )
        latency = getattr(
            self.bot,
            "latency",
            float("nan")
        )
        latency_text = (
            f"{latency * 1000:.0f}ms"
            if isinstance(latency, (int, float))
            and math.isfinite(latency)
            else "측정 전"
        )
        disconnect_count = getattr(
            self.bot,
            "gateway_disconnect_count",
            0
        )
        resume_count = getattr(
            self.bot,
            "gateway_resume_count",
            0
        )

        latest_internal_backup = find_latest_file(
            BACKUP_DIR,
            "blooming_*.db"
        )
        one_drive = (
            os.getenv("OneDrive")
            or os.getenv("OneDriveConsumer")
        )
        latest_external_backup = (
            find_latest_file(
                Path(one_drive) / "꼬붕봇_외부백업",
                "blooming_*.db"
            )
            if one_drive
            else None
        )
        bot_log_path = LOG_DIR / "bot.log"
        error_log_path = LOG_DIR / "error.log"

        operations_monitor = self.bot.get_cog(
            "OperationsMonitor"
        )
        monitor_loop = getattr(
            operations_monitor,
            "operations_check",
            None
        )
        monitor_running = bool(
            monitor_loop is not None
            and monitor_loop.is_running()
        )
        monitor_issues = set(getattr(
            operations_monitor,
            "current_issues",
            ()
        ))
        issue_names = {
            "database": "DB",
            "backup": "백업",
            "gateway": "Gateway"
        }
        monitor_issue_text = (
            ", ".join(
                issue_names.get(issue, issue)
                for issue in sorted(monitor_issues)
            )
            if monitor_issues
            else "없음"
        )
        try:
            operations_event_count = get_operations_event_count()
            recent_operations_events = get_operations_events(limit=1)
            recent_operations_event = (
                recent_operations_events[0]
                if recent_operations_events
                else None
            )
        except Exception:
            operations_event_count = None
            recent_operations_event = None

        if recent_operations_event is None:
            recent_event_text = (
                "기록 없음"
                if operations_event_count == 0
                else "조회 실패"
            )
        else:
            event_type_text = (
                "복구"
                if recent_operations_event["event_type"] == "recovery"
                else "경고"
            )
            event_issue_text = issue_names.get(
                recent_operations_event["issue_key"],
                recent_operations_event["issue_key"]
            )
            recent_event_text = (
                f"{event_type_text} · {event_issue_text} · "
                f"{recent_operations_event['created_at']}"
            )
        operations_event_count_text = (
            f"{operations_event_count}개"
            if operations_event_count is not None
            else "조회 실패"
        )

        rooms = (
            join_cog.room_manager
            .get_rooms()
        )

        participant_count = sum(
            len(room.players)
            for room in rooms
        )
        active_match_count = sum(
            bool(room.match_in_progress)
            for room in rooms
        )
        active_transaction_count = sum(
            bool(room.match_transaction_active)
            for room in rooms
        )
        pending_result_count = sum(
            room.pending_match_token is not None
            for room in rooms
        )

        system_ready = (
            integrity_ok
            and schema_ready
            and data_dir_ready
            and backup_dir_ready
        )

        embed = discord.Embed(
            title=f"🩺 {BOT_NAME} 시스템 점검",
            description=(
                "✅ 운영 준비 완료"
                if system_ready
                else "⚠️ 확인이 필요한 항목이 있습니다."
            ),
            color=(
                discord.Color.green()
                if system_ready
                else discord.Color.orange()
            )
        )

        embed.add_field(
            name="봇 정보",
            value=(
                f"버전: **{VERSION}**\n"
                f"실행시간: **{uptime}**\n"
                f"Discord 지연시간: **{latency_text}**\n"
                f"Gateway 끊김/복구: "
                f"**{disconnect_count}/{resume_count}회**\n"
                f"로드된 내전방: **{len(rooms)}개**"
            ),
            inline=False
        )
        embed.add_field(
            name="SQLite DB",
            value=(
                f"{'✅ 정상' if integrity_ok else '❌ 오류'}\n"
                f"검사 결과: `{integrity_result}`\n"
                f"스키마: "
                f"**{schema_version}/{CURRENT_SCHEMA_VERSION}** "
                f"{'✅' if schema_ready else '❌'}"
            ),
            inline=False
        )
        embed.add_field(
            name="백업 상태",
            value=(
                "최근 내부 백업: "
                f"**{describe_file_time(latest_internal_backup)}**\n"
                "최근 외부 백업: "
                f"**{describe_file_time(latest_external_backup)}**"
            ),
            inline=False
        )
        embed.add_field(
            name="운영 로그",
            value=(
                f"bot.log: **{format_file_size(bot_log_path)}**\n"
                f"error.log: **{format_file_size(error_log_path)}**\n"
                "마지막 오류 기록: "
                f"**{describe_file_time(error_log_path if error_log_path.exists() else None)}**"
            ),
            inline=False
        )
        embed.add_field(
            name="자동 운영 감시",
            value=(
                "상태: "
                f"**{'✅ 실행 중' if monitor_running else '❌ 중지'}**\n"
                "현재 감지 문제: "
                f"**{monitor_issue_text}**\n"
                "마지막 점검: "
                f"**{describe_datetime(getattr(operations_monitor, 'last_check_at', None))}**\n"
                "마지막 경고: "
                f"**{describe_datetime(getattr(operations_monitor, 'last_alert_at', None))}**\n"
                "마지막 복구: "
                f"**{describe_datetime(getattr(operations_monitor, 'last_recovery_at', None))}**\n"
                "저장된 이력: "
                f"**{operations_event_count_text}**\n"
                "최근 저장 기록: "
                f"**{recent_event_text}**"
            ),
            inline=False
        )
        embed.add_field(
            name="저장 경로",
            value=(
                "데이터 폴더: "
                f"{'✅' if data_dir_ready else '❌'}\n"
                "백업 폴더: "
                f"{'✅' if backup_dir_ready else '❌'}"
            ),
            inline=False
        )
        embed.add_field(
            name="현재 내전 상태",
            value=(
                f"참가자: **{participant_count}명**\n"
                f"진행 경기: **{active_match_count}개**\n"
                f"결과 트랜잭션: **{active_transaction_count}개**\n"
                f"pending 복구: **{pending_result_count}개**"
            ),
            inline=False
        )
        embed.set_footer(
            text="읽기 전용 점검이며 운영 데이터는 변경하지 않습니다."
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True
        )

    @discord.app_commands.command(
        name="내전종료",
        description="세트 결과를 보존하며 내전을 종료합니다. 종료 전 확인이 필요합니다."
    )
    async def end_game(
        self,
        interaction: discord.Interaction
    ):
        if not (
            is_admin(interaction)
            or is_match_operator(interaction)
        ):
            await send_match_operator_only_message(interaction)
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
            await self._end_game_locked(
                interaction
            )

    async def _end_game_locked(
        self,
        interaction: discord.Interaction
    ):
        if not (
            is_admin(interaction)
            or is_match_operator(interaction)
        ):
            await send_match_operator_only_message(interaction)
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
            room.match_in_progress
            or room.match_transaction_active
            or room.pending_match_token is not None
        ):
            await interaction.response.send_message(
                "❌ 경기 진행 또는 결과 저장 중에는 내전을 종료할 수 없습니다.",
                ephemeral=True
            )
            return
        if room.series_game <= 0 or room.current_teams is None:
            await interaction.response.send_message(
                "❌ 종료할 진행 중인 시리즈가 없습니다. 최소 한 세트 결과를 먼저 등록해주세요.",
                ephemeral=True
            )
            return

        score = room.series_score
        await interaction.response.send_message(
            f"현재 점수는 🔴 레드 **{score['red']} : {score['blue']}** 블루입니다.\n"
            "종료하면 세트별 경기 기록은 보존되고 참가자와 팀 상태만 초기화됩니다.",
            view=EndSeriesConfirmView(
                self.bot, room, interaction.user.id
            ),
            ephemeral=True
        )

    async def confirm_end_series(
        self,
        interaction,
        room,
        control_view=None,
        source_message=None
    ):
        join_cog = get_join_cog(self.bot)
        if join_cog is None:
            await interaction.edit_original_response(
                content="❌ 내전 관리 기능을 불러오지 못했습니다."
            )
            return

        # Do not let an end request sit behind a stuck match/result operation.
        # The user has already confirmed; report the conflict immediately.
        if room.operation_lock.locked():
            await interaction.edit_original_response(
                content=(
                    "⏳ 이 방에서 다른 경기 작업이 아직 처리 중입니다. "
                    "내전은 종료되지 않았습니다. 잠시 후 다시 눌러주세요."
                )
            )
            return
        if room.pending_match_token is not None:
            await interaction.edit_original_response(
                content=(
                    "⏳ 직전 경기 결과 저장이 아직 정리되지 않았습니다. "
                    "기록을 확인한 뒤 다시 종료해주세요."
                )
            )
            return

        async with room.operation_lock:
            if (
                room.match_in_progress
                or room.match_transaction_active
                or room.pending_match_token is not None
            ):
                await interaction.edit_original_response(
                    content="❌ 경기 진행 또는 결과 저장 중이라 종료하지 않았습니다."
                )
                return
            if room.series_game <= 0 or room.current_teams is None:
                await interaction.edit_original_response(
                    content="❌ 종료할 진행 중인 시리즈가 없습니다."
                )
                return

            last_match = get_last_match(room.room_id)
            snapshot = {
                "players": copy.deepcopy(room.players),
                "current_teams": copy.deepcopy(room.current_teams),
                "series_score": dict(room.series_score),
                "series_game": int(room.series_game),
                "tournament_id": room.tournament_id,
                "tournament_fixture_no": room.tournament_fixture_no,
                "last_match_id": int(last_match["id"]) if last_match else None,
            }
            participant_ids = set(map(str, room.players.keys()))
            participant_ids.update(
                str(user_id)
                for team in (room.current_teams or {}).values()
                for user_id in (team or {}).values()
            )
            try:
                voice = await asyncio.wait_for(
                    join_cog.move_members_to_voice_channel(
                        guild=interaction.guild,
                        user_ids=participant_ids,
                        channel_id=room.waiting_voice_channel_id
                    ),
                    timeout=15
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "내전 종료 중 음성채널 이동 시간 초과 | 방=%s",
                    room.room_id
                )
                voice = {"moved": 0, "failed": len(participant_ids)}

            tournament_notice = ""
            tournament_id = room.tournament_id
            fixture_no = room.tournament_fixture_no
            if tournament_id and fixture_no:
                red_score = int(room.series_score.get("red", 0))
                blue_score = int(room.series_score.get("blue", 0))
                if red_score == blue_score:
                    release_fixture(tournament_id, fixture_no)
                    tournament_notice = "\n미니컵 대진은 다시 진행할 수 있도록 대기 상태로 두었습니다."
                else:
                    side = "red" if red_score > blue_score else "blue"
                    fixture = get_fixture(tournament_id, fixture_no)
                    if fixture and last_match:
                        resolve_fixture(
                            tournament_id, fixture_no,
                            fixture[f"{side}_team_id"], int(last_match["id"])
                        )
                        tournament_notice = "\n미니컵 대진표에 현재 시리즈 승자를 반영했습니다."

            recruit_view = room.current_recruit_view
            if recruit_view:
                recruit_view.recruit_closed = True
                for item in recruit_view.children:
                    if isinstance(item, discord.ui.Button):
                        item.disabled = True

            room.reset_game()
            room.ended_series_snapshot = snapshot
            join_cog.save_rooms_state()

            if recruit_view and recruit_view.message:
                try:
                    await recruit_view.message.edit(
                        embed=recruit_view.create_embed(),
                        view=recruit_view
                    )
                except discord.HTTPException:
                    logger.exception("내전 종료 후 모집 버튼 갱신 실패")

            # The room is now ended and persisted. Remove the old controls
            # before attempting any channel announcement that might be slow.
            if control_view is not None:
                control_view.stop()
            if source_message is not None:
                try:
                    await source_message.edit(view=None)
                except discord.HTTPException:
                    logger.exception("내전 종료 후 이전 경기 버튼 제거 실패")

            score = snapshot["series_score"]
            content = (
                f"✅ **{room.room_name} · 내전이 종료되었습니다.**\n"
                f"기록된 세트: **{snapshot['series_game']}세트** · "
                f"현재 점수: 🔴 레드 **{score['red']} : {score['blue']}** 블루\n"
                "세트별 경기 결과는 저장되어 있습니다.\n"
                "실수로 종료했다면 관리자 또는 내전진행자가 아래 버튼으로 복구할 수 있습니다."
                f"{tournament_notice}\n"
                f"🔊 대기 음성채널 복귀: {voice.get('moved', 0)}명 이동"
            )
            try:
                output_message, _ = await join_cog.send_output_message(
                    room=room,
                    fallback_channel=interaction.channel,
                    content=content,
                    view=SeriesRecoveryView(self.bot)
                )
            except Exception:
                logger.exception(
                    "내전 종료 안내 전송 실패 | 방=%s",
                    room.room_id
                )
                output_message = None
            if output_message is None:
                try:
                    output_message = await interaction.edit_original_response(
                        content=(
                            "⚠️ 공용 채널에 올리지 못해 이 메시지에 "
                            "종료 및 복구 버튼을 표시합니다."
                        ),
                        view=SeriesRecoveryView(self.bot),
                    )
                except discord.HTTPException:
                    output_message = None
                if output_message is None:
                    join_cog.save_rooms_state()
                    try:
                        await interaction.edit_original_response(
                            content=(
                                "⚠️ 내전은 종료했고 상태도 저장했습니다. "
                                "복구 안내 메시지를 보내지 못했으니 관리자에게 알려주세요."
                            ),
                            view=None
                        )
                    except discord.HTTPException:
                        pass
                    return

            snapshot["recovery_message_id"] = str(output_message.id)
            room.ended_series_snapshot = snapshot
            join_cog.save_rooms_state()

            try:
                await interaction.edit_original_response(
                    content=(
                        f"✅ 내전을 종료했습니다. 세트 결과는 보존했습니다. "
                        f"종료 안내: <#{output_message.channel.id}>"
                    )
                )
            except discord.HTTPException:
                logger.info(
                    "내전 종료 완료 안내 갱신 생략(상호작용 만료) | 방=%s",
                    room.room_id
                )



async def setup(bot):
    await bot.add_cog(AdminGame(bot))
    bot.add_view(SeriesRecoveryView(bot))
