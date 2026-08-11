import discord

from config import ADMIN_IDS


def is_admin(
    interaction: discord.Interaction
) -> bool:
    """
    봇 관리자 권한을 확인합니다.

    다음 중 하나에 해당하면 관리자로 인정합니다.

    1. config.py의 ADMIN_IDS에 등록된 사용자
    2. Discord 서버의 관리자 권한을 가진 사용자
    """

    # 봇 소유자 및 별도 허용 사용자
    if interaction.user.id in ADMIN_IDS:
        return True

    # 개인 메시지에서는 Discord 서버 권한을 확인할 수 없습니다.
    if interaction.guild is None:
        return False

    # 서버 안에서는 실제 Discord 관리자 권한을 확인합니다.
    if isinstance(
        interaction.user,
        discord.Member
    ):
        return (
            interaction.user
            .guild_permissions
            .administrator
        )

    return False


async def send_admin_only_message(
    interaction: discord.Interaction
):
    message = "❌ 관리자만 사용할 수 있습니다."

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