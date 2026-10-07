"""Commands for creating and running four-team mini cups."""

import logging
import os
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands

from services.tournament_service import (
    create_tournament,
    register_team,
    create_bracket,
    get_bracket,
    get_fixture,
    get_tournament,
    delete_tournament,
    claim_fixture,
    release_fixture,
)
from storage.sqlite_db import conn, get_player
from utils.cog_helper import get_join_cog
from utils.permissions import (
    is_match_operator,
    send_match_operator_only_message,
)
from views.join_view import MatchControlView, add_match_button_instructions


logger = logging.getLogger(__name__)
POSITIONS = ("TOP", "JUNGLE", "MID", "ADC", "SUPPORT")
SITE_BASE_URL = os.getenv("PUBLIC_SITE_URL", "https://kkobung-web.onrender.com").rstrip("/")


class TournamentDeleteConfirmView(discord.ui.View):
    """Require a second, operator-only confirmation before deleting a cup."""

    def __init__(self, tournament_id, guild_id, tournament_name):
        super().__init__(timeout=60)
        self.tournament_id = int(tournament_id)
        self.guild_id = str(guild_id)
        self.tournament_name = str(tournament_name)
        self.message = None

    @discord.ui.button(label="대회 삭제 확정", style=discord.ButtonStyle.danger, emoji="🗑️")
    async def confirm_delete(self, interaction, button):
        if str(interaction.guild_id) != self.guild_id:
            await interaction.response.send_message(
                "❌ 대회를 만든 서버에서만 삭제할 수 있습니다.",
                ephemeral=True
            )
            return
        if not is_match_operator(interaction):
            await send_match_operator_only_message(interaction)
            return

        # Acknowledge first so the confirmation cannot expire during DB work.
        await interaction.response.defer()
        try:
            deleted = delete_tournament(self.tournament_id)
        except ValueError as error:
            await interaction.edit_original_response(
                content=f"❌ {error}",
                view=None
            )
            self.stop()
            return
        except Exception:
            logger.exception(
                "미니컵 삭제 실패 | 대회=%s | 서버=%s",
                self.tournament_id,
                self.guild_id
            )
            await interaction.edit_original_response(
                content="❌ 미니컵 삭제 중 오류가 발생했습니다. 로그를 확인해주세요.",
                view=None
            )
            self.stop()
            return

        message = (
            f"🗑️ **{self.tournament_name}** (대회 #{self.tournament_id})을 삭제했습니다.\n"
            "대회 명단과 대진만 삭제했으며, 일반 경기 기록은 보존했습니다."
            if deleted else "이미 삭제되었거나 존재하지 않는 미니컵입니다."
        )
        await interaction.edit_original_response(content=message, view=None)
        self.stop()

    @discord.ui.button(label="취소", style=discord.ButtonStyle.secondary, emoji="↩️")
    async def cancel_delete(self, interaction, button):
        await interaction.response.edit_message(
            content="✅ 미니컵 삭제를 취소했습니다.",
            view=None
        )
        self.stop()

    async def on_timeout(self):
        if self.message is None:
            return
        for item in self.children:
            item.disabled = True
        try:
            await self.message.edit(
                content="⌛ 삭제 확인 시간이 지나 취소되었습니다.",
                view=self
            )
        except discord.HTTPException:
            pass


