import logging
import re

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


TIER_ROLE_PRIORITY = (
    "C", "챌린저",
    "GM", "그랜드마스터",
    "M9", "M7", "M5", "M3", "M1", "마스터",
    "다이아", "에메랄드", "플래티넘", "골드", "실버", "브론즈", "아이언"
)

TIER_ORDER = {
    "언랭크": 0, "아이언": 1, "브론즈": 2, "실버": 3, "골드": 4,
    "플래티넘": 5, "에메랄드": 6, "다이아": 7,
    "M1": 8, "M3": 9, "M5": 10, "M7": 11, "M9": 12, "GM": 13, "C": 14
}

TIER_SHORT = {
    "아이언": "I", "브론즈": "B", "실버": "S", "골드": "G",
    "플래티넘": "P", "에메랄드": "E", "다이아": "D", "마스터": "M",
    "M1": "M1", "M3": "M3", "M5": "M5", "M7": "M7", "M9": "M9",
    "그랜드마스터": "GM", "GM": "GM", "챌린저": "C", "C": "C",
    "언랭크": "UR"
}


def normalize_highest_tier(value):
    """입력/역할 이름을 저장에 사용하는 티어 이름으로 통일합니다."""
    normalized = re.sub(r"\s+", "", str(value or "")).upper()
    aliases = {
        "IRON": "아이언", "아이언": "아이언",
        "BRONZE": "브론즈", "브론즈": "브론즈",
        "SILVER": "실버", "실버": "실버",
        "GOLD": "골드", "골드": "골드",
        "PLAT": "플래티넘", "PLATINUM": "플래티넘",
        "플레": "플래티넘", "플래티넘": "플래티넘",
        "EMERALD": "에메랄드", "에메랄드": "에메랄드",
        "DIA": "다이아", "DIAMOND": "다이아",
        "다이아": "다이아", "다이아몬드": "다이아",
        "M1": "M1", "M3": "M3", "M5": "M5", "M7": "M7", "M9": "M9",
        "MASTER": "M1", "마스터": "M1",
        "GM": "GM", "GRANDMASTER": "GM", "그랜드마스터": "GM",
        "C": "C", "CHALLENGER": "C", "챌린저": "C",
        "UNRANKED": "언랭크", "언랭크": "언랭크"
    }
    if normalized in aliases:
        return aliases[normalized]

    lp_match = re.fullmatch(r"(?:(?:MASTER|마스터))?(\d{1,4})(?:LP|점)?", normalized)
    if lp_match:
        lp = int(lp_match.group(1))
        if lp >= 900:
            return "M9"
        if lp >= 700:
            return "M7"
        if lp >= 500:
            return "M5"
        if lp >= 300:
            return "M3"
        return "M1"

    return None


def get_member_role_tier(member):
    """멤버가 가진 티어 역할 중 가장 높은 티어를 반환합니다."""
    role_tiers = {
        normalize_highest_tier(role.name)
        for role in getattr(member, "roles", ())
    }
    role_tiers.discard(None)
    return max(
        role_tiers,
        key=lambda tier: TIER_ORDER.get(tier, 0),
        default="언랭크"
    )


def build_profile_nickname(riot_id, tier, main_position, sub_position):
    normalized_tier = normalize_highest_tier(tier) or "언랭크"
    return (
        f"{riot_id} / {TIER_SHORT.get(normalized_tier, 'UR')} / "
        f"{main_position} {str(sub_position)[:3]}"
    )[:32]


def get_role_adjusted_hidden_mmr(current_mmr, previous_tier, new_tier):
    """티어 역할이 실제로 바뀐 순간에만 MMR을 70:30으로 보정합니다."""
    try:
        current_mmr = int(current_mmr)
    except (TypeError, ValueError):
        current_mmr = 1000
    if previous_tier == new_tier:
        return current_mmr
    # 역할 교체 과정에서 기존 역할이 먼저 빠지고 새 역할이 잠시 뒤에
    # 들어오는 중간 상태로 MMR이 두 번 움직이지 않게 합니다.
    if new_tier == "언랭크":
        return current_mmr
    role_mmr = get_initial_hidden_mmr(new_tier)
    return round(current_mmr * 0.70 + role_mmr * 0.30)


