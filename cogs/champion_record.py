import asyncio
import logging
from typing import Literal

import discord
from discord.ext import commands

from services.champion_service import ChampionService
from storage.sqlite_db import (
    get_match_champion_progress,
    get_match_champion_status,
    get_match_player_for_champion,
    get_match_team_players,
    get_player_champion_suggestions,
    save_match_player_champion,
    save_match_team_champions
)
from utils.permissions import (
    is_match_operator,
    send_match_operator_only_message
)


TEAM_LABELS = {
    "레드": "red",
    "블루": "blue"
}

logger = logging.getLogger(__name__)


async def resolve_champion_or_reply(interaction, raw_name):
    try:
        champion = await asyncio.to_thread(
            ChampionService.resolve,
            raw_name
        )
    except Exception:
        await interaction.followup.send(
            "❌ Riot 챔피언 목록을 불러오지 못했습니다. "
            "잠시 후 다시 시도해주세요.",
            ephemeral=True
        )
        return None

    if champion is None:
        await interaction.followup.send(
            f"❌ `{raw_name}` 챔피언을 찾지 못했습니다.\n"
            "한글 정식 이름 또는 영문 이름으로 입력해주세요.",
            ephemeral=True
        )
        return None

    return champion


async def save_self_champion_and_reply(
    interaction,
    match_id,
    champion,
    source_message=None,
    source_view=None
):
    try:
        progress = save_match_player_champion(
            match_id,
            interaction.user.id,
            champion
        )
    except (TypeError, ValueError) as error:
        await interaction.followup.send(
            f"❌ 저장할 수 없습니다: {error}",
            ephemeral=True
        )
        return None
    except Exception as error:
        logger.exception(
            "개인 챔피언 기록 저장 실패 | 경기=%s | 사용자=%s",
            match_id,
            interaction.user.id
        )
        await interaction.followup.send(
            "❌ 챔피언 기록 저장 중 오류가 발생했습니다.\n"
            f"오류 종류: `{type(error).__name__}`\n"
            f"오류 내용: `{str(error)[:180]}`",
            ephemeral=True
        )
        return None

    action = "수정" if progress["updated"] else "등록"
    completed = progress["completed_count"]
    total = progress["total_count"]
    await interaction.followup.send(
        f"✅ **{champion['champion_name']}**으로 {action}했습니다.\n"
        f"현재 입력 현황: **{completed}/{total}명**",
        ephemeral=True
    )

    if total > 0 and completed >= total and not progress["updated"]:
        if source_message is not None and source_view is not None:
            for item in source_view.children:
                item.disabled = True

            try:
                await source_message.edit(view=source_view)
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("챔피언 입력 완료 버튼 비활성화 실패 | 경기=%s", match_id)

        try:
            await interaction.channel.send(
                f"✅ **{match_id}번 경기** 참가자 {total}명의 "
                "챔피언 기록이 모두 완료되었습니다."
            )
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("챔피언 입력 완료 안내 전송 실패 | 경기=%s", match_id)

    return progress


