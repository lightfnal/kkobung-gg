import json
from itertools import combinations

from storage.paths import TEAM_HISTORY_FILE



def load_history():
    """
    저장된 팀 히스토리를 불러옵니다.

    파일이 없거나 내용이 잘못되어 있으면
    빈 기록을 반환합니다.
    """

    if not TEAM_HISTORY_FILE.exists():
        return {
            "same_team": {},
            "opponents": {}
        }

    try:
        with TEAM_HISTORY_FILE.open(
            "r",
            encoding="utf-8"
        ) as file:
            data = json.load(file)

    except (
        json.JSONDecodeError,
        OSError
    ):
        return {
            "same_team": {},
            "opponents": {}
        }

    # 예전 파일에 same_team 항목이 없더라도 안전하게 보완
    if "same_team" not in data:
        data["same_team"] = {}

    if "opponents" not in data:
        data["opponents"] = {}

    return data


def save_history(data):
    """
    팀 히스토리를 JSON 파일에 저장합니다.
    """

    TEAM_HISTORY_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with TEAM_HISTORY_FILE.open(
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=4
        )


def make_pair_key(
    user_id_1,
    user_id_2
):
    """
    두 Discord ID로 항상 같은 조합 키를 만듭니다.

    예:
    300, 100
    100, 300

    둘 다 결과는:
    100_300
    """

    first_id, second_id = sorted(
        [
            str(user_id_1),
            str(user_id_2)
        ]
    )

    return f"{first_id}_{second_id}"


def add_same_team(team):
    """
    한 팀 안에서 함께 배정된 모든 선수 조합의
    같은 팀 횟수를 1씩 증가시킵니다.

    team은 Discord ID 목록을 받습니다.

    예:
    ["A", "B", "C", "D", "E"]
    """

    team = [
        str(user_id)
        for user_id in team
    ]

    # 같은 사람이 중복으로 들어온 비정상 데이터 방지
    team = list(dict.fromkeys(team))

    if len(team) < 2:
        return

    history = load_history()
    same_team_history = history["same_team"]

    # 5명이라면 총 10개 조합 생성
    for user_id_1, user_id_2 in combinations(
        team,
        2
    ):
        pair_key = make_pair_key(
            user_id_1,
            user_id_2
        )

        same_team_history[pair_key] = (
            same_team_history.get(
                pair_key,
                0
            )
            + 1
        )

    save_history(history)


def get_same_team_count(
    user_id_1,
    user_id_2,
    history=None
):
    """
    두 선수가 지금까지 같은 팀이었던 횟수를 반환합니다.

    이미 불러온 history를 전달하면
    파일을 다시 읽지 않습니다.
    """

    if history is None:
        history = load_history()

    pair_key = make_pair_key(
        user_id_1,
        user_id_2
    )

    same_team_history = history.get(
        "same_team",
        {}
    )

    return same_team_history.get(
        pair_key,
        0
    )


def get_same_team_penalty(
    team,
    history=None
):
    """
    해당 팀 구성의 같은 팀 반복 페널티를 계산합니다.

    이미 불러온 history를 전달하면
    모든 선수 조합에서 같은 기록을 재사용합니다.
    """

    if history is None:
        history = load_history()

    team = [
        str(user_id)
        for user_id in team
    ]

    team = list(
        dict.fromkeys(team)
    )

    total_penalty = 0

    for user_id_1, user_id_2 in combinations(
        team,
        2
    ):
        same_team_count = get_same_team_count(
            user_id_1,
            user_id_2,
            history=history
        )

        total_penalty += calculate_pair_penalty(
            same_team_count
        )

    return total_penalty


def calculate_pair_penalty(
    same_team_count
):
    """
    같은 팀 횟수에 따라 조합 하나의 패널티를 계산합니다.

    0회: 0점
    1회: 1점
    2회: 3점
    3회: 6점
    4회: 10점

    삼각수 방식으로 점점 강하게 증가합니다.
    """

    if same_team_count <= 0:
        return 0

    return (
        same_team_count
        * (same_team_count + 1)
        // 2
    )


def add_opponents(
    red_team,
    blue_team
):
    """
    레드팀과 블루팀 사이의 모든 상대 조합 횟수를
    1씩 증가시킵니다.

    5대5라면 총 25개의 상대 조합이 기록됩니다.
    """

    red_team = [
        str(user_id)
        for user_id in red_team
    ]

    blue_team = [
        str(user_id)
        for user_id in blue_team
    ]

    red_team = list(dict.fromkeys(red_team))
    blue_team = list(dict.fromkeys(blue_team))

    if not red_team or not blue_team:
        return

    history = load_history()

    opponent_history = history.setdefault(
        "opponents",
        {}
    )

    for red_user_id in red_team:
        for blue_user_id in blue_team:
            pair_key = make_pair_key(
                red_user_id,
                blue_user_id
            )

            opponent_history[pair_key] = (
                opponent_history.get(
                    pair_key,
                    0
                )
                + 1
            )

    save_history(history)


def get_opponent_penalty(
    red_team,
    blue_team,
    history=None
):
    """
    두 팀 사이에서 과거에 반복된 상대 조합의
    전체 페널티를 계산합니다.

    이미 불러온 history를 전달하면
    파일을 다시 읽지 않습니다.
    """

    if history is None:
        history = load_history()

    red_team = [
        str(user_id)
        for user_id in red_team
    ]

    blue_team = [
        str(user_id)
        for user_id in blue_team
    ]

    opponent_history = history.get(
        "opponents",
        {}
    )

    total_penalty = 0

    for red_user_id in red_team:
        for blue_user_id in blue_team:
            pair_key = make_pair_key(
                red_user_id,
                blue_user_id
            )

            opponent_count = (
                opponent_history.get(
                    pair_key,
                    0
                )
            )

            total_penalty += (
                calculate_pair_penalty(
                    opponent_count
                )
            )

    return total_penalty

def clear_team_history():
    """
    같은 팀 기록과 상대 기록을 모두 초기화합니다.
    """

    save_history({
        "same_team": {},
        "opponents": {}
    })