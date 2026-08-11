from config import (
    PLACEMENT_GAMES,
    MMR_EARLY_GAMES,
    MMR_K_PLACEMENT,
    MMR_K_EARLY,
    MMR_K_NORMAL,
    INITIAL_HIDDEN_MMR_BY_TIER,
    DEFAULT_INITIAL_HIDDEN_MMR
)

def get_initial_hidden_mmr(
    tier
):
    """
    신규 가입자의 라이엇 티어에 따라
    초기 Hidden MMR을 반환합니다.

    알 수 없는 티어이거나 값이 없으면
    기본 초기 MMR을 사용합니다.
    """

    normalized_tier = (
        str(tier).strip()
        if tier is not None
        else "언랭크"
    )

    return INITIAL_HIDDEN_MMR_BY_TIER.get(
        normalized_tier,
        DEFAULT_INITIAL_HIDDEN_MMR
    )


def get_mmr_k_factor(
    placement_games
):
    """
    지금까지 완료한 경기 수에 따라
    Hidden MMR 변동 계수를 반환합니다.

    0~4경기:
        배치 구간

    5~14경기:
        초기 안정화 구간

    15경기 이상:
        일반 구간
    """

    if placement_games < PLACEMENT_GAMES:
        return MMR_K_PLACEMENT

    if placement_games < MMR_EARLY_GAMES:
        return MMR_K_EARLY

    return MMR_K_NORMAL


def calculate_expected_score(
    player_mmr,
    enemy_avg_mmr
):
    """
    플레이어가 상대 팀을 상대로
    승리할 예상 확률을 계산합니다.

    반환값 예시:
    0.50 = 승리 확률 50%
    0.75 = 승리 확률 75%
    0.25 = 승리 확률 25%
    """

    return 1 / (
        1 + 10 ** (
            (
                enemy_avg_mmr
                - player_mmr
            )
            / 400
        )
    )


def calculate_mmr_change(
    player_mmr,
    enemy_avg_mmr,
    won,
    placement_games
):
    """
    경기 결과에 따라 Hidden MMR 변동값을 계산합니다.

    반영 요소:
    - 현재 개인 Hidden MMR
    - 상대 팀 평균 Hidden MMR
    - 승리 또는 패배
    - 지금까지 완료한 경기 수
    """

    expected_score = calculate_expected_score(
        player_mmr=player_mmr,
        enemy_avg_mmr=enemy_avg_mmr
    )

    actual_score = (
        1
        if won
        else 0
    )

    k_factor = get_mmr_k_factor(
        placement_games
    )

    change = round(
        k_factor
        * (
            actual_score
            - expected_score
        )
    )

    return change


def apply_mmr_result(
    profile,
    enemy_avg_mmr,
    won
):
    """
    플레이어 프로필에 경기 결과를 반영합니다.

    다음 값이 변경됩니다.
    - hidden_mmr
    - placement_games

    변경된 프로필과 MMR 변동값을 반환합니다.
    """

    current_mmr = profile.get(
        "hidden_mmr",
        profile.get(
            "rating",
            1000
        )
    )

    placement_games = profile.get(
        "placement_games",
        0
    )

    mmr_change = calculate_mmr_change(
        player_mmr=current_mmr,
        enemy_avg_mmr=enemy_avg_mmr,
        won=won,
        placement_games=placement_games
    )

    profile["hidden_mmr"] = (
        current_mmr
        + mmr_change
    )

    profile["placement_games"] = (
        placement_games
        + 1
    )

    return profile, mmr_change