import discord

from config import MAX_WAITING_PLAYERS
from utils.positions import normalize_position


def is_joinable_recruitment_room(room, guild_id):
    """등록 직후 참가 선택에 표시할 수 있는 모집 방인지 확인합니다."""

    recruit_view = room.current_recruit_view
    return bool(
        room.guild_id == guild_id
        and recruit_view is not None
        and recruit_view.message is not None
        and not getattr(recruit_view, "recruit_closed", False)
        and not getattr(recruit_view, "team_generating", False)
        and not room.team_generation_lock.locked()
        and room.current_teams is None
        and not room.match_in_progress
        and not getattr(room, "single_draft_mode_active", False)
        and (
            len(room.players) < room.player_limit
            or len(room.waiting_players) < MAX_WAITING_PLAYERS
        )
    )


class RegistrationJoinView(discord.ui.View):
    """프로필 등록 직후 모집 중인 내전에 참가하도록 안내합니다."""

    def __init__(self, join_cog, guild_id, rooms, registration_message, announcement_url=None):
        super().__init__(timeout=300)
        self.join_cog = join_cog
        self.guild_id = guild_id
        self.registration_message = registration_message
        self.selection_prompt = (
            "🎮 **모집 중인 내전방**\n"
            "참가할 방을 선택하고 아래 버튼을 눌러주세요. "
            "정원이 찬 방은 대기자로 등록됩니다."
        )
        self.selected_room_id = None

        options = []
        for room in rooms[:25]:
            if len(room.players) < room.player_limit:
                status = f"참가 {len(room.players)}/{room.player_limit}명"
            else:
                status = f"대기 {len(room.waiting_players)}/{MAX_WAITING_PLAYERS}명"
            options.append(
                discord.SelectOption(
                    label=f"{room.room_name} · {status}"[:100],
                    value=str(room.room_id),
                    description="모집 중 · 선택 후 참가 버튼을 눌러주세요"
                )
            )

        self.add_item(RegistrationRoomSelect(options, self))
        self.join_selected_button.disabled = True

        if announcement_url:
            self.add_item(discord.ui.Button(
                label="모집 안내 채널",
                emoji="📣",
                style=discord.ButtonStyle.link,
                url=announcement_url,
                row=1
            ))

    @discord.ui.button(
        label="선택한 내전에 참가",
        emoji="✅",
        style=discord.ButtonStyle.success,
        disabled=True,
        row=1
    )
    async def join_selected_button(self, interaction, button):
        if self.selected_room_id is None:
            await interaction.response.send_message(
                "먼저 참가할 내전방을 선택해주세요.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        join_cog = self.join_cog
        user_id = str(interaction.user.id)
        result = None
        joined_room_view = None
        waiting = False

        async with join_cog.room_manager.management_lock:
            room = join_cog.room_manager.get_room(self.selected_room_id)
            if room is None or room.guild_id != self.guild_id:
                result = "❌ 선택한 내전방을 찾을 수 없습니다. 모집 안내 채널에서 최신 모집을 확인해주세요."
            else:
                join_cog.activate_room(room)
                async with room.operation_lock:
                    recruit_view = room.current_recruit_view
                    if not is_joinable_recruitment_room(room, self.guild_id):
                        result = "❌ 이 내전은 방금 마감됐거나 팀 편성이 시작됐습니다. 모집 안내 채널에서 다른 모집을 확인해주세요."
                    elif user_id not in join_cog.profiles:
                        result = "❌ 프로필 등록을 확인하지 못했습니다. 안내방에서 통합 프로필 등록을 다시 완료해주세요."
                    elif user_id in room.players:
                        result = f"ℹ️ 이미 **{room.room_name}** 참가자 명단에 등록되어 있습니다."
                    elif user_id in room.waiting_players:
                        waiting_number = list(room.waiting_players).index(user_id) + 1
                        result = f"ℹ️ 이미 **{room.room_name}** 대기 {waiting_number}번으로 등록되어 있습니다."
                    else:
                        other_room = join_cog.room_manager.find_player_room(user_id)
                        if other_room is not None:
                            result = (
                                "❌ 한 번에 한 내전만 참가할 수 있습니다.\n"
                                f"현재 **{other_room.room_name}**에서 참가 또는 대기 중입니다."
                            )
                        elif (
                            len(room.players) >= room.player_limit
                            and len(room.waiting_players) >= MAX_WAITING_PLAYERS
                        ):
                            result = f"❌ **{room.room_name}** 참가와 대기가 모두 마감됐습니다."
                        else:
                            nickname = interaction.user.display_name
                            if len(room.players) >= room.player_limit:
                                room.waiting_players[user_id] = {"nickname": nickname}
                                waiting = True
                                queue_number = len(room.waiting_players)
                                result = (
                                    f"🕒 **{room.room_name}** 대기 {queue_number}번으로 등록됐습니다.\n"
                                    f"현재 대기자: {queue_number}/{MAX_WAITING_PLAYERS}명"
                                )
                            else:
                                room.players[user_id] = {"nickname": nickname}
                                result = f"✅ **{room.room_name}** 참가자 명단에 등록됐습니다."

                            join_cog.save_rooms_state()
                            recruit_view.make_teams_button.disabled = (
                                len(room.players) < room.player_limit
                            )
                            joined_room_view = recruit_view
                            if recruit_view.message is not None:
                                try:
                                    await recruit_view.message.edit(
                                        embeds=recruit_view.create_embeds(),
                                        view=recruit_view
                                    )
                                except discord.HTTPException:
                                    result += "\n⚠️ 참가 처리는 완료됐지만 모집창 갱신에 실패했습니다. 진행자에게 알려주세요."

        if joined_room_view is not None:
            try:
                from views.join_view import announce_recruitment_join
                await announce_recruitment_join(
                    joined_room_view,
                    user_id,
                    waiting=waiting
                )
            except Exception:
                # 참가 처리는 성공한 상태이므로 알림 실패가 등록을 되돌리지는 않습니다.
                pass

        await interaction.edit_original_response(
            content=f"{self.registration_message}\n\n{result}",
            view=None
        )
        self.stop()


class RegistrationRoomSelect(discord.ui.Select):
    def __init__(self, options, parent_view):
        self.parent_view = parent_view
        super().__init__(
            placeholder="참가할 내전방을 선택하세요",
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )

    async def callback(self, interaction):
        self.parent_view.selected_room_id = self.values[0]
        self.parent_view.join_selected_button.disabled = False
        selected_room = self.parent_view.join_cog.room_manager.get_room(
            self.values[0]
        )
        room_name = (
            selected_room.room_name
            if selected_room is not None
            else "선택한 내전"
        )
        await interaction.response.edit_message(
            content=(
                f"{self.parent_view.registration_message}\n\n"
                f"{self.parent_view.selection_prompt}\n"
                f"선택한 방: **{room_name}**\n"
                "아래 [선택한 내전에 참가] 버튼을 눌러주세요."
            ),
            view=self.parent_view
        )


class RegisterView(discord.ui.View):

    def __init__(self, bot):
        super().__init__(timeout=None)

        self.bot = bot

    @discord.ui.button(
        label="통합 프로필 등록",
        style=discord.ButtonStyle.green,
        custom_id="register_profile_button"
    )
    async def register(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.send_modal(
            RegisterModal(self.bot)
        )


class RegisterModal(discord.ui.Modal):

    def __init__(self, bot):
        super().__init__(
            title="프로필 등록"
        )

        self.bot = bot

        self.riot_id = discord.ui.TextInput(
            label="Riot ID",
            placeholder="Blueee#KR1",
            max_length=40
        )

        self.highest_tier = discord.ui.TextInput(
            label="최고 티어",
            placeholder=(
                "아이언 / 브론즈 / 실버 / 골드 / 플레 / 에메랄드 / "
                "다이아 / M1~M9 / GM / C"
            ),
            max_length=24
        )

        self.main = discord.ui.TextInput(
            label="주 포지션",
            placeholder="탑 / 정글 / 미드 / 원딜 / 서폿",
            max_length=8
        )

        self.sub = discord.ui.TextInput(
            label="부 포지션",
            placeholder="탑 / 정글 / 미드 / 원딜 / 서폿",
            max_length=8
        )

        self.add_item(self.riot_id)
        self.add_item(self.highest_tier)
        self.add_item(self.main)
        self.add_item(self.sub)

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        profile_cog = self.bot.get_cog("Profile")

        if profile_cog is None:
            await interaction.response.send_message(
                "❌ 프로필 등록 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        main_position = normalize_position(self.main.value)
        sub_position = normalize_position(self.sub.value)

        if main_position is None:
            await interaction.response.send_message(
                "❌ 주 포지션을 올바르게 입력해주세요.\n"
                "`탑`, `정글`, `미드`, `원딜`, `서폿` 중 하나를 입력해주세요.",
                ephemeral=True
            )
            return

        if sub_position is None:
            await interaction.response.send_message(
                "❌ 부 포지션을 올바르게 입력해주세요.\n"
                "`탑`, `정글`, `미드`, `원딜`, `서폿` 중 하나를 입력해주세요.",
                ephemeral=True
            )
            return

        if main_position == sub_position:
            await interaction.response.send_message(
                "❌ 주 포지션과 부 포지션은 다르게 선택해주세요.",
                ephemeral=True
            )
            return

        await profile_cog.process_registration(
            interaction=interaction,
            riot_id=str(self.riot_id.value),
            main_position=main_position,
            sub_position=sub_position,
            highest_tier=str(self.highest_tier.value)
        )
