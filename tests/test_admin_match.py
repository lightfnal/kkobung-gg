import asyncio
import unittest
from unittest.mock import patch

from cogs.admin_match import AdminMatch


class DummyResponse:

    def __init__(self):
        self.deferred = False
        self.messages = []

    async def defer(
        self,
        ephemeral=False
    ):
        self.deferred = True

    async def send_message(
        self,
        message,
        ephemeral=False
    ):
        self.messages.append(
            {
                "message": message,
                "ephemeral": ephemeral
            }
        )


class DummyFollowup:

    def __init__(self):
        self.messages = []

    async def send(
        self,
        message,
        ephemeral=False
    ):
        self.messages.append(
            {
                "message": message,
                "ephemeral": ephemeral
            }
        )


class DummyChannel:

    def __init__(
        self,
        channel_id
    ):
        self.id = channel_id


class DummyInteraction:

    def __init__(self):
        self.response = DummyResponse()
        self.followup = DummyFollowup()

        self.channel = DummyChannel(
            100
        )

        self.channel_id = 100


class DummyRoom:

    def __init__(
        self,
        room_id,
        match_in_progress=False
    ):
        self.room_id = str(room_id)
        self.room_name = f"내전 {room_id}"

        self.match_in_progress = (
            match_in_progress
        )

        self.mvp_vote_in_progress = False

        self.match_transaction_active = False
        self.match_transaction_committed = False

        self.transaction_series_score = None
        self.transaction_series_game = None
        self.pending_match_token = None
        self.pending_series_score = None
        self.pending_series_game = None
        self.operation_lock = asyncio.Lock()


class DummyMessage:

    def __init__(
        self,
        channel
    ):
        self.channel = channel


class DummyJoinCog:

    def __init__(
        self,
        room
    ):
        self.active_room = room
        self.save_count = 0

    async def require_room(
        self,
        interaction
    ):
        return True

    def save_rooms_state(self):
        self.save_count += 1

    async def send_output_message(
        self,
        room,
        fallback_channel,
        **kwargs
    ):
        return (
            DummyMessage(
                fallback_channel
            ),
            False
        )

    def reload_profiles(self):
        pass


class DummyBot:
    pass


