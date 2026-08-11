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
# 시즌 API
#
# GET /api/season
# =====================================================

@router.get(
    "/season"
)
def season_api():

    with get_db_connection() as conn:

        cursor = conn.cursor()


        # ==============================
        # 현재 활성 시즌
        # ==============================

        cursor.execute(
            """
            SELECT
                id,
                season_name,
                started_at,
                ended_at,
                is_active

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


        # ==============================
        # 활성 시즌 없음
        # ==============================

        if active_season_row is None:

            return {
                "success":
                    True,

                "active_season":
                    None,

                "summary": {
                    "season_match_count":
                        0,

                    "season_player_count":
                        0
                },

                "season_mvp":
                    None,

                "best_win_streak_player":
                    None,

                "best_winrate_player":
                    None,

                "most_games_player":
                    None,

                "season_players":
                    []
            }


        active_season = dict(
            active_season_row
        )


        season_id = (
            active_season[
                "id"
            ]
        )


        # ==============================
        # 시즌 랭킹
        # ==============================

        cursor.execute(
            """
            SELECT
                sps.discord_id,

                sps.rating,
                sps.wins,
                sps.losses,

                sps.win_streak,
                sps.lose_streak,
                sps.best_win_streak,

                sps.mvp,

                p.id
                    AS player_id,

                p.discord_nickname,
                p.riot_name,
                p.tier,

                p.main_position,
                p.sub_position

            FROM season_player_stats sps

            LEFT JOIN players p
                ON p.discord_id
                    = sps.discord_id

            WHERE sps.season_id = ?

            ORDER BY
                sps.rating DESC,
                sps.wins DESC,
                sps.losses ASC,
                sps.discord_id ASC
            """,
            (
                season_id,
            )
        )


        season_rows = (
            cursor.fetchall()
        )


        season_players = []


        for index, row in enumerate(
            season_rows,
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


            games = (
                wins
                + losses
            )


            win_rate = (
                round(
                    wins
                    / games
                    * 100,
                    1
                )
                if games > 0
                else 0
            )


            player["rank"] = (
                index
            )

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

            player["games"] = (
                games
            )

            player["win_rate"] = (
                win_rate
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


            season_players.append(
                player
            )


        # ==============================
        # 시즌 경기 수
        # ==============================

        cursor.execute(
            """
            SELECT
                COUNT(*) AS count

            FROM matches

            WHERE season_id = ?
            """,
            (
                season_id,
            )
        )


        season_match_count = (
            cursor.fetchone()[
                "count"
            ]
            or 0
        )


        # ==============================
        # 실제 시즌 참가자 수
        # ==============================

        cursor.execute(
            """
            SELECT
                COUNT(
                    DISTINCT mp.discord_id
                ) AS count

            FROM match_players mp

            INNER JOIN matches m
                ON m.id = mp.match_id

            WHERE m.season_id = ?
            """,
            (
                season_id,
            )
        )


        season_player_count = (
            cursor.fetchone()[
                "count"
            ]
            or 0
        )


        # ==============================
        # 시즌 MVP
        # ==============================

        cursor.execute(
            """
            SELECT
                sps.discord_id,

                sps.mvp,
                sps.rating,
                sps.wins,
                sps.losses,

                p.id
                    AS player_id,

                p.discord_nickname,
                p.riot_name

            FROM season_player_stats sps

            LEFT JOIN players p
                ON p.discord_id
                    = sps.discord_id

            WHERE sps.season_id = ?
              AND sps.mvp > 0

            ORDER BY
                sps.mvp DESC,
                sps.rating DESC,
                sps.wins DESC,
                sps.discord_id ASC

            LIMIT 1
            """,
            (
                season_id,
            )
        )


        row = (
            cursor.fetchone()
        )


        season_mvp = (
            dict(
                row
            )
            if row
            else None
        )


        # ==============================
        # 최고 연승
        # ==============================

        cursor.execute(
            """
            SELECT
                sps.discord_id,

                sps.best_win_streak,
                sps.rating,
                sps.wins,
                sps.losses,

                p.id
                    AS player_id,

                p.discord_nickname,
                p.riot_name

            FROM season_player_stats sps

            LEFT JOIN players p
                ON p.discord_id
                    = sps.discord_id

            WHERE sps.season_id = ?
              AND sps.best_win_streak > 0

            ORDER BY
                sps.best_win_streak DESC,
                sps.rating DESC,
                sps.wins DESC,
                sps.discord_id ASC

            LIMIT 1
            """,
            (
                season_id,
            )
        )


        row = (
            cursor.fetchone()
        )


        best_win_streak_player = (
            dict(
                row
            )
            if row
            else None
        )


        # ==============================
        # 최고 승률
        #
        # 최소 3경기
        # ==============================

        cursor.execute(
            """
            SELECT
                sps.discord_id,

                sps.rating,
                sps.wins,
                sps.losses,

                (
                    sps.wins
                    + sps.losses
                ) AS games,

                ROUND(
                    CASE
                        WHEN (
                            sps.wins
                            + sps.losses
                        ) > 0

                        THEN (
                            CAST(
                                sps.wins
                                AS REAL
                            )
                            /
                            (
                                sps.wins
                                + sps.losses
                            )
                            * 100
                        )

                        ELSE 0
                    END,
                    1
                ) AS win_rate,

                p.id
                    AS player_id,

                p.discord_nickname,
                p.riot_name

            FROM season_player_stats sps

            LEFT JOIN players p
                ON p.discord_id
                    = sps.discord_id

            WHERE sps.season_id = ?
              AND (
                    sps.wins
                    + sps.losses
                  ) >= 3

            ORDER BY
                win_rate DESC,
                games DESC,
                sps.rating DESC,
                sps.discord_id ASC

            LIMIT 1
            """,
            (
                season_id,
            )
        )


        row = (
            cursor.fetchone()
        )


        best_winrate_player = (
            dict(
                row
            )
            if row
            else None
        )


        # ==============================
        # 최다 참가
        # ==============================

        cursor.execute(
            """
            SELECT
                sps.discord_id,

                sps.rating,
                sps.wins,
                sps.losses,

                (
                    sps.wins
                    + sps.losses
                ) AS games,

                p.id
                    AS player_id,

                p.discord_nickname,
                p.riot_name

            FROM season_player_stats sps

            LEFT JOIN players p
                ON p.discord_id
                    = sps.discord_id

            WHERE sps.season_id = ?
              AND (
                    sps.wins
                    + sps.losses
                  ) > 0

            ORDER BY
                games DESC,
                sps.wins DESC,
                sps.rating DESC,
                sps.discord_id ASC

            LIMIT 1
            """,
            (
                season_id,
            )
        )


        row = (
            cursor.fetchone()
        )


        most_games_player = (
            dict(
                row
            )
            if row
            else None
        )


    # ==============================
    # 응답
    # ==============================

    return {
        "success":
            True,

        "active_season":
            active_season,

        "summary": {

            "season_match_count":
                season_match_count,

            "season_player_count":
                season_player_count
        },

        "season_mvp":
            season_mvp,

        "best_win_streak_player":
            best_win_streak_player,

        "best_winrate_player":
            best_winrate_player,

        "most_games_player":
            most_games_player,

        "season_players":
            season_players
    }