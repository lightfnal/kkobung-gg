import discord

from discord.ext import commands

from services.riot_service import RiotService


class Riot(commands.Cog):

    def __init__(self, bot):
        self.bot = bot


    @discord.app_commands.command(
        name="라이엇조회",
        description="Riot ID를 조회합니다."
    )
    async def riot_lookup(
        self,
        interaction: discord.Interaction,
        game_name: str,
        tag_line: str
    ):

        await interaction.response.defer(
            ephemeral=True
        )

        account = RiotService.get_account(
            game_name,
            tag_line
        )

        if account is None:
            await interaction.followup.send(
                "❌ Riot ID를 찾지 못했습니다."
            )
            return

        summoner = RiotService.get_summoner(
            account["puuid"]
        )

        if summoner is None:
            await interaction.followup.send(
                "❌ 소환사 정보를 찾지 못했습니다."
            )
            return

        ranks = RiotService.get_rank(
            account["puuid"]
        )

        if ranks is None:
            await interaction.followup.send(
                "❌ 랭크 정보를 조회하지 못했습니다.\n"
                "Riot API 키가 만료되었거나 요청에 실패했을 수 있습니다."
            )
            return

        solo_rank = None

        for rank in ranks:
            if rank.get("queueType") == "RANKED_SOLO_5x5":
                solo_rank = rank
                break

        if solo_rank is None:

            text = (
                "언랭크"
            )

        else:

            text = (
                f"{solo_rank['tier']} "
                f"{solo_rank['rank']} "
                f"{solo_rank['leaguePoints']}LP"
            )

        embed = discord.Embed(
            title="🔍 Riot 조회 결과"
        )

        embed.add_field(
            name="Riot ID",
            value=f"{game_name}#{tag_line}",
            inline=False
        )

        embed.add_field(
            name="소환사 레벨",
            value=str(
                summoner["summonerLevel"]
            ),
            inline=False
        )

        embed.add_field(
            name="솔랭 티어",
            value=text,
            inline=False
        )

        await interaction.followup.send(
            embed=embed
        )


async def setup(bot):
    await bot.add_cog(Riot(bot))