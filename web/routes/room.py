from fastapi import (
    APIRouter,
    Request,
    HTTPException
)

from fastapi.templating import (
    Jinja2Templates
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


router = APIRouter()

templates = Jinja2Templates(
    directory="web/templates"
)


POSITION_ORDER = {
    "TOP": 1,
    "JUNGLE": 2,
    "MID": 3,
    "ADC": 4,
    "SUPPORT": 5
}


# ==============================
# 방 상태 파일 읽기
# ==============================

def load_rooms_state():

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


# ==============================
# DB 프로필 조회
# ==============================

def get_player_profiles(
    discord_ids
):

    clean_ids = []
    seen_ids = set()

    for discord_id in discord_ids:

        value = str(
            discord_id
            or ""
        ).strip()

        if not value:
            continue

        if value in seen_ids:
            continue

        seen_ids.add(
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
        str(row["discord_id"]):
            dict(row)

        for row in rows
    }


# ==============================
# 참가자 정규화
# ==============================

def normalize_players(
    players_data
):

    players = []

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

                player_info = dict(
                    player
                )

                player_info.setdefault(
                    "discord_id",
                    str(discord_id)
                )

            else:

                player_info = {
                    "discord_id":
                        str(discord_id),

                    "discord_nickname":
                        str(player)
                }

            players.append(
                player_info
            )

    elif isinstance(
        players_data,
        list
    ):

        for player in players_data:

            if isinstance(
                player,
                dict
            ):

                player_info = dict(
                    player
                )

                player_info["discord_id"] = str(
                    player_info.get(
                        "discord_id",
                        player_info.get(
                            "user_id",
                            ""
                        )
                    )
                    or ""
                )

                players.append(
                    player_info
                )

            else:

                value = str(
                    player
                    or ""
                )

                if value:

                    players.append(
                        {
                            "discord_id":
                                value
                        }
                    )

    normalized_players = []

    seen_ids = set()

    for player in players:

        discord_id = str(
            player.get(
                "discord_id",
                ""
            )
            or ""
        ).strip()

        if not discord_id:
            continue

        if discord_id in seen_ids:
            continue

        seen_ids.add(
            discord_id
        )

        player["discord_id"] = (
            discord_id
        )

        normalized_players.append(
            player
        )

    return normalized_players


# ==============================
# 팀 정규화
# ==============================

def normalize_team(
    team_data
):

    members = []

    if isinstance(
        team_data,
        dict
    ):

        for position, user_id in (
            team_data.items()
        ):

            discord_id = str(
                user_id
                or ""
            ).strip()

            if not discord_id:
                continue

            members.append(
                {
                    "position":
                        str(position),

                    "discord_id":
                        discord_id
                }
            )

    elif isinstance(
        team_data,
        list
    ):

        for member in team_data:

            if isinstance(
                member,
                dict
            ):

                member_info = dict(
                    member
                )

                member_info["discord_id"] = str(
                    member_info.get(
                        "discord_id",
                        member_info.get(
                            "user_id",
                            ""
                        )
                    )
                    or ""
                ).strip()

                if not member_info[
                    "discord_id"
                ]:
                    continue

                members.append(
                    member_info
                )

            else:

                discord_id = str(
                    member
                    or ""
                ).strip()

                if discord_id:

                    members.append(
                        {
                            "discord_id":
                                discord_id
                        }
                    )

    members.sort(
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

    return members


# ==============================
# 프로필 정보 합치기
# ==============================

def enrich_player(
    player,
    profiles
):

    player_info = dict(
        player
    )

    discord_id = str(
        player_info.get(
            "discord_id",
            ""
        )
        or ""
    )

    db_player = profiles.get(
        discord_id
    )

    if db_player is not None:

        player_info[
            "player_id"
        ] = db_player.get(
            "id"
        )

        player_info[
            "discord_nickname"
        ] = (
            db_player.get(
                "discord_nickname"
            )
            or player_info.get(
                "discord_nickname"
            )
            or player_info.get(
                "nickname"
            )
            or player_info.get(
                "display_name"
            )
            or discord_id
        )

        player_info[
            "riot_name"
        ] = (
            db_player.get(
                "riot_name"
            )
            or player_info.get(
                "riot_name"
            )
        )

        player_info[
            "tier"
        ] = (
            db_player.get(
                "tier"
            )
            or player_info.get(
                "tier"
            )
        )

        player_info[
            "main_position"
        ] = (
            db_player.get(
                "main_position"
            )
            or player_info.get(
                "main_position"
            )
        )

        player_info[
            "sub_position"
        ] = (
            db_player.get(
                "sub_position"
            )
            or player_info.get(
                "sub_position"
            )
        )

        player_info[
            "rating"
        ] = db_player.get(
            "rating"
        )

        player_info[
            "wins"
        ] = db_player.get(
            "wins"
        )

        player_info[
            "losses"
        ] = db_player.get(
            "losses"
        )

        player_info[
            "mvp"
        ] = db_player.get(
            "mvp"
        )

    else:

        player_info.setdefault(
            "player_id",
            None
        )

        player_info[
            "discord_nickname"
        ] = (
            player_info.get(
                "discord_nickname"
            )
            or player_info.get(
                "nickname"
            )
            or player_info.get(
                "display_name"
            )
            or player_info.get(
                "riot_name"
            )
            or discord_id
            or "알 수 없는 플레이어"
        )

        player_info.setdefault(
            "riot_name",
            None
        )

        player_info.setdefault(
            "tier",
            None
        )

        player_info.setdefault(
            "main_position",
            None
        )

        player_info.setdefault(
            "sub_position",
            None
        )

        player_info.setdefault(
            "rating",
            None
        )

        player_info.setdefault(
            "wins",
            None
        )

        player_info.setdefault(
            "losses",
            None
        )

        player_info.setdefault(
            "mvp",
            None
        )

    return player_info


# ==============================
# 방 상세
# ==============================

@router.get(
    "/room/{room_id}"
)
def room_detail(
    request: Request,
    room_id: str
):

    rooms = load_rooms_state()

    room = rooms.get(
        str(room_id)
    )

    # ==============================
    # key가 room_id와 다를 경우 보조 탐색
    # ==============================

    if room is None:

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

            if (
                stored_room_id
                == str(room_id)
            ):

                room = value
                break

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
            status_code=404,
            detail="내전방 상태가 올바르지 않습니다."
        )

    # ==============================
    # 실제 방 ID / 이름
    # ==============================

    resolved_room_id = str(
        room.get(
            "room_id",
            room_id
        )
    )

    room_name = (
        room.get(
            "room_name"
        )
        or f"내전 {resolved_room_id}"
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
    # 현재 팀
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
    # 필요한 모든 Discord ID 수집
    # ==============================

    discord_ids = []

    for player in players:

        discord_ids.append(
            player.get(
                "discord_id",
                ""
            )
        )

    for member in blue_team:

        discord_ids.append(
            member.get(
                "discord_id",
                ""
            )
        )

    for member in red_team:

        discord_ids.append(
            member.get(
                "discord_id",
                ""
            )
        )

    # ==============================
    # DB 프로필 조회
    # ==============================

    profiles = get_player_profiles(
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
    # 참가자 명단 보강
    #
    # players에 없지만 current_teams에는
    # 존재하는 플레이어도 표시합니다.
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

    player_count = len(
        players
    )

    # ==============================
    # 팀 레이팅
    # ==============================

    blue_ratings = [
        member["rating"]
        for member in blue_team
        if member.get(
            "rating"
        ) is not None
    ]

    red_ratings = [
        member["rating"]
        for member in red_team
        if member.get(
            "rating"
        ) is not None
    ]

    # 한 명이라도 레이팅을 알 수 없으면
    # 예상 승률을 확정해서 보여주지 않습니다.

    has_complete_rating_data = (
        bool(blue_team)
        and bool(red_team)
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

    if blue_ratings:

        blue_avg = round(
            sum(
                blue_ratings
            )
            / len(
                blue_ratings
            )
        )

    else:

        blue_avg = 0

    if red_ratings:

        red_avg = round(
            sum(
                red_ratings
            )
            / len(
                red_ratings
            )
        )

    else:

        red_avg = 0

    # ==============================
    # Elo 예상 승률
    # ==============================

    if has_complete_rating_data:

        blue_expected = (
            calculate_expected_score(
                player_rating=blue_avg,
                enemy_avg_rating=red_avg
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
    # 밸런스
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
    # 완료 세트 수
    #
    # 0 = 아직 완료된 세트 없음
    # 1 = 1세트 완료
    # 2 = 2세트 완료
    # ==============================

    raw_series_game = room.get(
        "series_game",
        0
    )

    try:

        series_game = int(
            raw_series_game
        )

    except (
        TypeError,
        ValueError
    ):

        series_game = 0

    if series_game < 0:
        series_game = 0

    # 다음에 진행할 실제 세트 번호
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
    # 방 상태
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

    elif player_count > 0:

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
    # 템플릿
    # ==============================

    return templates.TemplateResponse(
        request=request,
        name="room.html",
        context={
            "room_id":
                resolved_room_id,

            "room_name":
                room_name,

            "status":
                status,

            "status_code":
                status_code,

            "players":
                players,

            "player_count":
                player_count,

            "blue_team":
                blue_team,

            "red_team":
                red_team,

            "blue_score":
                blue_score,

            "red_score":
                red_score,

            # 완료된 세트 수
            "series_game":
                series_game,

            # 실제 현재/다음 세트
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
    )