class Profile(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self._nickname_sync_done = False

    def get_join_cog(self):
        return self.bot.get_cog("Join")

    def refresh_join_profiles(self):
        join_cog = self.get_join_cog()

        if join_cog is not None:
            join_cog.reload_profiles()

    @commands.Cog.listener()
    async def on_ready(self):
        """재시작 시 가입자 이름을 현재 Discord 서버 별명과 맞춥니다."""

        if self._nickname_sync_done:
            return

        self._nickname_sync_done = True
        updated_count = 0
        current_member_ids = {
            str(member.id)
            for guild in self.bot.guilds
            for member in guild.members
            if not member.bot
        }

        membership_change_count = (
            PlayerService.sync_guild_membership(
                current_member_ids
            )
        )

        for guild in self.bot.guilds:
            for member in guild.members:
                if member.bot:
                    continue

                try:
                    profile_row = PlayerService.get(str(member.id))
                    role_tier = get_member_role_tier(member)
                    stored_profile = (
                        dict(profile_row)
                        if profile_row is not None
                        else None
                    )
                    expected_nickname = (
                        build_profile_nickname(
                            stored_profile.get("riot_name") or member.display_name,
                            role_tier,
                            stored_profile.get("main_position") or "-",
                            stored_profile.get("sub_position") or "-"
                        )
                        if stored_profile is not None
                        else None
                    )

                    if (
                        stored_profile is not None
                        and (
                            stored_profile.get("tier") != role_tier
                            or member.display_name != expected_nickname
                        )
                    ):
                        profile = stored_profile
                        nickname = expected_nickname
                        profile["hidden_mmr"] = get_role_adjusted_hidden_mmr(
                            profile.get("hidden_mmr"),
                            profile.get("tier"),
                            role_tier
                        )
                        profile["tier"] = role_tier
                        profile["discord_nickname"] = nickname
                        PlayerService.update(str(member.id), profile)
                        changed = True

                        if member.display_name != nickname:
                            try:
                                await member.edit(nick=nickname)
                            except (discord.Forbidden, discord.HTTPException):
                                logger.warning(
                                    "시작 시 티어 역할 별명 동기화 실패 | 사용자=%s",
                                    member.id
                                )
                    else:
                        changed = PlayerService.update_discord_nickname(
                            str(member.id),
                            member.display_name
                        )

                    if changed:
                        updated_count += 1

                except Exception:
                    logger.exception(
                        "Discord 닉네임 동기화 실패 | 사용자=%s",
                        member.id
                    )

        if updated_count or membership_change_count:
            self.refresh_join_profiles()

        logger.info(
            "Discord 프로필 초기 동기화 완료 | 닉네임=%s명 | 멤버상태=%s건",
            updated_count,
            membership_change_count
        )

    @commands.Cog.listener()
    async def on_member_join(
        self,
        member: discord.Member
    ):
        """가입자가 서버에 재입장하면 랭킹에 다시 표시합니다."""

        if member.bot:
            return

        membership_changed = PlayerService.set_guild_membership(
            str(member.id),
            True
        )
        nickname_changed = PlayerService.update_discord_nickname(
            str(member.id),
            member.display_name
        )

        if membership_changed or nickname_changed:
            self.refresh_join_profiles()

    @commands.Cog.listener()
    async def on_member_remove(
        self,
        member: discord.Member
    ):
        """가입자가 서버를 나가면 기록은 보존하고 랭킹에서 숨깁니다."""

        if member.bot:
            return

        still_in_another_guild = any(
            guild.get_member(member.id) is not None
            for guild in self.bot.guilds
        )

        if still_in_another_guild:
            return

        if PlayerService.set_guild_membership(
            str(member.id),
            False
        ):
            self.refresh_join_profiles()

    @commands.Cog.listener()
    async def on_member_update(
        self,
        before: discord.Member,
        after: discord.Member
    ):
        """서버 별명과 티어 역할 변경을 프로필에 자동 반영합니다."""

        if after.bot:
            return

        before_roles = {role.id for role in before.roles}
        after_roles = {role.id for role in after.roles}
        role_changed = before_roles != after_roles
        display_name_changed = before.display_name != after.display_name

        if not role_changed and not display_name_changed:
            return

        try:
            changed = False
            profile_row = PlayerService.get(str(after.id))

            if role_changed and profile_row is not None:
                profile = dict(profile_row)
                stored_tier = normalize_highest_tier(
                    profile.get("tier")
                )
                stored_tier_is_assigned = (
                    stored_tier is not None
                    and stored_tier != "언랭크"
                    and any(
                        normalize_highest_tier(role.name) == stored_tier
                        for role in after.roles
                    )
                )
                # 새 티어 역할이 이미 지급된 상태라면, 역할 정리 중 생기는
                # 임시 상태가 저장된 티어와 닉네임을 덮어쓰지 않게 합니다.
                role_tier = (
                    stored_tier
                    if stored_tier_is_assigned
                    else get_member_role_tier(after)
                )
                nickname = build_profile_nickname(
                    profile.get("riot_name") or after.display_name,
                    role_tier,
                    profile.get("main_position") or "-",
                    profile.get("sub_position") or "-"
                )
                profile["hidden_mmr"] = get_role_adjusted_hidden_mmr(
                    profile.get("hidden_mmr"),
                    profile.get("tier"),
                    role_tier
                )
                profile["tier"] = role_tier
                profile["discord_nickname"] = nickname
                PlayerService.update(str(after.id), profile)
                changed = True

                if after.display_name != nickname:
                    try:
                        await after.edit(nick=nickname)
                    except discord.Forbidden:
                        logger.warning(
                            "티어 역할 변경 후 닉네임 변경 실패 | 사용자=%s",
                            after.id
                        )
                    except discord.HTTPException:
                        logger.exception(
                            "티어 역할 변경 후 Discord 오류 | 사용자=%s",
                            after.id
                        )

            elif display_name_changed:
                changed = PlayerService.update_discord_nickname(
                    str(after.id),
                    after.display_name
                )

            if changed:
                self.refresh_join_profiles()
                logger.info(
                    "Discord 프로필 자동 동기화 | 사용자=%s | 닉네임=%s",
                    after.id,
                    after.display_name
                )

        except Exception:
            logger.exception(
                "Discord 닉네임 자동 동기화 실패 | 사용자=%s",
                after.id
            )

    async def process_registration(
        self,
        interaction: discord.Interaction,
        riot_id: str,
        main_position: str,
        sub_position: str,
        highest_tier: str = None
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

        tier = (
            normalize_highest_tier(highest_tier)
            if highest_tier is not None
            else get_member_role_tier(interaction.user)
        )
        if tier is None:
            await interaction.followup.send(
                "❌ 최고 티어를 확인할 수 없습니다. "
                "브론즈/실버/골드/플레/다이아/M1/M3/M5/M7/M9/GM/C 중 "
                "하나를 입력해주세요. 마스터 LP도 입력할 수 있습니다. "
                "예: 마스터 300점은 M3입니다.",
                ephemeral=True
            )
            return

        tier_role = None
        if isinstance(interaction.user, discord.Member) and interaction.guild is not None:
            tier_role = next(
                (role for role in interaction.guild.roles if role.name == tier),
                None
            )
            if tier_role is None:
                tier_role = next(
                    (
                        role for role in interaction.guild.roles
                        if normalize_highest_tier(role.name) == tier
                    ),
                    None
                )
            if tier != "언랭크" and tier_role is None:
                await interaction.followup.send(
                    f"❌ 이 서버에 {tier} 역할이 없습니다. "
                    "서버 역할을 만든 뒤 다시 등록해주세요.",
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

        riot_tier = "언랭크"

        for rank in ranks:
            if rank.get("queueType") == "RANKED_SOLO_5x5":
                riot_tier = rank.get(
                    "tier",
                    "UNRANKED"
                )

                riot_tier = tier_map.get(
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

        existing_hidden_mmr = old_profile.get(
            "hidden_mmr",
            tier_initial_mmr
        )
        if old_profile and old_profile.get("tier") != tier:
            existing_hidden_mmr = get_role_adjusted_hidden_mmr(
                existing_hidden_mmr,
                old_profile.get("tier"),
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
            "hidden_mmr": existing_hidden_mmr,
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

        nickname = build_profile_nickname(
            official_riot_id,
            tier,
            main_position,
            sub_position
        )

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

        role_assignment_warning = None
        try:
            # ---------- 멤버, 최고 티어 및 포지션 역할 자동 지급 ----------
            if (
                isinstance(interaction.user, discord.Member)
                and interaction.guild is not None
            ):
                member = interaction.user
                guild_roles = interaction.guild.roles

                member_role = discord.utils.get(
                    guild_roles,
                    name="멤버"
                )

                position_roles = {
                    "TOP",
                    "JUNGLE",
                    "MID",
                    "ADC",
                    "SUPPORT"
                }
                tier_roles = [
                    role for role in guild_roles
                    if normalize_highest_tier(role.name) is not None
                ]

                main_role = discord.utils.get(
                    guild_roles,
                    name=main_position
                )
                sub_role = discord.utils.get(
                    guild_roles,
                    name=sub_position
                )

                # 새 티어 역할을 먼저 지급해 티어가 비는 중간 상태를 피합니다.
                roles_to_add = [
                    role for role in (
                        member_role,
                        tier_role,
                        main_role,
                        sub_role
                    )
                    if role is not None and role not in member.roles
                ]
                if roles_to_add:
                    await member.add_roles(
                        *roles_to_add,
                        reason="통합 프로필 등록"
                    )

                roles_to_remove = [
                    role for role in member.roles
                    if (
                        (
                            role in tier_roles
                            and role != tier_role
                        )
                        or (
                            role.name in position_roles
                            and role not in (main_role, sub_role)
                        )
                    )
                ]
                if roles_to_remove:
                    await member.remove_roles(
                        *roles_to_remove,
                        reason="프로필 티어/포지션 갱신"
                    )

                if member_role is None:
                    role_assignment_warning = (
                        "⚠️ 서버에 멤버 역할이 없어 멤버 역할은 지급하지 못했습니다. "
                        "역할을 만든 뒤 다시 등록해주세요."
                    )
        except discord.Forbidden:
            logger.warning(
                "티어/포지션 역할 지급 실패: 봇 역할 권한과 역할 순서를 확인해주세요."
            )
            role_assignment_warning = (
                "⚠️ 프로필은 저장했지만 역할을 변경하지 못했습니다. "
                "봇의 역할 관리 권한과 역할 순서를 확인해주세요."
            )
        except discord.HTTPException:
            logger.exception("티어/포지션 역할 변경 중 Discord 오류")
            role_assignment_warning = (
                "⚠️ 프로필은 저장했지만 Discord 오류로 역할을 변경하지 못했습니다."
            )

        result_message = (
            "✅ **프로필이 등록되었습니다.**\n\n"
            f"🎮 라이엇 계정: `{official_riot_id}`\n"
            f"🏆 최고 티어: **{tier}**\n"
            f"🔎 라이엇 솔로랭크: **{riot_tier}**\n"
            f"🎯 주 포지션: **{main_position}**\n"
            f"🔄 부 포지션: **{sub_position}**\n"
            f"🧮 기준 Hidden MMR: **{join_cog.profiles[user_id]['hidden_mmr']}**\n"
            f"⭐ 현재 레이팅: "
            f"**{join_cog.profiles[user_id]['rating']}점**\n"
        )

        if role_assignment_warning:
            result_message += "\n" + role_assignment_warning

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
