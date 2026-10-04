import discord
from discord.ext import commands

from views.register_view import RegisterView


class Register(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(
        name="가입",
        description="통합 프로필 등록창을 엽니다."
    )
    async def register_panel(
        self,
        interaction: discord.Interaction
    ):
        embed = discord.Embed(
            title="👋 내전 서버 프로필 등록",
            description=(
                "아래 버튼을 눌러 프로필 등록을 시작해주세요.\n\n"
                "등록 항목\n"
                "• Riot ID\n"
                "• 최고 티어 (아이언/브론즈/실버/골드/플레/에메랄드/"
                "다이아/M1~M9/GM/C)\n"
                "  아이언(IRON), 에메랄드(EMERALD) 입력도 가능합니다.\n"
                "• 주 포지션\n"
                "• 부 포지션\n\n"
                "마스터 LP 기준: 100=M1, 300=M3, 500=M5, "
                "마스터 300점은 M3로 자동 구분됩니다.\n\n"
                "등록이 완료되면 내전 모집에 참가할 수 있습니다.\n\n"
                "📌 규칙\n"
                "1. 위장 티어 적발 시 무통보 추방될 수 있습니다.\n"
                "2. 프로필 등록 후 내전 참가를 원하시면 내전모집1~3 "
                "채널을 확인해주세요."
            )
        )

        await interaction.response.send_message(
            embed=embed,
            view=RegisterView(self.bot)
        )


async def setup(bot):
    await bot.add_cog(Register(bot))
