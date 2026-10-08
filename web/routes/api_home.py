from fastapi import (
    APIRouter
)

from web.database import (
    get_db_connection
)
from web.home_engagement import build_home_engagement


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
            WHERE is_guild_member = 1
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


        # TOP 5와 시즌 카드는 같은 활성 시즌을 기준으로 표시합니다.
        cursor.execute(
            """
            SELECT id, season_name, started_at
            FROM seasons
            WHERE is_active = 1
            ORDER BY id DESC
            LIMIT 1
            """
        )
        active_season_row = cursor.fetchone()
        active_season = dict(active_season_row) if active_season_row else None
        season_id = active_season["id"] if active_season else -1


        # ==============================
        # TOP 5 플레이어
        # ==============================

        cursor.execute(
            """
            WITH season_deltas AS (
                SELECT
                    mp.discord_id,
                    1000 + SUM(COALESCE(mp.rating_change, 0)) AS rating
                FROM match_players mp
                JOIN matches m ON m.id = mp.match_id
                WHERE m.season_id = ?
                GROUP BY mp.discord_id
            )
            SELECT
                p.id,
                p.discord_nickname,
                p.riot_name,
                p.tier,
                COALESCE(sd.rating, 1000) AS rating,
                COALESCE(sps.wins, 0) AS wins,
                COALESCE(sps.losses, 0) AS losses
            FROM players p
            LEFT JOIN season_player_stats sps
              ON sps.discord_id = p.discord_id
             AND sps.season_id = ?
            LEFT JOIN season_deltas sd
              ON sd.discord_id = p.discord_id
            WHERE p.is_guild_member = 1
            ORDER BY rating DESC, wins DESC, p.discord_nickname ASC
            LIMIT 5
            """,
            (season_id, season_id)
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
        season_id = active_season["id"] if active_season else None
        weekly_awards, activity_feed = build_home_engagement(
            cursor,
            season_id
        )


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

        "weekly_awards": weekly_awards,

        "activity_feed": activity_feed,

        "active_season":
            active_season,

        "season": {

            "match_count":
                season_match_count,

            "player_count":
                season_player_count
        }
    }