class SelfChampionRecordModal(discord.ui.Modal):

    def __init__(self, match_id, player, source_message=None, source_view=None):
        super().__init__(title=f"{match_id}번 경기 · 내 챔피언")
        self.match_id = int(match_id)
        self.player = player
        self.source_message = source_message
        self.source_view = source_view
        self.champion = discord.ui.TextInput(
            label=(
                f"{str(player.get('team') or '').upper()} · "
                f"{str(player.get('position') or '미정').upper()}"
            ),
            placeholder="내가 사용한 챔피언 이름",
            required=True,
            max_length=30
        )
        self.add_item(self.champion)

    async def on_submit(self, interaction):
        if str(interaction.user.id) != str(self.player["discord_id"]):
            await interaction.response.send_message(
                "❌ 자신의 챔피언만 등록할 수 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        raw_name = str(self.champion.value).strip()
        champion = await resolve_champion_or_reply(interaction, raw_name)

        if champion is None:
            return

        await save_self_champion_and_reply(
            interaction,
            self.match_id,
            champion,
            self.source_message,
            self.source_view
        )


class QuickChampionSelect(discord.ui.Select):

    def __init__(self, parent_view, suggestions):
        self.parent_view = parent_view
        self.champions = {
            str(record["champion_key"]): record
            for record in suggestions
        }
        options = []

        for record in suggestions:
            reason = record.get("reason") or "최근"
            games = int(record.get("games") or 0)
            options.append(
                discord.SelectOption(
                    label=str(record["champion_name"])[:100],
                    value=str(record["champion_key"]),
                    description=f"{reason} · {games}회 사용"[:100]
                )
            )

        super().__init__(
            placeholder="최근·모스트 챔피언에서 선택",
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )

    async def callback(self, interaction):
        if str(interaction.user.id) != str(self.parent_view.player["discord_id"]):
            await interaction.response.send_message(
                "❌ 자신의 챔피언만 등록할 수 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        champion = self.champions[self.values[0]]
        await save_self_champion_and_reply(
            interaction,
            self.parent_view.match_id,
            champion,
            self.parent_view.source_message,
            self.parent_view.source_view
        )
        self.parent_view.stop()


class QuickChampionChoiceView(discord.ui.View):

    def __init__(
        self,
        match_id,
        player,
        suggestions,
        source_message=None,
        source_view=None
    ):
        super().__init__(timeout=5 * 60)
        self.match_id = int(match_id)
        self.player = player
        self.source_message = source_message
        self.source_view = source_view
        self.add_item(QuickChampionSelect(self, suggestions))

    @discord.ui.button(
        label="목록에 없음 · 직접 입력",
        emoji="⌨️",
        style=discord.ButtonStyle.secondary,
        row=1
    )
    async def open_manual_modal(self, interaction, button):
        if str(interaction.user.id) != str(self.player["discord_id"]):
            await interaction.response.send_message(
                "❌ 자신의 챔피언만 등록할 수 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            SelfChampionRecordModal(
                self.match_id,
                self.player,
                self.source_message,
                self.source_view
            )
        )


def get_both_team_players(match_id):
    red_players = get_match_team_players(match_id, "red")
    blue_players = get_match_team_players(match_id, "blue")

    if len(red_players) != 5 or len(blue_players) != 5:
        return None

    return red_players, blue_players


class CombinedChampionRecordModal(discord.ui.Modal):

    def __init__(self, match_id, red_players, blue_players):
        super().__init__(title=f"{match_id}번 경기 · 양 팀 챔피언")
        self.match_id = int(match_id)
        self.red_players = red_players
        self.blue_players = blue_players
        self.champion_inputs = []

        for red_player, blue_player in zip(red_players, blue_players):
            position = str(red_player.get("position") or "미정").upper()
            red_name = str(
                red_player.get("discord_nickname")
                or red_player.get("riot_name")
                or red_player["discord_id"]
            )
            blue_name = str(
                blue_player.get("discord_nickname")
                or blue_player.get("riot_name")
                or blue_player["discord_id"]
            )
            field = discord.ui.TextInput(
                label=f"{position} · {red_name[:12]} ↔ {blue_name[:12]}",
                placeholder="레드 챔피언 / 블루 챔피언",
                required=True,
                max_length=65
            )
            self.champion_inputs.append(field)
            self.add_item(field)

    async def on_submit(self, interaction):
        if not is_match_operator(interaction):
            await send_match_operator_only_message(interaction)
            return

        await interaction.response.defer(ephemeral=True)
        parsed_pairs = []

        for field in self.champion_inputs:
            red_name, separator, blue_name = str(field.value).partition("/")

            if not separator or not red_name.strip() or not blue_name.strip():
                await interaction.followup.send(
                    "❌ 모든 칸을 `레드 챔피언 / 블루 챔피언` "
                    "형식으로 입력해주세요.\n예: `나서스 / 레넥톤`",
                    ephemeral=True
                )
                return

            parsed_pairs.append((red_name.strip(), blue_name.strip()))

        raw_names = [
            name
            for pair in parsed_pairs
            for name in pair
        ]

        try:
            resolved = await asyncio.to_thread(
                lambda: [ChampionService.resolve(name) for name in raw_names]
            )
        except Exception:
            await interaction.followup.send(
                "❌ Riot 챔피언 목록을 불러오지 못했습니다. "
                "잠시 후 다시 시도해주세요.",
                ephemeral=True
            )
            return

        invalid_names = [
            raw_name
            for raw_name, champion in zip(raw_names, resolved)
            if champion is None
        ]

        if invalid_names:
            await interaction.followup.send(
                "❌ 다음 챔피언 이름을 확인해주세요: "
                + ", ".join(f"`{name}`" for name in invalid_names),
                ephemeral=True
            )
            return

        red_records = []
        blue_records = []
        result_lines = []

        for index, (red_player, blue_player) in enumerate(
            zip(self.red_players, self.blue_players)
        ):
            red_champion = resolved[index * 2]
            blue_champion = resolved[index * 2 + 1]
            red_record = dict(red_champion)
            red_record["discord_id"] = str(red_player["discord_id"])
            blue_record = dict(blue_champion)
            blue_record["discord_id"] = str(blue_player["discord_id"])
            red_records.append(red_record)
            blue_records.append(blue_record)
            result_lines.append(
                f"• **{red_player.get('position') or '미정'}** "
                f"{red_champion['champion_name']} / "
                f"{blue_champion['champion_name']}"
            )

        try:
            save_match_team_champions(self.match_id, "red", red_records)
            save_match_team_champions(self.match_id, "blue", blue_records)
        except (TypeError, ValueError) as error:
            await interaction.followup.send(
                f"❌ 저장할 수 없습니다: {error}",
                ephemeral=True
            )
            return
        except Exception as error:
            logger.exception(
                "양 팀 챔피언 기록 저장 실패 | 경기=%s",
                self.match_id
            )
            await interaction.followup.send(
                "❌ 챔피언 기록 저장 중 오류가 발생했습니다.\n"
                f"오류 종류: `{type(error).__name__}`\n"
                f"오류 내용: `{str(error)[:180]}`",
                ephemeral=True
            )
            return

        await interaction.followup.send(
            f"✅ **{self.match_id}번 경기 · 양 팀 10명**의 "
            "챔피언 기록을 저장했습니다.\n"
            + "\n".join(result_lines),
            ephemeral=True
        )


class ChampionRecordView(discord.ui.View):

    def __init__(self, match_id):
        super().__init__(timeout=24 * 60 * 60)
        self.match_id = int(match_id)

    @discord.ui.button(
        label="내 챔피언 입력",
        emoji="✅",
        style=discord.ButtonStyle.success
    )
    async def open_self_record_modal(self, interaction, button):
        player = get_match_player_for_champion(
            self.match_id,
            interaction.user.id
        )

        if player is None:
            await interaction.response.send_message(
                "❌ 이 경기의 참가자만 자신의 챔피언을 입력할 수 있습니다.",
                ephemeral=True
            )
            return

        suggestions = get_player_champion_suggestions(
            interaction.user.id,
            self.match_id
        )

        if not suggestions:
            await interaction.response.send_modal(
                SelfChampionRecordModal(
                    self.match_id,
                    player,
                    interaction.message,
                    self
                )
            )
            return

        await interaction.response.send_message(
            "🎭 사용한 챔피언을 선택하세요.\n"
            "목록에 없다면 `직접 입력`을 눌러주세요.",
            view=QuickChampionChoiceView(
                self.match_id,
                player,
                suggestions,
                interaction.message,
                self
            ),
            ephemeral=True
        )

    @discord.ui.button(
        label="관리자 일괄 입력",
        emoji="🎭",
        style=discord.ButtonStyle.primary
    )
    async def open_record_modal(self, interaction, button):
        if not is_match_operator(interaction):
            await send_match_operator_only_message(interaction)
            return

        teams = get_both_team_players(self.match_id)

        if teams is None:
            await interaction.response.send_message(
                "❌ 해당 경기에서 양 팀 선수 10명을 찾지 못했습니다.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            CombinedChampionRecordModal(
                self.match_id,
                teams[0],
                teams[1]
            )
        )

    @discord.ui.button(
        label="입력 현황",
        emoji="📋",
        style=discord.ButtonStyle.secondary
    )
    async def show_record_status(self, interaction, button):
        if not is_match_operator(interaction):
            await send_match_operator_only_message(interaction)
            return

        rows = get_match_champion_status(self.match_id)

        if not rows:
            await interaction.response.send_message(
                "❌ 해당 경기 참가자 정보를 찾지 못했습니다.",
                ephemeral=True
            )
            return

        lines = []

        for row in rows:
            mark = "✅" if row["champion_name"] else "❌"
            champion = row["champion_name"] or "미입력"
            lines.append(
                f"{mark} **{str(row['team']).upper()} "
                f"{row['position'] or '미정'}** · "
                f"<@{row['discord_id']}> — {champion}"
            )

        completed = sum(1 for row in rows if row["champion_name"])
        await interaction.response.send_message(
            f"📋 **{self.match_id}번 경기 입력 현황 "
            f"({completed}/{len(rows)}명)**\n" + "\n".join(lines),
            ephemeral=True
        )


