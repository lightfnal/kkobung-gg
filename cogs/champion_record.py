import asyncio
import logging
from typing import Literal

import discord
from discord.ext import commands

from services.champion_service import ChampionService
from storage.sqlite_db import (
    get_match_team_players,
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
        name="챔피언기록",
        description="완료된 내전의 팀별 챔피언 5명을 기록합니다."
    )
    async def champion_record(
        self,
        interaction: discord.Interaction,
        경기번호: int,
        팀: Literal["레드", "블루"]
    ):
        if not is_match_operator(interaction):
            await send_match_operator_only_message(interaction)
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
