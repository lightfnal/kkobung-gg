import asyncio
import unittest

from config import MVP_VOTE_TIMEOUT_SECONDS
from views.mvp_vote_view import MVPVoteView


class DummyBot:

    def __init__(self, guild=None):
        self.guild = guild
        self.guilds = (
            [guild]
            if guild is not None
            else []
        )

    def get_guild(
        self,
        guild_id
    ):
        if (
            self.guild is not None
            and self.guild.id == guild_id
        ):
            return self.guild
        return None

    def get_user(
        self,
        user_id
    ):
        return None


class DummyJoinCog:

    def __init__(self):
        # 실제 Join Cog처럼 현재 활성 방을 가리킵니다.
        self.active_room = self
        self.guild_id = 777

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

    async def test_buttons_use_current_guild_display_name(
        self
    ):
        class DummyGuild:
            id = 777

            def get_member(
                self,
                user_id
            ):
                if user_id == 1001:
                    return type(
                        "Member",
                        (),
                        {
                            "display_name": (
                                "1티어케이틀린#ADC / E / SUPPORT ADC"
                            )
                        }
                    )()
                return None

        async def result_callback(
            votes
        ):
            return None

        view = MVPVoteView(
            bot=DummyBot(DummyGuild()),
            join_cog=DummyJoinCog(),
            winner="red",
            callback=result_callback
        )

        self.assertEqual(
            view.children[0].label,
            "TOP - 1티어케이틀린#ADC / E / SUPPORT ADC"
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

    async def test_vote_acknowledges_before_waiting_for_room_lock(
        self
    ):
        class DummyResponse:

            def __init__(self):
                self.deferred = False

            async def defer(self):
                self.deferred = True

        class DummyFollowup:

            async def send(self, *args, **kwargs):
                return None

        join_cog = DummyJoinCog()
        join_cog.operation_lock = asyncio.Lock()
        join_cog.match_in_progress = True
        join_cog.mvp_vote_in_progress = True

        async def result_callback(votes):
            return None

        view = MVPVoteView(
            bot=DummyBot(),
            join_cog=join_cog,
            winner="red",
            callback=result_callback
        )

        interaction = type(
            "Interaction",
            (),
            {
                "user": type("User", (), {"id": 2001})(),
                "response": DummyResponse(),
                "followup": DummyFollowup(),
                "message": None
            }
        )()

        await join_cog.operation_lock.acquire()
        task = asyncio.create_task(
            view.children[0].callback(interaction)
        )

        try:
            await asyncio.sleep(0)
            self.assertTrue(
                interaction.response.deferred,
                "the interaction must be acknowledged while the room lock is held"
            )
        finally:
            join_cog.operation_lock.release()

        await task

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