class TestAdminMatch(
    unittest.IsolatedAsyncioTestCase
):

    async def test_force_end_only_changes_active_room(
        self
    ):
        active_room = DummyRoom(
            room_id="1",
            match_in_progress=True
        )

        active_room.pending_match_token = "pending-token"
        active_room.pending_series_score = {
            "red": 2,
            "blue": 1
        }
        active_room.pending_series_game = 3

        other_room = DummyRoom(
            room_id="2",
            match_in_progress=True
        )

        join_cog = DummyJoinCog(
            active_room
        )

        interaction = DummyInteraction()

        cog = AdminMatch(
            DummyBot()
        )

        with (
            patch(
                "cogs.admin_match.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_match.get_join_cog",
                return_value=join_cog
            )
        ):
            await AdminMatch.force_end_match.callback(
                cog,
                interaction
            )

        self.assertFalse(
            active_room.match_in_progress
        )

        self.assertTrue(
            other_room.match_in_progress
        )

        self.assertIsNone(
            active_room.pending_match_token
        )

        self.assertIsNone(
            active_room.pending_series_score
        )

        self.assertIsNone(
            active_room.pending_series_game
        )

        self.assertGreaterEqual(
            join_cog.save_count,
            1
        )

    async def test_force_end_rechecks_state_after_lock(
        self
    ):
        room = DummyRoom(
            room_id="1",
            match_in_progress=True
        )
        join_cog = DummyJoinCog(room)
        interaction = DummyInteraction()
        cog = AdminMatch(DummyBot())

        await room.operation_lock.acquire()

        with (
            patch(
                "cogs.admin_match.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_match.get_join_cog",
                return_value=join_cog
            )
        ):
            force_end_task = asyncio.create_task(
                AdminMatch.force_end_match.callback(
                    cog,
                    interaction
                )
            )

            await asyncio.sleep(0)

            self.assertFalse(
                force_end_task.done()
            )

            room.match_in_progress = False
            room.operation_lock.release()

            await force_end_task

        self.assertEqual(
            join_cog.save_count,
            0
        )
        self.assertFalse(
            interaction.response.deferred
        )
        self.assertIn(
            "현재 진행 중인 경기가 없습니다",
            interaction.response.messages[0]["message"]
        )

    async def test_delete_rejects_other_room_match(
        self
    ):
        active_room = DummyRoom(
            room_id="1"
        )

        join_cog = DummyJoinCog(
            active_room
        )

        interaction = DummyInteraction()

        cog = AdminMatch(
            DummyBot()
        )

        with (
            patch(
                "cogs.admin_match.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_match.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.admin_match.get_match",
                return_value={
                    "id": 50,
                    "room_id": "2"
                }
            ),
            patch(
                "cogs.admin_match.delete_match_only"
            ) as delete_mock
        ):
            await (
                AdminMatch
                .delete_match_record_only
                .callback(
                    cog,
                    interaction,
                    경기번호=50
                )
            )

        delete_mock.assert_not_called()

        self.assertEqual(
            len(interaction.response.messages),
            1
        )

        self.assertIn(
            "현재 내전 방의 경기 기록이 아닙니다",
            interaction
            .response
            .messages[0]["message"]
        )

    async def test_delete_record_rechecks_transaction_after_lock(
        self
    ):
        room = DummyRoom(
            room_id="1"
        )
        join_cog = DummyJoinCog(room)
        interaction = DummyInteraction()
        cog = AdminMatch(DummyBot())

        await room.operation_lock.acquire()

        with (
            patch(
                "cogs.admin_match.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_match.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.admin_match.get_match"
            ) as get_match_mock,
            patch(
                "cogs.admin_match.delete_match_only"
            ) as delete_mock
        ):
            delete_task = asyncio.create_task(
                AdminMatch.delete_match_record_only.callback(
                    cog,
                    interaction,
                    경기번호=50
                )
            )

            await asyncio.sleep(0)

            self.assertFalse(delete_task.done())

            room.match_transaction_active = True
            room.operation_lock.release()

            await delete_task

        get_match_mock.assert_not_called()
        delete_mock.assert_not_called()
        self.assertIn(
            "경기 결과를 처리하고 있습니다",
            interaction.response.messages[0]["message"]
        )

    async def test_cancel_is_blocked_during_transaction(
        self
    ):
        active_room = DummyRoom(
            room_id="1"
        )

        active_room.match_transaction_active = True

        join_cog = DummyJoinCog(
            active_room
        )

        interaction = DummyInteraction()

        cog = AdminMatch(
            DummyBot()
        )

        with (
            patch(
                "cogs.admin_match.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_match.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.admin_match.get_last_match",
                return_value={
                    "id": 10,
                    "season_id": None
                }
            ),
            patch(
                "cogs.admin_match.get_match_players",
                return_value=[
                    {
                        "discord_id": "1001"
                    }
                ]
            )
        ):
        
            await AdminMatch.cancel_match.callback(
                cog,
                interaction
            )

        self.assertFalse(
            interaction.response.deferred
        )

        self.assertEqual(
            len(interaction.response.messages),
            1
        )

        self.assertIn(
            "경기 결과를 처리하고 있습니다",
            interaction
            .response
            .messages[0]["message"]
        )

    async def test_cancel_rechecks_transaction_after_lock(
        self
    ):
        room = DummyRoom(
            room_id="1"
        )
        join_cog = DummyJoinCog(room)
        interaction = DummyInteraction()
        cog = AdminMatch(DummyBot())

        await room.operation_lock.acquire()

        with (
            patch(
                "cogs.admin_match.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_match.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.admin_match.get_last_match",
                return_value={
                    "id": 10,
                    "season_id": None
                }
            ),
            patch(
                "cogs.admin_match.get_match_players",
                return_value=[
                    {"discord_id": "1001"}
                ]
            ),
            patch(
                "cogs.admin_match.begin_transaction"
            ) as begin_mock
        ):
            cancel_task = asyncio.create_task(
                AdminMatch.cancel_match.callback(
                    cog,
                    interaction
                )
            )

            await asyncio.sleep(0)

            self.assertFalse(cancel_task.done())

            room.match_transaction_active = True
            room.operation_lock.release()

            await cancel_task

        begin_mock.assert_not_called()
        self.assertFalse(interaction.response.deferred)
        self.assertIn(
            "경기 결과를 처리하고 있습니다",
            interaction.response.messages[0]["message"]
        )

    async def test_cancel_error_rolls_back_transaction(
        self
    ):
        active_room = DummyRoom(
            room_id="1"
        )

        join_cog = DummyJoinCog(
            active_room
        )

        interaction = DummyInteraction()

        cog = AdminMatch(
            DummyBot()
        )

        with (
            patch(
                "cogs.admin_match.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_match.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.admin_match.get_last_match",
                return_value={
                    "id": 10,
                    "season_id": None,
                    "mvp_discord_id": None
                }
            ),
            patch(
                "cogs.admin_match.get_match_players",
                return_value=[
                    {
                        "discord_id": "1001"
                    }
                ]
            ),
            patch(
                "cogs.admin_match.begin_transaction"
            ) as begin_mock,
            patch(
                "cogs.admin_match.commit_transaction"
            ) as commit_mock,
            patch(
                "cogs.admin_match.rollback_transaction"
            ) as rollback_mock,
            patch(
                "cogs.admin_match.PlayerService.get",
                side_effect=RuntimeError(
                    "강제 복구 오류"
                )
            )
        ):
            await AdminMatch.cancel_match.callback(
                cog,
                interaction
            )

        begin_mock.assert_called_once()
        rollback_mock.assert_called_once()
        commit_mock.assert_not_called()

        self.assertFalse(
            active_room.match_transaction_active
        )

        self.assertFalse(
            active_room.match_transaction_committed
        )

        self.assertTrue(
            interaction.response.deferred
        )

        self.assertEqual(
            len(interaction.followup.messages),
            1
        )

        self.assertIn(
            "모든 데이터 변경을 취소",
            interaction
            .followup
            .messages[0]["message"]
        )


if __name__ == "__main__":
    unittest.main()
