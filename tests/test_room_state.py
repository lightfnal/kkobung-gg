import unittest

from services.room_state import (
    InhouseRoom
)


class TestInhouseRoom(
    unittest.TestCase
):

    def test_default_room_state(self):
        room = InhouseRoom(
            room_id="1",
            room_name="내전 1"
        )

        self.assertEqual(
            room.room_id,
            "1"
        )

        self.assertEqual(
            room.room_name,
            "내전 1"
        )

        self.assertEqual(
            room.players,
            {}
        )

        self.assertIsNone(
            room.current_teams
        )

        self.assertFalse(
            room.match_in_progress
        )

        self.assertEqual(
            room.series_score,
            {
                "red": 0,
                "blue": 0
            }
        )

        self.assertEqual(
            room.series_game,
            0
        )

    def test_rooms_have_independent_state(self):
        first_room = InhouseRoom(
            room_id="1",
            room_name="내전 1"
        )

        second_room = InhouseRoom(
            room_id="2",
            room_name="내전 2"
        )

        first_room.players["1001"] = {
            "nickname": "첫 번째 참가자"
        }

        first_room.series_score["red"] = 1

        self.assertEqual(
            len(first_room.players),
            1
        )

        self.assertEqual(
            second_room.players,
            {}
        )

        self.assertEqual(
            first_room.series_score["red"],
            1
        )

        self.assertEqual(
            second_room.series_score["red"],
            0
        )

    def test_reset_and_restore_room(self):
        room = InhouseRoom(
            room_id="2",
            room_name="내전 2",
            guild_id=1234,
            channel_id=5678,
            output_channel_id=901,
            waiting_voice_channel_id=902,
            red_voice_channel_id=903,
            blue_voice_channel_id=904
        )

        room.players["1001"] = {
            "nickname": "테스트 참가자"
        }

        room.current_teams = {
            "red": {
                "TOP": "1001"
            },
            "blue": {
                "TOP": "2001"
            }
        }

        room.match_in_progress = True
        room.series_score["red"] = 1
        room.series_game = 1
        room.mvp_vote_in_progress = True

        saved_data = room.to_dict()

        restored_room = (
            InhouseRoom.from_dict(
                saved_data
            )
        )

        self.assertEqual(
            restored_room.room_id,
            "2"
        )

        self.assertEqual(
            restored_room.players,
            room.players
        )

        self.assertEqual(
            restored_room.current_teams,
            room.current_teams
        )

        self.assertTrue(
            restored_room.match_in_progress
        )

        self.assertEqual(
            restored_room.series_score["red"],
            1
        )

        restored_room.reset_game()

        self.assertEqual(
            restored_room.players,
            {}
        )

        self.assertIsNone(
            restored_room.current_teams
        )

        self.assertFalse(
            restored_room.match_in_progress
        )

        self.assertEqual(
            restored_room.series_score,
            {
                "red": 0,
                "blue": 0
            }
        )

        self.assertEqual(
            restored_room.series_game,
            0
        )

        # 방의 기본 정보는 초기화 후에도 유지
        self.assertEqual(
            restored_room.room_id,
            "2"
        )

        self.assertEqual(
            restored_room.guild_id,
            1234
        )

        self.assertEqual(
            restored_room.channel_id,
            5678
        )

        # 공용 진행 채널과 음성채널 설정도
        # 저장·복원 및 경기 초기화 후 유지되어야 합니다.
        self.assertEqual(
            restored_room.output_channel_id,
            901
        )

        self.assertEqual(
            restored_room.waiting_voice_channel_id,
            902
        )

        self.assertEqual(
            restored_room.red_voice_channel_id,
            903
        )

        self.assertEqual(
            restored_room.blue_voice_channel_id,
            904
        )


if __name__ == "__main__":
    unittest.main()