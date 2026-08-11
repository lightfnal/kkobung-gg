import asyncio
import unittest
from unittest.mock import patch

from cogs.room import Room
from services.room_manager import RoomManager


class DummyResponse:

    def __init__(self):
        self.messages = []

    async def send_message(
        self,
        message,
        **kwargs
    ):
        self.messages.append(
            {
                "message": message,
                **kwargs
            }
        )


class DummyPermissions:

    def __init__(
        self,
        view_channel=True,
        send_messages=True,
        embed_links=True,
        connect=True
    ):
        self.view_channel = view_channel
        self.send_messages = send_messages
        self.embed_links = embed_links
        self.connect = connect


class DummyTextChannel:

    def __init__(
        self,
        channel_id,
        permissions=None
    ):
        self.id = channel_id

        self.permissions = (
            permissions
            or DummyPermissions()
        )

    def permissions_for(
        self,
        member
    ):
        return self.permissions


class DummyVoiceChannel:

    def __init__(
        self,
        channel_id,
        guild
    ):
        self.id = channel_id
        self.guild = guild
        self.mention = f"<#{channel_id}>"

    def permissions_for(
        self,
        member
    ):
        return DummyPermissions()


class DummyGuildPermissions:

    move_members = True


class DummyMember:

    guild_permissions = (
        DummyGuildPermissions()
    )


class DummyGuild:

    def __init__(
        self,
        guild_id
    ):
        self.id = guild_id
        self.me = DummyMember()


class DummyInteraction:

    def __init__(
        self,
        guild,
        channel
    ):
        self.guild = guild
        self.channel = channel
        self.channel_id = channel.id
        self.response = DummyResponse()


class DummyRoom:

    def __init__(
        self,
        room_id,
        guild_id,
        channel_id
    ):
        self.room_id = str(room_id)
        self.room_name = f"내전 {room_id}"

        self.guild_id = guild_id
        self.channel_id = channel_id

        self.output_channel_id = None
        self.waiting_voice_channel_id = None
        self.red_voice_channel_id = None
        self.blue_voice_channel_id = None

        self.players = {}
        self.current_teams = None
        self.current_recruit_view = None

        self.match_in_progress = False
        self.mvp_vote_in_progress = False
        self.match_transaction_active = False
        self.operation_lock = asyncio.Lock()

        self.series_game = 0
        self.series_score = {
            "red": 0,
            "blue": 0
        }


class DummyRoomManager:

    def __init__(
        self,
        rooms=None
    ):
        self.rooms = list(
            rooms or []
        )

        self.max_rooms = 3
        self.remove_count = 0
        self.management_lock = asyncio.Lock()

    def get_rooms(self):
        return list(
            self.rooms
        )

    def get_room_by_channel(
        self,
        guild_id,
        channel_id
    ):
        for room in self.rooms:
            if (
                room.guild_id == guild_id
                and room.channel_id == channel_id
            ):
                return room

        return None

    def remove_room(
        self,
        room_id
    ):
        for room in self.rooms:
            if room.room_id == str(room_id):
                self.rooms.remove(
                    room
                )

                self.remove_count += 1
                return room

        return None


class DummyJoinCog:

    def __init__(
        self,
        room_manager
    ):
        self.room_manager = room_manager
        self.save_count = 0

    def save_rooms_state(self):
        self.save_count += 1


class DummyBot:
    pass


