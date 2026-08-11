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


@router.get("/season")
def season_page(
    request: Request
):

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

        active_season = (
            cursor.fetchone()
        )

        # ==============================
        # 활성 시즌 없음
        # ==============================

        if active_season is None:

            return templates.TemplateResponse(
                request=request,
                name="season.html",
                context={
                    "active_season":
                        None,

                    "season_players":
                        [],

                    "season_match_count":
                        0,

                    "season_player_count":
                        0,

                    "season_mvp":
                        None,

                    "best_win_streak_player":
                        None,

                    "best_winrate_player":
                        None,

                    "most_games_player":
                        None
                }
            )

        season_id = (
            active_season["id"]
        )

        # ==============================
        # 시즌 랭킹
        #
        # 정렬 기준
        # 1. 레이팅
        # 2. 승
        # 3. 패 적은 순
        # 4. discord_id
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

        for row in season_rows:

            player = dict(row)

            total_games = (
                player["wins"]
                + player["losses"]
            )

            player["games"] = (
                total_games
            )

            player["win_rate"] = (
                round(
                    player["wins"]
                    / total_games
                    * 100,
                    1
                )
                if total_games > 0
                else 0
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
            cursor.fetchone()["count"]
            or 0
        )

        # ==============================
        # 시즌 실제 참가자 수
        #
        # season_player_stats에 행만 있는
        # 플레이어가 아니라 실제 경기 참가 기준
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
            cursor.fetchone()["count"]
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

        season_mvp = (
            cursor.fetchone()
        )

        # ==============================
        # 최고 연승 플레이어
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

        best_win_streak_player = (
            cursor.fetchone()
        )

        # ==============================
        # 최고 승률 플레이어
        #
        # 최소 3경기 이상
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
                            / (
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

        best_winrate_player = (
            cursor.fetchone()
        )

        # ==============================
        # 최다 참가 플레이어
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

        most_games_player = (
            cursor.fetchone()
        )

    return templates.TemplateResponse(
        request=request,
        name="season.html",
        context={
            "active_season":
                active_season,

            "season_players":
                season_players,

            "season_match_count":
                season_match_count,

            "season_player_count":
                season_player_count,

            "season_mvp":
                season_mvp,

            "best_win_streak_player":
                best_win_streak_player,

            "best_winrate_player":
                best_winrate_player,

            "most_games_player":
                most_games_player
        }
    )