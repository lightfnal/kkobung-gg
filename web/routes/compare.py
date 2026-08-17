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


def calculate_win_rate(
    wins,
    games
):
    return (
        round(
            wins
            / games
            * 100,
            1
        )
        if games > 0
        else 0
    )


def get_recent_form(
    cursor,
    discord_id,
    season_id,
    limit=5
):
    """
    특정 플레이어의 최근 경기 폼을 반환합니다.
    """

    cursor.execute(
        """
        SELECT
            m.id AS match_id,
            m.match_date,
            mp.won,
            mp.rating_change,
            mp.rating_before,
            mp.rating_after
        FROM match_players mp
        JOIN matches m
            ON m.id = mp.match_id
        WHERE mp.discord_id = ?
          AND m.season_id = ?
        ORDER BY m.id DESC
        LIMIT ?
        """,
        (
            str(discord_id),
            season_id,
            limit
        )
    )

    rows = list(
        cursor.fetchall()
    )

    games = len(rows)

    wins = sum(
        1
        for row in rows
        if row["won"]
    )

    losses = (
        games
        - wins
    )

    win_rate = calculate_win_rate(
        wins,
        games
    )

    rating_change = sum(
        row["rating_change"] or 0
        for row in rows
    )

    # 화면 표시용으로 오래된 경기 → 최신 경기 순서
    results = list(
        reversed(
            rows
        )
    )

    return {
        "games": games,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "rating_change": rating_change,
        "results": results
    }


