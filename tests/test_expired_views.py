import unittest

from types import SimpleNamespace
from unittest.mock import AsyncMock

from views.join_view import (
    ExpiredInhouseView,
    MatchControlView
)


class TestExpiredViews(
    unittest.IsolatedAsyncioTestCase
):

    async def test_restart_fallback_button_explains_expiration(
        self
    ):
        view = ExpiredInhouseView()
        interaction = SimpleNamespace(
            response=SimpleNamespace(
                send_message=AsyncMock()
            )
        )

        await view.children[0].callback(interaction)

        interaction.response.send_message.assert_awaited_once()
        call = interaction.response.send_message.await_args
        self.assertIn("재시작", call.args[0])
        self.assertIn("만료", call.args[0])
        self.assertIn("/내전모집", call.args[0])
        self.assertTrue(call.kwargs["ephemeral"])

    async def test_old_match_button_is_rejected_after_team_regeneration(
        self
    ):
        original_teams = {
            "red": {"TOP": "1"},
            "blue": {"TOP": "2"}
        }
        room = SimpleNamespace(
            room_id="1",
            current_teams=original_teams
        )

        class DummyJoinCog:

            def __init__(self):
                self.active_room = room

            def activate_room(self, target_room):
                self.active_room = target_room
                return True

            @property
            def current_teams(self):
                return self.active_room.current_teams

        view = MatchControlView(DummyJoinCog())
        room.current_teams = {
            "red": {"TOP": "3"},
            "blue": {"TOP": "4"}
        }
        interaction = SimpleNamespace(
            response=SimpleNamespace(
                send_message=AsyncMock()
            )
        )

        result = await view.interaction_check(interaction)

        self.assertFalse(result)
        call = interaction.response.send_message.await_args
        self.assertIn("팀이 다시 생성", call.args[0])
        self.assertIn("만료", call.args[0])
        self.assertTrue(call.kwargs["ephemeral"])


if __name__ == "__main__":
    unittest.main()
