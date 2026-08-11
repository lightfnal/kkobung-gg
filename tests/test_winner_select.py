import asyncio
import unittest

from views.winner_select_view import (
    WinnerSelectView
)


class DummyResponse:

    def __init__(self):
        self.deferred = False
        self.messages = []

    async def defer(self):
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


class DummyMessage:

    def __init__(self):
        self.edit_count = 0

    async def edit(
        self,
        **kwargs
    ):
        self.edit_count += 1


class DummyInteraction:

    def __init__(self):
        self.response = DummyResponse()
        self.message = DummyMessage()


class DummyRoom:

    def __init__(
        self,
        room_id
    ):
        self.room_id = room_id


class DummyJoinCog:

    def __init__(self):
        self.active_room = DummyRoom("1")
        self.activated_rooms = []

    def activate_room(
        self,
        room
    ):
        self.active_room = room
        self.activated_rooms.append(
            room
        )
        return True


class TestWinnerSelectView(
    unittest.IsolatedAsyncioTestCase
):

    async def test_simultaneous_selection_runs_once(
        self
    ):
        callback_count = 0

        async def callback(
            interaction,
            winner
        ):
            nonlocal callback_count

            await asyncio.sleep(0)
            callback_count += 1

        join_cog = DummyJoinCog()

        view = WinnerSelectView(
            join_cog=join_cog,
            callback=callback
        )

        first_interaction = (
            DummyInteraction()
        )

        second_interaction = (
            DummyInteraction()
        )

        await asyncio.gather(
            view.finish_selection(
                first_interaction,
                "red"
            ),
            view.finish_selection(
                second_interaction,
                "blue"
            )
        )

        self.assertEqual(
            callback_count,
            1
        )

        self.assertTrue(
            view.finished
        )

    async def test_timeout_and_selection_do_not_overlap(
        self
    ):
        callback_count = 0

        async def callback(
            interaction,
            winner
        ):
            nonlocal callback_count
            callback_count += 1

        join_cog = DummyJoinCog()

        view = WinnerSelectView(
            join_cog=join_cog,
            callback=callback
        )

        interaction = DummyInteraction()

        await asyncio.gather(
            view.finish_selection(
                interaction,
                "red"
            ),
            view.on_timeout()
        )

        self.assertEqual(
            callback_count,
            1
        )

        self.assertTrue(
            view.finished
        )

    async def test_original_room_is_reactivated(
        self
    ):
        selected_winner = None

        async def callback(
            interaction,
            winner
        ):
            nonlocal selected_winner
            selected_winner = winner

        join_cog = DummyJoinCog()

        original_room = (
            join_cog.active_room
        )

        view = WinnerSelectView(
            join_cog=join_cog,
            callback=callback
        )

        # 다른 내전 방이 활성화된 상황을 흉내 냅니다.
        join_cog.active_room = (
            DummyRoom("2")
        )

        await view.finish_selection(
            DummyInteraction(),
            "blue"
        )

        self.assertIs(
            join_cog.active_room,
            original_room
        )

        self.assertEqual(
            selected_winner,
            "blue"
        )


if __name__ == "__main__":
    unittest.main()