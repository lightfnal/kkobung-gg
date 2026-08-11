from services.rating_service import RatingService


def make_player(
    user_id,
    rating,
    hidden_mmr,
    wins=0,
    losses=0,
    win_streak=0,
    lose_streak=0,
    best_win_streak=0,
    mvp=0,
    placement_games=0
):
    return {
        "discord_id": str(user_id),
        "discord_nickname": f"테스트{user_id}",
        "riot_name": f"테스트{user_id}#KR1",
        "rating": rating,
        "hidden_mmr": hidden_mmr,
        "placement_games": placement_games,
        "wins": wins,
        "losses": losses,
        "win_streak": win_streak,
        "lose_streak": lose_streak,
        "best_win_streak": best_win_streak,
        "mvp": mvp
    }


# ============================================================
# 10명 테스트 데이터
# ============================================================

profiles = {
    "1": make_player(
        1,
        rating=1100,
        hidden_mmr=1120
    ),
    "2": make_player(
        2,
        rating=1050,
        hidden_mmr=1080,
        win_streak=2,
        best_win_streak=2
    ),
    "3": make_player(
        3,
        rating=1000,
        hidden_mmr=1030
    ),
    "4": make_player(
        4,
        rating=980,
        hidden_mmr=1000
    ),
    "5": make_player(
        5,
        rating=970,
        hidden_mmr=990
    ),

    "6": make_player(
        6,
        rating=1080,
        hidden_mmr=1100
    ),
    "7": make_player(
        7,
        rating=1040,
        hidden_mmr=1070
    ),
    "8": make_player(
        8,
        rating=1010,
        hidden_mmr=1020
    ),
    "9": make_player(
        9,
        rating=990,
        hidden_mmr=1000,
        lose_streak=2
    ),
    "10": make_player(
        10,
        rating=960,
        hidden_mmr=980
    )
}


winner_players = [
    "1",
    "2",
    "3",
    "4",
    "5"
]

loser_players = [
    "6",
    "7",
    "8",
    "9",
    "10"
]

mvp_id = "2"


# ============================================================
# 경기 전 평균
# ============================================================

winner_avg = sum(
    profiles[user_id]["rating"]
    for user_id in winner_players
) / len(winner_players)

loser_avg = sum(
    profiles[user_id]["rating"]
    for user_id in loser_players
) / len(loser_players)


winner_mmr_avg = sum(
    profiles[user_id]["hidden_mmr"]
    for user_id in winner_players
) / len(winner_players)

loser_mmr_avg = sum(
    profiles[user_id]["hidden_mmr"]
    for user_id in loser_players
) / len(loser_players)


print("=" * 70)
print("경기 전 팀 평균")
print("=" * 70)

print(
    f"승리팀 평균 레이팅: {winner_avg:.1f}"
)

print(
    f"패배팀 평균 레이팅: {loser_avg:.1f}"
)

print(
    f"승리팀 평균 Hidden MMR: "
    f"{winner_mmr_avg:.1f}"
)

print(
    f"패배팀 평균 Hidden MMR: "
    f"{loser_mmr_avg:.1f}"
)


# ============================================================
# 결과 저장용
# ============================================================

results = {}


# ============================================================
# 승리팀
# ============================================================

for user_id in winner_players:

    result = RatingService.process_match_result(
        profile=profiles[user_id],
        won=True,
        team_avg_rating=winner_avg,
        enemy_avg_rating=loser_avg,
        enemy_avg_mmr=loser_mmr_avg,
        is_mvp=(user_id == mvp_id)
    )

    results[user_id] = result


# ============================================================
# 패배팀
# ============================================================

for user_id in loser_players:

    result = RatingService.process_match_result(
        profile=profiles[user_id],
        won=False,
        team_avg_rating=loser_avg,
        enemy_avg_rating=winner_avg,
        enemy_avg_mmr=winner_mmr_avg,
        is_mvp=False
    )

    results[user_id] = result


# ============================================================
# 결과 출력
# ============================================================

print()
print("=" * 70)
print("경기 결과")
print("=" * 70)


for user_id in winner_players + loser_players:

    result = results[user_id]

    status = (
        "승리"
        if result["won"]
        else "패배"
    )

    mvp_text = (
        " / MVP"
        if result["is_mvp"]
        else ""
    )

    print()
    print(
        f"[{user_id}] "
        f"{status}{mvp_text}"
    )

    print(
        "레이팅:",
        result["rating_before"],
        "→",
        result["rating_after"],
        f"({result['rating_change']:+})"
    )

    print(
        "MMR:",
        result["hidden_mmr_before"],
        "→",
        result["hidden_mmr_after"],
        f"({result['hidden_mmr_change']:+})"
    )

    print(
        "전적:",
        f"{result['wins_before']}승 "
        f"{result['losses_before']}패",
        "→",
        f"{result['wins_after']}승 "
        f"{result['losses_after']}패"
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
        "MVP:",
        result["mvp_before"],
        "→",
        result["mvp_after"]
    )


# ============================================================
# 자동 검증
# ============================================================

# 승리팀 5명 모두 승수 +1
for user_id in winner_players:
    result = results[user_id]

    assert (
        result["wins_after"]
        ==
        result["wins_before"] + 1
    )

    assert (
        result["losses_after"]
        ==
        result["losses_before"]
    )

    assert (
        result["win_streak_after"]
        ==
        result["win_streak_before"] + 1
    )

    assert (
        result["lose_streak_after"]
        == 0
    )


# 패배팀 5명 모두 패수 +1
for user_id in loser_players:
    result = results[user_id]

    assert (
        result["losses_after"]
        ==
        result["losses_before"] + 1
    )

    assert (
        result["wins_after"]
        ==
        result["wins_before"]
    )

    assert (
        result["win_streak_after"]
        == 0
    )

    assert (
        result["lose_streak_after"]
        ==
        result["lose_streak_before"] + 1
    )


# MVP는 딱 1명만 증가
mvp_increase_count = sum(
    1
    for result in results.values()
    if (
        result["mvp_after"]
        ==
        result["mvp_before"] + 1
    )
)

assert mvp_increase_count == 1

assert (
    results[mvp_id]["mvp_after"]
    ==
    results[mvp_id]["mvp_before"] + 1
)


# MVP가 아닌 선수는 MVP 유지
for user_id, result in results.items():

    if user_id == mvp_id:
        continue

    assert (
        result["mvp_after"]
        ==
        result["mvp_before"]
    )


# 원본 프로필이 변경되지 않았는지 확인
assert profiles["2"]["mvp"] == 0
assert profiles["2"]["wins"] == 0
assert profiles["2"]["win_streak"] == 2

assert profiles["9"]["losses"] == 0
assert profiles["9"]["lose_streak"] == 2


print()
print("=" * 70)
print("✅ 10명 경기 레이팅 시뮬레이션 전체 통과")
print("=" * 70)