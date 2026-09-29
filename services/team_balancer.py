import random
import config

from itertools import (
    combinations,
    permutations
)

TEAM_MMR_DIFFERENCE_WEIGHT = getattr(config, "TEAM_MMR_DIFFERENCE_WEIGHT", 1)
TEAM_POSITION_PENALTY_WEIGHT = getattr(config, "TEAM_POSITION_PENALTY_WEIGHT", 50)
TEAM_SAME_TEAM_PENALTY_WEIGHT = getattr(config, "TEAM_SAME_TEAM_PENALTY_WEIGHT", 3)
TEAM_OPPONENT_PENALTY_WEIGHT = getattr(config, "TEAM_OPPONENT_PENALTY_WEIGHT", 1)
TEAM_LANE_GAP_FREE_MARGIN = getattr(config, "TEAM_LANE_GAP_FREE_MARGIN", 100)
TEAM_LANE_GAP_WEIGHT = getattr(config, "TEAM_LANE_GAP_WEIGHT", 2)
TEAM_HARD_LANE_GAP = getattr(config, "TEAM_HARD_LANE_GAP", 200)
TEAM_HARD_LANE_GAP_PENALTY = getattr(
    config,
    "TEAM_HARD_LANE_GAP_PENALTY",
    100000
)
TEAM_HARD_LANE_EXCESS_WEIGHT = getattr(
    config,
    "TEAM_HARD_LANE_EXCESS_WEIGHT",
    10
)
TEAM_EXACT_REPEAT_PENALTY = getattr(
    config,
    "TEAM_EXACT_REPEAT_PENALTY",
    500
)
POSITION_MAIN_FACTOR = getattr(config, "POSITION_MAIN_FACTOR", 1.00)
POSITION_SUB_FACTOR = getattr(config, "POSITION_SUB_FACTOR", 0.93)
POSITION_OTHER_FACTOR = getattr(config, "POSITION_OTHER_FACTOR", 0.80)
TEAM_EXPECTED_WINRATE_LIMIT = getattr(config, "TEAM_EXPECTED_WINRATE_LIMIT", 55.0)
TEAM_EXPECTED_WINRATE_WEIGHT = getattr(config, "TEAM_EXPECTED_WINRATE_WEIGHT", 120)
TEAM_TOP_TWO_GAP_FREE_MARGIN = getattr(config, "TEAM_TOP_TWO_GAP_FREE_MARGIN", 150)
TEAM_TOP_TWO_GAP_WEIGHT = getattr(config, "TEAM_TOP_TWO_GAP_WEIGHT", 2)
TEAM_AUTOFILL_IMBALANCE_WEIGHT = getattr(config, "TEAM_AUTOFILL_IMBALANCE_WEIGHT", 120)
TEAM_UNCERTAINTY_IMBALANCE_WEIGHT = getattr(config, "TEAM_UNCERTAINTY_IMBALANCE_WEIGHT", 80)

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


def get_position_factor(profile, position):
    """선호 포지션과 실제 경기 기록을 섞어 포지션 숙련도를 계산합니다."""
    main_position = str(profile.get("main_position") or "").upper()
    sub_position = str(profile.get("sub_position") or "").upper()
    if position == main_position:
        initial_factor = POSITION_MAIN_FACTOR
    elif position == sub_position:
        initial_factor = POSITION_SUB_FACTOR
    else:
        initial_factor = POSITION_OTHER_FACTOR

    stats = (profile.get("position_stats") or {}).get(position, {})
    games = max(0, int(stats.get("games") or 0))
    wins = max(0, int(stats.get("wins") or 0))
    if games == 0:
        return initial_factor

    # 소수 경기의 우연한 연승/연패가 실력을 과도하게 바꾸지 않도록
    # 50% 승률의 가상 8경기와 섞습니다.
    smoothed_winrate = (wins + 4) / (games + 8)
    observed_factor = max(0.78, min(1.15, 0.80 + smoothed_winrate * 0.40))
    confidence = min(0.80, games / 20)
    return initial_factor * (1 - confidence) + observed_factor * confidence


def get_position_mmr(profile, position):
    fallback_mmr = int(round(
        get_balance_mmr(profile) * get_position_factor(profile, position)
    ))
    independent = (profile.get("position_ratings") or {}).get(position)
    if not independent:
        return fallback_mmr
    games = max(0, int(independent.get("games") or 0))
    independent_mmr = int(independent.get("rating") or fallback_mmr)
    if games < 5:
        weight = 0.30
    elif games < 15:
        weight = 0.60
    else:
        weight = 0.80
    blended = fallback_mmr * (1 - weight) + independent_mmr * weight
    form = (profile.get("recent_position_form") or {}).get(position, {})
    weighted_games = float(form.get("weighted_games") or 0)
    if weighted_games:
        recent_winrate = float(form.get("weighted_wins") or 0) / weighted_games
        sample_confidence = min(1.0, int(form.get("games") or 0) / 10)
        blended += max(-60, min(60, (recent_winrate - 0.5) * 120)) * sample_confidence
    return int(round(blended))


