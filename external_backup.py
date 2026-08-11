import logging
import os

from logging.handlers import RotatingFileHandler
from pathlib import Path

from storage.paths import PROJECT_ROOT
from storage.sqlite_db import (
    backup_database,
    check_database_file_integrity
)


DEFAULT_MAX_BACKUPS = 30


def get_default_external_backup_dir():
    one_drive = (
        os.getenv("OneDrive")
        or os.getenv("OneDriveConsumer")
    )

    if not one_drive:
        raise RuntimeError(
            "OneDrive 경로를 찾을 수 없습니다. "
            "OneDrive 환경 변수를 확인해주세요."
        )

    return Path(one_drive) / "꼬붕봇_외부백업"


def run_external_backup(
    backup_dir=None,
    max_backups=DEFAULT_MAX_BACKUPS,
    source_connection=None
):
    if backup_dir is None:
        backup_dir = get_default_external_backup_dir()

    backup_path = backup_database(
        max_backups=max_backups,
        source_connection=source_connection,
        backup_dir=backup_dir
    )
    integrity_ok, integrity_result = (
        check_database_file_integrity(
            backup_path
        )
    )

    if not integrity_ok:
        raise RuntimeError(
            "외부 백업 무결성 검사 실패: "
            f"{integrity_result}"
        )

    return backup_path


def configure_backup_logging():
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "backup.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s"
        )
    )
    logger = logging.getLogger("external_backup")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for old_handler in list(logger.handlers):
        logger.removeHandler(old_handler)
        old_handler.close()

    logger.addHandler(handler)
    return logger


def main():
    logger = configure_backup_logging()

    try:
        backup_path = run_external_backup()
        logger.info(
            "외부 DB 백업 완료: %s",
            backup_path
        )
        print(f"외부 DB 백업 완료: {backup_path}")
        return 0

    except Exception:
        logger.exception("외부 DB 백업 실패")
        print("외부 DB 백업 실패: logs/backup.log를 확인해주세요.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
