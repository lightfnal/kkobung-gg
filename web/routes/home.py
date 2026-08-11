from fastapi import (
    APIRouter,
    Request
)

from fastapi.templating import (
    Jinja2Templates
)

from fastapi.responses import (
    JSONResponse
)

import json

from storage.paths import (
    ROOMS_STATE_FILE
)

from web.database import (
    get_db_connection
)


router = APIRouter()

templates = Jinja2Templates(
    directory="web/templates"
)


# ==============================
# 실시간 내전방 상태 읽기
# ==============================

def load_live_rooms():

    if not ROOMS_STATE_FILE.exists():
        return []

    try:

        with ROOMS_STATE_FILE.open(
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

    except (
        OSError,
        json.JSONDecodeError
    ):

        return []


    # ==============================
    # rooms 데이터 찾기
    # ==============================

    if isinstance(data, dict):

        rooms_data = data.get(
            "rooms",
            data
        )

    else:

        rooms_data = data


    rooms = []


    # ==============================
    # dict 형식
    # ==============================

    if isinstance(
        rooms_data,
        dict
    ):

        room_items = (
            rooms_data.items()
        )


    # ==============================
    # list 형식
    # ==============================

    elif isinstance(
        rooms_data,
        list
    ):

        room_items = []

        for index, room in enumerate(
            rooms_data,
            start=1
        ):

            if not isinstance(
                room,
                dict
            ):
                continue

            room_id = room.get(
                "room_id",
                str(index)
            )

            room_items.append(
                (
                    str(room_id),
                    room
                )
            )


    else:

        return []


    # ==============================
    # 웹 표시용 데이터 정리
    # ==============================

    for room_id, room in room_items:

        if not isinstance(
            room,
            dict
        ):
            continue


        players = room.get(
            "players",
            []
        )


        # players가 dict인 경우
        if isinstance(
            players,
            dict
        ):

            player_count = len(
                players
            )


        # players가 list인 경우
        elif isinstance(
            players,
            list
        ):

            player_count = len(
                players
            )


        else:

            player_count = 0


        # ------------------------------
        # 팀 배정 여부
        # ------------------------------

        current_teams = room.get(
            "current_teams"
        )

        has_teams = bool(
            current_teams
        )


        # ------------------------------
        # 경기 진행 여부
        # ------------------------------

        match_in_progress = bool(
            room.get(
                "match_in_progress",
                False
            )
        )


        # ------------------------------
        # 시리즈 점수
        # ------------------------------

        series_score = room.get(
            "series_score",
            {}
        )

        if not isinstance(
            series_score,
            dict
        ):

            series_score = {}


        red_score = (
            series_score.get(
                "red",
                0
            )
            or 0
        )

        blue_score = (
            series_score.get(
                "blue",
                0
            )
            or 0
        )


        series_game = (
            room.get(
                "series_game",
                1
            )
            or 1
        )


        # ------------------------------
        # 현재 상태 결정
        # ------------------------------

        if match_in_progress:

            status = "경기 진행 중"

            status_code = (
                "playing"
            )

        elif has_teams:

            status = "팀 구성 완료"

            status_code = (
                "ready"
            )

        elif player_count > 0:

            status = "모집 중"

            status_code = (
                "recruiting"
            )

        else:

            status = "대기 중"

            status_code = (
                "waiting"
            )


        rooms.append(
            {
                "room_id":
                    str(
                        room.get(
                            "room_id",
                            room_id
                        )
                    ),

                "room_name":
                    room.get(
                        "room_name"
                    )
                    or f"내전 {room_id}",

                "player_count":
                    player_count,

                "match_in_progress":
                    match_in_progress,

                "has_teams":
                    has_teams,

                "red_score":
                    red_score,

                "blue_score":
                    blue_score,

                "series_game":
                    series_game,

                "status":
                    status,

                "status_code":
                    status_code
            }
        )


    # ==============================
    # 활성 방 우선 정렬
    # ==============================

    status_order = {
        "playing": 0,
        "ready": 1,
        "recruiting": 2,
        "waiting": 3
    }

    rooms.sort(
        key=lambda room: (
            status_order.get(
                room["status_code"],
                99
            ),
            room["room_id"]
        )
    )


    return rooms


# ==============================
# 실시간 내전방 API
# ==============================

@router.get("/api/live-rooms")
def live_rooms_api():

    rooms = (
        load_live_rooms()
    )


    # ==============================
    # 활성 내전방 수
    # ==============================

    active_room_count = sum(
        1
        for room in rooms
        if room["status_code"]
        != "waiting"
    )


    # ==============================
    # 현재 참가 인원
    # ==============================

    recruiting_player_count = sum(
        room["player_count"]
        for room in rooms
        if room["status_code"]
        in (
            "recruiting",
            "ready",
            "playing"
        )
    )


    return JSONResponse(
        content={
            "rooms":
                rooms,

            "active_room_count":
                active_room_count,

            "recruiting_player_count":
                recruiting_player_count
        }
    )


# ==============================
# 홈
# ==============================

@router.get("/")
def home(
    request: Request
):

    with get_db_connection() as conn:

        cursor = conn.cursor()


        # ==============================
        # 등록 플레이어 수
        # ==============================

        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM players
            """
        )

        player_count = (
            cursor.fetchone()["count"]
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
        )


        # ==============================
        # TOP 5 플레이어
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
                losses

            FROM players

            ORDER BY
                rating DESC,
                wins DESC

            LIMIT 5
            """
        )

        top_players = (
            cursor.fetchall()
        )


        # ==============================
        # 최근 경기 5개
        # ==============================

        cursor.execute(
            """
            SELECT
                m.id,
                m.match_date,
                m.winner,
                m.mvp_discord_id,
                m.room_id,

                p.id AS mvp_player_id,
                p.discord_nickname AS mvp_name,

                s.season_name

            FROM matches m

            LEFT JOIN players p
                ON p.discord_id
                    = m.mvp_discord_id

            LEFT JOIN seasons s
                ON s.id
                    = m.season_id

            ORDER BY
                m.id DESC

            LIMIT 5
            """
        )

        recent_matches = (
            cursor.fetchall()
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


        season_match_count = 0
        season_player_count = 0


        # ==============================
        # 현재 시즌 통계
        # ==============================

        if active_season is not None:

            season_id = (
                active_season["id"]
            )


            cursor.execute(
                """
                SELECT COUNT(*) AS count

                FROM matches

                WHERE season_id = ?
                """,
                (
                    season_id,
                )
            )

            season_match_count = (
                cursor.fetchone()["count"]
            )


            cursor.execute(
                """
                SELECT COUNT(*) AS count

                FROM season_player_stats

                WHERE season_id = ?
                """,
                (
                    season_id,
                )
            )

            season_player_count = (
                cursor.fetchone()["count"]
            )


    # ==============================
    # 실시간 내전방
    # ==============================

    live_rooms = (
        load_live_rooms()
    )


    # ==============================
    # 활성 내전방 수
    # ==============================

    active_room_count = sum(
        1
        for room in live_rooms
        if room["status_code"]
        != "waiting"
    )


    # ==============================
    # 현재 참가 인원
    # ==============================

    recruiting_player_count = sum(
        room["player_count"]
        for room in live_rooms
        if room["status_code"]
        in (
            "recruiting",
            "ready",
            "playing"
        )
    )


    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "player_count":
                player_count,

            "match_count":
                match_count,

            "top_players":
                top_players,

            "recent_matches":
                recent_matches,

            "active_season":
                active_season,

            "season_match_count":
                season_match_count,

            "season_player_count":
                season_player_count,

            # 실시간 내전
            "live_rooms":
                live_rooms,

            "active_room_count":
                active_room_count,

            "recruiting_player_count":
                recruiting_player_count
        }
    )