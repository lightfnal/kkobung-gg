import logging

from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_FORMAT = (
    "%(asctime)s | %(levelname)s | "
    "%(name)s | %(message)s"
)
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5


class MaximumLevelFilter(logging.Filter):

    def __init__(self, maximum_level):
        super().__init__()
        self.maximum_level = maximum_level

    def filter(self, record):
        return record.levelno <= self.maximum_level


def configure_logging(
    log_dir=None,
    max_bytes=DEFAULT_MAX_BYTES,
    backup_count=DEFAULT_BACKUP_COUNT
):
    """터미널과 순환 로그 파일에 운영 로그를 기록합니다."""

    if log_dir is None:
        log_dir = (
            Path(__file__).resolve().parent.parent
            / "logs"
        )
    else:
        log_dir = Path(log_dir)

    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    for handler in list(root_logger.handlers):
        if getattr(handler, "inhouse_bot_handler", False):
            root_logger.removeHandler(handler)
            handler.close()

    bot_handler = RotatingFileHandler(
        log_dir / "bot.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8"
    )
    bot_handler.setLevel(logging.INFO)
    bot_handler.addFilter(
        MaximumLevelFilter(logging.WARNING)
    )
    bot_handler.setFormatter(formatter)
    bot_handler.inhouse_bot_handler = True

    error_handler = RotatingFileHandler(
        log_dir / "error.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    error_handler.inhouse_bot_handler = True

    root_logger.addHandler(bot_handler)
    root_logger.addHandler(error_handler)

    return {
        "bot": log_dir / "bot.log",
        "error": log_dir / "error.log"
    }
