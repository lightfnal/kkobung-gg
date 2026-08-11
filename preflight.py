import importlib

from config import (
    ADMIN_IDS,
    BOT_NAME,
    RIOT_API_KEY,
    TOKEN,
    VERSION
)
from storage.paths import validate_runtime_paths
from storage.sqlite_db import (
    backup_database,
    check_database_file_integrity,
    check_database_integrity
)


EXTENSIONS = (
    "cogs.join",
    "cogs.room",
    "cogs.profile",
    "cogs.match",
    "cogs.statistics",
    "cogs.ranking",
    "cogs.record",
    "cogs.duo",
    "cogs.team",
    "cogs.history",
    "cogs.season",
    "cogs.admin_match",
    "cogs.admin_player",
    "cogs.admin_game",
    "cogs.riot",
    "cogs.register"
)


def run_preflight(create_backup=True):
    checks = []

    def record(name, passed, detail):
        checks.append(
            {
                "name": name,
                "passed": bool(passed),
                "detail": str(detail)
            }
        )

    record(
        "Discord 토큰",
        bool(TOKEN),
        "설정됨" if TOKEN else "DISCORD_TOKEN 누락"
    )
    record(
        "Riot API 키",
        bool(RIOT_API_KEY),
        "설정됨" if RIOT_API_KEY else "선택 기능 사용 불가"
    )
    record(
        "관리자 ID",
        bool(ADMIN_IDS),
        f"{len(ADMIN_IDS)}명 등록"
    )

    try:
        validate_runtime_paths()
        record("저장 경로", True, "쓰기 가능")
    except Exception as error:
        record("저장 경로", False, error)

    try:
        integrity_ok, integrity_result = (
            check_database_integrity()
        )
        record(
            "운영 DB 무결성",
            integrity_ok,
            integrity_result
        )
    except Exception as error:
        record("운영 DB 무결성", False, error)

    if create_backup:
        try:
            backup_path = backup_database(
                max_backups=10
            )
            backup_ok, backup_result = (
                check_database_file_integrity(
                    backup_path
                )
            )
            record(
                "검증 백업",
                backup_ok,
                f"{backup_path} ({backup_result})"
            )
        except Exception as error:
            record("검증 백업", False, error)

    failed_extensions = []

    for extension in EXTENSIONS:
        try:
            importlib.import_module(extension)
        except Exception as error:
            failed_extensions.append(
                f"{extension}: {error}"
            )

    record(
        "확장 기능 import",
        not failed_extensions,
        (
            f"{len(EXTENSIONS)}개 정상"
            if not failed_extensions
            else " | ".join(failed_extensions)
        )
    )

    # Riot API 키는 선택 기능이므로 전체 배포 실패 조건에서는 제외합니다.
    required_checks = [
        check
        for check in checks
        if check["name"] != "Riot API 키"
    ]

    return {
        "bot": BOT_NAME,
        "version": VERSION,
        "passed": all(
            check["passed"]
            for check in required_checks
        ),
        "checks": checks
    }


def main():
    result = run_preflight()

    print(
        f"{result['bot']} v{result['version']} 배포 사전점검"
    )

    for check in result["checks"]:
        icon = "✅" if check["passed"] else "❌"
        print(
            f"{icon} {check['name']}: {check['detail']}"
        )

    if result["passed"]:
        print("✅ Discord 로그인 전 점검을 모두 통과했습니다.")
        return 0

    print("❌ 실패 항목을 해결한 뒤 다시 실행해주세요.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
