from fastapi import (
    APIRouter,
    HTTPException
)

import json

from storage.paths import (
    ROOMS_STATE_FILE
)

from web.database import (
    get_db_connection
)

from utils.rating import (
    calculate_expected_score
)


router = APIRouter(
    prefix="/api"
)


POSITION_ORDER = {
    "TOP": 1,
    "JUNGLE": 2,
    "MID": 3,
    "ADC": 4,
    "SUPPORT": 5
}


# =====================================================
# 방 상태 파일 읽기
# =====================================================

def load_rooms():

    if not ROOMS_STATE_FILE.exists():
        return {}

    try:

        with ROOMS_STATE_FILE.open(
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(
                file
            )

    except (
        OSError,
        json.JSONDecodeError
    ):

        return {}

    if not isinstance(
        data,
        dict
    ):
        return {}

    rooms = data.get(
        "rooms",
        data
    )

    if not isinstance(
        rooms,
        dict
    ):
        return {}

    return rooms


# =====================================================
# 참가자 데이터 정규화
# =====================================================

def normalize_players(
    players_data
):

    result = []

    # ==============================
    # dict 형식
    # ==============================

    if isinstance(
        players_data,
        dict
    ):

        for discord_id, player in (
            players_data.items()
        ):

            if isinstance(
                player,
                dict
            ):

                info = dict(
                    player
                )

            else:

                info = {
                    "discord_nickname":
                        str(player)
                }

            info["discord_id"] = str(
                info.get(
                    "discord_id",
                    discord_id
                )
                or discord_id
            ).strip()

            if not info[
                "discord_id"
            ]:
                continue

            result.append(
                info
            )

    # ==============================
    # list 형식
    # ==============================

    elif isinstance(
        players_data,
        list
    ):

        for player in (
            players_data
        ):

            if isinstance(
                player,
                dict
            ):

                info = dict(
                    player
                )

                info[
                    "discord_id"
                ] = str(
                    info.get(
                        "discord_id",
                        info.get(
                            "user_id",
                            ""
                        )
                    )
                    or ""
                ).strip()

            else:

                info = {
                    "discord_id":
                        str(
                            player
                            or ""
                        ).strip()
                }

            if not info[
                "discord_id"
            ]:
                continue

            result.append(
                info
            )


    # ==============================
    # 중복 제거
    # ==============================

    unique_players = {}

    for player in result:

        discord_id = str(
            player.get(
                "discord_id",
                ""
            )
            or ""
        ).strip()

        if not discord_id:
            continue

        player[
            "discord_id"
        ] = discord_id

        unique_players[
            discord_id
        ] = player


    return list(
        unique_players.values()
    )


# =====================================================
# 팀 데이터 정규화
# =====================================================

def normalize_team(
    team_data
):

    result = []


    # ==============================
    # dict
    #
    # {
    #     "TOP": "123",
    #     "JUNGLE": "456"
    # }
    # ==============================

    if isinstance(
        team_data,
        dict
    ):

        for position, discord_id in (
            team_data.items()
        ):

            value = str(
                discord_id
                or ""
            ).strip()

            if not value:
                continue

            result.append(
                {
                    "position":
                        str(
                            position
                        ),

                    "discord_id":
                        value
                }
            )


    # ==============================
    # list
    # ==============================

    elif isinstance(
        team_data,
        list
    ):

        for member in (
            team_data
        ):

            if isinstance(
                member,
                dict
            ):

                info = dict(
                    member
                )

                info[
                    "discord_id"
                ] = str(
                    info.get(
                        "discord_id",
                        info.get(
                            "user_id",
                            ""
                        )
                    )
                    or ""
                ).strip()

                if not info[
                    "discord_id"
                ]:
                    continue

                result.append(
                    info
                )

            else:

                value = str(
                    member
                    or ""
                ).strip()

                if not value:
                    continue

                result.append(
                    {
                        "discord_id":
                            value
                    }
                )


    # ==============================
    # 포지션 순 정렬
    # ==============================

    result.sort(
        key=lambda member: (
            POSITION_ORDER.get(
                str(
                    member.get(
                        "position",
                        ""
                    )
                    or ""
                ).upper(),
                99
            ),
            str(
                member.get(
                    "discord_id",
                    ""
                )
            )
        )
    )


    return result


# =====================================================
# DB 플레이어 프로필 조회
# =====================================================

def get_profiles(
    discord_ids
):

    clean_ids = []

    seen = set()


    for discord_id in (
        discord_ids
    ):

        value = str(
            discord_id
            or ""
        ).strip()

        if not value:
            continue

        if value in seen:
            continue

        seen.add(
            value
        )

        clean_ids.append(
            value
        )


    if not clean_ids:
        return {}


    placeholders = ",".join(
        "?"
        for _ in clean_ids
    )


    with get_db_connection() as conn:

        cursor = conn.cursor()

        cursor.execute(
            f"""
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
                mvp

            FROM players

            WHERE discord_id
                IN ({placeholders})
            """,
            tuple(
                clean_ids
            )
        )

        rows = (
            cursor.fetchall()
        )


    return {
        str(
            row["discord_id"]
        ):
            dict(
                row
            )

        for row in rows
    }


# =====================================================
# 참가자 + DB 프로필 병합
# =====================================================

def enrich_player(
    player,
    profiles
):

    result = dict(
        player
    )

    discord_id = str(
        result.get(
            "discord_id",
            ""
        )
        or ""
    ).strip()

    result[
        "discord_id"
    ] = discord_id


    db_player = (
        profiles.get(
            discord_id
        )
    )


    # ==============================
    # DB 플레이어 존재
    # ==============================

    if db_player is not None:

        result[
            "player_id"
        ] = db_player.get(
            "id"
        )

        result[
            "discord_nickname"
        ] = (
            db_player.get(
                "discord_nickname"
            )
            or result.get(
                "discord_nickname"
            )
            or result.get(
                "nickname"
            )
            or result.get(
                "display_name"
            )
            or discord_id
        )

        result[
            "riot_name"
        ] = (
            db_player.get(
                "riot_name"
            )
            or result.get(
                "riot_name"
            )
        )

        result[
            "tier"
        ] = (
            db_player.get(
                "tier"
            )
            or result.get(
                "tier"
            )
        )

        result[
            "main_position"
        ] = (
            db_player.get(
                "main_position"
            )
            or result.get(
                "main_position"
            )
        )

        result[
            "sub_position"
        ] = (
            db_player.get(
                "sub_position"
            )
            or result.get(
                "sub_position"
            )
        )

        result[
            "rating"
        ] = db_player.get(
            "rating"
        )

        result[
            "wins"
        ] = db_player.get(
            "wins"
        )

        result[
            "losses"
        ] = db_player.get(
            "losses"
        )

        result[
            "mvp"
        ] = db_player.get(
            "mvp"
        )


    # ==============================
    # DB 플레이어 없음
    # ==============================

    else:

        result.setdefault(
            "player_id",
            None
        )

        result[
            "discord_nickname"
        ] = (
            result.get(
                "discord_nickname"
            )
            or result.get(
                "nickname"
            )
            or result.get(
                "display_name"
            )
            or result.get(
                "riot_name"
            )
            or discord_id
            or "알 수 없는 플레이어"
        )

        result.setdefault(
            "riot_name",
            None
        )

        result.setdefault(
            "tier",
            None
        )

        result.setdefault(
            "main_position",
            None
        )

        result.setdefault(
            "sub_position",
            None
        )

        result.setdefault(
            "rating",
            None
        )

        result.setdefault(
            "wins",
            None
        )

        result.setdefault(
            "losses",
            None
        )

        result.setdefault(
            "mvp",
            None
        )


    return result


# =====================================================
# 방 찾기
# =====================================================

def find_room(
    rooms,
    room_id
):

    target_id = str(
        room_id
    )


    room = rooms.get(
        target_id
    )


    if isinstance(
        room,
        dict
    ):
        return room


    # ==============================
    # dict key와 실제 room_id가
    # 다른 경우 보조 탐색
    # ==============================

    for key, value in (
        rooms.items()
    ):

        if not isinstance(
            value,
            dict
        ):
            continue

        stored_room_id = str(
            value.get(
                "room_id",
                key
            )
        )

        if stored_room_id == target_id:

            return value


    return None


# =====================================================
# 방 기본 데이터 준비
# =====================================================

def prepare_room_data(
    room,
    fallback_room_id
):

    room_id = str(
        room.get(
            "room_id",
            fallback_room_id
        )
    )

    room_name = (
        room.get(
            "room_name"
        )
        or f"내전 {room_id}"
    )


    # ==============================
    # 참가자
    # ==============================

    players = normalize_players(
        room.get(
            "players",
            []
        )
    )


    # ==============================
    # 팀
    # ==============================

    current_teams = (
        room.get(
            "current_teams"
        )
        or {}
    )

    if not isinstance(
        current_teams,
        dict
    ):
        current_teams = {}


    blue_team = normalize_team(
        current_teams.get(
            "blue",
            {}
        )
    )

    red_team = normalize_team(
        current_teams.get(
            "red",
            {}
        )
    )


    # ==============================
    # 필요한 Discord ID
    # ==============================

    discord_ids = []


    for player in players:

        discord_ids.append(
            player.get(
                "discord_id"
            )
        )


    for member in (
        blue_team
        + red_team
    ):

        discord_ids.append(
            member.get(
                "discord_id"
            )
        )


    # ==============================
    # DB 프로필
    # ==============================

    profiles = get_profiles(
        discord_ids
    )


    players = [
        enrich_player(
            player,
            profiles
        )
        for player in players
    ]


    blue_team = [
        enrich_player(
            member,
            profiles
        )
        for member in blue_team
    ]


    red_team = [
        enrich_player(
            member,
            profiles
        )
        for member in red_team
    ]


    # ==============================
    # 팀에만 존재하는 플레이어도
    # 참가자 목록에 보강
    # ==============================

    players_by_id = {
        str(
            player.get(
                "discord_id",
                ""
            )
        ):
            player

        for player in players

        if player.get(
            "discord_id"
        )
    }


    for member in (
        blue_team
        + red_team
    ):

        discord_id = str(
            member.get(
                "discord_id",
                ""
            )
            or ""
        )

        if (
            discord_id
            and discord_id
            not in players_by_id
        ):

            players_by_id[
                discord_id
            ] = member


    players = list(
        players_by_id.values()
    )


    # ==============================
    # 팀 레이팅
    # ==============================

    blue_ratings = [
        member[
            "rating"
        ]
        for member in blue_team
        if member.get(
            "rating"
        ) is not None
    ]


    red_ratings = [
        member[
            "rating"
        ]
        for member in red_team
        if member.get(
            "rating"
        ) is not None
    ]


    has_complete_rating_data = (
        bool(
            blue_team
        )
        and bool(
            red_team
        )
        and len(
            blue_ratings
        ) == len(
            blue_team
        )
        and len(
            red_ratings
        ) == len(
            red_team
        )
    )


    # ==============================
    # 평균 레이팅
    # ==============================

    blue_avg = (
        round(
            sum(
                blue_ratings
            )
            / len(
                blue_ratings
            )
        )
        if blue_ratings
        else 0
    )


    red_avg = (
        round(
            sum(
                red_ratings
            )
            / len(
                red_ratings
            )
        )
        if red_ratings
        else 0
    )


    # ==============================
    # 예상 승률
    # ==============================

    if has_complete_rating_data:

        blue_expected = (
            calculate_expected_score(
                player_rating=
                    blue_avg,

                enemy_avg_rating=
                    red_avg
            )
        )


        blue_win_rate = round(
            blue_expected
            * 100,
            1
        )


        red_win_rate = round(
            100
            - blue_win_rate,
            1
        )


    else:

        blue_win_rate = None
        red_win_rate = None


    # ==============================
    # 팀 밸런스
    # ==============================

    rating_difference = (
        blue_avg
        - red_avg
    )


    absolute_rating_difference = abs(
        rating_difference
    )


    if not has_complete_rating_data:

        balance_text = (
            "레이팅 정보 부족"
        )

        balance_code = (
            "unknown"
        )


    elif absolute_rating_difference <= 10:

        balance_text = (
            "매우 균형"
        )

        balance_code = (
            "excellent"
        )


    elif absolute_rating_difference <= 25:

        balance_text = (
            "균형"
        )

        balance_code = (
            "good"
        )


    elif absolute_rating_difference <= 50:

        balance_text = (
            "약간 차이"
        )

        balance_code = (
            "normal"
        )


    else:

        balance_text = (
            "밸런스 차이 큼"
        )

        balance_code = (
            "bad"
        )


    # ==============================
    # BO3 점수
    # ==============================

    series_score = (
        room.get(
            "series_score"
        )
        or {}
    )


    if not isinstance(
        series_score,
        dict
    ):

        series_score = {}


    blue_score = (
        series_score.get(
            "blue",
            0
        )
        or 0
    )


    red_score = (
        series_score.get(
            "red",
            0
        )
        or 0
    )


    # ==============================
    # 완료된 세트 수
    # ==============================

    try:

        series_game = int(
            room.get(
                "series_game",
                0
            )
            or 0
        )


    except (
        TypeError,
        ValueError
    ):

        series_game = 0


    if series_game < 0:

        series_game = 0


    current_game_number = (
        series_game
        + 1
    )


    # ==============================
    # 경기 진행 여부
    # ==============================

    match_in_progress = bool(
        room.get(
            "match_in_progress",
            False
        )
    )


    # ==============================
    # 상태
    # ==============================

    if match_in_progress:

        status = (
            "경기 진행 중"
        )

        status_code = (
            "playing"
        )


    elif blue_team or red_team:

        status = (
            "팀 구성 완료"
        )

        status_code = (
            "ready"
        )


    elif players:

        status = (
            "모집 중"
        )

        status_code = (
            "recruiting"
        )


    else:

        status = (
            "대기 중"
        )

        status_code = (
            "waiting"
        )


    # ==============================
    # 반환
    # ==============================

    return {
        "room_id":
            room_id,

        "room_name":
            room_name,

        "status":
            status,

        "status_code":
            status_code,

        "players":
            players,

        "player_count":
            len(
                players
            ),

        "blue_team":
            blue_team,

        "red_team":
            red_team,

        "has_teams":
            bool(
                blue_team
                or red_team
            ),

        "blue_score":
            blue_score,

        "red_score":
            red_score,

        "series_game":
            series_game,

        "current_game_number":
            current_game_number,

        "match_in_progress":
            match_in_progress,

        "blue_avg":
            blue_avg,

        "red_avg":
            red_avg,

        "blue_win_rate":
            blue_win_rate,

        "red_win_rate":
            red_win_rate,

        "has_complete_rating_data":
            has_complete_rating_data,

        "rating_difference":
            rating_difference,

        "absolute_rating_difference":
            absolute_rating_difference,

        "balance_text":
            balance_text,

        "balance_code":
            balance_code
    }


# =====================================================
# 특정 내전방 API
#
# GET /api/room/1
# =====================================================

@router.get(
    "/room/{room_id}"
)
def room_api(
    room_id: str
):

    rooms = load_rooms()


    room = find_room(
        rooms,
        room_id
    )


    if room is None:

        raise HTTPException(
            status_code=404,
            detail="내전방을 찾을 수 없습니다."
        )


    if not isinstance(
        room,
        dict
    ):

        raise HTTPException(
            status_code=500,
            detail="내전방 데이터 형식이 올바르지 않습니다."
        )


    room_data = prepare_room_data(
        room,
        room_id
    )


    return {
        "success":
            True,

        "room":
            room_data
    }


# =====================================================
# 전체 내전방 API
#
# GET /api/rooms
# =====================================================

@router.get(
    "/rooms"
)
def rooms_api():

    rooms = load_rooms()


    result = []


    # ==============================
    # 모든 방 변환
    # ==============================

    for key, room in (
        rooms.items()
    ):

        if not isinstance(
            room,
            dict
        ):

            continue


        room_data = (
            prepare_room_data(
                room,
                key
            )
        )


        # 홈에서는 전체 선수 상세정보가
        # 꼭 필요하지 않으므로
        # 가벼운 데이터만 반환합니다.

        result.append(
            {
                "room_id":
                    room_data[
                        "room_id"
                    ],

                "room_name":
                    room_data[
                        "room_name"
                    ],

                "player_count":
                    room_data[
                        "player_count"
                    ],

                "status":
                    room_data[
                        "status"
                    ],

                "status_code":
                    room_data[
                        "status_code"
                    ],

                "match_in_progress":
                    room_data[
                        "match_in_progress"
                    ],

                "has_teams":
                    room_data[
                        "has_teams"
                    ],

                "blue_score":
                    room_data[
                        "blue_score"
                    ],

                "red_score":
                    room_data[
                        "red_score"
                    ],

                "series_game":
                    room_data[
                        "series_game"
                    ],

                "current_game_number":
                    room_data[
                        "current_game_number"
                    ]
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


    def room_sort_key(
        room
    ):

        room_id = str(
            room.get(
                "room_id",
                ""
            )
        )


        # 숫자 room_id는 숫자로 정렬
        if room_id.isdigit():

            room_id_key = (
                0,
                int(
                    room_id
                )
            )


        else:

            room_id_key = (
                1,
                room_id
            )


        return (
            status_order.get(
                room.get(
                    "status_code"
                ),
                99
            ),
            room_id_key
        )


    result.sort(
        key=room_sort_key
    )


    # ==============================
    # 활성 방 개수
    # ==============================

    active_room_count = sum(
        1
        for room in result
        if room[
            "status_code"
        ] != "waiting"
    )


    # ==============================
    # 현재 참가 인원
    #
    # 대기방은 참가자가 없으므로
    # 활성 상태만 합산
    # ==============================

    recruiting_player_count = sum(
        room[
            "player_count"
        ]
        for room in result
        if room[
            "status_code"
        ]
        in (
            "recruiting",
            "ready",
            "playing"
        )
    )


    # ==============================
    # 응답
    # ==============================

    return {
        "success":
            True,

        "rooms":
            result,

        "summary": {

            "room_count":
                len(
                    result
                ),

            "active_room_count":
                active_room_count,

            "recruiting_player_count":
                recruiting_player_count
        }
    }