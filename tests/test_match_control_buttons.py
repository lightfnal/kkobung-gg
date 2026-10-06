import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from views.join_view import MatchControlView


class DummyRoom:
    def __init__(self, match_in_progress=False):
        self.room_id = "1"
        self.room_name = "내전 1"
        self.current_teams = {
            "red": {"TOP": "101"},
            "blue": {"TOP": "202"},
        }
        self.match_in_progress = match_in_progress
        self.operation_lock = asyncio.Lock()


class DummyJoinCog:
    def __init__(self, room):
        self.active_room = room
        self.bot = SimpleNamespace(get_cog=lambda name: None)

    @property
    def current_teams(self):
        return self.active_room.current_teams

    def activate_room(self, room):
        self.active_room = room
        return True


class TestMatchControlButtons(unittest.IsolatedAsyncioTestCase):
    async def test_button_states_follow_match_state(self):
        room = DummyRoom(match_in_progress=False)
        view = MatchControlView(DummyJoinCog(room))

        self.assertFalse(view.start_button.disabled)
        self.assertTrue(view.red_button.disabled)
        self.assertTrue(view.blue_button.disabled)

        room.match_in_progress = True
        in_game_view = MatchControlView(DummyJoinCog(room))
        self.assertTrue(in_game_view.start_button.disabled)
        self.assertFalse(in_game_view.red_button.disabled)
        self.assertFalse(in_game_view.blue_button.disabled)

    async def test_only_match_participants_can_use_controls(self):
        room = DummyRoom()
        join_cog = DummyJoinCog(room)
        view = MatchControlView(join_cog)

        participant = SimpleNamespace(
            user=SimpleNamespace(id=101),
            guild=None,
            response=SimpleNamespace(send_message=AsyncMock()),
        )
        outsider = SimpleNamespace(
            user=SimpleNamespace(id=303),
            guild=None,
            response=SimpleNamespace(send_message=AsyncMock()),
        )

        self.assertTrue(await view.interaction_check(participant))
        self.assertFalse(await view.interaction_check(outsider))
        outsider.response.send_message.assert_awaited_once()
        self.assertIn("참가자만", outsider.response.send_message.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
