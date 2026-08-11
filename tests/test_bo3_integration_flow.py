import asyncio
import unittest

from services.room_manager import RoomManager


MAX_PLAYERS = 10


class TestBO3IntegrationFlow(
    unittest.IsolatedAsyncioTestCase
):

    async def join_player(
        self,
        manager,
        room,
        user_id
    ):
        async with manager.management_lock:
            if manager.find_player_room(user_id):
                return False

            async with room.operation_lock:
                if len(room.players) >= MAX_PLAYERS:
                    return False

                await asyncio.sleep(0)
                room.players[user_id] = {
                    "nickname": user_id
                }
                return True

    async def create_teams_and_start(
        self,
        room
    ):
        async with room.operation_lock:
            if len(room.players) != MAX_PLAYERS:
                return False

            player_ids = list(room.players)
            positions = (
                "TOP",
                "JUNGLE",
                "MID",
                "ADC",
                "SUPPORT"
            )
            room.current_teams = {
                "red": dict(
                    zip(positions, player_ids[:5])
                ),
                "blue": dict(
                    zip(positions, player_ids[5:])
                )
            }
            room.match_in_progress = True
            return True

    async def record_set_result(
        self,
        room,
        winner
    ):
        async with room.operation_lock:
            if not room.match_in_progress:
                return False

            if max(room.series_score.values()) >= 2:
                return False

            room.mvp_vote_in_progress = True
            await asyncio.sleep(0)
            room.series_score[winner] += 1
            room.series_game += 1
            room.mvp_vote_in_progress = False
            room.match_in_progress = False

            series_finished = (
                room.series_score[winner] >= 2
            )

            if series_finished:
                room.reset_game()

            return True

    async def start_next_set(
        self,
        room
    ):
        async with room.operation_lock:
            if room.current_teams is None:
                return False

            if room.match_in_progress:
                return False

            if max(room.series_score.values()) >= 2:
                return False

            room.match_in_progress = True
            return True

    async def test_three_rooms_complete_independent_bo3_after_restart(
        self
    ):
        manager = RoomManager(max_rooms=3)
        rooms = [
            manager.create_room(
                room_id=str(room_number),
                room_name=f"내전 {room_number}",
                guild_id=100,
                channel_id=1000 + room_number
            )
            for room_number in range(1, 4)
        ]

        join_results = await asyncio.gather(
            *(
                self.join_player(
                    manager,
                    room,
                    f"room-{room.room_id}-player-{number}"
                )
                for room in rooms
                for number in range(MAX_PLAYERS)
            )
        )

        self.assertEqual(
            join_results.count(True),
            30
        )

        start_results = await asyncio.gather(
            *(
                self.create_teams_and_start(room)
                for room in rooms
            )
        )

        self.assertEqual(
            start_results,
            [True, True, True]
        )

        await asyncio.gather(
            self.record_set_result(rooms[0], "red"),
            self.record_set_result(rooms[1], "blue"),
            self.record_set_result(rooms[2], "red")
        )

        restored_manager = RoomManager.from_dict(
            manager.to_dict(),
            max_rooms=3
        )
        restored_rooms = restored_manager.get_rooms()

        self.assertEqual(
            [room.series_game for room in restored_rooms],
            [1, 1, 1]
        )
        self.assertEqual(
            [len(room.players) for room in restored_rooms],
            [10, 10, 10]
        )

        await asyncio.gather(
            *(
                self.start_next_set(room)
                for room in restored_rooms
            )
        )

        await asyncio.gather(
            self.record_set_result(restored_rooms[0], "red"),
            self.record_set_result(restored_rooms[1], "red"),
            self.record_set_result(restored_rooms[2], "red")
        )

        # 1번과 3번 방은 2:0으로 종료되어 완전히 초기화됩니다.
        for room in (
            restored_rooms[0],
            restored_rooms[2]
        ):
            self.assertEqual(room.players, {})
            self.assertIsNone(room.current_teams)
            self.assertEqual(
                room.series_score,
                {"red": 0, "blue": 0}
            )
            self.assertEqual(room.series_game, 0)

        # 2번 방은 1:1 상태를 그대로 유지합니다.
        second_room = restored_rooms[1]
        self.assertEqual(len(second_room.players), 10)
        self.assertEqual(
            second_room.series_score,
            {"red": 1, "blue": 1}
        )
        self.assertEqual(second_room.series_game, 2)

        self.assertTrue(
            await self.start_next_set(second_room)
        )
        self.assertTrue(
            await self.record_set_result(
                second_room,
                "blue"
            )
        )

        self.assertEqual(second_room.players, {})
        self.assertIsNone(second_room.current_teams)
        self.assertEqual(
            second_room.series_score,
            {"red": 0, "blue": 0}
        )
        self.assertEqual(second_room.series_game, 0)


if __name__ == "__main__":
    unittest.main()
