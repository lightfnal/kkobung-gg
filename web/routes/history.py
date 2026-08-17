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


HISTORY_LIMIT = 100


@router.get("/history")
def history_page(
    request: Request,
    scope: str = "season"
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
        history_scope = (
            "all"
            if scope == "all"
            else "season"
        )
        scope_season_id = (
            active_season["id"]
            if history_scope == "season"
            and active_season is not None
            else (
                -1
                if history_scope == "season"
                else None
            )
        )
        scope_label = (
            active_season["season_name"]
            if history_scope == "season"
            and active_season is not None
            else (
                "현재 시즌"
                if history_scope == "season"
                else "전체 기록"
            )
        )

        # ==============================
        # 전체 경기 수
        # ==============================

        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM matches m
            WHERE (
                ? IS NULL
                OR m.season_id = ?
            )
            """,
            (
                scope_season_id,
                scope_season_id,
            )
        )

        total_match_count = (
            cursor.fetchone()["count"]
            or 0
        )

        # ==============================
        # 최근 경기 목록
        # ==============================

        cursor.execute(
            """
            SELECT
                m.id,
                m.match_date,
                m.winner,
                m.mvp_discord_id,
                m.room_id,
                m.season_id,

                p.id AS mvp_player_id,
                p.discord_nickname AS mvp_name,
                p.riot_name AS mvp_riot_name,

                s.season_name

            FROM matches m

            LEFT JOIN players p
                ON p.discord_id
                    = m.mvp_discord_id

            LEFT JOIN seasons s
                ON s.id
                    = m.season_id

            WHERE (
                ? IS NULL
                OR m.season_id = ?
            )

            ORDER BY
                m.id DESC

            LIMIT ?
            """,
            (
                scope_season_id,
                scope_season_id,
                HISTORY_LIMIT,
            )
        )

        match_rows = (
            cursor.fetchall()
        )

        matches = [
            dict(row)
            for row in match_rows
        ]

        # ==============================
        # 경기별 참가자 전체 조회
        #
        # 기존:
        # 경기 100개 → 참가자 SELECT 100번
        #
        # 변경:
        # 참가자 전체를 SELECT 1번
        # ==============================

        players_by_match = {}

        if matches:

            match_ids = [
                match["id"]
                for match in matches
            ]

            placeholders = ",".join(
                "?"
                for _ in match_ids
            )

            cursor.execute(
                f"""
                SELECT
                    mp.id,
                    mp.match_id,
                    mp.discord_id,
                    mp.team,
                    mp.position,
                    mp.won,
                    mp.rating_change,

                    p.id AS player_id,
                    p.discord_nickname,
                    p.riot_name,
                    p.tier

                FROM match_players mp

                LEFT JOIN players p
                    ON p.discord_id
                        = mp.discord_id

                WHERE mp.match_id
                    IN ({placeholders})

                ORDER BY

                    mp.match_id DESC,

                    CASE LOWER(
                        COALESCE(
                            mp.team,
                            ''
                        )
                    )
                        WHEN 'blue' THEN 0
                        WHEN 'red' THEN 1
                        ELSE 2
                    END,

                    CASE UPPER(
                        COALESCE(
                            mp.position,
                            ''
                        )
                    )
                        WHEN 'TOP' THEN 1
                        WHEN 'JUNGLE' THEN 2
                        WHEN 'MID' THEN 3
                        WHEN 'ADC' THEN 4
                        WHEN 'SUPPORT' THEN 5
                        ELSE 99
                    END,

                    mp.id ASC
                """,
                tuple(
                    match_ids
                )
            )

            for row in cursor.fetchall():

                player = dict(row)

                match_id = (
                    player["match_id"]
                )

                if match_id not in players_by_match:

                    players_by_match[
                        match_id
                    ] = {
                        "blue": [],
                        "red": []
                    }

                team = str(
                    player.get(
                        "team",
                        ""
                    )
                    or ""
                ).lower()

                if team == "blue":

                    players_by_match[
                        match_id
                    ]["blue"].append(
                        player
                    )

                elif team == "red":

                    players_by_match[
                        match_id
                    ]["red"].append(
                        player
                    )

        # ==============================
        # 템플릿용 경기 목록 생성
        # ==============================

        match_list = []

        for match in matches:

            teams = players_by_match.get(
                match["id"],
                {
                    "blue": [],
                    "red": []
                }
            )

            match_list.append(
                {
                    "match":
                        match,

                    "blue_team":
                        teams["blue"],

                    "red_team":
                        teams["red"]
                }
            )

        # ==============================
        # 현재 표시 중인 경기 수
        # ==============================

        displayed_match_count = len(
            match_list
        )

    return templates.TemplateResponse(
        request=request,
        name="history.html",
        context={
            "matches":
                match_list,

            "total_match_count":
                total_match_count,

            "displayed_match_count":
                displayed_match_count,

            "history_limit":
                HISTORY_LIMIT,

            "active_season":
                active_season,

            "history_scope":
                history_scope,

            "scope_label":
                scope_label
        }
    )
