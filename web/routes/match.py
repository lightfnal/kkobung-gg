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

from utils.rating import (
    calculate_expected_score
)


router = APIRouter()

templates = Jinja2Templates(
    directory="web/templates"
)


@router.get("/match/{match_id}")
def match_detail(
    request: Request,
    match_id: int
):

    with get_db_connection() as conn:

        cursor = conn.cursor()

        # ==============================
        # 경기 정보 + 시즌 + MVP 정보
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

                s.season_name,

                p.id
                    AS mvp_player_id,

                p.discord_nickname
                    AS mvp_discord_nickname,

                p.riot_name
                    AS mvp_riot_name

            FROM matches m

            LEFT JOIN seasons s
                ON s.id = m.season_id

            LEFT JOIN players p
                ON p.discord_id
                    = m.mvp_discord_id

            WHERE m.id = ?
            """,
            (
                match_id,
            )
        )

        match = (
            cursor.fetchone()
        )

        if match is None:

            raise HTTPException(
                status_code=404,
                detail="경기를 찾을 수 없습니다."
            )

        # ==============================
        # 참가 선수
        # ==============================

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

                p.id
                    AS player_id,

                p.discord_nickname,
                p.riot_name,
                p.tier

            FROM match_players mp

            LEFT JOIN players p
                ON p.discord_id
                    = mp.discord_id

            WHERE mp.match_id = ?

            ORDER BY

                CASE LOWER(mp.team)
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
            (
                match_id,
            )
        )

        player_rows = (
            cursor.fetchall()
        )

        players = [
            dict(row)
            for row in player_rows
        ]

        # ==============================
        # 블루 / 레드팀 분리
        # ==============================

        blue_team = []
        red_team = []

        for player in players:

            team = str(
                player.get(
                    "team",
                    ""
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
        # 경기 전 평균 레이팅
        # ==============================

        blue_avg = (
            round(
                sum(
                    player["rating_before"]
                    for player in blue_team
                )
                / len(blue_team),
                1
            )
            if blue_team
            else 0
        )

        red_avg = (
            round(
                sum(
                    player["rating_before"]
                    for player in red_team
                )
                / len(red_team),
                1
            )
            if red_team
            else 0
        )

        # ==============================
        # Elo 예상 승률
        # ==============================

        if blue_team and red_team:

            blue_expected = (
                calculate_expected_score(
                    player_rating=blue_avg,
                    enemy_avg_rating=red_avg
                )
            )

            blue_win_rate = round(
                blue_expected * 100,
                1
            )

            red_win_rate = round(
                100 - blue_win_rate,
                1
            )

        else:

            blue_win_rate = 0
            red_win_rate = 0

        # ==============================
        # 레이팅 차이
        # ==============================

        rating_difference = round(
            abs(
                blue_avg
                - red_avg
            ),
            1
        )

        # ==============================
        # 레이팅 우세 팀
        # ==============================

        if blue_avg > red_avg:

            favored_team = "blue"

        elif red_avg > blue_avg:

            favored_team = "red"

        else:

            favored_team = "draw"

        # ==============================
        # 경기 결과 분류
        # ==============================

        winner = str(
            match["winner"]
            or ""
        ).lower()

        if (
            winner not in {
                "blue",
                "red"
            }
        ):

            result_type = "unknown"

        elif favored_team == "draw":

            result_type = "balanced"

        elif favored_team == winner:

            result_type = "expected"

        else:

            result_type = "upset"

        # ==============================
        # 팀별 LP 총 변화
        # ==============================

        blue_lp_total = sum(
            player["rating_change"]
            or 0
            for player in blue_team
        )

        red_lp_total = sum(
            player["rating_change"]
            or 0
            for player in red_team
        )

        # ==============================
        # 최대 상승 / 최대 하락
        # ==============================

        if players:

            max_gain_player = max(
                players,
                key=lambda player: (
                    player["rating_change"]
                    or 0
                )
            )

            max_loss_player = min(
                players,
                key=lambda player: (
                    player["rating_change"]
                    or 0
                )
            )

        else:

            max_gain_player = None
            max_loss_player = None

    return templates.TemplateResponse(
        request=request,
        name="match.html",
        context={
            "match":
                match,

            "blue_team":
                blue_team,

            "red_team":
                red_team,

            "blue_avg":
                blue_avg,

            "red_avg":
                red_avg,

            "blue_win_rate":
                blue_win_rate,

            "red_win_rate":
                red_win_rate,

            "rating_difference":
                rating_difference,

            "favored_team":
                favored_team,

            "result_type":
                result_type,

            "blue_lp_total":
                blue_lp_total,

            "red_lp_total":
                red_lp_total,

            "max_gain_player":
                max_gain_player,

            "max_loss_player":
                max_loss_player
        }
    )