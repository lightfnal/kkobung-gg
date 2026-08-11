from services.rating_service import RatingService


def print_result(
    title,
    result
):
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)

    print(
        "레이팅:",
        result["rating_before"],
        "→",
        result["rating_after"],
        f"({result['rating_change']:+})"
    )

    print(
        "Hidden MMR:",
        result["hidden_mmr_before"],
        "→",
        result["hidden_mmr_after"],
        f"({result['hidden_mmr_change']:+})"
    )

    print(
        "배치 경기:",
        result["placement_games_before"],
        "→",
        result["placement_games_after"]
    )

    print(
        "승:",
        result["wins_before"],
        "→",
        result["wins_after"]
    )

    print(
        "패:",
        result["losses_before"],
        "→",
        result["losses_after"]
    )

    print(
        "연승:",
        result["win_streak_before"],
        "→",
        result["win_streak_after"]
    )

    print(
        "연패:",
        result["lose_streak_before"],
        "→",
        result["lose_streak_after"]
    )

    print(
        "최고 연승:",
        result["best_win_streak_before"],
        "→",
        result["best_win_streak_after"]
    )

    print(
        "MVP:",
        result["mvp_before"],
        "→",
        result["mvp_after"]
    )

    print(
        "티어:",
        result["tier_before"],
        "→",
        result["tier_after"]
    )

    print(
        "배치 완료:",
        result["placement_completed"]
    )


# ============================================================
# 기본 테스트 프로필
# ============================================================

base_profile = {
    "discord_id": "123456789",
    "discord_nickname": "테스트유저",
    "riot_name": "테스트#KR1",

    "rating": 1000,
    "hidden_mmr": 1000,
    "placement_games": 0,

    "wins": 0,
    "losses": 0,

    "win_streak": 0,
    "lose_streak": 0,
    "best_win_streak": 0,

    "mvp": 0
}


# ============================================================
# 테스트 1
# 일반 승리
# ============================================================

result1 = RatingService.process_match_result(
    profile=base_profile,
    won=True,
    team_avg_rating=1000,
    enemy_avg_rating=1000,
    enemy_avg_mmr=1000,
    is_mvp=False
)

print_result(
    "테스트 1 - 일반 승리",
    result1
)


# ============================================================
# 테스트 2
# 일반 패배
# ============================================================

result2 = RatingService.process_match_result(
    profile=base_profile,
    won=False,
    team_avg_rating=1000,
    enemy_avg_rating=1000,
    enemy_avg_mmr=1000,
    is_mvp=False
)

print_result(
    "테스트 2 - 일반 패배",
    result2
)


# ============================================================
# 테스트 3
# MVP 승리
# ============================================================

result3 = RatingService.process_match_result(
    profile=base_profile,
    won=True,
    team_avg_rating=1000,
    enemy_avg_rating=1000,
    enemy_avg_mmr=1000,
    is_mvp=True
)

print_result(
    "테스트 3 - MVP 승리",
    result3
)


# ============================================================
# 테스트 4
# 2연승 상태에서 승리 → 3연승
# ============================================================

streak_profile = {
    **base_profile,

    "rating": 1100,
    "hidden_mmr": 1100,

    "wins": 5,
    "losses": 2,

    "win_streak": 2,
    "lose_streak": 0,
    "best_win_streak": 2
}

result4 = RatingService.process_match_result(
    profile=streak_profile,
    won=True,
    team_avg_rating=1100,
    enemy_avg_rating=1100,
    enemy_avg_mmr=1100,
    is_mvp=False
)

print_result(
    "테스트 4 - 3연승 진입",
    result4
)


# ============================================================
# 테스트 5
# 4연승 상태에서 승리 → 5연승
# ============================================================

five_streak_profile = {
    **base_profile,

    "rating": 1200,
    "hidden_mmr": 1200,

    "wins": 10,
    "losses": 3,

    "win_streak": 4,
    "lose_streak": 0,
    "best_win_streak": 4
}

result5 = RatingService.process_match_result(
    profile=five_streak_profile,
    won=True,
    team_avg_rating=1200,
    enemy_avg_rating=1200,
    enemy_avg_mmr=1200,
    is_mvp=False
)

print_result(
    "테스트 5 - 5연승 진입",
    result5
)


# ============================================================
# 테스트 6
# 2연패 상태에서 패배 → 3연패
# ============================================================

lose_streak_profile = {
    **base_profile,

    "rating": 1050,
    "hidden_mmr": 1050,

    "wins": 4,
    "losses": 5,

    "win_streak": 0,
    "lose_streak": 2,
    "best_win_streak": 3
}

result6 = RatingService.process_match_result(
    profile=lose_streak_profile,
    won=False,
    team_avg_rating=1050,
    enemy_avg_rating=1050,
    enemy_avg_mmr=1050,
    is_mvp=False
)

print_result(
    "테스트 6 - 3연패 진입",
    result6
)


# ============================================================
# 테스트 7
# 배치 마지막 경기
# ============================================================

placement_profile = {
    **base_profile,

    "rating": 1000,
    "hidden_mmr": 1100,

    "placement_games": 4
}

result7 = RatingService.process_match_result(
    profile=placement_profile,
    won=True,
    team_avg_rating=1000,
    enemy_avg_rating=1000,
    enemy_avg_mmr=1100,
    is_mvp=False
)

print_result(
    "테스트 7 - 배치 완료",
    result7
)


# ============================================================
# 테스트 8
# 원본 profile이 변하지 않는지 확인
# ============================================================

original_profile = {
    **base_profile
}

before_profile = {
    **original_profile
}

RatingService.process_match_result(
    profile=original_profile,
    won=True,
    team_avg_rating=1000,
    enemy_avg_rating=1000,
    enemy_avg_mmr=1000,
    is_mvp=True
)

print()
print("=" * 60)
print("테스트 8 - 원본 profile 보호")
print("=" * 60)

if original_profile == before_profile:
    print("✅ PASS - 원본 profile이 변경되지 않았습니다.")
else:
    print("❌ FAIL - 원본 profile이 변경되었습니다.")
    print(
        "변경 전:",
        before_profile
    )
    print(
        "변경 후:",
        original_profile
    )


# ============================================================
# 기본 검증
# ============================================================

assert result1["wins_after"] == 1
assert result1["losses_after"] == 0
assert result1["win_streak_after"] == 1
assert result1["lose_streak_after"] == 0

assert result2["wins_after"] == 0
assert result2["losses_after"] == 1
assert result2["win_streak_after"] == 0
assert result2["lose_streak_after"] == 1

assert result3["mvp_after"] == 1

assert result4["win_streak_after"] == 3

assert result5["win_streak_after"] == 5
assert result5["best_win_streak_after"] == 5

assert result6["lose_streak_after"] == 3
assert result6["win_streak_after"] == 0

assert result7["placement_completed"] is True

assert original_profile == before_profile


print()
print("=" * 60)
print("✅ RatingService 전체 기본 테스트 통과")
print("=" * 60)