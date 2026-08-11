import unittest

from unittest.mock import (
    AsyncMock,
    patch
)

from cogs.join import Join
from services.room_state import InhouseRoom


class DummyRoomManager:

    def __init__(
        self,
        rooms
    ):
        self.rooms = rooms

    def get_rooms(self):
        return self.rooms


class DummyJoinCog:

    def __init__(
        self,
        rooms
    ):
        self.room_manager = (
            DummyRoomManager(
                rooms
            )
        )


class TestRestartRecovery(
    unittest.TestCase
):

    @patch(
        "cogs.join.save_room_manager"
    )
    def test_restart_normalizes_room_state(
        self,
        save_room_manager
    ):
        room = InhouseRoom(
            room_id="1",
            room_name="내전 1"
        )

        room.players = {
            1001: {
                "nickname": "참가자"
            }
        }

        room.current_teams = {
            "red": {
                "TOP": 1001
            },
            "blue": {
                "TOP": 2001
            }
        }

        room.last_team_signature = (
            "이전 팀"
        )

        room.current_recruit_view = object()
        room.mvp_vote_in_progress = True

        room.match_transaction_active = True
        room.match_transaction_committed = True

        room.transaction_series_score = {
            "red": 1,
            "blue": 0
        }

        room.transaction_series_game = 1

        join_cog = DummyJoinCog(
            [room]
        )

        Join.prepare_rooms_after_restart(
            join_cog
        )

        self.assertIn(
            "1001",
            room.players
        )

        self.assertEqual(
            room.current_teams["red"]["TOP"],
            "1001"
        )

        self.assertEqual(
            room.current_teams["blue"]["TOP"],
            "2001"
        )

        self.assertIsNone(
            room.last_team_signature
        )

        self.assertIsNone(
            room.current_recruit_view
        )

        self.assertFalse(
            room.mvp_vote_in_progress
        )

        self.assertFalse(
            room.match_transaction_active
        )

        self.assertFalse(
            room.match_transaction_committed
        )

        self.assertIsNone(
            room.transaction_series_score
        )

        self.assertIsNone(
            room.transaction_series_game
        )

        save_room_manager.assert_called_once_with(
            join_cog.room_manager
        )

    @patch(
        "cogs.join.save_room_manager"
    )
    def test_match_without_teams_is_repaired(
        self,
        save_room_manager
    ):
        room = InhouseRoom(
            room_id="2",
            room_name="내전 2"
        )

        room.current_teams = None
        room.match_in_progress = True

        join_cog = DummyJoinCog(
            [room]
        )

        Join.prepare_rooms_after_restart(
            join_cog
        )

        self.assertFalse(
            room.match_in_progress
        )

    @patch(
        "cogs.join.save_room_manager"
    )
    def test_invalid_teams_are_removed(
        self,
        save_room_manager
    ):
        room = InhouseRoom(
            room_id="3",
            room_name="내전 3"
        )

        room.current_teams = {
            "red": {
                "TOP": "1001"
            }
        }

        room.match_in_progress = True

        join_cog = DummyJoinCog(
            [room]
        )

        Join.prepare_rooms_after_restart(
            join_cog
        )

        self.assertIsNone(
            room.current_teams
        )

        self.assertFalse(
            room.match_in_progress
        )

    @patch(
        "cogs.join.save_room_manager"
    )
    def test_every_room_is_recovered_independently(
        self,
        save_room_manager
    ):
        first_room = InhouseRoom(
            room_id="1",
            room_name="내전 1"
        )

        second_room = InhouseRoom(
            room_id="2",
            room_name="내전 2"
        )

        third_room = InhouseRoom(
            room_id="3",
            room_name="내전 3"
        )

        first_room.players = {
            1001: {}
        }

        second_room.players = {
            2001: {}
        }

        third_room.players = {
            3001: {}
        }

        join_cog = DummyJoinCog(
            [
                first_room,
                second_room,
                third_room
            ]
        )

        Join.prepare_rooms_after_restart(
            join_cog
        )

        self.assertEqual(
            set(first_room.players),
            {"1001"}
        )

        self.assertEqual(
            set(second_room.players),
            {"2001"}
        )

        self.assertEqual(
            set(third_room.players),
            {"3001"}
        )


    @patch(
        "cogs.join.save_room_manager"
    )
    def test_valid_bo3_state_is_preserved(
        self,
        save_room_manager
    ):
        room = InhouseRoom(
            room_id="1",
            room_name="내전 1",
            guild_id=100,
            channel_id=200,
            output_channel_id=300,
            waiting_voice_channel_id=400,
            red_voice_channel_id=500,
            blue_voice_channel_id=600
        )

        room.players = {
            "1001": {},
            "1002": {}
        }

        room.current_teams = {
            "red": {
                "TOP": "1001"
            },
            "blue": {
                "TOP": "1002"
            }
        }

        room.match_in_progress = True

        room.series_score = {
            "red": 1,
            "blue": 1
        }

        room.series_game = 2

        join_cog = DummyJoinCog(
            [room]
        )

        Join.prepare_rooms_after_restart(
            join_cog
        )

        self.assertTrue(
            room.match_in_progress
        )

        self.assertEqual(
            room.series_score,
            {
                "red": 1,
                "blue": 1
            }
        )

        self.assertEqual(
            room.series_game,
            2
        )

        self.assertEqual(
            room.output_channel_id,
            300
        )

        self.assertEqual(
            room.waiting_voice_channel_id,
            400
        )

        self.assertEqual(
            room.red_voice_channel_id,
            500
        )

        self.assertEqual(
            room.blue_voice_channel_id,
            600
        )

    @patch(
        "cogs.join.save_room_manager"
    )
    def test_bo3_states_do_not_leak_between_rooms(
        self,
        save_room_manager
    ):
        first_room = InhouseRoom(
            room_id="1",
            room_name="내전 1"
        )

        second_room = InhouseRoom(
            room_id="2",
            room_name="내전 2"
        )

        third_room = InhouseRoom(
            room_id="3",
            room_name="내전 3"
        )

        first_room.series_score = {
            "red": 1,
            "blue": 0
        }
        first_room.series_game = 1

        second_room.series_score = {
            "red": 0,
            "blue": 1
        }
        second_room.series_game = 1

        third_room.series_score = {
            "red": 1,
            "blue": 1
        }
        third_room.series_game = 2

        join_cog = DummyJoinCog(
            [
                first_room,
                second_room,
                third_room
            ]
        )

        Join.prepare_rooms_after_restart(
            join_cog
        )

        self.assertEqual(
            first_room.series_score,
            {
                "red": 1,
                "blue": 0
            }
        )

        self.assertEqual(
            second_room.series_score,
            {
                "red": 0,
                "blue": 1
            }
        )

        self.assertEqual(
            third_room.series_score,
            {
                "red": 1,
                "blue": 1
            }
        )

        self.assertEqual(
            first_room.series_game,
            1
        )

        self.assertEqual(
            second_room.series_game,
            1
        )

        self.assertEqual(
            third_room.series_game,
            2
        )

    @patch(
        "cogs.join.save_room_manager"
    )
    def test_committed_pending_result_is_recovered(
        self,
        save_room_manager
    ):
        """
        JSON에 대기 중인 결과가 있고 SQLite에도 같은
        토큰과 방 번호의 경기가 존재하면 BO3 점수를 확정합니다.
        """

        room = InhouseRoom(
            room_id="1",
            room_name="내전 1"
        )

        # 경기 결과 처리 전의 기존 점수
        room.series_score = {
            "red": 0,
            "blue": 0
        }
        room.series_game = 0
        room.match_in_progress = True

        # SQLite 저장 성공 시 적용할 예정이었던 점수
        room.pending_match_token = (
            "committed-token"
        )
        room.pending_series_score = {
            "red": 1,
            "blue": 0
        }
        room.pending_series_game = 1

        join_cog = DummyJoinCog(
            [room]
        )

        with patch(
            "cogs.join.get_match_by_result_token",
            return_value={
                "id": 100,
                "room_id": "1",
                "result_token": (
                    "committed-token"
                )
            }
        ) as get_match:
            Join.prepare_rooms_after_restart(
                join_cog
            )

        get_match.assert_called_once_with(
            "committed-token"
        )

        # SQLite에 결과가 있으므로 예정 점수를 확정
        self.assertEqual(
            room.series_score,
            {
                "red": 1,
                "blue": 0
            }
        )

        self.assertEqual(
            room.series_game,
            1
        )

        self.assertFalse(
            room.match_in_progress
        )

        # 복구가 끝났으므로 대기 표식 제거
        self.assertIsNone(
            room.pending_match_token
        )

        self.assertIsNone(
            room.pending_series_score
        )

        self.assertIsNone(
            room.pending_series_game
        )

        save_room_manager.assert_called_once_with(
            join_cog.room_manager
        )

    @patch(
        "cogs.join.save_room_manager"
    )
    def test_uncommitted_pending_result_is_cancelled(
        self,
        save_room_manager
    ):
        """
        JSON에는 대기 결과가 있지만 SQLite에 같은 토큰의
        경기가 없으면 기존 BO3 점수를 유지합니다.
        """

        room = InhouseRoom(
            room_id="2",
            room_name="내전 2"
        )

        room.series_score = {
            "red": 1,
            "blue": 0
        }
        room.series_game = 1

        room.pending_match_token = (
            "uncommitted-token"
        )
        room.pending_series_score = {
            "red": 1,
            "blue": 1
        }
        room.pending_series_game = 2

        join_cog = DummyJoinCog(
            [room]
        )

        with patch(
            "cogs.join.get_match_by_result_token",
            return_value=None
        ) as get_match:
            Join.prepare_rooms_after_restart(
                join_cog
            )

        get_match.assert_called_once_with(
            "uncommitted-token"
        )

        # DB에 결과가 없으므로 기존 점수를 그대로 유지
        self.assertEqual(
            room.series_score,
            {
                "red": 1,
                "blue": 0
            }
        )

        self.assertEqual(
            room.series_game,
            1
        )

        # 처리되지 않은 대기 표식은 제거
        self.assertIsNone(
            room.pending_match_token
        )

        self.assertIsNone(
            room.pending_series_score
        )

        self.assertIsNone(
            room.pending_series_game
        )

        save_room_manager.assert_called_once_with(
            join_cog.room_manager
        )

    @patch(
        "cogs.join.save_room_manager"
    )
    def test_pending_result_from_other_room_is_rejected(
        self,
        save_room_manager
    ):
        """
        토큰이 SQLite에 존재하더라도 다른 내전 방의
        경기라면 현재 방에 BO3 점수를 적용하지 않습니다.
        """

        room = InhouseRoom(
            room_id="3",
            room_name="내전 3"
        )

        room.series_score = {
            "red": 0,
            "blue": 1
        }
        room.series_game = 1

        room.pending_match_token = (
            "wrong-room-token"
        )
        room.pending_series_score = {
            "red": 1,
            "blue": 1
        }
        room.pending_series_game = 2

        join_cog = DummyJoinCog(
            [room]
        )

        with patch(
            "cogs.join.get_match_by_result_token",
            return_value={
                "id": 200,
                # 토큰은 있지만 2번 방 경기입니다.
                "room_id": "2",
                "result_token": (
                    "wrong-room-token"
                )
            }
        ) as get_match:
            Join.prepare_rooms_after_restart(
                join_cog
            )

        get_match.assert_called_once_with(
            "wrong-room-token"
        )

        # 다른 방의 결과이므로 기존 점수 유지
        self.assertEqual(
            room.series_score,
            {
                "red": 0,
                "blue": 1
            }
        )

        self.assertEqual(
            room.series_game,
            1
        )

        self.assertIsNone(
            room.pending_match_token
        )

        self.assertIsNone(
            room.pending_series_score
        )

        self.assertIsNone(
            room.pending_series_game
        )

        save_room_manager.assert_called_once_with(
            join_cog.room_manager
        )

