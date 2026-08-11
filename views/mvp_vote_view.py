import asyncio
import discord

from discord.ui import Button

from config import MVP_VOTE_TIMEOUT_SECONDS


class MVPVoteView(discord.ui.View):

    def __init__(
        self,
        bot,
        join_cog,
        winner,
        callback
    ):
        super().__init__(
            timeout=MVP_VOTE_TIMEOUT_SECONDS
        )

        self.bot = bot
        self.join_cog = join_cog

        # MVP 투표창이 생성된 내전 방을 기억합니다.
        self.room = self.join_cog.active_room

        self.winner = winner
        self.callback = callback

        self.votes = {}
        self.finished = False
        self.finish_lock = asyncio.Lock()
        self.vote_lock = asyncio.Lock()
        self.message = None
        self.room.current_mvp_vote_view = self

        self.create_buttons()

    def invalidate(self):
        """투표 결과 콜백 없이 현재 투표창을 만료시킵니다."""

        if self.finished:
            return False

        self.finished = True
        if self.room.current_mvp_vote_view is self:
            self.room.current_mvp_vote_view = None

        for item in self.children:
            item.disabled = True

        self.stop()
        if self.message is not None:
            asyncio.create_task(self._show_invalidated_state())
        return True

    async def _show_invalidated_state(self):
        try:
            await self.message.edit(view=self)
        except discord.HTTPException:
            pass

    async def finish_vote_once(self):
        """
        MVP 투표 결과가 한 번만 처리되도록 보호합니다.
        """

        self.join_cog.activate_room(
            self.room
        )

        async with self.finish_lock:
            if self.finished:
                return False

            self.finished = True

            if self.room.current_mvp_vote_view is self:
                self.room.current_mvp_vote_view = None

            for item in self.children:
                item.disabled = True

            if self.message is not None:
                try:
                    await self.message.edit(
                        view=self
                    )
                except discord.HTTPException:
                    pass

            await self.callback(
                self.votes
            )

            self.stop()

            return True

    async def on_timeout(self):
        await self.finish_vote_once()

    def create_buttons(self):
        self.join_cog.activate_room(
            self.room
        )

        team = self.join_cog.current_teams[self.winner]

        for position, user_id in team.items():

            member = self.bot.get_user(int(user_id))

            nickname = (
                member.display_name
                if member
                else str(user_id)
            )

            button = Button(
                label=f"{position} - {nickname}",
                style=discord.ButtonStyle.primary
            )

            button.callback = self.make_callback(user_id)

            self.add_item(button)

    def make_callback(self, target_id):

        async def callback(interaction: discord.Interaction):
            async with self.vote_lock:
                self.join_cog.activate_room(
                    self.room
                )

                async with self.room.operation_lock:
                    if self.finished:
                        await interaction.response.send_message(
                            "❌ 이미 MVP 투표가 종료되었습니다.",
                            ephemeral=True
                        )
                        return

                    if self.room.current_mvp_vote_view is not self:
                        await interaction.response.send_message(
                            "❌ 더 최근에 생성된 MVP 투표창이 있습니다.\n"
                            "가장 최근 메시지의 버튼을 사용해주세요.",
                            ephemeral=True
                        )
                        return

                    if (
                        not self.room.match_in_progress
                        or not self.room.mvp_vote_in_progress
                        or self.room.current_teams is None
                    ):
                        await interaction.response.send_message(
                            "❌ 현재 경기 정보가 더 이상 존재하지 않습니다.",
                            ephemeral=True
                        )
                        return

                    all_players = {
                        str(user_id)
                        for team in self.room.current_teams.values()
                        for user_id in team.values()
                    }
                    voter_id = str(interaction.user.id)

                    if voter_id not in all_players:
                        await interaction.response.send_message(
                            "❌ 현재 경기 참가자만 투표할 수 있습니다.",
                            ephemeral=True
                        )
                        return

                    if voter_id in self.votes:
                        await interaction.response.send_message(
                            "❌ 이미 MVP 투표를 완료했습니다.",
                            ephemeral=True
                        )
                        return

                    if voter_id == str(target_id):
                        await interaction.response.send_message(
                            "❌ 자신에게는 투표할 수 없습니다.",
                            ephemeral=True
                        )
                        return

                    self.votes[voter_id] = str(target_id)
                    vote_count = len(self.votes)
                    player_count = len(all_players)
                    should_finish = vote_count >= player_count

            # 상태 기록이 끝나면 두 잠금을 모두 해제한 뒤
            # Discord 네트워크 응답을 처리합니다.
            progress_embed = None
            if self.message is not None and self.message.embeds:
                progress_embed = self.message.embeds[0]
                progress_embed.description = (
                    progress_embed.description.split("📊")[0]
                    + "\n📊 **현재 투표 현황**\n"
                    + f"🗳️ {len(self.votes)}/{player_count}명 완료"
                )

            if should_finish:
                for item in self.children:
                    item.disabled = True

                await interaction.response.edit_message(
                    embed=progress_embed,
                    view=self
                )

                # 종료 콜백은 room.operation_lock을 다시 사용합니다.
                await self.finish_vote_once()
                return

            await interaction.response.send_message(
                "✅ MVP 투표가 완료되었습니다.\n"
                f"현재 투표: {vote_count}/{player_count}명",
                ephemeral=True
            )

            if self.message is not None and progress_embed is not None:
                try:
                    await self.message.edit(
                        embed=progress_embed,
                        view=self
                    )
                except discord.HTTPException:
                    pass

        return callback
