import asyncio
import unittest

from config import MVP_VOTE_TIMEOUT_SECONDS
from views.mvp_vote_view import MVPVoteView


class DummyBot:

    def get_user(
        self,
        user_id
    ):
        return None


class DummyJoinCog:

    def __init__(self):
        # 실제 Join Cog처럼 현재 활성 방을 가리킵니다.
        self.active_room = self

        self.current_teams = {
            "red": {
                "TOP": "1001",
                "JUNGLE": "1002",
                "MID": "1003",
                "ADC": "1004",
                "SUPPORT": "1005"
            },
            "blue": {
                "TOP": "2001",
                "JUNGLE": "2002",
                "MID": "2003",
                "ADC": "2004",
                "SUPPORT": "2005"
            }
        }

    def activate_room(
        self,
        room
    ):
        self.active_room = room
        return True


class TestMVPVote(
    unittest.IsolatedAsyncioTestCase
):

    async def test_timeout_uses_configured_duration(
        self
    ):
        async def result_callback(
            votes
        ):
            return None

        view = MVPVoteView(
            bot=DummyBot(),
            join_cog=DummyJoinCog(),
            winner="red",
            callback=result_callback
        )

        self.assertEqual(
            MVP_VOTE_TIMEOUT_SECONDS,
            10
        )
        self.assertEqual(
            view.timeout,
            MVP_VOTE_TIMEOUT_SECONDS
        )

    async def test_simultaneous_finish_runs_once(
        self
    ):
        callback_count = 0

        async def result_callback(
            votes
        ):
            nonlocal callback_count

            # 동시에 실행될 가능성을 높이기 위해
            # 잠깐 실행권을 넘깁니다.
            await asyncio.sleep(0)

            callback_count += 1

        view = MVPVoteView(
            bot=DummyBot(),
            join_cog=DummyJoinCog(),
            winner="red",
            callback=result_callback
        )

        results = await asyncio.gather(
            view.finish_vote_once(),
            view.finish_vote_once(),
            view.finish_vote_once()
        )

        self.assertEqual(
            callback_count,
            1
        )

        self.assertEqual(
            results.count(True),
            1
        )

        self.assertEqual(
            results.count(False),
            2
        )

        self.assertTrue(
            view.finished
        )

    async def test_timeout_runs_callback_once(
        self
    ):
        callback_count = 0

        async def result_callback(
            votes
        ):
            nonlocal callback_count
            callback_count += 1

        view = MVPVoteView(
            bot=DummyBot(),
            join_cog=DummyJoinCog(),
            winner="blue",
            callback=result_callback
        )

        await asyncio.gather(
            view.on_timeout(),
            view.on_timeout()
        )

        self.assertEqual(
            callback_count,
            1
        )

        self.assertTrue(
            view.finished
        )


if __name__ == "__main__":
    unittest.main()
