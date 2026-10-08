import asyncio
import copy
import logging
import os
import random
import discord

from config import (
    MAX_PLAYERS,
    MAX_AUCTION_PLAYERS,
    MAX_WAITING_PLAYERS,
    MATCH_MODE
)

from utils.permissions import (
    is_match_operator as is_admin,
    send_match_operator_only_message as send_admin_only_message
)

from services.team_balancer import (
    generate_balanced_teams,
    validate_team_profiles,
    assign_positions,
    create_team_signature,
    POSITIONS
)
from services.tournament_service import (
    claim_fixture,
    create_auction_bracket,
    get_fixture,
    reopen_fixture,
    release_fixture,
    resolve_fixture,
)
from storage.sqlite_db import (
    get_active_season,
    get_season_player_stats,
    get_last_match,
    get_match_champion_progress
)
from utils.room_display import format_room_status


logger = logging.getLogger(__name__)

AUCTION_TEAM_BUDGET = 1000
AUCTION_MIN_BID = 50
AUCTION_BID_STEP = 50
AUCTION_LOT_SECONDS = 10
AUCTION_SIDES = (
    ("red", "🔴 레드팀"),
    ("blue", "🔵 블루팀"),
    ("green", "🟢 그린팀"),
    ("yellow", "🟡 옐로팀"),
)


async def send_ephemeral_response(interaction, content):
    """Send an ephemeral result whether this interaction was already deferred."""
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True)
    else:
        await interaction.response.send_message(content, ephemeral=True)


def add_match_button_instructions(embed):
    """팀 편성 결과에 버튼 사용 순서를 짧게 붙입니다."""
    instruction = (
        "**경기 진행 방법**\n"
        "1. 참가자 한 명이 `🎮 경기 시작`을 누릅니다.\n"
        "2. 경기가 끝나면 이 메시지에서 승리팀 버튼을 한 번 누릅니다."
    )
    description = (embed.description or "").rstrip()
    embed.description = f"{description}\n\n{instruction}" if description else instruction
    return embed


async def refresh_match_controls_at_bottom(
    join_cog,
    room,
    source_message,
    previous_view,
    stage="next_set"
):
    """다음 작업 버튼을 새 메시지로 올려 채널 하단에서 바로 누르게 합니다."""
    previous_view.start_button.disabled = room.match_in_progress
    previous_view.red_button.disabled = not room.match_in_progress
    previous_view.blue_button.disabled = not room.match_in_progress
    if hasattr(previous_view, "end_series_button"):
        previous_view.end_series_button.disabled = (
            room.match_in_progress or room.series_game <= 0
        )

    try:
        await source_message.edit(view=previous_view)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        logger.info(
            "이전 경기 조작 메시지 갱신 실패 | 방=%s",
            room.room_id
        )

    next_view = MatchControlView(join_cog)
    next_embed = None
    if source_message.embeds:
        next_embed = discord.Embed.from_dict(
            source_message.embeds[0].to_dict()
        )
        next_set = max(1, int(room.series_game) + 1)
        next_embed.title = (
            f"🎮 {room.room_name} · {next_set}세트 경기 조작"
        )
        score = room.series_score
        if stage == "in_progress":
            stage_line = "🎮 경기가 진행 중입니다. 끝나면 아래에서 승리팀을 선택하세요."
        elif stage == "reselect":
            stage_line = "↩️ 잘못된 결과를 취소했습니다. 이번 세트의 승리팀을 다시 선택하세요."
        else:
            stage_line = f"다음은 **{next_set}세트**입니다. 경기 시작 버튼을 눌러주세요."
        score_line = (
            f"📊 현재 시리즈 점수: 🔴 레드 **{score['red']}** : "
            f"**{score['blue']}** 블루 🔵\n"
            + stage_line
        )
        description = (next_embed.description or "").split(
            "\n\n📊 현재 시리즈 점수:",
            1
        )[0].strip()
        next_embed.description = (
            f"{description}\n\n{score_line}"
            if description else score_line
        )

    content = source_message.content or None
    if next_embed is None and content is None:
        content = (
            f"🎮 **{room.room_name} · "
            f"{max(1, int(room.series_game) + 1)}세트 경기 조작**\n"
            f"팀 편성 확인: {source_message.jump_url}"
        )

    try:
        new_message = await source_message.channel.send(
            content=content,
            embed=next_embed,
            view=next_view,
            allowed_mentions=discord.AllowedMentions.none()
        )
    except (discord.Forbidden, discord.HTTPException):
        logger.exception(
            "새 경기 조작 메시지를 채널 하단에 전송하지 못함 | 방=%s",
            room.room_id
        )
        return source_message, previous_view

    next_view.team_message = new_message
    # 이 세트의 결과 카드가 참조하는 컨텍스트도 최신 메시지를 가리키게 합니다.
    previous_view.team_message = new_message
    previous_view.stop()

    try:
        await source_message.edit(view=None)
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        logger.info(
            "이전 경기 조작 버튼 제거 실패 | 방=%s",
            room.room_id
        )

    return new_message, next_view


async def announce_recruitment_join(join_view, user_id, waiting=False):
    """내전 참가 등록을 홍보 채널에 알리고 모집글 바로가기를 붙입니다."""
    room = join_view.room
    channel_id = room.announcement_channel_id
    if channel_id is None or room.guild_id is None or room.channel_id is None:
        return

    bot = join_view.join_cog.bot
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            logger.warning(
                "내전 홍보 채널을 찾지 못했습니다 | room=%s | channel=%s",
                room.room_id,
                channel_id
            )
            return

    recruit_message = join_view.message
    if recruit_message is None:
        return

    participant_count = len(room.players)
    waiting_count = len(room.waiting_players)
    status = f"참가자 {participant_count}/{room.player_limit}명"
    if waiting or waiting_count:
        status += f" · 대기자 {waiting_count}/{MAX_WAITING_PLAYERS}명"
    registration_type = "대기 등록" if waiting else "참가 등록"

    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(
        label=f"{room.room_name} 모집 채널로 이동",
        emoji="📣",
        style=discord.ButtonStyle.link,
        url=recruit_message.jump_url
    ))

    try:
        await channel.send(
            f"@everyone 🔔 **{room.room_name} {registration_type} 알림**\n"
            f"현재 {status}입니다. 아래 버튼을 눌러 모집글로 이동하세요.",
            view=view,
            allowed_mentions=discord.AllowedMentions(
                everyone=True,
                users=False,
                roles=False
            )
        )
    except (discord.Forbidden, discord.HTTPException):
        logger.exception(
            "내전 참가 알림 전송 실패 | room=%s | channel=%s | user=%s",
            room.room_id,
            channel_id,
            user_id
        )


    
