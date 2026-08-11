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
# 서버 통계 API
#
# GET /api/stats
# =====================================================

@router.get(
    "/stats"
)
def stats_api():

    with get_db_connection() as conn:

        cursor = conn.cursor()


        # ==============================
        # 전체 플레이어 수
        # ==============================

        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM players
            """
        )

        player_count = (
            cursor.fetchone()["count"]
            or 0
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
            or 0
        )


        # ==============================
        # 평균 레이팅
        # ==============================

        cursor.execute(
            """
            SELECT
                AVG(rating) AS average_rating

            FROM players
            """
        )

        average_rating = round(
            cursor.fetchone()[
                "average_rating"
            ]
            or 0,
            1
        )


        # ==============================
        # 전체 MVP
        # ==============================

        cursor.execute(
            """
            SELECT
                SUM(mvp) AS total_mvp

            FROM players
            """
        )

        total_mvp = (
            cursor.fetchone()[
                "total_mvp"
            ]
            or 0
        )


        # ==============================
        # 진영 승률
        # ==============================

        cursor.execute(
            """
            SELECT

                SUM(
                    CASE
                        WHEN LOWER(winner) = 'blue'
                        THEN 1
                        ELSE 0
                    END
                ) AS blue_wins,

                SUM(
                    CASE
                        WHEN LOWER(winner) = 'red'
                        THEN 1
                        ELSE 0
                    END
                ) AS red_wins

            FROM matches
            """
        )

        side_row = (
            cursor.fetchone()
        )

        blue_wins = (
            side_row["blue_wins"]
            or 0
        )

        red_wins = (
            side_row["red_wins"]
            or 0
        )

        finished_games = (
            blue_wins
            + red_wins
        )

        blue_win_rate = (
            round(
                blue_wins
                / finished_games
                * 100,
                1
            )
            if finished_games > 0
            else 0
        )

        red_win_rate = (
            round(
                red_wins
                / finished_games
                * 100,
                1
            )
            if finished_games > 0
            else 0
        )


        # ==============================
        # 레이팅 TOP 5
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
                losses,
                mvp,
                best_win_streak

            FROM players

            ORDER BY
                rating DESC,
                wins DESC,
                mvp DESC

            LIMIT 5
            """
        )

        top_rating_players = [
            dict(row)
            for row in cursor.fetchall()
        ]


        # ==============================
        # MVP TOP 5
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
                losses,
                mvp,
                best_win_streak

            FROM players

            WHERE mvp > 0

            ORDER BY
                mvp DESC,
                rating DESC,
                wins DESC

            LIMIT 5
            """
        )

        top_mvp_players = [
            dict(row)
            for row in cursor.fetchall()
        ]


        # ==============================
        # 최다 참가 TOP 5
        # ==============================

        cursor.execute(
            """
            SELECT
                p.id,
                p.discord_nickname,
                p.riot_name,
                p.tier,
                p.rating,

                COUNT(mp.match_id)
                    AS games,

                SUM(
                    CASE
                        WHEN mp.won = 1
                        THEN 1
                        ELSE 0
                    END
                ) AS wins

            FROM players p

            LEFT JOIN match_players mp
                ON mp.discord_id
                    = p.discord_id

            GROUP BY
                p.id,
                p.discord_nickname,
                p.riot_name,
                p.tier,
                p.rating

            ORDER BY
                games DESC,
                wins DESC,
                p.rating DESC

            LIMIT 5
            """
        )

        most_active_players = []

        for row in cursor.fetchall():

            player = dict(
                row
            )

            games = (
                player["games"]
                or 0
            )

            wins = (
                player["wins"]
                or 0
            )

            losses = (
                games
                - wins
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

            player["losses"] = (
                losses
            )

            player["win_rate"] = (
                win_rate
            )

            most_active_players.append(
                player
            )


        # ==============================
        # 승률 TOP 5
        # 최소 3경기
        # ==============================

        cursor.execute(
            """
            SELECT
                p.id,
                p.discord_nickname,
                p.riot_name,
                p.tier,
                p.rating,

                COUNT(mp.match_id)
                    AS games,

                SUM(
                    CASE
                        WHEN mp.won = 1
                        THEN 1
                        ELSE 0
                    END
                ) AS wins

            FROM players p

            JOIN match_players mp
                ON mp.discord_id
                    = p.discord_id

            GROUP BY
                p.id,
                p.discord_nickname,
                p.riot_name,
                p.tier,
                p.rating

            HAVING COUNT(mp.match_id) >= 3

            ORDER BY

                (
                    CAST(
                        SUM(
                            CASE
                                WHEN mp.won = 1
                                THEN 1
                                ELSE 0
                            END
                        )
                        AS REAL
                    )
                    /
                    COUNT(mp.match_id)
                ) DESC,

                COUNT(mp.match_id) DESC,

                p.rating DESC

            LIMIT 5
            """
        )

        top_winrate_players = []

        for row in cursor.fetchall():

            player = dict(
                row
            )

            games = (
                player["games"]
                or 0
            )

            wins = (
                player["wins"]
                or 0
            )

            player["losses"] = (
                games
                - wins
            )

            player["win_rate"] = (
                round(
                    wins
                    / games
                    * 100,
                    1
                )
                if games > 0
                else 0
            )

            top_winrate_players.append(
                player
            )


        # ==============================
        # 최고 연승 TOP 5
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
                losses,
                win_streak,
                best_win_streak,
                mvp

            FROM players

            WHERE best_win_streak > 0

            ORDER BY
                best_win_streak DESC,
                rating DESC,
                wins DESC

            LIMIT 5
            """
        )

        top_streak_players = [
            dict(row)
            for row in cursor.fetchall()
        ]


        # ==============================
        # 포지션 통계
        # ==============================

        cursor.execute(
            """
            SELECT

                COALESCE(
                    position,
                    'UNKNOWN'
                ) AS position,

                COUNT(*) AS games,

                SUM(
                    CASE
                        WHEN won = 1
                        THEN 1
                        ELSE 0
                    END
                ) AS wins

            FROM match_players

            GROUP BY
                COALESCE(
                    position,
                    'UNKNOWN'
                )

            ORDER BY
                games DESC
            """
        )

        position_stats = []

        for row in cursor.fetchall():

            stat = dict(
                row
            )

            games = (
                stat["games"]
                or 0
            )

            wins = (
                stat["wins"]
                or 0
            )

            stat["losses"] = (
                games
                - wins
            )

            stat["win_rate"] = (
                round(
                    wins
                    / games
                    * 100,
                    1
                )
                if games > 0
                else 0
            )

            position_stats.append(
                stat
            )


        # ==============================
        # 최근 20경기 진영 흐름
        # ==============================

        cursor.execute(
            """
            SELECT
                id,
                winner,
                match_date

            FROM matches

            WHERE LOWER(winner)
                IN (
                    'blue',
                    'red'
                )

            ORDER BY
                id DESC

            LIMIT 20
            """
        )

        recent_side_rows = (
            cursor.fetchall()
        )

        recent_side_results = [
            dict(row)
            for row in reversed(
                recent_side_rows
            )
        ]

        recent_blue_wins = sum(
            1
            for match in recent_side_results
            if (
                match["winner"]
                or ""
            ).lower() == "blue"
        )

        recent_red_wins = sum(
            1
            for match in recent_side_results
            if (
                match["winner"]
                or ""
            ).lower() == "red"
        )

        recent_side_game_count = (
            len(
                recent_side_results
            )
        )

        recent_blue_win_rate = (
            round(
                recent_blue_wins
                / recent_side_game_count
                * 100,
                1
            )
            if recent_side_game_count > 0
            else 0
        )

        recent_red_win_rate = (
            round(
                recent_red_wins
                / recent_side_game_count
                * 100,
                1
            )
            if recent_side_game_count > 0
            else 0
        )


        # ==============================
        # 최근 상승/하락세 계산
        # ==============================

        cursor.execute(
            """
            SELECT
                id,
                discord_id,
                discord_nickname,
                riot_name,
                tier,
                rating

            FROM players
            """
        )

        all_players = (
            cursor.fetchall()
        )

        trend_players = []

        for player_row in all_players:

            player = dict(
                player_row
            )

            discord_id = str(
                player["discord_id"]
            )

            cursor.execute(
                """
                SELECT
                    won,
                    rating_change

                FROM match_players

                WHERE discord_id = ?

                ORDER BY
                    match_id DESC

                LIMIT 5
                """,
                (
                    discord_id,
                )
            )

            recent_rows = (
                cursor.fetchall()
            )

            recent_games = (
                len(
                    recent_rows
                )
            )

            if recent_games == 0:
                continue

            recent_wins = sum(
                1
                for game in recent_rows
                if game["won"]
            )

            recent_losses = (
                recent_games
                - recent_wins
            )

            recent_rating_change = sum(
                game["rating_change"]
                or 0
                for game in recent_rows
            )

            recent_win_rate = (
                round(
                    recent_wins
                    / recent_games
                    * 100,
                    1
                )
                if recent_games > 0
                else 0
            )

            player["recent_games"] = (
                recent_games
            )

            player["recent_wins"] = (
                recent_wins
            )

            player["recent_losses"] = (
                recent_losses
            )

            player["recent_win_rate"] = (
                recent_win_rate
            )

            player["recent_rating_change"] = (
                recent_rating_change
            )

            trend_players.append(
                player
            )


        top_trending_players = sorted(
            trend_players,
            key=lambda player: (
                player[
                    "recent_rating_change"
                ],
                player[
                    "recent_win_rate"
                ],
                player[
                    "rating"
                ]
            ),
            reverse=True
        )[:5]


        top_declining_players = sorted(
            trend_players,
            key=lambda player: (
                player[
                    "recent_rating_change"
                ],
                player[
                    "recent_win_rate"
                ],
                player[
                    "rating"
                ]
            )
        )[:5]


        # ==============================
        # 티어 분포
        # ==============================

        cursor.execute(
            """
            SELECT

                COALESCE(
                    NULLIF(
                        TRIM(tier),
                        ''
                    ),
                    '미설정'
                ) AS tier,

                COUNT(*)
                    AS player_count,

                AVG(rating)
                    AS average_rating

            FROM players

            GROUP BY
                COALESCE(
                    NULLIF(
                        TRIM(tier),
                        ''
                    ),
                    '미설정'
                )

            ORDER BY
                player_count DESC,
                average_rating DESC
            """
        )

        tier_stats = []

        for row in cursor.fetchall():

            stat = dict(
                row
            )

            stat["average_rating"] = round(
                stat["average_rating"]
                or 0,
                1
            )

            stat["percentage"] = (
                round(
                    stat["player_count"]
                    / player_count
                    * 100,
                    1
                )
                if player_count > 0
                else 0
            )

            tier_stats.append(
                stat
            )


    return {
        "success":
            True,

        "summary": {

            "player_count":
                player_count,

            "match_count":
                match_count,

            "average_rating":
                average_rating,

            "total_mvp":
                total_mvp
        },

        "side": {

            "blue_wins":
                blue_wins,

            "red_wins":
                red_wins,

            "blue_win_rate":
                blue_win_rate,

            "red_win_rate":
                red_win_rate
        },

        "recent_side": {

            "games":
                recent_side_game_count,

            "blue_wins":
                recent_blue_wins,

            "red_wins":
                recent_red_wins,

            "blue_win_rate":
                recent_blue_win_rate,

            "red_win_rate":
                recent_red_win_rate,

            "results":
                recent_side_results
        },

        "top_rating_players":
            top_rating_players,

        "top_mvp_players":
            top_mvp_players,

        "most_active_players":
            most_active_players,

        "top_winrate_players":
            top_winrate_players,

        "top_streak_players":
            top_streak_players,

        "top_trending_players":
            top_trending_players,

        "top_declining_players":
            top_declining_players,

        "position_stats":
            position_stats,

        "tier_stats":
            tier_stats
    }