def get_position_mmr_confidence(profile, position):
    """15경기에서 최대가 되는 라인 MMR 신뢰도를 반환합니다."""
    independent = (profile.get("position_ratings") or {}).get(position)
    games = max(0, int((independent or {}).get("games") or 0))
    return min(1.0, games / 15)


def is_autofilled(profile, position):
    if position in {
        str(profile.get("main_position") or "").upper(),
        str(profile.get("sub_position") or "").upper()
    }:
        return False
    games = int(
        ((profile.get("position_stats") or {}).get(position, {})).get("games")
        or 0
    )
    return games < 3


def get_position_preference_penalty(profile, position):
    if position == profile.get("main_position"):
        return 0
    if position == profile.get("sub_position"):
        return 1
    games = int(
        ((profile.get("position_stats") or {}).get(position, {})).get("games")
        or 0
    )
    # 실제로 자주 플레이한 제3 포지션은 완전 비선호로 취급하지 않습니다.
    if games >= 8:
        return 1.25
    if games >= 3:
        return 2
    return 3


def get_balance_grade(mmr_difference, lane_gaps, position_penalty):
    """관리자가 즉시 판단할 수 있는 S~D 균형 등급을 반환합니다."""
    max_lane_gap = max(lane_gaps.values(), default=0)
    if mmr_difference <= 100 and max_lane_gap <= 75 and position_penalty <= 2:
        return "S", "매우 균형적"
    if mmr_difference <= 200 and max_lane_gap <= 120 and position_penalty <= 4:
        return "A", "정상 진행 권장"
    if mmr_difference <= 300 and max_lane_gap <= 160:
        return "B", "일부 라인 차이 존재"
    if max_lane_gap <= TEAM_HARD_LANE_GAP:
        return "C", "큰 라인 차이 · 다시뽑기 권장"
    return "D", "현재 인원으로 균형 맞추기 어려움"

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
    profiles,
    return_all=False
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

            position_penalty = get_position_preference_penalty(
                profile,
                position
            )

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

    if return_all:
        # 모든 참가자가 같은 포지션을 선호하는 극단적인 경우에도
        # 팀 생성 시간이 길어지지 않도록 동률 후보를 제한합니다.
        if len(best_assignments) > 30:
            best_assignments = random.sample(best_assignments, 30)
        return best_assignments, lowest_penalty

    return random.choice(best_assignments), lowest_penalty


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


def calculate_expected_winrates(red_mmr, blue_mmr, prediction_calibration=1.0):
    """최종 팀 점수와 항상 같은 방향의 예상 승률을 반환합니다."""
    red_average_mmr = red_mmr / len(POSITIONS)
    blue_average_mmr = blue_mmr / len(POSITIONS)
    raw_red_winrate = 100 / (
        1 + 10 ** ((blue_average_mmr - red_average_mmr) / 400)
    )
    calibration = max(0.70, min(1.30, float(prediction_calibration)))
    red_winrate = 50 + (raw_red_winrate - 50) * calibration
    return red_winrate, 100 - red_winrate


