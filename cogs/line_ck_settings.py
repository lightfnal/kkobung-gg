"""관리자가 라인CK 포지션별 무작위 챔피언 풀을 관리하는 명령어."""

import asyncio
import logging
from typing import Optional

import discord
from discord.ext import commands

from services.champion_service import ChampionService
from services.line_ck_champions import can_assign_standard_line_ck_roster
from storage.sqlite_db import (
    add_line_ck_champion,
    get_line_ck_champion_ids,
    remove_line_ck_champion,
)
from utils.permissions import (
    is_match_operator,
    send_match_operator_only_message,
)


logger = logging.getLogger(__name__)

LANE_CHOICES = [
    discord.app_commands.Choice(name="탑", value="TOP"),
    discord.app_commands.Choice(name="정글", value="JUNGLE"),
    discord.app_commands.Choice(name="미드", value="MID"),
    discord.app_commands.Choice(name="원딜", value="ADC"),
    discord.app_commands.Choice(name="서폿", value="SUPPORT"),
]
LANE_LABELS = {choice.value: choice.name for choice in LANE_CHOICES}


class LineCKSettings(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def _resolve_champion(self, interaction, name):
        if not is_match_operator(interaction):
            await send_match_operator_only_message(interaction)
            return None

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            champion = await asyncio.to_thread(ChampionService.resolve, name)
        except Exception:
            logger.exception("라인CK 챔피언 이름 조회 실패 | 입력=%s", name)
            await interaction.followup.send(
                "챔피언 목록을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.",
                ephemeral=True,
            )
            return None

        if champion is None:
            await interaction.followup.send(
                f"`{name}` 챔피언을 찾지 못했습니다. 한국어 이름이나 영문 이름을 입력해주세요.",
                ephemeral=True,
            )
            return None
        return champion

    @discord.app_commands.command(
        name="라인챔피언목록",
        description="라인CK에서 라인별로 무작위 선택되는 챔피언을 확인합니다.",
    )
    @discord.app_commands.rename(line="라인")
    @discord.app_commands.choices(line=LANE_CHOICES)
    async def line_champion_list(
        self,
        interaction: discord.Interaction,
        line: Optional[str] = None,
    ):
        if not is_match_operator(interaction):
            await send_match_operator_only_message(interaction)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        pools = get_line_ck_champion_ids()
        positions = [line] if line else list(LANE_LABELS)
        embed = discord.Embed(title="🎲 라인CK 챔피언 풀")
        for position in positions:
            ids = sorted(pools.get(position, set()))
            def localized_name(champion_key):
                try:
                    record = ChampionService.resolve(champion_key)
                    return record["champion_name"] if record else champion_key
                except Exception:
                    return champion_key

            names = await asyncio.to_thread(
                lambda: [localized_name(champion_key) for champion_key in ids]
            )
            embed.add_field(
                name=f"{LANE_LABELS[position]} ({len(ids)}명)",
                value=", ".join(names) if names else "등록된 챔피언이 없습니다.",
                inline=False,
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.app_commands.command(
        name="라인챔피언추가",
        description="라인CK 무작위 챔피언 후보에 챔피언을 추가합니다.",
    )
    @discord.app_commands.describe(champion="한국어 또는 영문 챔피언 이름")
    @discord.app_commands.rename(line="라인", champion="챔피언")
    @discord.app_commands.choices(line=LANE_CHOICES)
    async def line_champion_add(
        self,
        interaction: discord.Interaction,
        line: str,
        champion: str,
    ):
        champion_record = await self._resolve_champion(interaction, champion)
        if champion_record is None:
            return
        added = add_line_ck_champion(line, champion_record["champion_key"])
        if added:
            message = (
                f"✅ **{champion_record['champion_name']}**을(를) "
                f"**{LANE_LABELS[line]}** 라인CK 후보에 추가했습니다."
            )
        else:
            message = (
                f"ℹ️ **{champion_record['champion_name']}**은(는) 이미 "
                f"**{LANE_LABELS[line]}** 후보에 있습니다."
            )
        await interaction.followup.send(message, ephemeral=True)

    @discord.app_commands.command(
        name="라인챔피언삭제",
        description="라인CK 무작위 챔피언 후보에서 챔피언을 삭제합니다.",
    )
    @discord.app_commands.describe(champion="한국어 또는 영문 챔피언 이름")
    @discord.app_commands.rename(line="라인", champion="챔피언")
    @discord.app_commands.choices(line=LANE_CHOICES)
    async def line_champion_remove(
        self,
        interaction: discord.Interaction,
        line: str,
        champion: str,
    ):
        champion_record = await self._resolve_champion(interaction, champion)
        if champion_record is None:
            return

        current = get_line_ck_champion_ids().get(line, set())
        if champion_record["champion_key"] not in current:
            await interaction.followup.send(
                f"ℹ️ **{champion_record['champion_name']}**은(는) "
                f"**{LANE_LABELS[line]}** 후보에 없습니다.",
                ephemeral=True,
            )
            return
        proposed = {
            position: set(champion_ids)
            for position, champion_ids in get_line_ck_champion_ids().items()
        }
        proposed[line].discard(champion_record["champion_key"])
        if not can_assign_standard_line_ck_roster(proposed):
            await interaction.followup.send(
                "❌ 삭제하면 기본 라인CK 10명에게 서로 다른 챔피언을 "
                "배정할 수 없습니다. 다른 후보를 추가한 뒤 삭제해주세요.",
                ephemeral=True,
            )
            return

        removed = remove_line_ck_champion(line, champion_record["champion_key"])
        if removed:
            message = (
                f"✅ **{champion_record['champion_name']}**을(를) "
                f"**{LANE_LABELS[line]}** 라인CK 후보에서 삭제했습니다."
            )
        else:
            message = "⚠️ 목록 변경 중 문제가 생겼습니다. 목록을 다시 확인해주세요."
        await interaction.followup.send(message, ephemeral=True)


async def setup(bot):
    await bot.add_cog(LineCKSettings(bot))
