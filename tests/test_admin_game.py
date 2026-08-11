import unittest
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from cogs.admin_game import AdminGame
from services.room_state import InhouseRoom


class DummyResponse:

    def __init__(self):
        self.deferred = False

    async def defer(
        self,
        ephemeral=False
    ):
        self.deferred = True


class DummyFollowup:

    def __init__(self):
        self.messages = []

    async def send(
        self,
        message=None,
        ephemeral=False,
        embed=None
    ):
        self.messages.append(
            {
                "message": message,
                "embed": embed,
                "ephemeral": ephemeral
            }
        )


class DummyChannel:

    def __init__(self):
        self.id = 100


class DummyMessage:

    def __init__(self, channel):
        self.channel = channel


class DummyInteraction:

    def __init__(self):
        self.response = DummyResponse()
        self.followup = DummyFollowup()
        self.channel = DummyChannel()
        self.channel_id = self.channel.id
        self.guild = object()


class DummyJoinCog:

    ROOM_PROPERTIES = {
        "players",
        "current_teams",
        "last_team_signature",
        "match_in_progress",
        "series_score",
        "series_game",
        "current_recruit_view"
    }

    def __init__(self, room):
        object.__setattr__(self, "active_room", room)
        object.__setattr__(self, "save_count", 0)

    def __getattr__(self, name):
        if name in self.ROOM_PROPERTIES:
            return getattr(self.active_room, name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        if name in self.ROOM_PROPERTIES:
            setattr(self.active_room, name, value)
            return
        object.__setattr__(self, name, value)

    async def require_room(self, interaction):
        return True

    async def move_members_to_voice_channel(
        self,
        **kwargs
    ):
        return {
            "moved": 0,
            "already_connected": 0,
            "not_connected": len(kwargs["user_ids"]),
            "failed": 0,
            "channel_missing": False
        }

    async def send_output_message(
        self,
        room,
        fallback_channel,
        **kwargs
    ):
        return DummyMessage(fallback_channel), False

    def save_rooms_state(self):
        self.save_count += 1


class DummyBot:
    pass


class TestAdminGame(
    unittest.IsolatedAsyncioTestCase
):

    async def test_system_check_reports_db_paths_and_room_state(
        self
    ):
        room = InhouseRoom(
            room_id="1",
            room_name="내전 1"
        )
        room.players = {
            "1001": {},
            "1002": {}
        }
        room.match_in_progress = True
        room.pending_match_token = "pending-token"

        join_cog = SimpleNamespace(
            room_manager=SimpleNamespace(
                get_rooms=lambda: [room]
            )
        )
        interaction = DummyInteraction()
        bot = DummyBot()
        bot.started_monotonic = time.monotonic() - 3661
        bot.latency = 0.123
        bot.gateway_disconnect_count = 2
        bot.gateway_resume_count = 1
        cog = AdminGame(bot)

        with TemporaryDirectory() as temporary_root:
            data_dir = Path(temporary_root) / "data"
            backup_dir = data_dir / "backups"
            data_dir.mkdir()
            backup_dir.mkdir()
            log_dir = Path(temporary_root) / "logs"
            log_dir.mkdir()
            (log_dir / "bot.log").write_text(
                "bot log",
                encoding="utf-8"
            )
            (log_dir / "error.log").write_text(
                "error log",
                encoding="utf-8"
            )
            (backup_dir / "blooming_test.db").write_bytes(
                b"backup"
            )
            one_drive = Path(temporary_root) / "OneDrive"
            external_dir = one_drive / "꼬붕봇_외부백업"
            external_dir.mkdir(parents=True)
            (external_dir / "blooming_external.db").write_bytes(
                b"external"
            )

            with (
                patch(
                    "cogs.admin_game.is_admin",
                    return_value=True
                ),
                patch(
                    "cogs.admin_game.get_join_cog",
                    return_value=join_cog
                ),
                patch(
                    "cogs.admin_game.check_database_integrity",
                    return_value=(True, "ok")
                ),
                patch(
                    "cogs.admin_game.DATA_DIR",
                    data_dir
                ),
                patch(
                    "cogs.admin_game.BACKUP_DIR",
                    backup_dir
                ),
                patch(
                    "cogs.admin_game.LOG_DIR",
                    log_dir
                ),
                patch(
                    "cogs.admin_game.get_database_schema_version",
                    return_value=1
                ),
                patch.dict(
                    "os.environ",
                    {"OneDrive": str(one_drive)}
                )
            ):
                await AdminGame.system_check.callback(
                    cog,
                    interaction
                )

        self.assertTrue(interaction.response.deferred)
        self.assertEqual(
            len(interaction.followup.messages),
            1
        )

        sent = interaction.followup.messages[0]
        embed = sent["embed"]

        self.assertTrue(sent["ephemeral"])
        self.assertIn("시스템 점검", embed.title)
        self.assertIn("운영 준비 완료", embed.description)

        field_values = "\n".join(
            field.value
            for field in embed.fields
        )

        self.assertIn("검사 결과: `ok`", field_values)
        self.assertIn("참가자: **2명**", field_values)
        self.assertIn("진행 경기: **1개**", field_values)
        self.assertIn("pending 복구: **1개**", field_values)
        self.assertIn("실행시간: **1시간 1분", field_values)
        self.assertIn("Discord 지연시간: **123ms**", field_values)
        self.assertIn("Gateway 끊김/복구: **2/1회**", field_values)
        self.assertIn("스키마: **1/1** ✅", field_values)
        self.assertIn("최근 내부 백업:", field_values)
        self.assertIn("최근 외부 백업:", field_values)
        self.assertIn("마지막 오류 기록:", field_values)

    async def test_system_check_warns_about_db_and_missing_paths(
        self
    ):
        join_cog = SimpleNamespace(
            room_manager=SimpleNamespace(
                get_rooms=lambda: []
            )
        )
        interaction = DummyInteraction()
        cog = AdminGame(DummyBot())

        with TemporaryDirectory() as temporary_root:
            missing_data_dir = (
                Path(temporary_root)
                / "missing-data"
            )
            missing_backup_dir = (
                missing_data_dir
                / "backups"
            )

            with (
                patch(
                    "cogs.admin_game.is_admin",
                    return_value=True
                ),
                patch(
                    "cogs.admin_game.get_join_cog",
                    return_value=join_cog
                ),
                patch(
                    "cogs.admin_game.check_database_integrity",
                    return_value=(False, "database disk image is malformed")
                ),
                patch(
                    "cogs.admin_game.DATA_DIR",
                    missing_data_dir
                ),
                patch(
                    "cogs.admin_game.BACKUP_DIR",
                    missing_backup_dir
                )
            ):
                await AdminGame.system_check.callback(
                    cog,
                    interaction
                )

        embed = interaction.followup.messages[0]["embed"]
        field_values = "\n".join(
            field.value
            for field in embed.fields
        )

        self.assertIn(
            "확인이 필요한 항목",
            embed.description
        )
        self.assertIn("❌ 오류", field_values)
        self.assertIn("database disk image is malformed", field_values)
        self.assertIn("데이터 폴더: ❌", field_values)
        self.assertIn("백업 폴더: ❌", field_values)

    async def test_system_check_reports_integrity_check_exception(
        self
    ):
        join_cog = SimpleNamespace(
            room_manager=SimpleNamespace(
                get_rooms=lambda: []
            )
        )
        interaction = DummyInteraction()
        cog = AdminGame(DummyBot())

        with (
            patch(
                "cogs.admin_game.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_game.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.admin_game.check_database_integrity",
                side_effect=OSError("unavailable")
            )
        ):
            await AdminGame.system_check.callback(
                cog,
                interaction
            )

        embed = interaction.followup.messages[0]["embed"]
        field_values = "\n".join(
            field.value
            for field in embed.fields
        )

        self.assertIn(
            "검사 실행 실패: OSError",
            field_values
        )
        self.assertIn(
            "확인이 필요한 항목",
            embed.description
        )

    async def test_end_game_clears_all_room_and_recovery_state(
        self
    ):
        room = InhouseRoom(
            room_id="1",
            room_name="내전 1",
            waiting_voice_channel_id=200
        )
        room.players = {
            "1001": {"nickname": "참가자"}
        }
        room.current_teams = {
            "red": {"TOP": "1001"},
            "blue": {}
        }
        room.match_in_progress = True
        room.series_score = {
            "red": 1,
            "blue": 1
        }
        room.series_game = 2
        room.mvp_vote_in_progress = True
        room.match_transaction_active = True
        room.match_transaction_committed = True
        room.transaction_series_score = {
            "red": 1,
            "blue": 1
        }
        room.transaction_series_game = 2
        room.pending_match_token = "pending-token"
        room.pending_series_score = {
            "red": 2,
            "blue": 1
        }
        room.pending_series_game = 3

        join_cog = DummyJoinCog(room)
        interaction = DummyInteraction()
        cog = AdminGame(DummyBot())

        with (
            patch(
                "cogs.admin_game.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_game.get_join_cog",
                return_value=join_cog
            )
        ):
            await AdminGame.end_game.callback(
                cog,
                interaction
            )

        self.assertEqual(room.players, {})
        self.assertIsNone(room.current_teams)
        self.assertFalse(room.match_in_progress)
        self.assertEqual(
            room.series_score,
            {"red": 0, "blue": 0}
        )
        self.assertEqual(room.series_game, 0)
        self.assertFalse(room.mvp_vote_in_progress)
        self.assertFalse(room.match_transaction_active)
        self.assertFalse(room.match_transaction_committed)
        self.assertIsNone(room.transaction_series_score)
        self.assertIsNone(room.transaction_series_game)
        self.assertIsNone(room.pending_match_token)
        self.assertIsNone(room.pending_series_score)
        self.assertIsNone(room.pending_series_game)
        self.assertTrue(interaction.response.deferred)
        self.assertEqual(join_cog.save_count, 1)


if __name__ == "__main__":
    unittest.main()
