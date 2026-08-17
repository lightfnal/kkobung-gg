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


def calculate_recent_form(
    rows
):
    """
    최근 경기 목록을 받아서
    전적 / 승률 / LP 변화량을 계산합니다.
    """

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

    rating_change = sum(
        row["rating_change"] or 0
        for row in rows
    )

    return {
        "games": games,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "rating_change": rating_change
    }


@router.get("/analysis")
def analysis_page(
    request: Request,
    player_id: int | None = None,
    scope: str = "season"
):

    with get_db_connection() as conn:

        cursor = conn.cursor()

        # 기본 분석 범위는 현재 진행 중인 시즌입니다.
        # 과거 테스트 경기는 사용자가 "전체 기록"을 선택할 때만 포함합니다.
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
        analysis_scope = (
            "all"
            if scope == "all"
            else "season"
        )
        scope_season_id = (
            active_season["id"]
            if analysis_scope == "season"
            and active_season is not None
            else (
                -1
                if analysis_scope == "season"
                else None
            )
        )
        scope_label = (
            active_season["season_name"]
            if analysis_scope == "season"
            and active_season is not None
            else (
                "현재 시즌"
                if analysis_scope == "season"
                else "전체 기록"
            )
        )

        # ==============================
        # 플레이어 선택 목록
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

        selected_player = None

        analysis = None

        recent_5 = None
        recent_10 = None
        recent_20 = None

        recent_results = []
        rating_history = []

        position_stats = []
        best_duos = []
        opponent_stats = []

        season_stats = None

        # ==============================
        # 플레이어 선택
        # ==============================

        if player_id is not None:

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
                    hidden_mmr,
                    placement_games,
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
                    player_id,
                )
            )

            selected_player = (
                cursor.fetchone()
            )

            # ==============================
            # 존재하는 플레이어만 분석
            # ==============================

            if selected_player is not None:

                discord_id = str(
                    selected_player[
                        "discord_id"
                    ]
                )

                # ==============================
                # 전체 순위
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
                        selected_player["rating"],
                        selected_player["rating"],
                        selected_player["id"]
                    )
                )

                player_rank = (
                    cursor.fetchone()["count"]
                    + 1
                )

                cursor.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM players
                    """
                )

                total_player_count = (
                    cursor.fetchone()["count"]
                    or 0
                )

                top_percent = (
                    round(
                        player_rank
                        / total_player_count
                        * 100,
                        1
                    )
                    if total_player_count > 0
                    else 0
                )

                # ==============================
                # 전체 경기 통계
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
                        ) AS total_rating_change,

                        SUM(
                            CASE
                                WHEN LOWER(team) = 'blue'
                                THEN 1
                                ELSE 0
                            END
                        ) AS blue_games,

                        SUM(
                            CASE
                                WHEN LOWER(team) = 'blue'
                                AND won = 1
                                THEN 1
                                ELSE 0
                            END
                        ) AS blue_wins,

                        SUM(
                            CASE
                                WHEN LOWER(team) = 'red'
                                THEN 1
                                ELSE 0
                            END
                        ) AS red_games,

                        SUM(
                            CASE
                                WHEN LOWER(team) = 'red'
                                AND won = 1
                                THEN 1
                                ELSE 0
                            END
                        ) AS red_wins

                    FROM match_players mp
                    JOIN matches m
                        ON m.id = mp.match_id

                    WHERE mp.discord_id = ?
                      AND (
                          ? IS NULL
                          OR m.season_id = ?
                      )
                    """,
                    (
                        discord_id,
                        scope_season_id,
                        scope_season_id,
                    )
                )

                row = (
                    cursor.fetchone()
                )

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

                avg_rating_change = round(
                    row["avg_rating_change"]
                    or 0,
                    1
                )

                total_rating_change = (
                    row["total_rating_change"]
                    or 0
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

                # ==============================
                # 진영 기록
                # ==============================

                blue_games = (
                    row["blue_games"]
                    or 0
                )

                blue_wins = (
                    row["blue_wins"]
                    or 0
                )

                red_games = (
                    row["red_games"]
                    or 0
                )

                red_wins = (
                    row["red_wins"]
                    or 0
                )

                blue_win_rate = (
                    round(
                        blue_wins
                        / blue_games
                        * 100,
                        1
                    )
                    if blue_games > 0
                    else 0
                )

                red_win_rate = (
                    round(
                        red_wins
                        / red_games
                        * 100,
                        1
                    )
                    if red_games > 0
                    else 0
                )

                # ==============================
                # 실제 경기 MVP 횟수
                # ==============================

                cursor.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM matches m
                    WHERE m.mvp_discord_id = ?
                      AND (
                          ? IS NULL
                          OR m.season_id = ?
                      )
                    """,
                    (
                        discord_id,
                        scope_season_id,
                        scope_season_id,
                    )
                )

                actual_mvp_count = (
                    cursor.fetchone()["count"]
                    or 0
                )

                mvp_rate = (
                    round(
                        actual_mvp_count
                        / games
                        * 100,
                        1
                    )
                    if games > 0
                    else 0
                )

                # ==============================
                # 최근 최대 20경기
                # ==============================

                cursor.execute(
                    """
                    SELECT
                        m.id AS match_id,
                        m.match_date,
                        m.winner,
                        mp.team,
                        mp.position,
                        mp.won,
                        mp.rating_before,
                        mp.rating_after,
                        mp.rating_change
                    FROM match_players mp
                    JOIN matches m
                        ON m.id = mp.match_id
                    WHERE mp.discord_id = ?
                      AND (
                          ? IS NULL
                          OR m.season_id = ?
                      )
                    ORDER BY m.id DESC
                    LIMIT 20
                    """,
                    (
                        discord_id,
                        scope_season_id,
                        scope_season_id,
                    )
                )

                recent_rows_desc = list(
                    cursor.fetchall()
                )

                recent_5 = calculate_recent_form(
                    recent_rows_desc[:5]
                )

                recent_10 = calculate_recent_form(
                    recent_rows_desc[:10]
                )

                recent_20 = calculate_recent_form(
                    recent_rows_desc[:20]
                )

                # 그래프와 W/L 스트립은
                # 오래된 경기 → 최근 경기 순서
                recent_results = list(
                    reversed(
                        recent_rows_desc
                    )
                )

                # ==============================
                # 최근 레이팅 흐름
                # ==============================

                rating_history = [
                    {
                        "match_id":
                            row["match_id"],

                        "match_date":
                            row["match_date"],

                        "rating_before":
                            row["rating_before"],

                        "rating_after":
                            row["rating_after"],

                        "rating_change":
                            row["rating_change"]
                            or 0,

                        "won":
                            bool(
                                row["won"]
                            )
                    }
                    for row in recent_results
                ]

                # ==============================
                # 최근 폼 판정
                # ==============================

                recent_form_code = "neutral"
                recent_form_text = "보통"

                if (
                    recent_5["games"] >= 3
                    and recent_5["win_rate"] >= 70
                    and recent_5["rating_change"] > 0
                ):
                    recent_form_code = "hot"
                    recent_form_text = "매우 좋음"

                elif (
                    recent_5["games"] >= 3
                    and recent_5["win_rate"] >= 55
                    and recent_5["rating_change"] > 0
                ):
                    recent_form_code = "good"
                    recent_form_text = "상승세"

                elif (
                    recent_5["games"] >= 3
                    and recent_5["win_rate"] <= 30
                    and recent_5["rating_change"] < 0
                ):
                    recent_form_code = "cold"
                    recent_form_text = "하락세"

                elif (
                    recent_5["games"] >= 3
                    and recent_5["win_rate"] < 50
                    and recent_5["rating_change"] < 0
                ):
                    recent_form_code = "bad"
                    recent_form_text = "부진"

                # ==============================
                # 핵심 분석
                # ==============================

                analysis = {
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

                    "actual_mvp_count":
                        actual_mvp_count,

                    "mvp_rate":
                        mvp_rate,

                    "blue_games":
                        blue_games,

                    "blue_wins":
                        blue_wins,

                    "blue_win_rate":
                        blue_win_rate,

                    "red_games":
                        red_games,

                    "red_wins":
                        red_wins,

                    "red_win_rate":
                        red_win_rate,

                    "player_rank":
                        player_rank,

                    "total_player_count":
                        total_player_count,

                    "top_percent":
                        top_percent,

                    "recent_form_code":
                        recent_form_code,

                    "recent_form_text":
                        recent_form_text
                }

                # ==============================
                # 현재 활성 시즌
                # ==============================

                if active_season is not None:

                    cursor.execute(
                        """
                        SELECT
                            rating,
                            wins,
                            losses,
                            win_streak,
                            lose_streak,
                            best_win_streak,
                            mvp
                        FROM season_player_stats
                        WHERE season_id = ?
                          AND discord_id = ?
                        """,
                        (
                            active_season["id"],
                            discord_id
                        )
                    )

                    season_row = (
                        cursor.fetchone()
                    )

                    if season_row is not None:

                        season_stats = dict(
                            season_row
                        )

                        season_games = (
                            season_stats["wins"]
                            + season_stats["losses"]
                        )

                        season_stats[
                            "games"
                        ] = season_games

                        season_stats[
                            "win_rate"
                        ] = (
                            round(
                                season_stats["wins"]
                                / season_games
                                * 100,
                                1
                            )
                            if season_games > 0
                            else 0
                        )

                # ==============================
                # 포지션별 성적
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
                      AND (
                          ? IS NULL
                          OR m.season_id = ?
                      )

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
                        discord_id,
                        scope_season_id,
                        scope_season_id,
                    )
                )

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
                        round(
                            stat["wins"]
                            / stat["games"]
                            * 100,
                            1
                        )
                        if stat["games"] > 0
                        else 0
                    )

                    stat[
                        "avg_rating_change"
                    ] = round(
                        stat[
                            "avg_rating_change"
                        ]
                        or 0,
                        1
                    )

                    stat[
                        "total_rating_change"
                    ] = (
                        stat[
                            "total_rating_change"
                        ]
                        or 0
                    )

                    position_stats.append(
                        stat
                    )

                # ==============================
                # 자주 함께한 플레이어 TOP 5
                # ==============================

                cursor.execute(
                    """
                    SELECT
                        teammate.discord_id,

                        p.id AS player_id,
                        p.discord_nickname,
                        p.riot_name,
                        p.tier,

                        COUNT(*) AS games,

                        SUM(
                            CASE
                                WHEN me.won = 1
                                THEN 1
                                ELSE 0
                            END
                        ) AS wins

                    FROM match_players me

                    JOIN matches m
                        ON m.id = me.match_id

                    JOIN match_players teammate
                        ON teammate.match_id = me.match_id
                        AND teammate.team = me.team
                        AND teammate.discord_id
                            != me.discord_id

                    LEFT JOIN players p
                        ON p.discord_id
                            = teammate.discord_id

                    WHERE me.discord_id = ?
                      AND (
                          ? IS NULL
                          OR m.season_id = ?
                      )

                    GROUP BY
                        teammate.discord_id,
                        p.id,
                        p.discord_nickname,
                        p.riot_name,
                        p.tier

                    ORDER BY
                        games DESC,
                        wins DESC

                    LIMIT 5
                    """,
                    (
                        discord_id,
                        scope_season_id,
                        scope_season_id,
                    )
                )

                for row in cursor.fetchall():

                    duo = dict(
                        row
                    )

                    duo["games"] = (
                        duo["games"]
                        or 0
                    )

                    duo["wins"] = (
                        duo["wins"]
                        or 0
                    )

                    duo["losses"] = (
                        duo["games"]
                        - duo["wins"]
                    )

                    duo["win_rate"] = (
                        round(
                            duo["wins"]
                            / duo["games"]
                            * 100,
                            1
                        )
                        if duo["games"] > 0
                        else 0
                    )

                    best_duos.append(
                        duo
                    )

                # ==============================
                # 자주 만난 상대 TOP 5
                # ==============================

                cursor.execute(
                    """
                    SELECT
                        opponent.discord_id,

                        p.id AS player_id,
                        p.discord_nickname,
                        p.riot_name,
                        p.tier,

                        COUNT(*) AS games,

                        SUM(
                            CASE
                                WHEN me.won = 1
                                THEN 1
                                ELSE 0
                            END
                        ) AS wins

                    FROM match_players me

                    JOIN matches m
                        ON m.id = me.match_id

                    JOIN match_players opponent
                        ON opponent.match_id = me.match_id
                        AND opponent.team != me.team

                    LEFT JOIN players p
                        ON p.discord_id
                            = opponent.discord_id

                    WHERE me.discord_id = ?
                      AND (
                          ? IS NULL
                          OR m.season_id = ?
                      )

                    GROUP BY
                        opponent.discord_id,
                        p.id,
                        p.discord_nickname,
                        p.riot_name,
                        p.tier

                    ORDER BY
                        games DESC,
                        wins DESC

                    LIMIT 5
                    """,
                    (
                        discord_id,
                        scope_season_id,
                        scope_season_id,
                    )
                )

                for row in cursor.fetchall():

                    opponent = dict(
                        row
                    )

                    opponent["games"] = (
                        opponent["games"]
                        or 0
                    )

                    opponent["wins"] = (
                        opponent["wins"]
                        or 0
                    )

                    opponent["losses"] = (
                        opponent["games"]
                        - opponent["wins"]
                    )

                    opponent["win_rate"] = (
                        round(
                            opponent["wins"]
                            / opponent["games"]
                            * 100,
                            1
                        )
                        if opponent["games"] > 0
                        else 0
                    )

                    opponent_stats.append(
                        opponent
                    )

    return templates.TemplateResponse(
        request=request,
        name="analysis.html",
        context={
            "players":
                players,

            "selected_player_id":
                player_id,

            "selected_player":
                selected_player,

            "analysis":
                analysis,

            "recent_5":
                recent_5,

            "recent_10":
                recent_10,

            "recent_20":
                recent_20,

            "recent_results":
                recent_results,

            "rating_history":
                rating_history,

            "position_stats":
                position_stats,

            "best_duos":
                best_duos,

            "opponent_stats":
                opponent_stats,

            "active_season":
                active_season,

            "season_stats":
                season_stats,

            "analysis_scope":
                analysis_scope,

            "scope_label":
                scope_label
        }
    )
