import asyncio
import logging
import discord

from config import MAX_PLAYERS

from utils.permissions import (
    is_admin,
    send_admin_only_message
)

from services.team_balancer import (
    generate_balanced_teams,
    validate_team_profiles
)
from utils.room_display import format_room_status


logger = logging.getLogger(__name__)


    
class ExpiredInhouseView(discord.ui.View):
    """재시작 전에 만들어진 persistent 버튼에 만료 안내를 보냅니다."""

    BUTTONS = (
        ("참가", "inhouse_join"),
        ("참가취소", "inhouse_cancel"),
        ("명단 확인", "inhouse_list"),
        ("팀 생성", "inhouse_make_teams"),
        ("모집 종료", "inhouse_close"),
        ("모집 초기화", "inhouse_reset"),
        ("경기 시작", "match_start_button")
    )

    def __init__(self):
        super().__init__(timeout=None)

        for label, custom_id in self.BUTTONS:
            button = discord.ui.Button(
                label=label,
                custom_id=custom_id,
                style=discord.ButtonStyle.secondary
            )
            button.callback = self.send_expired_message
            self.add_item(button)

    async def send_expired_message(
        self,
        interaction: discord.Interaction
    ):
        await interaction.response.send_message(
            "❌ 봇이 재시작되어 이 버튼은 만료되었습니다.\n"
            "현재 채널에서 `/내전모집`을 실행해 새 모집창을 "
            "사용해주세요.",
            ephemeral=True
        )


class MatchControlView(discord.ui.View):

    def __init__(self, join_cog):
        super().__init__(timeout=None)

        self.join_cog = join_cog

        # 경기 시작 버튼이 만들어진 내전 방을 기억합니다.
        self.room = (
            join_cog.active_room
        )
        self.teams_reference = self.room.current_teams

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ) -> bool:
        if not self.join_cog.activate_room(
            self.room
        ):
            await interaction.response.send_message(
                "❌ 연결된 내전 방을 찾지 못했습니다.",
                ephemeral=True
            )
            return False

        if self.join_cog.current_teams is None:
            await interaction.response.send_message(
                "❌ 이 경기는 이미 종료되었습니다.",
                ephemeral=True
            )
            return False

        if self.room.current_teams is not self.teams_reference:
            await interaction.response.send_message(
                "❌ 팀이 다시 생성되어 이 경기 시작 버튼은 "
                "만료되었습니다.\n가장 최근 팀 메시지의 버튼을 "
                "사용해주세요.",
                ephemeral=True
            )
            return False

        return True


    @discord.ui.button(
        label="🎮 경기 시작",
        style=discord.ButtonStyle.success,
        custom_id="match_start_button"
    )
    async def start_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        self.join_cog.activate_room(
            self.room
        )

        if not is_admin(interaction):
            await send_admin_only_message(
                interaction
            )
            return


        async with self.room.operation_lock:
            if self.room.current_teams is None:
                await interaction.response.send_message(
                    "❌ 먼저 팀을 생성해주세요.",
                    ephemeral=True
                )
                return

            if self.room.current_teams is not self.teams_reference:
                await interaction.response.send_message(
                    "❌ 팀이 다시 생성되어 이 경기 시작 버튼은 "
                    "만료되었습니다.\n"
                    "가장 최근 팀 메시지의 버튼을 사용해주세요.",
                    ephemeral=True
                )
                return

            if self.room.match_in_progress:
                await interaction.response.send_message(
                    "❌ 이미 경기 중입니다.",
                    ephemeral=True
                )
                return

            self.room.match_in_progress = True

            self.join_cog.save_rooms_state()

            button.disabled = True

        await interaction.response.edit_message(
            view=self
        )

        await interaction.followup.send(
            f"🎮 **{self.room.room_name} 경기가 "
            "시작되었습니다!**\n\n"
            f"{format_room_status(self.room)}\n\n"
            f"경기 종료 후 <#{self.room.channel_id}>에서 "
            "`/경기결과`를 입력해주세요."
        )


