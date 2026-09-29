import unittest

import discord

from cogs.join import Join


class DummyHTTPResponse:
    status = 403
    reason = "Forbidden"
    headers = {}


class DummyMessage:
    def __init__(self, channel, send_kwargs):
        self.channel = channel
        self.send_kwargs = send_kwargs


class DummyChannel:
    def __init__(self, channel_id, fail=False):
        self.id = channel_id
        self.fail = fail
        self.sent_messages = []

    async def send(self, **send_kwargs):
        if self.fail:
            raise discord.Forbidden(
                DummyHTTPResponse(),
                {"message": "Missing Access", "code": 50001}
            )

        message = DummyMessage(self, send_kwargs)
        self.sent_messages.append(message)
        return message


class DummyRoom:
    def __init__(self, channel_id):
        self.room_id = "1"
        self.channel_id = channel_id


class DummyBot:
    def __init__(self, channels):
        self.channels = channels

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)

    async def fetch_channel(self, channel_id):
        return self.channels.get(channel_id)


class DummyJoinCog:
    def __init__(self, bot):
        self.bot = bot
        self.active_room = None

    get_room_recruit_channel = Join.get_room_recruit_channel
    get_output_channel = Join.get_output_channel


class TestOutputChannel(unittest.IsolatedAsyncioTestCase):
    async def test_uses_room_recruit_channel(self):
        room_channel = DummyChannel(100)
        command_channel = DummyChannel(200)
        join_cog = DummyJoinCog(DummyBot({100: room_channel}))

        message, used_fallback = await Join.send_output_message(
            join_cog,
            room=DummyRoom(100),
            fallback_channel=command_channel,
            content="테스트 메시지"
        )

        self.assertIs(message.channel, room_channel)
        self.assertFalse(used_fallback)
        self.assertEqual(len(command_channel.sent_messages), 0)

    async def test_each_room_uses_its_own_channel(self):
        first_channel = DummyChannel(101)
        second_channel = DummyChannel(102)
        join_cog = DummyJoinCog(
            DummyBot({101: first_channel, 102: second_channel})
        )

        first_message, _ = await Join.send_output_message(
            join_cog,
            room=DummyRoom(101),
            content="1번 방"
        )
        second_message, _ = await Join.send_output_message(
            join_cog,
            room=DummyRoom(102),
            content="2번 방"
        )

        self.assertIs(first_message.channel, first_channel)
        self.assertIs(second_message.channel, second_channel)

    async def test_missing_room_channel_uses_command_channel(self):
        command_channel = DummyChannel(200)
        join_cog = DummyJoinCog(DummyBot({}))

        message, used_fallback = await Join.send_output_message(
            join_cog,
            room=DummyRoom(100),
            fallback_channel=command_channel,
            content="대체 전송"
        )

        self.assertIs(message.channel, command_channel)
        self.assertTrue(used_fallback)

    async def test_all_channels_fail(self):
        room_channel = DummyChannel(100, fail=True)
        command_channel = DummyChannel(200, fail=True)
        join_cog = DummyJoinCog(DummyBot({100: room_channel}))

        message, used_fallback = await Join.send_output_message(
            join_cog,
            room=DummyRoom(100),
            fallback_channel=command_channel,
            content="전송 실패"
        )

        self.assertIsNone(message)
        self.assertFalse(used_fallback)


if __name__ == "__main__":
    unittest.main()
