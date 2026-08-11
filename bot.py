import logging
import socket
import time

from collections import deque
from contextlib import AsyncExitStack

import discord
from discord.ext import commands

from config import (
    COMMAND_COOLDOWN_SECONDS,
    RIOT_LOOKUP_COOLDOWN_SECONDS,
    TOKEN
)
from services.rate_limiter import CooldownRateLimiter
from storage.sqlite_db import (
    backup_database,
    check_database_integrity
)
from storage.paths import validate_runtime_paths
from utils.logging_config import configure_logging


logger = logging.getLogger(__name__)

SINGLE_INSTANCE_HOST = "127.0.0.1"
SINGLE_INSTANCE_PORT = 47653


class InhouseCommandTree(
    discord.app_commands.CommandTree
):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cooldown_limiter = CooldownRateLimiter()

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ) -> bool:
        command = getattr(interaction, "command", None)
        user = getattr(interaction, "user", None)

        if command is None or user is None:
            return True

        command_name = command.name
        cooldown_seconds = (
            RIOT_LOOKUP_COOLDOWN_SECONDS
            if command_name == "라이엇조회"
            else COMMAND_COOLDOWN_SECONDS
        )
        allowed, retry_after = (
            self.cooldown_limiter.acquire(
                (str(user.id), command_name),
                cooldown_seconds
            )
        )

        if allowed:
            return True

        await interaction.response.send_message(
            "⏳ 같은 명령을 너무 빠르게 반복했습니다.\n"
            f"**{retry_after:.1f}초** 후 다시 시도해주세요.",
            ephemeral=True
        )
        logger.info(
            "슬래시 명령어 쿨다운 차단 | 명령어=/%s | "
            "사용자=%s | 남은시간=%.1f초",
            command_name,
            user.id,
            retry_after
        )
        return False


intents = discord.Intents.default()
intents.message_content = True
intents.members = True

EXTENSIONS = (
    "cogs.join",
    "cogs.room",
    "cogs.profile",
    "cogs.match",
    "cogs.statistics",
    "cogs.ranking",
    "cogs.record",
    "cogs.duo",
    "cogs.team",
    "cogs.history",
    "cogs.season",
    "cogs.admin_match",
    "cogs.admin_player",
    "cogs.admin_game",
    "cogs.operations_monitor",
    "cogs.riot",
    "cogs.register",
)


class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix="!",
            intents=intents,
            tree_cls=InhouseCommandTree
        )
        self._shutdown_state_saved = False
        self.started_monotonic = time.monotonic()
        self.gateway_disconnect_count = 0
        self.gateway_resume_count = 0
        self.gateway_disconnect_times = deque(maxlen=100)

    async def save_state_before_shutdown(self):
        """종료 직전에 모든 내전 방 상태를 한 번 안전하게 저장합니다."""

        if self._shutdown_state_saved:
            return False

        join_cog = self.get_cog("Join")

        if join_cog is None:
            logger.warning(
                "종료 상태 저장 생략: Join Cog가 로드되지 않음"
            )
            return False

        room_manager = join_cog.room_manager

        try:
            async with room_manager.management_lock:
                rooms = sorted(
                    room_manager.get_rooms(),
                    key=lambda room: str(room.room_id)
                )

                async with AsyncExitStack() as stack:
                    for room in rooms:
                        await stack.enter_async_context(
                            room.operation_lock
                        )

                    join_cog.save_rooms_state()

            self._shutdown_state_saved = True
            logger.info(
                "종료 전 내전 상태 저장 완료 | 방=%s",
                len(rooms)
            )
            return True

        except Exception:
            logger.exception(
                "종료 전 내전 상태 저장 실패"
            )
            return False

    async def close(self):
        await self.save_state_before_shutdown()
        await super().close()

    async def setup_hook(self):
        try:

            validate_runtime_paths()

            logger.info(
                "✅ 데이터 저장 경로 검사 완료"
            )

            # DB가 정상인지 먼저 검사합니다.
            integrity_ok, integrity_result = (
                check_database_integrity()
            )

            if not integrity_ok:
                raise RuntimeError(
                    "SQLite DB 무결성 검사 실패: "
                    f"{integrity_result}"
                )

            logger.info(
                "✅ DB 무결성 검사 완료"
            )

            # 정상 DB만 자동으로 백업합니다.
            # 백업 자체가 실패해도 봇 실행은 계속합니다.
            try:
                backup_path = backup_database(
                    max_backups=10
                )

                logger.info(
                    f"💾 DB 백업 완료: "
                    f"{backup_path}"
                )

            except Exception:
                logger.exception(
                    "DB 자동 백업 중 오류가 발생했습니다."
                )

            for extension in EXTENSIONS:
                logger.info(
                    "확장 기능 불러오기 시작: %s",
                    extension
                )

                await self.load_extension(extension)

                logger.info(
                    "확장 기능 불러오기 완료: %s",
                    extension
                )

            logger.info("슬래시 명령어 동기화 시작")

            synced = await self.tree.sync()

            logger.info(
                "슬래시 명령어 %s개 동기화 완료",
                len(synced)
            )

            for command in synced:
                logger.info("동기화 명령어: /%s", command.name)

        except Exception:
            logger.exception("setup_hook 실행 중 오류 발생")
            raise


