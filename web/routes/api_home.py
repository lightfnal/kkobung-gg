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
# 홈 데이터 API
#
# GET /api/home
# =====================================================

@router.get(
    "/home"
)
def home_api():

    with get_db_connection() as conn:

        cursor = conn.cursor()


        # ==============================
        # 등록 플레이어 수
        # ==============================

        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM players
            """
        )

        player_count = (
            cursor.fetchone()["count"]
        )


        # ==============================
        # 전체 경기 수
        # ==============================

        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM matches
            """
        )

        match_count = (
            cursor.fetchone()["count"]
        )


        # ==============================
        # TOP 5 플레이어
        # ==============================

        cursor.execute(
            """
            SELECT
                id,
                discord_nickname,
                riot_name,
                tier,
                rating,
                wins,
                losses

            FROM players

            ORDER BY
                rating DESC,
                wins DESC

            LIMIT 5
            """
        )

        top_rows = (
            cursor.fetchall()
        )


        top_players = []

        for row in top_rows:

            player = dict(
                row
            )

            wins = (
                player["wins"]
                or 0
            )

            losses = (
                player["losses"]
                or 0
            )

            total_games = (
                wins
                + losses
            )

            player[
                "win_rate"
            ] = (
                round(
                    wins
                    / total_games
                    * 100,
                    1
                )
                if total_games > 0
                else 0
            )

            top_players.append(
                player
            )


        # ==============================
        # 최근 경기 5개
        # ==============================

        cursor.execute(
            """
            SELECT
                m.id,
                m.match_date,
                m.winner,
                m.mvp_discord_id,
                m.room_id,

                p.id AS mvp_player_id,
                p.discord_nickname AS mvp_name,

                s.season_name

            FROM matches m

            LEFT JOIN players p
                ON p.discord_id
                    = m.mvp_discord_id

            LEFT JOIN seasons s
                ON s.id
                    = m.season_id

            ORDER BY
                m.id DESC

            LIMIT 5
            """
        )

        recent_matches = [
            dict(
                row
            )
            for row in cursor.fetchall()
        ]


        # ==============================
        # 현재 활성 시즌
        # ==============================

        cursor.execute(
            """
            SELECT
                id,
                season_name,
                started_at

            FROM seasons

            WHERE is_active = 1

            ORDER BY
                id DESC

            LIMIT 1
            """
        )

        active_season_row = (
            cursor.fetchone()
        )


        active_season = (
            dict(
                active_season_row
            )
            if active_season_row
            else None
        )


        season_match_count = 0
        season_player_count = 0


        # ==============================
        # 현재 시즌 통계
        # ==============================

        if active_season is not None:

            season_id = (
                active_season[
                    "id"
                ]
            )


            cursor.execute(
                """
                SELECT COUNT(*) AS count

                FROM matches

                WHERE season_id = ?
                """,
                (
                    season_id,
                )
            )

            season_match_count = (
                cursor.fetchone()["count"]
            )


            cursor.execute(
                """
                SELECT COUNT(*) AS count

                FROM season_player_stats

                WHERE season_id = ?
                """,
                (
                    season_id,
                )
            )

            season_player_count = (
                cursor.fetchone()["count"]
            )


    return {
        "success":
            True,

        "summary": {

            "player_count":
                player_count,

            "match_count":
                match_count
        },

        "top_players":
            top_players,

        "recent_matches":
            recent_matches,

        "active_season":
            active_season,

        "season": {

            "match_count":
                season_match_count,

            "player_count":
                season_player_count
        }
    }