def generate_balanced_teams(
    players,
    profiles,
    last_team_signature=None,
    prediction_calibration=1.0
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

        is_exact_repeat = (
            last_team_signature is not None
            and current_signature == last_team_signature
        )

        (
            red_assignments,
            red_position_penalty
        ) = assign_positions(
            team=red_team,
            profiles=profiles,
            return_all=True
        )

        (
            blue_assignments,
            blue_position_penalty
        ) = assign_positions(
            team=blue_team,
            profiles=profiles,
            return_all=True
        )

        # 선호도 페널티가 같은 배정 중에서는 양 팀의 총 전력과
        # 라인별 맞대결 차이가 가장 작은 포지션 조합을 고릅니다.
        best_assignment_pair = None
        best_assignment_score = float("inf")
        for possible_red in red_assignments:
            for possible_blue in blue_assignments:
                possible_red_mmrs = {
                    position: get_position_mmr(
                        profiles.get(user_id, {}), position
                    )
                    for position, user_id in possible_red.items()
                }
                possible_blue_mmrs = {
                    position: get_position_mmr(
                        profiles.get(user_id, {}), position
                    )
                    for position, user_id in possible_blue.items()
                }
                possible_lane_gaps = {
                    position: abs(
                        possible_red_mmrs[position]
                        - possible_blue_mmrs[position]
                    )
                    for position in POSITIONS
                }
                possible_score = abs(
                    sum(possible_red_mmrs.values())
                    - sum(possible_blue_mmrs.values())
                ) + TEAM_LANE_GAP_WEIGHT * sum(
                    max(0, gap - TEAM_LANE_GAP_FREE_MARGIN)
                    for gap in possible_lane_gaps.values()
                )
                # 200점을 조금 넘긴 라인과 400~500점 벌어진 라인을
                # 같은 위험도로 취급하지 않습니다. 초과분을 제곱해
                # 한 라인이 무너지는 조합을 강하게 밀어냅니다.
                possible_score += TEAM_HARD_LANE_EXCESS_WEIGHT * sum(
                    max(0, gap - TEAM_HARD_LANE_GAP) ** 2
                    for gap in possible_lane_gaps.values()
                )
                # 같은 선호도 배정이라도 포지션을 서로 바꿔 보면서
                # 예상 승률·비주력 배치·라인 MMR 신뢰도가 더 고른 쪽을 택합니다.
                possible_winrate, _ = calculate_expected_winrates(
                    sum(possible_red_mmrs.values()),
                    sum(possible_blue_mmrs.values()),
                    prediction_calibration
                )
                possible_score += max(
                    0, max(possible_winrate, 100 - possible_winrate)
                    - TEAM_EXPECTED_WINRATE_LIMIT
                ) * TEAM_EXPECTED_WINRATE_WEIGHT
                possible_red_autofill = sum(
                    is_autofilled(profiles.get(user_id, {}), position)
                    for position, user_id in possible_red.items()
                )
                possible_blue_autofill = sum(
                    is_autofilled(profiles.get(user_id, {}), position)
                    for position, user_id in possible_blue.items()
                )
                possible_score += abs(
                    possible_red_autofill - possible_blue_autofill
                ) * TEAM_AUTOFILL_IMBALANCE_WEIGHT
                possible_red_uncertainty = sum(
                    1 - get_position_mmr_confidence(
                        profiles.get(user_id, {}), position
                    )
                    for position, user_id in possible_red.items()
                )
                possible_blue_uncertainty = sum(
                    1 - get_position_mmr_confidence(
                        profiles.get(user_id, {}), position
                    )
                    for position, user_id in possible_blue.items()
                )
                possible_score += abs(
                    possible_red_uncertainty - possible_blue_uncertainty
                ) * TEAM_UNCERTAINTY_IMBALANCE_WEIGHT
                if possible_score < best_assignment_score:
                    best_assignment_score = possible_score
                    best_assignment_pair = (possible_red, possible_blue)

        red_assignment, blue_assignment = best_assignment_pair

        red_position_mmrs = {
            position: get_position_mmr(profiles.get(user_id, {}), position)
            for position, user_id in red_assignment.items()
        }
        blue_position_mmrs = {
            position: get_position_mmr(profiles.get(user_id, {}), position)
            for position, user_id in blue_assignment.items()
        }
        red_mmr = sum(red_position_mmrs.values())
        blue_mmr = sum(blue_position_mmrs.values())

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

        lane_gaps = {
            position: abs(
                red_position_mmrs[position] - blue_position_mmrs[position]
            )
            for position in POSITIONS
        }
        lane_gap_penalty = sum(
            max(0, gap - TEAM_LANE_GAP_FREE_MARGIN)
            for gap in lane_gaps.values()
        )
        weighted_lane_gap_penalty = lane_gap_penalty * TEAM_LANE_GAP_WEIGHT
        hard_lane_violation_count = sum(
            1
            for gap in lane_gaps.values()
            if gap > TEAM_HARD_LANE_GAP
        )
        weighted_hard_lane_penalty = (
            hard_lane_violation_count * TEAM_HARD_LANE_GAP_PENALTY
        )
        hard_lane_excess_penalty = sum(
            max(0, gap - TEAM_HARD_LANE_GAP) ** 2
            for gap in lane_gaps.values()
        )
        weighted_hard_lane_excess_penalty = (
            hard_lane_excess_penalty * TEAM_HARD_LANE_EXCESS_WEIGHT
        )

        red_expected_winrate, blue_expected_winrate = calculate_expected_winrates(
            red_mmr,
            blue_mmr,
            prediction_calibration
        )
        favored_winrate = max(red_expected_winrate, blue_expected_winrate)
        expected_winrate_penalty = max(
            0.0,
            favored_winrate - TEAM_EXPECTED_WINRATE_LIMIT
        )
        weighted_expected_winrate_penalty = (
            expected_winrate_penalty * TEAM_EXPECTED_WINRATE_WEIGHT
        )

        red_top_two = sum(sorted(red_position_mmrs.values(), reverse=True)[:2])
        blue_top_two = sum(sorted(blue_position_mmrs.values(), reverse=True)[:2])
        top_two_gap = abs(red_top_two - blue_top_two)
        top_two_penalty = max(0, top_two_gap - TEAM_TOP_TWO_GAP_FREE_MARGIN)
        weighted_top_two_penalty = top_two_penalty * TEAM_TOP_TWO_GAP_WEIGHT

        red_autofill_count = sum(
            is_autofilled(profiles.get(user_id, {}), position)
            for position, user_id in red_assignment.items()
        )
        blue_autofill_count = sum(
            is_autofilled(profiles.get(user_id, {}), position)
            for position, user_id in blue_assignment.items()
        )
        autofill_imbalance = abs(red_autofill_count - blue_autofill_count)
        weighted_autofill_penalty = (
            autofill_imbalance * TEAM_AUTOFILL_IMBALANCE_WEIGHT
        )

        red_uncertainty = sum(
            1 - get_position_mmr_confidence(
                profiles.get(user_id, {}), position
            )
            for position, user_id in red_assignment.items()
        )
        blue_uncertainty = sum(
            1 - get_position_mmr_confidence(
                profiles.get(user_id, {}), position
            )
            for position, user_id in blue_assignment.items()
        )
        uncertainty_imbalance = abs(red_uncertainty - blue_uncertainty)
        weighted_uncertainty_penalty = (
            uncertainty_imbalance * TEAM_UNCERTAINTY_IMBALANCE_WEIGHT
        )
        weighted_exact_repeat_penalty = (
            TEAM_EXACT_REPEAT_PENALTY if is_exact_repeat else 0
        )

        total_penalty = (
            weighted_mmr_penalty
            + weighted_position_penalty
            + weighted_same_team_penalty
            + weighted_opponent_penalty
            + weighted_lane_gap_penalty
            + weighted_hard_lane_penalty
            + weighted_hard_lane_excess_penalty
            + weighted_expected_winrate_penalty
            + weighted_top_two_penalty
            + weighted_autofill_penalty
            + weighted_uncertainty_penalty
            + weighted_exact_repeat_penalty
        )

        balance_grade, balance_summary = get_balance_grade(
            mmr_difference,
            lane_gaps,
            position_penalty
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
            "lane_gaps": lane_gaps,
            "lane_gap_penalty": lane_gap_penalty,
            "weighted_lane_gap_penalty": weighted_lane_gap_penalty,
            "hard_lane_violation_count": hard_lane_violation_count,
            "weighted_hard_lane_penalty": weighted_hard_lane_penalty,
            "hard_lane_excess_penalty": hard_lane_excess_penalty,
            "weighted_hard_lane_excess_penalty": weighted_hard_lane_excess_penalty,
            "balance_grade": balance_grade,
            "balance_summary": balance_summary,
            "red_expected_winrate": round(red_expected_winrate, 1),
            "blue_expected_winrate": round(blue_expected_winrate, 1),
            "expected_winrate_penalty": expected_winrate_penalty,
            "weighted_expected_winrate_penalty": weighted_expected_winrate_penalty,
            "top_two_gap": top_two_gap,
            "weighted_top_two_penalty": weighted_top_two_penalty,
            "red_autofill_count": red_autofill_count,
            "blue_autofill_count": blue_autofill_count,
            "autofill_imbalance": autofill_imbalance,
            "weighted_autofill_penalty": weighted_autofill_penalty,
            "red_uncertainty": round(red_uncertainty, 2),
            "blue_uncertainty": round(blue_uncertainty, 2),
            "weighted_uncertainty_penalty": weighted_uncertainty_penalty,
            "is_exact_repeat": is_exact_repeat,
            "weighted_exact_repeat_penalty": weighted_exact_repeat_penalty,
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

        for red_key, blue_key in (
            ("red_autofill_count", "blue_autofill_count"),
            ("red_uncertainty", "blue_uncertainty")
        ):
            (
                selected_candidate[red_key],
                selected_candidate[blue_key]
            ) = (
                selected_candidate[blue_key],
                selected_candidate[red_key]
            )

    # 색상 교환 여부와 상관없이 최종 점수로 다시 계산합니다.
    # 이 값이 최종 레드/블루 팀 점수와 반대로 표시되는 일을 막습니다.
    final_red_winrate, final_blue_winrate = calculate_expected_winrates(
        selected_candidate["red_mmr"],
        selected_candidate["blue_mmr"],
        prediction_calibration
    )
    selected_candidate["red_expected_winrate"] = round(final_red_winrate, 1)
    selected_candidate["blue_expected_winrate"] = round(final_blue_winrate, 1)

    return selected_candidate