class ChampionRecordModal(discord.ui.Modal):

    def __init__(self, match_id, team, players):
        team_label = "레드" if team == "red" else "블루"
        super().__init__(
            title=f"{match_id}번 경기 · {team_label}팀 챔피언"
        )
        self.match_id = int(match_id)
        self.team = team
        self.players = players
        self.champion_inputs = []

        for player in players:
            position = str(player.get("position") or "미정").upper()
            nickname = (
                player.get("discord_nickname")
                or player.get("riot_name")
                or player["discord_id"]
            )
            field = discord.ui.TextInput(
                label=f"{position} · {str(nickname)[:28]}",
                placeholder="한글 또는 영문 챔피언 이름",
                required=True,
                max_length=30
            )
            self.champion_inputs.append(field)
            self.add_item(field)

    async def on_submit(self, interaction):
        if not is_match_operator(interaction):
            await send_match_operator_only_message(interaction)
            return

        await interaction.response.defer(ephemeral=True)
        raw_names = [str(field.value) for field in self.champion_inputs]

        try:
            resolved = await asyncio.to_thread(
                lambda: [
                    ChampionService.resolve(name)
                    for name in raw_names
                ]
            )
        except Exception:
            await interaction.followup.send(
                "❌ Riot 챔피언 목록을 불러오지 못했습니다. "
                "잠시 후 다시 시도해주세요.",
                ephemeral=True
            )
            return

        invalid_names = [
            raw_name
            for raw_name, champion in zip(raw_names, resolved)
            if champion is None
        ]

        if invalid_names:
            await interaction.followup.send(
                "❌ 다음 챔피언 이름을 확인해주세요: "
                + ", ".join(f"`{name}`" for name in invalid_names)
                + "\n한글 정식 이름 또는 영문 이름으로 입력해주세요.",
                ephemeral=True
            )
            return

        records = []
        result_lines = []

        for player, champion in zip(self.players, resolved):
            record = dict(champion)
            record["discord_id"] = str(player["discord_id"])
            records.append(record)
            nickname = (
                player.get("discord_nickname")
                or player.get("riot_name")
                or player["discord_id"]
            )
            result_lines.append(
                f"• **{player.get('position') or '미정'}** "
                f"{nickname}: {champion['champion_name']}"
            )

        try:
            save_match_team_champions(
                self.match_id,
                self.team,
                records
            )
        except (TypeError, ValueError) as error:
            await interaction.followup.send(
                f"❌ 저장할 수 없습니다: {error}",
                ephemeral=True
            )
            return
        except Exception as error:
            logger.exception(
                "챔피언 기록 저장 실패 | 경기=%s | 팀=%s",
                self.match_id,
                self.team
            )
            await interaction.followup.send(
                "❌ 챔피언 기록 저장 중 오류가 발생했습니다.\n"
                f"오류 종류: `{type(error).__name__}`\n"
                f"오류 내용: `{str(error)[:180]}`",
                ephemeral=True
            )
            return

        team_label = "레드팀" if self.team == "red" else "블루팀"
        await interaction.followup.send(
            f"✅ **{self.match_id}번 경기 · {team_label}** "
            "챔피언 기록을 저장했습니다.\n"
            + "\n".join(result_lines),
            ephemeral=True
        )


