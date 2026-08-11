from fastapi import (
    APIRouter
)

from web.database import (
    get_db_connection
)


router = APIRouter(
    prefix="/api"
)


# =====================================================
# 전체 랭킹 API
#
# GET /api/ranking
# =====================================================

@router.get(
    "/ranking"
)
def ranking_api():

    with get_db_connection() as conn:

        cursor = conn.cursor()


        # ==============================
        # 전체 플레이어
        # ==============================

        cursor.execute(
            """
            SELECT
                id,
                discord_id,
                discord_nickname,
                riot_name,
                tier,
                main_position,
                sub_position,

                rating,

                wins,
                losses,

                win_streak,
                lose_streak,
                best_win_streak,

                mvp

            FROM players

            ORDER BY
                rating DESC,
                wins DESC,
                mvp DESC,
                discord_nickname ASC
            """
        )


        rows = (
            cursor.fetchall()
        )


        players = []


        # ==============================
        # 플레이어 데이터 가공
        # ==============================

        for index, row in enumerate(
            rows,
            start=1
        ):

            player = dict(
                row
            )


            wins = (
                player.get(
                    "wins"
                )
                or 0
            )


            losses = (
                player.get(
                    "losses"
                )
                or 0
            )


            total_games = (
                wins
                + losses
            )


            # ==============================
            # 승률
            # ==============================

            if total_games > 0:

                win_rate = round(
                    wins
                    / total_games
                    * 100,
                    1
                )

            else:

                win_rate = 0.0


            # ==============================
            # 안전한 기본값
            # ==============================

            player["rating"] = (
                player.get(
                    "rating"
                )
                or 0
            )


            player["wins"] = (
                wins
            )


            player["losses"] = (
                losses
            )


            player["win_streak"] = (
                player.get(
                    "win_streak"
                )
                or 0
            )


            player["lose_streak"] = (
                player.get(
                    "lose_streak"
                )
                or 0
            )


            player["best_win_streak"] = (
                player.get(
                    "best_win_streak"
                )
                or 0
            )


            player["mvp"] = (
                player.get(
                    "mvp"
                )
                or 0
            )


            # ==============================
            # 추가 계산값
            # ==============================

            player["rank"] = (
                index
            )


            player["total_games"] = (
                total_games
            )


            player["win_rate"] = (
                win_rate
            )


            players.append(
                player
            )


        # ==============================
        # 서버 요약
        # ==============================

        player_count = len(
            players
        )


        # ==============================
        # 평균 레이팅
        # ==============================

        if player_count > 0:

            average_rating = round(
                sum(
                    player["rating"]
                    for player in players
                )
                / player_count,
                1
            )

        else:

            average_rating = 0.0


        # ==============================
        # 최고 레이팅
        # ==============================

        top_rating = (
            players[0]["rating"]
            if players
            else 0
        )


        # ==============================
        # 총 경기 참가 횟수
        #
        # 10명이 한 경기에 참가하므로
        # 단순 match 수와는 다른 값입니다.
        # ==============================

        total_player_games = sum(
            player["total_games"]
            for player in players
        )


    # ==============================
    # 응답
    # ==============================

    return {
        "success":
            True,

        "summary": {

            "player_count":
                player_count,

            "average_rating":
                average_rating,

            "top_rating":
                top_rating,

            "total_player_games":
                total_player_games
        },

        "players":
            players
    }