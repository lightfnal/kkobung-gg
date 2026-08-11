from fastapi import (
    APIRouter,
    Request
)

from fastapi.templating import (
    Jinja2Templates
)

from web.database import (
    get_db_connection
)


router = APIRouter()

templates = Jinja2Templates(
    directory="web/templates"
)


@router.get("/stats")
def stats_page(
    request: Request
):

    with get_db_connection() as conn:

        cursor = conn.cursor()

        # ==============================
        # 전체 플레이어
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
        # 전체 경기
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
        # 평균 / 최고 레이팅
        # ==============================

        cursor.execute(
            """
            SELECT
                AVG(rating) AS average_rating,
                MAX(rating) AS highest_rating
            FROM players
            """
        )

        rating_summary = (
            cursor.fetchone()
        )

        average_rating = round(
            rating_summary["average_rating"]
            or 0,
            1
        )

        highest_rating = (
            rating_summary["highest_rating"]
            or 0
        )

        # ==============================
        # 실제 경기 기록 기준 MVP 횟수
        # ==============================

        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM matches
            WHERE mvp_discord_id IS NOT NULL
              AND TRIM(mvp_discord_id) != ''
            """
        )

        total_mvp = (
            cursor.fetchone()["count"]
            or 0
        )

        # ==============================
        # 블루 / 레드 승리
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

        side = cursor.fetchone()

        blue_wins = (
            side["blue_wins"]
            or 0
        )

        red_wins = (
            side["red_wins"]
            or 0
        )

        finished_match_count = (
            blue_wins
            + red_wins
        )

        if finished_match_count > 0:

            blue_win_rate = round(
                blue_wins
                / finished_match_count
                * 100,
                1
            )

            red_win_rate = round(
                red_wins
                / finished_match_count
                * 100,
                1
            )

        else:

            blue_win_rate = 0
            red_win_rate = 0

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
                mvp DESC,
                id ASC

            LIMIT 5
            """
        )

        top_rating_players = (
            cursor.fetchall()
        )

        # ==============================
        # MVP TOP 5
        #
        # players.mvp가 아니라
        # 실제 matches 기록 기준
        # ==============================

        cursor.execute(
            """
            SELECT
                p.id,
                p.discord_id,
                p.discord_nickname,
                p.riot_name,
                p.tier,
                p.rating,
                p.wins,
                p.losses,

                COUNT(m.id) AS mvp

            FROM matches m

            JOIN players p
                ON p.discord_id
                    = m.mvp_discord_id

            WHERE m.mvp_discord_id IS NOT NULL
              AND TRIM(m.mvp_discord_id) != ''

            GROUP BY
                p.id,
                p.discord_id,
                p.discord_nickname,
                p.riot_name,
                p.tier,
                p.rating,
                p.wins,
                p.losses

            ORDER BY
                mvp DESC,
                p.rating DESC,
                p.wins DESC,
                p.id ASC

            LIMIT 5
            """
        )

        top_mvp_players = (
            cursor.fetchall()
        )

        # ==============================
        # 최다 참가 TOP 5
        #
        # 실제 match_players 기록 기준
        # 경기 0회 플레이어 제외
        # ==============================

        cursor.execute(
            """
            SELECT
                p.id,
                p.discord_id,
                p.discord_nickname,
                p.riot_name,
                p.tier,
                p.rating,

                COUNT(mp.match_id) AS games,

                SUM(
                    CASE
                        WHEN mp.won = 1
                        THEN 1
                        ELSE 0
                    END
                ) AS wins

            FROM match_players mp

            JOIN players p
                ON p.discord_id
                    = mp.discord_id

            GROUP BY
                p.id,
                p.discord_id,
                p.discord_nickname,
                p.riot_name,
                p.tier,
                p.rating

            ORDER BY
                games DESC,
                wins DESC,
                p.rating DESC,
                p.id ASC

            LIMIT 5
            """
        )

        most_active_players = []

        for row in cursor.fetchall():

            player = dict(row)

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

            most_active_players.append(
                player
            )

        # ==============================
        # 승률 TOP 5
        #
        # 최소 3경기
        # ==============================

        cursor.execute(
            """
            SELECT
                p.id,
                p.discord_id,
                p.discord_nickname,
                p.riot_name,
                p.tier,
                p.rating,

                COUNT(mp.match_id) AS games,

                SUM(
                    CASE
                        WHEN mp.won = 1
                        THEN 1
                        ELSE 0
                    END
                ) AS wins

            FROM match_players mp

            JOIN players p
                ON p.discord_id
                    = mp.discord_id

            GROUP BY
                p.id,
                p.discord_id,
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
                p.rating DESC,
                p.id ASC

            LIMIT 5
            """
        )

        top_winrate_players = []

        for row in cursor.fetchall():

            player = dict(row)

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
                wins DESC,
                id ASC

            LIMIT 5
            """
        )

        top_streak_players = (
            cursor.fetchall()
        )

        # ==============================
        # 포지션별 기록
        #
        # games는 실제 경기 수가 아니라
        # 해당 포지션으로 출전한 선수-경기 수
        # ==============================

        cursor.execute(
            """
            SELECT

                COALESCE(
                    NULLIF(
                        TRIM(position),
                        ''
                    ),
                    'UNKNOWN'
                ) AS position,

                COUNT(*) AS games,

                COUNT(
                    DISTINCT discord_id
                ) AS player_count,

                SUM(
                    CASE
                        WHEN won = 1
                        THEN 1
                        ELSE 0
                    END
                ) AS wins,

                AVG(
                    COALESCE(
                        rating_change,
                        0
                    )
                ) AS average_rating_change

            FROM match_players

            GROUP BY
                COALESCE(
                    NULLIF(
                        TRIM(position),
                        ''
                    ),
                    'UNKNOWN'
                )

            ORDER BY
                games DESC,
                position ASC
            """
        )

        position_stats = []

        for row in cursor.fetchall():

            stat = dict(row)

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

            stat[
                "average_rating_change"
            ] = round(
                stat[
                    "average_rating_change"
                ]
                or 0,
                1
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
                IN ('blue', 'red')

            ORDER BY id DESC

            LIMIT 20
            """
        )

        recent_side_results = list(
            reversed(
                cursor.fetchall()
            )
        )

        recent_side_game_count = len(
            recent_side_results
        )

        recent_blue_wins = sum(
            1
            for match in recent_side_results
            if (
                match["winner"]
                or ""
            ).lower() == "blue"
        )

        recent_red_wins = (
            recent_side_game_count
            - recent_blue_wins
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
        # 최근 5경기 폼
        #
        # Window Function을 사용해서
        # 플레이어별 SQL 반복을 제거합니다.
        # ==============================

        cursor.execute(
            """
            WITH ranked_matches AS (

                SELECT
                    mp.discord_id,
                    mp.won,
                    mp.rating_change,
                    mp.match_id,

                    ROW_NUMBER() OVER (
                        PARTITION BY
                            mp.discord_id

                        ORDER BY
                            mp.match_id DESC
                    ) AS row_number

                FROM match_players mp
            ),

            recent_form AS (

                SELECT
                    discord_id,

                    COUNT(*) AS recent_games,

                    SUM(
                        CASE
                            WHEN won = 1
                            THEN 1
                            ELSE 0
                        END
                    ) AS recent_wins,

                    SUM(
                        COALESCE(
                            rating_change,
                            0
                        )
                    ) AS recent_rating_change

                FROM ranked_matches

                WHERE row_number <= 5

                GROUP BY
                    discord_id
            )

            SELECT
                p.id,
                p.discord_id,
                p.discord_nickname,
                p.riot_name,
                p.tier,
                p.rating,

                rf.recent_games,
                rf.recent_wins,
                rf.recent_rating_change

            FROM recent_form rf

            JOIN players p
                ON p.discord_id
                    = rf.discord_id
            """
        )

        recent_form_players = []

        for row in cursor.fetchall():

            player = dict(row)

            recent_games = (
                player["recent_games"]
                or 0
            )

            recent_wins = (
                player["recent_wins"]
                or 0
            )

            recent_losses = (
                recent_games
                - recent_wins
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

            player["recent_losses"] = (
                recent_losses
            )

            player["recent_win_rate"] = (
                recent_win_rate
            )

            player["recent_rating_change"] = (
                player[
                    "recent_rating_change"
                ]
                or 0
            )

            recent_form_players.append(
                player
            )

        # ==============================
        # 최근 상승세
        #
        # 실제 총 LP 변화가 양수인 선수만
        # ==============================

        rising_players = [
            player
            for player in recent_form_players
            if (
                player[
                    "recent_rating_change"
                ]
                > 0
            )
        ]

        rising_players.sort(
            key=lambda player: (
                -player[
                    "recent_rating_change"
                ],
                -player[
                    "recent_win_rate"
                ],
                -player[
                    "rating"
                ],
                player[
                    "id"
                ]
            )
        )

        top_trending_players = (
            rising_players[:5]
        )

        # ==============================
        # 최근 하락세
        #
        # 실제 총 LP 변화가 음수인 선수만
        # ==============================

        declining_players = [
            player
            for player in recent_form_players
            if (
                player[
                    "recent_rating_change"
                ]
                < 0
            )
        ]

        declining_players.sort(
            key=lambda player: (
                player[
                    "recent_rating_change"
                ],
                player[
                    "recent_win_rate"
                ],
                player[
                    "rating"
                ],
                player[
                    "id"
                ]
            )
        )

        top_declining_players = (
            declining_players[:5]
        )

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

                COUNT(*) AS player_count,

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
                average_rating DESC,
                tier ASC
            """
        )

        tier_stats = []

        for row in cursor.fetchall():

            stat = dict(row)

            stat[
                "average_rating"
            ] = round(
                stat[
                    "average_rating"
                ]
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

    return templates.TemplateResponse(
        request=request,
        name="stats.html",
        context={

            "player_count":
                player_count,

            "match_count":
                match_count,

            "finished_match_count":
                finished_match_count,

            "average_rating":
                average_rating,

            "highest_rating":
                highest_rating,

            "total_mvp":
                total_mvp,

            "blue_wins":
                blue_wins,

            "red_wins":
                red_wins,

            "blue_win_rate":
                blue_win_rate,

            "red_win_rate":
                red_win_rate,

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
                tier_stats,

            "recent_side_results":
                recent_side_results,

            "recent_side_game_count":
                recent_side_game_count,

            "recent_blue_wins":
                recent_blue_wins,

            "recent_red_wins":
                recent_red_wins,

            "recent_blue_win_rate":
                recent_blue_win_rate,

            "recent_red_win_rate":
                recent_red_win_rate
        }
    )