bot = MyBot()


def get_interaction_audit_context(interaction):
    guild = getattr(interaction, "guild", None)
    channel = getattr(interaction, "channel", None)

    return {
        "user_id": getattr(
            getattr(interaction, "user", None),
            "id",
            None
        ),
        "guild_id": getattr(guild, "id", None),
        "channel_id": (
            getattr(interaction, "channel_id", None)
            or getattr(channel, "id", None)
        )
    }


@bot.event
async def on_app_command_completion(
    interaction: discord.Interaction,
    command: discord.app_commands.Command
):
    context = get_interaction_audit_context(
        interaction
    )
    logger.info(
        "슬래시 명령어 성공 | 명령어=/%s | 사용자=%s | "
        "서버=%s | 채널=%s",
        command.name,
        context["user_id"],
        context["guild_id"],
        context["channel_id"]
    )


@bot.event
async def on_connect():
    logger.info(
        "Discord Gateway 연결 성공"
    )


@bot.event
async def on_disconnect():
    bot.gateway_disconnect_count += 1
    bot.gateway_disconnect_times.append(time.monotonic())
    logger.warning(
        "Discord Gateway 연결 끊김 | 자동 재연결 대기"
    )


@bot.event
async def on_resumed():
    bot.gateway_resume_count += 1
    logger.info(
        "Discord Gateway 세션 복구 완료"
    )



@bot.event
async def on_ready():
    logger.info("Discord 로그인 완료: %s", bot.user)

    join_cog = bot.get_cog(
        "Join"
    )

    if join_cog is None:
        logger.warning(
            "Join Cog를 찾을 수 없어 "
            "재시작 복구 안내를 실행하지 못했습니다."
        )
        return

    if join_cog._restart_recovery_message_sent:
        return

    try:
        await join_cog.validate_recovered_discord_channels()
        await join_cog.send_restart_recovery_messages()

    except Exception:
        logger.exception(
            "재시작 복구 안내 실행 중 "
            "오류가 발생했습니다."
        )




@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: discord.app_commands.AppCommandError
):
    if (
        isinstance(
            error,
            discord.app_commands.CheckFailure
        )
        and interaction.response.is_done()
    ):
        logger.info(
            "이미 안내된 명령어 Check 실패는 추가 응답을 생략합니다."
        )
        return

    command_name = (
        interaction.command.name
        if interaction.command
        else "알 수 없음"
    )
    context = get_interaction_audit_context(
        interaction
    )

    logger.error(
        "슬래시 명령어 실행 오류 | 명령어=/%s | 사용자=%s (%s) | "
        "서버=%s | 채널=%s",
        command_name,
        interaction.user,
        interaction.user.id,
        context["guild_id"],
        context["channel_id"],
        exc_info=(
            type(error),
            error,
            error.__traceback__
        )
    )

    message = (
        "❌ 명령어 실행 중 오류가 발생했습니다.\n"
        "터미널의 오류 내용을 확인해주세요."
    )

    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                message,
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                message,
                ephemeral=True
            )

    except discord.HTTPException:
        pass

@bot.tree.command(
    name="핑",
    description="봇이 살아있는지 확인합니다."
)
async def ping(
    interaction: discord.Interaction
):
    await interaction.response.send_message(
        "🏓 퐁!"
    )




def acquire_single_instance_lock(
    host=SINGLE_INSTANCE_HOST,
    port=SINGLE_INSTANCE_PORT
):
    """로컬 포트를 점유해 동일 PC의 봇 중복 실행을 차단합니다."""

    lock_socket = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )

    try:
        lock_socket.bind((host, port))
        lock_socket.listen(1)
        return lock_socket

    except OSError as error:
        lock_socket.close()
        raise RuntimeError(
            "꼬붕봇이 이미 실행 중입니다. 기존 봇 터미널을 "
            "확인하고 중복 실행하지 마세요."
        ) from error


def run_bot():
    """실제 운영 실행에서만 파일 로그를 초기화하고 봇을 시작합니다."""

    instance_lock = acquire_single_instance_lock()

    try:
        configure_logging()
        logger.info("꼬붕봇 운영 프로세스 시작")
        bot.run(TOKEN)
    finally:
        instance_lock.close()


if __name__ == "__main__":
    run_bot()
