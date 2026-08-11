from storage.sqlite_db import (
    validate_rating_history
)


def print_issue(
    index,
    issue
):
    issue_type = (
        issue.get("type")
    )

    print()
    print(
        f"[{index}] "
        f"{issue_type}"
    )

    print(
        "-" * 60
    )


    # ==============================
    # 경기 내부 계산 불일치
    # ==============================

    if (
        issue_type
        == "rating_math_mismatch"
    ):

        print(
            "플레이어:",
            issue.get(
                "discord_id"
            )
        )

        print(
            "경기:",
            issue.get(
                "match_id"
            )
        )

        print(
            "경기 전 레이팅:",
            issue.get(
                "rating_before"
            )
        )

        print(
            "레이팅 변화:",
            issue.get(
                "rating_change"
            )
        )

        print(
            "저장된 경기 후 레이팅:",
            issue.get(
                "rating_after"
            )
        )

        print(
            "정상 계산값:",
            issue.get(
                "expected_rating_after"
            )
        )


    # ==============================
    # 경기 연결 불일치
    # ==============================

    elif (
        issue_type
        == "rating_chain_mismatch"
    ):

        print(
            "플레이어:",
            issue.get(
                "discord_id"
            )
        )

        print(
            "이전 경기:",
            issue.get(
                "previous_match_id"
            )
        )

        print(
            "현재 경기:",
            issue.get(
                "match_id"
            )
        )

        print(
            "이전 경기 종료 레이팅:",
            issue.get(
                "previous_rating_after"
            )
        )

        print(
            "현재 경기 시작 레이팅:",
            issue.get(
                "current_rating_before"
            )
        )


    # ==============================
    # 현재 플레이어 레이팅 불일치
    # ==============================

    elif (
        issue_type
        == "current_rating_mismatch"
    ):

        print(
            "플레이어:",
            issue.get(
                "discord_id"
            )
        )

        print(
            "마지막 경기:",
            issue.get(
                "last_match_id"
            )
        )

        print(
            "players.rating:",
            issue.get(
                "player_rating"
            )
        )

        print(
            "경기 기록상 레이팅:",
            issue.get(
                "history_rating"
            )
        )


    # ==============================
    # 플레이어 자체 없음
    # ==============================

    elif (
        issue_type
        == "player_missing"
    ):

        print(
            "플레이어:",
            issue.get(
                "discord_id"
            )
        )

        print(
            "마지막 경기:",
            issue.get(
                "last_match_id"
            )
        )

        print(
            "players 테이블에서 "
            "플레이어를 찾을 수 없습니다."
        )


    # ==============================
    # 알 수 없는 유형
    # ==============================

    else:

        for key, value in (
            issue.items()
        ):

            print(
                f"{key}: {value}"
            )


def main():

    print()
    print(
        "=" * 60
    )

    print(
        "꼬붕.gg 레이팅 기록 검증"
    )

    print(
        "=" * 60
    )


    result = (
        validate_rating_history()
    )


    print()

    print(
        "검사 경기 참가 기록:",
        result[
            "checked_records"
        ]
    )

    print(
        "검사 플레이어:",
        result[
            "checked_players"
        ]
    )

    print(
        "발견 문제:",
        result[
            "issue_count"
        ]
    )


    # ==============================
    # 정상
    # ==============================

    if result["ok"]:

        print()
        print(
            "✅ 레이팅 기록이 "
            "정상적으로 연결되어 있습니다."
        )

        print()

        return


    # ==============================
    # 문제 발견
    # ==============================

    print()
    print(
        "⚠️ 레이팅 기록에서 "
        "불일치가 발견되었습니다."
    )


    issues = (
        result["issues"]
    )


    for index, issue in enumerate(
        issues,
        start=1
    ):

        print_issue(
            index,
            issue
        )


    print()
    print(
        "=" * 60
    )

    print(
        "총 문제:",
        len(issues)
    )

    print(
        "=" * 60
    )

    print()


if __name__ == "__main__":
    main()