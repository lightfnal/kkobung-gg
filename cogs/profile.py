import logging

import discord
from discord.ext import commands

from services.player_service import PlayerService
from services.riot_service import RiotService

from utils.mmr import get_initial_hidden_mmr
from config import (
    PLACEMENT_GAMES,
    MMR_EARLY_GAMES
)


logger = logging.getLogger(__name__)


class Profile(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    def get_join_cog(self):
        return self.bot.get_cog("Join")

    async def process_registration(
        self,
        interaction: discord.Interaction,
        riot_id: str,
        main_position: str,
        sub_position: str
    ):
        """
        /프로필등록과 통합 가입 모달이 함께 사용하는
        실제 프로필 등록 처리 함수입니다.
        """

        # Riot API 조회가 길어져도 디스코드 응답 시간이 만료되지 않게 합니다.
        if not interaction.response.is_done():
            await interaction.response.defer(
                ephemeral=True
            )

        join_cog = self.get_join_cog()

        if join_cog is None:
            await interaction.followup.send(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        riot_id = riot_id.strip()
        main_position = main_position.strip().upper()
        sub_position = sub_position.strip().upper()

        valid_positions = {
            "TOP",
            "JUNGLE",
            "MID",
            "ADC",
            "SUPPORT"
        }

        if main_position not in valid_positions:
            await interaction.followup.send(
                "❌ 주 포지션이 올바르지 않습니다.\n"
                "`TOP`, `JUNGLE`, `MID`, `ADC`, `SUPPORT` 중 "
                "하나를 입력해주세요.",
                ephemeral=True
            )
            return

        if sub_position not in valid_positions:
            await interaction.followup.send(
                "❌ 부 포지션이 올바르지 않습니다.\n"
                "`TOP`, `JUNGLE`, `MID`, `ADC`, `SUPPORT` 중 "
                "하나를 입력해주세요.",
                ephemeral=True
            )
            return

        if main_position == sub_position:
            await interaction.followup.send(
                "❌ 주 포지션과 부 포지션은 다르게 설정해주세요.",
                ephemeral=True
            )
            return

        if "#" not in riot_id:
            await interaction.followup.send(
                "❌ Riot ID는 `닉네임#태그` 형식으로 입력해주세요.",
                ephemeral=True
            )
            return

        game_name, tag_line = riot_id.split("#", 1)

        game_name = game_name.strip()
        tag_line = tag_line.strip()

        if not game_name or not tag_line:
            await interaction.followup.send(
                "❌ Riot ID는 `닉네임#태그` 형식으로 입력해주세요.",
                ephemeral=True
            )
            return

        account = RiotService.get_account(
            game_name,
            tag_line
        )

        if account is None:
            await interaction.followup.send(
                "❌ Riot ID를 찾지 못했습니다.\n"
                "닉네임과 태그를 다시 확인해주세요.",
                ephemeral=True
            )
            return

        summoner = RiotService.get_summoner(
            account["puuid"]
        )

        if summoner is None:
            await interaction.followup.send(
                "❌ 소환사 정보를 찾지 못했습니다.",
                ephemeral=True
            )
            return

        ranks = RiotService.get_rank(
            account["puuid"]
        )

        if ranks is None:
            await interaction.followup.send(
                "❌ Riot API 조회에 실패했습니다.\n"
                "API 키가 만료되었거나 요청에 실패했을 수 있습니다.",
                ephemeral=True
            )
            return

        tier_map = {
            "IRON": "아이언",
            "BRONZE": "브론즈",
            "SILVER": "실버",
            "GOLD": "골드",
            "PLATINUM": "플래티넘",
            "EMERALD": "에메랄드",
            "DIAMOND": "다이아",
            "MASTER": "마스터",
            "GRANDMASTER": "그랜드마스터",
            "CHALLENGER": "챌린저"
        }

        tier_short = {
            "아이언": "I",
            "브론즈": "B",
            "실버": "S",
            "골드": "G",
            "플래티넘": "P",
            "에메랄드": "E",
            "다이아": "D",
            "마스터": "M",
            "그랜드마스터": "GM",
            "챌린저": "C",
            "언랭크": "UR"
        }

        tier = "언랭크"

        for rank in ranks:
            if rank.get("queueType") == "RANKED_SOLO_5x5":
                riot_tier = rank.get(
                    "tier",
                    "UNRANKED"
                )

                tier = tier_map.get(
                    riot_tier,
                    riot_tier
                )
                break

        # Riot API가 돌려준 공식 표기가 있으면 그 표기를 사용합니다.
        official_game_name = account.get(
            "gameName",
            game_name
        )

        official_tag_line = account.get(
            "tagLine",
            tag_line
        )

        official_riot_id = (
            f"{official_game_name}#{official_tag_line}"
        )

        user_id = str(interaction.user.id)

        # 기존 전적과 레이팅을 유지하기 위해 최신 프로필을 불러옵니다.
        join_cog.reload_profiles()

        old_profile = join_cog.profiles.get(
            user_id,
            {}
        )

        tier_initial_mmr = get_initial_hidden_mmr(
            tier
        )

        profile = {
            "discord_nickname": interaction.user.display_name,
            "riot_name": official_riot_id,
            "tier": tier,
            "main_position": main_position,
            "sub_position": sub_position,
            "rating": old_profile.get(
                "rating",
                1000
            ),
            "hidden_mmr": old_profile.get(
                "hidden_mmr",
                tier_initial_mmr
            ),
            "placement_games": old_profile.get(
                "placement_games",
                0
            ),
            "wins": old_profile.get(
                "wins",
                0
            ),
            "losses": old_profile.get(
                "losses",
                0
            ),
            "win_streak": old_profile.get(
                "win_streak",
                0
            ),
            "lose_streak": old_profile.get(
                "lose_streak",
                0
            ),
            "best_win_streak": old_profile.get(
                "best_win_streak",
                0
            ),
            "mvp": old_profile.get(
                "mvp",
                0
            )
        }

        existing_player = PlayerService.get(
            user_id
        )

        if existing_player is None:
            PlayerService.create(
                user_id,
                profile
            )
        else:
            PlayerService.update(
                user_id,
                profile
            )

        join_cog.reload_profiles()

        nickname = (
            f"{official_riot_id} / "
            f"{tier_short.get(tier, tier)} / "
            f"{main_position} "
            f"{sub_position[:3]}"
        )[:32]

        nickname_changed = False

        try:
            if isinstance(
                interaction.user,
                discord.Member
            ):
                await interaction.user.edit(
                    nick=nickname
                )
                nickname_changed = True

        except discord.Forbidden:
            logger.warning(
                "닉네임 변경 실패: "
                "봇 권한 또는 역할 순서를 확인해주세요."
            )

        except discord.HTTPException as error:
            logger.warning(
                "닉네임 변경 중 Discord 오류: %s",
                error,
                exc_info=True
            )

        # ---------- 티어 역할 자동 지급 ----------
        
        if (
            isinstance(interaction.user, discord.Member)
            and interaction.guild is not None
        ):

            tier_roles = [
                "아이언",
                "브론즈",
                "실버",
                "골드",
                "플래티넘",
                "에메랄드",
                "다이아"
            ]

            # 기존 티어 역할 제거
            remove_roles = [
                role
                for role in interaction.user.roles
                if role.name in tier_roles
            ]

            if remove_roles:
                await interaction.user.remove_roles(
                    *remove_roles,
                    reason="티어 갱신"
                )

            # 새 티어 역할 지급
            if tier in tier_roles:


                new_role = discord.utils.get(
                    interaction.guild.roles,
                    name=tier
                )

                if new_role is None:
                    logger.warning(
                        "티어 역할을 찾지 못했습니다: %s",
                        tier
                    )
                else:

                    try:
                        await interaction.user.add_roles(
                            new_role,
                            reason="프로필 등록"
                        )

                    except discord.Forbidden:
                        logger.warning(
                            "티어 역할 지급 실패: 권한 부족"
                        )

                    except discord.HTTPException as error:
                        logger.warning(
                            "티어 역할 지급 중 Discord 오류: %s",
                            error,
                            exc_info=True
                        )


        # ---------- 포지션 역할 자동 지급 ----------
        if (
            isinstance(interaction.user, discord.Member)
            and interaction.guild is not None
        ):

            position_roles = [
                "TOP",
                "JUNGLE",
                "MID",
                "ADC",
                "SUPPORT"
            ]

            # 기존 포지션 역할 제거
            remove_roles = [
                role
                for role in interaction.user.roles
                if role.name in position_roles
            ]

            if remove_roles:
                await interaction.user.remove_roles(
                    *remove_roles,
                    reason="포지션 갱신"
                )

            # 주 포지션 지급
            main_role = discord.utils.get(
                interaction.guild.roles,
                name=main_position
            )

            if main_role is not None:
                await interaction.user.add_roles(
                    main_role,
                    reason="주 포지션"
                )

            # 부 포지션 지급
            sub_role = discord.utils.get(
                interaction.guild.roles,
                name=sub_position
            )

            if (
                sub_role is not None
                and sub_role != main_role
            ):
                await interaction.user.add_roles(
                    sub_role,
                    reason="부 포지션"
                )

        result_message = (
            "✅ **프로필이 등록되었습니다.**\n\n"
            f"🎮 라이엇 계정: `{official_riot_id}`\n"
            f"🏆 티어: **{tier}**\n"
            f"🎯 주 포지션: **{main_position}**\n"
            f"🔄 부 포지션: **{sub_position}**\n"
            f"⭐ 현재 레이팅: "
            f"**{join_cog.profiles[user_id]['rating']}점**\n"
        )

        if nickname_changed:
            result_message += (
                f"🪪 서버 별명: `{nickname}`"
            )
        else:
            result_message += (
                "⚠️ 프로필은 저장되었지만 서버 별명은 "
                "변경하지 못했습니다.\n"
                "봇 역할과 `별명 관리하기` 권한을 확인해주세요."
            )

        await interaction.followup.send(
            result_message,
            ephemeral=True
        )

    @discord.app_commands.command(
        name="프로필",
        description="등록된 내 프로필을 확인합니다."
    )
    async def show_profile(
        self,
        interaction: discord.Interaction
    ):
        join_cog = self.get_join_cog()

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        user_id = str(interaction.user.id)

        profile = PlayerService.get(
            user_id
        )

        if profile is None:
            await interaction.response.send_message(
                "❌ 등록된 프로필이 없습니다.",
                ephemeral=True
            )
            return

        profile = dict(
            profile
        )

        placement_games = profile.get(
            "placement_games",
            0
        )

        if placement_games < PLACEMENT_GAMES:
            remaining_games = (
                PLACEMENT_GAMES
                - placement_games
            )

            placement_text = (
                f"🎯 MMR 상태: **배치 진행 중**\n"
                f"📊 배치 진행: "
                f"**{placement_games}/{PLACEMENT_GAMES}경기**\n"
                f"⏳ 배치 완료까지 **{remaining_games}경기** 남음"
            )

        elif placement_games < MMR_EARLY_GAMES:
            placement_text = (
                "✅ MMR 상태: **배치 완료**\n"
                "📊 적용 구간: **초기 안정화**"
            )

        else:
            placement_text = (
                "✅ MMR 상태: **배치 완료**\n"
                "📊 적용 구간: **일반 구간**"
            )

        await interaction.response.send_message(
            f"👤 **{interaction.user.display_name}**\n\n"
            f"🎮 라이엇 계정: {profile['riot_name']}\n"
            f"🏆 티어: {profile['tier']}\n"
            f"🎯 주 포지션: {profile['main_position']}\n"
            f"🔄 부 포지션: {profile['sub_position']}\n\n"
            f"⭐ 레이팅: {profile['rating']}\n"
            f"🏅 전적: {profile['wins']}승 "
            f"{profile['losses']}패\n\n"
            f"{placement_text}",
            ephemeral=True
        )

    @discord.app_commands.command(
        name="프로필등록",
        description="Riot API를 이용해 내전 프로필을 등록하거나 수정합니다."
    )
    @discord.app_commands.choices(
        main_position=[
            discord.app_commands.Choice(
                name="탑",
                value="TOP"
            ),
            discord.app_commands.Choice(
                name="정글",
                value="JUNGLE"
            ),
            discord.app_commands.Choice(
                name="미드",
                value="MID"
            ),
            discord.app_commands.Choice(
                name="원딜",
                value="ADC"
            ),
            discord.app_commands.Choice(
                name="서포터",
                value="SUPPORT"
            )
        ],
        sub_position=[
            discord.app_commands.Choice(
                name="탑",
                value="TOP"
            ),
            discord.app_commands.Choice(
                name="정글",
                value="JUNGLE"
            ),
            discord.app_commands.Choice(
                name="미드",
                value="MID"
            ),
            discord.app_commands.Choice(
                name="원딜",
                value="ADC"
            ),
            discord.app_commands.Choice(
                name="서포터",
                value="SUPPORT"
            )
        ]
    )
    async def register_profile(
        self,
        interaction: discord.Interaction,
        riot_id: str,
        main_position: str,
        sub_position: str
    ):
        await self.process_registration(
            interaction=interaction,
            riot_id=riot_id,
            main_position=main_position,
            sub_position=sub_position
        )


async def setup(bot):
    await bot.add_cog(Profile(bot))
