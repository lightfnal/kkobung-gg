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
    finalize_pending_position_ratings,
    save_match_player_champion,
    save_match_team_champions
)
from utils.permissions import (
    is_match_operator,
    send_match_operator_only_message
)


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


async def finish_champion_entry_ui(
    interaction,
    match_id,
    source_message=None,
    source_view=None
):
    """완료 안내 후 BO3 다음 세트 조작창을 다시 채널 하단에 올립니다."""
    progress = get_match_champion_progress(match_id)
    total = int(progress.get("total_count") or 0)
    completed = int(progress.get("completed_count") or 0)
    if total == 0 or completed < total:
        return False

    if source_message is not None and source_view is not None:
        for item in source_view.children:
            if item is not source_view.reopen_result_button:
                item.disabled = True
        try:
            await source_message.edit(view=source_view)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            logger.info("챔피언 입력 완료 버튼 갱신 실패 | 경기=%s", match_id)

    try:
        await interaction.channel.send(
            f"✅ **{match_id}번 경기** 참가자 {total}명의 "
            "챔피언 기록이 모두 완료되었습니다."
        )
    except (discord.Forbidden, discord.HTTPException):
        logger.warning("챔피언 입력 완료 안내 전송 실패 | 경기=%s", match_id)

    if (
        source_view is not None
        and source_view.control_message is not None
        and source_view.control_message_view is not None
        and source_view.join_cog is not None
        and source_view.room is not None
    ):
        from views.join_view import refresh_match_controls_at_bottom

        message, view = await refresh_match_controls_at_bottom(
            source_view.join_cog,
            source_view.room,
            source_view.control_message,
            source_view.control_message_view,
            stage="next_set"
        )
        source_view.control_message = message
        source_view.control_message_view = view

    return True