class ChampionRecord(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(
        name="내챔피언",
        description="완료된 내전에서 자신이 사용한 챔피언을 등록합니다."
    )
    async def my_champion(
        self,
        interaction: discord.Interaction,
        경기번호: int,
        챔피언: str
    ):
        player = get_match_player_for_champion(
            경기번호,
            interaction.user.id
        )

        if player is None:
            await interaction.response.send_message(
                "❌ 해당 경기의 참가자만 등록할 수 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        resolved = await resolve_champion_or_reply(interaction, 챔피언)

        if resolved is None:
            return

        try:
            progress = save_match_player_champion(
                경기번호,
                interaction.user.id,
                resolved
            )
        except Exception as error:
            logger.exception(
                "개인 챔피언 명령 저장 실패 | 경기=%s | 사용자=%s",
                경기번호,
                interaction.user.id
            )
            await interaction.followup.send(
                "❌ 저장 중 오류가 발생했습니다.\n"
                f"오류 내용: `{str(error)[:180]}`",
                ephemeral=True
            )
            return

        await interaction.followup.send(
            f"✅ **{resolved['champion_name']}**으로 저장했습니다.\n"
            f"현재 입력 현황: **{progress['completed_count']}/"
            f"{progress['total_count']}명**",
            ephemeral=True
        )

    @discord.app_commands.command(
        name="챔피언기록",
        description="완료된 내전의 양 팀 챔피언 10명을 한 번에 기록합니다."
    )
    async def champion_record(
        self,
        interaction: discord.Interaction,
        경기번호: int,
        팀: Literal["레드", "블루"] | None = None
    ):
        if not is_match_operator(interaction):
            await send_match_operator_only_message(interaction)
            return

        if 팀 is None:
            teams = get_both_team_players(경기번호)

            if teams is None:
                await interaction.response.send_message(
                    "❌ 해당 경기 번호에서 양 팀 선수 10명을 "
                    "찾지 못했습니다.",
                    ephemeral=True
                )
                return

            await interaction.response.send_modal(
                CombinedChampionRecordModal(
                    경기번호,
                    teams[0],
                    teams[1]
                )
            )
            return

        team = TEAM_LABELS[팀]
        players = get_match_team_players(
            경기번호,
            team
        )

        if len(players) != 5:
            await interaction.response.send_message(
                "❌ 해당 경기 번호와 팀에서 선수 5명을 찾지 못했습니다.\n"
                "꼬붕.GG 경기 기록의 경기 번호를 확인해주세요.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            ChampionRecordModal(
                match_id=경기번호,
                team=team,
                players=players
            )
        )


async def setup(bot):
    await bot.add_cog(ChampionRecord(bot))