class ExpiredInhouseView(discord.ui.View):
    """재시작 전에 만들어진 persistent 버튼에 만료 안내를 보냅니다."""

    BUTTONS = (
        ("참가", "inhouse_join"),
        ("참가취소", "inhouse_cancel"),
        ("명단 확인", "inhouse_list"),
        ("인원 선택", "inhouse_capacity"),
        ("팀 생성", "inhouse_make_teams"),
        ("모집 종료", "inhouse_close"),
        ("모집 초기화", "inhouse_reset"),
        ("경기 시작", "match_start_button"),
        ("경기 시작", "match_start_participant_button"),
        ("레드팀 승리", "match_result_red_button"),
        ("블루팀 승리", "match_result_blue_button")
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


class EndSeriesConfirmView(discord.ui.View):
    """Requires an explicit second press before clearing an active series."""

    def __init__(
        self,
        bot,
        room,
        requester_id,
        control_view=None,
        source_message=None
    ):
        super().__init__(timeout=90)
        self.bot = bot
        self.room = room
        self.requester_id = str(requester_id)
        self.control_view = control_view
        self.source_message = source_message

    async def interaction_check(self, interaction):
        if str(interaction.user.id) != self.requester_id:
            await interaction.response.send_message(
                "❌ 종료 확인을 요청한 사람만 누를 수 있습니다.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(
        label="🛑 내전 종료 확인",
        style=discord.ButtonStyle.danger,
        row=0
    )
    async def confirm_button(self, interaction, button):
        # Acknowledge the component immediately. Editing the ephemeral view
        # first can itself exceed Discord's short interaction deadline.
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            if interaction.message is not None:
                await interaction.message.edit(
                    content="내전을 종료하고 결과 기록을 보존하는 중입니다…",
                    view=None
                )
            await interaction.edit_original_response(
                content="내전을 종료하고 결과 기록을 보존하는 중입니다…"
            )
        except discord.HTTPException:
            logger.exception("내전 종료 확인창 갱신 실패")
        game_cog = self.bot.get_cog("AdminGame")
        if game_cog is None:
            await interaction.edit_original_response(
                content="❌ 내전 종료 기능을 불러오지 못했습니다."
            )
            return
        try:
            await game_cog.confirm_end_series(
                interaction,
                self.room,
                control_view=self.control_view,
                source_message=self.source_message
            )
        except Exception as error:
            logger.exception(
                "내전 종료 처리 실패 | 방=%s",
                self.room.room_id
            )
            try:
                await interaction.edit_original_response(
                    content=(
                        "❌ 내전 종료 처리 중 오류가 발생했습니다. "
                        f"오류 종류: `{type(error).__name__}`. "
                        "관리자에게 이 오류 종류와 Render 로그를 전달해주세요."
                    )
                )
            except discord.HTTPException:
                pass
        self.stop()

    @discord.ui.button(
        label="계속 진행",
        style=discord.ButtonStyle.secondary,
        row=0
    )
    async def cancel_button(self, interaction, button):
        self.stop()
        await interaction.response.edit_message(
            content="✅ 내전을 계속 진행합니다.",
            view=None
        )


class SeriesRecoveryView(discord.ui.View):
    """Persistent operator-only button to restore a manually ended series."""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(
        label="↩️ 내전 이어서 진행",
        style=discord.ButtonStyle.primary,
        custom_id="inhouse_series_recovery",
        row=0
    )
    async def recover_button(self, interaction, button):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return
        join_cog = self.bot.get_cog("Join")
        if join_cog is None or not await join_cog.require_room(interaction):
            return

        room = join_cog.active_room
        async with room.operation_lock:
            snapshot = room.ended_series_snapshot
            if (
                not isinstance(snapshot, dict)
                or str(snapshot.get("recovery_message_id"))
                    != str(getattr(interaction.message, "id", ""))
            ):
                await interaction.response.send_message(
                    "❌ 이 복구 버튼은 이미 사용됐거나 최신 종료 기록이 아닙니다.",
                    ephemeral=True
                )
                return
            if (
                room.current_teams is not None
                or room.players
                or room.match_in_progress
                or room.match_transaction_active
            ):
                await interaction.response.send_message(
                    "❌ 방에 새 참가자나 경기가 생겨 복구할 수 없습니다. 현재 방을 먼저 정리해주세요.",
                    ephemeral=True
                )
                return

            tournament_id = snapshot.get("tournament_id")
            fixture_no = snapshot.get("tournament_fixture_no")
            if tournament_id and fixture_no:
                fixture = get_fixture(tournament_id, fixture_no)
                if fixture is None:
                    await interaction.response.send_message(
                        "❌ 미니컵 대진 정보를 찾지 못해 복구할 수 없습니다.",
                        ephemeral=True
                    )
                    return
                if fixture["status"] == "completed":
                    reopen_fixture(tournament_id, fixture_no)
                    fixture = get_fixture(tournament_id, fixture_no)
                if fixture["status"] == "ready":
                    if not claim_fixture(tournament_id, fixture_no):
                        await interaction.response.send_message(
                            "❌ 다른 진행자가 대진을 불러왔습니다. 대진표를 확인해주세요.",
                            ephemeral=True
                        )
                        return
                elif fixture["status"] != "in_progress":
                    await interaction.response.send_message(
                        "❌ 현재 대진 상태에서 경기를 복구할 수 없습니다.",
                        ephemeral=True
                    )
                    return

            join_cog.activate_room(room)
            room.players = copy.deepcopy(snapshot.get("players", {}))
            room.current_teams = copy.deepcopy(snapshot.get("current_teams"))
            room.series_score = dict(snapshot.get("series_score", {"red": 0, "blue": 0}))
            room.series_game = int(snapshot.get("series_game", 0))
            room.tournament_id = tournament_id
            room.tournament_fixture_no = fixture_no
            room.ended_series_snapshot = None
            room.match_in_progress = False
            room.last_team_signature = None
            join_cog.save_rooms_state()

            score = room.series_score
            next_set = room.series_game + 1
            embed = discord.Embed(
                title=f"↩️ {room.room_name} · 내전 복구",
                description=(
                    f"종료 전 상태로 복구했습니다. 이미 저장된 {room.series_game}세트 결과는 유지됩니다.\n"
                    f"현재 점수: 🔴 레드 **{score['red']}** : **{score['blue']}** 블루 🔵\n"
                    f"다음은 **{next_set}세트**입니다. 아래 경기 시작 버튼을 눌러주세요."
                )
            )
            for side, label in (("red", "🔴 레드팀"), ("blue", "🔵 블루팀")):
                assignment = room.current_teams.get(side, {})
                lines = [
                    f"**{position}** — <@{user_id}>"
                    for position, user_id in assignment.items()
                ]
                embed.add_field(name=label, value="\n".join(lines) or "-", inline=True)
            add_match_button_instructions(embed)
            output_message, _ = await join_cog.send_output_message(
                room=room,
                fallback_channel=interaction.channel,
                embed=embed,
                view=MatchControlView(join_cog)
            )
            if output_message is None:
                # Restore the recoverable state if the fresh controls could not be posted.
                room.reset_game()
                room.ended_series_snapshot = snapshot
                if tournament_id and fixture_no:
                    red_score = int(snapshot["series_score"].get("red", 0))
                    blue_score = int(snapshot["series_score"].get("blue", 0))
                    if red_score == blue_score:
                        release_fixture(tournament_id, fixture_no)
                    else:
                        side = "red" if red_score > blue_score else "blue"
                        fixture = get_fixture(tournament_id, fixture_no)
                        if fixture is not None:
                            resolve_fixture(
                                tournament_id,
                                fixture_no,
                                fixture[f"{side}_team_id"],
                                snapshot.get("last_match_id") or 0
                            )
                join_cog.save_rooms_state()
                await interaction.response.send_message(
                    "❌ 복구 버튼은 눌렀지만 경기 조작 메시지를 올리지 못했습니다. 종료 상태를 유지했습니다.",
                    ephemeral=True
                )
                return

            try:
                await interaction.response.edit_message(
                    content="✅ 복구를 완료했습니다. 새 경기 조작 메시지를 확인해주세요.",
                    view=None
                )
            except discord.HTTPException:
                pass
            await interaction.followup.send(
                f"✅ {room.room_name}을 {next_set}세트부터 이어서 진행합니다.",
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
        self.team_message = None
        self.players_snapshot = copy.deepcopy(
            getattr(self.room, "players", {})
        )
        self.teams_snapshot = copy.deepcopy(self.room.current_teams)
        self.series_score_snapshot = dict(
            getattr(self.room, "series_score", {"red": 0, "blue": 0})
        )
        self.series_game_snapshot = getattr(self.room, "series_game", 0)
        self.tournament_id_snapshot = getattr(self.room, "tournament_id", None)
        self.tournament_fixture_no_snapshot = getattr(
            self.room, "tournament_fixture_no", None
        )
        self.champion_record_view = None
        self._result_lock = asyncio.Lock()

        # 한 장의 팀 안내 메시지에서 시작과 결과 등록을 모두 처리합니다.
        # 방금 팀이 만들어졌다면 시작만 누를 수 있고, 경기 중이라면
        # 승리팀 버튼만 누를 수 있습니다.
        self.start_button.disabled = self.room.match_in_progress
        self.red_button.disabled = not self.room.match_in_progress
        self.blue_button.disabled = not self.room.match_in_progress
        self.end_series_button.disabled = (
            self.room.match_in_progress or self.room.series_game <= 0
        )
        if self.room.series_game <= 0:
            self.remove_item(self.end_series_button)

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

        team_ids = {
            str(user_id)
            for team in (self.room.current_teams or {}).values()
            if isinstance(team, dict)
            for user_id in team.values()
        }
        if (
            not is_admin(interaction)
            and str(interaction.user.id) not in team_ids
        ):
            await interaction.response.send_message(
                "❌ 현재 내전 참가자만 경기 버튼을 사용할 수 있습니다.",
                ephemeral=True
            )
            return False

        return True


    @discord.ui.button(
        label="🎮 경기 시작",
        style=discord.ButtonStyle.success,
        custom_id="match_start_participant_button"
    )
    async def start_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        self.join_cog.activate_room(
            self.room
        )
        self.team_message = interaction.message
        # The room lock can be busy while another room or match operation is
        # finishing. Acknowledge this click before waiting for it.
        await interaction.response.defer()

        async with self.room.operation_lock:
            if self.room.current_teams is None:
                await interaction.followup.send(
                    "❌ 먼저 팀을 생성해주세요.",
                    ephemeral=True
                )
                return

            if self.room.current_teams is not self.teams_reference:
                await interaction.followup.send(
                    "❌ 팀이 다시 생성되어 이 경기 시작 버튼은 "
                    "만료되었습니다.\n"
                    "가장 최근 팀 메시지의 버튼을 사용해주세요.",
                    ephemeral=True
                )
                return

            if self.room.match_in_progress:
                await interaction.followup.send(
                    "❌ 이미 경기 중입니다.",
                    ephemeral=True
                )
                return

            if MATCH_MODE != "single" and self.room.series_game > 0:
                previous_match = get_last_match(self.room.room_id)
                if previous_match is not None:
                    progress = get_match_champion_progress(
                        previous_match["id"]
                    )
                    if (
                        progress["total_count"] > 0
                        and progress["completed_count"]
                            < progress["total_count"]
                    ):
                        missing = (
                            progress["total_count"]
                            - progress["completed_count"]
                        )
                        await interaction.followup.send(
                            f"⏳ 이전 세트 경기번호 **{previous_match['id']}**의 "
                            f"챔피언 입력이 **{missing}명** 남았습니다.\n"
                            "각자 결과 메시지에서 `내 챔피언 입력`을 눌러주세요. "
                            "남은 칸은 참가자가 `미입력자만 입력` 버튼으로 채울 수 있습니다.",
                            ephemeral=True
                        )
                        return

            # 다음 세트 결과를 되돌릴 때 이 시점의 팀/참가자/시리즈 점수를 복원합니다.
            self.players_snapshot = copy.deepcopy(
                getattr(self.room, "players", {})
            )
            self.teams_snapshot = copy.deepcopy(self.room.current_teams)
            self.series_score_snapshot = dict(
                getattr(self.room, "series_score", {"red": 0, "blue": 0})
            )
            self.series_game_snapshot = getattr(self.room, "series_game", 0)
            self.tournament_id_snapshot = getattr(self.room, "tournament_id", None)
            self.tournament_fixture_no_snapshot = getattr(
                self.room, "tournament_fixture_no", None
            )

            self.room.match_in_progress = True
            self.room.ended_series_snapshot = None

            self.join_cog.save_rooms_state()

            self.start_button.disabled = True
            self.red_button.disabled = False
            self.blue_button.disabled = False
            self.end_series_button.disabled = True

        await interaction.message.edit(view=self)

        await interaction.followup.send(
            f"🎮 **{self.room.room_name} 경기가 "
            "시작되었습니다!**\n"
            "게임이 끝나면 이 팀 안내 메시지에서 "
            "🔴 레드팀 승리 또는 🔵 블루팀 승리 버튼을 한 번 눌러주세요."
        )
        await refresh_match_controls_at_bottom(
            self.join_cog,
            self.room,
            self.team_message,
            self,
            stage="in_progress"
        )

    async def _report_winner(self, interaction, winner, response_deferred=False):
        if self._result_lock.locked():
            await interaction.followup.send(
                "⏳ 결과를 이미 처리하고 있습니다. 잠시만 기다려주세요.",
                ephemeral=True
            )
            return

        if not response_deferred:
            await interaction.response.defer(ephemeral=True, thinking=True)
        async with self._result_lock:
            if not self.room.match_in_progress:
                await interaction.followup.send(
                    "❌ 현재 진행 중인 경기가 없습니다.",
                    ephemeral=True
                )
                return

            match_cog = self.join_cog.bot.get_cog("Match")
            if match_cog is None:
                await interaction.followup.send(
                    "❌ 경기 결과 기능을 불러오지 못했습니다. 관리자에게 알려주세요.",
                    ephemeral=True
                )
                return

            self.start_button.disabled = True
            self.red_button.disabled = True
            self.blue_button.disabled = True
            team_message = self.team_message or interaction.message
            try:
                await team_message.edit(view=self)
            except discord.HTTPException:
                pass

            try:
                await match_cog.process_match_result(
                    interaction,
                    winner,
                    self.room,
                    match_control_view=self
                )
            except Exception:
                logger.exception(
                    "버튼 경기 결과 처리 실패 | 방=%s",
                    self.room.room_id
                )
                # 실패하면 결과 버튼을 다시 열어 입력을 복구합니다.
                self.start_button.disabled = True
                self.red_button.disabled = False
                self.blue_button.disabled = False
                self.end_series_button.disabled = True
                try:
                    await team_message.edit(view=self)
                except discord.HTTPException:
                    pass
                await interaction.followup.send(
                    "❌ 결과 저장 중 오류가 발생했습니다.\n"
                    "버튼을 다시 누르지 말고 관리자에게 알려주세요.",
                    ephemeral=True
                )
                return

            if self.room.match_in_progress:
                # Validation can reject the report without closing the game.
                # Keep the result buttons available in that case.
                self.start_button.disabled = True
                self.red_button.disabled = False
                self.blue_button.disabled = False
                try:
                    await team_message.edit(view=self)
                except discord.HTTPException:
                    pass
                return

            if self.room.current_teams is None:
                # 단판 종료 또는 BO5 종료
                self.start_button.disabled = True
                self.red_button.disabled = True
                self.blue_button.disabled = True
                self.end_series_button.disabled = True
                self.stop()
                try:
                    await team_message.edit(view=self)
                except discord.HTTPException:
                    pass
            else:
                # BO5 다음 세트 조작창을 채널 맨 아래에 새로 올립니다.
                self.teams_reference = self.room.current_teams
                self.start_button.disabled = False
                self.red_button.disabled = True
                self.blue_button.disabled = True
                control_message, control_view = await refresh_match_controls_at_bottom(
                    self.join_cog,
                    self.room,
                    team_message,
                    self
                )

                if self.champion_record_view is not None:
                    self.champion_record_view.join_cog = self.join_cog
                    self.champion_record_view.control_message = control_message
                    self.champion_record_view.control_message_view = control_view

            if self.champion_record_view is not None:
                await self.champion_record_view.move_to_bottom()

            await interaction.followup.send(
                "✅ 승리팀 결과를 등록했습니다.\n"
                "챔피언 입력 안내는 아래 경기 결과 메시지를 확인해주세요.",
                ephemeral=True
            )

    @discord.ui.button(
        label="🔴 레드팀 승리",
        style=discord.ButtonStyle.danger,
        custom_id="match_result_red_button"
    )
    async def red_button(self, interaction, button):
        self.team_message = interaction.message
        await interaction.response.send_message(
            "🔴 **레드팀 승리로 등록할까요?**",
            view=WinnerConfirmView(self, "red", interaction.user.id),
            ephemeral=True
        )

    @discord.ui.button(
        label="🔵 블루팀 승리",
        style=discord.ButtonStyle.primary,
        custom_id="match_result_blue_button"
    )
    async def blue_button(self, interaction, button):
        self.team_message = interaction.message
        await interaction.response.send_message(
            "🔵 **블루팀 승리로 등록할까요?**",
            view=WinnerConfirmView(self, "blue", interaction.user.id),
            ephemeral=True
        )

    @discord.ui.button(
        label="🛑 내전 종료",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def end_series_button(self, interaction, button):
        if (
            self.room.match_transaction_active
            or self.room.pending_match_token is not None
        ):
            await interaction.response.send_message(
                "⏳ 직전 경기 결과를 아직 저장하고 있습니다. "
                "저장이 끝난 뒤 내전을 종료해주세요.",
                ephemeral=True
            )
            return
        if self.room.series_game <= 0:
            await interaction.response.send_message(
                "❌ 최소 한 세트 결과를 등록한 뒤 내전을 종료할 수 있습니다.",
                ephemeral=True
            )
            return
        if self.room.match_in_progress:
            await interaction.response.send_message(
                "❌ 경기 중에는 내전을 종료할 수 없습니다. 먼저 세트 결과를 등록해주세요.",
                ephemeral=True
            )
            return
        score = self.room.series_score
        await interaction.response.send_message(
            f"현재 점수는 🔴 레드 **{score['red']} : {score['blue']}** 블루입니다.\n"
            "이 세트까지 저장된 결과를 남기고 내전을 종료할까요?",
            view=EndSeriesConfirmView(
                self.join_cog.bot,
                self.room,
                interaction.user.id,
                control_view=self,
                source_message=interaction.message
            ),
            ephemeral=True
        )


class WinnerConfirmView(discord.ui.View):
    """승리팀 오입력을 줄이기 위한 본인 확인 단계."""

    def __init__(self, match_control_view, winner, actor_id):
        super().__init__(timeout=60)
        self.match_control_view = match_control_view
        self.winner = winner
        self.actor_id = int(actor_id)

    async def interaction_check(self, interaction):
        if int(interaction.user.id) != self.actor_id:
            await interaction.response.send_message(
                "❌ 승리팀을 선택한 사람만 확인할 수 있습니다.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="결과 등록", style=discord.ButtonStyle.success)
    async def confirm(self, interaction, button):
        self.stop()
        await interaction.response.edit_message(
            content="결과를 저장하고 있습니다…",
            view=None
        )
        await self.match_control_view._report_winner(
            interaction,
            self.winner,
            response_deferred=True
        )

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        self.stop()
        await interaction.response.edit_message(
            content="승리팀 선택을 취소했습니다. 원래 경기 메시지에서 다시 선택할 수 있습니다.",
            view=None
        )


def _season_profiles_for_players(join_cog, players):
    """드래프트 참가자의 현재 시즌 레이팅을 팀 편성용으로 준비합니다."""
    join_cog.reload_profiles()
    profiles = {
        user_id: dict(profile)
        for user_id, profile in join_cog.profiles.items()
    }
    active_season = get_active_season()
    if active_season is not None:
        for user_id in players:
            profile = profiles.get(user_id)
            if profile is None:
                continue
            season_stats = get_season_player_stats(
                active_season["id"],
                user_id
            )
            season_rating = int(
                (season_stats or {}).get("rating") or 1000
            )
            profile["rating"] = season_rating
            profile["hidden_mmr"] = season_rating
            profile["position_ratings"] = {}
            profile["recent_position_form"] = {}
    return profiles


class TeamModeView(discord.ui.View):
    """관리자가 자동 편성과 캡틴 드래프트 중 하나를 선택합니다."""

    def __init__(self, recruit_view):
        super().__init__(timeout=120)
        self.recruit_view = recruit_view
        self.join_cog = recruit_view.join_cog
        self.room = recruit_view.room
        self.balanced_button.disabled = self.room.player_limit != MAX_PLAYERS
        self.captain_button.disabled = self.room.player_limit != MAX_PLAYERS

    async def interaction_check(self, interaction):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return False
        if not self.join_cog.activate_room(self.room):
            await interaction.response.send_message(
                "❌ 연결된 내전 방을 찾지 못했습니다.",
                ephemeral=True
            )
            return False
        if self.join_cog.current_recruit_view is not self.recruit_view:
            await interaction.response.send_message(
                "❌ 이 모집창은 이미 만료되었습니다.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(
        label="자동 밸런스 편성",
        emoji="⚖️",
        style=discord.ButtonStyle.primary
    )
    async def balanced_button(self, interaction, button):
        if self.room.player_limit != MAX_PLAYERS:
            await interaction.response.send_message(
                "❌ 자동 편성은 10인 내전에서만 사용할 수 있습니다. 20인은 4팀 경매로 진행해주세요.",
                ephemeral=True
            )
            return
        if self.recruit_view.team_generating:
            await interaction.response.send_message(
                "⏳ 이미 팀 편성 또는 드래프트가 진행 중입니다.",
                ephemeral=True
            )
            return
        self.recruit_view.team_generating = True
        try:
            await interaction.response.edit_message(
                content="⚖️ 자동 밸런스 팀을 편성하고 있습니다…",
                view=None
            )
            await self.recruit_view.generate_teams(
                interaction,
                allow_team_generating=True
            )
        finally:
            self.recruit_view.team_generating = False

    @discord.ui.button(
        label="캡틴 드래프트",
        emoji="🎖️",
        style=discord.ButtonStyle.success
    )
    async def captain_button(self, interaction, button):
        if self.recruit_view.team_generating:
            await interaction.response.send_message(
                "⏳ 이미 팀 편성 또는 드래프트가 진행 중입니다.",
                ephemeral=True
            )
            return
        player_ids = list(self.room.players.keys())
        if self.room.player_limit != MAX_PLAYERS or len(player_ids) != MAX_PLAYERS:
            await interaction.response.send_message(
                f"❌ 참가자가 {MAX_PLAYERS}명 모여야 드래프트를 시작할 수 있습니다.",
                ephemeral=True
            )
            return

        # Reserve this room's team-generation flow before yielding to the DB
        # read, so a second mode cannot open a competing setup at the same time.
        self.recruit_view.team_generating = True
        # 프로필/시즌 정보를 동기 DB에서 읽으므로 먼저 버튼 상호작용을
        # 확인합니다. 이 조회가 Discord의 3초 응답 제한을 넘으면 버튼이
        # 실패한 것처럼 보이고 Unknown interaction 오류가 발생합니다.
        try:
            await interaction.response.defer()
        except Exception:
            self.recruit_view.team_generating = False
            raise
        try:
            profiles = _season_profiles_for_players(
                self.join_cog,
                player_ids
            )
            errors = validate_team_profiles(player_ids, profiles)
        except Exception:
            logger.exception(
                "캡틴 드래프트 참가자 프로필 조회 실패 | 방=%s",
                self.room.room_id
            )
            self.recruit_view.team_generating = False
            await interaction.followup.send(
                "❌ 참가자 프로필을 확인하지 못했습니다. 잠시 후 다시 눌러주세요.",
                ephemeral=True
            )
            return
        if errors:
            self.recruit_view.team_generating = False
            await interaction.followup.send(
                "❌ 참가자 프로필의 포지션 정보를 확인해주세요.\n"
                + "\n".join(f"• {error}" for error in errors),
                ephemeral=True
            )
            return
        setup_view = CaptainSetupView(
            self.recruit_view,
            player_ids,
            profiles
        )
        self.recruit_view._captain_setup_view = setup_view
        try:
            setup_view.message = await interaction.edit_original_response(
                content=(
                    "🎖️ 드래프트를 이끌 캡틴 2명을 선택한 뒤 시작을 눌러주세요.\n"
                    "캡틴도 각자 한 팀에 포함됩니다."
                ),
                view=setup_view
            )
        except discord.HTTPException:
            self.recruit_view._captain_setup_view = None
            self.recruit_view.team_generating = False
            logger.exception(
                "캡틴 드래프트 선택창 전송 실패 | 방=%s",
                self.room.room_id
            )
            await interaction.followup.send(
                "❌ 캡틴 선택창을 표시하지 못했습니다. 모집 메시지를 새로고침한 뒤 다시 눌러주세요.",
                ephemeral=True
            )

    @discord.ui.button(
        label="경매 내전",
        emoji="🔨",
        style=discord.ButtonStyle.secondary
    )
    async def auction_button(self, interaction, button):
        if self.recruit_view.team_generating:
            await interaction.response.send_message(
                "⏳ 이미 팀 편성 또는 드래프트가 진행 중입니다.",
                ephemeral=True
            )
            return
        player_ids = list(self.room.players.keys())
        expected_count = self.room.player_limit
        if len(player_ids) != expected_count:
            await interaction.response.send_message(
                f"❌ 참가자가 {expected_count}명 모여야 경매를 시작할 수 있습니다.",
                ephemeral=True
            )
            return
        # Profile lookups hit SQLite. Acknowledge the component before the
        # synchronous reads so Discord's 3-second interaction deadline cannot
        # expire while preparing either the 10-player or 20-player auction.
        self.recruit_view.team_generating = True
        await interaction.response.defer()
        try:
            profiles = _season_profiles_for_players(
                self.join_cog,
                player_ids
            )
        except Exception:
            self.recruit_view.team_generating = False
            logger.exception(
                "경매 참가자 프로필 조회 실패 | 방=%s",
                self.room.room_id
            )
            await interaction.followup.send(
                "❌ 참가자 프로필을 확인하지 못했습니다. 잠시 후 다시 눌러주세요.",
                ephemeral=True
            )
            return
        errors = validate_team_profiles(player_ids, profiles)
        if errors:
            self.recruit_view.team_generating = False
            await interaction.followup.send(
                "❌ 참가자 프로필의 포지션 정보를 확인해주세요.\n"
                + "\n".join(f"• {error}" for error in errors),
                ephemeral=True
            )
            return

        setup_view = AuctionSetupView(
            self.recruit_view,
            player_ids,
            profiles
        )
        self.recruit_view._auction_setup_view = setup_view
        try:
            captain_count = 4 if expected_count == MAX_AUCTION_PLAYERS else 2
            setup_view.message = await interaction.edit_original_response(
                content=(
                    f"🔨 {expected_count}인 경매 준비: 캡틴 {captain_count}명을 선택하고 시작을 눌러주세요.\n"
                    f"팀별 예산은 {AUCTION_TEAM_BUDGET}포인트이며, "
                    f"선수 시작가는 {AUCTION_MIN_BID}포인트입니다."
                ),
                view=setup_view
            )
        except discord.HTTPException:
            self.recruit_view._auction_setup_view = None
            self.recruit_view.team_generating = False
            logger.exception(
                "경매 캡틴 선택창 갱신 실패 | 방=%s",
                self.room.room_id
            )
            await interaction.followup.send(
                "❌ 경매 준비창을 표시하지 못했습니다. 모집 메시지를 새로고침한 뒤 다시 눌러주세요.",
                ephemeral=True
            )

class CaptainSelection(discord.ui.Select):
    def __init__(self, setup_view):
        self.setup_view = setup_view
        options = []
        for user_id in setup_view.player_ids:
            player = setup_view.room.players.get(user_id, {})
            nickname = str(player.get("nickname") or user_id)
            options.append(discord.SelectOption(
                label=nickname[:100],
                value=user_id
            ))
        super().__init__(
            placeholder=f"캡틴 {setup_view.captain_count}명을 선택하세요",
            min_values=setup_view.captain_count,
            max_values=setup_view.captain_count,
            options=options
        )

    async def callback(self, interaction):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return
        self.setup_view.selected_captains = list(self.values)
        await interaction.response.send_message(
            f"✅ 캡틴 {len(self.values)}명이 선택되었습니다. 아래 시작 버튼을 눌러주세요.",
            ephemeral=True
        )


class AuctionSetupView(discord.ui.View):
    """경매 시작 전에 관리자가 경매 규모에 맞는 캡틴을 지정합니다."""

    def __init__(self, recruit_view, player_ids, profiles):
        super().__init__(timeout=180)
        self.recruit_view = recruit_view
        self.join_cog = recruit_view.join_cog
        self.room = recruit_view.room
        self.player_ids = list(player_ids)
        self.profiles = profiles
        self.captain_count = 4 if self.room.player_limit == MAX_AUCTION_PLAYERS else 2
        self.selected_captains = []
        self.message = None
        self.started = False
        self.lock_acquired = False
        self.previous_recruit_closed = recruit_view.recruit_closed
        self.add_item(CaptainSelection(self))

    def _release_room_lock(self):
        if self.lock_acquired:
            if self.room.team_generation_lock.locked():
                self.room.team_generation_lock.release()
            self.lock_acquired = False

    async def _rollback_start(self):
        self._release_room_lock()
        self.recruit_view.team_generating = False
        self.recruit_view._auction_setup_view = None
        self.recruit_view.recruit_closed = self.previous_recruit_closed
        await self.recruit_view.restore_recruitment_controls()

    @discord.ui.button(
        label="경매 시작",
        emoji="🔨",
        style=discord.ButtonStyle.success,
        row=1
    )
    async def start_button(self, interaction, button):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return
        if not self.join_cog.activate_room(self.room):
            await interaction.response.send_message(
                "❌ 연결된 내전 방을 찾지 못했습니다.",
                ephemeral=True
            )
            return
        if (
            self.recruit_view._auction_setup_view is not self
            or self.started
        ):
            await interaction.response.send_message(
                "⏳ 경매가 이미 시작됐거나 이 설정창이 만료되었습니다.",
                ephemeral=True
            )
            return
        if list(self.room.players.keys()) != self.player_ids:
            await interaction.response.send_message(
                "❌ 참가 명단이 바뀌었습니다. 팀 생성 버튼부터 다시 눌러주세요.",
                ephemeral=True
            )
            await self._rollback_start()
            return
        if len(self.selected_captains) != self.captain_count:
            await interaction.response.send_message(
                f"❌ 먼저 캡틴 {self.captain_count}명을 선택해주세요.",
                ephemeral=True
            )
            return
        if (
            self.room.current_teams is not None
            or self.room.match_in_progress
            or self.room.mvp_vote_in_progress
            or self.room.match_transaction_active
        ):
            await interaction.response.send_message(
                "❌ 이미 팀이 생성됐거나 경기가 진행 중입니다.",
                ephemeral=True
            )
            await self._rollback_start()
            return
        if self.room.team_generation_lock.locked():
            await interaction.response.send_message(
                "⏳ 이 내전방에서 다른 팀 생성 작업이 진행 중입니다.",
                ephemeral=True
            )
            return

        self.started = True
        self.recruit_view._auction_setup_view = None
        await interaction.response.defer(ephemeral=True)
        try:
            await asyncio.wait_for(
                self.room.team_generation_lock.acquire(),
                timeout=0.5
            )
        except asyncio.TimeoutError:
            await self._rollback_start()
            await interaction.followup.send(
                "⏳ 이 내전방에서 다른 팀 편성 작업이 진행 중입니다. 끝난 뒤 경매를 다시 준비해주세요.",
                ephemeral=True
            )
            return
        self.lock_acquired = True

        if list(self.room.players.keys()) != self.player_ids:
            await self._rollback_start()
            await interaction.followup.send(
                "❌ 경매 시작 중 참가 명단이 바뀌어 취소했습니다.",
                ephemeral=True
            )
            return

        self.recruit_view._draft_was_closed = self.recruit_view.recruit_closed
        self.recruit_view.recruit_closed = True
        for item in self.recruit_view.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        if self.recruit_view.message is not None:
            try:
                await self.recruit_view.message.edit(
                    embed=self.recruit_view.create_embed(),
                    view=self.recruit_view
                )
            except discord.HTTPException:
                logger.exception("경매 시작 시 모집 버튼 잠금 실패")

        auction_view = AuctionView(
            self.recruit_view,
            self.player_ids,
            self.profiles,
            captains=self.selected_captains
        )
        try:
            message, _ = await self.join_cog.send_output_message(
                room=self.room,
                fallback_channel=interaction.channel,
                embed=auction_view.create_embed(),
                view=auction_view
            )
        except discord.HTTPException:
            logger.exception("경매 진행 메시지 전송 실패 | 방=%s", self.room.room_id)
            message = None
        if message is None:
            await self._rollback_start()
            await interaction.followup.send(
                "❌ 경매 메시지를 보낼 수 없습니다. 채널 권한을 확인해주세요.",
                ephemeral=True
            )
            return

        auction_view.message = message
        auction_view.lock_acquired = True
        self.lock_acquired = False
        auction_view.start_lot_timer()
        if interaction.message is not None:
            try:
                await interaction.message.edit(
                    content="✅ 경매를 시작했습니다. 모집 채널의 경매 메시지를 확인해주세요.",
                    view=None
                )
            except discord.HTTPException:
                pass
        await interaction.followup.send(
            f"✅ 경매를 시작했습니다.\n진행 메시지: {message.jump_url}",
            ephemeral=True
        )

    @discord.ui.button(
        label="취소",
        emoji="✖️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def cancel_button(self, interaction, button):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return
        if self.started:
            await interaction.response.send_message(
                "⏳ 경매가 이미 시작되었습니다.",
                ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        self.stop()
        await self._rollback_start()
        await interaction.followup.send(
            "경매 설정을 취소했습니다.",
            ephemeral=True
        )

    async def on_timeout(self):
        if not self.started and self.recruit_view._auction_setup_view is self:
            self.stop()
            await self._rollback_start()


class PlayerLimitView(discord.ui.View):
    """관리자가 모집 정원을 10명 또는 20명으로 선택합니다."""

    def __init__(self, recruit_view):
        super().__init__(timeout=60)
        self.recruit_view = recruit_view
        self.room = recruit_view.room
        self.join_cog = recruit_view.join_cog

    async def interaction_check(self, interaction):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return False
        if not self.join_cog.activate_room(self.room):
            await interaction.response.send_message(
                "❌ 연결된 내전 방을 찾지 못했습니다.",
                ephemeral=True
            )
            return False
        if self.join_cog.current_recruit_view is not self.recruit_view:
            await interaction.response.send_message(
                "❌ 이 모집창은 이미 만료되었습니다.",
                ephemeral=True
            )
            return False
        return True

    async def _select_limit(self, interaction, limit):
        room = self.room
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with room.operation_lock:
            if (
                self.recruit_view.recruit_closed
                or room.current_teams is not None
                or room.match_in_progress
                or room.mvp_vote_in_progress
                or room.match_transaction_active
                or self.recruit_view.team_generating
            ):
                await interaction.edit_original_response(
                    content="❌ 모집 중이고 팀/경기가 없는 상태에서만 정원을 바꿀 수 있습니다."
                )
                return
            if len(room.players) > limit:
                await interaction.edit_original_response(
                    content=(
                        f"❌ 현재 참가자가 {len(room.players)}명이라 "
                        f"{limit}인 정원으로 바꿀 수 없습니다. 참가자를 줄인 뒤 다시 시도해주세요."
                    )
                )
                return
            if limit not in (MAX_PLAYERS, MAX_AUCTION_PLAYERS):
                await interaction.edit_original_response(
                    content="❌ 지원하지 않는 모집 정원입니다."
                )
                return

            room.player_limit = limit
            self.join_cog.save_rooms_state()
            await interaction.edit_original_response(
                content=(
                    f"✅ 모집 정원을 **{limit}명**으로 설정했습니다.\n"
                    + (
                        "20명은 캡틴 4명, 팀별 5명씩 경매로 4팀을 편성합니다."
                        if limit == MAX_AUCTION_PLAYERS
                        else "10명은 기존 5대5 내전과 2팀 경매를 사용할 수 있습니다."
                    )
                ),
                view=None
            )
            await self.recruit_view.restore_recruitment_controls()

    @discord.ui.button(label="10명 · 일반 내전", style=discord.ButtonStyle.secondary)
    async def ten_players(self, interaction, button):
        await self._select_limit(interaction, MAX_PLAYERS)

    @discord.ui.button(label="20명 · 4팀 경매", style=discord.ButtonStyle.primary)
    async def twenty_players(self, interaction, button):
        await self._select_limit(interaction, MAX_AUCTION_PLAYERS)


class AuctionBidButton(discord.ui.Button):
    def __init__(self, auction_view, side, lot_index):
        self.auction_view = auction_view
        self.side = side
        self.lot_index = lot_index
        bid = (
            AUCTION_MIN_BID
            if auction_view.current_bid == 0
            else auction_view.current_bid + AUCTION_BID_STEP
        )
        team_name = dict(auction_view.side_labels).get(side, side).split()[-1]
        label = f"{team_name} {bid}점 입찰"
        super().__init__(label=label, style=discord.ButtonStyle.primary)

    async def callback(self, interaction):
        await self.auction_view.place_bid(
            interaction,
            self.side,
            expected_lot=self.lot_index
        )


class AuctionRetryButton(discord.ui.Button):
    def __init__(self, auction_view):
        self.auction_view = auction_view
        super().__init__(
            label="후순위 재입찰 시작",
            emoji="🔁",
            style=discord.ButtonStyle.success
        )

    async def callback(self, interaction):
        await self.auction_view.retry_unsold_players(interaction)


class AuctionView(discord.ui.View):
    """2인 또는 4인 캡틴 경매로 2팀·4팀 로스터를 편성합니다."""

    def __init__(
        self,
        recruit_view,
        player_ids,
        profiles,
        captains
    ):
        super().__init__(timeout=86400)
        self.recruit_view = recruit_view
        self.join_cog = recruit_view.join_cog
        self.room = recruit_view.room
        self.player_ids = list(player_ids)
        self.profiles = profiles
        self.side_labels = AUCTION_SIDES[:len(captains)]
        self.captains = {
            side: str(captain_id)
            for (side, _), captain_id in zip(self.side_labels, captains)
        }
        self.teams = {
            side: [str(captain_id)]
            for side, captain_id in self.captains.items()
        }
        self.budgets = {side: AUCTION_TEAM_BUDGET for side in self.teams}
        self.spent = {side: 0 for side in self.teams}
        self.purchase_prices = {str(captain_id): 0 for captain_id in captains}
        self.tournament_id = None
        captain_ids = set(self.captains.values())
        self.lots = [
            user_id for user_id in self.player_ids
            if user_id not in captain_ids
        ]
        random.shuffle(self.lots)
        self.unsold_players = []
        self.auction_round = 1
        self.lot_index = 0
        self._lot_token = 0
        self.current_bid = 0
        self.current_bidder = None
        self._auction_lock = asyncio.Lock()
        self._timer_task = None
        self._finished = False
        self.lock_acquired = False
        self.message = None
        self._refresh_controls()

    def _refresh_controls(self):
        self.clear_items()
        if self.lot_index < len(self.lots) and not self._finished:
            for side, _ in self.side_labels:
                self.add_item(AuctionBidButton(self, side, self._lot_token))
            cancel = discord.ui.Button(
                label="경매 취소",
                emoji="⏹️",
                style=discord.ButtonStyle.danger,
                row=1
            )
            cancel.callback = self.cancel_button
            self.add_item(cancel)
        elif self.unsold_players and not self._finished:
            self.add_item(AuctionRetryButton(self))
            cancel = discord.ui.Button(
                label="경매 취소",
                emoji="⏹️",
                style=discord.ButtonStyle.danger,
                row=1
            )
            cancel.callback = self.cancel_button
            self.add_item(cancel)

    def _player_label(self, user_id):
        profile = self.profiles.get(user_id, {})
        rating = profile.get("rating", 1000)
        main = profile.get("main_position", "-")
        sub = profile.get("sub_position", "-")
        return f"<@{user_id}> · ⭐{rating} · {main}/{sub}"

    def create_embed(self):
        if self.lot_index < len(self.lots):
            current_player = self.lots[self.lot_index]
            next_bid = (
                AUCTION_MIN_BID
                if self.current_bid == 0
                else self.current_bid + AUCTION_BID_STEP
            )
            if self.current_bidder is None:
                bidding_text = f"입찰 대기 · 시작가 **{AUCTION_MIN_BID}점**"
            else:
                bidding_text = (
                    f"현재 최고 입찰: **{self.current_bid}점** · "
                    f"{dict(self.side_labels).get(self.current_bidder, self.current_bidder)}\n"
                    f"다음 입찰: **{next_bid}점**"
                )
            auction_description = (
                f"{'본 경매' if self.auction_round == 1 else f'후순위 입찰 {self.auction_round - 1}회차'} · "
                f"대상 **{self.lot_index + 1}/{len(self.lots)}**\n"
                f"{self._player_label(current_player)}\n\n"
                f"{bidding_text}\n"
                f"입찰 시간은 {AUCTION_LOT_SECONDS}초이며, 입찰할 때마다 초기화됩니다."
            )
        else:
            if self.unsold_players:
                unsold_mentions = "\n".join(
                    f"• {self._player_label(user_id)}"
                    for user_id in self.unsold_players
                )
                auction_description = (
                    "후순위 입찰에서도 유찰된 선수입니다.\n"
                    "아래 버튼으로 재입찰을 시작하거나 경매를 취소해주세요.\n\n"
                    f"{unsold_mentions}"
                )
            else:
                auction_description = "경매 결과를 정리하고 있습니다…"

        embed = discord.Embed(
            title=f"🔨 {self.room.room_name} · 선수 경매",
            description=(
                f"{auction_description}\n\n"
                f"팀별 예산 **{AUCTION_TEAM_BUDGET}포인트** · "
                f"입찰 단위 **{AUCTION_BID_STEP}포인트**\n"
                "경매 포인트는 시즌 레이팅과 별도로 사용됩니다.\n"
                f"캡틴은 팀에 자동 포함되며, 예산은 나머지 4명 영입에 사용합니다. "
                f"현재 {len(self.teams)}팀 · {len(self.player_ids)}명 경매입니다."
            )
        )
        for side, label in self.side_labels:
            roster = self.teams[side]
            roster_lines = [
                f"<@{user_id}>" + (
                    " · 캡틴" if user_id == self.captains[side]
                    else f" · {self.purchase_prices.get(user_id, 0)}점"
                )
                for user_id in roster
            ]
            embed.add_field(
                name=(
                    f"{label} · {len(roster)}/5명 · "
                    f"잔액 {self.budgets[side]}점"
                ),
                value="\n".join(roster_lines),
                inline=True
            )
        embed.set_footer(
            text=(
                "선수 순서는 무작위입니다. 캡틴만 입찰할 수 있습니다. "
                "유찰 선수는 후순위 입찰로 넘어가며 자동 배정되지 않습니다."
            )
        )
        return embed

    def start_lot_timer(self):
        old_task = self._timer_task
        current_task = asyncio.current_task()
        if old_task is not None and old_task is not current_task:
            old_task.cancel()
        if self.lot_index < len(self.lots) and not self._finished:
            token = self._lot_token
            self._timer_task = asyncio.create_task(
                self._close_lot_after_timeout(token)
            )

    async def _close_lot_after_timeout(self, expected_lot):
        try:
            await asyncio.sleep(AUCTION_LOT_SECONDS)
            async with self._auction_lock:
                if self._finished or expected_lot != self._lot_token:
                    return
                await self._close_current_lot()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("경매 자동 마감 처리 중 오류 | 방=%s", self.room.room_id)
            if not self._finished:
                await self.abort("경매 처리 중 오류가 발생해 경매를 취소했습니다.")

    async def place_bid(self, interaction, side, expected_lot):
        await interaction.response.defer()
        async with self._auction_lock:
            if self._finished or self.is_finished():
                await interaction.followup.send(
                    "❌ 이 경매는 이미 종료되었습니다.",
                    ephemeral=True
                )
                return
            if expected_lot != self._lot_token:
                await interaction.followup.send(
                    "🔄 경매 대상이 바뀌었습니다. 최신 경매 메시지에서 입찰해주세요.",
                    ephemeral=True
                )
                return
            captain_id = self.captains[side]
            if str(interaction.user.id) != captain_id and not is_admin(interaction):
                team_label = dict(self.side_labels).get(side, side)
                await interaction.followup.send(
                    f"❌ {team_label} 캡틴만 입찰할 수 있습니다.",
                    ephemeral=True
                )
                return
            if self.current_bidder == side:
                await interaction.followup.send(
                    "이미 이 팀이 최고 입찰 중입니다.",
                    ephemeral=True
                )
                return
            if (
                list(self.room.players.keys()) != self.player_ids
                or self.room.current_teams is not None
                or self.room.match_in_progress
            ):
                await interaction.followup.send(
                    "❌ 참가자나 경기 상태가 바뀌어 경매를 취소합니다.",
                    ephemeral=True
                )
                await self.abort("참가자나 경기 상태가 변경되어 경매가 취소되었습니다.")
                return
            if len(self.teams[side]) >= 5:
                await interaction.followup.send(
                    "❌ 이 팀은 이미 정원이 찼습니다.",
                    ephemeral=True
                )
                return

            bid = (
                AUCTION_MIN_BID
                if self.current_bid == 0
                else self.current_bid + AUCTION_BID_STEP
            )
            slots_after_purchase = 5 - (len(self.teams[side]) + 1)
            reserve = slots_after_purchase * AUCTION_MIN_BID
            max_allowed_bid = self.budgets[side] - reserve
            if bid > max_allowed_bid:
                await interaction.followup.send(
                    f"❌ 예산 부족입니다. 남은 팀원에게 최소 {reserve}점을 남겨야 해서 "
                    f"최대 {max_allowed_bid}점까지 입찰할 수 있습니다.",
                    ephemeral=True
                )
                return

            self.current_bid = bid
            self.current_bidder = side
            self._refresh_controls()
            self.start_lot_timer()
            await self._publish_current_state()

    async def _close_current_lot(self):
        if self._finished or self.lot_index >= len(self.lots):
            return
        if (
            list(self.room.players.keys()) != self.player_ids
            or self.room.current_teams is not None
            or self.room.match_in_progress
            or self.room.mvp_vote_in_progress
        ):
            await self.abort("참가자나 경기 상태가 바뀌어 경매를 취소했습니다.")
            return

        player_id = self.lots[self.lot_index]
        if self.current_bidder is not None:
            winner = self.current_bidder
            price = self.current_bid
            award_note = f"낙찰: {dict(self.side_labels).get(winner, winner)} · {price}점"
            self.teams[winner].append(player_id)
            self.budgets[winner] -= price
            self.spent[winner] += price
            self.purchase_prices[player_id] = price
        else:
            self.unsold_players.append(player_id)
            award_note = f"유찰 · <@{player_id}> 후순위 입찰 예정"

        self.lot_index += 1
        self._lot_token += 1
        self.current_bid = 0
        self.current_bidder = None

        if self.lot_index >= len(self.lots):
            if self.unsold_players and self.auction_round == 1:
                self.lots = list(self.unsold_players)
                self.unsold_players.clear()
                self.auction_round = 2
                self.lot_index = 0
                self.current_bid = 0
                self.current_bidder = None
                self._refresh_controls()
                await self._publish_current_state(
                    content=(
                        "🔁 본 경매가 끝났습니다. 유찰 선수 "
                        f"{len(self.lots)}명을 후순위로 다시 올립니다."
                    )
                )
                self.start_lot_timer()
                return
            if self.unsold_players:
                self._refresh_controls()
                await self._publish_current_state(
                    content=(
                        "⏸️ 후순위 입찰이 끝났지만 유찰 선수가 남아 있습니다. "
                        "관리자가 재입찰을 시작해주세요."
                    )
                )
                return
            await self._finish_auction()
            return

        self._refresh_controls()
        await self._publish_current_state(
            content=f"✅ {award_note} · <@{player_id}>"
        )
        self.start_lot_timer()

    async def retry_unsold_players(self, interaction):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return
        await interaction.response.defer(ephemeral=True)
        async with self._auction_lock:
            if self._finished:
                await interaction.followup.send(
                    "이미 종료된 경매입니다.",
                    ephemeral=True
                )
                return
            if self.lot_index < len(self.lots) or not self.unsold_players:
                await interaction.followup.send(
                    "현재 후순위 재입찰을 시작할 수 없습니다.",
                    ephemeral=True
                )
                return
            self.lots = list(self.unsold_players)
            self.unsold_players.clear()
            self.auction_round += 1
            self.lot_index = 0
            self._lot_token += 1
            self.current_bid = 0
            self.current_bidder = None
            self._refresh_controls()
            await self._publish_current_state(
                content=(
                    f"🔁 후순위 입찰 {self.auction_round - 1}회차를 시작합니다. "
                    f"유찰 선수 {len(self.lots)}명입니다."
                )
            )
            self.start_lot_timer()
        await interaction.followup.send(
            "✅ 유찰 선수 후순위 입찰을 다시 시작했습니다.",
            ephemeral=True
        )

    async def _publish_current_state(self, content=None):
        if self.message is None or self._finished:
            return
        try:
            await self.message.edit(
                content=content,
                embed=self.create_embed(),
                view=self
            )
        except discord.HTTPException:
            logger.exception("경매 메시지 갱신 실패 | 방=%s", self.room.room_id)
            try:
                replacement, _ = await self.join_cog.send_output_message(
                    room=self.room,
                    fallback_channel=getattr(self.message, "channel", None),
                    content=content,
                    embed=self.create_embed(),
                    view=self
                )
            except Exception:
                logger.exception("경매 대체 메시지 전송 실패 | 방=%s", self.room.room_id)
                replacement = None
            if replacement is None:
                await self.abort("경매 메시지를 갱신할 수 없어 경매를 취소했습니다.")
            else:
                self.message = replacement

    def _release_generation_lock(self):
        if self.lock_acquired:
            if self.room.team_generation_lock.locked():
                self.room.team_generation_lock.release()
            self.lock_acquired = False
        self.recruit_view.team_generating = False

    async def _finish_auction(self):
        try:
            await self._finish_auction_locked()
        finally:
            # Even if Discord fails while publishing the committed result,
            # do not leave this room permanently locked.
            self._release_generation_lock()

    async def _finish_auction_locked(self):
        self._finished = True
        self.stop()
        timer_task = self._timer_task
        if timer_task is not None and timer_task is not asyncio.current_task():
            timer_task.cancel()

        try:
            assignments = {
                side: assign_positions(self.teams[side], self.profiles)[0]
                for side, _ in self.side_labels
            }
            self.join_cog.activate_room(self.room)
            if len(assignments) == 2:
                self.room.current_teams = {
                    "red": assignments["red"],
                    "blue": assignments["blue"]
                }
                self.room.current_balance_prediction = None
                self.join_cog.last_team_signature = create_team_signature(
                    self.teams["red"], self.teams["blue"]
                )
            else:
                team_rows = []
                for (side, label), assignment in zip(self.side_labels, assignments.values()):
                    roster = [assignment[position] for position in POSITIONS]
                    team_rows.append({
                        "team_name": f"{self.room.room_name} {label.split()[-1]}",
                        "captain_id": self.captains[side],
                        "roster": roster,
                    })
                self.tournament_id = create_auction_bracket(
                    self.room.guild_id or getattr(getattr(self.message, "guild", None), "id", 0),
                    f"{self.room.room_name} 경매컵",
                    self.captains[self.side_labels[0][0]],
                    team_rows,
                )
                # 경매 인원 20명을 경기방 참가자로 남겨두면
                # 10명씩 불러오는 준결승을 시작할 수 없으므로 컵 로스터에 보관하고 방을 비웁니다.
                self.room.reset_game(keep_recruit_view=True)
                self.room.player_limit = MAX_PLAYERS
                self.join_cog.last_team_signature = None
            self.join_cog.save_rooms_state()
        except Exception:
            logger.exception("경매 팀 배정/저장 실패 | 방=%s", self.room.room_id)
            self.room.current_teams = None
            self.room.current_balance_prediction = None
            self._finished = False
            await self.abort("팀 배정 중 오류가 발생해 경매를 취소했습니다.")
            return

        self.recruit_view.recruit_closed = True
        self.recruit_view.team_generating = False
        for item in self.recruit_view.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = item.custom_id not in (
                    "inhouse_list",
                    "inhouse_reset"
                )
        if self.recruit_view.message is not None:
            try:
                await self.recruit_view.message.edit(
                    embed=self.recruit_view.create_embed(),
                    view=self.recruit_view
                )
            except discord.HTTPException:
                logger.exception("경매 완료 후 모집창 갱신 실패")

        totals = {
            side: sum(
                int(self.profiles.get(user_id, {}).get("rating", 1000))
                for user_id in self.teams[side]
            )
            for side, _ in self.side_labels
        }
        if len(assignments) == 2:
            description = (
                f"{format_room_status(self.room)}\n\n"
                f"팀 레이팅 차이: **{abs(totals['red'] - totals['blue'])}점**\n"
                f"경매 지출: 레드 **{self.spent['red']}점**, "
                f"블루 **{self.spent['blue']}점**"
            )
        else:
            site_base = os.getenv(
                "PUBLIC_SITE_URL", "https://kkobung-web.onrender.com"
            ).rstrip("/")
            description = (
                f"20명 경매로 **4팀 편성**을 완료했습니다.\n"
                f"대회 번호: **{self.tournament_id}** · 각 대진은 BO5입니다.\n\n"
                "준결승 2경기 후 결승으로 진행합니다.\n"
                f"첫 준결승을 시작하려면 `/미니컵경기불러오기 대회번호:{self.tournament_id} 경기:1번 준결승`을 실행하세요.\n"
                f"대진표: {site_base}/tournament/{self.tournament_id}"
            )
        embed = discord.Embed(
            title=f"✅ {self.room.room_name} · 경매 팀 편성 완료",
            description=description
        )
        for side, label in self.side_labels:
            assignment = assignments[side]
            total = totals[side]
            lines = []
            for position in POSITIONS:
                user_id = assignment[position]
                rating = self.profiles.get(user_id, {}).get("rating", 1000)
                if user_id == self.captains[side]:
                    acquisition = "캡틴"
                else:
                    acquisition = f"낙찰 {self.purchase_prices.get(user_id, 0)}점"
                lines.append(
                    f"**{position}** - <@{user_id}> ({rating}) · {acquisition}"
                )
            embed.add_field(
                name=f"{label} · {total}점",
                value="\n".join(lines),
                inline=len(assignments) == 2
            )

        if len(assignments) == 2:
            guild = getattr(self.message, "guild", None)
            try:
                await self.join_cog.move_members_to_voice_channel(
                    guild=guild,
                    user_ids=assignments["blue"].values(),
                    channel_id=self.room.blue_voice_channel_id
                )
                await self.join_cog.move_members_to_voice_channel(
                    guild=guild,
                    user_ids=assignments["red"].values(),
                    channel_id=self.room.red_voice_channel_id
                )
            except Exception:
                # 팀 저장은 이미 완료됐습니다. 음성 이동 실패가
                # 경매 성공 상태나 결과 메시지 전송을 취소시키면 안 됩니다.
                logger.exception(
                    "경매 완료 후 음성 채널 이동 실패 | 방=%s",
                    self.room.room_id
                )
            add_match_button_instructions(embed)
        try:
            result_message, _ = await self.join_cog.send_output_message(
                room=self.room,
                fallback_channel=getattr(self.message, "channel", None),
                embed=embed,
                view=MatchControlView(self.join_cog) if len(assignments) == 2 else None
            )
        except Exception:
            logger.exception("경매 완료 결과 메시지 전송 실패 | 방=%s", self.room.room_id)
            result_message = None
        if self.message is not None:
            try:
                await self.message.edit(
                    embed=discord.Embed(
                        title=f"✅ {self.room.room_name} · 경매 종료",
                        description=(
                            "최종 팀 편성 결과를 새 메시지에 게시했습니다."
                            if result_message is not None
                            else "팀 편성은 저장했지만 결과 메시지를 보내지 못했습니다."
                        )
                    ),
                    view=None
                )
            except discord.HTTPException:
                pass

    async def abort(self, reason):
        if self._finished:
            return
        self._finished = True
        self.stop()
        timer_task = self._timer_task
        if timer_task is not None and timer_task is not asyncio.current_task():
            timer_task.cancel()
        self._release_generation_lock()
        self.recruit_view.recruit_closed = getattr(
            self.recruit_view,
            "_draft_was_closed",
            False
        )
        await self.recruit_view.restore_recruitment_controls()
        if self.message is not None:
            try:
                await self.message.edit(
                    content=f"⏹️ {reason}",
                    embed=None,
                    view=None
                )
            except discord.HTTPException:
                pass

    async def cancel_button(self, interaction):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return
        await interaction.response.defer(ephemeral=True)
        async with self._auction_lock:
            if self._finished:
                await interaction.followup.send(
                    "이미 종료된 경매입니다.",
                    ephemeral=True
                )
                return
            await self.abort("관리자가 경매를 취소했습니다.")
        await interaction.followup.send("✅ 경매를 취소했습니다.", ephemeral=True)

    async def on_timeout(self):
        async with self._auction_lock:
            if not self._finished:
                await self.abort("경매 화면이 만료되어 경매를 취소했습니다.")


class CaptainSetupView(discord.ui.View):
    def __init__(self, recruit_view, player_ids, profiles):
        super().__init__(timeout=180)
        self.recruit_view = recruit_view
        self.join_cog = recruit_view.join_cog
        self.room = recruit_view.room
        self.player_ids = list(player_ids)
        self.profiles = profiles
        self.selected_captains = []
        self.message = None
        self.started = False
        self.lock_acquired = False
        self.add_item(CaptainSelection(self))

    def _release_room_lock(self):
        if self.lock_acquired:
            if self.room.team_generation_lock.locked():
                self.room.team_generation_lock.release()
            self.lock_acquired = False

    @discord.ui.button(
        label="드래프트 시작",
        emoji="▶️",
        style=discord.ButtonStyle.success,
        row=1
    )
    async def start_button(self, interaction, button):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return
        if not self.join_cog.activate_room(self.room):
            await interaction.response.send_message(
                "❌ 연결된 내전 방을 찾지 못했습니다.",
                ephemeral=True
            )
            return
        if self.join_cog.current_recruit_view is not self.recruit_view:
            await interaction.response.send_message(
                "❌ 이 모집창은 이미 만료되었습니다.",
                ephemeral=True
            )
            return
        if (
            self.recruit_view._captain_setup_view is not self
            or self.started
        ):
            await interaction.response.send_message(
                "⏳ 이미 팀 편성 또는 드래프트가 진행 중입니다.",
                ephemeral=True
            )
            return
        current_players = list(self.room.players.keys())
        if current_players != self.player_ids:
            await interaction.response.send_message(
                "❌ 참가 명단이 바뀌었습니다. 팀 생성 버튼부터 다시 눌러주세요.",
                ephemeral=True
            )
            return
        if len(self.selected_captains) != 2:
            await interaction.response.send_message(
                "❌ 먼저 캡틴 2명을 선택해주세요.",
                ephemeral=True
            )
            return
        if (
            self.room.current_teams is not None
            or self.room.match_in_progress
            or self.room.mvp_vote_in_progress
            or self.room.match_transaction_active
        ):
            await interaction.response.send_message(
                "❌ 이미 팀이 생성됐거나 경기가 진행 중입니다.",
                ephemeral=True
            )
            return

        self.started = True
        await interaction.response.defer(ephemeral=True)
        try:
            await asyncio.wait_for(
                self.room.team_generation_lock.acquire(),
                timeout=0.5
            )
        except asyncio.TimeoutError:
            self.started = False
            await interaction.followup.send(
                "⏳ 이 내전방에서 다른 팀 편성 작업이 진행 중입니다. 끝난 뒤 다시 눌러주세요.",
                ephemeral=True
            )
            return
        self.lock_acquired = True
        self.recruit_view._captain_setup_view = None
        self.recruit_view.team_generating = True
        self.recruit_view._draft_was_closed = self.recruit_view.recruit_closed
        self.recruit_view.recruit_closed = True
        for item in self.recruit_view.children:
            item.disabled = True
        if self.recruit_view.message is not None:
            try:
                recruit_embed = self.recruit_view.create_embed()
                for item in self.recruit_view.children:
                    item.disabled = True
                await self.recruit_view.message.edit(
                    embed=recruit_embed,
                    view=self.recruit_view
                )
            except discord.HTTPException:
                pass

        first_pick_view = CaptainFirstPickView(
            self.recruit_view,
            self.player_ids,
            self.profiles,
            captain1=self.selected_captains[0],
            captain2=self.selected_captains[1]
        )
        try:
            message, _ = await self.join_cog.send_output_message(
                room=self.room,
                fallback_channel=interaction.channel,
                embed=first_pick_view.create_embed(),
                view=first_pick_view
            )
        except Exception:
            logger.exception(
                "캡틴 드래프트 시작 메시지 전송 실패 | 방=%s",
                self.room.room_id
            )
            message = None
        if message is None:
            self._release_room_lock()
            self.recruit_view.team_generating = False
            self.recruit_view.recruit_closed = self.recruit_view._draft_was_closed
            await self.recruit_view.restore_recruitment_controls()
            await interaction.followup.send(
                "❌ 드래프트 메시지를 보낼 수 없습니다. 채널 권한을 확인해주세요.",
                ephemeral=True
            )
            return
        first_pick_view.lock_acquired = self.lock_acquired
        self.lock_acquired = False
        first_pick_view.message = message
        if interaction.message is not None:
            try:
                await interaction.message.edit(
                    content="✅ 캡틴 드래프트를 시작했습니다. 모집 채널을 확인해주세요.",
                    view=None
                )
            except discord.HTTPException:
                pass
        await interaction.followup.send(
            "✅ 캡틴들에게 첫 픽 담당을 합의해달라고 안내했습니다.\n"
            f"진행 메시지: {message.jump_url}",
            ephemeral=True
        )

    async def on_timeout(self):
        if self.recruit_view._captain_setup_view is self:
            self.recruit_view._captain_setup_view = None
            self.recruit_view.team_generating = False


class FirstPickButton(discord.ui.Button):
    def __init__(self, first_pick_view, side, label):
        self.first_pick_view = first_pick_view
        self.side = side
        super().__init__(
            label=label,
            style=discord.ButtonStyle.primary
        )

    async def callback(self, interaction):
        await self.first_pick_view.vote(interaction, self.side)


class CaptainFirstPickView(discord.ui.View):
    """두 캡틴이 같은 첫 픽 담당자를 골라 드래프트를 시작합니다."""

    def __init__(self, recruit_view, player_ids, profiles, captain1, captain2):
        super().__init__(timeout=1800)
        self.recruit_view = recruit_view
        self.join_cog = recruit_view.join_cog
        self.room = recruit_view.room
        self.player_ids = list(player_ids)
        self.profiles = profiles
        self.captains = {"red": captain1, "blue": captain2}
        self.votes = {}
        self.vote_lock = asyncio.Lock()
        self.lock_acquired = False
        self.message = None
        self.add_item(FirstPickButton(self, "red", "캡틴1이 첫 픽"))
        self.add_item(FirstPickButton(self, "blue", "캡틴2가 첫 픽"))
        cancel = discord.ui.Button(
            label="드래프트 취소",
            emoji="⏹️",
            style=discord.ButtonStyle.danger,
            row=1
        )
        cancel.callback = self.cancel_button
        self.add_item(cancel)

    def _release_room_lock(self):
        if self.lock_acquired:
            if self.room.team_generation_lock.locked():
                self.room.team_generation_lock.release()
            self.lock_acquired = False

    def create_embed(self):
        red_vote = self.votes.get(self.captains["red"], "아직 선택 안 함")
        blue_vote = self.votes.get(self.captains["blue"], "아직 선택 안 함")
        vote_name = {"red": "캡틴1 선픽", "blue": "캡틴2 선픽"}
        embed = discord.Embed(
            title=f"🎖️ {self.room.room_name} · 첫 픽 캡틴 합의",
            description=(
                f"캡틴1: <@{self.captains['red']}>\n"
                f"캡틴2: <@{self.captains['blue']}>\n\n"
                "두 캡틴이 같은 선택 버튼을 눌러 첫 픽 담당을 정하세요."
            )
        )
        embed.add_field(
            name="캡틴1 선택",
            value=vote_name.get(red_vote, red_vote),
            inline=True
        )
        embed.add_field(
            name="캡틴2 선택",
            value=vote_name.get(blue_vote, blue_vote),
            inline=True
        )
        embed.set_footer(text="합의되면 1-2-2-2-1 순서로 드래프트가 시작됩니다.")
        return embed

    async def vote(self, interaction, side):
        user_id = str(interaction.user.id)
        if user_id not in self.captains.values():
            await interaction.response.send_message(
                "❌ 첫 픽 담당은 두 캡틴이 직접 정해야 합니다.",
                ephemeral=True
            )
            return
        await interaction.response.defer()
        async with self.vote_lock:
            if self.is_finished():
                await interaction.followup.send(
                    "이 첫 픽 선택은 이미 처리되었습니다.",
                    ephemeral=True
                )
                return
            if (
                list(self.room.players.keys()) != self.player_ids
                or self.room.current_teams is not None
                or self.room.match_in_progress
            ):
                await self.abort("참가자 또는 경기 상태가 변경되어 드래프트가 취소되었습니다.")
                await interaction.followup.send(
                    "❌ 참가자나 경기 상태가 바뀌어 드래프트를 취소했습니다.",
                    ephemeral=True
                )
                return

            self.votes[user_id] = side
            if (
                len(self.votes) == 2
                and len(set(self.votes.values())) == 1
            ):
                first_side = side
                draft_view = CaptainDraftView(
                    self.recruit_view,
                    self.player_ids,
                    self.profiles,
                    red_captain=self.captains["red"],
                    blue_captain=self.captains["blue"],
                    first_side=first_side
                )
                draft_view.lock_acquired = self.lock_acquired
                self.lock_acquired = False
                draft_view.message = self.message
                self.stop()
                await self.message.edit(
                    embed=draft_view.create_embed(),
                    view=draft_view
                )
                return

            await self.message.edit(
                embed=self.create_embed(),
                view=self
            )

    async def cancel_button(self, interaction):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return
        await interaction.response.defer(ephemeral=True)
        async with self.vote_lock:
            if self.is_finished():
                await interaction.followup.send(
                    "이미 종료된 드래프트입니다.",
                    ephemeral=True
                )
                return
            await self.abort("관리자가 캡틴 드래프트를 취소했습니다.")
        await interaction.followup.send(
            "✅ 드래프트를 취소했습니다.",
            ephemeral=True
        )

    async def abort(self, reason):
        self.stop()
        self._release_room_lock()
        self.recruit_view.team_generating = False
        self.recruit_view.recruit_closed = getattr(
            self.recruit_view,
            "_draft_was_closed",
            False
        )
        await self.recruit_view.restore_recruitment_controls()
        if self.message is not None:
            try:
                await self.message.edit(
                    content=f"⏹️ {reason}",
                    embed=None,
                    view=None
                )
            except discord.HTTPException:
                pass

    async def on_timeout(self):
        async with self.vote_lock:
            if not self.is_finished():
                await self.abort(
                    "30분 동안 캡틴 간 합의가 없어 드래프트가 종료되었습니다."
                )


class DraftPlayerSelect(discord.ui.Select):
    def __init__(self, draft_view):
        self.draft_view = draft_view
        self.turn_index = draft_view.turn_index
        side = draft_view.current_side
        pick_size = draft_view.current_pick_size
        remaining = [
            user_id for user_id in draft_view.player_ids
            if user_id not in draft_view.red_team
            and user_id not in draft_view.blue_team
        ]
        options = []
        for user_id in remaining:
            player = draft_view.room.players.get(user_id, {})
            nickname = str(player.get("nickname") or user_id)
            options.append(discord.SelectOption(
                label=nickname[:100],
                value=user_id
            ))
        captain_id = draft_view.captains[side]
        super().__init__(
            placeholder=(
                f"{'🔴 레드팀' if side == 'red' else '🔵 블루팀'} 차례 — "
                f"<@{captain_id}> {pick_size}명 선택"
            )[:150],
            min_values=pick_size,
            max_values=pick_size,
            options=options,
            disabled=not options
        )

    async def callback(self, interaction):
        await self.draft_view.pick_players(
            interaction,
            list(self.values),
            expected_turn=self.turn_index
        )


class CaptainDraftView(discord.ui.View):
    PICK_PATTERN = (1, 2, 2, 2, 1)

    def __init__(
        self,
        recruit_view,
        player_ids,
        profiles,
        red_captain,
        blue_captain,
        first_side="red"
    ):
        super().__init__(timeout=1800)
        self.recruit_view = recruit_view
        self.join_cog = recruit_view.join_cog
        self.room = recruit_view.room
        self.player_ids = list(player_ids)
        self.profiles = profiles
        self.captains = {"red": red_captain, "blue": blue_captain}
        self.red_team = [red_captain]
        self.blue_team = [blue_captain]
        self.first_side = first_side
        self.turn_index = 0
        self._finishing = False
        self._draft_lock = asyncio.Lock()
        self.lock_acquired = False
        self.message = None
        self._refresh_controls()

    def _release_room_lock(self):
        if self.lock_acquired:
            if self.room.team_generation_lock.locked():
                self.room.team_generation_lock.release()
            self.lock_acquired = False

    @property
    def current_side(self):
        if self.turn_index % 2 == 0:
            return self.first_side
        return "blue" if self.first_side == "red" else "red"

    @property
    def current_pick_size(self):
        return self.PICK_PATTERN[self.turn_index]

    def _refresh_controls(self):
        self.clear_items()
        if len(self.red_team) < 5 or len(self.blue_team) < 5:
            self.add_item(DraftPlayerSelect(self))
            cancel = discord.ui.Button(
                label="드래프트 취소",
                emoji="⏹️",
                style=discord.ButtonStyle.danger,
                row=1
            )
            cancel.callback = self.cancel_button
            self.add_item(cancel)

    def create_embed(self):
        side_text = "🔴 레드팀" if self.current_side == "red" else "🔵 블루팀"
        remaining = MAX_PLAYERS - len(self.red_team) - len(self.blue_team)
        embed = discord.Embed(
            title=f"🎖️ {self.room.room_name} · 캡틴 드래프트",
            description=(
                f"현재 선택 차례: **{side_text}** — "
                f"<@{self.captains[self.current_side]}>\n"
                f"이번 선택 인원: **{self.current_pick_size}명**\n"
                f"남은 선수: **{remaining}명**\n\n"
                "해당 팀 캡틴이 아래 목록에서 필요한 인원을 한 번에 선택하세요."
            )
        )
        for side, team, label in (
            ("red", self.red_team, "🔴 레드팀"),
            ("blue", self.blue_team, "🔵 블루팀")
        ):
            captain_id = self.captains[side]
            picks = [f"<@{user_id}>" for user_id in team]
            embed.add_field(
                name=f"{label} · 캡틴 <@{captain_id}> ({len(team)}/5)",
                value="\n".join(picks) or "아직 선택한 선수가 없습니다.",
                inline=True
            )
        embed.set_footer(text="선택 순서: 1명 → 2명 → 2명 → 2명 → 마지막 1명")
        return embed

    async def pick_players(self, interaction, user_ids, expected_turn):
        # Acknowledge before waiting on another pick/cancel callback so queued
        # interactions do not expire while the current message is being edited.
        await interaction.response.defer()
        async with self._draft_lock:
            await self._pick_players_locked(
                interaction,
                user_ids,
                expected_turn
            )

    async def _pick_players_locked(self, interaction, user_ids, expected_turn):
        if self._finishing or self.is_finished():
            await interaction.followup.send(
                "❌ 이 드래프트는 이미 종료되었습니다.",
                ephemeral=True
            )
            return
        if expected_turn != self.turn_index:
            await interaction.followup.send(
                "🔄 선택 차례가 바뀌었습니다. 최신 드래프트 메시지에서 골라주세요.",
                ephemeral=True
            )
            return
        expected_captain = self.captains[self.current_side]
        if str(interaction.user.id) != expected_captain and not is_admin(interaction):
            await interaction.followup.send(
                f"❌ 지금은 <@{expected_captain}> 캡틴의 선택 차례입니다.",
                ephemeral=True
            )
            return
        if len(user_ids) != self.current_pick_size:
            await interaction.followup.send(
                f"❌ 이번 차례에는 {self.current_pick_size}명을 선택해야 합니다.",
                ephemeral=True
            )
            return
        if any(
            user_id in self.red_team or user_id in self.blue_team
            for user_id in user_ids
        ):
            await interaction.followup.send(
                "❌ 이미 선택된 참가자가 포함되어 있습니다.",
                ephemeral=True
            )
            return
        current_ids = list(self.room.players.keys())
        if current_ids != self.player_ids or self.room.current_teams is not None:
            await interaction.followup.send(
                "❌ 참가자 명단이나 팀 상태가 바뀌어 드래프트를 취소합니다.",
                ephemeral=True
            )
            await self.abort("참가자 명단이나 팀 상태가 변경되어 드래프트가 취소되었습니다.")
            return
        side = self.current_side
        (self.red_team if side == "red" else self.blue_team).extend(user_ids)
        self.turn_index += 1
        if self.turn_index >= len(self.PICK_PATTERN):
            self._finishing = True
            await self.finish_draft()
            return
        self._refresh_controls()
        await self.message.edit(
            embed=self.create_embed(),
            view=self
        )

    async def finish_draft(self):
        try:
            self.join_cog.activate_room(self.room)
            red_assignment, _ = assign_positions(self.red_team, self.profiles)
            blue_assignment, _ = assign_positions(self.blue_team, self.profiles)
            if red_assignment is None or blue_assignment is None:
                raise ValueError("드래프트 팀의 포지션 배정을 만들지 못했습니다.")
            self.room.current_teams = {
                "red": red_assignment,
                "blue": blue_assignment
            }
            self.room.current_balance_prediction = None
            self.join_cog.last_team_signature = create_team_signature(
                self.red_team,
                self.blue_team
            )
            self.join_cog.save_rooms_state()
        except Exception:
            logger.exception(
                "캡틴 드래프트 팀 배정/저장 실패 | 방=%s",
                self.room.room_id
            )
            self.room.current_teams = None
            self.room.current_balance_prediction = None
            self.join_cog.last_team_signature = None
            self._finishing = False
            await self.abort("팀 배정 중 오류가 발생해 드래프트를 취소했습니다.")
            return

        self._release_room_lock()

        for item in self.recruit_view.children:
            if not isinstance(item, discord.ui.Button):
                continue
            item.disabled = item.custom_id not in ("inhouse_list", "inhouse_reset")
        self.recruit_view.recruit_closed = True
        self.recruit_view.team_generating = False
        if self.recruit_view.message is not None:
            try:
                recruit_embed = self.recruit_view.create_embed()
                for item in self.recruit_view.children:
                    if isinstance(item, discord.ui.Button):
                        item.disabled = item.custom_id not in (
                            "inhouse_list",
                            "inhouse_reset"
                        )
                await self.recruit_view.message.edit(
                    embed=recruit_embed,
                    view=self.recruit_view
                )
            except discord.HTTPException:
                pass

        red_rating = sum(int(self.profiles.get(uid, {}).get("rating", 1000)) for uid in self.red_team)
        blue_rating = sum(int(self.profiles.get(uid, {}).get("rating", 1000)) for uid in self.blue_team)
        embed = discord.Embed(
            title=f"🎖️ {self.room.room_name} · 캡틴 드래프트 완료",
            description=(
                f"{format_room_status(self.room)}\n\n"
                f"팀 레이팅 차이: **{abs(red_rating - blue_rating)}점**"
            )
        )
        for side, assignment, total, label in (
            ("red", red_assignment, red_rating, "🔴 레드팀"),
            ("blue", blue_assignment, blue_rating, "🔵 블루팀")
        ):
            lines = []
            for position in POSITIONS:
                user_id = assignment[position]
                rating = self.profiles.get(user_id, {}).get("rating", 1000)
                captain_mark = " 👑" if user_id == self.captains[side] else ""
                lines.append(f"**{position}** - <@{user_id}> ({rating}){captain_mark}")
            embed.add_field(
                name=f"{label} · {total}점",
                value="\n".join(lines),
                inline=True
            )

        guild = getattr(self.message, "guild", None)
        try:
            await asyncio.wait_for(
                self.join_cog.move_members_to_voice_channel(
                    guild=guild,
                    user_ids=blue_assignment.values(),
                    channel_id=self.room.blue_voice_channel_id
                ),
                timeout=15
            )
            await asyncio.wait_for(
                self.join_cog.move_members_to_voice_channel(
                    guild=self.message.guild if self.message else None,
                    user_ids=red_assignment.values(),
                    channel_id=self.room.red_voice_channel_id
                ),
                timeout=15
            )
        except Exception:
            logger.exception(
                "캡틴 드래프트 후 음성채널 이동 실패 | 방=%s",
                self.room.room_id
            )
        add_match_button_instructions(embed)
        try:
            await self.join_cog.send_output_message(
                room=self.room,
                fallback_channel=getattr(self.message, "channel", None),
                embed=embed,
                view=MatchControlView(self.join_cog)
            )
        except Exception:
            logger.exception(
                "캡틴 드래프트 최종 팀 메시지 전송 실패 | 방=%s",
                self.room.room_id
            )
        self.stop()
        if self.message is not None:
            try:
                await self.message.edit(
                    embed=discord.Embed(
                        title=f"✅ {self.room.room_name} · 드래프트 완료",
                        description="최종 팀 편성 결과는 새 메시지에 게시되었습니다."
                    ),
                    view=None
                )
            except discord.HTTPException:
                pass

    async def cancel_button(self, interaction):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return
        await interaction.response.defer(ephemeral=True)
        async with self._draft_lock:
            if self._finishing or self.is_finished():
                await interaction.followup.send(
                    "⏳ 팀 편성을 마무리하고 있거나 드래프트가 종료되었습니다.",
                    ephemeral=True
                )
                return
            await self.abort("관리자가 캡틴 드래프트를 취소했습니다.")
        await interaction.followup.send("✅ 드래프트를 취소했습니다.", ephemeral=True)

    async def abort(self, reason):
        if self._finishing:
            return
        self._finishing = True
        self.stop()
        self._release_room_lock()
        self.recruit_view.team_generating = False
        self.recruit_view.recruit_closed = getattr(
            self.recruit_view,
            "_draft_was_closed",
            False
        )
        await self.recruit_view.restore_recruitment_controls()
        if self.message is not None:
            try:
                await self.message.edit(
                    content=f"⏹️ {reason}",
                    embed=None,
                    view=None
                )
            except discord.HTTPException:
                pass

    async def on_timeout(self):
        async with self._draft_lock:
            if not self.is_finished():
                await self.abort("30분 동안 선택이 없어 드래프트가 종료되었습니다.")

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
        self._captain_setup_view = None
        self._auction_setup_view = None

        if len(self.join_cog.players) < self.room.player_limit:
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
        waiting_players = self.room.waiting_players

        self.make_teams_button.disabled = (
            len(players) < self.room.player_limit
        )

        if self.recruit_closed:
            title = "🔒 내전 모집 종료"
            description = (
                "모집이 종료되었습니다.\n\n"
                f"👥 현재 참가자: **{len(players)}/{self.room.player_limit}명**\n"
                f"🕒 현재 대기자: "
                f"**{len(waiting_players)}/{MAX_WAITING_PLAYERS}명**"
            )
        else:
            title = "🎮 내전 참가 모집"
            description = (
                "아래 버튼을 눌러 내전에 참가하세요.\n\n"
                f"👥 현재 참가자: **{len(players)}/{self.room.player_limit}명**\n"
                f"🕒 현재 대기자: "
                f"**{len(waiting_players)}/{MAX_WAITING_PLAYERS}명**"
            )

        description = (
            f"{format_room_status(self.room)}\n\n"
            f"{description}"
        )

        if self.room.recruit_start_mode == "when_full":
            start_notice = f"🚀 **시작 안내:** {self.room.player_limit}명 모이면 바로 시작"
        elif self.room.recruit_start_mode == "scheduled":
            start_notice = (
                "⏰ **시작 예정:** "
                f"{self.room.recruit_start_time or '시간 미정'}"
            )
        else:
            start_notice = "🗓️ **시작 안내:** 아직 미정"

        description = f"{description}\n\n{start_notice}"

        embed = discord.Embed(
            title=title,
            description=description
        )

        if players:
            participant_list = []

            # 모집 명단도 시즌2 레이팅을 표시합니다. 저장된 전체 시즌
            # 프로필 rating을 그대로 쓰면 이전 시즌 점수가 노출됩니다.
            display_profiles = _season_profiles_for_players(
                self.join_cog,
                players
            )

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

                profile = display_profiles.get(user_id)

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

        if waiting_players:
            waiting_list = [
                f"**{index}.** <@{user_id}>"
                for index, user_id in enumerate(
                    waiting_players,
                    start=1
                )
            ]
            embed.add_field(
                name="🕒 대기자 명단",
                value="\n".join(waiting_list),
                inline=False
            )
        else:
            embed.add_field(
                name="🕒 대기자 명단",
                value="아직 대기자가 없습니다.",
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
        await interaction.response.defer()
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

            if self.team_generating or room.team_generation_lock.locked():
                await send_ephemeral_response(
                    interaction,
                    "⏳ 팀 편성, 경매 또는 드래프트 준비 중에는 참가 명단을 변경할 수 없습니다."
                )
                return

            if room.match_in_progress:
                await send_ephemeral_response(
                    interaction,
                    "❌ 현재 경기가 진행 중입니다."
                )
                return

            if self.recruit_closed:
                await send_ephemeral_response(
                    interaction,
                    "🔒 모집이 종료되었습니다."
                )
                return

            if user_id not in self.join_cog.profiles:
                await send_ephemeral_response(
                    interaction,
                    "❌ 내전에 참가하려면 먼저 `/가입`으로 프로필 등록을 완료해주세요."
                )
                return

            if user_id in players:
                await send_ephemeral_response(
                    interaction,
                    "❌ 이미 참가 중입니다."
                )
                return

            if user_id in room.waiting_players:
                waiting_number = (
                    list(room.waiting_players).index(user_id) + 1
                )
                await send_ephemeral_response(
                    interaction,
                    f"❌ 이미 대기 **{waiting_number}번**으로 등록되어 있습니다."
                )
                return

            other_room = (
                self.join_cog.room_manager
                .find_player_room(
                    user_id
                )
            )

            if other_room is not None:
                await send_ephemeral_response(
                    interaction,
                    "❌ 다른 내전에 이미 참가 중입니다.\n"
                    f"현재 참가 중인 방: **{other_room.room_name}**"
                )
                return

            if len(players) >= room.player_limit:
                if len(room.waiting_players) >= MAX_WAITING_PLAYERS:
                    await send_ephemeral_response(
                        interaction,
                        "❌ 참가자와 대기자 모집이 모두 마감되었습니다."
                    )
                    return

                room.waiting_players[user_id] = {
                    "nickname": interaction.user.display_name
                }
                self.join_cog.save_rooms_state()
                waiting_number = len(room.waiting_players)

                await interaction.edit_original_response(
                    embed=self.create_embed(),
                    view=self
                )
                await interaction.followup.send(
                    f"🕒 대기 **{waiting_number}번**으로 등록되었습니다.",
                    ephemeral=True
                )
                await announce_recruitment_join(
                    self,
                    user_id,
                    waiting=True
                )
                return

            players[user_id] = {
                "nickname": interaction.user.display_name
            }

            self.join_cog.save_rooms_state()

            self.make_teams_button.disabled = (
                len(players) < self.room.player_limit
            )

            await interaction.edit_original_response(
                embed=self.create_embed(),
                view=self
            )

            await interaction.followup.send(
                "✅ 내전에 참가했습니다.",
                ephemeral=True
            )
            await announce_recruitment_join(
                self,
                user_id
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
        await interaction.response.defer()
        user_id = str(interaction.user.id)
        room = self.join_cog.active_room

        async with room.operation_lock:
            players = room.players

            if self.team_generating or room.team_generation_lock.locked():
                await send_ephemeral_response(
                    interaction,
                    "⏳ 팀 편성, 경매 또는 드래프트 준비 중에는 참가 명단을 변경할 수 없습니다."
                )
                return

            if self.recruit_closed:
                await send_ephemeral_response(
                    interaction,
                    "🔒 모집이 종료되어 참가 취소가 불가능합니다."
                )
                return

            if room.match_in_progress:
                await send_ephemeral_response(
                    interaction,
                    "❌ 경기 중에는 참가 취소가 불가능합니다."
                )
                return

            if (
                user_id not in players
                and user_id not in room.waiting_players
            ):
                await send_ephemeral_response(
                    interaction,
                    "❌ 현재 참가 또는 대기 중이 아닙니다."
                )
                return

            promoted_user_id = None

            if user_id in room.waiting_players:
                del room.waiting_players[user_id]
                cancellation_message = "✅ 대기 등록이 취소되었습니다."
            else:
                del players[user_id]
                cancellation_message = "✅ 참가가 취소되었습니다."

                if room.waiting_players:
                    promoted_user_id = next(iter(room.waiting_players))
                    players[promoted_user_id] = (
                        room.waiting_players.pop(promoted_user_id)
                    )

            self.join_cog.save_rooms_state()

            self.make_teams_button.disabled = (
                len(players) < self.room.player_limit
            )

            await interaction.edit_original_response(
                embed=self.create_embed(),
                view=self
            )

            await interaction.followup.send(
                cancellation_message
                + (
                    f"\n🎉 대기 1번 <@{promoted_user_id}>님이 "
                    "참가자로 자동 승격되었습니다."
                    if promoted_user_id is not None
                    else ""
                ),
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
        await interaction.response.defer(ephemeral=True, thinking=True)
        room = self.join_cog.active_room

        async with room.operation_lock:
            player_ids = list(
                room.players.keys()
            )

            waiting_ids = list(
                room.waiting_players.keys()
            )

        if not player_ids and not waiting_ids:
            await interaction.edit_original_response(
                content="📋 현재 참가자와 대기자가 없습니다."
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

        waiting_text = ""
        if waiting_ids:
            waiting_text = (
                "\n\n🕒 **대기자 "
                f"({len(waiting_ids)}/{MAX_WAITING_PLAYERS}명)**\n"
                + "\n".join(
                    f"{index}. <@{user_id}>"
                    for index, user_id in enumerate(
                        waiting_ids,
                        start=1
                    )
                )
            )

        await interaction.edit_original_response(
            content=(
                f"📋 **현재 참가자 "
                f"({len(player_ids)}/{self.room.player_limit}명)**\n\n"
                + "\n".join(participant_list)
                + waiting_text
            )
        )

    @discord.ui.button(
        label="인원 선택",
        emoji="👥",
        style=discord.ButtonStyle.secondary,
        custom_id="inhouse_capacity",
        row=1
    )
    async def capacity_button(self, interaction, button):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return
        if self.recruit_closed:
            await interaction.response.send_message(
                "🔒 모집을 다시 연 뒤 인원을 변경해주세요.",
                ephemeral=True
            )
            return
        if self.team_generating or self._auction_setup_view is not None:
            await interaction.response.send_message(
                "⏳ 팀 생성 또는 경매 준비 중에는 정원을 변경할 수 없습니다.",
                ephemeral=True
            )
            return
        await interaction.response.send_message(
            "모집 인원을 선택해주세요.\n"
            "20명은 캡틴 4명과 팀별 5명으로 구성되는 4팀 경매입니다.",
            view=PlayerLimitView(self),
            ephemeral=True
        )

    async def generate_teams(
        self,
        interaction: discord.Interaction,
        allow_team_generating=False
    ):
        """현재 방의 팀 생성을 한 번에 하나씩 처리합니다."""

        room = self.join_cog.active_room

        # Slash commands can create a temporary JoinView. Route generation
        # through the room's live recruitment view so its buttons and state
        # are the ones that get locked after the teams are made.
        active_view = room.current_recruit_view
        if active_view is not None and active_view is not self:
            return await active_view.generate_teams(
                interaction,
                allow_team_generating=allow_team_generating
            )

        if not interaction.response.is_done():
            await interaction.response.defer()

        if active_view is not None:
            setup_in_progress = (
                getattr(active_view, "_captain_setup_view", None) is not None
                or getattr(active_view, "_auction_setup_view", None) is not None
            )
            if setup_in_progress or (
                active_view.team_generating and not allow_team_generating
            ):
                await send_ephemeral_response(
                    interaction,
                    "⏳ 이 내전방에서 팀 편성·드래프트·경매 준비가 진행 중입니다."
                )
                return

        if getattr(room, "tournament_id", None):
            await send_ephemeral_response(
                interaction,
                "❌ 미니컵 대진에서 불러온 경기는 일반 팀 재생성을 할 수 없습니다."
            )
            return

        if room.team_generation_lock.locked():
            await send_ephemeral_response(
                interaction,
                "⏳ 이 내전방은 이미 팀 생성·경매 작업 중입니다. 작업 종료 후 다시 시도해주세요."
            )
            return

        try:
            await asyncio.wait_for(
                room.team_generation_lock.acquire(),
                timeout=0.5
            )
        except asyncio.TimeoutError:
            await send_ephemeral_response(
                interaction,
                "⏳ 이 내전방에서 다른 팀 생성 작업이 시작됐습니다. 잠시 뒤 다시 시도해주세요."
            )
            return

        try:
            try:
                await asyncio.wait_for(
                    room.operation_lock.acquire(),
                    timeout=5
                )
            except asyncio.TimeoutError:
                await send_ephemeral_response(
                    interaction,
                    "⏳ 이 내전방에서 다른 처리가 진행 중입니다. 잠시 뒤 다시 시도해주세요."
                )
                return
            try:
                await self._generate_teams(
                    interaction,
                    room
                )
            finally:
                room.operation_lock.release()
        finally:
            room.team_generation_lock.release()

    async def _generate_teams(
        self,
        interaction: discord.Interaction,
        room
    ):
        """포지션과 레이팅을 고려해 팀을 생성합니다."""

        if room.mvp_vote_in_progress:
            await send_ephemeral_response(
                interaction,
                "❌ MVP 투표 중에는 팀을 다시 생성할 수 없습니다."
            )
            return

        if (
            room.match_in_progress
            or room.match_transaction_active
            or room.pending_match_token is not None
        ):
            await send_ephemeral_response(
                interaction,
                "❌ 경기 진행 또는 결과 저장 중에는 팀을 다시 생성할 수 없습니다."
            )
            return

        if room.series_game > 0:
            await send_ephemeral_response(
                interaction,
                "❌ 세트 결과가 등록된 시리즈는 팀을 다시 생성할 수 없습니다. 먼저 `/내전종료`를 실행해주세요."
            )
            return

        self.join_cog.reload_profiles()

        players = list(self.join_cog.players.keys())

        if len(players) != room.player_limit:

            # 팀 생성 완료
            

            await send_ephemeral_response(
                interaction,
                f"❌ 아직 {room.player_limit}명이 모이지 않았습니다. 현재 {len(players)}/{room.player_limit}명입니다."
            )
            return

        if interaction.guild is None:

            

            await send_ephemeral_response(
                interaction,
                "❌ 서버 안에서만 팀을 생성할 수 있습니다."
            )
            return

        # 계산과 음성채널 이동 중 상호작용 시간 초과를 방지합니다.
        if not interaction.response.is_done():
            await interaction.response.defer()


        # 시즌이 진행 중이면 전체 누적 레이팅 대신 이번 시즌 레이팅으로
        # 팀을 계산하고 표시합니다. 새 시즌 참가자는 1000점에서 시작합니다.
        active_season = get_active_season()
        profiles = {
            user_id: dict(profile)
            for user_id, profile in self.join_cog.profiles.items()
        }
        if active_season is not None:
            for user_id in players:
                profile = profiles.get(user_id)
                if profile is None:
                    continue
                season_stats = get_season_player_stats(
                    active_season["id"],
                    user_id
                )
                season_rating = int(
                    (season_stats or {}).get("rating") or 1000
                )
                profile["rating"] = season_rating
                profile["hidden_mmr"] = season_rating
                # 포지션별 MMR/최근 폼도 시즌 전 자료를 이어받지 않게 합니다.
                profile["position_ratings"] = {}
                profile["recent_position_form"] = {}

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
            ),
            prediction_calibration=getattr(
                self.join_cog, "balance_prediction_calibration", 1.0
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
        lane_gaps = balance_result.get("lane_gaps", {})
        weighted_lane_gap_penalty = balance_result.get(
            "weighted_lane_gap_penalty",
            0
        )
        hard_lane_violation_count = balance_result.get(
            "hard_lane_violation_count",
            0
        )
        balance_grade = balance_result.get("balance_grade", "-")
        balance_summary = balance_result.get("balance_summary", "계산 완료")
        red_expected_winrate = balance_result.get("red_expected_winrate", 50.0)
        blue_expected_winrate = balance_result.get("blue_expected_winrate", 50.0)
        top_two_gap = balance_result.get("top_two_gap", 0)
        red_autofill_count = balance_result.get("red_autofill_count", 0)
        blue_autofill_count = balance_result.get("blue_autofill_count", 0)
        red_uncertainty = balance_result.get("red_uncertainty", 0)
        blue_uncertainty = balance_result.get("blue_uncertainty", 0)

        self.join_cog.last_team_signature = (
            balance_result[
                "signature"
            ]
        )

        self.join_cog.current_teams = {
            "red": best_red_assignment,
            "blue": best_blue_assignment
        }
        room.current_balance_prediction = {
            "red_expected_winrate": red_expected_winrate,
            "calibration_factor": getattr(
                self.join_cog, "balance_prediction_calibration", 1.0
            )
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
            "상대=%s(가중=%s) | 라인차=%s(가중=%s) | "
            "예상승률=%.1f:%.1f | 상위2명차=%s | 자동배정=%s:%s | 최종=%s",
            room.room_id,
            mmr_difference,
            weighted_mmr_penalty,
            position_penalty,
            weighted_position_penalty,
            same_team_penalty,
            weighted_same_team_penalty,
            opponent_penalty,
            weighted_opponent_penalty,
            lane_gaps,
            weighted_lane_gap_penalty,
            red_expected_winrate,
            blue_expected_winrate,
            top_two_gap,
            red_autofill_count,
            blue_autofill_count,
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
                f"**{abs(red_rating - blue_rating)}점**\n"
                f"균형 등급: **{balance_grade}** · {balance_summary}"
            )
        )

        embed.add_field(
            name="🎯 예상 승률 · 정밀 보정",
            value=(
                f"🔴 **{red_expected_winrate:.1f}%** · "
                f"🔵 **{blue_expected_winrate:.1f}%**\n"
                f"상위 2명 전력 차이: **{top_two_gap}점**\n"
                f"비주력 라인 배치: 🔴 {red_autofill_count}명 · "
                f"🔵 {blue_autofill_count}명\n"
                f"라인 MMR 미확정치: 🔴 {red_uncertainty:.1f} · "
                f"🔵 {blue_uncertainty:.1f}"
            ),
            inline=False
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

        largest_lane = max(
            lane_gaps,
            key=lane_gaps.get,
            default=None
        )
        if largest_lane is not None:
            gap_lines = " · ".join(
                f"{position} {lane_gaps.get(position, 0)}"
                for position in ("TOP", "JUNGLE", "MID", "ADC", "SUPPORT")
            )
            embed.add_field(
                name="⚖️ 포지션별 예상 전력 차이",
                value=(
                    f"{gap_lines}\n"
                    f"가장 큰 차이: **{largest_lane} "
                    f"{lane_gaps[largest_lane]}점**"
                ),
                inline=False
            )

        if hard_lane_violation_count:
            embed.add_field(
                name="⚠️ 밸런스 경고",
                value=(
                    f"200점을 초과한 라인이 **{hard_lane_violation_count}개** 있습니다.\n"
                    "가능하면 `다시뽑기`를 권장합니다. 모든 조합이 비슷하다면 "
                    "현재 참가자 구성으로는 완전한 균형이 어렵습니다."
                ),
                inline=False
            )
        elif max(red_expected_winrate, blue_expected_winrate) > 55.0:
            embed.add_field(
                name="⚠️ 예상 승률 경고",
                value=(
                    "가능한 모든 팀 조합을 비교했지만 45~55% 범위에 "
                    "들어오지 못했습니다. 참가자 실력·포지션 구성상 "
                    "완전한 균형이 어려울 수 있습니다."
                ),
                inline=False
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


        # 모집창 버튼에서 실행된 경우에만 원본 모집 메시지를 잠급니다.
        # /관리자팀생성 같은 슬래시 명령은 interaction.message가 None입니다.
        if interaction.message is not None:
            try:
                await interaction.message.edit(
                    embed=self.create_embed(),
                    view=self
                )
            except discord.HTTPException:
                pass


        add_match_button_instructions(embed)
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
                "현재 모집 채널에서 꼬붕봇의 "
                "`채널 보기`, `메시지 보내기`, "
                "`링크 첨부` 권한을 확인해주세요."
            )

        elif used_fallback:
            confirmation_message = (
                "⚠️ 팀 생성은 정상적으로 완료됐습니다.\n"
                "저장된 모집 채널을 찾을 수 없어 "
                "현재 명령 채널에 결과를 표시했습니다.\n"
                "모집 채널에서 꼬붕봇의 "
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
                "✅ 팀 생성 결과를 해당 내전 모집 채널에 "
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
            await interaction.response.send_message(
                "팀 편성 방식을 선택해주세요.",
                view=TeamModeView(self),
                ephemeral=True
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

    async def restore_recruitment_controls(self):
        """드래프트가 취소되면 모집 버튼 상태를 다시 엽니다."""
        if self.message is None:
            return
        recruit_embed = self.create_embed()
        if self.recruit_closed:
            for item in self.children:
                if not isinstance(item, discord.ui.Button):
                    continue
                item.disabled = item.custom_id not in (
                    "inhouse_list",
                    "inhouse_reset",
                    "inhouse_close"
                )
                if item.custom_id == "inhouse_close":
                    item.label = "모집 재개"
                    item.emoji = "🔓"
                    item.style = discord.ButtonStyle.success
        else:
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = False
                    if item.custom_id == "inhouse_make_teams":
                        item.disabled = len(self.room.players) < self.room.player_limit
                    if item.custom_id == "inhouse_close":
                        item.label = "모집 종료"
                        item.emoji = "🔒"
                        item.style = discord.ButtonStyle.secondary
        try:
            await self.message.edit(
                embed=recruit_embed,
                view=self
            )
        except discord.HTTPException:
            logger.exception("드래프트 취소 후 모집 버튼 복구 실패")
            

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

        await interaction.response.defer()

        async with room.operation_lock:
            if self.team_generating or room.team_generation_lock.locked():
                await send_ephemeral_response(
                    interaction,
                    "⏳ 팀 편성, 경매 또는 드래프트 중에는 모집을 변경할 수 없습니다."
                )
                return
            if self.recruit_closed:
                if (
                    room.current_teams is not None
                    or room.match_in_progress
                    or room.mvp_vote_in_progress
                    or room.match_transaction_active
                ):
                    await send_ephemeral_response(
                        interaction,
                        "❌ 팀이 생성됐거나 경기를 처리 중일 때는 모집을 다시 열 수 없습니다."
                    )
                    return

                self.recruit_closed = False

                for item in self.children:
                    if not isinstance(item, discord.ui.Button):
                        continue

                    if item.custom_id == "inhouse_make_teams":
                        item.disabled = (
                            len(room.players) < room.player_limit
                        )
                    else:
                        item.disabled = False

                button.label = "모집 종료"
                button.emoji = "🔒"
                button.style = discord.ButtonStyle.secondary
                result_message = "🔓 모집을 다시 시작했습니다."

            else:
                self.recruit_closed = True

                for item in self.children:
                    if isinstance(item, discord.ui.Button):
                        if item.custom_id not in [
                            "inhouse_list",
                            "inhouse_reset",
                            "inhouse_close"
                        ]:
                            item.disabled = True

                button.disabled = False
                button.label = "모집 재개"
                button.emoji = "🔓"
                button.style = discord.ButtonStyle.success
                result_message = "🔒 모집을 종료했습니다."

            await interaction.edit_original_response(
                embed=self.create_embed(),
                view=self
            )

            await interaction.followup.send(
                result_message,
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

        await interaction.response.defer()

        async with room.operation_lock:
            if self.team_generating or room.team_generation_lock.locked():
                await send_ephemeral_response(
                    interaction,
                    "⏳ 팀 편성, 경매 또는 드래프트 중에는 모집을 초기화할 수 없습니다."
                )
                return
            fixture_released = True
            tournament_id = getattr(room, "tournament_id", None)
            fixture_no = getattr(room, "tournament_fixture_no", None)
            if tournament_id and fixture_no:
                try:
                    fixture_released = release_fixture(tournament_id, fixture_no)
                except Exception:
                    fixture_released = False
                    logger.exception(
                        "모집 초기화 중 미니컵 대진 반환 실패 | 방=%s | 대진=%s",
                        room.room_id,
                        fixture_no
                    )
            room.reset_game(keep_recruit_view=True)

            self.join_cog.save_rooms_state()

            self.recruit_closed = False

            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = False

                    if item.custom_id == "inhouse_close":
                        item.label = "모집 종료"
                        item.emoji = "🔒"
                        item.style = discord.ButtonStyle.secondary

            self.make_teams_button.disabled = True

            await interaction.edit_original_response(
                embed=self.create_embed(),
                view=self
            )

            message = "🔄 모집이 초기화되었습니다."
            if not fixture_released:
                message += "\n⚠️ 미니컵 대진을 대기 상태로 되돌리지 못했습니다. 대진 상태를 확인해주세요."
            await interaction.followup.send(message, ephemeral=True)
