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
                "• 주 포지션\n"
                "• 부 포지션\n\n"
                "등록이 완료되면 내전 모집에 참가할 수 있습니다."
            )
        )

        await interaction.response.send_message(
            embed=embed,
            view=RegisterView(self.bot)
        )


async def setup(bot):
    await bot.add_cog(Register(bot))