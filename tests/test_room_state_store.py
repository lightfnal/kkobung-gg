import json
import tempfile
import unittest

from pathlib import Path
from unittest.mock import patch

from services.room_manager import (
    RoomManager
)

from storage.room_state_store import (
    clear_room_manager,
    load_room_manager,
    save_room_manager
)


class TestRoomStateStore(
    unittest.TestCase
):

    def setUp(self):
        self.temporary_directory = (
            tempfile.TemporaryDirectory()
        )

        self.state_file = (
            Path(
                self.temporary_directory.name
            )
            / "rooms_state.json"
        )

        self.path_patcher = patch(
            "storage.room_state_store."
            "ROOMS_STATE_FILE",
            self.state_file
        )

        self.path_patcher.start()

    def tearDown(self):
        self.path_patcher.stop()
        self.temporary_directory.cleanup()

    def test_missing_file_returns_empty_manager(
        self
    ):
        manager = load_room_manager(
            max_rooms=3
        )

        self.assertEqual(
            manager.get_rooms(),
            []
        )

    def test_save_and_load_room_manager(
        self
    ):
        manager = RoomManager(
            max_rooms=3
        )

        room = manager.create_room(
            room_id="1",
            room_name="내전 1",
            guild_id=100,
            channel_id=200
        )

        room.output_channel_id = 300
        room.waiting_voice_channel_id = 400
        room.red_voice_channel_id = 500
        room.blue_voice_channel_id = 600

        room.players["1001"] = {
            "nickname": "테스트 참가자"
        }

        room.series_score["red"] = 1

        save_room_manager(
            manager
        )

        restored_manager = (
            load_room_manager(
                max_rooms=3
            )
        )

        restored_room = (
            restored_manager.get_room(
                "1"
            )
        )

        self.assertIsNotNone(
            restored_room
        )

        self.assertIn(
            "1001",
            restored_room.players
        )

        self.assertEqual(
            restored_room
            .series_score["red"],
            1
        )

        self.assertEqual(
            restored_room.output_channel_id,
            300
        )

        self.assertEqual(
            restored_room.waiting_voice_channel_id,
            400
        )

        self.assertEqual(
            restored_room.red_voice_channel_id,
            500
        )

        self.assertEqual(
            restored_room.blue_voice_channel_id,
            600
        )

    def test_invalid_file_returns_empty_manager(
        self
    ):
        self.state_file.write_text(
            "{ 잘못된 JSON",
            encoding="utf-8"
        )

        manager = load_room_manager(
            max_rooms=3
        )

        self.assertEqual(
            manager.get_rooms(),
            []
        )

    def test_clear_room_manager(
        self
    ):
        manager = RoomManager(
            max_rooms=3
        )

        manager.create_room(
            room_id="1",
            room_name="내전 1"
        )

        save_room_manager(
            manager
        )

        cleared_manager = (
            clear_room_manager(
                max_rooms=3
            )
        )

        self.assertEqual(
            cleared_manager.get_rooms(),
            []
        )

        saved_data = json.loads(
            self.state_file.read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(
            saved_data,
            {}
        )


if __name__ == "__main__":
    unittest.main()