class JoinView(discord.ui.View):

    def __init__(self, join_cog):
        # timeout=None이면 봇이 켜져 있는 동안 버튼이 만료되지 않습니다.
        super().__init__(timeout=None)

        self.join_cog = join_cog
        self.room = join_cog.active_room
        self.recruit_closed = False
        self.message = None

        # 팀 생성 중복 실행 방지
        self.team_generating = False

        if len(self.join_cog.players) < MAX_PLAYERS:
            self.make_teams_button.disabled = True

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ) -> bool:
        if not await self.join_cog.require_room(
            interaction
        ):
            return False
        
        # 현재 모집창이 아니면 오래된 버튼으로 판단
        if self.join_cog.current_recruit_view is not self:
            await interaction.response.send_message(
                "❌ 만료된 내전 모집창입니다.\n"
                "가장 최근에 생성된 모집창을 이용해주세요.",
                ephemeral=True
            )
            return False

        return True

    def create_embed(self):
        """현재 참가자 정보를 모집 메시지로 만듭니다."""

        players = self.join_cog.players

        self.make_teams_button.disabled = (
            len(players) < MAX_PLAYERS
        )

        if self.recruit_closed:
            title = "🔒 내전 모집 종료"
            description = (
                "모집이 종료되었습니다.\n\n"
                f"👥 현재 참가자: **{len(players)}/{MAX_PLAYERS}명**"
            )
        else:
            title = "🎮 내전 참가 모집"
            description = (
                "아래 버튼을 눌러 내전에 참가하세요.\n\n"
                f"👥 현재 참가자: **{len(players)}/{MAX_PLAYERS}명**"
            )

        description = (
            f"{format_room_status(self.room)}\n\n"
            f"{description}"
        )

        embed = discord.Embed(
            title=title,
            description=description
        )

        if players:
            participant_list = []

            self.join_cog.reload_profiles()

            tier_short = {
                "아이언": "I",
                "브론즈": "B",
                "실버": "S",
                "골드": "G",
                "플래티넘": "P",
                "에메랄드": "E",
                "다이아": "D",
                "언랭크": "UR"
            }

            position_short = {
                "TOP": "TOP",
                "JUNGLE": "JUN",
                "MID": "MID",
                "ADC": "ADC",
                "SUPPORT": "SUP"
            }

            for index, user_id in enumerate(players, start=1):

                profile = self.join_cog.profiles.get(user_id)

                if profile:
                    tier = tier_short.get(
                        profile.get("tier", "언랭크"),
                        "?"
                    )

                    rating = profile.get(
                        "rating",
                        1000
                    )

                    main = position_short.get(
                        profile.get("main_position", ""),
                        "-"
                    )

                    sub = position_short.get(
                        profile.get("sub_position", ""),
                        "-"
                    )

                else:
                    tier = "?"
                    rating = "-"
                    main = "-"
                    sub = "-"

                participant_list.append(
                    f"**{index}.** "
                    f"<@{user_id}> · "
                    f"**{tier}** · "
                    f"⭐{rating} · "
                    f"`{main}/{sub}`"
                )

            embed.add_field(
                name="📋 참가자 명단",
                value="\n".join(participant_list),
                inline=False
            )
        else:
            embed.add_field(
                name="📋 참가자 명단",
                value="아직 참가자가 없습니다.",
                inline=False
            )

        if self.recruit_closed:
            embed.set_footer(
                text="모집이 종료되었습니다."
            )
        else:
            embed.set_footer(
                text="참가 또는 참가취소 버튼을 눌러주세요."
            )

        return embed

    @discord.ui.button(
        label="참가",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="inhouse_join"
    )
    async def join_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        async with (
            self.join_cog.room_manager
            .management_lock
        ):
            await self._join_button_locked(
                interaction,
                button
            )

    async def _join_button_locked(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        user_id = str(interaction.user.id)
        room = self.join_cog.active_room

        async with room.operation_lock:
            players = room.players

            self.join_cog.reload_profiles()

            if room.match_in_progress:
                await interaction.response.send_message(
                    "❌ 현재 경기가 진행 중입니다.",
                    ephemeral=True
                )
                return

            if self.recruit_closed:
                await interaction.response.send_message(
                    "🔒 모집이 종료되었습니다.",
                    ephemeral=True
                )
                return

            if user_id not in self.join_cog.profiles:
                await interaction.response.send_message(
                    "❌ 내전에 참가하려면 먼저 `/가입`으로 "
                    "프로필 등록을 완료해주세요.",
                    ephemeral=True
                )
                return

            if user_id in players:
                await interaction.response.send_message(
                    "❌ 이미 참가 중입니다.",
                    ephemeral=True
                )
                return

            other_room = (
                self.join_cog.room_manager
                .find_player_room(
                    user_id
                )
            )

            if other_room is not None:
                await interaction.response.send_message(
                    "❌ 다른 내전에 이미 참가 중입니다.\n"
                    f"현재 참가 중인 방: "
                    f"**{other_room.room_name}**",
                    ephemeral=True
                )
                return

            if len(players) >= MAX_PLAYERS:
                await interaction.response.send_message(
                    f"❌ 참가 인원이 {MAX_PLAYERS}명으로 마감되었습니다.",
                    ephemeral=True
                )
                return

            players[user_id] = {
                "nickname": interaction.user.display_name
            }

            self.join_cog.save_rooms_state()

            self.make_teams_button.disabled = (
                len(players) < MAX_PLAYERS
            )

            await interaction.response.edit_message(
                embed=self.create_embed(),
                view=self
            )

            await interaction.followup.send(
                "✅ 내전에 참가했습니다.",
                ephemeral=True
            )

    @discord.ui.button(
        label="참가취소",
        emoji="❌",
        style=discord.ButtonStyle.danger,
        custom_id="inhouse_cancel"
    )
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        user_id = str(interaction.user.id)
        room = self.join_cog.active_room

        async with room.operation_lock:
            players = room.players

            if self.recruit_closed:
                await interaction.response.send_message(
                    "🔒 모집이 종료되어 참가 취소가 불가능합니다.",
                    ephemeral=True
                )
                return

            if room.match_in_progress:
                await interaction.response.send_message(
                    "❌ 경기 중에는 참가 취소가 불가능합니다.",
                    ephemeral=True
                )
                return

            if user_id not in players:
                await interaction.response.send_message(
                    "❌ 현재 참가 중이 아닙니다.",
                    ephemeral=True
                )
                return

            del players[user_id]
            self.join_cog.save_rooms_state()

            self.make_teams_button.disabled = (
                len(players) < MAX_PLAYERS
            )

            await interaction.response.edit_message(
                embed=self.create_embed(),
                view=self
            )

            await interaction.followup.send(
                "✅ 참가가 취소되었습니다.",
                ephemeral=True
            )

    @discord.ui.button(
        label="명단 확인",
        emoji="📋",
        style=discord.ButtonStyle.secondary,
        custom_id="inhouse_list"
    )
    async def list_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        room = self.join_cog.active_room

        async with room.operation_lock:
            player_ids = list(
                room.players.keys()
            )

        if not player_ids:
            await interaction.response.send_message(
                "📋 현재 참가자가 없습니다.",
                ephemeral=True
            )
            return

        participant_list = []

        for index, user_id in enumerate(
            player_ids,
            start=1
        ):
            participant_list.append(
                f"{index}. <@{user_id}>"
            )

        await interaction.response.send_message(
            f"📋 **현재 참가자 "
            f"({len(player_ids)}/{MAX_PLAYERS}명)**\n\n"
            + "\n".join(participant_list),
            ephemeral=True
        )

    async def generate_teams(
        self,
        interaction: discord.Interaction
    ):
        """현재 방의 팀 생성을 한 번에 하나씩 처리합니다."""

        room = self.join_cog.active_room

        if room.team_generation_lock.locked():
            await interaction.response.send_message(
                "⏳ 이 내전방은 이미 팀을 생성하고 있습니다.\n"
                "현재 작업이 끝난 뒤 다시 시도해주세요.",
                ephemeral=True
            )
            return

        async with room.team_generation_lock:
            async with room.operation_lock:
                await self._generate_teams(
                    interaction,
                    room
                )

    async def _generate_teams(
        self,
        interaction: discord.Interaction,
        room
    ):
        """포지션과 레이팅을 고려해 팀을 생성합니다."""

        if room.mvp_vote_in_progress:
            await interaction.response.send_message(
                "❌ MVP 투표 중에는 팀을 다시 생성할 수 없습니다.",
                ephemeral=True
            )
            return

        if room.match_in_progress:
            await interaction.response.send_message(
                "❌ 경기 진행 중에는 팀을 다시 생성할 수 없습니다.\n"
                "먼저 세트를 정상 종료하거나 취소해주세요.",
                ephemeral=True
            )
            return

        self.join_cog.reload_profiles()

        players = list(self.join_cog.players.keys())

        if len(players) != MAX_PLAYERS:

            # 팀 생성 완료
            

            await interaction.response.send_message(
                f"❌ 아직 {MAX_PLAYERS}명이 모이지 않았습니다.\n"
                f"현재 {len(players)}/{MAX_PLAYERS}명입니다.",
                ephemeral=True
            )
            return

        if interaction.guild is None:

            

            await interaction.response.send_message(
                "❌ 서버 안에서만 팀을 생성할 수 있습니다.",
                ephemeral=True
            )
            return

        # 계산과 음성채널 이동 중 상호작용 시간 초과를 방지합니다.
        await interaction.response.defer()


        profiles = self.join_cog.profiles

        validation_errors = (
            validate_team_profiles(
                players=players,
                profiles=profiles
            )
        )

        if validation_errors:
            

            error_lines = []

            for error in validation_errors:
                user_id, error_message = (
                    error.split(
                        ": ",
                        1
                    )
                )

                error_lines.append(
                    f"• <@{user_id}>: "
                    f"{error_message}"
                )

            await interaction.followup.send(
                "❌ 참가자 프로필 정보에 문제가 있습니다.\n\n"
                + "\n".join(
                    error_lines
                )
                + "\n\n프로필을 수정한 뒤 다시 시도해주세요.",
                ephemeral=True
            )
            return


        balance_result = await asyncio.to_thread(
            generate_balanced_teams,
            players=players,
            profiles=profiles,
            last_team_signature=(
                self.join_cog.last_team_signature
            )
        )

        current_players = list(
            self.join_cog.players.keys()
        )

        if current_players != players:
            await interaction.followup.send(
                "⚠️ 팀 계산 중 참가자 명단이 변경되었습니다.\n"
                "현재 명단을 기준으로 `팀 생성` 버튼을 "
                "다시 눌러주세요.",
                ephemeral=True
            )
            return

        if balance_result is None:

            

            await interaction.followup.send(
                "❌ 유효한 팀 조합을 찾지 못했습니다.",
                ephemeral=True
            )
            return

        best_red_assignment = (
            balance_result[
                "red_assignment"
            ]
        )

        best_blue_assignment = (
            balance_result[
                "blue_assignment"
            ]
        )

        red_mmr = balance_result[
            "red_mmr"
        ]

        blue_mmr = balance_result[
            "blue_mmr"
        ]

        selected_total_penalty = (
            balance_result[
                "total_penalty"
            ]
        )

        mmr_difference = balance_result[
            "mmr_difference"
        ]

        position_penalty = balance_result[
            "position_penalty"
        ]

        same_team_penalty = balance_result[
            "same_team_penalty"
        ]

        opponent_penalty = balance_result[
            "opponent_penalty"
        ]

        weighted_mmr_penalty = balance_result[
            "weighted_mmr_penalty"
        ]

        weighted_position_penalty = balance_result[
            "weighted_position_penalty"
        ]

        weighted_same_team_penalty = balance_result[
            "weighted_same_team_penalty"
        ]

        weighted_opponent_penalty = balance_result[
            "weighted_opponent_penalty"
        ]

        self.join_cog.last_team_signature = (
            balance_result[
                "signature"
            ]
        )

        self.join_cog.current_teams = {
            "red": best_red_assignment,
            "blue": best_blue_assignment
        }

        # 화면에는 Hidden MMR 대신 공개 레이팅만 표시합니다.
        red_rating = sum(
            profiles.get(user_id, {}).get(
                "rating",
                1000
            )
            for user_id in best_red_assignment.values()
        )

        blue_rating = sum(
            profiles.get(user_id, {}).get(
                "rating",
                1000
            )
            for user_id in best_blue_assignment.values()
        )

        logger.info(
            "팀 생성 완료 | 방=%s | MMR차이=%s(가중=%s) | "
            "포지션=%s(가중=%s) | 같은팀=%s(가중=%s) | "
            "상대=%s(가중=%s) | 최종=%s",
            room.room_id,
            mmr_difference,
            weighted_mmr_penalty,
            position_penalty,
            weighted_position_penalty,
            same_team_penalty,
            weighted_same_team_penalty,
            opponent_penalty,
            weighted_opponent_penalty,
            selected_total_penalty
        )

        self.join_cog.save_rooms_state()

        red_list = "\n".join(
            f"**{position}** - <@{user_id}> "
            f"({profiles.get(user_id, {}).get('rating', 1000)})"
            for position, user_id in best_red_assignment.items()
        )

        blue_list = "\n".join(
            f"**{position}** - <@{user_id}> "
            f"({profiles.get(user_id, {}).get('rating', 1000)})"
            for position, user_id in best_blue_assignment.items()
        )

        embed = discord.Embed(
            title=(
                f"🎲 {room.room_name} · "
                "밸런스 팀 생성 완료"
            ),
            description=(
                f"{format_room_status(room)}\n\n"
                f"레이팅 차이: "
                f"**{abs(red_rating - blue_rating)}점**"
            )
        )

        embed.add_field(
            name=f"🔴 레드팀 · {red_rating}점",
            value=red_list,
            inline=True
        )

        embed.add_field(
            name=f"🔵 블루팀 · {blue_rating}점",
            value=blue_list,
            inline=True
        )

        guild = interaction.guild

        blue_voice_result = (
            await self.join_cog.move_members_to_voice_channel(
                guild=guild,
                user_ids=best_blue_assignment.values(),
                channel_id=room.blue_voice_channel_id
            )
        )

        red_voice_result = (
            await self.join_cog.move_members_to_voice_channel(
                guild=guild,
                user_ids=best_red_assignment.values(),
                channel_id=room.red_voice_channel_id
            )
        )

        voice_results = (
            blue_voice_result,
            red_voice_result
        )

        moved_count = sum(
            result["moved"]
            for result in voice_results
        )

        already_connected_count = sum(
            result["already_connected"]
            for result in voice_results
        )

        not_connected_count = sum(
            result["not_connected"]
            for result in voice_results
        )

        failed_count = sum(
            result["failed"]
            for result in voice_results
        )

        channel_missing = any(
            result["channel_missing"]
            for result in voice_results
        )

        voice_result_parts = [
            f"{moved_count}명 이동"
        ]

        if already_connected_count:
            voice_result_parts.append(
                f"{already_connected_count}명 이미 위치"
            )

        if not_connected_count:
            voice_result_parts.append(
                f"{not_connected_count}명 음성 미접속"
            )

        if failed_count:
            voice_result_parts.append(
                f"{failed_count}명 이동 실패"
            )

        voice_result_text = ", ".join(
            voice_result_parts
        )

        if channel_missing:
            embed.set_footer(
                text=(
                    f"⚠️ {room.room_name}의 팀 음성채널 일부가 "
                    "설정되지 않았거나 삭제되었습니다. "
                    f"처리 결과: {voice_result_text}"
                )
            )

        else:
            embed.set_footer(
                text=(
                    f"음성채널 처리 결과: "
                    f"{voice_result_text}"
                )
            )

    
        

        # 팀 생성 후 모집창 잠금
        self.recruit_closed = True

        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id not in [
                    "inhouse_list",
                    "inhouse_reset"
                ]:
                    item.disabled = True


        try:
            await interaction.message.edit(
                embed=self.create_embed(),
                view=self
            )
        except discord.HTTPException:
            pass


        output_message, used_fallback = (
            await self.join_cog.send_output_message(
                room=room,
                fallback_channel=interaction.channel,
                embed=embed,
                view=MatchControlView(
                    self.join_cog
                )
            )
        )

        if output_message is None:
            confirmation_message = (
                "⚠️ 팀 생성은 정상적으로 완료됐지만 "
                "결과 메시지를 전송하지 못했습니다.\n"
                "공용 진행 채널과 모집 채널에서 꼬붕봇의 "
                "`채널 보기`, `메시지 보내기`, "
                "`링크 첨부` 권한을 확인해주세요."
            )

        elif used_fallback:
            confirmation_message = (
                "⚠️ 팀 생성은 정상적으로 완료됐습니다.\n"
                "공용 진행 채널에 접근할 수 없어 "
                "현재 모집 채널에 결과를 표시했습니다.\n"
                "공용 진행 채널에서 꼬붕봇의 "
                "`채널 보기`와 `메시지 보내기` "
                "권한을 확인해주세요."
            )

        elif (
            output_message.channel.id
            == interaction.channel_id
        ):
            confirmation_message = (
                "✅ 팀 생성 결과를 현재 채널에 표시했습니다."
            )

        else:
            confirmation_message = (
                "✅ 팀 생성 결과를 공용 진행 채널에 "
                "표시했습니다.\n"
                f"진행 채널: "
                f"<#{output_message.channel.id}>"
            )

        await interaction.followup.send(
            confirmation_message,
            ephemeral=True
        )

    @discord.ui.button(
        label="팀 생성",
        emoji="🎲",
        style=discord.ButtonStyle.primary,
        custom_id="inhouse_make_teams"
    )
    async def make_teams_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        if not is_admin(interaction):
            await send_admin_only_message(
                interaction
            )
            return
        
        if self.team_generating:
            await interaction.response.send_message(
                "⏳ 이미 팀 생성 중입니다.",
                ephemeral=True
            )
            return

        self.team_generating = True
        self.team_generation_user = (
            interaction.user.id
        )

        try:
            await self.generate_teams(
                interaction
            )

        except Exception as error:
            logger.exception(
                "팀 생성 중 오류: %r",
                error
            )

            message = (
                "❌ 팀 생성 중 오류가 발생했습니다.\n"
                "잠시 후 다시 시도해주세요."
            )

            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        message,
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        message,
                        ephemeral=True
                    )

            except discord.HTTPException:
                pass

        finally:
            self.team_generating = False
            self.team_generation_user = None
            

    @discord.ui.button(
        label="모집 종료",
        emoji="🔒",
        style=discord.ButtonStyle.secondary,
        custom_id="inhouse_close"
    )
    async def close_recruitment_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not is_admin(interaction):
            await send_admin_only_message(
                interaction
            )
            return

        room = self.join_cog.active_room

        async with room.operation_lock:
            self.recruit_closed = True

            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    if item.custom_id not in [
                        "inhouse_list",
                        "inhouse_reset"
                    ]:
                        item.disabled = True

            await interaction.response.edit_message(
                embed=self.create_embed(),
                view=self
            )

            await interaction.followup.send(
                "🔒 모집을 종료했습니다.",
                ephemeral=True
            )

    @discord.ui.button(
        label="모집 초기화",
        emoji="🔄",
        style=discord.ButtonStyle.success,
        custom_id="inhouse_reset"
    )
    async def reset_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        if not is_admin(interaction):
            await send_admin_only_message(
                interaction
            )
            return

        room = self.join_cog.active_room

        async with room.operation_lock:
            room.reset_game(keep_recruit_view=True)

            self.join_cog.save_rooms_state()

            self.recruit_closed = False

            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = False

            self.make_teams_button.disabled = True

            await interaction.response.edit_message(
                embed=self.create_embed(),
                view=self
            )

            await interaction.followup.send(
                "🔄 모집이 초기화되었습니다.",
                ephemeral=True
            )