class Tournament(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _operator_only(self, interaction):
        if is_match_operator(interaction):
            return True
        await send_match_operator_only_message(interaction)
        return False

    @app_commands.command(name="미니컵개설", description="4팀 고정 로스터 미니컵을 개설합니다.")
    @app_commands.describe(대회명="대회에 표시할 이름")
    async def create_cup(self, interaction: discord.Interaction, 대회명: str):
        if not await self._operator_only(interaction):
            return
        if interaction.guild is None:
            await interaction.response.send_message("서버 안에서 사용해주세요.", ephemeral=True)
            return
        name = 대회명.strip()
        if not name or len(name) > 80:
            await interaction.response.send_message("대회명은 1~80자로 입력해주세요.", ephemeral=True)
            return
        tournament_id = create_tournament(interaction.guild.id, name, interaction.user.id)
        await interaction.response.send_message(
            f"🏆 **{name}** 미니컵을 열었습니다. (대회 번호 `{tournament_id}`)\n"
            "팀장은 `/미니컵팀등록`에서 본인 포함 5명의 프로필과 포지션을 등록하면 됩니다.\n"
            "4팀이 모이면 진행자가 `/미니컵대진표`를 실행하세요.",
            allowed_mentions=discord.AllowedMentions.none()
        )

    @app_commands.command(name="미니컵팀등록", description="5명 고정 로스터로 미니컵에 참가 신청합니다.")
    @app_commands.describe(
        대회번호="미니컵개설에서 안내된 번호",
        팀이름="팀 이름",
        탑="TOP 담당 참가자",
        정글="JUNGLE 담당 참가자",
        미드="MID 담당 참가자",
        원딜="ADC 담당 참가자",
        서폿="SUPPORT 담당 참가자",
    )
    async def register_cup_team(
        self,
        interaction: discord.Interaction,
        대회번호: int,
        팀이름: str,
        탑: discord.Member,
        정글: discord.Member,
        미드: discord.Member,
        원딜: discord.Member,
        서폿: discord.Member,
    ):
        tournament = get_tournament(대회번호)
        if tournament is None or str(tournament["guild_id"]) != str(interaction.guild_id):
            await interaction.response.send_message("❌ 이 서버의 미니컵을 찾지 못했습니다.", ephemeral=True)
            return
        roster = [탑, 정글, 미드, 원딜, 서폿]
        team_name = 팀이름.strip()
        if not team_name or len(team_name) > 40:
            await interaction.response.send_message("팀 이름은 1~40자로 입력해주세요.", ephemeral=True)
            return
        roster_ids = [str(member.id) for member in roster]
        if len(set(roster_ids)) != 5:
            await interaction.response.send_message("❌ 포지션마다 서로 다른 참가자를 선택해주세요.", ephemeral=True)
            return
        if str(interaction.user.id) not in roster_ids:
            await interaction.response.send_message("❌ 팀 등록자는 본인도 팀 로스터에 포함되어야 합니다.", ephemeral=True)
            return
        missing_profiles = [member.display_name for member in roster if get_player(str(member.id)) is None]
        if missing_profiles:
            await interaction.response.send_message(
                "❌ 아래 참가자는 통합 프로필 등록이 필요합니다.\n" + "\n".join(missing_profiles),
                ephemeral=True
            )
            return
        try:
            register_team(대회번호, team_name, interaction.user.id, roster_ids)
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        count = conn.execute(
            "SELECT COUNT(*) FROM tournament_teams WHERE tournament_id = ?",
            (int(대회번호),)
        ).fetchone()[0]
        await interaction.response.send_message(
            f"✅ **{team_name}** 등록 완료 ({count}/4팀)\n"
            + " · ".join(f"{position} <@{member.id}>" for position, member in zip(POSITIONS, roster)),
            allowed_mentions=discord.AllowedMentions.none()
        )

    @app_commands.command(name="미니컵대진표", description="등록된 4팀으로 준결승·결승 대진표를 만듭니다.")
    @app_commands.describe(대회번호="미니컵 번호")
    async def make_bracket(self, interaction: discord.Interaction, 대회번호: int):
        if not await self._operator_only(interaction):
            return
        tournament = get_tournament(대회번호)
        if tournament is None or str(tournament["guild_id"]) != str(interaction.guild_id):
            await interaction.response.send_message("❌ 이 서버의 미니컵을 찾지 못했습니다.", ephemeral=True)
            return
        try:
            fixtures = create_bracket(대회번호)
        except ValueError as error:
            await interaction.response.send_message(f"❌ {error}", ephemeral=True)
            return
        await interaction.response.send_message(
            self._bracket_text(대회번호, tournament["name"], fixtures),
            allowed_mentions=discord.AllowedMentions.none()
        )

    @app_commands.command(name="미니컵조회", description="미니컵 대진표와 경기 상태를 확인합니다.")
    @app_commands.describe(대회번호="미니컵 번호")
    async def show_bracket(self, interaction: discord.Interaction, 대회번호: int):
        tournament = get_tournament(대회번호)
        if tournament is None or str(tournament["guild_id"]) != str(interaction.guild_id):
            await interaction.response.send_message("❌ 이 서버의 미니컵을 찾지 못했습니다.", ephemeral=True)
            return
        fixtures = get_bracket(대회번호)
        if not fixtures:
            teams = conn.execute(
                "SELECT team_name FROM tournament_teams WHERE tournament_id = ? ORDER BY id",
                (int(대회번호),)
            ).fetchall()
            body = "\n".join(f"• {team['team_name']}" for team in teams) or "아직 등록된 팀이 없습니다."
            await interaction.response.send_message(
                f"🏆 **{tournament['name']}** · 팀 등록 {len(teams)}/4\n{body}",
                allowed_mentions=discord.AllowedMentions.none()
            )
            return
        await interaction.response.send_message(
            self._bracket_text(대회번호, tournament["name"], fixtures),
            allowed_mentions=discord.AllowedMentions.none()
        )

    @app_commands.command(
        name="미니컵삭제",
        description="테스트 또는 종료된 미니컵과 대진을 삭제합니다."
    )
    @app_commands.describe(대회번호="삭제할 미니컵 번호")
    async def delete_cup(self, interaction: discord.Interaction, 대회번호: int):
        if not await self._operator_only(interaction):
            return
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ 서버 안에서 사용해주세요.",
                ephemeral=True
            )
            return
        tournament = get_tournament(대회번호)
        if tournament is None or str(tournament["guild_id"]) != str(interaction.guild_id):
            await interaction.response.send_message(
                "❌ 이 서버의 미니컵을 찾지 못했습니다.",
                ephemeral=True
            )
            return

        team_count = conn.execute(
            "SELECT COUNT(*) FROM tournament_teams WHERE tournament_id = ?",
            (int(대회번호),)
        ).fetchone()[0]
        view = TournamentDeleteConfirmView(
            대회번호,
            interaction.guild_id,
            tournament["name"]
        )
        await interaction.response.send_message(
            f"⚠️ **{tournament['name']}** (대회 #{대회번호})을 삭제할까요?\n"
            f"등록 팀: {team_count}팀 · 상태: {tournament['status']}\n"
            "대회 팀 명단과 대진을 삭제합니다. 일반 경기 기록은 유지됩니다.",
            view=view,
            ephemeral=True
        )
        view.message = await interaction.original_response()

    @app_commands.command(name="미니컵경기불러오기", description="선택한 대진 경기를 현재 내전방에 불러옵니다.")
    @app_commands.describe(
        대회번호="미니컵 번호",
        경기="1·2는 준결승, 3은 결승",
    )
    async def load_fixture(
        self,
        interaction: discord.Interaction,
        대회번호: int,
        경기: Literal["1번 준결승", "2번 준결승", "결승"]
    ):
        if not await self._operator_only(interaction):
            return
        join_cog = get_join_cog(self.bot)
        if join_cog is None or not await join_cog.require_room(interaction):
            return
        tournament = get_tournament(대회번호)
        if tournament is None or str(tournament["guild_id"]) != str(interaction.guild_id):
            await interaction.response.send_message("❌ 이 서버의 미니컵을 찾지 못했습니다.", ephemeral=True)
            return
        fixture_no = {"1번 준결승": 1, "2번 준결승": 2, "결승": 3}[경기]
        fixture = get_fixture(대회번호, fixture_no)
        if fixture is None or fixture["status"] != "ready":
            await interaction.response.send_message("❌ 해당 경기는 아직 대진이 확정되지 않았거나 이미 끝났습니다.", ephemeral=True)
            return
        room = join_cog.active_room
        if (
            room.current_teams is not None or room.match_in_progress
            or room.mvp_vote_in_progress or room.match_transaction_active
            or room.players or room.waiting_players
        ):
            await interaction.response.send_message(
                "❌ 현재 내전방에 참가자나 진행 중인 경기가 있습니다. 방을 비운 뒤 다시 실행해주세요.",
                ephemeral=True
            )
            return
        red = {position: str(fixture[f"red_{key}"]) for position, key in zip(POSITIONS, ("top", "jungle", "mid", "adc", "support"))}
        blue = {position: str(fixture[f"blue_{key}"]) for position, key in zip(POSITIONS, ("top", "jungle", "mid", "adc", "support"))}
        all_ids = list(red.values()) + list(blue.values())
        if len(set(all_ids)) != 10:
            await interaction.response.send_message("❌ 두 팀 로스터에 중복 참가자가 있습니다. 등록 정보를 확인해주세요.", ephemeral=True)
            return
        profiles = {user_id: get_player(user_id) for user_id in all_ids}
        if any(profile is None for profile in profiles.values()):
            await interaction.response.send_message("❌ 로스터 참가자의 프로필을 찾지 못했습니다. 팀 등록을 확인해주세요.", ephemeral=True)
            return
        async with room.operation_lock:
            if room.current_teams is not None or room.players or room.waiting_players or room.match_in_progress:
                await interaction.response.send_message("❌ 방 상태가 바뀌었습니다. 다시 시도해주세요.", ephemeral=True)
                return
            if not claim_fixture(대회번호, fixture_no):
                await interaction.response.send_message(
                    "❌ 다른 진행자가 이미 이 대진을 경기방에 불러왔습니다.",
                    ephemeral=True
                )
                return
            join_cog.activate_room(room)
            room.players = {
                user_id: {"nickname": profile["discord_nickname"] or "참가자"}
                for user_id, profile in profiles.items()
            }
            room.current_teams = {"red": red, "blue": blue}
            room.current_balance_prediction = None
            room.series_score = {"red": 0, "blue": 0}
            room.series_game = 0
            room.tournament_id = int(대회번호)
            room.tournament_fixture_no = fixture_no
            room.last_team_signature = None
            join_cog.save_rooms_state()

        embed = discord.Embed(
            title=f"🏆 {tournament['name']} · 경기 {fixture_no}",
            description=(
                f"**{fixture['red_team_name']}** vs **{fixture['blue_team_name']}**\n"
                "준결승은 1·2번 경기, 결승은 3번 경기입니다.\n"
                "기존 내전 버튼으로 BO5 경기를 진행하면 최종 승리팀이 대진표에 자동 반영됩니다."
            )
        )
        for side, title in (("red", "🔴 레드팀"), ("blue", "🔵 블루팀")):
            rows = [f"**{position}** — <@{fixture[f'{side}_{key}']}>" for position, key in zip(POSITIONS, ("top", "jungle", "mid", "adc", "support"))]
            embed.add_field(name=title, value="\n".join(rows), inline=True)
        add_match_button_instructions(embed)
        message, _ = await join_cog.send_output_message(
            room=room,
            fallback_channel=interaction.channel,
            embed=embed,
            view=MatchControlView(join_cog)
        )
        link = f"\n대진표: {SITE_BASE_URL}/tournament/{대회번호}"
        if message is None:
            async with room.operation_lock:
                room.players.clear()
                room.current_teams = None
                room.current_balance_prediction = None
                room.series_score = {"red": 0, "blue": 0}
                room.series_game = 0
                room.tournament_id = None
                room.tournament_fixture_no = None
                join_cog.save_rooms_state()
            release_fixture(대회번호, fixture_no)
            await interaction.response.send_message(
                "❌ 진행 메시지를 보낼 수 없어 경기방 설정을 되돌렸습니다. "
                "꼬붕봇의 채널 보기·메시지 보내기 권한을 확인한 뒤 다시 실행해주세요."
                + link,
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"✅ **{fixture['red_team_name']} vs {fixture['blue_team_name']}** 경기를 방에 불러왔습니다."
                + link,
                ephemeral=True
            )

    @staticmethod
    def _bracket_text(tournament_id, name, fixtures):
        lines = [f"🏆 **{name}** 대진표 (대회 번호 `{tournament_id}`)"]
        for fixture in fixtures:
            if int(fixture["fixture_no"]) == 3:
                title = "결승"
            else:
                title = f"{fixture['fixture_no']}번 준결승"
            red = fixture["red_team_name"] or "진출 팀 대기"
            blue = fixture["blue_team_name"] or "진출 팀 대기"
            state = {
                "waiting": "대기",
                "ready": "경기 가능",
                "in_progress": "진행 중",
                "completed": "완료"
            }.get(fixture["status"], fixture["status"])
            winner = f" · 승자 **{fixture['winner_team_name']}**" if fixture["winner_team_name"] else ""
            lines.append(f"**{title}** · {state}\n{red} vs {blue}{winner}")
        lines.append(f"웹 대진표: {SITE_BASE_URL}/tournament/{tournament_id}")
        return "\n\n".join(lines)


async def setup(bot):
    await bot.add_cog(Tournament(bot))
