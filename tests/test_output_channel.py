import unittest

import discord

from cogs.join import Join


class DummyHTTPResponse:
    status = 403
    reason = "Forbidden"
    headers = {}


class DummyMessage:

    def __init__(
        self,
        channel,
        send_kwargs
    ):
        self.channel = channel
        self.send_kwargs = send_kwargs


class DummyChannel:

    def __init__(
        self,
        channel_id,
        fail=False
    ):
        self.id = channel_id
        self.fail = fail
        self.sent_messages = []

    async def send(
        self,
        **send_kwargs
    ):
        if self.fail:
            raise discord.Forbidden(
                DummyHTTPResponse(),
                {
                    "message": "Missing Access",
                    "code": 50001
                }
            )

        message = DummyMessage(
            channel=self,
            send_kwargs=send_kwargs
        )

        self.sent_messages.append(
            message
        )

        return message


class DummyRoom:

    def __init__(
        self,
        output_channel_id
    ):
        self.output_channel_id = (
            output_channel_id
        )


class DummyJoinCog:

    def __init__(
        self,
        output_channel
    ):
        self.output_channel = (
            output_channel
        )
        self.active_room = None

    async def get_output_channel(
        self,
        room=None,
        fallback_channel=None
    ):
        return self.output_channel


class TestOutputChannel(
    unittest.IsolatedAsyncioTestCase
):

    async def test_output_channel_success(
        self
    ):
        output_channel = DummyChannel(
            channel_id=100
        )

        fallback_channel = DummyChannel(
            channel_id=200
        )

        join_cog = DummyJoinCog(
            output_channel=output_channel
        )

        room = DummyRoom(
            output_channel_id=100
        )

        message, used_fallback = (
            await Join.send_output_message(
                join_cog,
                room=room,
                fallback_channel=fallback_channel,
                content="테스트 메시지"
            )
        )

        self.assertIsNotNone(
            message
        )

        self.assertIs(
            message.channel,
            output_channel
        )

        self.assertFalse(
            used_fallback
        )

        self.assertEqual(
            len(fallback_channel.sent_messages),
            0
        )

    async def test_missing_access_uses_fallback(
        self
    ):
        output_channel = DummyChannel(
            channel_id=100,
            fail=True
        )

        fallback_channel = DummyChannel(
            channel_id=200
        )

        join_cog = DummyJoinCog(
            output_channel=output_channel
        )

        room = DummyRoom(
            output_channel_id=100
        )

        message, used_fallback = (
            await Join.send_output_message(
                join_cog,
                room=room,
                fallback_channel=fallback_channel,
                content="대체 전송 테스트"
            )
        )

        self.assertIsNotNone(
            message
        )

        self.assertIs(
            message.channel,
            fallback_channel
        )

        self.assertTrue(
            used_fallback
        )

        self.assertEqual(
            len(fallback_channel.sent_messages),
            1
        )

        fallback_content = (
            fallback_channel
            .sent_messages[0]
            .send_kwargs["content"]
        )

        self.assertIn(
            "권한",
            fallback_content
        )
        self.assertIn(
            "대체 전송 테스트",
            fallback_content
        )

    async def test_missing_configured_channel_explains_fallback(
        self
    ):
        fallback_channel = DummyChannel(
            channel_id=200
        )
        join_cog = DummyJoinCog(
            output_channel=fallback_channel
        )
        room = DummyRoom(
            output_channel_id=100
        )

        message, used_fallback = (
            await Join.send_output_message(
                join_cog,
                room=room,
                fallback_channel=fallback_channel,
                embed=discord.Embed(title="테스트")
            )
        )

        self.assertIsNotNone(message)
        self.assertTrue(used_fallback)
        self.assertIn(
            "삭제되었거나",
            message.send_kwargs["content"]
        )
        self.assertIn(
            "채널 보기",
            message.send_kwargs["content"]
        )

    async def test_all_channels_fail(
        self
    ):
        output_channel = DummyChannel(
            channel_id=100,
            fail=True
        )

        fallback_channel = DummyChannel(
            channel_id=200,
            fail=True
        )

        join_cog = DummyJoinCog(
            output_channel=output_channel
        )

        room = DummyRoom(
            output_channel_id=100
        )

        message, used_fallback = (
            await Join.send_output_message(
                join_cog,
                room=room,
                fallback_channel=fallback_channel,
                content="전송 실패 테스트"
            )
        )

        self.assertIsNone(
            message
        )

        self.assertTrue(
            used_fallback
        )


if __name__ == "__main__":
    unittest.main()
