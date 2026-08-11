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
# 전체 전적 API
#
# GET /api/history
# =====================================================

@router.get(
    "/history"
)
def history_api():

    with get_db_connection() as conn:

        cursor = conn.cursor()


        # ==============================
        # 경기 목록
        # ==============================

        cursor.execute(
            """
            SELECT
                m.id,
                m.match_date,
                m.winner,
                m.room_id,
                m.season_id,
                m.mvp_discord_id,

                s.season_name,

                p.id AS mvp_player_id,
                p.discord_nickname AS mvp_name,
                p.riot_name AS mvp_riot_name

            FROM matches m

            LEFT JOIN seasons s
                ON s.id = m.season_id

            LEFT JOIN players p
                ON p.discord_id
                    = m.mvp_discord_id

            ORDER BY
                m.id DESC
            """
        )

        match_rows = (
            cursor.fetchall()
        )


        matches = []


        # ==============================
        # 각 경기 선수 조회
        # ==============================

        for match_row in match_rows:

            match = dict(
                match_row
            )

            match_id = (
                match["id"]
            )


            cursor.execute(
                """
                SELECT
                    mp.discord_id,
                    mp.team,
                    mp.position,
                    mp.won,
                    mp.rating_before,
                    mp.rating_after,
                    mp.rating_change,

                    p.id AS player_id,
                    p.discord_nickname,
                    p.riot_name,
                    p.tier

                FROM match_players mp

                LEFT JOIN players p
                    ON p.discord_id
                        = mp.discord_id

                WHERE mp.match_id = ?

                ORDER BY

                    CASE
                        WHEN UPPER(mp.team) = 'BLUE'
                        THEN 1

                        WHEN UPPER(mp.team) = 'RED'
                        THEN 2

                        ELSE 3
                    END,

                    CASE UPPER(mp.position)

                        WHEN 'TOP'
                        THEN 1

                        WHEN 'JUNGLE'
                        THEN 2

                        WHEN 'MID'
                        THEN 3

                        WHEN 'ADC'
                        THEN 4

                        WHEN 'SUPPORT'
                        THEN 5

                        ELSE 99

                    END
                """,
                (
                    match_id,
                )
            )


            player_rows = (
                cursor.fetchall()
            )


            blue_team = []
            red_team = []


            for player_row in player_rows:

                player = dict(
                    player_row
                )


                # ==============================
                # 기본값
                # ==============================

                player["position"] = (
                    player.get(
                        "position"
                    )
                    or "-"
                )


                player["rating_before"] = (
                    player.get(
                        "rating_before"
                    )
                    or 0
                )


                player["rating_after"] = (
                    player.get(
                        "rating_after"
                    )
                    or 0
                )


                player["rating_change"] = (
                    player.get(
                        "rating_change"
                    )
                    or 0
                )


                player["won"] = bool(
                    player.get(
                        "won"
                    )
                )


                team = str(
                    player.get(
                        "team"
                    )
                    or ""
                ).lower()


                if team == "blue":

                    blue_team.append(
                        player
                    )


                elif team == "red":

                    red_team.append(
                        player
                    )


            # ==============================
            # 경기 데이터
            # ==============================

            match["winner"] = str(
                match.get(
                    "winner"
                )
                or ""
            ).lower()


            match["blue_team"] = (
                blue_team
            )


            match["red_team"] = (
                red_team
            )


            match["player_count"] = (
                len(
                    blue_team
                )
                + len(
                    red_team
                )
            )


            matches.append(
                match
            )


        # ==============================
        # 전체 경기 수
        # ==============================

        match_count = len(
            matches
        )


    return {
        "success":
            True,

        "summary": {

            "match_count":
                match_count
        },

        "matches":
            matches
    }