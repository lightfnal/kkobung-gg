import math
import os
import time

from datetime import datetime
from pathlib import Path

import discord
from discord.ext import commands

from utils.permissions import (
    is_admin,
    send_admin_only_message
)

from utils.cog_helper import get_join_cog
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
        active_mvp_count = sum(
            bool(room.mvp_vote_in_progress)
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
                f"MVP 투표: **{active_mvp_count}개**\n"
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
        description="현재 내전을 종료하고 참가자와 팀을 초기화합니다."
    )
    async def end_game(
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
            await self._end_game_locked(
                interaction
            )

    async def _end_game_locked(
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

        await interaction.response.defer(
            ephemeral=True
        )


        # 참가자 정보를 초기화하기 전에 대기 음성채널로 복귀시킵니다.
        participant_ids = set(
            room.players.keys()
        )

        if room.current_teams is not None:
            participant_ids.update(
                str(user_id)
                for team
                in room.current_teams.values()
                for user_id
                in team.values()
            )

        waiting_voice_result = (
            await join_cog.move_members_to_voice_channel(
                guild=interaction.guild,
                user_ids=participant_ids,
                channel_id=room.waiting_voice_channel_id
            )
        )

        waiting_voice_parts = [
            f"{waiting_voice_result['moved']}명 이동"
        ]

        if waiting_voice_result["already_connected"]:
            waiting_voice_parts.append(
                f"{waiting_voice_result['already_connected']}명 "
                "이미 위치"
            )

        if waiting_voice_result["not_connected"]:
            waiting_voice_parts.append(
                f"{waiting_voice_result['not_connected']}명 "
                "음성 미접속"
            )

        if waiting_voice_result["failed"]:
            waiting_voice_parts.append(
                f"{waiting_voice_result['failed']}명 "
                "이동 실패"
            )

        waiting_voice_text = ", ".join(
            waiting_voice_parts
        )

        if waiting_voice_result["channel_missing"]:
            voice_status_message = (
                "\n\n⚠️ 대기 음성채널이 설정되지 않았거나 "
                "삭제되어 자동 복귀를 완료하지 못했습니다.\n"
                f"처리 결과: {waiting_voice_text}"
            )

        else:
            voice_status_message = (
                "\n\n🔊 대기 음성채널 복귀: "
                f"{waiting_voice_text}"
            )

        recruit_view = room.current_recruit_view
        room.reset_game()

        if recruit_view:
            recruit_view.recruit_closed = True

            for item in recruit_view.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True

            if recruit_view.message:
                try:
                    await recruit_view.message.edit(
                        embed=recruit_view.create_embed(),
                        view=recruit_view
                    )
                except discord.HTTPException:
                    pass

        join_cog.save_rooms_state()

        output_message, used_fallback = (
            await join_cog.send_output_message(
                room=room,
                fallback_channel=interaction.channel,
                content=(
                    f"✅ **{room.room_name} · 내전이 "
                    "종료되었습니다.**\n"
                    f"방 번호: **{room.room_id}**\n\n"
                    "참가자, 팀, 경기 상태와 시리즈 점수가 "
                    "모두 초기화되었습니다."
                    f"{voice_status_message}"
                )
            )
        )

        if output_message is None:
            confirmation_message = (
                "✅ 내전 상태는 정상적으로 초기화됐습니다.\n"
                "⚠️ 다만 종료 안내 메시지를 전송하지 "
                "못했습니다.\n"
                "공용 진행 채널과 모집 채널에서 꼬붕봇의 "
                "`채널 보기`와 `메시지 보내기` "
                "권한을 확인해주세요."
            )

        elif used_fallback:
            confirmation_message = (
                "✅ 내전 상태를 정상적으로 초기화했습니다.\n"
                "⚠️ 공용 진행 채널에 접근할 수 없어 "
                "현재 모집 채널에 종료 안내를 표시했습니다."
            )

        elif (
            output_message.channel.id
            == interaction.channel_id
        ):
            confirmation_message = (
                "✅ 내전을 종료하고 현재 채널에 "
                "안내를 표시했습니다."
            )

        else:
            confirmation_message = (
                "✅ 내전을 종료하고 공용 진행 채널에 "
                "안내를 표시했습니다.\n"
                f"진행 채널: "
                f"<#{output_message.channel.id}>"
            )

        await interaction.followup.send(
            confirmation_message,
            ephemeral=True
        )



async def setup(bot):
    await bot.add_cog(AdminGame(bot))
