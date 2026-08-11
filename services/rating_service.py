from copy import deepcopy

from config import PLACEMENT_GAMES

from utils.rating import (
    calculate_rating_change,
    get_rating_tier
)

from utils.mmr import (
    calculate_mmr_change
)


class RatingService:
    """
    경기 결과에 따른 플레이어 개인 기록 계산을 담당합니다.

    담당 범위:
    - 공개 레이팅
    - Hidden MMR
    - 배치 경기 수
    - 승/패
    - 연승/연패
    - 최고 연승
    - MVP
    - 티어 변화 확인용 데이터

    DB 저장은 이 서비스에서 하지 않습니다.
    """

    @staticmethod
    def _safe_int(
        value,
        default=0
    ):
        try:
            return int(value)

        except (
            TypeError,
            ValueError
        ):
            return default


    @staticmethod
    def process_match_result(
        profile,
        won,
        team_avg_rating,
        enemy_avg_rating,
        enemy_avg_mmr,
        is_mvp=False
    ):
        """
        플레이어 1명의 경기 결과를 계산합니다.

        원본 profile을 직접 변경하지 않고
        복사본을 만들어 결과를 반환합니다.
        """

        if profile is None:
            raise ValueError(
                "profile이 필요합니다."
            )

        updated_profile = deepcopy(
            profile
        )


        # ==============================
        # 경기 전 공개 레이팅
        # ==============================

        rating_before = RatingService._safe_int(
            updated_profile.get(
                "rating",
                1000
            ),
            1000
        )


        # ==============================
        # 경기 전 Hidden MMR
        # ==============================

        hidden_mmr_before = (
            RatingService._safe_int(
                updated_profile.get(
                    "hidden_mmr",
                    rating_before
                ),
                rating_before
            )
        )


        # ==============================
        # 경기 전 배치 경기 수
        # ==============================

        placement_games_before = (
            RatingService._safe_int(
                updated_profile.get(
                    "placement_games",
                    0
                )
            )
        )


        # ==============================
        # 경기 전 승패
        # ==============================

        wins_before = (
            RatingService._safe_int(
                updated_profile.get(
                    "wins",
                    0
                )
            )
        )

        losses_before = (
            RatingService._safe_int(
                updated_profile.get(
                    "losses",
                    0
                )
            )
        )


        # ==============================
        # 경기 전 연승 / 연패
        # ==============================

        win_streak_before = (
            RatingService._safe_int(
                updated_profile.get(
                    "win_streak",
                    0
                )
            )
        )

        lose_streak_before = (
            RatingService._safe_int(
                updated_profile.get(
                    "lose_streak",
                    0
                )
            )
        )

        best_win_streak_before = (
            RatingService._safe_int(
                updated_profile.get(
                    "best_win_streak",
                    0
                )
            )
        )


        # ==============================
        # 경기 전 MVP
        # ==============================

        mvp_before = (
            RatingService._safe_int(
                updated_profile.get(
                    "mvp",
                    0
                )
            )
        )


        # ==============================
        # 경기 전 티어
        # ==============================

        tier_before = get_rating_tier(
            rating_before
        )


        # ==============================
        # 이번 경기 후 연승 / 연패
        # ==============================

        if won:

            win_streak_after = (
                win_streak_before
                + 1
            )

            lose_streak_after = 0

            best_win_streak_after = max(
                best_win_streak_before,
                win_streak_after
            )

        else:

            win_streak_after = 0

            lose_streak_after = (
                lose_streak_before
                + 1
            )

            best_win_streak_after = (
                best_win_streak_before
            )


        # ==============================
        # 공개 레이팅 변화
        # ==============================

        rating_change = (
            calculate_rating_change(
                won=bool(won),
                team_avg_rating=team_avg_rating,
                enemy_avg_rating=enemy_avg_rating,
                win_streak=(
                    win_streak_after
                    if won
                    else 0
                ),
                is_mvp=(
                    bool(is_mvp)
                    if won
                    else False
                )
            )
        )

        rating_after = (
            rating_before
            + rating_change
        )


        # ==============================
        # Hidden MMR 변화
        # ==============================

        hidden_mmr_change = (
            calculate_mmr_change(
                player_mmr=hidden_mmr_before,
                enemy_avg_mmr=enemy_avg_mmr,
                won=bool(won),
                placement_games=(
                    placement_games_before
                )
            )
        )

        hidden_mmr_after = (
            hidden_mmr_before
            + hidden_mmr_change
        )


        # ==============================
        # 배치 경기 수
        # ==============================

        placement_games_after = (
            placement_games_before
            + 1
        )

        placement_completed = (
            placement_games_before
            < PLACEMENT_GAMES
            <= placement_games_after
        )


        # ==============================
        # 승패 누적
        # ==============================

        if won:

            wins_after = (
                wins_before
                + 1
            )

            losses_after = (
                losses_before
            )

        else:

            wins_after = (
                wins_before
            )

            losses_after = (
                losses_before
                + 1
            )


        # ==============================
        # MVP
        # ==============================

        if (
            won
            and is_mvp
        ):

            mvp_after = (
                mvp_before
                + 1
            )

        else:

            mvp_after = (
                mvp_before
            )


        # ==============================
        # 티어
        # ==============================

        tier_after = get_rating_tier(
            rating_after
        )


        # ==============================
        # 프로필 반영
        # ==============================

        updated_profile[
            "rating"
        ] = rating_after

        updated_profile[
            "hidden_mmr"
        ] = hidden_mmr_after

        updated_profile[
            "placement_games"
        ] = placement_games_after

        updated_profile[
            "wins"
        ] = wins_after

        updated_profile[
            "losses"
        ] = losses_after

        updated_profile[
            "win_streak"
        ] = win_streak_after

        updated_profile[
            "lose_streak"
        ] = lose_streak_after

        updated_profile[
            "best_win_streak"
        ] = best_win_streak_after

        updated_profile[
            "mvp"
        ] = mvp_after


        # ==============================
        # 결과 반환
        # ==============================

        return {

            "profile":
                updated_profile,

            # 공개 레이팅
            "rating_before":
                rating_before,

            "rating_after":
                rating_after,

            "rating_change":
                rating_change,

            # 티어
            "tier_before":
                tier_before,

            "tier_after":
                tier_after,

            # Hidden MMR
            "hidden_mmr_before":
                hidden_mmr_before,

            "hidden_mmr_after":
                hidden_mmr_after,

            "hidden_mmr_change":
                hidden_mmr_change,

            # 배치
            "placement_games_before":
                placement_games_before,

            "placement_games_after":
                placement_games_after,

            "placement_completed":
                placement_completed,

            # 승패
            "wins_before":
                wins_before,

            "wins_after":
                wins_after,

            "losses_before":
                losses_before,

            "losses_after":
                losses_after,

            # 연승 / 연패
            "win_streak_before":
                win_streak_before,

            "win_streak_after":
                win_streak_after,

            "lose_streak_before":
                lose_streak_before,

            "lose_streak_after":
                lose_streak_after,

            "best_win_streak_before":
                best_win_streak_before,

            "best_win_streak_after":
                best_win_streak_after,

            # MVP
            "mvp_before":
                mvp_before,

            "mvp_after":
                mvp_after,

            # 경기 결과
            "won":
                bool(won),

            "is_mvp":
                bool(
                    is_mvp
                    and won
                )
        }