def get_position_stats(
    cursor,
    discord_id,
    season_id
):
    """
    포지션별 경기 성적을 반환합니다.
    """

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
            ) AS avg_rating_change

        FROM match_players mp

        JOIN matches m
            ON m.id = mp.match_id

        WHERE mp.discord_id = ?
          AND m.season_id = ?

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
            wins DESC
        """,
        (
            str(discord_id),
            season_id,
        )
    )

    position_stats = []

    for row in cursor.fetchall():

        stat = dict(
            row
        )

        stat["games"] = (
            stat["games"]
            or 0
        )

        stat["wins"] = (
            stat["wins"]
            or 0
        )

        stat["losses"] = (
            stat["games"]
            - stat["wins"]
        )

        stat["win_rate"] = (
            calculate_win_rate(
                stat["wins"],
                stat["games"]
            )
        )

        stat[
            "avg_rating_change"
        ] = round(
            stat["avg_rating_change"]
            or 0,
            1
        )

        position_stats.append(
            stat
        )

    return position_stats


def get_player_compare_data(
    cursor,
    player,
    season_id
):
    """
    비교 페이지에서 사용할 플레이어 전체 요약 데이터를 만듭니다.
    """

    discord_id = str(
        player["discord_id"]
    )

    # ==============================
    # 실제 경기 수 / 승패 / 평균 LP
    # ==============================

    cursor.execute(
        """
        SELECT
            COUNT(*) AS games,

            SUM(
                CASE
                    WHEN won = 1
                    THEN 1
                    ELSE 0
                END
            ) AS wins,

            SUM(
                CASE
                    WHEN won = 0
                    THEN 1
                    ELSE 0
                END
            ) AS losses,

            AVG(
                COALESCE(
                    rating_change,
                    0
                )
            ) AS avg_rating_change,

            SUM(
                COALESCE(
                    rating_change,
                    0
                )
            ) AS total_rating_change

        FROM match_players mp

        JOIN matches m
            ON m.id = mp.match_id

        WHERE mp.discord_id = ?
          AND m.season_id = ?
        """,
        (
            discord_id,
            season_id,
        )
    )

    row = cursor.fetchone()

    games = (
        row["games"]
        or 0
    )

    wins = (
        row["wins"]
        or 0
    )

    losses = (
        row["losses"]
        or 0
    )

    win_rate = calculate_win_rate(
        wins,
        games
    )

    avg_rating_change = round(
        row["avg_rating_change"]
        or 0,
        1
    )

    total_rating_change = (
        row["total_rating_change"]
        or 0
    )

    # ==============================
    # 실제 MVP 횟수
    # ==============================

    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM matches
        WHERE mvp_discord_id = ?
          AND season_id = ?
        """,
        (
            discord_id,
            season_id,
        )
    )

    mvp_count = (
        cursor.fetchone()["count"]
        or 0
    )

    mvp_rate = (
        round(
            mvp_count
            / games
            * 100,
            1
        )
        if games > 0
        else 0
    )

    # ==============================
    # 랭킹
    # ==============================

    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM players
        WHERE
            rating > ?
            OR (
                rating = ?
                AND id < ?
            )
        """,
        (
            player["rating"],
            player["rating"],
            player["id"]
        )
    )

    rank = (
        cursor.fetchone()["count"]
        + 1
    )

    # ==============================
    # 최근 5 / 10 / 20경기
    # ==============================

    recent_5 = get_recent_form(
        cursor,
        discord_id,
        season_id,
        5
    )

    recent_10 = get_recent_form(
        cursor,
        discord_id,
        season_id,
        10
    )

    recent_20 = get_recent_form(
        cursor,
        discord_id,
        season_id,
        20
    )

    # ==============================
    # 포지션 기록
    # ==============================

    position_stats = get_position_stats(
        cursor,
        discord_id,
        season_id
    )

    return {
        "player":
            player,

        "rank":
            rank,

        "games":
            games,

        "wins":
            wins,

        "losses":
            losses,

        "win_rate":
            win_rate,

        "avg_rating_change":
            avg_rating_change,

        "total_rating_change":
            total_rating_change,

        "mvp_count":
            mvp_count,

        "mvp_rate":
            mvp_rate,

        "recent_5":
            recent_5,

        "recent_10":
            recent_10,

        "recent_20":
            recent_20,

        "position_stats":
            position_stats
    }


@router.get("/compare")
def compare_page(
    request: Request,
    player1_id: int | None = None,
    player2_id: int | None = None
):

    with get_db_connection() as conn:

        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT
                id,
                season_name,
                started_at
            FROM seasons
            WHERE is_active = 1
            ORDER BY id DESC
            LIMIT 1
            """
        )

        active_season = cursor.fetchone()
        scope_season_id = (
            active_season["id"]
            if active_season is not None
            else -1
        )

        # ==============================
        # 비교 대상 선택 목록
        # ==============================

        cursor.execute(
            """
            SELECT
                id,
                discord_id,
                discord_nickname,
                riot_name,
                tier,
                rating,
                wins,
                losses
            FROM players
            ORDER BY
                rating DESC,
                wins DESC,
                discord_nickname ASC
            """
        )

        players = (
            cursor.fetchall()
        )

        player1 = None
        player2 = None

        player1_data = None
        player2_data = None

        head_to_head = None
        same_team = None

        # ==============================
        # 두 플레이어 선택 완료
        # ==============================

        if (
            player1_id is not None
            and player2_id is not None
        ):

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
                WHERE id = ?
                """,
                (
                    player1_id,
                )
            )

            player1 = (
                cursor.fetchone()
            )

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
                WHERE id = ?
                """,
                (
                    player2_id,
                )
            )

            player2 = (
                cursor.fetchone()
            )

            if (
                player1 is not None
                and player2 is not None
            ):

                player1_data = (
                    get_player_compare_data(
                        cursor,
                        player1,
                        scope_season_id
                    )
                )

                player2_data = (
                    get_player_compare_data(
                        cursor,
                        player2,
                        scope_season_id
                    )
                )

                player1_discord_id = str(
                    player1["discord_id"]
                )

                player2_discord_id = str(
                    player2["discord_id"]
                )

                # ==============================
                # 맞대결
                # ==============================

                cursor.execute(
                    """
                    SELECT
                        COUNT(*) AS games,

                        SUM(
                            CASE
                                WHEN p1.won = 1
                                THEN 1
                                ELSE 0
                            END
                        ) AS player1_wins,

                        SUM(
                            CASE
                                WHEN p2.won = 1
                                THEN 1
                                ELSE 0
                            END
                        ) AS player2_wins

                    FROM match_players p1

                    JOIN match_players p2
                        ON p1.match_id = p2.match_id
                        AND p1.team != p2.team

                    JOIN matches m
                        ON m.id = p1.match_id

                    WHERE p1.discord_id = ?
                      AND p2.discord_id = ?
                      AND m.season_id = ?
                    """,
                    (
                        player1_discord_id,
                        player2_discord_id,
                        scope_season_id
                    )
                )

                h2h_row = (
                    cursor.fetchone()
                )

                h2h_games = (
                    h2h_row["games"]
                    or 0
                )

                h2h_player1_wins = (
                    h2h_row[
                        "player1_wins"
                    ]
                    or 0
                )

                h2h_player2_wins = (
                    h2h_row[
                        "player2_wins"
                    ]
                    or 0
                )

                head_to_head = {
                    "games":
                        h2h_games,

                    "player1_wins":
                        h2h_player1_wins,

                    "player2_wins":
                        h2h_player2_wins,

                    "player1_win_rate":
                        calculate_win_rate(
                            h2h_player1_wins,
                            h2h_games
                        ),

                    "player2_win_rate":
                        calculate_win_rate(
                            h2h_player2_wins,
                            h2h_games
                        )
                }

                # ==============================
                # 같은 팀 성적
                # ==============================

                cursor.execute(
                    """
                    SELECT
                        COUNT(*) AS games,

                        SUM(
                            CASE
                                WHEN p1.won = 1
                                THEN 1
                                ELSE 0
                            END
                        ) AS wins

                    FROM match_players p1

                    JOIN match_players p2
                        ON p1.match_id = p2.match_id
                        AND p1.team = p2.team

                    JOIN matches m
                        ON m.id = p1.match_id

                    WHERE p1.discord_id = ?
                      AND p2.discord_id = ?
                      AND m.season_id = ?
                    """,
                    (
                        player1_discord_id,
                        player2_discord_id,
                        scope_season_id
                    )
                )

                same_team_row = (
                    cursor.fetchone()
                )

                same_team_games = (
                    same_team_row["games"]
                    or 0
                )

                same_team_wins = (
                    same_team_row["wins"]
                    or 0
                )

                same_team = {
                    "games":
                        same_team_games,

                    "wins":
                        same_team_wins,

                    "losses":
                        (
                            same_team_games
                            - same_team_wins
                        ),

                    "win_rate":
                        calculate_win_rate(
                            same_team_wins,
                            same_team_games
                        )
                }

    return templates.TemplateResponse(
        request=request,
        name="compare.html",
        context={
            "players":
                players,

            "player1_id":
                player1_id,

            "player2_id":
                player2_id,

            "player1":
                player1,

            "player2":
                player2,

            "player1_data":
                player1_data,

            "player2_data":
                player2_data,

            "head_to_head":
                head_to_head,

            "same_team":
                same_team,

            "active_season":
                active_season
        }
    )
