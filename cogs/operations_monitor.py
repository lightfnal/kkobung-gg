import logging
import time
import csv
import io
from datetime import datetime
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands, tasks

from config import (
    ADMIN_ALERT_CHANNEL_ID,
    ADMIN_IDS,
    BACKUP_STALE_HOURS,
    GATEWAY_DISCONNECT_ALERT_COUNT,
    GATEWAY_DISCONNECT_WINDOW_MINUTES,
    OPERATIONS_ALERT_COOLDOWN_SECONDS,
    OPERATIONS_CHECK_INTERVAL_SECONDS,
    OPERATIONS_EVENT_RETENTION_COUNT
)
from storage.paths import BACKUP_DIR
from storage.sqlite_db import (
    check_database_integrity,
    get_all_operations_events,
    get_operations_events,
    record_operations_event
)
from utils.permissions import is_admin, send_admin_only_message


logger = logging.getLogger(__name__)


class OperationsMonitor(commands.Cog):
    """운영 장애를 주기적으로 감지해 관리자에게 알립니다."""

    def __init__(self, bot):
        self.bot = bot
        self.last_alert_times = {}
        self.notified_issues = set()
        self.current_issues = set()
        self.last_check_at = None
        self.last_alert_at = None
        self.last_recovery_at = None
        self.restore_state_from_history()
        self.operations_check.change_interval(
            seconds=OPERATIONS_CHECK_INTERVAL_SECONDS
        )
        self.operations_check.start()

    def cog_unload(self):
        self.operations_check.cancel()

    def restore_state_from_history(self):
        """재시작 전 마지막 경고 상태와 쿨다운을 DB에서 복원합니다."""

        try:
            events = get_all_operations_events()
        except Exception:
            logger.exception("운영 감시 상태 DB 복원 실패")
            return

        active_issues = set()
        latest_alert_by_issue = {}

        for event in events:
            try:
                created_at = datetime.strptime(
                    event["created_at"],
                    "%Y-%m-%d %H:%M:%S"
                )
            except (TypeError, ValueError):
                logger.warning(
                    "운영 이력 시각 형식 오류 | 기록=%s",
                    event.get("id")
                )
                continue

            issue_key = event["issue_key"]
            if event["event_type"] == "alert":
                active_issues.add(issue_key)
                latest_alert_by_issue[issue_key] = created_at
                self.last_alert_at = created_at
            elif event["event_type"] == "recovery":
                active_issues.discard(issue_key)
                latest_alert_by_issue.pop(issue_key, None)
                self.last_recovery_at = created_at

        self.notified_issues = active_issues
        now_datetime = datetime.now()
        now_monotonic = time.monotonic()

        for issue_key in active_issues:
            alerted_at = latest_alert_by_issue.get(issue_key)
            if alerted_at is None:
                continue

            elapsed_seconds = max(
                0,
                (now_datetime - alerted_at).total_seconds()
            )
            if elapsed_seconds < OPERATIONS_ALERT_COOLDOWN_SECONDS:
                self.last_alert_times[issue_key] = (
                    now_monotonic - elapsed_seconds
                )

        if events:
            logger.info(
                "운영 감시 상태 DB 복원 완료 | 활성문제=%s | 이력=%s",
                ",".join(sorted(active_issues)) or "없음",
                len(events)
            )

    def find_latest_backup(self):
        backup_dir = Path(BACKUP_DIR)
        if not backup_dir.is_dir():
            return None

        backups = list(backup_dir.glob("blooming_*.db"))
        return (
            max(backups, key=lambda path: path.stat().st_mtime)
            if backups
            else None
        )

    def collect_issues(self):
        issues = {}

        try:
            integrity_ok, integrity_result = check_database_integrity()
            if not integrity_ok:
                issues["database"] = (
                    "SQLite DB 무결성 검사에 실패했습니다.\n"
                    f"결과: `{integrity_result}`"
                )
        except Exception as error:
            logger.exception("운영 점검 중 DB 무결성 검사 실패")
            issues["database"] = (
                "SQLite DB 무결성 검사를 실행하지 못했습니다.\n"
                f"오류: `{type(error).__name__}`"
            )

        latest_backup = self.find_latest_backup()
        if latest_backup is None:
            issues["backup"] = "내부 DB 백업 파일이 없습니다."
        else:
            backup_age_seconds = time.time() - latest_backup.stat().st_mtime
            if backup_age_seconds > BACKUP_STALE_HOURS * 3600:
                age_hours = backup_age_seconds / 3600
                issues["backup"] = (
                    f"최근 내부 DB 백업이 **{age_hours:.1f}시간 전**입니다.\n"
                    f"기준: {BACKUP_STALE_HOURS}시간 이내"
                )

        cutoff = time.monotonic() - (
            GATEWAY_DISCONNECT_WINDOW_MINUTES * 60
        )
        disconnect_times = getattr(
            self.bot,
            "gateway_disconnect_times",
            ()
        )
        recent_disconnects = sum(
            disconnected_at >= cutoff
            for disconnected_at in disconnect_times
        )
        if recent_disconnects >= GATEWAY_DISCONNECT_ALERT_COUNT:
            issues["gateway"] = (
                f"최근 {GATEWAY_DISCONNECT_WINDOW_MINUTES}분 동안 Discord "
                f"Gateway 연결이 **{recent_disconnects}회** 끊겼습니다."
            )

        return issues

    def should_send_alert(self, issue_key):
        now = time.monotonic()
        last_sent = self.last_alert_times.get(issue_key)
        if (
            last_sent is not None
            and now - last_sent < OPERATIONS_ALERT_COOLDOWN_SECONDS
        ):
            return False

        return True

    async def resolve_alert_targets(self):
        if ADMIN_ALERT_CHANNEL_ID is not None:
            channel = self.bot.get_channel(ADMIN_ALERT_CHANNEL_ID)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(
                        ADMIN_ALERT_CHANNEL_ID
                    )
                except (discord.HTTPException, discord.NotFound, discord.Forbidden):
                    logger.exception(
                        "운영 경고 채널을 찾지 못했습니다 | 채널=%s",
                        ADMIN_ALERT_CHANNEL_ID
                    )
            if channel is not None and hasattr(channel, "send"):
                return [channel]

        targets = []
        for admin_id in ADMIN_IDS:
            user = self.bot.get_user(admin_id)
            if user is None:
                try:
                    user = await self.bot.fetch_user(admin_id)
                except (discord.HTTPException, discord.NotFound):
                    logger.exception(
                        "운영 경고 관리자를 찾지 못했습니다 | 사용자=%s",
                        admin_id
                    )
                    continue
            targets.append(user)

        return targets

    async def send_alert(
        self,
        issue_key,
        message,
        title="🚨 꼬붕봇 운영 이상 감지",
        color=None,
        is_recovery=False
    ):
        embed = discord.Embed(
            title=title,
            description=message,
            color=color or discord.Color.red()
        )
        embed.set_footer(
            text=f"문제 구분: {issue_key} · /시스템점검으로 상세 확인"
        )

        targets = await self.resolve_alert_targets()
        if not targets:
            logger.error(
                "운영 경고를 보낼 대상이 없습니다 | 문제=%s",
                issue_key
            )
            return False

        sent = False
        for target in targets:
            try:
                await target.send(embed=embed)
                sent = True
            except discord.HTTPException:
                logger.exception(
                    "운영 경고 전송 실패 | 문제=%s | 대상=%s",
                    issue_key,
                    getattr(target, "id", "알 수 없음")
                )

        if sent:
            if is_recovery:
                self.last_recovery_at = datetime.now()
                logger.info(
                    "운영 이상 복구 알림 전송 | 문제=%s",
                    issue_key
                )
            elif issue_key == "manual_test":
                logger.info(
                    "운영 경고 수동 테스트 전송 완료"
                )
            else:
                self.last_alert_at = datetime.now()
                logger.warning(
                    "운영 이상 관리자 경고 전송 | 문제=%s",
                    issue_key
                )

            if issue_key != "manual_test":
                try:
                    record_operations_event(
                        "recovery" if is_recovery else "alert",
                        issue_key,
                        message,
                        max_events=OPERATIONS_EVENT_RETENTION_COUNT
                    )
                except Exception:
                    logger.exception(
                        "운영 알림 이력 DB 저장 실패 | 문제=%s",
                        issue_key
                    )
        return sent

    async def send_recovery(self, issue_key):
        issue_names = {
            "database": "SQLite DB 상태",
            "backup": "내부 DB 백업 상태",
            "gateway": "Discord Gateway 연결 상태"
        }
        issue_name = issue_names.get(issue_key, issue_key)
        return await self.send_alert(
            issue_key,
            f"**{issue_name}**가 정상 상태로 돌아왔습니다.",
            title="✅ 꼬붕봇 운영 상태 복구",
            color=discord.Color.green(),
            is_recovery=True
        )

    @discord.app_commands.command(
        name="경고테스트",
        description="운영 이상 경고가 관리자에게 정상 전송되는지 확인합니다."
    )
    async def alert_test(self, interaction: discord.Interaction):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        await interaction.response.defer(ephemeral=True)

        sent = await self.send_alert(
            "manual_test",
            "관리자가 직접 실행한 테스트 알림입니다.\n"
            "이 메시지가 보이면 운영 경고 전송 설정이 정상입니다.",
            title="🧪 꼬붕봇 운영 경고 테스트"
        )

        if sent:
            await interaction.followup.send(
                "✅ 테스트 경고를 설정된 운영 경고 대상으로 전송했습니다.",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "❌ 테스트 경고를 전송하지 못했습니다. "
                "봇 로그와 관리자 ID 또는 경고 채널 설정을 확인해주세요.",
                ephemeral=True
            )

    @discord.app_commands.command(
        name="운영이력",
        description="최근 운영 경고와 복구 알림 기록을 확인합니다."
    )
    @discord.app_commands.rename(
        issue="문제",
        event_type="상태",
        count="개수"
    )
    @discord.app_commands.describe(
        issue="조회할 문제 종류이며 선택하지 않으면 전체입니다.",
        event_type="조회할 기록 상태이며 선택하지 않으면 전체입니다.",
        count="표시할 최근 기록 개수이며 기본값은 10개입니다."
    )
    @discord.app_commands.choices(
        issue=[
            discord.app_commands.Choice(name="SQLite DB", value="database"),
            discord.app_commands.Choice(name="내부 DB 백업", value="backup"),
            discord.app_commands.Choice(name="Discord Gateway", value="gateway")
        ],
        event_type=[
            discord.app_commands.Choice(name="장애 경고", value="alert"),
            discord.app_commands.Choice(name="복구 완료", value="recovery")
        ],
        count=[
            discord.app_commands.Choice(name="5개", value=5),
            discord.app_commands.Choice(name="10개", value=10),
            discord.app_commands.Choice(name="20개", value=20)
        ]
    )
    async def operations_history(
        self,
        interaction: discord.Interaction,
        issue: Optional[str] = None,
        event_type: Optional[str] = None,
        count: Optional[int] = None
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        await interaction.response.defer(ephemeral=True)
        selected_count = count if count in {5, 10, 20} else 10

        try:
            events = get_operations_events(
                limit=selected_count,
                issue_key=issue,
                event_type=event_type
            )
        except Exception:
            logger.exception("운영 경고·복구 이력 조회 실패")
            await interaction.followup.send(
                "❌ 운영 이력을 조회하지 못했습니다. "
                "DB 스키마와 봇 로그를 확인해주세요.",
                ephemeral=True
            )
            return

        if not events:
            await interaction.followup.send(
                "📭 선택한 조건에 해당하는 운영 이력이 없습니다.",
                ephemeral=True
            )
            return

        issue_names = {
            "database": "SQLite DB",
            "backup": "내부 DB 백업",
            "gateway": "Discord Gateway"
        }
        event_type_names = {
            "alert": "장애 경고",
            "recovery": "복구 완료"
        }
        active_filters = []
        if issue is not None:
            active_filters.append(
                f"문제: {issue_names.get(issue, issue)}"
            )
        if event_type is not None:
            active_filters.append(
                f"상태: {event_type_names.get(event_type, event_type)}"
            )
        filter_text = (
            " · ".join(active_filters)
            if active_filters
            else "전체"
        )
        embed = discord.Embed(
            title="📋 꼬붕봇 운영 이력",
            description=(
                f"최근 자동 경고·복구 기록 {selected_count}개를 "
                "최신순으로 표시합니다.\n"
                f"필터: **{filter_text}**"
            ),
            color=discord.Color.blue()
        )

        for event in events:
            is_recovery = event["event_type"] == "recovery"
            event_label = "✅ 복구" if is_recovery else "🚨 경고"
            issue_label = issue_names.get(
                event["issue_key"],
                event["issue_key"]
            )
            message = str(event["message"])
            if len(message) > 850:
                message = f"{message[:847]}..."

            embed.add_field(
                name=(
                    f"{event_label} · {issue_label} · "
                    f"{event['created_at']}"
                ),
                value=message,
                inline=False
            )

        embed.set_footer(
            text=(
                f"표시 결과: {len(events)}개 · "
                "수동 /경고테스트 기록은 포함되지 않습니다."
            )
        )
        await interaction.followup.send(
            embed=embed,
            ephemeral=True
        )

    @discord.app_commands.command(
        name="운영이력내보내기",
        description="저장된 전체 운영 경고·복구 이력을 CSV로 받습니다."
    )
    @discord.app_commands.rename(
        issue="문제",
        event_type="상태"
    )
    @discord.app_commands.describe(
        issue="내보낼 문제 종류이며 선택하지 않으면 전체입니다.",
        event_type="내보낼 기록 상태이며 선택하지 않으면 전체입니다."
    )
    @discord.app_commands.choices(
        issue=[
            discord.app_commands.Choice(name="SQLite DB", value="database"),
            discord.app_commands.Choice(name="내부 DB 백업", value="backup"),
            discord.app_commands.Choice(name="Discord Gateway", value="gateway")
        ],
        event_type=[
            discord.app_commands.Choice(name="장애 경고", value="alert"),
            discord.app_commands.Choice(name="복구 완료", value="recovery")
        ]
    )
    async def export_operations_history(
        self,
        interaction: discord.Interaction,
        issue: Optional[str] = None,
        event_type: Optional[str] = None
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            events = get_all_operations_events(
                issue_key=issue,
                event_type=event_type
            )
        except Exception:
            logger.exception("운영 경고·복구 이력 CSV 조회 실패")
            await interaction.followup.send(
                "❌ 운영 이력을 불러오지 못했습니다. "
                "DB 스키마와 봇 로그를 확인해주세요.",
                ephemeral=True
            )
            return

        if not events:
            await interaction.followup.send(
                "📭 선택한 조건에 해당하는 운영 이력이 없습니다.",
                ephemeral=True
            )
            return

        csv_buffer = io.StringIO(newline="")
        writer = csv.writer(csv_buffer)
        writer.writerow([
            "번호",
            "상태",
            "문제 종류",
            "상세 메시지",
            "기록 시각"
        ])

        event_type_names = {
            "alert": "장애 경고",
            "recovery": "복구 완료"
        }
        issue_names = {
            "database": "SQLite DB",
            "backup": "내부 DB 백업",
            "gateway": "Discord Gateway"
        }
        for event in events:
            writer.writerow([
                event["id"],
                event_type_names.get(
                    event["event_type"],
                    event["event_type"]
                ),
                issue_names.get(
                    event["issue_key"],
                    event["issue_key"]
                ),
                event["message"],
                event["created_at"]
            ])

        file_buffer = io.BytesIO(
            csv_buffer.getvalue().encode("utf-8-sig")
        )
        filename = (
            "operations_history_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        filter_labels = []
        if issue is not None:
            filter_labels.append(issue_names.get(issue, issue))
        if event_type is not None:
            filter_labels.append(
                event_type_names.get(event_type, event_type)
            )
        filter_text = (
            " · ".join(filter_labels)
            if filter_labels
            else "전체"
        )
        await interaction.followup.send(
            content=(
                f"✅ 운영 이력 **{len(events)}개**를 내보냈습니다.\n"
                f"필터: **{filter_text}**"
            ),
            file=discord.File(file_buffer, filename=filename),
            ephemeral=True
        )

    @tasks.loop(seconds=OPERATIONS_CHECK_INTERVAL_SECONDS)
    async def operations_check(self):
        issues = self.collect_issues()
        self.last_check_at = datetime.now()
        self.current_issues = set(issues)
        recovered_issues = self.notified_issues - set(issues)

        for issue_key in tuple(recovered_issues):
            if await self.send_recovery(issue_key):
                self.notified_issues.discard(issue_key)
                self.last_alert_times.pop(issue_key, None)

        for issue_key, message in issues.items():
            if not self.should_send_alert(issue_key):
                continue

            if await self.send_alert(issue_key, message):
                self.last_alert_times[issue_key] = time.monotonic()
                self.notified_issues.add(issue_key)

    @operations_check.before_loop
    async def before_operations_check(self):
        await self.bot.wait_until_ready()

    @operations_check.error
    async def operations_check_error(self, error):
        logger.exception(
            "운영 이상 자동 점검 작업 오류",
            exc_info=(type(error), error, error.__traceback__)
        )


async def setup(bot):
    await bot.add_cog(OperationsMonitor(bot))
