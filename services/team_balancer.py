import random

from itertools import (
    combinations,
    permutations
)

from config import (
    TEAM_MMR_DIFFERENCE_WEIGHT,
    TEAM_POSITION_PENALTY_WEIGHT,
    TEAM_SAME_TEAM_PENALTY_WEIGHT,
    TEAM_OPPONENT_PENALTY_WEIGHT
)

from storage.team_history import (
    load_history,
    get_same_team_penalty,
    get_opponent_penalty
)


POSITIONS = (
    "TOP",
    "JUNGLE",
    "MID",
    "ADC",
    "SUPPORT"
)


def get_balance_mmr(
    profile
):
    """
    팀 밸런싱에 사용할 Hidden MMR을 반환합니다.

    사용 순서:
    1. 정상적인 hidden_mmr
    2. 정상적인 공개 rating
    3. 기본값 1000

    숫자 문자열도 안전하게 정수로 변환합니다.
    """

    if not isinstance(
        profile,
        dict
    ):
        return 1000

    candidate_values = (
        profile.get(
            "hidden_mmr"
        ),
        profile.get(
            "rating"
        ),
        1000
    )

    for value in candidate_values:
        if isinstance(
            value,
            bool
        ):
            continue

        try:
            converted_value = int(
                value
            )

        except (
            TypeError,
            ValueError
        ):
            continue

        if converted_value >= 0:
            return converted_value

    return 1000

def validate_team_profiles(
    players,
    profiles
):
    """
    팀 생성 전에 참가자의 프로필과
    포지션 정보를 검사합니다.

    문제가 없으면 빈 목록을 반환합니다.
    """

    errors = []

    for user_id in players:
        profile = profiles.get(
            user_id
        )

        if not isinstance(
            profile,
            dict
        ):
            errors.append(
                f"{user_id}: 프로필 없음"
            )
            continue

        main_position = profile.get(
            "main_position"
        )

        sub_position = profile.get(
            "sub_position"
        )

        if main_position not in POSITIONS:
            errors.append(
                f"{user_id}: 주 포지션 오류"
            )

        if sub_position not in POSITIONS:
            errors.append(
                f"{user_id}: 부 포지션 오류"
            )

    return errors


def assign_positions(
    team,
    profiles
):
    """
    한 팀의 선수들을 5개 포지션에 배정합니다.

    포지션 페널티:
    - 주 포지션: 0
    - 부 포지션: 1
    - 나머지 포지션: 3

    최소 페널티 배정이 여러 개면
    그중 하나를 무작위로 선택합니다.
    """

    best_assignments = []
    lowest_penalty = float("inf")

    for player_order in permutations(
        team
    ):
        assignment = {}
        penalty = 0

        for position, user_id in zip(
            POSITIONS,
            player_order
        ):
            profile = profiles.get(
                user_id,
                {}
            )

            main_position = profile.get(
                "main_position",
                ""
            )

            sub_position = profile.get(
                "sub_position",
                ""
            )

            if position == main_position:
                position_penalty = 0

            elif position == sub_position:
                position_penalty = 1

            else:
                position_penalty = 3

            assignment[position] = user_id
            penalty += position_penalty

        if penalty < lowest_penalty:
            lowest_penalty = penalty

            best_assignments = [
                assignment
            ]

        elif penalty == lowest_penalty:
            best_assignments.append(
                assignment
            )

    if not best_assignments:
        return None, float("inf")

    return (
        random.choice(
            best_assignments
        ),
        lowest_penalty
    )


def create_team_signature(
    red_team,
    blue_team
):
    """
    레드·블루 색상과 관계없이
    동일한 팀 구성인지 비교할 서명을 만듭니다.
    """

    return frozenset({
        frozenset(red_team),
        frozenset(blue_team)
    })


