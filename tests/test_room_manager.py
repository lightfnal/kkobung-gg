import unittest

from services.room_manager import (
    RoomManager
)


class TestRoomManager(
    unittest.TestCase
):

    def test_create_and_get_room(self):
        manager = RoomManager(
            max_rooms=3
        )

        room = manager.create_room(
            room_id="1",
            room_name="내전 1",
            guild_id=100,
            channel_id=200
        )

        self.assertIs(
            manager.get_room("1"),
            room
        )

        self.assertEqual(
            room.room_name,
            "내전 1"
        )

        self.assertEqual(
            len(manager.get_rooms()),
            1
        )

    def test_maximum_room_limit(self):
        manager = RoomManager(
            max_rooms=3
        )

        for room_number in range(
            1,
            4
        ):
            manager.create_room(
                room_id=str(room_number),
                room_name=f"내전 {room_number}"
            )

        with self.assertRaises(
            RuntimeError
        ):
            manager.create_room(
                room_id="4",
                room_name="내전 4"
            )

        self.assertEqual(
            len(manager.get_rooms()),
            3
        )

    def test_duplicate_room_is_rejected(self):
        manager = RoomManager()

        manager.create_room(
            room_id="1",
            room_name="내전 1"
        )

        with self.assertRaises(
            ValueError
        ):
            manager.create_room(
                room_id="1",
                room_name="중복 내전"
            )

    def test_find_room_by_channel_and_player(
        self
    ):
        manager = RoomManager()

        first_room = manager.create_room(
            room_id="1",
            room_name="내전 1",
            guild_id=100,
            channel_id=201
        )

        second_room = manager.create_room(
            room_id="2",
            room_name="내전 2",
            guild_id=100,
            channel_id=202
        )

        second_room.players["9001"] = {
            "nickname": "테스트 참가자"
        }

        self.assertIs(
            manager.get_room_by_channel(
                guild_id=100,
                channel_id=201
            ),
            first_room
        )

        self.assertIs(
            manager.find_player_room(
                "9001"
            ),
            second_room
        )

        self.assertIsNone(
            manager.find_player_room(
                "없는 사용자"
            )
        )

    def test_save_and_restore_rooms(self):
        manager = RoomManager(
            max_rooms=3
        )

        first_room = manager.create_room(
            room_id="1",
            room_name="내전 1",
            guild_id=100,
            channel_id=201
        )

        second_room = manager.create_room(
            room_id="2",
            room_name="내전 2",
            guild_id=100,
            channel_id=202
        )

        first_room.players["1001"] = {
            "nickname": "1번 참가자"
        }

        second_room.players["2001"] = {
            "nickname": "2번 참가자"
        }

        saved_data = manager.to_dict()

        restored_manager = (
            RoomManager.from_dict(
                saved_data,
                max_rooms=3
            )
        )

        self.assertEqual(
            len(restored_manager.get_rooms()),
            2
        )

        self.assertIn(
            "1001",
            restored_manager
            .get_room("1")
            .players
        )

        self.assertIn(
            "2001",
            restored_manager
            .get_room("2")
            .players
        )

        removed_room = (
            restored_manager.remove_room(
                "2"
            )
        )

        self.assertIsNotNone(
            removed_room
        )

        self.assertIsNone(
            restored_manager.get_room("2")
        )


if __name__ == "__main__":
    unittest.main()