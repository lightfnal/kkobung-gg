import asyncio
import unittest

from services.room_state import InhouseRoom
from services.room_manager import RoomManager


MAX_PLAYERS = 10


class TestThreeRoomStress(
    unittest.IsolatedAsyncioTestCase
):

    def setUp(self):
        self.rooms = [
            InhouseRoom(
                room_id=str(room_number),
                room_name=f"내전 {room_number}"
            )
            for room_number in range(1, 4)
        ]

    async def join_room(
        self,
        room,
        user_id
    ):
        async with room.operation_lock:
            if user_id in room.players:
                return False

            if len(room.players) >= MAX_PLAYERS:
                return False

            # 상태 검사와 변경 사이에 실행권을 넘겨
            # 실제 동시 요청과 비슷한 경쟁 조건을 만듭니다.
            await asyncio.sleep(0)

            room.players[user_id] = {
                "nickname": user_id
            }
            return True

    async def record_series_win(
        self,
        room,
        winner
    ):
        async with room.operation_lock:
            if max(room.series_score.values()) >= 2:
                return False

            await asyncio.sleep(0)

            room.series_score[winner] += 1
            room.series_game += 1

            if room.series_score[winner] >= 2:
                room.match_in_progress = False

            return True

    async def test_three_rooms_accept_only_ten_unique_players(
        self
    ):
        tasks = []

        for room in self.rooms:
            # 방마다 15명이 두 번씩 동시에 참가를 시도합니다.
            for attempt in range(2):
                for player_number in range(15):
                    tasks.append(
                        self.join_room(
                            room,
                            f"{room.room_id}-{player_number}"
                        )
                    )

        results = await asyncio.gather(*tasks)

        self.assertEqual(
            results.count(True),
            MAX_PLAYERS * len(self.rooms)
        )

        for room in self.rooms:
            self.assertEqual(
                len(room.players),
                MAX_PLAYERS
            )
            self.assertEqual(
                len(set(room.players)),
                MAX_PLAYERS
            )

    async def test_same_player_can_join_only_one_room(
        self
    ):
        manager = RoomManager(
            max_rooms=3
        )
        rooms = [
            manager.create_room(
                room_id=str(room_number),
                room_name=f"내전 {room_number}"
            )
            for room_number in range(1, 4)
        ]

        async def join_managed_room(room):
            async with manager.management_lock:
                if manager.find_player_room("same-player"):
                    return False

                return await self.join_room(
                    room,
                    "same-player"
                )

        results = await asyncio.gather(
            *(
                join_managed_room(room)
                for room in rooms
            )
        )

        self.assertEqual(
            results.count(True),
            1
        )
        self.assertEqual(
            sum(
                "same-player" in room.players
                for room in rooms
            ),
            1
        )

    async def test_three_bo3_series_stop_at_two_wins(
        self
    ):
        for room in self.rooms:
            room.match_in_progress = True

        tasks = []

        for room in self.rooms:
            # 결과 요청을 충분히 겹쳐도 시리즈 종료 뒤에는
            # 추가 결과가 반영되지 않아야 합니다.
            for winner in ("red", "blue") * 20:
                tasks.append(
                    self.record_series_win(
                        room,
                        winner
                    )
                )

        await asyncio.gather(*tasks)

        for room in self.rooms:
            self.assertEqual(
                max(room.series_score.values()),
                2
            )
            self.assertIn(
                room.series_game,
                (2, 3)
            )
            self.assertFalse(
                room.match_in_progress
            )

    async def test_room_locks_do_not_block_other_rooms(
        self
    ):
        first_room_entered = asyncio.Event()
        release_first_room = asyncio.Event()
        second_room_finished = asyncio.Event()

        async def hold_first_room():
            async with self.rooms[0].operation_lock:
                first_room_entered.set()
                await release_first_room.wait()

        async def use_second_room():
            await first_room_entered.wait()

            async with self.rooms[1].operation_lock:
                self.rooms[1].players["independent"] = {}

            second_room_finished.set()

        first_task = asyncio.create_task(
            hold_first_room()
        )
        second_task = asyncio.create_task(
            use_second_room()
        )

        await asyncio.wait_for(
            second_room_finished.wait(),
            timeout=1
        )

        self.assertIn(
            "independent",
            self.rooms[1].players
        )

        release_first_room.set()

        await asyncio.gather(
            first_task,
            second_task
        )


if __name__ == "__main__":
    unittest.main()
