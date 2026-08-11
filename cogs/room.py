import discord
from contextlib import AsyncExitStack

from discord.ext import commands

from utils.cog_helper import get_join_cog

from utils.permissions import (
    is_admin,
    send_admin_only_message
)


class Room(commands.Cog):
    """
    여러 내전 방과 Discord 채널의 연결을 관리합니다.
    """

    def __init__(
        self,
        bot
    ):
        self.bot = bot

    @discord.app_commands.command(
        name="내전방생성",
        description="현재 채널에 내전 방을 생성하거나 연결합니다."
    )
    @discord.app_commands.describe(
        방이름="표시할 내전 방 이름"
    )
    async def create_room(
        self,
        interaction: discord.Interaction,
        방이름: str
    ):
        if not is_admin(interaction):
            await send_admin_only_message(
                interaction
            )
            return

        if (
            interaction.guild is None
            or interaction.channel_id is None
        ):
            await interaction.response.send_message(
                "❌ 서버 채널에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        async with join_cog.room_manager.management_lock:
            await self._create_room_locked(
                interaction,
                방이름
            )

    async def _create_room_locked(
        self,
        interaction: discord.Interaction,
        방이름: str
    ):
        if not is_admin(interaction):
            await send_admin_only_message(
                interaction
            )
            return

        if (
            interaction.guild is None
            or interaction.channel_id is None
        ):
            await interaction.response.send_message(
                "❌ 서버 채널에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        recruit_channel = interaction.channel

        if not isinstance(
            recruit_channel,
            discord.TextChannel
        ):
            await interaction.response.send_message(
                "❌ 일반 텍스트 채널에만 내전 방을 "
                "생성할 수 있습니다.",
                ephemeral=True
            )
            return

        bot_member = interaction.guild.me

        if bot_member is None:
            await interaction.response.send_message(
                "❌ 서버에서 봇의 권한 정보를 "
                "확인할 수 없습니다.",
                ephemeral=True
            )
            return

        permissions = recruit_channel.permissions_for(
            bot_member
        )

        missing_permissions = []

        if not permissions.view_channel:
            missing_permissions.append(
                "채널 보기"
            )

        if not permissions.send_messages:
            missing_permissions.append(
                "메시지 보내기"
            )

        if not permissions.embed_links:
            missing_permissions.append(
                "링크 첨부"
            )

        if missing_permissions:
            await interaction.response.send_message(
                "❌ 꼬붕봇이 현재 채널을 내전 모집 "
                "채널로 사용할 수 없습니다.\n"
                "필요한 권한: "
                + ", ".join(
                    missing_permissions
                ),
                ephemeral=True
            )
            return

        room_manager = (
            join_cog.room_manager
        )

        existing_room = (
            room_manager.get_room_by_channel(
                guild_id=interaction.guild.id,
                channel_id=interaction.channel_id
            )
        )

        if existing_room is not None:
            await interaction.response.send_message(
                "❌ 현재 채널에는 이미 내전 방이 연결되어 있습니다.\n"
                f"방 번호: `{existing_room.room_id}`\n"
                f"방 이름: **{existing_room.room_name}**",
                ephemeral=True
            )
            return

        room_name = 방이름.strip()

        if not room_name:
            await interaction.response.send_message(
                "❌ 내전 방 이름을 입력해주세요.",
                ephemeral=True
            )
            return

        existing_output_channel_id = next(
            (
                current_room.output_channel_id
                for current_room
                in room_manager.get_rooms()
                if (
                    current_room.guild_id
                    == interaction.guild.id
                    and current_room.output_channel_id
                    is not None
                )
            ),
            None
        )

        # 기존 호환용 1번 방이 아직 채널에 연결되지 않았다면
        # 새 방을 만들지 않고 현재 채널에 연결합니다.
        room = next(
            (
                current_room
                for current_room
                in room_manager.get_rooms()
                if current_room.guild_id is None
                and current_room.channel_id is None
            ),
            None
        )

        if room is None:
            available_room_id = None

            for room_number in range(
                1,
                room_manager.max_rooms + 1
            ):
                candidate_id = str(
                    room_number
                )

                if (
                    room_manager.get_room(
                        candidate_id
                    )
                    is None
                ):
                    available_room_id = (
                        candidate_id
                    )
                    break

            if available_room_id is None:
                await interaction.response.send_message(
                    "❌ 생성할 수 있는 최대 내전 방 수에 도달했습니다.\n"
                    f"최대 방 수: {room_manager.max_rooms}개",
                    ephemeral=True
                )
                return

            room = room_manager.create_room(
                room_id=available_room_id,
                room_name=room_name,
                guild_id=interaction.guild.id,
                channel_id=interaction.channel_id
            )

        else:
            async with room.operation_lock:
                room.room_name = room_name
                room.guild_id = (
                    interaction.guild.id
                )
                room.channel_id = (
                    interaction.channel_id
                )

        async with room.operation_lock:
            if room.output_channel_id is None:
                room.output_channel_id = (
                    existing_output_channel_id
                )

        join_cog.save_rooms_state()

        await interaction.response.send_message(
            "✅ 현재 채널에 내전 방을 연결했습니다.\n\n"
            f"방 번호: `{room.room_id}`\n"
            f"방 이름: **{room.room_name}**\n"
            f"최대 참가자: 10명"
        )

    @discord.app_commands.command(
        name="내전방목록",
        description="현재 생성된 내전 방 목록을 확인합니다."
    )
    async def show_rooms(
        self,
        interaction: discord.Interaction
    ):
        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ 서버에서만 내전 방 목록을 "
                "확인할 수 있습니다.",
                ephemeral=True
            )
            return

        rooms = [
            room
            for room
            in join_cog.room_manager.get_rooms()
            if room.guild_id == interaction.guild.id
        ]

        if not rooms:
            await interaction.response.send_message(
                "📋 현재 서버에 생성된 내전 방이 없습니다."
            )
            return

        room_messages = []

        for room in rooms:
            channel_text = "연결되지 않음"

            if room.channel_id is not None:
                channel_text = (
                    f"<#{room.channel_id}>"
                )

            status_text = (
                "경기 진행 중"
                if room.match_in_progress
                else "대기 중"
            )

            room_messages.append(
                f"**{room.room_id}. {room.room_name}**\n"
                f"채널: {channel_text}\n"
                f"참가자: {len(room.players)}/10명\n"
                f"상태: {status_text}"
            )

        await interaction.response.send_message(
            "📋 **내전 방 목록**\n\n"
            + "\n\n".join(
                room_messages
            )
        )

    @discord.app_commands.command(
        name="내전방정보",
        description="현재 채널에 연결된 내전 방을 확인합니다."
    )
    async def show_current_room(
        self,
        interaction: discord.Interaction
    ):
        if (
            interaction.guild is None
            or interaction.channel_id is None
        ):
            await interaction.response.send_message(
                "❌ 서버 채널에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        room = (
            join_cog.room_manager
            .get_room_by_channel(
                guild_id=interaction.guild.id,
                channel_id=interaction.channel_id
            )
        )

        if room is None:
            await interaction.response.send_message(
                "❌ 현재 채널에는 연결된 내전 방이 없습니다.\n"
                "관리자가 `/내전방생성`을 실행해주세요.",
                ephemeral=True
            )
            return

        status_text = (
            "🎮 경기 진행 중"
            if room.match_in_progress
            else "⏳ 대기 중"
        )

        output_channel_text = (
            f"<#{room.output_channel_id}>"
            if room.output_channel_id is not None
            else "설정되지 않음"
        )

        waiting_channel_text = (
            f"<#{room.waiting_voice_channel_id}>"
            if room.waiting_voice_channel_id is not None
            else "설정되지 않음"
        )

        red_channel_text = (
            f"<#{room.red_voice_channel_id}>"
            if room.red_voice_channel_id is not None
            else "설정되지 않음"
        )

        blue_channel_text = (
            f"<#{room.blue_voice_channel_id}>"
            if room.blue_voice_channel_id is not None
            else "설정되지 않음"
        )

        await interaction.response.send_message(
            "🏠 **현재 내전 방 정보**\n\n"
            f"방 번호: `{room.room_id}`\n"
            f"방 이름: **{room.room_name}**\n"
            f"참가자: {len(room.players)}/10명\n"
            f"현재 세트: {room.series_game}경기 완료\n"
            f"시리즈 점수: "
            f"레드 {room.series_score['red']} : "
            f"{room.series_score['blue']} 블루\n"
            f"상태: {status_text}\n\n"
            "📢 **진행 채널**\n"
            f"{output_channel_text}\n\n"
            "🔊 **음성채널**\n"
            f"대기: {waiting_channel_text}\n"
            f"레드팀: {red_channel_text}\n"
            f"블루팀: {blue_channel_text}"
        )

    @discord.app_commands.command(
        name="내전진행채널설정",
        description="현재 채널을 모든 내전의 공용 진행 채널로 설정합니다."
    )
    async def set_output_channel(
        self,
        interaction: discord.Interaction
    ):
        if not is_admin(interaction):
            await send_admin_only_message(
                interaction
            )
            return

        if (
            interaction.guild is None
            or interaction.channel_id is None
        ):
            await interaction.response.send_message(
                "❌ 서버 채널에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        output_channel = interaction.channel

        if not isinstance(
            output_channel,
            discord.TextChannel
        ):
            await interaction.response.send_message(
                "❌ 일반 텍스트 채널만 공용 진행 "
                "채널로 설정할 수 있습니다.",
                ephemeral=True
            )
            return

        bot_member = interaction.guild.me

        if bot_member is None:
            await interaction.response.send_message(
                "❌ 서버에서 봇의 권한 정보를 "
                "확인할 수 없습니다.",
                ephemeral=True
            )
            return

        permissions = output_channel.permissions_for(
            bot_member
        )

        missing_permissions = []

        if not permissions.view_channel:
            missing_permissions.append(
                "채널 보기"
            )

        if not permissions.send_messages:
            missing_permissions.append(
                "메시지 보내기"
            )

        if not permissions.embed_links:
            missing_permissions.append(
                "링크 첨부"
            )

        if missing_permissions:
            await interaction.response.send_message(
                "❌ 꼬붕봇이 현재 채널을 공용 진행 "
                "채널로 사용할 수 없습니다.\n"
                "필요한 권한: "
                + ", ".join(
                    missing_permissions
                ),
                ephemeral=True
            )
            return

        guild_rooms = [
            room
            for room
            in join_cog.room_manager.get_rooms()
            if room.guild_id == interaction.guild.id
        ]

        if not guild_rooms:
            await interaction.response.send_message(
                "❌ 이 서버에 연결된 내전 방이 없습니다.\n"
                "먼저 모집 채널에서 `/내전방생성`을 실행해주세요.",
                ephemeral=True
            )
            return

        guild_rooms.sort(
            key=lambda room: str(room.room_id)
        )

        async with AsyncExitStack() as lock_stack:
            for room in guild_rooms:
                await lock_stack.enter_async_context(
                    room.operation_lock
                )

            for room in guild_rooms:
                room.output_channel_id = (
                    interaction.channel_id
                )

            join_cog.save_rooms_state()

        room_names = ", ".join(
            room.room_name
            for room in guild_rooms
        )

        await interaction.response.send_message(
            "✅ 현재 채널을 공용 내전 진행 채널로 설정했습니다.\n\n"
            f"진행 채널: <#{interaction.channel_id}>\n"
            f"적용된 내전: **{room_names}**\n\n"
            "앞으로 팀 생성 이후의 진행 정보가 "
            "이 채널에 표시됩니다."
        )

    @discord.app_commands.command(
        name="내전음성채널설정",
        description="현재 내전 방에서 사용할 음성채널을 설정합니다."
    )
    @discord.app_commands.describe(
        대기채널="경기 전 참가자들이 대기하는 음성채널",
        레드팀채널="레드팀 참가자를 이동시킬 음성채널",
        블루팀채널="블루팀 참가자를 이동시킬 음성채널"
    )
    async def set_voice_channels(
        self,
        interaction: discord.Interaction,
        대기채널: discord.VoiceChannel,
        레드팀채널: discord.VoiceChannel,
        블루팀채널: discord.VoiceChannel
    ):
        if not is_admin(interaction):
            await send_admin_only_message(
                interaction
            )
            return

        if (
            interaction.guild is None
            or interaction.channel_id is None
        ):
            await interaction.response.send_message(
                "❌ 서버 채널에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        room = (
            join_cog.room_manager
            .get_room_by_channel(
                guild_id=interaction.guild.id,
                channel_id=interaction.channel_id
            )
        )

        if room is None:
            await interaction.response.send_message(
                "❌ 현재 채널에는 연결된 내전 방이 없습니다.\n"
                "먼저 `/내전방생성`을 실행해주세요.",
                ephemeral=True
            )
            return

        async with room.operation_lock:
            await self._set_voice_channels_locked(
                interaction,
                대기채널,
                레드팀채널,
                블루팀채널
            )

    async def _set_voice_channels_locked(
        self,
        interaction: discord.Interaction,
        대기채널: discord.VoiceChannel,
        레드팀채널: discord.VoiceChannel,
        블루팀채널: discord.VoiceChannel
    ):
        if not is_admin(interaction):
            await send_admin_only_message(
                interaction
            )
            return

        if (
            interaction.guild is None
            or interaction.channel_id is None
        ):
            await interaction.response.send_message(
                "❌ 서버 채널에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        room = (
            join_cog.room_manager
            .get_room_by_channel(
                guild_id=interaction.guild.id,
                channel_id=interaction.channel_id
            )
        )

        if room is None:
            await interaction.response.send_message(
                "❌ 현재 채널에는 연결된 내전 방이 없습니다.\n"
                "먼저 `/내전방생성`을 실행해주세요.",
                ephemeral=True
            )
            return

        if (
            room.current_teams is not None
            or room.match_in_progress
            or room.mvp_vote_in_progress
            or room.match_transaction_active
            or room.match_transaction_committed
            or room.pending_match_token is not None
            or room.pending_series_score is not None
            or room.pending_series_game is not None
        ):
            await interaction.response.send_message(
                "❌ 팀이 생성됐거나 경기를 처리 중일 때는 "
                "음성채널 설정을 변경할 수 없습니다.\n"
                "내전 종료 후 다시 설정해주세요.",
                ephemeral=True
            )
            return

        selected_channel_ids = {
            대기채널.id,
            레드팀채널.id,
            블루팀채널.id
        }

        if len(selected_channel_ids) != 3:
            await interaction.response.send_message(
                "❌ 대기, 레드팀, 블루팀 채널은 "
                "서로 다른 음성채널이어야 합니다.",
                ephemeral=True
            )
            return

        voice_channels = (
            대기채널,
            레드팀채널,
            블루팀채널
        )

        if any(
            channel.guild.id
            != interaction.guild.id
            for channel in voice_channels
        ):
            await interaction.response.send_message(
                "❌ 현재 서버에 속한 음성채널만 "
                "설정할 수 있습니다.",
                ephemeral=True
            )
            return

        bot_member = interaction.guild.me

        if bot_member is None:
            await interaction.response.send_message(
                "❌ 서버에서 봇의 권한 정보를 "
                "확인할 수 없습니다.",
                ephemeral=True
            )
            return

        if not bot_member.guild_permissions.move_members:
            await interaction.response.send_message(
                "❌ 꼬붕봇에 `멤버 이동` 권한이 없습니다.\n"
                "서버 역할 설정에서 권한을 허용해주세요.",
                ephemeral=True
            )
            return

        inaccessible_channels = []

        for channel in voice_channels:
            permissions = channel.permissions_for(
                bot_member
            )

            if not (
                permissions.view_channel
                and permissions.connect
            ):
                inaccessible_channels.append(
                    channel.mention
                )

        if inaccessible_channels:
            await interaction.response.send_message(
                "❌ 꼬붕봇이 접근할 수 없는 음성채널이 "
                "있습니다.\n"
                "필요한 권한: `채널 보기`, `연결`\n"
                "확인할 채널: "
                + ", ".join(
                    inaccessible_channels
                ),
                ephemeral=True
            )
            return

        room.waiting_voice_channel_id = (
            대기채널.id
        )

        room.red_voice_channel_id = (
            레드팀채널.id
        )

        room.blue_voice_channel_id = (
            블루팀채널.id
        )

        join_cog.save_rooms_state()

        await interaction.response.send_message(
            f"✅ **{room.room_name} 음성채널 설정 완료**\n\n"
            f"방 번호: `{room.room_id}`\n"
            f"대기 채널: {대기채널.mention}\n"
            f"레드팀 채널: {레드팀채널.mention}\n"
            f"블루팀 채널: {블루팀채널.mention}"
        )

    @discord.app_commands.command(
        name="내전방삭제",
        description="현재 채널에 연결된 빈 내전 방을 삭제합니다."
    )
    async def delete_room(
        self,
        interaction: discord.Interaction
    ):
        if not is_admin(interaction):
            await send_admin_only_message(
                interaction
            )
            return

        if (
            interaction.guild is None
            or interaction.channel_id is None
        ):
            await interaction.response.send_message(
                "❌ 서버 채널에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        room_manager = join_cog.room_manager

        async with room_manager.management_lock:
            room = (
                room_manager.get_room_by_channel(
                    guild_id=interaction.guild.id,
                    channel_id=interaction.channel_id
                )
            )

            if room is None:
                await interaction.response.send_message(
                    "❌ 현재 채널에는 연결된 내전 방이 없습니다.",
                    ephemeral=True
                )
                return

            async with room.operation_lock:
                await self._delete_room_locked(
                    interaction
                )

    async def _delete_room_locked(
        self,
        interaction: discord.Interaction
    ):
        if not is_admin(interaction):
            await send_admin_only_message(
                interaction
            )
            return

        if (
            interaction.guild is None
            or interaction.channel_id is None
        ):
            await interaction.response.send_message(
                "❌ 서버 채널에서만 사용할 수 있습니다.",
                ephemeral=True
            )
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        room_manager = (
            join_cog.room_manager
        )

        room = (
            room_manager.get_room_by_channel(
                guild_id=interaction.guild.id,
                channel_id=interaction.channel_id
            )
        )

        if room is None:
            await interaction.response.send_message(
                "❌ 현재 채널에는 연결된 내전 방이 없습니다.",
                ephemeral=True
            )
            return

        if room.players:
            await interaction.response.send_message(
                "❌ 참가자가 남아 있어 내전 방을 삭제할 수 없습니다.\n"
                "먼저 `/내전종료`를 실행해주세요.",
                ephemeral=True
            )
            return

        if (
            room.current_teams is not None
            or room.match_in_progress
            or room.mvp_vote_in_progress
            or room.match_transaction_active
            or room.match_transaction_committed
            or room.pending_match_token is not None
            or room.pending_series_score is not None
            or room.pending_series_game is not None
        ):
            await interaction.response.send_message(
                "❌ 경기 상태가 남아 있어 내전 방을 삭제할 수 없습니다.\n"
                "먼저 `/내전종료`를 실행해주세요.",
                ephemeral=True
            )
            return

        room.invalidate_game_views()

        recruit_view = (
            room.current_recruit_view
        )

        if recruit_view is not None:
            recruit_view.recruit_closed = True

            for item in recruit_view.children:
                if isinstance(
                    item,
                    discord.ui.Button
                ):
                    item.disabled = True

            if recruit_view.message is not None:
                try:
                    await recruit_view.message.edit(
                        embed=recruit_view.create_embed(),
                        view=recruit_view
                    )

                except discord.HTTPException:
                    pass

            room.current_recruit_view = None

        deleted_room = (
            room_manager.remove_room(
                room.room_id
            )
        )

        if deleted_room is None:
            await interaction.response.send_message(
                "❌ 내전 방 삭제에 실패했습니다.",
                ephemeral=True
            )
            return

        join_cog.save_rooms_state()

        await interaction.response.send_message(
            "✅ 현재 채널의 내전 방을 삭제했습니다.\n\n"
            f"삭제된 방 번호: `{room.room_id}`\n"
            f"삭제된 방 이름: **{room.room_name}**"
        )


async def setup(
    bot
):
    await bot.add_cog(
        Room(bot)
    )