class TestRoomCog(
    unittest.IsolatedAsyncioTestCase
):

    async def test_room_list_only_shows_current_guild(
        self
    ):
        first_room = DummyRoom(
            room_id="1",
            guild_id=100,
            channel_id=1001
        )

        second_room = DummyRoom(
            room_id="2",
            guild_id=200,
            channel_id=2001
        )

        manager = DummyRoomManager(
            [
                first_room,
                second_room
            ]
        )

        join_cog = DummyJoinCog(
            manager
        )

        interaction = DummyInteraction(
            guild=DummyGuild(100),
            channel=DummyTextChannel(500)
        )

        cog = Room(
            DummyBot()
        )

        with patch(
            "cogs.room.get_join_cog",
            return_value=join_cog
        ):
            await Room.show_rooms.callback(
                cog,
                interaction
            )

        message = (
            interaction
            .response
            .messages[0]["message"]
        )

        self.assertIn(
            first_room.room_name,
            message
        )

        self.assertNotIn(
            second_room.room_name,
            message
        )

    async def test_output_channel_locks_all_guild_rooms_in_order(
        self
    ):
        guild = DummyGuild(100)
        first_room = DummyRoom(
            room_id="1",
            guild_id=100,
            channel_id=501
        )
        second_room = DummyRoom(
            room_id="2",
            guild_id=100,
            channel_id=502
        )
        manager = DummyRoomManager([
            second_room,
            first_room
        ])
        join_cog = DummyJoinCog(manager)
        interaction = DummyInteraction(
            guild=guild,
            channel=DummyTextChannel(900)
        )
        cog = Room(DummyBot())

        await second_room.operation_lock.acquire()

        with (
            patch(
                "cogs.room.is_admin",
                return_value=True
            ),
            patch(
                "cogs.room.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.room.discord.TextChannel",
                DummyTextChannel
            )
        ):
            setting_task = asyncio.create_task(
                Room.set_output_channel.callback(
                    cog,
                    interaction
                )
            )

            await asyncio.sleep(0)

            self.assertFalse(setting_task.done())
            self.assertTrue(
                first_room.operation_lock.locked()
            )
            self.assertIsNone(first_room.output_channel_id)

            second_room.operation_lock.release()

            await setting_task

        self.assertEqual(first_room.output_channel_id, 900)
        self.assertEqual(second_room.output_channel_id, 900)
        self.assertEqual(join_cog.save_count, 1)
        self.assertFalse(first_room.operation_lock.locked())
        self.assertFalse(second_room.operation_lock.locked())

    async def test_delete_room_with_players_is_blocked(
        self
    ):
        room = DummyRoom(
            room_id="1",
            guild_id=100,
            channel_id=500
        )

        room.players["1001"] = {
            "nickname": "참가자"
        }

        manager = DummyRoomManager(
            [room]
        )

        join_cog = DummyJoinCog(
            manager
        )

        interaction = DummyInteraction(
            guild=DummyGuild(100),
            channel=DummyTextChannel(500)
        )

        cog = Room(
            DummyBot()
        )

        with (
            patch(
                "cogs.room.is_admin",
                return_value=True
            ),
            patch(
                "cogs.room.get_join_cog",
                return_value=join_cog
            )
        ):
            await Room.delete_room.callback(
                cog,
                interaction
            )

        self.assertEqual(
            manager.remove_count,
            0
        )

        self.assertIn(
            room,
            manager.rooms
        )

        self.assertIn(
            "참가자가 남아 있어",
            interaction
            .response
            .messages[0]["message"]
        )

    async def test_delete_room_rechecks_players_after_lock(
        self
    ):
        room = DummyRoom(
            room_id="1",
            guild_id=100,
            channel_id=500
        )
        manager = DummyRoomManager([room])
        join_cog = DummyJoinCog(manager)
        interaction = DummyInteraction(
            guild=DummyGuild(100),
            channel=DummyTextChannel(500)
        )
        cog = Room(DummyBot())

        await room.operation_lock.acquire()

        with (
            patch(
                "cogs.room.is_admin",
                return_value=True
            ),
            patch(
                "cogs.room.get_join_cog",
                return_value=join_cog
            )
        ):
            delete_task = asyncio.create_task(
                Room.delete_room.callback(
                    cog,
                    interaction
                )
            )

            await asyncio.sleep(0)

            self.assertFalse(delete_task.done())

            room.players["1001"] = {
                "nickname": "참가자"
            }
            room.operation_lock.release()

            await delete_task

        self.assertEqual(manager.remove_count, 0)
        self.assertIn(room, manager.rooms)
        self.assertIn(
            "참가자가 남아 있어",
            interaction.response.messages[0]["message"]
        )

    async def test_voice_change_is_blocked_during_game(
        self
    ):
        guild = DummyGuild(100)

        room = DummyRoom(
            room_id="1",
            guild_id=100,
            channel_id=500
        )

        room.current_teams = {
            "red": {},
            "blue": {}
        }

        manager = DummyRoomManager(
            [room]
        )

        join_cog = DummyJoinCog(
            manager
        )

        interaction = DummyInteraction(
            guild=guild,
            channel=DummyTextChannel(500)
        )

        cog = Room(
            DummyBot()
        )

        with (
            patch(
                "cogs.room.is_admin",
                return_value=True
            ),
            patch(
                "cogs.room.get_join_cog",
                return_value=join_cog
            )
        ):
            await Room.set_voice_channels.callback(
                cog,
                interaction,
                대기채널=DummyVoiceChannel(
                    600,
                    guild
                ),
                레드팀채널=DummyVoiceChannel(
                    601,
                    guild
                ),
                블루팀채널=DummyVoiceChannel(
                    602,
                    guild
                )
            )

        self.assertIsNone(
            room.waiting_voice_channel_id
        )

        self.assertEqual(
            join_cog.save_count,
            0
        )

        self.assertIn(
            "음성채널 설정을 변경할 수 없습니다",
            interaction
            .response
            .messages[0]["message"]
        )

    async def test_voice_change_rechecks_state_after_lock(
        self
    ):
        guild = DummyGuild(100)
        room = DummyRoom(
            room_id="1",
            guild_id=100,
            channel_id=500
        )
        manager = DummyRoomManager([room])
        join_cog = DummyJoinCog(manager)
        interaction = DummyInteraction(
            guild=guild,
            channel=DummyTextChannel(500)
        )
        cog = Room(DummyBot())

        waiting_channel = DummyVoiceChannel(601, guild)
        red_channel = DummyVoiceChannel(602, guild)
        blue_channel = DummyVoiceChannel(603, guild)

        await room.operation_lock.acquire()

        with (
            patch(
                "cogs.room.is_admin",
                return_value=True
            ),
            patch(
                "cogs.room.get_join_cog",
                return_value=join_cog
            )
        ):
            change_task = asyncio.create_task(
                Room.set_voice_channels.callback(
                    cog,
                    interaction,
                    대기채널=waiting_channel,
                    레드팀채널=red_channel,
                    블루팀채널=blue_channel
                )
            )

            await asyncio.sleep(0)

            self.assertFalse(change_task.done())

            room.current_teams = {
                "red": {},
                "blue": {}
            }
            room.operation_lock.release()

            await change_task

        self.assertIsNone(room.waiting_voice_channel_id)
        self.assertIsNone(room.red_voice_channel_id)
        self.assertIsNone(room.blue_voice_channel_id)
        self.assertIn(
            "음성채널 설정을 변경할 수 없습니다",
            interaction.response.messages[0]["message"]
        )

    async def test_create_rejects_missing_permissions(
        self
    ):
        guild = DummyGuild(100)

        channel = DummyTextChannel(
            channel_id=500,
            permissions=DummyPermissions(
                view_channel=True,
                send_messages=False,
                embed_links=True
            )
        )

        manager = DummyRoomManager()

        join_cog = DummyJoinCog(
            manager
        )

        interaction = DummyInteraction(
            guild=guild,
            channel=channel
        )

        cog = Room(
            DummyBot()
        )

        with (
            patch(
                "cogs.room.is_admin",
                return_value=True
            ),
            patch(
                "cogs.room.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.room.discord.TextChannel",
                DummyTextChannel
            )
        ):
            await Room.create_room.callback(
                cog,
                interaction,
                방이름="테스트 내전"
            )

        self.assertEqual(
            manager.rooms,
            []
        )

        self.assertIn(
            "메시지 보내기",
            interaction
            .response
            .messages[0]["message"]
        )

    async def test_simultaneous_room_creation_uses_unique_ids(
        self
    ):
        guild = DummyGuild(100)
        manager = RoomManager(
            max_rooms=3
        )
        join_cog = DummyJoinCog(manager)
        first_interaction = DummyInteraction(
            guild=guild,
            channel=DummyTextChannel(501)
        )
        second_interaction = DummyInteraction(
            guild=guild,
            channel=DummyTextChannel(502)
        )
        cog = Room(DummyBot())

        with (
            patch(
                "cogs.room.is_admin",
                return_value=True
            ),
            patch(
                "cogs.room.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.room.discord.TextChannel",
                DummyTextChannel
            )
        ):
            await asyncio.gather(
                Room.create_room.callback(
                    cog,
                    first_interaction,
                    방이름="내전 A"
                ),
                Room.create_room.callback(
                    cog,
                    second_interaction,
                    방이름="내전 B"
                )
            )

        rooms = manager.get_rooms()

        self.assertEqual(len(rooms), 2)
        self.assertEqual(
            {room.room_id for room in rooms},
            {"1", "2"}
        )
        self.assertEqual(
            {room.channel_id for room in rooms},
            {501, 502}
        )
        self.assertEqual(join_cog.save_count, 2)

    async def test_delete_then_create_reuses_id_without_race(
        self
    ):
        guild = DummyGuild(100)
        manager = RoomManager(
            max_rooms=3
        )
        old_room = manager.create_room(
            room_id="1",
            room_name="기존 내전",
            guild_id=100,
            channel_id=500
        )
        join_cog = DummyJoinCog(manager)
        delete_interaction = DummyInteraction(
            guild=guild,
            channel=DummyTextChannel(500)
        )
        create_interaction = DummyInteraction(
            guild=guild,
            channel=DummyTextChannel(501)
        )
        cog = Room(DummyBot())

        await old_room.operation_lock.acquire()

        with (
            patch(
                "cogs.room.is_admin",
                return_value=True
            ),
            patch(
                "cogs.room.get_join_cog",
                return_value=join_cog
            ),
            patch(
                "cogs.room.discord.TextChannel",
                DummyTextChannel
            )
        ):
            delete_task = asyncio.create_task(
                Room.delete_room.callback(
                    cog,
                    delete_interaction
                )
            )

            await asyncio.sleep(0)

            self.assertTrue(
                manager.management_lock.locked()
            )

            create_task = asyncio.create_task(
                Room.create_room.callback(
                    cog,
                    create_interaction,
                    방이름="새 내전"
                )
            )

            await asyncio.sleep(0)

            self.assertFalse(create_task.done())

            old_room.operation_lock.release()

            await asyncio.gather(
                delete_task,
                create_task
            )

        rooms = manager.get_rooms()

        self.assertEqual(len(rooms), 1)
        self.assertEqual(rooms[0].room_id, "1")
        self.assertEqual(rooms[0].channel_id, 501)
        self.assertEqual(rooms[0].room_name, "새 내전")
        self.assertFalse(manager.management_lock.locked())


if __name__ == "__main__":
    unittest.main()
