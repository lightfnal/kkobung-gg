from config import (
    RATING_WIN_BASE,
    RATING_LOSS_BASE,
    RATING_MVP_BONUS,
    RATING_PARTICIPATION_BONUS,
    RATING_MIN_WIN,
    RATING_MAX_WIN,
    RATING_MAX_LOSS,
    RATING_WIN_STREAK_3_BONUS,
    RATING_WIN_STREAK_5_BONUS,
    RATING_UNDERDOG_THRESHOLD,
    RATING_UNDERDOG_BONUS
)


def calculate_expected_score(
    player_rating,
    enemy_avg_rating
):
    """
    Elo 공식으로 예상 승률을 계산합니다.

    반환값 예시:
    0.5  = 50%
    0.75 = 75%
    """

    return 1 / (
        1 + 10 ** (
            (
                enemy_avg_rating
                - player_rating
            )
            / 400
        )
    )


def calculate_elo_change(
    player_rating,
    enemy_avg_rating,
    won,
    k_factor=40
):
    """
    기존 레이팅 시스템에서 사용하던 Elo 계산 함수입니다.

    cogs/match.py가 새 레이팅 함수로 완전히 전환될 때까지
    기존 기능 보호를 위해 유지합니다.
    """

    expected = calculate_expected_score(
        player_rating,
        enemy_avg_rating
    )

    actual = 1 if won else 0

    return round(
        k_factor * (
            actual - expected
        )
    )


def get_win_streak_bonus(
    win_streak
):
    """
    현재 연승 횟수에 따라 공개 레이팅 보너스를 반환합니다.

    0~2연승: 보너스 없음
    3~4연승: 3연승 보너스
    5연승 이상: 5연승 보너스
    """

    if win_streak >= 5:
        return RATING_WIN_STREAK_5_BONUS

    if win_streak >= 3:
        return RATING_WIN_STREAK_3_BONUS

    return 0


def get_underdog_bonus(
    team_avg_rating,
    enemy_avg_rating,
    won
):
    """
    약팀이 승리했을 때 언더독 보너스를 반환합니다.

    개인 레이팅이 아니라 양 팀의 평균 레이팅을 비교합니다.
    """

    if not won:
        return 0

    rating_difference = (
        enemy_avg_rating
        - team_avg_rating
    )

    if (
        rating_difference
        >= RATING_UNDERDOG_THRESHOLD
    ):
        return RATING_UNDERDOG_BONUS

    return 0


def clamp_rating_change(
    change,
    won
):
    """
    한 경기에서 오르거나 내려갈 수 있는 점수의
    최소·최대 범위를 적용합니다.
    """

    if won:
        return max(
            RATING_MIN_WIN,
            min(
                change,
                RATING_MAX_WIN
            )
        )

    return max(
        change,
        RATING_MAX_LOSS
    )


def calculate_rating_change(
    won,
    team_avg_rating,
    enemy_avg_rating,
    win_streak=0,
    is_mvp=False
):
    """
    새로운 공개 레이팅 변동값을 계산합니다.

    반영 요소:
    - 기본 승리 또는 패배 점수
    - 참가 보너스
    - MVP 보너스
    - 연승 보너스
    - 언더독 승리 보너스
    - 최소·최대 변동 제한

    win_streak에는 이번 경기 결과까지 반영된
    현재 연승 횟수를 전달합니다.
    """

    if won:
        change = RATING_WIN_BASE
    else:
        change = RATING_LOSS_BASE

    # 경기 참가 보너스는 승패와 관계없이 적용
    change += RATING_PARTICIPATION_BONUS

    # MVP는 승리팀 선수에게만 적용
    if won and is_mvp:
        change += RATING_MVP_BONUS

    # 연승 보너스는 승리했을 때만 적용
    if won:
        change += get_win_streak_bonus(
            win_streak
        )

    change += get_underdog_bonus(
        team_avg_rating=team_avg_rating,
        enemy_avg_rating=enemy_avg_rating,
        won=won
    )

    return clamp_rating_change(
        change=change,
        won=won
    )


def get_rating_tier(
    rating
):
    """
    공개 레이팅 점수에 따른 등급 이름을 반환합니다.
    """

    if rating >= 2000:
        return "🔥 Challenger"

    if rating >= 1800:
        return "👑 Master"

    if rating >= 1600:
        return "💎 Diamond"

    if rating >= 1400:
        return "🥇 Platinum"

    if rating >= 1200:
        return "🥈 Gold"

    if rating >= 1000:
        return "🥉 Silver"

    return "🔰 Bronze"