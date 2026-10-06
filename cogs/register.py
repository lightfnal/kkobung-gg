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
                "• 주 포지션\n"
                "• 부 포지션\n\n"
                "마스터 LP 기준: 100=M1, 300=M3, 500=M5, "
                "마스터 300점은 M3로 자동 구분됩니다.\n\n"
                "등록이 완료되면 내전 모집에 참가할 수 있습니다.\n\n"
                "📌 도움말\n"
                "1. 닉네임은 복사하지 않고 직접 입력 해주셔야 합니다.\n"
                "2. 포지션은 예시대로 대문자, 줄임없이 그대로 작성해주세요.\n"
                "3. 최고티어 반드시 작성해주시고 마스터는 M1 M3 M5 M7 M9 기준으로 "
                "가장 가까운 점수에 반올림해서 입력해주시면 됩니다.\n\n"
                "📌 규칙\n"
                "1. 위장 티어 적발 시 무통보 추방 될 수 있습니다.\n"
                "2. 내전 진행 중 픽창과 인게임에서 솔랭(개인)픽은 지양 하며 "
                "팀 게임 위주로 플레이 및 소통 부탁드립니다.\n"
                "3. 프로필 등록 후 내전 참가를 원하시면 내전모집1~3 "
                "채널을 확인해주세요."
            )
        )

        await interaction.response.send_message(
            embed=embed,
            view=RegisterView(self.bot)
        )


async def setup(bot):
    await bot.add_cog(Register(bot))
