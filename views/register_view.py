import discord


class RegisterView(discord.ui.View):

    def __init__(self, bot):
        super().__init__(timeout=None)

        self.bot = bot

    @discord.ui.button(
        label="통합 프로필 등록",
        style=discord.ButtonStyle.green,
        custom_id="register_profile_button"
    )
    async def register(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await interaction.response.send_modal(
            RegisterModal(self.bot)
        )


class RegisterModal(discord.ui.Modal):

    def __init__(self, bot):
        super().__init__(
            title="프로필 등록"
        )

        self.bot = bot

        self.riot_id = discord.ui.TextInput(
            label="Riot ID",
            placeholder="Blueee#KR1",
            max_length=40
        )

        self.main = discord.ui.TextInput(
            label="주 포지션",
            placeholder="TOP / JUNGLE / MID / ADC / SUPPORT",
            max_length=10
        )

        self.sub = discord.ui.TextInput(
            label="부 포지션",
            placeholder="TOP / JUNGLE / MID / ADC / SUPPORT",
            max_length=10
        )

        self.add_item(self.riot_id)
        self.add_item(self.main)
        self.add_item(self.sub)

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):
        profile_cog = self.bot.get_cog("Profile")

        if profile_cog is None:
            await interaction.response.send_message(
                "❌ 프로필 등록 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        main_position = str(self.main.value).strip().upper()
        sub_position = str(self.sub.value).strip().upper()

        valid_positions = {
            "TOP",
            "JUNGLE",
            "MID",
            "ADC",
            "SUPPORT"
        }

        if main_position not in valid_positions:
            await interaction.response.send_message(
                "❌ 주 포지션을 올바르게 입력해주세요.\n"
                "`TOP`, `JUNGLE`, `MID`, `ADC`, `SUPPORT` 중 하나입니다.",
                ephemeral=True
            )
            return

        if sub_position not in valid_positions:
            await interaction.response.send_message(
                "❌ 부 포지션을 올바르게 입력해주세요.\n"
                "`TOP`, `JUNGLE`, `MID`, `ADC`, `SUPPORT` 중 하나입니다.",
                ephemeral=True
            )
            return

        if main_position == sub_position:
            await interaction.response.send_message(
                "❌ 주 포지션과 부 포지션은 다르게 선택해주세요.",
                ephemeral=True
            )
            return

        await profile_cog.process_registration(
            interaction=interaction,
            riot_id=str(self.riot_id.value),
            main_position=main_position,
            sub_position=sub_position
        )