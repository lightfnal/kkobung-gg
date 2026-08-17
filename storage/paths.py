from pathlib import Path
import tempfile


# 프로젝트 최상위 폴더
PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)


# =====================================
# 데이터 저장 위치
# Render에서는 Persistent Disk 사용
# 로컬에서는 기존 data 폴더 사용
# =====================================

RENDER_DATA_DIR = Path("/var/data")

if RENDER_DATA_DIR.exists():
    DATA_DIR = RENDER_DATA_DIR
else:
    DATA_DIR = PROJECT_ROOT / "data"

DATA_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# SQLite DB
DB_PATH = DATA_DIR / "blooming.db"

# 자동 백업 폴더
BACKUP_DIR = DATA_DIR / "backups"

# 운영 로그 폴더
LOG_DIR = PROJECT_ROOT / "logs"


# 참가자 및 호환용 JSON
PLAYERS_FILE = DATA_DIR / "players.json"

# 경기 기록 JSON
MATCH_HISTORY_FILE = (
    DATA_DIR
    / "match_history.json"
)

# 진행 중인 경기 상태
GAME_STATE_FILE = (
    DATA_DIR
    / "game_state.json"
)

# 같은 팀 및 상대 기록
TEAM_HISTORY_FILE = (
    DATA_DIR
    / "team_history.json"
)

# 예전 프로필 마이그레이션 파일
PROFILE_PATH = (
    DATA_DIR
    / "profiles.json"
)

# 여러 내전 방의 상태
ROOMS_STATE_FILE = (
    DATA_DIR
    / "rooms_state.json"
)


def validate_runtime_paths(
    data_dir=DATA_DIR,
    backup_dir=BACKUP_DIR
):
    """데이터 및 백업 폴더를 만들고 쓰기 가능 여부를 검사합니다."""

    for directory in (
        Path(data_dir),
        Path(backup_dir)
    ):
        directory.mkdir(
            parents=True,
            exist_ok=True
        )

        temporary_path = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=directory,
                prefix="startup_check_",
                suffix=".tmp",
                delete=False
            ) as temporary_file:
                temporary_file.write(
                    "runtime path check"
                )
                temporary_path = Path(
                    temporary_file.name
                )

        except OSError as error:
            raise RuntimeError(
                "데이터 저장 경로에 쓸 수 없습니다: "
                f"{directory}"
            ) from error

        finally:
            if (
                temporary_path is not None
                and temporary_path.exists()
            ):
                try:
                    temporary_path.unlink()
                except OSError:
                    pass

    return True