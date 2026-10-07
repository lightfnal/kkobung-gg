import asyncio
import unittest

from services.room_manager import RoomManager


MAX_PLAYERS = 10


class TestBO5IntegrationFlow(unittest.IsolatedAsyncioTestCase):
    async def create_teams(self, room):
        async with room.operation_lock:
            room.players = {
                f"{room.room_id}-{n}": {"nickname": str(n)}
                for n in range(MAX_PLAYERS)
            }
            players = list(room.players)
            positions = ("TOP", "JUNGLE", "MID", "ADC", "SUPPORT")
            room.current_teams = {
                "red": dict(zip(positions, players[:5])),
                "blue": dict(zip(positions, players[5:])),
            }

    async def record_set(self, room, winner):
        async with room.operation_lock:
            if room.current_teams is None or room.match_in_progress:
                return False
            room.match_in_progress = True
            room.series_score[winner] += 1
            room.series_game += 1
            room.match_in_progress = False
            if room.series_score[winner] >= 3 or room.series_game >= 5:
                room.reset_game()
            return True

    async def test_series_can_reach_five_sets_and_ends_at_three_wins(self):
        manager = RoomManager(max_rooms=3)
        rooms = [
            manager.create_room(
                room_id=str(n), room_name=f"내전 {n}",
                guild_id=1, channel_id=100 + n
            )
            for n in range(1, 4)
        ]
        await asyncio.gather(*(self.create_teams(room) for room in rooms))

        # Room 1 finishes 3:0; room 2 plays the full five sets and finishes 3:2.
        five_set_results = ("red", "blue", "red", "blue", "red")
        for winner in five_set_results:
            self.assertTrue(await self.record_set(rooms[1], winner))
        self.assertEqual(len(five_set_results), 5)
        self.assertEqual(rooms[1].series_game, 0)
        self.assertIsNone(rooms[1].current_teams)
        self.assertEqual(rooms[1].players, {})

        for _ in range(3):
            self.assertTrue(await self.record_set(rooms[0], "red"))
        self.assertEqual(rooms[0].series_game, 0)
        self.assertIsNone(rooms[0].current_teams)

        # The third room remains independent and can be restored mid-series.
        await self.record_set(rooms[2], "blue")
        await self.record_set(rooms[2], "red")
        restored = RoomManager.from_dict(manager.to_dict(), max_rooms=3)
        room = restored.get_room("3")
        self.assertEqual(room.series_game, 2)
        self.assertEqual(room.series_score, {"red": 1, "blue": 1})
        self.assertEqual(len(room.players), MAX_PLAYERS)
