import logging

import discord

from views.winner_select_view import WinnerSelectView
from discord.ext import commands

from config import (
    MATCH_MODE,
    MVP_VOTE_TIMEOUT_SECONDS
)

from datetime import datetime
from uuid import uuid4

from utils.permissions import (
    is_admin,
    send_admin_only_message
)

from storage.team_history import (
    add_same_team,
    add_opponents
)

from utils.cog_helper import get_join_cog

from storage.sqlite_db import (
    get_active_season,
    get_season_player_stats,
    create_season_player_stats,
    update_season_player_stats,
    add_match,
    add_match_player,
    begin_transaction,
    commit_transaction,
    rollback_transaction
)

from services.player_service import PlayerService
from services.rating_service import RatingService

from utils.rating import get_rating_tier
from utils.room_display import format_room_status

from collections import Counter
import random

from views.mvp_vote_view import MVPVoteView


logger = logging.getLogger(__name__)


class Match(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    @discord.app_commands.command(
        name="경기결과",
        description="승리팀을 선택하고 MVP 투표를 시작합니다."
    )
    async def match_result(
        self,
        interaction: discord.Interaction
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not await join_cog.require_room(
            interaction
        ):
            return

        room = join_cog.active_room

        async def select_winner(
            button_interaction: discord.Interaction,
            winner: str
        ):
            await self.start_mvp_vote(
                button_interaction,
                winner,
                room
            )

        async with room.operation_lock:
            if room.current_teams is None:
                await interaction.response.send_message(
                    "❌ 먼저 팀을 생성해주세요.",
                    ephemeral=True
                )
                return

            if not room.match_in_progress:
                await interaction.response.send_message(
                    "❌ 현재 진행 중인 경기가 없습니다.",
                    ephemeral=True
                )
                return

            if room.mvp_vote_in_progress:
                await interaction.response.send_message(
                    "❌ 현재 MVP 투표가 진행 중입니다.",
                    ephemeral=True
                )
                return

            current_winner_view = (
                room.current_winner_select_view
            )
            if (
                current_winner_view is not None
                and not current_winner_view.finished
            ):
                await interaction.response.send_message(
                    "❌ 이미 승리팀 선택창이 열려 있습니다.\n"
                    "가장 최근 선택창을 사용하거나 "
                    "30초 만료 후 다시 시도해주세요.",
                    ephemeral=True
                )
                return

            await interaction.response.defer(
                ephemeral=True
            )

            # 생성자가 현재 선택창을 설정하므로 같은 방의
            # 다른 /경기결과 요청보다 먼저 선택창을 예약합니다.
            view = WinnerSelectView(
                join_cog=join_cog,
                callback=select_winner
            )

        embed = discord.Embed(
            title=(
                f"🏆 {room.room_name} · "
                "승리팀 선택"
            ),
            description=(
                f"방 번호: **{room.room_id}**\n\n"
                "이번 경기에서 승리한 팀을 선택해주세요.\n\n"
                "🔴 **레드팀 승리**\n"
                "🔵 **블루팀 승리**\n\n"
                "⏱️ 선택 시간: **30초**"
            )
        )

        try:
            output_message, used_fallback = (
                await join_cog.send_output_message(
                    room=room,
                    fallback_channel=interaction.channel,
                    embed=embed,
                    view=view
                )
            )
        except Exception:
            async with room.operation_lock:
                if room.current_winner_select_view is view:
                    room.current_winner_select_view = None
                view.finished = True
                view.stop()
            raise

        view.message = output_message

        if output_message is None:
            async with room.operation_lock:
                if room.current_winner_select_view is view:
                    room.current_winner_select_view = None
                view.finished = True
                view.stop()

            confirmation_message = (
                "❌ 승리팀 선택창을 전송하지 못했습니다.\n"
                "경기 상태는 변경하지 않았습니다.\n"
                "공용 진행 채널과 모집 채널에서 꼬붕봇의 "
                "`채널 보기`, `메시지 보내기`, "
                "`링크 첨부` 권한을 확인한 뒤 "
                "`/경기결과`를 다시 실행해주세요."
            )

        elif used_fallback:
            confirmation_message = (
                "⚠️ 공용 진행 채널에 접근할 수 없어 "
                "현재 모집 채널에 승리팀 선택창을 "
                "표시했습니다."
            )

        elif (
            output_message.channel.id
            == interaction.channel_id
        ):
            confirmation_message = (
                "✅ 승리팀 선택창을 현재 채널에 표시했습니다."
            )

        else:
            confirmation_message = (
                "✅ 승리팀 선택창을 공용 진행 채널에 "
                "표시했습니다.\n"
                f"진행 채널: "
                f"<#{output_message.channel.id}>"
            )

        await interaction.followup.send(
            confirmation_message,
            ephemeral=True
        )


    async def start_mvp_vote(
        self,
        interaction: discord.Interaction,
        winner: str,
        room
    ):
        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.followup.send(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not join_cog.activate_room(
            room
        ):
            await interaction.followup.send(
                "❌ 연결된 내전 방을 찾지 못했습니다.",
                ephemeral=True
            )
            return

        async with room.operation_lock:
            if room.current_teams is None:
                await interaction.followup.send(
                    "❌ 현재 팀 정보가 존재하지 않습니다.",
                    ephemeral=True
                )
                return

            if not room.match_in_progress:
                await interaction.followup.send(
                    "❌ 현재 진행 중인 경기가 없습니다.",
                    ephemeral=True
                )
                return

            if room.mvp_vote_in_progress:
                await interaction.followup.send(
                    "❌ 현재 MVP 투표가 이미 진행 중입니다.",
                    ephemeral=True
                )
                return

            winner_team = room.current_teams.get(
                winner
            )

            if not winner_team:
                await interaction.followup.send(
                    "❌ 승리팀 정보를 찾지 못했습니다.",
                    ephemeral=True
                )
                return

            winner_team = dict(winner_team)

            room.mvp_vote_in_progress = True

            join_cog.save_rooms_state()

        async def finish_vote(votes):
            async with room.operation_lock:
                await finish_vote_locked(votes)

        async def finish_vote_locked(votes):
            try:
                if (
                    not room.match_in_progress
                    or not room.mvp_vote_in_progress
                ):
                    logger.info(
                        "만료된 MVP 투표 결과 처리 생략 | 방=%s",
                        room.room_id
                    )
                    return

                if not votes:
                    await join_cog.send_output_message(
                        room=room,
                        fallback_channel=recruitment_channel,
                        content=(
                            f"⚠️ **{room.room_name}** MVP 투표자가 없어 "
                            "경기 결과를 등록하지 않았습니다.\n"
                            f"방 번호: **{room.room_id}**\n"
                            f"<#{room.channel_id}>에서 "
                            "`/경기결과`를 다시 입력해주세요."
                        )
                    )
                    return

                vote_counts = Counter(
                    votes.values()
                )

                highest_votes = max(
                    vote_counts.values()
                )

                tied_candidates = [
                    user_id
                    for user_id, count in vote_counts.items()
                    if count == highest_votes
                ]

                # 최고 득표자가 여러 명이면 무작위로 선정
                mvp_id = random.choice(
                    tied_candidates
                )

                sorted_votes = sorted(
                    vote_counts.items(),
                    key=lambda item: item[1],
                    reverse=True
                )

                result_lines = []
                medals = ["🥇", "🥈", "🥉"]

                for index, (user_id, count) in enumerate(
                    sorted_votes
                ):
                    icon = (
                        medals[index]
                        if index < 3
                        else "▪️"
                    )

                    result_lines.append(
                        f"{icon} <@{user_id}> - **{count}표**"
                    )

                await join_cog.send_output_message(
                    room=room,
                    fallback_channel=recruitment_channel,
                    content=(
                        f"🗳️ **{room.room_name} · "
                        "MVP 투표 종료**\n"
                        f"방 번호: **{room.room_id}**\n\n"
                        + "\n".join(result_lines)
                        + f"\n\n🏅 **최종 MVP: <@{mvp_id}>**"
                    )
                )

                await self.process_match_result(
                    interaction,
                    winner,
                    mvp_id,
                    room
                )

            except Exception as error:
                logger.exception(
                    "경기 결과 처리 중 오류: %r",
                    error
                )

                if room.match_transaction_active:
                    rollback_transaction()

                    room.match_transaction_active = False
                    room.match_transaction_committed = False

                    if room.transaction_series_score is not None:
                        join_cog.series_score = dict(
                            room.transaction_series_score
                        )

                    if room.transaction_series_game is not None:
                        join_cog.series_game = (
                            room.transaction_series_game
                        )

                    room.pending_match_token = None
                    room.pending_series_score = None
                    room.pending_series_game = None

                    join_cog.reload_profiles()
                    join_cog.save_rooms_state()

                    error_message = (
                        "❌ 경기 결과 저장 중 오류가 발생했습니다.\n"
                        "레이팅, Hidden MMR, 배치 경기 수와 "
                        "시즌 기록은 모두 경기 전 상태로 복구했습니다.\n"
                        "`/경기결과`를 다시 실행해주세요."
                    )

                elif room.match_transaction_committed:
                    # SQLite 커밋은 성공했으므로
                    # 대기 중인 BO3 점수도 즉시 확정합니다.
                    if room.pending_series_score is not None:
                        join_cog.series_score = dict(
                            room.pending_series_score
                        )

                    if room.pending_series_game is not None:
                        join_cog.series_game = (
                            room.pending_series_game
                        )

                    join_cog.match_in_progress = False

                    room.pending_match_token = None
                    room.pending_series_score = None
                    room.pending_series_game = None

                    join_cog.save_rooms_state()

                    error_message = (
                        "⚠️ 경기 데이터와 BO3 점수는 "
                        "정상 저장되었지만 "
                        "후속 처리 중 오류가 발생했습니다.\n"
                        "관리자는 `/mmr기록`과 경기 기록을 "
                        "확인해주세요."
                    )

                else:
                    room.pending_match_token = None
                    room.pending_series_score = None
                    room.pending_series_game = None

                    error_message = (
                        "❌ 경기 결과 처리 중 오류가 발생했습니다.\n"
                        "경기 데이터는 저장되지 않았습니다.\n"
                        "`/경기결과`를 다시 실행해주세요."
                    )

                await join_cog.send_output_message(
                    room=room,
                    fallback_channel=recruitment_channel,
                    content=error_message
                )

            finally:
                room.mvp_vote_in_progress = False
                room.match_transaction_active = False
                room.match_transaction_committed = False
                room.transaction_series_score = None
                room.transaction_series_game = None

                join_cog.save_rooms_state()

        view = MVPVoteView(
            self.bot,
            join_cog,
            winner,
            finish_vote
        )

        candidate_list = "\n".join(
            f"**{position}** · <@{user_id}>"
            for position, user_id in winner_team.items()
        )

        winner_name = (
            "🔴 레드팀"
            if winner == "red"
            else "🔵 블루팀"
        )

        embed = discord.Embed(
            title=(
                f"🏅 {room.room_name} · "
                "MVP 투표"
            ),
            description=(
                f"방 번호: **{room.room_id}**\n"
                f"승리팀: **{winner_name}**\n\n"
                "승리팀 선수 중 MVP를 선택해주세요.\n\n"
                f"{candidate_list}\n\n"
                f"⏱️ 투표 시간: "
                f"**{MVP_VOTE_TIMEOUT_SECONDS}초**\n"
                "경기 참가자만 투표할 수 있습니다.\n\n"
                "📊 **현재 투표 현황**\n"
                "🗳️ 0/10명 완료"
            )
        )

        recruitment_channel = self.bot.get_channel(
            room.channel_id
        )

        if recruitment_channel is None:
            try:
                recruitment_channel = (
                    await self.bot.fetch_channel(
                        room.channel_id
                    )
                )

            except (
                discord.Forbidden,
                discord.NotFound,
                discord.HTTPException
            ):
                recruitment_channel = None

        vote_message, used_fallback = (
            await join_cog.send_output_message(
                room=room,
                fallback_channel=recruitment_channel,
                embed=embed,
                view=view
            )
        )

        if vote_message is None:
            async with room.operation_lock:
                room.mvp_vote_in_progress = False
                join_cog.save_rooms_state()

            await interaction.followup.send(
                "❌ MVP 투표창을 전송하지 못했습니다.\n"
                "MVP 투표 잠금은 자동으로 해제했습니다.\n"
                "공용 진행 채널과 모집 채널의 봇 권한을 "
                "확인한 뒤 `/경기결과`를 다시 실행해주세요.",
                ephemeral=True
            )
            return

        view.message = vote_message

        join_cog.save_rooms_state()

        if used_fallback:
            try:
                await interaction.followup.send(
                    "⚠️ 공용 진행 채널에 접근할 수 없어 "
                    "모집 채널에 MVP 투표창을 표시했습니다.",
                    ephemeral=True
                )

            except discord.HTTPException:
                pass


    async def process_match_result(
        self,
        interaction: discord.Interaction,
        winner: str,
        mvp_id: str,
        room
    ):

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.followup.send(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not join_cog.activate_room(
            room
        ):
            await interaction.followup.send(
                "❌ 연결된 내전 방을 찾지 못했습니다.",
                ephemeral=True
            )
            return

        logger.info(
            "경기 결과 처리 시작 | 방=%s | 경기 진행=%s | 팀 구성=%s",
            room.room_id,
            join_cog.match_in_progress,
            join_cog.current_teams is not None
        )

        active_season = get_active_season()

        if active_season is None:
            await interaction.followup.send(
                "❌ 현재 진행 중인 시즌이 없습니다.\n"
                "먼저 `/시즌시작` 명령어로 시즌을 시작해주세요.",
                ephemeral=True
            )
            return

        if join_cog.current_teams is None:
            await interaction.followup.send(
                "❌ 먼저 팀을 생성해주세요.",
                ephemeral=True
            )
            return

        if not join_cog.match_in_progress:
            await interaction.followup.send(
                "❌ 현재 진행 중인 경기가 없습니다.",
                ephemeral=True
            )
            return

        season_id = active_season["id"]

        join_cog.profiles = {
            str(player["discord_id"]): player
            for player in PlayerService.get_all()
        }

        loser = (
            "blue"
            if winner == "red"
            else "red"
        )

        winner_ids = join_cog.current_teams[winner]
        loser_ids = join_cog.current_teams[loser]

        winner_players = [
            str(user_id)
            for user_id in winner_ids.values()
        ]

        loser_players = [
            str(user_id)
            for user_id in loser_ids.values()
        ]

        winner_positions = {
            str(user_id): position
            for position, user_id in winner_ids.items()
        }

        loser_positions = {
            str(user_id): position
            for position, user_id in loser_ids.items()
        }

        try:
            # 공개 레이팅 평균
            winner_avg = sum(
                join_cog.profiles[user_id]["rating"]
                for user_id in winner_players
            ) / len(winner_players)

            loser_avg = sum(
                join_cog.profiles[user_id]["rating"]
                for user_id in loser_players
            ) / len(loser_players)

            # Hidden MMR 평균
            winner_mmr_avg = sum(
                join_cog.profiles[user_id].get(
                    "hidden_mmr",
                    join_cog.profiles[user_id].get(
                        "rating",
                        1000
                    )
                )
                for user_id in winner_players
            ) / len(winner_players)

            loser_mmr_avg = sum(
                join_cog.profiles[user_id].get(
                    "hidden_mmr",
                    join_cog.profiles[user_id].get(
                        "rating",
                        1000
                    )
                )
                for user_id in loser_players
            ) / len(loser_players)

        except KeyError as error:
            await interaction.followup.send(
                f"❌ 팀원 중 프로필이 없는 참가자가 있습니다.\n"
                f"누락된 ID: `{error.args[0]}`",
                ephemeral=True
            )
            return

        winner_changes = []
        loser_changes = []
        placement_completed_players = []


        if mvp_id not in winner_players + loser_players:
            await interaction.followup.send(
                "❌ MVP는 현재 경기에 참가한 선수만 선택할 수 있습니다.",
                ephemeral=True
            )
            return


        # 이번 경기 결과를 구분하는 고유 토큰입니다.
        result_token = uuid4().hex

        # DB 저장이 성공했을 때 적용할 다음 BO3 상태를
        # 현재 상태와 분리하여 미리 계산합니다.
        next_series_score = dict(
            join_cog.series_score
        )

        next_series_score[winner] += 1

        next_series_game = (
            join_cog.series_game + 1
        )

        # SQLite 처리 중 봇이 종료될 경우를 대비해
        # 다음 BO3 상태와 토큰을 먼저 JSON에 저장합니다.
        room.pending_match_token = (
            result_token
        )

        room.pending_series_score = dict(
            next_series_score
        )

        room.pending_series_game = (
            next_series_game
        )

        join_cog.save_rooms_state()

        # 같은 프로세스 안에서 오류가 발생했을 때
        # 원래 BO3 상태로 되돌리기 위한 메모리 정보입니다.
        room.transaction_series_score = dict(
            join_cog.series_score
        )

        room.transaction_series_game = (
            join_cog.series_game
        )

        room.match_transaction_committed = False

        begin_transaction()
        room.match_transaction_active = True

        logger.info(
            "BO3 결과 반영 전 | 방=%s | 완료 세트=%s | red=%s | blue=%s",
            room.room_id,
            join_cog.series_game,
            join_cog.series_score["red"],
            join_cog.series_score["blue"]
        )


        match_date = datetime.now().strftime(
            "%Y-%m-%d %H:%M"
        )

        match_id = add_match(
            match_date=match_date,
            winner=winner,
            mvp_discord_id=mvp_id,
            auto_commit=False,
            room_id=room.room_id,
            result_token=result_token
        )

        for user_id in winner_players:
            profile = join_cog.profiles.get(user_id)

            if profile is None:
                continue

            season_profile = get_season_player_stats(
                season_id,
                user_id
            )

            if season_profile is None:
                season_profile = create_season_player_stats(
                    season_id,
                    user_id,
                    auto_commit=False
                )

            # 경기 반영 전 시즌 전적을 복사해 둡니다.
            season_before = dict(
                season_profile
            )

            result = RatingService.process_match_result(
                profile=profile,
                won=True,
                team_avg_rating=winner_avg,
                enemy_avg_rating=loser_avg,
                enemy_avg_mmr=loser_mmr_avg,
                is_mvp=(user_id == mvp_id)
            )

            profile = result["profile"]

            change = result["rating_change"]
            mmr_change = result["hidden_mmr_change"]

            old_rating = result["rating_before"]
            old_hidden_mmr = result["hidden_mmr_before"]
            old_placement_games = result["placement_games_before"]

            old_win_streak = result["win_streak_before"]
            old_lose_streak = result["lose_streak_before"]
            old_best_win_streak = result["best_win_streak_before"]

            old_tier = result["tier_before"]

            if result["placement_completed"]:
                placement_completed_players.append(
                    user_id
                )

            season_profile["wins"] += 1
            season_profile["win_streak"] += 1
            season_profile["lose_streak"] = 0
            season_profile["rating"] += change

            if (
                season_profile["win_streak"]
                > season_profile["best_win_streak"]
            ):
                season_profile["best_win_streak"] = (
                    season_profile["win_streak"]
                )

            if user_id == mvp_id:
                season_profile["mvp"] += 1

            update_season_player_stats(
                season_id,
                user_id,
                season_profile,
                auto_commit=False
            )

            PlayerService.update_stats(
                user_id,
                profile,
                auto_commit=False
            )

            add_match_player(
                match_id=match_id,
                discord_id=user_id,
                team=winner,
                position=winner_positions.get(user_id),
                won=True,
                rating_before=old_rating,
                rating_after=profile["rating"],
                rating_change=change,
                hidden_mmr_before=old_hidden_mmr,
                hidden_mmr_after=profile["hidden_mmr"],
                hidden_mmr_change=mmr_change,
                placement_games_before=old_placement_games,
                placement_games_after=profile["placement_games"],
                season_rating_before=season_before["rating"],
                season_wins_before=season_before["wins"],
                season_losses_before=season_before["losses"],
                season_win_streak_before=season_before["win_streak"],
                season_lose_streak_before=season_before["lose_streak"],
                season_best_win_streak_before=season_before["best_win_streak"],
                season_mvp_before=season_before["mvp"],
                win_streak_before=old_win_streak,
                lose_streak_before=old_lose_streak,
                best_win_streak_before=old_best_win_streak,
                auto_commit=False
            )

            change_text = f"<@{user_id}> +{change}"

            if profile["win_streak"] >= 3:
                change_text += (
                    f"\n🔥 {profile['win_streak']}연승 달성!"
                )

            new_tier = get_rating_tier(
                profile["rating"]
            )

            if old_tier != new_tier:
                change_text += (
                    f"\n🎉 {old_tier} → {new_tier}"
                )

            winner_changes.append(change_text)


        for user_id in loser_players:
            profile = join_cog.profiles.get(user_id)

            if profile is None:
                continue

            season_profile = get_season_player_stats(
                season_id,
                user_id
            )

            if season_profile is None:
                season_profile = create_season_player_stats(
                    season_id,
                    user_id,
                    auto_commit=False
                )

            season_before = dict(season_profile)

            result = RatingService.process_match_result(
                profile=profile,
                won=False,
                team_avg_rating=loser_avg,
                enemy_avg_rating=winner_avg,
                enemy_avg_mmr=winner_mmr_avg,
                is_mvp=False
            )

            profile = result["profile"]

            change = result["rating_change"]
            mmr_change = result["hidden_mmr_change"]

            old_rating = result["rating_before"]
            old_hidden_mmr = result["hidden_mmr_before"]
            old_placement_games = result["placement_games_before"]

            old_win_streak = result["win_streak_before"]
            old_lose_streak = result["lose_streak_before"]
            old_best_win_streak = result["best_win_streak_before"]

            old_tier = result["tier_before"]

            if result["placement_completed"]:
                placement_completed_players.append(user_id)

            season_profile["losses"] += 1
            season_profile["lose_streak"] += 1
            season_profile["win_streak"] = 0
            season_profile["rating"] += change

            if user_id == mvp_id:
                season_profile["mvp"] += 1

            update_season_player_stats(
                season_id,
                user_id,
                season_profile,
                auto_commit=False
            )

            PlayerService.update_stats(
                user_id,
                profile,
                auto_commit=False
            )

            add_match_player(
                match_id=match_id,
                discord_id=user_id,
                team=loser,
                position=loser_positions.get(user_id),
                won=False,
                rating_before=old_rating,
                rating_after=profile["rating"],
                rating_change=change,
                hidden_mmr_before=old_hidden_mmr,
                hidden_mmr_after=profile["hidden_mmr"],
                hidden_mmr_change=mmr_change,
                placement_games_before=old_placement_games,
                placement_games_after=profile["placement_games"],
                season_rating_before=season_before["rating"],
                season_wins_before=season_before["wins"],
                season_losses_before=season_before["losses"],
                season_win_streak_before=season_before["win_streak"],
                season_lose_streak_before=season_before["lose_streak"],
                season_best_win_streak_before=season_before["best_win_streak"],
                season_mvp_before=season_before["mvp"],
                win_streak_before=old_win_streak,
                lose_streak_before=old_lose_streak,
                best_win_streak_before=old_best_win_streak,
                auto_commit=False
            )

            change_text = f"<@{user_id}> {change}"

            if profile["lose_streak"] >= 3:
                change_text += (
                    f"\n💀 {profile['lose_streak']}연패"
                )

            new_tier = get_rating_tier(profile["rating"])

            if old_tier != new_tier:
                change_text += (
                    f"\n⬇️ {old_tier} → {new_tier}"
                )

            loser_changes.append(change_text)


        commit_transaction()

        room.match_transaction_active = False
        room.match_transaction_committed = True

        # SQLite 경기 기록 저장이 성공한 뒤에만
        # 이번 세트의 BO3 점수를 확정합니다.
        join_cog.series_score = dict(
            next_series_score
        )

        join_cog.series_game = (
            next_series_game
        )

        # DB와 BO3 점수가 모두 확정됐으므로
        # 재시작 복구 표식을 제거합니다.
        room.pending_match_token = None
        room.pending_series_score = None
        room.pending_series_game = None

        join_cog.save_rooms_state()

        # 첫 번째 세트 결과가 정상적으로 처리된 경우에만
        # 이번 시리즈의 팀 조합을 한 번 기록합니다.
        if join_cog.series_game == 1:
            red_team_players = list(
                join_cog.current_teams["red"].values()
            )

            blue_team_players = list(
                join_cog.current_teams["blue"].values()
            )

            add_same_team(
                red_team_players
            )

            add_same_team(
                blue_team_players
            )

            add_opponents(
                red_team_players,
                blue_team_players
            )

            logger.info(
                "시리즈 팀·상대 조합 기록 완료 | 방=%s",
                room.room_id
            )

        if MATCH_MODE == "single":
            series_finished = True
        else:
            series_finished = (
                join_cog.series_score["red"] >= 2
                or join_cog.series_score["blue"] >= 2
            )

        red_score = join_cog.series_score["red"]
        blue_score = join_cog.series_score["blue"]

        join_cog.reload_profiles()

        if placement_completed_players:
            placement_mentions = "\n".join(
                f"🎯 <@{user_id}>"
                for user_id in placement_completed_players
            )

            placement_message = (
                "\n\n✅ **배치 경기 완료**\n"
                f"{placement_mentions}\n"
                "다음 경기부터 초기 안정화 구간이 적용됩니다."
            )
        else:
            placement_message = ""

        winner_name = (
            "🔴 레드팀"
            if winner == "red"
            else "🔵 블루팀"
        )

        if MATCH_MODE == "single":
            series_message = (
                f"\n\n🏆 **단판 경기 종료**\n"
                f"최종 승리: **{winner_name}**"
            )

            result_title = "✅ 경기 결과가 등록되었습니다."
            winner_label = "🏆 승리팀"

        else:
            result_title = (
                f"✅ {join_cog.series_game}세트 결과가 등록되었습니다."
            )
            winner_label = "🏆 세트 승리팀"

            if series_finished:
                series_message = (
                    f"\n\n🏆 **3판 2선승제 종료**\n"
                    f"🔴 레드팀 {red_score} : "
                    f"{blue_score} 블루팀 🔵\n"
                    f"최종 승리: **{winner_name}**"
                )

            else:
                next_game = join_cog.series_game + 1

                series_message = (
                    f"\n\n📊 **현재 시리즈 점수**\n"
                    f"🔴 레드팀 {red_score} : "
                    f"{blue_score} 블루팀 🔵\n"
                    f"다음은 **{next_game}세트**입니다.\n"
                    f"<#{room.channel_id}>에서 "
                    "`/경기시작`으로 다음 세트를 시작해주세요."
                )

        result_message = (
            f"🎮 **{room.room_name} · 경기 결과**\n"
            f"방 번호: **{room.room_id}**\n\n"
            f"{result_title}\n\n"
            f"{winner_label}: **{winner_name}**\n\n"
            f"🏅 MVP: <@{mvp_id}>\n\n"
            f"📈 **승리팀 레이팅 변화**\n"
            f"{chr(10).join(winner_changes)}\n\n"
            f"📉 **패배팀 레이팅 변화**\n"
            f"{chr(10).join(loser_changes)}"
            f"{placement_message}"
            f"{series_message}"
        )

        recruitment_channel = self.bot.get_channel(
            room.channel_id
        )

        if recruitment_channel is None:
            try:
                recruitment_channel = (
                    await self.bot.fetch_channel(
                        room.channel_id
                    )
                )

            except (
                discord.Forbidden,
                discord.NotFound,
                discord.HTTPException
            ):
                recruitment_channel = None

        result_output_message, used_fallback = (
            await join_cog.send_output_message(
                room=room,
                fallback_channel=recruitment_channel,
                content=result_message
            )
        )

        if result_output_message is None:
            logger.warning(
                "경기 결과 메시지 전송 실패, 상태 처리는 계속함 | 방=%s (%s)",
                room.room_id,
                room.room_name
            )

        # 경기 결과 처리가 끝났으므로 진행 상태를 해제
        join_cog.match_in_progress = False

        if series_finished:
            # 단판 종료 또는 BO3에서 2승 달성: 경기 전체 종료
            match_player_ids = {
                str(user_id)
                for team in join_cog.current_teams.values()
                for user_id in team.values()
            }

            waiting_voice_result = (
                await join_cog.move_members_to_voice_channel(
                    guild=interaction.guild,
                    user_ids=match_player_ids,
                    channel_id=room.waiting_voice_channel_id
                )
            )

            voice_warning_parts = []

            if waiting_voice_result["channel_missing"]:
                voice_warning_parts.append(
                    "대기 음성채널이 설정되지 않았거나 삭제됨"
                )

            if waiting_voice_result["not_connected"]:
                voice_warning_parts.append(
                    f"{waiting_voice_result['not_connected']}명 "
                    "음성 미접속"
                )

            if waiting_voice_result["failed"]:
                voice_warning_parts.append(
                    f"{waiting_voice_result['failed']}명 "
                    "이동 실패"
                )

            if voice_warning_parts:
                await join_cog.send_output_message(
                    room=room,
                    fallback_channel=recruitment_channel,
                    content=(
                        f"⚠️ **{room.room_name} · "
                        "대기 음성채널 복귀 안내**\n"
                        f"방 번호: **{room.room_id}**\n"
                        + "\n".join(
                            f"• {part}"
                            for part in voice_warning_parts
                        )
                        + "\n\n경기 기록과 내전 종료 처리는 "
                        "정상적으로 계속됩니다."
                    )
                )


            join_cog.players.clear()

            join_cog.current_teams = None
            join_cog.last_team_signature = None
            join_cog.current_recruit_view = None

            join_cog.series_score = {
                "red": 0,
                "blue": 0
            }
            join_cog.series_game = 0

        join_cog.save_rooms_state()

    @discord.app_commands.command(
        name="팀교체",
        description="두 플레이어의 팀을 서로 교체합니다."
    )
    async def swap_team(
        self,
        interaction: discord.Interaction,
        player1: discord.Member,
        player2: discord.Member
    ):
        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not await join_cog.require_room(
            interaction
        ):
            return

        room = join_cog.active_room

        async with room.operation_lock:
            await self._swap_team_locked(
                interaction,
                player1,
                player2
            )

    async def _swap_team_locked(
        self,
        interaction: discord.Interaction,
        player1: discord.Member,
        player2: discord.Member
    ):

        

        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return
        
        join_cog = get_join_cog(
            self.bot
        )
        

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not await join_cog.require_room(
            interaction
        ):
            return

        room = join_cog.active_room

        if room.mvp_vote_in_progress:
            await interaction.response.send_message(
                "❌ MVP 투표 중에는 팀을 교체할 수 없습니다.",
                ephemeral=True
            )
            return

        if room.match_in_progress:
            await interaction.response.send_message(
                "❌ 경기 진행 중에는 팀을 교체할 수 없습니다.\n"
                "먼저 세트를 정상 종료하거나 취소해주세요.",
                ephemeral=True
            )
            return

        if join_cog.current_teams is None:
            await interaction.response.send_message(
                "❌ 먼저 팀을 생성해주세요.",
                ephemeral=True
            )
            return

        user1 = str(player1.id)
        user2 = str(player2.id)

        red_team = join_cog.current_teams["red"]
        blue_team = join_cog.current_teams["blue"]

        team1 = None
        team2 = None
        pos1 = None
        pos2 = None

        for position, user_id in red_team.items():
            if user_id == user1:
                team1 = "red"
                pos1 = position

            if user_id == user2:
                team2 = "red"
                pos2 = position

        for position, user_id in blue_team.items():
            if user_id == user1:
                team1 = "blue"
                pos1 = position

            if user_id == user2:
                team2 = "blue"
                pos2 = position

        if team1 is None or team2 is None:
            await interaction.response.send_message(
                "❌ 두 플레이어 모두 현재 팀에 있어야 합니다.",
                ephemeral=True
            )
            return

        if team1 == team2:
            await interaction.response.send_message(
                "❌ 같은 팀에 있는 플레이어끼리는 교체할 수 없습니다.",
                ephemeral=True
            )
            return

        if team1 == "red":
            red_position = pos1
            blue_position = pos2
        else:
            red_position = pos2
            blue_position = pos1

        red_team[red_position], blue_team[blue_position] = (
            blue_team[blue_position],
            red_team[red_position]
        )

        join_cog.save_rooms_state()

        guild = interaction.guild

        if team1 == "red":
            player1_target_channel_id = (
                room.blue_voice_channel_id
            )
            player2_target_channel_id = (
                room.red_voice_channel_id
            )

        else:
            player1_target_channel_id = (
                room.red_voice_channel_id
            )
            player2_target_channel_id = (
                room.blue_voice_channel_id
            )

        player1_voice_result = (
            await join_cog.move_members_to_voice_channel(
                guild=guild,
                user_ids=[user1],
                channel_id=player1_target_channel_id
            )
        )

        player2_voice_result = (
            await join_cog.move_members_to_voice_channel(
                guild=guild,
                user_ids=[user2],
                channel_id=player2_target_channel_id
            )
        )

        swap_voice_results = (
            player1_voice_result,
            player2_voice_result
        )

        swap_moved_count = sum(
            result["moved"]
            for result in swap_voice_results
        )

        swap_already_count = sum(
            result["already_connected"]
            for result in swap_voice_results
        )

        swap_not_connected_count = sum(
            result["not_connected"]
            for result in swap_voice_results
        )

        swap_failed_count = sum(
            result["failed"]
            for result in swap_voice_results
        )

        swap_channel_missing = any(
            result["channel_missing"]
            for result in swap_voice_results
        )

        red_rating = sum(
            join_cog.profiles.get(
                user_id,
                {}
            ).get(
                "rating",
                1000
            )
            for user_id in red_team.values()
        )

        blue_rating = sum(
            join_cog.profiles.get(
                user_id,
                {}
            ).get(
                "rating",
                1000
            )
            for user_id in blue_team.values()
        )

        red_list = "\n".join(
            f"**{position}** - <@{user_id}>"
            for position, user_id in red_team.items()
        )

        blue_list = "\n".join(
            f"**{position}** - <@{user_id}>"
            for position, user_id in blue_team.items()
        )

        embed = discord.Embed(
            title=(
                f"🔄 {room.room_name} · "
                "팀 교체 완료"
            ),
            description=(
                f"방 번호: **{room.room_id}**\n\n"
                f"{player1.mention} ↔ "
                f"{player2.mention}"
            )
        )

        embed.add_field(
            name=f"🔴 레드팀 · {red_rating}점",
            value=red_list,
            inline=True
        )

        embed.add_field(
            name=f"🔵 블루팀 · {blue_rating}점",
            value=blue_list,
            inline=True
        )

        swap_voice_parts = [
            f"{swap_moved_count}명 이동"
        ]

        if swap_already_count:
            swap_voice_parts.append(
                f"{swap_already_count}명 이미 위치"
            )

        if swap_not_connected_count:
            swap_voice_parts.append(
                f"{swap_not_connected_count}명 음성 미접속"
            )

        if swap_failed_count:
            swap_voice_parts.append(
                f"{swap_failed_count}명 이동 실패"
            )

        swap_voice_text = ", ".join(
            swap_voice_parts
        )

        if swap_channel_missing:
            embed.set_footer(
                text=(
                    "⚠️ 팀 음성채널 일부가 설정되지 않았거나 "
                    "삭제되었습니다. "
                    f"처리 결과: {swap_voice_text}"
                )
            )

        else:
            embed.set_footer(
                text=(
                    f"음성채널 처리 결과: "
                    f"{swap_voice_text}"
                )
            )

        output_message, used_fallback = (
            await join_cog.send_output_message(
                room=room,
                fallback_channel=interaction.channel,
                embed=embed
            )
        )

        if output_message is None:
            confirmation_message = (
                "✅ 팀 교체는 정상적으로 완료됐습니다.\n"
                "⚠️ 다만 교체 결과 메시지를 전송하지 "
                "못했습니다.\n"
                "공용 진행 채널과 모집 채널의 "
                "봇 권한을 확인해주세요."
            )

        elif used_fallback:
            confirmation_message = (
                "✅ 팀 교체는 정상적으로 완료됐습니다.\n"
                "⚠️ 공용 진행 채널에 접근할 수 없어 "
                "현재 모집 채널에 결과를 표시했습니다."
            )

        elif (
            output_message.channel.id
            == interaction.channel_id
        ):
            confirmation_message = (
                "✅ 팀 교체 결과를 현재 채널에 표시했습니다."
            )

        else:
            confirmation_message = (
                "✅ 팀 교체 결과를 공용 진행 채널에 "
                "표시했습니다.\n"
                f"진행 채널: "
                f"<#{output_message.channel.id}>"
            )

        await interaction.response.send_message(
            confirmation_message,
            ephemeral=True
        )


    @discord.app_commands.command(
        name="다시뽑기",
        description="현재 참가자로 팀을 다시 생성합니다."
    )
    async def reroll(
        self,
        interaction: discord.Interaction
    ):


        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not await join_cog.require_room(
            interaction
        ):
            return

        if join_cog.current_recruit_view is None:
            await interaction.response.send_message(
                "❌ 모집창이 없습니다.",
                ephemeral=True
            )
            return

        await join_cog.current_recruit_view.generate_teams(
            interaction
        )

    @discord.app_commands.command(
        name="세트취소",
        description="현재 진행 중인 세트만 취소합니다."
    )
    async def cancel_match(
        self,
        interaction: discord.Interaction
    ):

        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not await join_cog.require_room(
            interaction
        ):
            return

        room = join_cog.active_room


        async with room.operation_lock:
            if room.mvp_vote_in_progress:
                await interaction.response.send_message(
                    "❌ MVP 투표가 진행 중입니다.",
                    ephemeral=True
                )
                return

            if not room.match_in_progress:
                await interaction.response.send_message(
                    "❌ 현재 진행 중인 경기가 없습니다.",
                    ephemeral=True
                )
                return

            room.match_in_progress = False

            join_cog.save_rooms_state()

        if MATCH_MODE == "single":
            cancel_message = (
                f"🛑 **{room.room_name} · 현재 경기가 "
                "취소되었습니다.**\n"
                f"방 번호: **{room.room_id}**\n\n"
                "팀과 참가자 정보는 유지됩니다.\n"
                f"<#{room.channel_id}>에서 `/경기시작`으로 "
                "다시 시작할 수 있습니다."
            )
        else:
            cancel_message = (
                f"🛑 **{room.room_name} · 현재 세트가 "
                "취소되었습니다.**\n"
                f"방 번호: **{room.room_id}**\n\n"
                "팀과 시리즈 점수는 유지됩니다.\n"
                f"<#{room.channel_id}>에서 `/경기시작`으로 "
                "같은 세트를 다시 시작할 수 있습니다."
            )

        output_message, used_fallback = (
            await join_cog.send_output_message(
                room=room,
                fallback_channel=interaction.channel,
                content=cancel_message
            )
        )

        if output_message is None:
            confirmation_message = (
                "✅ 현재 세트는 정상적으로 취소됐습니다.\n"
                "⚠️ 다만 세트 취소 안내 메시지를 "
                "전송하지 못했습니다.\n"
                "공용 진행 채널과 모집 채널의 "
                "봇 권한을 확인해주세요."
            )

        elif used_fallback:
            confirmation_message = (
                "✅ 현재 세트를 정상적으로 취소했습니다.\n"
                "⚠️ 공용 진행 채널에 접근할 수 없어 "
                "현재 모집 채널에 안내를 표시했습니다."
            )

        elif (
            output_message.channel.id
            == interaction.channel_id
        ):
            confirmation_message = (
                "✅ 세트 취소 안내를 현재 채널에 표시했습니다."
            )

        else:
            confirmation_message = (
                "✅ 세트 취소 안내를 공용 진행 채널에 "
                "표시했습니다.\n"
                f"진행 채널: "
                f"<#{output_message.channel.id}>"
            )

        await interaction.response.send_message(
            confirmation_message,
            ephemeral=True
        )

    @discord.app_commands.command(
        name="경기시작",
        description="현재 생성된 팀으로 경기를 시작합니다."
    )
    async def start_match(
        self,
        interaction: discord.Interaction
    ):


        if not is_admin(interaction):
            await send_admin_only_message(interaction)
            return

        join_cog = get_join_cog(
            self.bot
        )

        if join_cog is None:
            await interaction.response.send_message(
                "❌ 내전 관리 기능을 불러오지 못했습니다.",
                ephemeral=True
            )
            return

        if not await join_cog.require_room(
            interaction
        ):
            return

        room = join_cog.active_room

        async with room.operation_lock:
            if room.current_teams is None:
                await interaction.response.send_message(
                    "❌ 먼저 팀을 생성해주세요.",
                    ephemeral=True
                )
                return

            if room.match_in_progress:
                await interaction.response.send_message(
                    "❌ 이미 진행 중인 경기가 있습니다.",
                    ephemeral=True
                )
                return

            await interaction.response.defer(
                ephemeral=True
            )

            room.match_in_progress = True

            join_cog.save_rooms_state()

        output_message, used_fallback = (
            await join_cog.send_output_message(
                room=room,
                fallback_channel=interaction.channel,
                content=(
                    f"🎮 **{room.room_name} · 경기가 "
                    "시작되었습니다!**\n"
                    f"{format_room_status(room)}\n\n"
                    f"경기 종료 후 <#{room.channel_id}>에서 "
                    "`/경기결과`를 입력해주세요."
                )
            )
        )

        if output_message is None:
            confirmation_message = (
                "✅ 경기 상태는 정상적으로 시작됐습니다.\n"
                "⚠️ 다만 경기 시작 안내 메시지를 "
                "전송하지 못했습니다.\n"
                "공용 진행 채널과 모집 채널의 "
                "봇 권한을 확인해주세요."
            )

        elif used_fallback:
            confirmation_message = (
                "✅ 경기를 정상적으로 시작했습니다.\n"
                "⚠️ 공용 진행 채널에 접근할 수 없어 "
                "현재 모집 채널에 안내를 표시했습니다."
            )

        elif (
            output_message.channel.id
            == interaction.channel_id
        ):
            confirmation_message = (
                "✅ 경기 시작 안내를 현재 채널에 표시했습니다."
            )

        else:
            confirmation_message = (
                "✅ 경기 시작 안내를 공용 진행 채널에 "
                "표시했습니다.\n"
                f"진행 채널: "
                f"<#{output_message.channel.id}>"
            )

        await interaction.followup.send(
            confirmation_message,
            ephemeral=True
        )



async def setup(bot):
    await bot.add_cog(Match(bot))
