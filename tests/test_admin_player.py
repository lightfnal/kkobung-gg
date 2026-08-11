import asyncio
import unittest
from unittest.mock import patch

from cogs.admin_player import AdminPlayer


class DummyResponse:

    def __init__(self):
        self.deferred = False
        self.messages = []

    async def defer(
        self,
        ephemeral=False
    ):
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


class DummyFollowup:

    def __init__(self):
        self.messages = []

    async def send(
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


class DummyInteraction:

    def __init__(self):
        self.response = DummyResponse()
        self.followup = DummyFollowup()


class DummyRoom:

    def __init__(
        self,
        room_id,
        room_name=None
    ):
        self.room_id = str(room_id)

        self.room_name = (
            room_name
            or f"내전 {room_id}"
        )

        self.players = {}
        self.current_teams = None

        self.match_in_progress = False
        self.mvp_vote_in_progress = False
        self.match_transaction_active = False
        self.operation_lock = asyncio.Lock()


class DummyRoomManager:

    def __init__(
        self,
        rooms
    ):
        self.rooms = rooms

    def get_rooms(self):
        return list(
            self.rooms
        )

    def find_player_room(
        self,
        user_id
    ):
        user_id = str(user_id)

        for room in self.rooms:
            if user_id in room.players:
                return room

        return None


class DummyJoinCog:

    def __init__(
        self,
        active_room,
        rooms
    ):
        self.active_room = active_room

        self.room_manager = (
            DummyRoomManager(
                rooms
            )
        )

        self.save_count = 0
        self.reload_count = 0

    @property
    def players(self):
        return self.active_room.players

    async def require_room(
        self,
        interaction
    ):
        return True

    def save_rooms_state(self):
        self.save_count += 1

    def reload_profiles(self):
        self.reload_count += 1


class DummyBot:
    pass


class DummyMember:

    def __init__(
        self,
        user_id,
        display_name="테스트선수"
    ):
        self.id = int(user_id)
        self.display_name = display_name
        self.mention = f"<@{self.id}>"


class TestAdminPlayer(
    unittest.IsolatedAsyncioTestCase
):

    async def test_test_players_fill_only_empty_slots(
        self
    ):
        active_room = DummyRoom(
            room_id="1"
        )

        other_room = DummyRoom(
            room_id="2"
        )

        active_room.players["real-player"] = {
            "nickname": "실제 참가자"
        }

        join_cog = DummyJoinCog(
            active_room=active_room,
            rooms=[
                active_room,
                other_room
            ]
        )

        interaction = DummyInteraction()

        cog = AdminPlayer(
            DummyBot()
        )

        with (
            patch(
                "cogs.admin_player.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_player.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.admin_player.PlayerService.get",
                return_value=None
            ),
            patch(
                "cogs.admin_player.PlayerService.create"
            ) as create_mock,
            patch(
                "cogs.admin_player.PlayerService.update"
            ) as update_mock
        ):
            await (
                AdminPlayer
                .create_test_players
                .callback(
                    cog,
                    interaction
                )
            )

        self.assertEqual(
            len(active_room.players),
            10
        )

        self.assertEqual(
            len(other_room.players),
            0
        )

        self.assertEqual(
            create_mock.call_count,
            9
        )

        update_mock.assert_not_called()

    async def test_remove_is_blocked_after_team_creation(
        self
    ):
        active_room = DummyRoom(
            room_id="1"
        )

        active_room.players["1001"] = {
            "nickname": "참가자"
        }

        active_room.current_teams = {
            "red": {
                "TOP": "1001"
            },
            "blue": {}
        }

        join_cog = DummyJoinCog(
            active_room=active_room,
            rooms=[
                active_room
            ]
        )

        interaction = DummyInteraction()

        cog = AdminPlayer(
            DummyBot()
        )

        with (
            patch(
                "cogs.admin_player.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_player.get_join_cog",
                return_value=join_cog
            )
        ):
            await (
                AdminPlayer
                .remove_participant
                .callback(
                    cog,
                    interaction,
                    discord_id="1001"
                )
            )

        self.assertIn(
            "1001",
            active_room.players
        )

        self.assertEqual(
            len(interaction.response.messages),
            1
        )

        self.assertIn(
            "참가자를 삭제할 수 없습니다",
            interaction
            .response
            .messages[0]["message"]
        )

    async def test_remove_rechecks_room_state_after_lock(
        self
    ):
        room = DummyRoom(
            room_id="1"
        )
        room.players["1001"] = {
            "nickname": "참가자"
        }

        join_cog = DummyJoinCog(
            active_room=room,
            rooms=[room]
        )
        interaction = DummyInteraction()
        cog = AdminPlayer(DummyBot())

        await room.operation_lock.acquire()

        with (
            patch(
                "cogs.admin_player.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_player.get_join_cog",
                return_value=join_cog
            )
        ):
            remove_task = asyncio.create_task(
                AdminPlayer.remove_participant.callback(
                    cog,
                    interaction,
                    discord_id="1001"
                )
            )

            await asyncio.sleep(0)

            self.assertFalse(
                remove_task.done()
            )

            room.current_teams = {
                "red": {"TOP": "1001"},
                "blue": {}
            }
            room.operation_lock.release()

            await remove_task

        self.assertIn(
            "1001",
            room.players
        )
        self.assertFalse(
            interaction.response.deferred
        )
        self.assertIn(
            "참가자를 삭제할 수 없습니다",
            interaction.response.messages[0]["message"]
        )

    async def test_record_reset_checks_every_room(
        self
    ):
        first_room = DummyRoom(
            room_id="1"
        )

        second_room = DummyRoom(
            room_id="2"
        )

        second_room.match_in_progress = True

        join_cog = DummyJoinCog(
            active_room=first_room,
            rooms=[
                first_room,
                second_room
            ]
        )

        interaction = DummyInteraction()

        cog = AdminPlayer(
            DummyBot()
        )

        with (
            patch(
                "cogs.admin_player.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_player.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.admin_player.PlayerService.get_all"
            ) as get_all_mock
        ):
            await AdminPlayer.reset_records.callback(
                cog,
                interaction,
                확인문구="전체초기화"
            )

        get_all_mock.assert_not_called()

        self.assertTrue(
            interaction.response.deferred
        )

        self.assertEqual(
            len(interaction.followup.messages),
            1
        )

        self.assertIn(
            "진행 중인 방",
            interaction
            .followup
            .messages[0]["message"]
        )

        self.assertIn(
            second_room.room_name,
            interaction
            .followup
            .messages[0]["message"]
        )

    async def test_record_reset_rechecks_all_rooms_after_locks(
        self
    ):
        first_room = DummyRoom(
            room_id="1"
        )
        second_room = DummyRoom(
            room_id="2"
        )
        join_cog = DummyJoinCog(
            active_room=first_room,
            rooms=[
                second_room,
                first_room
            ]
        )
        interaction = DummyInteraction()
        cog = AdminPlayer(DummyBot())

        await second_room.operation_lock.acquire()

        with (
            patch(
                "cogs.admin_player.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_player.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.admin_player.PlayerService.get_all"
            ) as get_all_mock
        ):
            reset_task = asyncio.create_task(
                AdminPlayer.reset_records.callback(
                    cog,
                    interaction,
                    확인문구="전체초기화"
                )
            )

            await asyncio.sleep(0)

            self.assertFalse(
                reset_task.done()
            )
            self.assertTrue(
                first_room.operation_lock.locked()
            )

            second_room.match_transaction_active = True
            second_room.operation_lock.release()

            await reset_task

        get_all_mock.assert_not_called()
        self.assertFalse(
            first_room.operation_lock.locked()
        )
        self.assertFalse(
            second_room.operation_lock.locked()
        )
        self.assertIn(
            second_room.room_name,
            interaction.followup.messages[0]["message"]
        )

    async def test_delete_profile_rechecks_players_room_after_locks(
        self
    ):
        first_room = DummyRoom(
            room_id="1"
        )
        player_room = DummyRoom(
            room_id="2"
        )
        player_room.players["1001"] = {
            "nickname": "테스트선수"
        }

        join_cog = DummyJoinCog(
            active_room=first_room,
            rooms=[
                player_room,
                first_room
            ]
        )
        interaction = DummyInteraction()
        player = DummyMember("1001")
        cog = AdminPlayer(DummyBot())

        await player_room.operation_lock.acquire()

        with (
            patch(
                "cogs.admin_player.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_player.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.admin_player.PlayerService.get",
                return_value={
                    "discord_id": "1001"
                }
            ),
            patch(
                "cogs.admin_player.PlayerService.delete"
            ) as delete_mock
        ):
            delete_task = asyncio.create_task(
                AdminPlayer.delete_profile.callback(
                    cog,
                    interaction,
                    player=player
                )
            )

            await asyncio.sleep(0)

            self.assertFalse(
                delete_task.done()
            )
            self.assertTrue(
                first_room.operation_lock.locked()
            )

            player_room.current_teams = {
                "red": {"TOP": "1001"},
                "blue": {}
            }
            player_room.operation_lock.release()

            await delete_task

        delete_mock.assert_not_called()
        self.assertIn(
            "1001",
            player_room.players
        )
        self.assertIn(
            player_room.room_name,
            interaction.response.messages[0]["message"]
        )
        self.assertFalse(
            first_room.operation_lock.locked()
        )
        self.assertFalse(
            player_room.operation_lock.locked()
        )

    async def test_edit_mmr_preserves_rating_and_placement(
        self
    ):
        room = DummyRoom(
            room_id="1"
        )
        room.players["1001"] = {
            "nickname": "테스트선수"
        }

        join_cog = DummyJoinCog(
            active_room=room,
            rooms=[room]
        )
        interaction = DummyInteraction()
        player = DummyMember("1001")
        cog = AdminPlayer(DummyBot())

        profile = {
            "discord_id": "1001",
            "rating": 1234,
            "hidden_mmr": 1400,
            "placement_games": 7
        }

        with (
            patch(
                "cogs.admin_player.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_player.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.admin_player.PlayerService.get",
                return_value=profile
            ),
            patch(
                "cogs.admin_player.PlayerService.update_stats"
            ) as update_mock
        ):
            await AdminPlayer.edit_mmr.callback(
                cog,
                interaction,
                player=player,
                hidden_mmr=1550
            )

        update_mock.assert_called_once()

        saved_profile = update_mock.call_args.args[1]

        self.assertEqual(
            saved_profile["hidden_mmr"],
            1550
        )
        self.assertEqual(
            saved_profile["rating"],
            1234
        )
        self.assertEqual(
            saved_profile["placement_games"],
            7
        )
        self.assertEqual(
            join_cog.reload_count,
            1
        )
        self.assertIn(
            "변경량: **+150점**",
            interaction.response.messages[0]["message"]
        )

    async def test_edit_rating_preserves_hidden_mmr_and_placement(
        self
    ):
        room = DummyRoom(
            room_id="1"
        )
        join_cog = DummyJoinCog(
            active_room=room,
            rooms=[room]
        )
        interaction = DummyInteraction()
        player = DummyMember("1001")
        cog = AdminPlayer(DummyBot())

        with (
            patch(
                "cogs.admin_player.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_player.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.admin_player.PlayerService.get",
                return_value={
                    "discord_id": "1001",
                    "rating": 1000,
                    "hidden_mmr": 1450,
                    "placement_games": 8
                }
            ),
            patch(
                "cogs.admin_player.PlayerService.update_stats"
            ) as update_mock
        ):
            await AdminPlayer.edit_rating.callback(
                cog,
                interaction,
                player=player,
                rating=1250
            )

        saved_profile = update_mock.call_args.args[1]

        self.assertEqual(saved_profile["rating"], 1250)
        self.assertEqual(saved_profile["hidden_mmr"], 1450)
        self.assertEqual(saved_profile["placement_games"], 8)
        self.assertTrue(interaction.response.deferred)
        self.assertEqual(join_cog.reload_count, 1)

    async def test_edit_rating_rechecks_room_state_after_lock(
        self
    ):
        room = DummyRoom(
            room_id="1"
        )
        room.players["1001"] = {
            "nickname": "테스트선수"
        }
        join_cog = DummyJoinCog(
            active_room=room,
            rooms=[room]
        )
        interaction = DummyInteraction()
        player = DummyMember("1001")
        cog = AdminPlayer(DummyBot())

        await room.operation_lock.acquire()

        with (
            patch(
                "cogs.admin_player.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_player.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.admin_player.PlayerService.get",
                return_value={
                    "rating": 1000,
                    "hidden_mmr": 1450,
                    "placement_games": 8
                }
            ),
            patch(
                "cogs.admin_player.PlayerService.update_stats"
            ) as update_mock
        ):
            edit_task = asyncio.create_task(
                AdminPlayer.edit_rating.callback(
                    cog,
                    interaction,
                    player=player,
                    rating=1250
                )
            )

            await asyncio.sleep(0)

            self.assertFalse(edit_task.done())

            room.match_transaction_active = True
            room.operation_lock.release()

            await edit_task

        update_mock.assert_not_called()
        self.assertIn(
            "내전이 완전히 종료된 뒤 수정",
            interaction.followup.messages[0]["message"]
        )

    async def test_edit_mmr_rejects_out_of_range_value(
        self
    ):
        room = DummyRoom(
            room_id="1"
        )
        join_cog = DummyJoinCog(
            active_room=room,
            rooms=[room]
        )
        interaction = DummyInteraction()
        player = DummyMember("1001")
        cog = AdminPlayer(DummyBot())

        with (
            patch(
                "cogs.admin_player.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_player.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.admin_player.PlayerService.get"
            ) as get_mock,
            patch(
                "cogs.admin_player.PlayerService.update_stats"
            ) as update_mock
        ):
            await AdminPlayer.edit_mmr.callback(
                cog,
                interaction,
                player=player,
                hidden_mmr=5001
            )

        get_mock.assert_not_called()
        update_mock.assert_not_called()
        self.assertIn(
            "0~5000",
            interaction.response.messages[0]["message"]
        )

    async def test_test_player_creation_rechecks_state_after_lock(
        self
    ):
        room = DummyRoom(
            room_id="1"
        )
        join_cog = DummyJoinCog(
            active_room=room,
            rooms=[room]
        )
        interaction = DummyInteraction()
        cog = AdminPlayer(DummyBot())

        await room.operation_lock.acquire()

        with (
            patch(
                "cogs.admin_player.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_player.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.admin_player.PlayerService.create"
            ) as create_mock,
            patch(
                "cogs.admin_player.PlayerService.update"
            ) as update_mock
        ):
            creation_task = asyncio.create_task(
                AdminPlayer.create_test_players.callback(
                    cog,
                    interaction
                )
            )

            await asyncio.sleep(0)

            self.assertFalse(
                creation_task.done()
            )

            room.current_teams = {
                "red": {},
                "blue": {}
            }
            room.operation_lock.release()

            await creation_task

        create_mock.assert_not_called()
        update_mock.assert_not_called()
        self.assertEqual(
            room.players,
            {}
        )
        self.assertIn(
            "테스트 참가자를 추가할 수 없습니다",
            interaction.response.messages[0]["message"]
        )

    async def test_test_player_reset_rechecks_state_after_lock(
        self
    ):
        room = DummyRoom(
            room_id="1"
        )
        test_user_id = "900000000000000000"
        room.players[test_user_id] = {
            "nickname": "테스트탑"
        }

        join_cog = DummyJoinCog(
            active_room=room,
            rooms=[room]
        )
        interaction = DummyInteraction()
        cog = AdminPlayer(DummyBot())

        await room.operation_lock.acquire()

        with (
            patch(
                "cogs.admin_player.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_player.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.admin_player.PlayerService.get"
            ) as get_mock,
            patch(
                "cogs.admin_player.PlayerService.delete"
            ) as delete_mock
        ):
            reset_task = asyncio.create_task(
                AdminPlayer.reset_test_players.callback(
                    cog,
                    interaction
                )
            )

            await asyncio.sleep(0)

            self.assertFalse(
                reset_task.done()
            )

            room.current_teams = {
                "red": {"TOP": test_user_id},
                "blue": {}
            }
            room.operation_lock.release()

            await reset_task

        get_mock.assert_not_called()
        delete_mock.assert_not_called()
        self.assertIn(
            test_user_id,
            room.players
        )
        self.assertIsNotNone(
            room.current_teams
        )
        self.assertIn(
            "테스트 참가자를 초기화할 수 없습니다",
            interaction.response.messages[0]["message"]
        )

    async def test_edit_mmr_is_blocked_after_team_creation(
        self
    ):
        room = DummyRoom(
            room_id="1"
        )
        room.players["1001"] = {
            "nickname": "테스트선수"
        }
        room.current_teams = {
            "red": {"TOP": "1001"},
            "blue": {}
        }

        join_cog = DummyJoinCog(
            active_room=room,
            rooms=[room]
        )
        interaction = DummyInteraction()
        player = DummyMember("1001")
        cog = AdminPlayer(DummyBot())

        with (
            patch(
                "cogs.admin_player.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_player.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.admin_player.PlayerService.get",
                return_value={
                    "rating": 1000,
                    "hidden_mmr": 1000,
                    "placement_games": 0
                }
            ),
            patch(
                "cogs.admin_player.PlayerService.update_stats"
            ) as update_mock
        ):
            await AdminPlayer.edit_mmr.callback(
                cog,
                interaction,
                player=player,
                hidden_mmr=1500
            )

        update_mock.assert_not_called()
        self.assertIn(
            "내전이 완전히 종료된 뒤",
            interaction.response.messages[0]["message"]
        )

    async def test_edit_mmr_rechecks_room_state_after_lock(
        self
    ):
        room = DummyRoom(
            room_id="1"
        )
        room.players["1001"] = {
            "nickname": "테스트선수"
        }

        join_cog = DummyJoinCog(
            active_room=room,
            rooms=[room]
        )
        interaction = DummyInteraction()
        player = DummyMember("1001")
        cog = AdminPlayer(DummyBot())

        await room.operation_lock.acquire()

        with (
            patch(
                "cogs.admin_player.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_player.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.admin_player.PlayerService.get",
                return_value={
                    "rating": 1000,
                    "hidden_mmr": 1400,
                    "placement_games": 7
                }
            ),
            patch(
                "cogs.admin_player.PlayerService.update_stats"
            ) as update_mock
        ):
            edit_task = asyncio.create_task(
                AdminPlayer.edit_mmr.callback(
                    cog,
                    interaction,
                    player=player,
                    hidden_mmr=1550
                )
            )

            await asyncio.sleep(0)

            self.assertFalse(
                edit_task.done()
            )

            room.match_in_progress = True
            room.operation_lock.release()

            await edit_task

        update_mock.assert_not_called()
        self.assertIn(
            "내전이 완전히 종료된 뒤 수정",
            interaction.response.messages[0]["message"]
        )

    async def test_reset_mmr_rechecks_players_other_room_after_lock(
        self
    ):
        command_room = DummyRoom(
            room_id="1"
        )
        player_room = DummyRoom(
            room_id="2"
        )
        player_room.players["1001"] = {
            "nickname": "테스트선수"
        }

        join_cog = DummyJoinCog(
            active_room=command_room,
            rooms=[
                command_room,
                player_room
            ]
        )
        interaction = DummyInteraction()
        player = DummyMember("1001")
        cog = AdminPlayer(DummyBot())

        await player_room.operation_lock.acquire()

        with (
            patch(
                "cogs.admin_player.is_admin",
                return_value=True
            ),
            patch(
                "cogs.admin_player.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.admin_player.PlayerService.get",
                return_value={
                    "rating": 1000,
                    "hidden_mmr": 1400,
                    "placement_games": 7,
                    "tier": "플래티넘"
                }
            ),
            patch(
                "cogs.admin_player.PlayerService.update_stats"
            ) as update_mock
        ):
            reset_task = asyncio.create_task(
                AdminPlayer.reset_mmr.callback(
                    cog,
                    interaction,
                    player=player
                )
            )

            await asyncio.sleep(0)

            self.assertFalse(
                reset_task.done()
            )

            player_room.current_teams = {
                "red": {"TOP": "1001"},
                "blue": {}
            }
            player_room.operation_lock.release()

            await reset_task

        update_mock.assert_not_called()
        self.assertIn(
            "내전이 완전히 종료된 뒤 초기화",
            interaction.response.messages[0]["message"]
        )


if __name__ == "__main__":
    unittest.main()
