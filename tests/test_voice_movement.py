import unittest
from unittest.mock import patch

import discord

from cogs.join import Join


class DummyVoiceState:

    def __init__(
        self,
        channel
    ):
        self.channel = channel


class DummyVoiceChannel:

    def __init__(
        self,
        channel_id
    ):
        self.id = channel_id


class DummyMember:

    def __init__(
        self,
        user_id,
        current_channel=None,
        move_fails=False,
        permission_denied=False
    ):
        self.id = user_id
        self.voice = (
            DummyVoiceState(
                current_channel
            )
            if current_channel is not None
            else None
        )

        self.move_fails = move_fails
        self.permission_denied = permission_denied
        self.move_count = 0
        self.moved_channel = None

    async def move_to(
        self,
        channel
    ):
        if self.permission_denied:
            raise discord.Forbidden(
                response=DummyHTTPResponse(),
                message="권한 부족"
            )

        if self.move_fails:
            raise discord.HTTPException(
                response=DummyHTTPResponse(),
                message="이동 실패"
            )

        self.move_count += 1
        self.moved_channel = channel
        self.voice = DummyVoiceState(
            channel
        )


class DummyHTTPResponse:

    status = 403
    reason = "Forbidden"
    headers = {}


class DummyGuild:

    def __init__(
        self,
        channels=None,
        members=None
    ):
        self.channels = channels or {}
        self.members = members or {}

    def get_channel(
        self,
        channel_id
    ):
        return self.channels.get(
            channel_id
        )

    def get_member(
        self,
        user_id
    ):
        return self.members.get(
            user_id
        )


class TestVoiceMovement(
    unittest.IsolatedAsyncioTestCase
):

    async def test_members_are_moved(
        self
    ):
        waiting_channel = (
            DummyVoiceChannel(100)
        )

        current_channel = (
            DummyVoiceChannel(200)
        )

        first_member = DummyMember(
            user_id=1,
            current_channel=current_channel
        )

        second_member = DummyMember(
            user_id=2,
            current_channel=current_channel
        )

        guild = DummyGuild(
            channels={
                100: waiting_channel
            },
            members={
                1: first_member,
                2: second_member
            }
        )

        with patch(
            "cogs.join.discord.VoiceChannel",
            DummyVoiceChannel
        ):
            result = (
                await Join
                .move_members_to_voice_channel(
                    None,
                    guild=guild,
                    user_ids={"1", "2"},
                    channel_id=100
                )
            )

        self.assertEqual(
            result["moved"],
            2
        )

        self.assertEqual(
            result["failed"],
            0
        )

        self.assertIs(
            first_member.moved_channel,
            waiting_channel
        )

        self.assertIs(
            second_member.moved_channel,
            waiting_channel
        )

    async def test_already_connected_member(
        self
    ):
        waiting_channel = (
            DummyVoiceChannel(100)
        )

        member = DummyMember(
            user_id=1,
            current_channel=waiting_channel
        )

        guild = DummyGuild(
            channels={
                100: waiting_channel
            },
            members={
                1: member
            }
        )

        with patch(
            "cogs.join.discord.VoiceChannel",
            DummyVoiceChannel
        ):
            result = (
                await Join
                .move_members_to_voice_channel(
                    None,
                    guild=guild,
                    user_ids={"1"},
                    channel_id=100
                )
            )

        self.assertEqual(
            result["already_connected"],
            1
        )

        self.assertEqual(
            result["moved"],
            0
        )

        self.assertEqual(
            member.move_count,
            0
        )

    async def test_disconnected_member(
        self
    ):
        waiting_channel = (
            DummyVoiceChannel(100)
        )

        member = DummyMember(
            user_id=1
        )

        guild = DummyGuild(
            channels={
                100: waiting_channel
            },
            members={
                1: member
            }
        )

        with patch(
            "cogs.join.discord.VoiceChannel",
            DummyVoiceChannel
        ):
            result = (
                await Join
                .move_members_to_voice_channel(
                    None,
                    guild=guild,
                    user_ids={"1"},
                    channel_id=100
                )
            )

        self.assertEqual(
            result["not_connected"],
            1
        )

        self.assertEqual(
            result["moved"],
            0
        )

    async def test_missing_channel(
        self
    ):
        guild = DummyGuild()

        result = (
            await Join
            .move_members_to_voice_channel(
                None,
                guild=guild,
                user_ids={"1"},
                channel_id=100
            )
        )

        self.assertTrue(
            result["channel_missing"]
        )

        self.assertEqual(
            result["moved"],
            0
        )

    async def test_move_failure_is_counted(
        self
    ):
        waiting_channel = (
            DummyVoiceChannel(100)
        )

        current_channel = (
            DummyVoiceChannel(200)
        )

        member = DummyMember(
            user_id=1,
            current_channel=current_channel,
            move_fails=True
        )

        guild = DummyGuild(
            channels={
                100: waiting_channel
            },
            members={
                1: member
            }
        )

        with patch(
            "cogs.join.discord.VoiceChannel",
            DummyVoiceChannel
        ):
            result = (
                await Join
                .move_members_to_voice_channel(
                    None,
                    guild=guild,
                    user_ids={"1"},
                    channel_id=100
                )
            )

        self.assertEqual(
            result["failed"],
            1
        )

        self.assertEqual(
            result["http_failed"],
            1
        )

        self.assertEqual(
            result["permission_denied"],
            0
        )

        self.assertEqual(
            result["moved"],
            0
        )

    async def test_permission_failure_is_counted_separately(
        self
    ):
        waiting_channel = DummyVoiceChannel(100)
        current_channel = DummyVoiceChannel(200)
        member = DummyMember(
            user_id=1,
            current_channel=current_channel,
            permission_denied=True
        )
        guild = DummyGuild(
            channels={100: waiting_channel},
            members={1: member}
        )

        with patch(
            "cogs.join.discord.VoiceChannel",
            DummyVoiceChannel
        ):
            result = await Join.move_members_to_voice_channel(
                None,
                guild=guild,
                user_ids={"1"},
                channel_id=100
            )

        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["permission_denied"], 1)
        self.assertEqual(result["http_failed"], 0)

    async def test_invalid_member_id_is_counted_separately(
        self
    ):
        waiting_channel = DummyVoiceChannel(100)
        guild = DummyGuild(
            channels={100: waiting_channel}
        )

        with patch(
            "cogs.join.discord.VoiceChannel",
            DummyVoiceChannel
        ):
            result = await Join.move_members_to_voice_channel(
                None,
                guild=guild,
                user_ids={"invalid"},
                channel_id=100
            )

        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["invalid_member_id"], 1)


if __name__ == "__main__":
    unittest.main()
