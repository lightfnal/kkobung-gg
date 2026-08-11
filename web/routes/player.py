from fastapi import (
    APIRouter,
    Request,
    HTTPException
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


@router.get("/player/{player_id}")
def player_detail(
    request: Request,
    player_id: int
):

    with get_db_connection() as conn:

        cursor = conn.cursor()

        # ==============================
        # 플레이어 기본 정보
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
            WHERE id = ?
            """,
            (
                player_id,
            )
        )

        player = cursor.fetchone()

        if player is None:
            raise HTTPException(
                status_code=404,
                detail="플레이어를 찾을 수 없습니다."
            )

        discord_id = str(
            player["discord_id"]
        )

        # ==============================
        # 전체 플레이어 수
        # ==============================

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

        # ==============================
        # 현재 순위
        # ranking.py와 동일한 기준
        #
        # 1. rating DESC
        # 2. wins DESC
        # 3. losses ASC
        # 4. id ASC
        # ==============================

        cursor.execute(
            """
            SELECT COUNT(*) AS count

            FROM players

            WHERE
                rating > ?

                OR (
                    rating = ?
                    AND wins > ?
                )

                OR (
                    rating = ?
                    AND wins = ?
                    AND losses < ?
                )

                OR (
                    rating = ?
                    AND wins = ?
                    AND losses = ?
                    AND id < ?
                )
            """,
            (
                player["rating"],

                player["rating"],
                player["wins"],

                player["rating"],
                player["wins"],
                player["losses"],

                player["rating"],
                player["wins"],
                player["losses"],
                player["id"]
            )
        )

        higher_player_count = (
            cursor.fetchone()["count"]
            or 0
        )

        player_rank = (
            higher_player_count + 1
        )

        # ==============================
        # 상위 퍼센트
        # ==============================

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

        active_season = (
            cursor.fetchone()
        )

        # ==============================
        # 현재 시즌 개인 기록
        # ==============================

        season_stats = None
        season_win_rate = 0
        season_rank = None
        season_player_count = 0

        if active_season is not None:

            season_id = (
                active_season["id"]
            )

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
                    season_id,
                    discord_id
                )
            )

            season_stats = (
                cursor.fetchone()
            )

            if season_stats is not None:

                season_total_games = (
                    season_stats["wins"]
                    + season_stats["losses"]
                )

                season_win_rate = (
                    round(
                        season_stats["wins"]
                        / season_total_games
                        * 100,
                        1
                    )
                    if season_total_games > 0
                    else 0
                )

                # ==============================
                # 시즌 순위
                #
                # 1. rating DESC
                # 2. wins DESC
                # 3. losses ASC
                # 4. discord_id ASC
                # ==============================

                cursor.execute(
                    """
                    SELECT COUNT(*) AS count

                    FROM season_player_stats

                    WHERE season_id = ?

                      AND (
                            rating > ?

                            OR (
                                rating = ?
                                AND wins > ?
                            )

                            OR (
                                rating = ?
                                AND wins = ?
                                AND losses < ?
                            )

                            OR (
                                rating = ?
                                AND wins = ?
                                AND losses = ?
                                AND discord_id < ?
                            )
                      )
                    """,
                    (
                        season_id,

                        season_stats["rating"],

                        season_stats["rating"],
                        season_stats["wins"],

                        season_stats["rating"],
                        season_stats["wins"],
                        season_stats["losses"],

                        season_stats["rating"],
                        season_stats["wins"],
                        season_stats["losses"],
                        discord_id
                    )
                )

                season_rank = (
                    cursor.fetchone()["count"]
                    + 1
                )

            # ==============================
            # 시즌 실제 참가자 수
            #
            # season_player_stats 행 개수가 아니라
            # 실제 해당 시즌 match_players 기록 기준
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
        # 최근 5경기
        # ==============================

        cursor.execute(
            """
            SELECT
                m.id AS match_id,
                m.match_date,
                m.winner,
                m.mvp_discord_id,

                mp.team,
                mp.won,
                mp.position,
                mp.rating_before,
                mp.rating_after,
                mp.rating_change

            FROM match_players mp

            JOIN matches m
                ON m.id = mp.match_id

            WHERE mp.discord_id = ?

            ORDER BY
                m.id DESC

            LIMIT 5
            """,
            (
                discord_id,
            )
        )

        recent_matches = (
            cursor.fetchall()
        )

        # ==============================
        # 최근 5경기 폼
        # ==============================

        recent_5_win_count = sum(
            1
            for match in recent_matches
            if match["won"]
        )

        recent_5_loss_count = (
            len(recent_matches)
            - recent_5_win_count
        )

        recent_5_win_rate = (
            round(
                recent_5_win_count
                / len(recent_matches)
                * 100,
                1
            )
            if recent_matches
            else 0
        )

        recent_5_rating_change = sum(
            match["rating_change"] or 0
            for match in recent_matches
        )

        # ==============================
        # 최근 20경기 레이팅 그래프
        # ==============================

        cursor.execute(
            """
            SELECT
                history.match_id,
                history.match_date,
                history.rating_after

            FROM (
                SELECT
                    m.id AS match_id,
                    m.match_date,
                    mp.rating_after

                FROM match_players mp

                JOIN matches m
                    ON m.id = mp.match_id

                WHERE mp.discord_id = ?

                ORDER BY
                    m.id DESC

                LIMIT 20
            ) AS history

            ORDER BY
                history.match_id ASC
            """,
            (
                discord_id,
            )
        )

        rating_history = (
            cursor.fetchall()
        )

        # ==============================
        # 최근 20경기 상세 변화
        # ==============================

        cursor.execute(
            """
            SELECT
                recent.match_id,
                recent.match_date,
                recent.won,
                recent.rating_before,
                recent.rating_after,
                recent.rating_change

            FROM (
                SELECT
                    m.id AS match_id,
                    m.match_date,

                    mp.won,
                    mp.rating_before,
                    mp.rating_after,
                    mp.rating_change

                FROM match_players mp

                JOIN matches m
                    ON m.id = mp.match_id

                WHERE mp.discord_id = ?

                ORDER BY
                    m.id DESC

                LIMIT 20
            ) AS recent

            ORDER BY
                recent.match_id ASC
            """,
            (
                discord_id,
            )
        )

        recent_results = (
            cursor.fetchall()
        )

        recent_win_count = sum(
            1
            for match in recent_results
            if match["won"]
        )

        recent_loss_count = (
            len(recent_results)
            - recent_win_count
        )

        recent_win_rate = (
            round(
                recent_win_count
                / len(recent_results)
                * 100,
                1
            )
            if recent_results
            else 0
        )

        recent_20_rating_change = sum(
            match["rating_change"] or 0
            for match in recent_results
        )

        # ==============================
        # 전체 승률
        # ==============================

        total_games = (
            player["wins"]
            + player["losses"]
        )

        win_rate = (
            round(
                player["wins"]
                / total_games
                * 100,
                1
            )
            if total_games > 0
            else 0
        )

        # ==============================
        # 자주 함께한 팀원 TOP 5
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
                ) AS wins,

                SUM(
                    CASE
                        WHEN me.won = 0
                        THEN 1
                        ELSE 0
                    END
                ) AS losses

            FROM match_players me

            JOIN match_players teammate
                ON teammate.match_id = me.match_id
                AND teammate.team = me.team
                AND teammate.discord_id != me.discord_id

            LEFT JOIN players p
                ON p.discord_id = teammate.discord_id

            WHERE me.discord_id = ?

            GROUP BY
                teammate.discord_id,
                p.id,
                p.discord_nickname,
                p.riot_name,
                p.tier

            ORDER BY
                games DESC,
                wins DESC,
                teammate.discord_id ASC

            LIMIT 5
            """,
            (
                discord_id,
            )
        )

        duo_rows = (
            cursor.fetchall()
        )

        duo_players = []

        for row in duo_rows:

            duo = dict(row)

            duo_games = (
                duo["games"]
                or 0
            )

            duo_wins = (
                duo["wins"]
                or 0
            )

            duo["win_rate"] = (
                round(
                    duo_wins
                    / duo_games
                    * 100,
                    1
                )
                if duo_games > 0
                else 0
            )

            duo_players.append(
                duo
            )

        # ==============================
        # 상대 전적 TOP 5
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
                ) AS wins,

                SUM(
                    CASE
                        WHEN me.won = 0
                        THEN 1
                        ELSE 0
                    END
                ) AS losses

            FROM match_players me

            JOIN match_players opponent
                ON opponent.match_id = me.match_id
                AND opponent.team != me.team

            LEFT JOIN players p
                ON p.discord_id = opponent.discord_id

            WHERE me.discord_id = ?

            GROUP BY
                opponent.discord_id,
                p.id,
                p.discord_nickname,
                p.riot_name,
                p.tier

            ORDER BY
                games DESC,
                wins DESC,
                opponent.discord_id ASC

            LIMIT 5
            """,
            (
                discord_id,
            )
        )

        opponent_rows = (
            cursor.fetchall()
        )

        opponent_players = []

        for row in opponent_rows:

            opponent = dict(row)

            opponent_games = (
                opponent["games"]
                or 0
            )

            opponent_wins = (
                opponent["wins"]
                or 0
            )

            opponent["win_rate"] = (
                round(
                    opponent_wins
                    / opponent_games
                    * 100,
                    1
                )
                if opponent_games > 0
                else 0
            )

            opponent_players.append(
                opponent
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

                SUM(
                    CASE
                        WHEN won = 0
                        THEN 1
                        ELSE 0
                    END
                ) AS losses

            FROM match_players

            WHERE discord_id = ?

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
                wins DESC,
                position ASC
            """,
            (
                discord_id,
            )
        )

        position_rows = (
            cursor.fetchall()
        )

        position_stats = []

        for row in position_rows:

            stat = dict(row)

            position_games = (
                stat["games"]
                or 0
            )

            position_wins = (
                stat["wins"]
                or 0
            )

            stat["win_rate"] = (
                round(
                    position_wins
                    / position_games
                    * 100,
                    1
                )
                if position_games > 0
                else 0
            )

            position_stats.append(
                stat
            )

    return templates.TemplateResponse(
        request=request,
        name="player.html",
        context={
            "player":
                player,

            "player_rank":
                player_rank,

            "total_player_count":
                total_player_count,

            "top_percent":
                top_percent,

            "win_rate":
                win_rate,

            "active_season":
                active_season,

            "season_stats":
                season_stats,

            "season_win_rate":
                season_win_rate,

            "season_rank":
                season_rank,

            "season_player_count":
                season_player_count,

            "recent_matches":
                recent_matches,

            "recent_5_win_count":
                recent_5_win_count,

            "recent_5_loss_count":
                recent_5_loss_count,

            "recent_5_win_rate":
                recent_5_win_rate,

            "recent_5_rating_change":
                recent_5_rating_change,

            "rating_history":
                rating_history,

            "recent_results":
                recent_results,

            "recent_win_count":
                recent_win_count,

            "recent_loss_count":
                recent_loss_count,

            "recent_win_rate":
                recent_win_rate,

            "recent_20_rating_change":
                recent_20_rating_change,

            "duo_players":
                duo_players,

            "opponent_players":
                opponent_players,

            "position_stats":
                position_stats
        }
    )