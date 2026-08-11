import asyncio
import discord

from utils.permissions import (
    is_admin,
    send_admin_only_message
)


class WinnerSelectView(discord.ui.View):

    def __init__(
        self,
        join_cog,
        callback
    ):
        super().__init__(timeout=30)

        self.join_cog = join_cog

        # 승리팀 선택창이 만들어진 내전 방을 기억합니다.
        self.room = (
            join_cog.active_room
        )

        self.callback = callback
        self.finished = False
        self.selection_lock = asyncio.Lock()
        self.message = None
        self.room.current_winner_select_view = self

    def invalidate(self):
        """결과 처리 없이 선택창을 즉시 만료시킵니다."""

        if self.finished:
            return False

        self.finished = True
        if self.room.current_winner_select_view is self:
            self.room.current_winner_select_view = None

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

    async def interaction_check(
        self,
        interaction: discord.Interaction
    ) -> bool:
        if not self.join_cog.activate_room(self.room):
            await interaction.response.send_message(
                "❌ 연결된 내전 방이 삭제되어 이 버튼은 "
                "사용할 수 없습니다.",
                ephemeral=True
            )
            return False

        if not is_admin(interaction):
            await send_admin_only_message(
                interaction
            )
            return False

        if self.finished:
            await interaction.response.send_message(
                "❌ 이미 승리팀 선택이 완료되었습니다.",
                ephemeral=True
            )
            return False

        if self.room.current_winner_select_view is not self:
            await interaction.response.send_message(
                "❌ 더 최근에 생성된 경기 결과 선택창이 있습니다.\n"
                "가장 최근 메시지의 버튼을 사용해주세요.",
                ephemeral=True
            )
            return False

        if not self.room.match_in_progress:
            await interaction.response.send_message(
                "❌ 이미 종료되거나 취소된 경기입니다.",
                ephemeral=True
            )
            return False

        return True

    async def finish_selection(
        self,
        interaction: discord.Interaction,
        winner: str
    ):
        self.join_cog.activate_room(
            self.room
        )

        async with self.selection_lock:
            if self.finished:
                await interaction.response.send_message(
                    "❌ 이미 승리팀 선택이 완료되었습니다.",
                    ephemeral=True
                )
                return

            self.finished = True

            if self.room.current_winner_select_view is self:
                self.room.current_winner_select_view = None

        await interaction.response.defer()

        for item in self.children:
            item.disabled = True

        try:
            await interaction.message.edit(
                view=self
            )

        except discord.HTTPException:
            pass

        self.stop()

        await self.callback(
            interaction,
            winner
        )

    async def on_timeout(self):
        self.join_cog.activate_room(
            self.room
        )

        async with self.selection_lock:
            if self.finished:
                return

            self.finished = True

            if self.room.current_winner_select_view is self:
                self.room.current_winner_select_view = None

        for item in self.children:
            item.disabled = True

        if self.message is not None:
            try:
                await self.message.edit(
                    content=(
                        "⌛ 승리팀 선택 시간이 만료되었습니다.\n"
                        "`/경기결과`를 다시 입력해주세요."
                    ),
                    view=self
                )

            except discord.HTTPException:
                pass

        self.stop()

    @discord.ui.button(
        label="🔴 레드팀 승리",
        style=discord.ButtonStyle.danger
    )
    async def red_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.finish_selection(
            interaction,
            "red"
        )

    @discord.ui.button(
        label="🔵 블루팀 승리",
        style=discord.ButtonStyle.primary
    )
    async def blue_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):
        await self.finish_selection(
            interaction,
            "blue"
        )
