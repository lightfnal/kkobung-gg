import sys
import asyncio
import unittest
import discord
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import (
    AsyncMock,
    patch
)

from bot import (
    EXTENSIONS,
    MyBot,
    acquire_single_instance_lock,
    bot,
    get_interaction_audit_context,
    on_app_command_completion,
    on_app_command_error,
    on_connect,
    on_disconnect,
    on_ready,
    on_resumed,
    run_bot
)
from services.room_manager import RoomManager
from storage.paths import validate_runtime_paths


class TestStartupSmoke(
    unittest.IsolatedAsyncioTestCase
):

    def test_runtime_path_validation_creates_writable_directories(
        self
    ):
        with TemporaryDirectory() as temporary_root:
            data_dir = Path(temporary_root) / "data"
            backup_dir = data_dir / "backups"

            result = validate_runtime_paths(
                data_dir=data_dir,
                backup_dir=backup_dir
            )

            self.assertTrue(result)
            self.assertTrue(data_dir.is_dir())
            self.assertTrue(backup_dir.is_dir())
            self.assertEqual(
                list(data_dir.glob("startup_check_*.tmp")),
                []
            )
            self.assertEqual(
                list(backup_dir.glob("startup_check_*.tmp")),
                []
            )

    def test_run_bot_initializes_logging_before_start(
        self
    ):
        call_order = []
        instance_lock = SimpleNamespace(
            close=lambda: call_order.append("unlock")
        )

        with (
            patch(
                "bot.acquire_single_instance_lock",
                return_value=instance_lock
            ) as lock_mock,
            patch(
                "bot.configure_logging",
                side_effect=lambda: call_order.append("logging")
            ) as logging_mock,
            patch(
                "bot.bot.run",
                side_effect=lambda token: call_order.append("run")
            ) as run_mock
        ):
            run_bot()

        lock_mock.assert_called_once_with()
        logging_mock.assert_called_once_with()
        run_mock.assert_called_once()
        self.assertEqual(
            call_order,
            ["logging", "run", "unlock"]
        )

    def test_single_instance_lock_rejects_second_process(
        self
    ):
        first_lock = acquire_single_instance_lock(
            port=0
        )
        assigned_port = first_lock.getsockname()[1]

        try:
            with self.assertRaisesRegex(
                RuntimeError,
                "이미 실행 중"
            ):
                acquire_single_instance_lock(
                    port=assigned_port
                )
        finally:
            first_lock.close()

        replacement_lock = acquire_single_instance_lock(
            port=assigned_port
        )
        replacement_lock.close()

    def test_runtime_path_validation_reports_write_failure(
        self
    ):
        with TemporaryDirectory() as temporary_root:
            data_dir = Path(temporary_root) / "data"
            backup_dir = data_dir / "backups"

            with patch(
                "storage.paths.tempfile.NamedTemporaryFile",
                side_effect=PermissionError("denied")
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "데이터 저장 경로에 쓸 수 없습니다"
                ):
                    validate_runtime_paths(
                        data_dir=data_dir,
                        backup_dir=backup_dir
                    )

    def create_error_interaction(
        self,
        response_done=False,
        response_error=None
    ):
        response = SimpleNamespace(
            is_done=lambda: response_done,
            send_message=AsyncMock(
                side_effect=response_error
            )
        )
        followup = SimpleNamespace(
            send=AsyncMock()
        )

        return SimpleNamespace(
            command=SimpleNamespace(
                name="테스트명령"
            ),
            user=SimpleNamespace(
                id=1001
            ),
            response=response,
            followup=followup
        )

    async def test_command_completion_writes_audit_context(
        self
    ):
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=1001),
            guild=SimpleNamespace(id=2001),
            channel_id=3001
        )
        command = SimpleNamespace(
            name="시스템점검"
        )

        with self.assertLogs("bot", level="INFO") as logs:
            await on_app_command_completion(
                interaction,
                command
            )

        message = "\n".join(logs.output)
        self.assertIn("명령어=/시스템점검", message)
        self.assertIn("사용자=1001", message)
        self.assertIn("서버=2001", message)
        self.assertIn("채널=3001", message)

    async def test_gateway_lifecycle_events_are_logged(
        self
    ):
        disconnect_before = bot.gateway_disconnect_count
        resume_before = bot.gateway_resume_count

        with self.assertLogs("bot", level="INFO") as logs:
            await on_connect()
            await on_disconnect()
            await on_resumed()

        message = "\n".join(logs.output)
        self.assertIn("Gateway 연결 성공", message)
        self.assertIn("Gateway 연결 끊김", message)
        self.assertIn("자동 재연결 대기", message)
        self.assertIn("Gateway 세션 복구 완료", message)
        self.assertEqual(
            bot.gateway_disconnect_count,
            disconnect_before + 1
        )
        self.assertEqual(
            bot.gateway_resume_count,
            resume_before + 1
        )

    def test_audit_context_handles_direct_message(self):
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=1001),
            guild=None,
            channel=SimpleNamespace(id=3001),
            channel_id=None
        )

        context = get_interaction_audit_context(
            interaction
        )

        self.assertEqual(context["user_id"], 1001)
        self.assertIsNone(context["guild_id"])
        self.assertEqual(context["channel_id"], 3001)

    async def test_command_error_uses_initial_response(
        self
    ):
        interaction = self.create_error_interaction(
            response_done=False
        )

        await on_app_command_error(
            interaction,
            RuntimeError("command failed")
        )

        interaction.response.send_message.assert_awaited_once()
        interaction.followup.send.assert_not_awaited()

        call = interaction.response.send_message.await_args

        self.assertIn(
            "명령어 실행 중 오류",
            call.args[0]
        )
        self.assertTrue(
            call.kwargs["ephemeral"]
        )

    async def test_command_error_uses_followup_after_response(
        self
    ):
        interaction = self.create_error_interaction(
            response_done=True
        )

        await on_app_command_error(
            interaction,
            RuntimeError("command failed")
        )

        interaction.response.send_message.assert_not_awaited()
        interaction.followup.send.assert_awaited_once()

        call = interaction.followup.send.await_args

        self.assertIn(
            "명령어 실행 중 오류",
            call.args[0]
        )
        self.assertTrue(
            call.kwargs["ephemeral"]
        )

    async def test_command_error_contains_discord_send_failure(
        self
    ):
        http_error = discord.HTTPException(
            SimpleNamespace(
                status=500,
                reason="Internal Server Error"
            ),
            "send failed"
        )
        interaction = self.create_error_interaction(
            response_done=False,
            response_error=http_error
        )

        await on_app_command_error(
            interaction,
            RuntimeError("command failed")
        )

        interaction.response.send_message.assert_awaited_once()

    async def test_global_command_cooldown_sends_retry_message(
        self
    ):
        bot = MyBot()
        response = SimpleNamespace(
            send_message=AsyncMock()
        )
        interaction = SimpleNamespace(
            command=SimpleNamespace(name="명단"),
            user=SimpleNamespace(id=1001),
            response=response
        )

        first_result = await bot.tree.interaction_check(
            interaction
        )
        second_result = await bot.tree.interaction_check(
            interaction
        )

        self.assertTrue(first_result)
        self.assertFalse(second_result)
        response.send_message.assert_awaited_once()
        call = response.send_message.await_args
        self.assertIn("2.0초", call.args[0])
        self.assertTrue(call.kwargs["ephemeral"])
        await bot.close()

    async def test_riot_command_uses_longer_cooldown(
        self
    ):
        bot = MyBot()
        interaction = SimpleNamespace(
            command=SimpleNamespace(name="라이엇조회"),
            user=SimpleNamespace(id=1001),
            response=SimpleNamespace(
                send_message=AsyncMock()
            )
        )

        await bot.tree.interaction_check(interaction)
        await bot.tree.interaction_check(interaction)

        call = interaction.response.send_message.await_args
        self.assertIn("10.0초", call.args[0])
        await bot.close()

    async def test_already_reported_check_failure_is_not_duplicated(
        self
    ):
        interaction = self.create_error_interaction(
            response_done=True
        )

        await on_app_command_error(
            interaction,
            discord.app_commands.CheckFailure(
                "cooldown blocked"
            )
        )

        interaction.response.send_message.assert_not_awaited()
        interaction.followup.send.assert_not_awaited()

    async def test_on_ready_runs_recovery_only_once(
        self
    ):
        class DummyJoinCog:

            def __init__(self):
                self._restart_recovery_message_sent = False
                self.call_count = 0

            async def send_restart_recovery_messages(self):
                self._restart_recovery_message_sent = True
                self.call_count += 1

        join_cog = DummyJoinCog()

        with patch(
            "bot.bot.get_cog",
            return_value=join_cog
        ):
            await on_ready()
            await on_ready()

        self.assertEqual(
            join_cog.call_count,
            1
        )

    async def test_on_ready_handles_missing_join_cog(
        self
    ):
        with patch(
            "bot.bot.get_cog",
            return_value=None
        ):
            await on_ready()

    async def test_on_ready_contains_recovery_error(
        self
    ):
        join_cog = SimpleNamespace(
            _restart_recovery_message_sent=False,
            send_restart_recovery_messages=AsyncMock(
                side_effect=RuntimeError("recovery failed")
            )
        )

        with patch(
            "bot.bot.get_cog",
            return_value=join_cog
        ):
            await on_ready()

        (
            join_cog
            .send_restart_recovery_messages
            .assert_awaited_once_with()
        )

    async def test_setup_hook_stops_on_integrity_failure(
        self
    ):
        bot = MyBot()

        with (
            patch(
                "bot.validate_runtime_paths"
            ),
            patch(
                "bot.check_database_integrity",
                return_value=(False, "broken")
            ),
            patch(
                "bot.backup_database"
            ) as backup_mock,
            patch.object(
                bot,
                "load_extension",
                new=AsyncMock()
            ) as load_mock,
            patch.object(
                bot.tree,
                "sync",
                new=AsyncMock()
            ) as sync_mock
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "SQLite DB 무결성 검사 실패"
            ):
                await bot.setup_hook()

        backup_mock.assert_not_called()
        load_mock.assert_not_awaited()
        sync_mock.assert_not_awaited()
        await bot.close()

    async def test_shutdown_saves_all_rooms_once_under_locks(
        self
    ):
        rooms = [
            SimpleNamespace(
                room_id=str(room_number),
                operation_lock=asyncio.Lock()
            )
            for room_number in range(1, 4)
        ]
        management_lock = asyncio.Lock()
        save_count = 0

        class DummyJoinCog:

            def __init__(self):
                self.room_manager = SimpleNamespace(
                    management_lock=management_lock,
                    get_rooms=lambda: list(reversed(rooms))
                )

            def save_rooms_state(self):
                nonlocal save_count
                self.assert_locks()
                save_count += 1

            @staticmethod
            def assert_locks():
                if not management_lock.locked():
                    raise AssertionError("management lock missing")

                if not all(
                    room.operation_lock.locked()
                    for room in rooms
                ):
                    raise AssertionError("room lock missing")

        bot = MyBot()
        join_cog = DummyJoinCog()

        with patch.object(
            bot,
            "get_cog",
            return_value=join_cog
        ):
            first_result = await bot.save_state_before_shutdown()
            second_result = await bot.save_state_before_shutdown()

        self.assertTrue(first_result)
        self.assertFalse(second_result)
        self.assertEqual(save_count, 1)
        self.assertFalse(management_lock.locked())
        self.assertTrue(
            all(
                not room.operation_lock.locked()
                for room in rooms
            )
        )
        await bot.close()

    async def test_shutdown_continues_when_state_save_fails(
        self
    ):
        room = SimpleNamespace(
            room_id="1",
            operation_lock=asyncio.Lock()
        )
        join_cog = SimpleNamespace(
            room_manager=SimpleNamespace(
                management_lock=asyncio.Lock(),
                get_rooms=lambda: [room]
            ),
            save_rooms_state=lambda: (_ for _ in ()).throw(
                OSError("save failed")
            )
        )
        bot = MyBot()

        with patch.object(
            bot,
            "get_cog",
            return_value=join_cog
        ):
            result = await bot.save_state_before_shutdown()

        self.assertFalse(result)
        self.assertFalse(room.operation_lock.locked())
        await bot.close()

    async def test_setup_hook_continues_after_backup_failure(
        self
    ):
        bot = MyBot()
        load_mock = AsyncMock()
        sync_mock = AsyncMock(
            return_value=[
                SimpleNamespace(name="테스트명령")
            ]
        )

        with (
            patch(
                "bot.validate_runtime_paths"
            ),
            patch(
                "bot.check_database_integrity",
                return_value=(True, "ok")
            ),
            patch(
                "bot.backup_database",
                side_effect=OSError("backup failed")
            ),
            patch.object(
                bot,
                "load_extension",
                new=load_mock
            ),
            patch.object(
                bot.tree,
                "sync",
                new=sync_mock
            )
        ):
            await bot.setup_hook()

        self.assertEqual(
            load_mock.await_count,
            len(EXTENSIONS)
        )
        self.assertEqual(
            [
                call.args[0]
                for call in load_mock.await_args_list
            ],
            list(EXTENSIONS)
        )
        sync_mock.assert_awaited_once_with()
        await bot.close()

    async def test_setup_hook_propagates_extension_failure(
        self
    ):
        bot = MyBot()
        load_mock = AsyncMock(
            side_effect=RuntimeError("extension failed")
        )
        sync_mock = AsyncMock()

        with (
            patch(
                "bot.validate_runtime_paths"
            ),
            patch(
                "bot.check_database_integrity",
                return_value=(True, "ok")
            ),
            patch(
                "bot.backup_database",
                return_value="backup.db"
            ),
            patch.object(
                bot,
                "load_extension",
                new=load_mock
            ),
            patch.object(
                bot.tree,
                "sync",
                new=sync_mock
            )
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "extension failed"
            ):
                await bot.setup_hook()

        load_mock.assert_awaited_once_with(
            EXTENSIONS[0]
        )
        sync_mock.assert_not_awaited()
        await bot.close()

    async def test_all_extensions_and_commands_load_without_duplicates(
        self
    ):
        original_extension_modules = {
            extension: sys.modules.get(extension)
            for extension in EXTENSIONS
        }

        def restore_extension_modules():
            for extension, module in (
                original_extension_modules.items()
            ):
                if module is None:
                    sys.modules.pop(
                        extension,
                        None
                    )
                else:
                    sys.modules[extension] = module

        self.addCleanup(
            restore_extension_modules
        )

        bot = MyBot()

        with (
            patch.object(
                Path,
                "exists",
                return_value=True
            ),
            patch(
                "storage.room_state_store.load_room_manager",
                return_value=RoomManager()
            ),
            patch(
                "storage.room_state_store.save_room_manager"
            ),
            patch(
                "storage.sqlite_db.get_all_players_dict",
                return_value=[]
            )
        ):
            async with bot:
                for extension in EXTENSIONS:
                    await bot.load_extension(
                        extension
                    )

                self.assertEqual(
                    set(bot.extensions),
                    set(EXTENSIONS)
                )

                command_names = [
                    command.name
                    for command in bot.tree.get_commands()
                ]

                self.assertTrue(command_names)
                self.assertEqual(
                    len(command_names),
                    len(set(command_names))
                )

                expected_cogs = {
                    "Join",
                    "Room",
                    "Profile",
                    "Match",
                    "Statistics",
                    "Ranking",
                    "Record",
                    "Duo",
                    "Team",
                    "History",
                    "Season",
                    "AdminMatch",
                    "AdminPlayer",
                    "AdminGame",
                    "Riot",
                    "Register"
                }

                self.assertEqual(
                    set(bot.cogs),
                    expected_cogs
                )


if __name__ == "__main__":
    unittest.main()