async def save_self_champion_and_reply(
    interaction,
    match_id,
    champion,
    source_message=None,
    source_view=None,
    actual_position=None
):
    try:
        progress = save_match_player_champion(
            match_id,
            interaction.user.id,
            champion,
            actual_position=actual_position
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
        await finish_champion_entry_ui(
            interaction,
            match_id,
            source_message,
            source_view
        )

    return progress


class SelfChampionRecordModal(discord.ui.Modal):

    def __init__(
        self,
        match_id,
        player,
        actual_position,
        source_message=None,
        source_view=None
    ):
        super().__init__(title=f"{match_id}번 경기 · 챔피언 직접 입력")
        self.match_id = int(match_id)
        self.player = player
        self.actual_position = actual_position
        self.source_message = source_message
        self.source_view = source_view
        self.champion = discord.ui.TextInput(
            label=f"실제 {actual_position} 포지션 · 챔피언 이름",
            placeholder="예: 아리",
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

        await interaction.response.defer(ephemeral=True, thinking=True)
        raw_name = str(self.champion.value).strip()
        champion = await resolve_champion_or_reply(interaction, raw_name)

        if champion is None:
            return

        await save_self_champion_and_reply(
            interaction,
            self.match_id,
            champion,
            self.source_message,
            self.source_view,
            self.actual_position
        )


class ActualPositionSelect(discord.ui.Select):

    def __init__(self, parent_view):
        self.parent_view = parent_view
        position_labels = {
            "TOP": "TOP (탑)",
            "JUNGLE": "JUNGLE (정글)",
            "MID": "MID (미드)",
            "ADC": "ADC (원딜)",
            "SUPPORT": "SUPPORT (서폿)"
        }
        options = [
            discord.SelectOption(
                label=position_labels[position],
                value=position,
            )
            for position in ("TOP", "JUNGLE", "MID", "ADC", "SUPPORT")
        ]
        super().__init__(
            placeholder="1단계 · 실제 플레이 라인을 먼저 선택",
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )

    async def callback(self, interaction):
        if str(interaction.user.id) != str(self.parent_view.player["discord_id"]):
            await interaction.response.send_message(
                "❌ 자신의 실제 포지션만 선택할 수 있습니다.",
                ephemeral=True
            )
            return
        self.parent_view.actual_position = self.values[0]
        self.placeholder = f"실제 플레이 라인: {self.values[0]} · 눌러서 변경"
        self.parent_view.enable_champion_choices()
        await interaction.response.edit_message(
            content=(
                f"✅ 실제 플레이 라인: **{self.values[0]}**\n"
                "2단계: 아래 챔피언 목록에서 고르거나 초록색 직접 입력 버튼을 누르세요."
            ),
            view=self.parent_view
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
            placeholder="2단계 · 추천 챔피언에서 선택",
            min_values=1,
            max_values=1,
            options=options,
            row=2
        )

    async def callback(self, interaction):
        if str(interaction.user.id) != str(self.parent_view.player["discord_id"]):
            await interaction.response.send_message(
                "❌ 자신의 챔피언만 등록할 수 있습니다.",
                ephemeral=True
            )
            return

        if self.parent_view.actual_position is None:
            await interaction.response.send_message(
                "먼저 실제로 플레이한 라인을 선택해주세요.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        champion = self.champions[self.values[0]]
        await save_self_champion_and_reply(
            interaction,
            self.parent_view.match_id,
            champion,
            self.parent_view.source_message,
            self.parent_view.source_view,
            self.parent_view.actual_position
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
        self.actual_position = None
        self.position_select = ActualPositionSelect(self)
        self.add_item(self.position_select)
        self.champion_select = None
        if suggestions:
            self.champion_select = QuickChampionSelect(self, suggestions)
            self.champion_select.disabled = True
            self.add_item(self.champion_select)
        self.open_manual_modal.disabled = True

    def enable_champion_choices(self):
        if self.champion_select is not None:
            self.champion_select.disabled = False
        self.open_manual_modal.disabled = False

    @discord.ui.button(
        label="챔피언 직접 입력 (목록에 없는 경우)",
        emoji="⌨️",
        style=discord.ButtonStyle.success,
        row=1
    )
    async def open_manual_modal(self, interaction, button):
        if str(interaction.user.id) != str(self.player["discord_id"]):
            await interaction.response.send_message(
                "❌ 자신의 챔피언만 등록할 수 있습니다.",
                ephemeral=True
            )
            return

        if self.actual_position is None:
            await interaction.response.send_message(
                "먼저 위에서 **실제 플레이 라인**을 선택해주세요. "
                "라인을 선택하면 이 버튼이 활성화됩니다.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            SelfChampionRecordModal(
                self.match_id,
                self.player,
                self.actual_position,
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

    def __init__(
        self,
        match_id,
        red_players,
        blue_players,
        champion_record_view=None
    ):
        super().__init__(title=f"{match_id}번 경기 · 양 팀 챔피언")
        self.match_id = int(match_id)
        self.red_players = red_players
        self.blue_players = blue_players
        self.champion_record_view = champion_record_view
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
                label=f"배정 {position} · {red_name[:12]} ↔ {blue_name[:12]}",
                placeholder="레드챔피언@실제포지션 / 블루챔피언",
                required=True,
                max_length=80
            )
            self.champion_inputs.append(field)
            self.add_item(field)

    async def on_submit(self, interaction):
        participant = get_match_player_for_champion(
            self.match_id,
            interaction.user.id
        )
        if not is_match_operator(interaction) and participant is None:
            await interaction.response.send_message(
                "❌ 이 경기 참가자 또는 내전 진행자만 챔피언 기록을 입력할 수 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        parsed_pairs = []

        for field in self.champion_inputs:
            red_name, separator, blue_name = str(field.value).partition("/")

            if not separator or not red_name.strip() or not blue_name.strip():
                await interaction.followup.send(
                    "❌ 모든 칸을 `레드 챔피언 / 블루 챔피언` "
                    "형식으로 입력해주세요. 실제 포지션을 바꿔 뛴 선수는 "
                    "`챔피언@포지션`으로 적으세요.\n"
                    "예: `레넥톤@TOP / 케이틀린@ADC`",
                    ephemeral=True
                )
                return

            def parse_champion_and_position(value):
                value = value.strip()
                if "@" not in value:
                    return value, None

                champion_name, actual_position = value.rsplit("@", 1)
                aliases = {
                    "탑": "TOP", "정글": "JUNGLE", "미드": "MID",
                    "원딜": "ADC", "바텀": "ADC", "서폿": "SUPPORT",
                    "서포터": "SUPPORT"
                }
                actual_position = actual_position.strip().upper()
                actual_position = aliases.get(actual_position.lower(), actual_position)
                valid_positions = {"TOP", "JUNGLE", "MID", "ADC", "SUPPORT"}
                if actual_position not in valid_positions or not champion_name.strip():
                    return None, None
                return champion_name.strip(), actual_position

            red_entry = parse_champion_and_position(red_name)
            blue_entry = parse_champion_and_position(blue_name)
            if red_entry[0] is None or blue_entry[0] is None:
                await interaction.followup.send(
                    "❌ 실제 포지션을 확인해주세요. "
                    "TOP/JUNGLE/MID/ADC/SUPPORT 또는 탑/정글/미드/원딜/서폿을 입력하세요.",
                    ephemeral=True
                )
                return

            parsed_pairs.append((red_entry, blue_entry))

        raw_names = [
            entry[0]
            for pair in parsed_pairs
            for entry in pair
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
            red_entry, blue_entry = parsed_pairs[index]
            red_actual_position = red_entry[1] or str(
                red_player.get("position") or ""
            ).upper()
            blue_actual_position = blue_entry[1] or str(
                blue_player.get("position") or ""
            ).upper()
            red_record["actual_position"] = red_actual_position
            blue_record = dict(blue_champion)
            blue_record["discord_id"] = str(blue_player["discord_id"])
            blue_record["actual_position"] = blue_actual_position
            red_records.append(red_record)
            blue_records.append(blue_record)
            red_label_position = str(red_player.get("position") or "미정").upper()
            red_display_name = (
                red_player.get("discord_nickname")
                or red_player.get("riot_name")
                or red_player["discord_id"]
            )
            blue_display_name = (
                blue_player.get("discord_nickname")
                or blue_player.get("riot_name")
                or blue_player["discord_id"]
            )
            result_lines.append(
                f"• 배정 {red_label_position}: "
                f"{red_display_name} — {red_champion['champion_name']} "
                f"({red_actual_position}) / {blue_display_name} — "
                f"{blue_champion['champion_name']} ({blue_actual_position})"
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

        if participant is not None:
            try:
                await interaction.channel.send(
                    f"✅ <@{interaction.user.id}>님이 **{self.match_id}번 경기** "
                    "양 팀 챔피언 기록을 한 번에 입력했습니다."
                )
            except (discord.Forbidden, discord.HTTPException):
                logger.info(
                    "전체 챔피언 입력 완료 알림 전송 실패 | 경기=%s",
                    self.match_id
                )

        if self.champion_record_view is not None:
            await finish_champion_entry_ui(
                interaction,
                self.match_id,
                self.champion_record_view.result_message,
                self.champion_record_view
            )


class MissingChampionRecordModal(discord.ui.Modal):

    def __init__(
        self,
        match_id,
        missing_players,
        source_view=None,
        source_message=None
    ):
        super().__init__(title=f"{match_id}번 경기 · 미입력자 챔피언")
        self.match_id = int(match_id)
        self.source_view = source_view
        self.source_message = source_message
        # Discord 모달은 최대 5개 입력 항목을 허용합니다. 남은 인원이
        # 더 많으면 저장 후 다시 열어 다음 인원을 입력할 수 있습니다.
        self.players = missing_players[:5]
        self.champion_inputs = []

        for player in self.players:
            display_name = str(
                player.get("discord_nickname")
                or player.get("riot_name")
                or player["discord_id"]
            )
            team = str(player.get("team") or "?").upper()
            position = str(player.get("position") or "미정").upper()
            field = discord.ui.TextInput(
                label=f"{team} {position} · {display_name}"[:45],
                placeholder="챔피언명 (필요하면 @실제포지션)",
                required=True,
                max_length=80
            )
            self.champion_inputs.append(field)
            self.add_item(field)

    async def on_submit(self, interaction):
        if (
            not is_match_operator(interaction)
            and get_match_player_for_champion(
                self.match_id,
                interaction.user.id
            ) is None
        ):
            await interaction.response.send_message(
                "❌ 이 경기 참가자만 미입력자의 챔피언을 입력할 수 있습니다.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        entries = []

        for player, field in zip(self.players, self.champion_inputs):
            value = str(field.value).strip()
            champion_name, separator, actual_position = value.rpartition("@")
            if separator:
                aliases = {
                    "탑": "TOP", "정글": "JUNGLE", "미드": "MID",
                    "원딜": "ADC", "바텀": "ADC", "서폿": "SUPPORT",
                    "서포터": "SUPPORT"
                }
                actual_position = actual_position.strip().upper()
                actual_position = aliases.get(
                    actual_position.lower(), actual_position
                )
                if actual_position not in {
                    "TOP", "JUNGLE", "MID", "ADC", "SUPPORT"
                } or not champion_name.strip():
                    await interaction.followup.send(
                        "❌ 실제 포지션은 TOP/JUNGLE/MID/ADC/SUPPORT 또는 "
                        "탑/정글/미드/원딜/서폿으로 입력해주세요.",
                        ephemeral=True
                    )
                    return
                champion_name = champion_name.strip()
            else:
                champion_name = value
                actual_position = str(player.get("position") or "").upper()

            entries.append((player, champion_name, actual_position))

        try:
            resolved = await asyncio.to_thread(
                lambda: [
                    ChampionService.resolve(champion_name)
                    for _, champion_name, _ in entries
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
            champion_name
            for (_, champion_name, _), champion in zip(entries, resolved)
            if champion is None
        ]
        if invalid_names:
            await interaction.followup.send(
                "❌ 다음 챔피언 이름을 확인해주세요: "
                + ", ".join(f"`{name}`" for name in invalid_names),
                ephemeral=True
            )
            return

        # 모달을 연 뒤 참가자가 먼저 입력했을 수 있으므로 최신 상태를
        # 확인해 이미 등록된 선수 기록은 덮어쓰지 않습니다.
        latest_by_id = {
            str(row["discord_id"]): row
            for row in get_match_champion_status(self.match_id)
        }
        saved_lines = []
        skipped_names = []

        for (player, _, actual_position), champion in zip(entries, resolved):
            discord_id = str(player["discord_id"])
            latest = latest_by_id.get(discord_id)
            if latest is None or latest.get("champion_name"):
                skipped_names.append(
                    player.get("discord_nickname") or discord_id
                )
                continue

            try:
                progress = save_match_player_champion(
                    self.match_id,
                    discord_id,
                    champion,
                    actual_position=actual_position
                )
            except (TypeError, ValueError) as error:
                await interaction.followup.send(
                    f"❌ {player.get('discord_nickname') or discord_id} 저장 실패: "
                    f"{error}",
                    ephemeral=True
                )
                return
            except Exception as error:
                logger.exception(
                    "미입력자 챔피언 기록 저장 실패 | 경기=%s | 사용자=%s",
                    self.match_id,
                    discord_id
                )
                await interaction.followup.send(
                    "❌ 챔피언 기록 저장 중 오류가 발생했습니다. "
                    f"오류 종류: `{type(error).__name__}`",
                    ephemeral=True
                )
                return

            saved_lines.append(
                f"• **{str(player.get('team') or '?').upper()} "
                f"{player.get('position') or '미정'}** · "
                f"{player.get('discord_nickname') or discord_id} — "
                f"{champion['champion_name']}"
            )

        summary = (
            f"✅ **{self.match_id}번 경기** 미입력자 챔피언을 저장했습니다.\n"
            + ("\n".join(saved_lines) if saved_lines else "저장된 항목이 없습니다.")
        )
        if skipped_names:
            summary += "\n이미 입력되어 건너뜀: " + ", ".join(skipped_names)
        summary += (
            f"\n현재 입력 현황: **{progress['completed_count']}/"
            f"{progress['total_count']}명**"
            if saved_lines else ""
        )
        await interaction.followup.send(summary, ephemeral=True)
        if saved_lines:
            await finish_champion_entry_ui(
                interaction,
                self.match_id,
                self.source_message,
                self.source_view
            )


class CombinedChampionModalLauncherView(discord.ui.View):

    def __init__(
        self,
        match_id,
        red_players,
        blue_players,
        champion_record_view=None
    ):
        super().__init__(timeout=3 * 60)
        self.match_id = int(match_id)
        self.red_players = red_players
        self.blue_players = blue_players
        self.champion_record_view = champion_record_view

    @discord.ui.button(
        label="양 팀 챔피언 입력창 열기",
        emoji="🎭",
        style=discord.ButtonStyle.primary
    )
    async def open_modal(self, interaction, button):
        if not is_match_operator(interaction):
            await send_match_operator_only_message(interaction)
            return

        await interaction.response.send_modal(
            CombinedChampionRecordModal(
                self.match_id,
                self.red_players,
                self.blue_players,
                self.champion_record_view
            )
        )

    @discord.ui.button(
        label="미입력자만 입력 (최대 5명)",
        emoji="📝",
        style=discord.ButtonStyle.secondary
    )
    async def open_missing_modal(self, interaction, button):
        if not is_match_operator(interaction):
            await send_match_operator_only_message(interaction)
            return

        try:
            missing_players = [
                row for row in get_match_champion_status(self.match_id)
                if not row.get("champion_name")
            ]
        except Exception as error:
            logger.exception(
                "미입력자 챔피언 입력 준비 실패 | 경기=%s",
                self.match_id
            )
            await interaction.response.send_message(
                "❌ 입력 현황을 불러오지 못했습니다. "
                f"오류 종류: `{type(error).__name__}`",
                ephemeral=True
            )
            return

        if not missing_players:
            await interaction.response.send_message(
                "✅ 이 경기에는 챔피언 미입력자가 없습니다.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            MissingChampionRecordModal(
                self.match_id,
                missing_players,
                self.champion_record_view,
                (
                    self.champion_record_view.result_message
                    if self.champion_record_view is not None
                    else interaction.message
                )
            )
        )


class ChampionRecordView(discord.ui.View):

    def __init__(self, match_id, room=None, match_control_view=None):
        super().__init__(timeout=24 * 60 * 60)
        self.match_id = int(match_id)
        self.room = room
        self.match_control_view = match_control_view
        self.result_message = None
        self.join_cog = None
        self.control_message = None
        self.control_message_view = None
        self.reopen_result_button.disabled = (
            room is None or match_control_view is None
        )

    async def move_to_bottom(self):
        """현재 챔피언 입력창을 최신 메시지로 옮겨 스크롤을 줄입니다."""
        old_message = self.result_message
        if old_message is None:
            return False

        original_content = old_message.content or None
        original_embeds = [
            discord.Embed.from_dict(embed.to_dict())
            for embed in old_message.embeds
        ]

        try:
            await old_message.edit(
                content="↘️ 최신 챔피언 입력창이 아래에 있습니다.",
                embeds=[],
                view=None
            )
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            logger.info("이전 챔피언 입력창 비활성화 실패 | 경기=%s", self.match_id)

        send_kwargs = {
            "view": self,
            "allowed_mentions": discord.AllowedMentions.none()
        }
        if original_content is not None:
            send_kwargs["content"] = original_content
        if original_embeds:
            send_kwargs["embeds"] = original_embeds

        try:
            new_message = await old_message.channel.send(**send_kwargs)
        except (discord.Forbidden, discord.HTTPException):
            logger.exception("챔피언 입력창을 하단으로 옮기지 못함 | 경기=%s", self.match_id)
            try:
                await old_message.edit(
                    content=original_content,
                    embeds=original_embeds,
                    view=self
                )
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass
            return False

        self.result_message = new_message
        return True

    @discord.ui.button(
        label="내 챔피언 입력",
        emoji="✅",
        style=discord.ButtonStyle.success
    )
    async def open_self_record_modal(self, interaction, button):
        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        player = get_match_player_for_champion(
            self.match_id,
            interaction.user.id
        )

        if player is None:
            await interaction.followup.send(
                "❌ 이 경기의 참가자만 자신의 챔피언을 입력할 수 있습니다.",
                ephemeral=True
            )
            return

        suggestions = get_player_champion_suggestions(
            interaction.user.id,
            self.match_id
        )

        prompt = (
            "🎭 **1단계: 실제로 플레이한 라인을 먼저 선택하세요.**\n"
            "프로필에 등록된 라인이 자동 적용되지 않습니다.\n"
            "라인을 고른 뒤 챔피언 목록을 선택하거나, 초록색 "
            "**챔피언 직접 입력** 버튼을 누르면 됩니다."
        )
        if not suggestions:
            prompt += "\n저장된 추천 챔피언이 없어 직접 입력을 이용해주세요."

        await interaction.followup.send(
            prompt,
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
        label="미입력자 입력 (최대 5명)",
        emoji="📝",
        style=discord.ButtonStyle.primary
    )
    async def open_missing_players_modal(self, interaction, button):
        participant = get_match_player_for_champion(
            self.match_id,
            interaction.user.id
        )
        if participant is None and not is_match_operator(interaction):
            await interaction.response.send_message(
                "❌ 이 경기 참가자만 미입력자의 챔피언을 입력할 수 있습니다.",
                ephemeral=True
            )
            return

        try:
            missing_players = [
                row for row in get_match_champion_status(self.match_id)
                if not row.get("champion_name")
            ]
        except Exception as error:
            logger.exception(
                "미입력자 챔피언 입력 준비 실패 | 경기=%s",
                self.match_id
            )
            await interaction.response.send_message(
                "❌ 입력 현황을 불러오지 못했습니다. "
                f"오류 종류: `{type(error).__name__}`",
                ephemeral=True
            )
            return

        if not missing_players:
            await interaction.response.send_message(
                "✅ 모든 참가자가 챔피언을 입력했습니다.",
                ephemeral=True
            )
            return

        await interaction.response.send_modal(
            MissingChampionRecordModal(
                self.match_id,
                missing_players,
                self,
                self.result_message or interaction.message
            )
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

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )
        teams = get_both_team_players(self.match_id)

        if teams is None:
            await interaction.followup.send(
                "❌ 해당 경기에서 양 팀 선수 10명을 찾지 못했습니다.",
                ephemeral=True
            )
            return

        await interaction.followup.send(
            "관리자 일괄 입력을 준비했습니다. 아래 버튼을 눌러 입력창을 여세요.",
            view=CombinedChampionModalLauncherView(
                self.match_id,
                teams[0],
                teams[1],
                self
            ),
            ephemeral=True
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

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )
        rows = get_match_champion_status(self.match_id)

        if not rows:
            await interaction.followup.send(
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
        await interaction.followup.send(
            f"📋 **{self.match_id}번 경기 입력 현황 "
            f"({completed}/{len(rows)}명)**\n" + "\n".join(lines),
            ephemeral=True
        )

    @discord.ui.button(
        label="잘못 등록했어요 · 승리팀 다시 선택",
        emoji="↩️",
        style=discord.ButtonStyle.danger,
        row=1
    )
    async def reopen_result_button(self, interaction, button):
        if not is_match_operator(interaction):
            await send_match_operator_only_message(interaction)
            return

        if (
            self.room is None
            or self.match_control_view is None
            or self.match_control_view.team_message is None
        ):
            await interaction.response.send_message(
                "❌ 이 경기의 원래 팀 메시지 정보를 찾을 수 없습니다. "
                "현재 방에서 `/경기취소`로 결과를 취소한 뒤 다시 진행해주세요.",
                ephemeral=True
            )
            return

        admin_cog = interaction.client.get_cog("AdminMatch")
        if admin_cog is None:
            await interaction.response.send_message(
                "❌ 경기 관리 기능을 불러오지 못했습니다. 관리자에게 알려주세요.",
                ephemeral=True
            )
            return

        await admin_cog.reopen_match_result(
            interaction,
            self.match_id,
            self.room,
            self.match_control_view,
            self.result_message
        )


class ChampionRecord(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self._position_mmr_recovery_done = False

    @commands.Cog.listener()
    async def on_ready(self):
        if self._position_mmr_recovery_done:
            return
        self._position_mmr_recovery_done = True
        try:
            recovered = finalize_pending_position_ratings()
            if recovered:
                logger.info("미반영 라인별 MMR 복구 완료 | 경기=%s", recovered)
        except Exception:
            logger.exception("미반영 라인별 MMR 복구 실패")

    @discord.app_commands.command(
        name="내챔피언",
        description="완료된 내전에서 자신이 사용한 챔피언을 등록합니다."
    )
    async def my_champion(
        self,
        interaction: discord.Interaction,
        경기번호: int,
        챔피언: str,
        실제포지션: Literal[
            "TOP", "JUNGLE", "MID", "ADC", "SUPPORT"
        ] | None = None
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

        await interaction.response.defer(ephemeral=True, thinking=True)
        resolved = await resolve_champion_or_reply(interaction, 챔피언)

        if resolved is None:
            return

        try:
            progress = save_match_player_champion(
                경기번호,
                interaction.user.id,
                resolved,
                actual_position=실제포지션
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
            f"실제 포지션: **{실제포지션 or player['position']}**\n"
            f"현재 입력 현황: **{progress['completed_count']}/"
            f"{progress['total_count']}명**",
            ephemeral=True
        )

    @discord.app_commands.command(
        name="챔피언기록",
        description="완료된 내전의 양 팀 챔피언을 챔피언 / 챔피언 형식으로 입력합니다."
    )
    async def champion_record(
        self,
        interaction: discord.Interaction,
        경기번호: int
    ):
        if not is_match_operator(interaction):
            await send_match_operator_only_message(interaction)
            return

        await interaction.response.defer(
            ephemeral=True,
            thinking=True
        )

        try:
            # sqlite_db uses a module-level sqlite connection created on this
            # thread. Do not pass its cursor to asyncio.to_thread.
            teams = get_both_team_players(경기번호)
        except Exception as error:
            logger.exception(
                "양 팀 챔피언 입력 준비 실패 | 경기=%s",
                경기번호
            )
            await interaction.followup.send(
                "❌ 참가자 정보를 불러오지 못했습니다.\n"
                f"오류 종류: `{type(error).__name__}`\n"
                f"내용: `{str(error)[:180]}`",
                ephemeral=True
            )
            return

        if teams is None:
            await interaction.followup.send(
                "❌ 해당 경기 번호에서 양 팀 선수 10명을 찾지 못했습니다.\n"
                "꼬붕.GG 경기 기록의 경기 번호를 확인해주세요.",
                ephemeral=True
            )
            return

        await interaction.followup.send(
            "남은 선수만 입력하려면 **미입력자만 입력**을 누르세요. "
            "양 팀 기록을 한 번에 입력하려면 **양 팀 챔피언 입력창 열기**를 누르세요.",
            view=CombinedChampionModalLauncherView(
                경기번호,
                teams[0],
                teams[1]
            ),
            ephemeral=True
        )
    

async def setup(bot):
    await bot.add_cog(ChampionRecord(bot))