def generate_balanced_teams(
    players,
    profiles,
    last_team_signature=None
):
    """
    참가자 목록과 프로필을 사용해
    가장 적합한 5대5 팀을 생성합니다.

    현재 views/join_view.py에서 사용하던
    계산 방식을 그대로 유지합니다.

    반환값이 None이면 유효한 후보를
    찾지 못한 것입니다.
    """

    players = list(players)

    if len(players) != 10:
        return None

    validation_errors = (
        validate_team_profiles(
            players=players,
            profiles=profiles
        )
    )

    if validation_errors:
        return None
    

    half = len(players) // 2

    lowest_total_penalty = float("inf")
    smallest_difference = float("inf")

    best_candidates = []

    # 모든 팀 후보가 동일한 기록을 사용하도록
    # 팀 생성 시작 시 파일을 한 번만 읽습니다.
    team_history = load_history()

    # 첫 번째 선수를 기준 팀에 고정하면
    # 레드·블루만 반전된 중복 조합을 제거할 수 있습니다.
    anchor_player = players[0]

    remaining_players = players[1:]

    for red_team_rest in combinations(
        remaining_players,
        half - 1
    ):
        red_team = [
            anchor_player,
            *red_team_rest
        ]

        red_team_set = set(
            red_team
        )

        blue_team = [
            user_id
            for user_id in players
            if user_id not in red_team_set
        ]

        current_signature = (
            create_team_signature(
                red_team,
                blue_team
            )
        )

        if (
            last_team_signature is not None
            and current_signature
            == last_team_signature
        ):
            continue

        (
            red_assignment,
            red_position_penalty
        ) = assign_positions(
            team=red_team,
            profiles=profiles
        )

        (
            blue_assignment,
            blue_position_penalty
        ) = assign_positions(
            team=blue_team,
            profiles=profiles
        )

        red_mmr = sum(
            get_balance_mmr(
                profiles.get(
                    user_id,
                    {}
                )
            )
            for user_id in red_team
        )

        blue_mmr = sum(
            get_balance_mmr(
                profiles.get(
                    user_id,
                    {}
                )
            )
            for user_id in blue_team
        )

        mmr_difference = abs(
            red_mmr
            - blue_mmr
        )

        same_team_penalty = (
            get_same_team_penalty(
                red_team,
                history=team_history
            )
            +
            get_same_team_penalty(
                blue_team,
                history=team_history
            )
        )

        opponent_penalty = (
            get_opponent_penalty(
                red_team,
                blue_team,
                history=team_history
            )
        )

        position_penalty = (
            red_position_penalty
            + blue_position_penalty
        )

        weighted_mmr_penalty = (
            mmr_difference
            * TEAM_MMR_DIFFERENCE_WEIGHT
        )

        weighted_position_penalty = (
            position_penalty
            * TEAM_POSITION_PENALTY_WEIGHT
        )

        weighted_same_team_penalty = (
            same_team_penalty
            * TEAM_SAME_TEAM_PENALTY_WEIGHT
        )

        weighted_opponent_penalty = (
            opponent_penalty
            * TEAM_OPPONENT_PENALTY_WEIGHT
        )

        total_penalty = (
            weighted_mmr_penalty
            + weighted_position_penalty
            + weighted_same_team_penalty
            + weighted_opponent_penalty
        )

        candidate = {
            "red_assignment": red_assignment,
            "blue_assignment": blue_assignment,
            "red_mmr": red_mmr,
            "blue_mmr": blue_mmr,
            "mmr_difference": mmr_difference,
            "position_penalty": position_penalty,
            "same_team_penalty": same_team_penalty,
            "opponent_penalty": opponent_penalty,
            "weighted_mmr_penalty": (
                weighted_mmr_penalty
            ),
            "weighted_position_penalty": (
                weighted_position_penalty
            ),
            "weighted_same_team_penalty": (
                weighted_same_team_penalty
            ),
            "weighted_opponent_penalty": (
                weighted_opponent_penalty
            ),
            "total_penalty": total_penalty,
            "signature": current_signature
        }

        if (
            total_penalty
            < lowest_total_penalty
        ):
            lowest_total_penalty = (
                total_penalty
            )

            smallest_difference = (
                mmr_difference
            )

            best_candidates = [
                candidate
            ]

        elif (
            total_penalty
            == lowest_total_penalty
        ):
            if (
                mmr_difference
                < smallest_difference
            ):
                smallest_difference = (
                    mmr_difference
                )

                best_candidates = [
                    candidate
                ]

            elif (
                mmr_difference
                == smallest_difference
            ):
                best_candidates.append(
                    candidate
                )

    if not best_candidates:
        return None

    selected_candidate = random.choice(
        best_candidates
    )

    # 중복 계산은 제거하되 특정 선수가 항상
    # 레드팀에 배정되지 않도록 팀 색상을 무작위로 바꿉니다.
    if random.choice(
        (True, False)
    ):
        (
            selected_candidate["red_assignment"],
            selected_candidate["blue_assignment"]
        ) = (
            selected_candidate["blue_assignment"],
            selected_candidate["red_assignment"]
        )

        (
            selected_candidate["red_mmr"],
            selected_candidate["blue_mmr"]
        ) = (
            selected_candidate["blue_mmr"],
            selected_candidate["red_mmr"]
        )

    return selected_candidate