class TestRestartRecoveryMessages(
    unittest.IsolatedAsyncioTestCase
):

    def create_join_cog(
        self,
        rooms
    ):
        """
        Discord 복구 안내 테스트에 사용할
        최소 Join Cog 객체를 생성합니다.
        """

        join_cog = DummyJoinCog(
            rooms
        )

        join_cog._restart_recovery_message_sent = False
        join_cog._recovered_result_room_ids = set()

        join_cog.get_room_recruit_channel = AsyncMock(
            return_value=None
        )

        join_cog.send_output_message = AsyncMock(
            return_value=(
                object(),
                False
            )
        )

        return join_cog

    async def test_empty_room_skips_recovery_message(
        self
    ):
        """
        참가자, 팀, 복구 결과가 모두 없는 빈 방에는
        복구 안내를 보내지 않습니다.
        """

        room = InhouseRoom(
            room_id="1",
            room_name="내전 1"
        )

        join_cog = self.create_join_cog(
            [room]
        )

        await Join.send_restart_recovery_messages(
            join_cog
        )

        join_cog.send_output_message.assert_not_awaited()

        self.assertTrue(
            join_cog._restart_recovery_message_sent
        )

    async def test_recruiting_room_sends_player_recovery_message(
        self
    ):
        """
        참가자 모집 중이던 방은 참가 인원과
        /내전모집 재실행 안내를 전송합니다.
        """

        room = InhouseRoom(
            room_id="1",
            room_name="내전 1",
            channel_id=100
        )

        room.players = {
            "1001": {
                "nickname": "참가자 1"
            },
            "1002": {
                "nickname": "참가자 2"
            }
        }

        join_cog = self.create_join_cog(
            [room]
        )

        fallback_channel = object()

        join_cog.get_room_recruit_channel = AsyncMock(
            return_value=fallback_channel
        )

        await Join.send_restart_recovery_messages(
            join_cog
        )

        join_cog.send_output_message.assert_awaited_once()

        call_kwargs = (
            join_cog
            .send_output_message
            .await_args
            .kwargs
        )

        self.assertIs(
            call_kwargs["room"],
            room
        )

        self.assertIs(
            call_kwargs["fallback_channel"],
            fallback_channel
        )

        embed = call_kwargs["embed"]

        field_values = "\n".join(
            field.value
            for field in embed.fields
        )

        self.assertIn(
            "2/10명",
            field_values
        )

        self.assertIn(
            "/내전모집",
            field_values
        )

    async def test_team_room_sends_bo3_recovery_message(
        self
    ):
        """
        팀이 생성된 방은 현재 BO3 점수와
        경기 번호를 안내합니다.
        """

        room = InhouseRoom(
            room_id="2",
            room_name="내전 2"
        )

        room.players = {
            "1001": {},
            "1002": {}
        }

        room.current_teams = {
            "red": {
                "TOP": "1001"
            },
            "blue": {
                "TOP": "1002"
            }
        }

        room.series_score = {
            "red": 1,
            "blue": 0
        }

        room.series_game = 2
        room.match_in_progress = True

        join_cog = self.create_join_cog(
            [room]
        )

        await Join.send_restart_recovery_messages(
            join_cog
        )

        call_kwargs = (
            join_cog
            .send_output_message
            .await_args
            .kwargs
        )

        embed = call_kwargs["embed"]

        field_values = "\n".join(
            field.value
            for field in embed.fields
        )

        self.assertIn(
            "레드팀 **1**",
            field_values
        )

        self.assertIn(
            "**0**",
            field_values
        )

        self.assertIn(
            "2경기",
            field_values
        )

        self.assertIn(
            "경기 진행 상태가 복구되었습니다.",
            field_values
        )

    async def test_recovered_result_room_includes_result_notice(
        self
    ):
        """
        SQLite 커밋 결과가 복구된 방에는
        경기 결과 복구 완료 안내를 포함합니다.
        """

        room = InhouseRoom(
            room_id="3",
            room_name="내전 3"
        )

        room.current_teams = {
            "red": {
                "TOP": "1001"
            },
            "blue": {
                "TOP": "2001"
            }
        }

        room.series_score = {
            "red": 1,
            "blue": 1
        }

        room.series_game = 2

        join_cog = self.create_join_cog(
            [room]
        )

        join_cog._recovered_result_room_ids.add(
            "3"
        )

        await Join.send_restart_recovery_messages(
            join_cog
        )

        call_kwargs = (
            join_cog
            .send_output_message
            .await_args
            .kwargs
        )

        embed = call_kwargs["embed"]

        field_names = [
            field.name
            for field in embed.fields
        ]

        field_values = "\n".join(
            field.value
            for field in embed.fields
        )

        self.assertIn(
            "✅ 경기 결과 복구 완료",
            field_names
        )

        self.assertIn(
            "SQLite",
            field_values
        )

        self.assertIn(
            "BO3 점수를 정상적으로 복구했습니다.",
            field_values
        )

    async def test_multiple_rooms_send_independent_messages(
        self
    ):
        """
        상태가 있는 여러 방은 각각 독립적인
        복구 안내 메시지를 전송합니다.
        """

        first_room = InhouseRoom(
            room_id="1",
            room_name="내전 1"
        )

        second_room = InhouseRoom(
            room_id="2",
            room_name="내전 2"
        )

        third_room = InhouseRoom(
            room_id="3",
            room_name="빈 방"
        )

        first_room.players = {
            "1001": {}
        }

        second_room.current_teams = {
            "red": {
                "TOP": "2001"
            },
            "blue": {
                "TOP": "2002"
            }
        }

        join_cog = self.create_join_cog(
            [
                first_room,
                second_room,
                third_room
            ]
        )

        await Join.send_restart_recovery_messages(
            join_cog
        )

        self.assertEqual(
            join_cog.send_output_message.await_count,
            2
        )

        sent_rooms = [
            await_call.kwargs["room"].room_id
            for await_call
            in join_cog.send_output_message.await_args_list
        ]

        self.assertEqual(
            sent_rooms,
            [
                "1",
                "2"
            ]
        )

    async def test_recovery_message_is_sent_only_once(
        self
    ):
        """
        on_ready가 여러 번 실행돼도 같은 프로세스에서는
        복구 안내를 한 번만 전송합니다.
        """

        room = InhouseRoom(
            room_id="1",
            room_name="내전 1"
        )

        room.players = {
            "1001": {}
        }

        join_cog = self.create_join_cog(
            [room]
        )

        await Join.send_restart_recovery_messages(
            join_cog
        )

        await Join.send_restart_recovery_messages(
            join_cog
        )

        join_cog.send_output_message.assert_awaited_once()

    async def test_send_output_message_marks_fallback_channel(
        self
    ):
        """
        공용 출력 채널을 사용할 수 없어 모집 채널로
        전송한 경우 used_fallback이 True가 됩니다.
        """

        room = InhouseRoom(
            room_id="1",
            room_name="내전 1",
            output_channel_id=999
        )

        fallback_channel = AsyncMock()
        fallback_channel.id = 100

        sent_message = object()

        fallback_channel.send = AsyncMock(
            return_value=sent_message
        )

        join_cog = DummyJoinCog(
            [room]
        )

        join_cog.active_room = room

        join_cog.get_output_channel = AsyncMock(
            return_value=fallback_channel
        )

        message, used_fallback = (
            await Join.send_output_message(
                join_cog,
                room=room,
                fallback_channel=fallback_channel,
                content="복구 안내"
            )
        )

        self.assertIs(
            message,
            sent_message
        )

        self.assertTrue(
            used_fallback
        )

        fallback_channel.send.assert_awaited_once()

        sent_content = (
            fallback_channel
            .send
            .await_args
            .kwargs["content"]
        )

        self.assertIn("채널 보기", sent_content)
        self.assertIn("메시지 보내기", sent_content)
        self.assertIn("복구 안내", sent_content)


if __name__ == "__main__":
    unittest.main()
