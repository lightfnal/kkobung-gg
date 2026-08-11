import unittest

from services.room_state import InhouseRoom
from utils.room_display import format_room_status


class TestRoomDisplay(unittest.TestCase):

    def test_recruiting_status_contains_all_operational_fields(self):
        room = InhouseRoom(
            room_id="2",
            room_name="저녁 내전"
        )
        room.players["1001"] = {}
        room.series_score = {"red": 1, "blue": 0}
        room.series_game = 1

        status = format_room_status(room)

        self.assertIn("저녁 내전", status)
        self.assertIn("방 **2**", status)
        self.assertIn("참가자 모집 중", status)
        self.assertIn("1/10명", status)
        self.assertIn("1세트", status)
        self.assertIn("🔴 1 : 0 🔵", status)

    def test_match_progress_takes_priority(self):
        room = InhouseRoom(
            room_id="1",
            room_name="내전 1"
        )
        room.current_teams = {"red": {}, "blue": {}}
        room.match_in_progress = True

        status = format_room_status(room)

        self.assertIn("경기 진행 중", status)
        self.assertNotIn("경기 시작 대기", status)


if __name__ == "__main__":
    unittest.main()
