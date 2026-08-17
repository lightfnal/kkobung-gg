"""Consistent SQLite backup creation shared by web and scheduled jobs."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class BackupError(RuntimeError):
    """Raised when a database backup cannot be created or retained safely."""


@dataclass(frozen=True)
class BackupResult:
    path: Path
    deleted_old_backups: int


def create_database_backup(
    source: Path,
    directory: Path,
    retention_limit: int,
) -> BackupResult:
    source = Path(source).expanduser().resolve()
    directory = Path(directory).expanduser().resolve()
    if not source.is_file():
        raise BackupError("Database file is unavailable")
    if not 1 <= retention_limit <= 1000:
        raise BackupError("Backup retention limit is invalid")

    try:
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
        destination = directory / f"backup_{timestamp}.db"
        temporary = directory / f".{destination.name}.tmp"
        temporary.unlink(missing_ok=True)

        with closing(sqlite3.connect(source, timeout=30.0)) as source_connection:
            source_connection.execute("PRAGMA busy_timeout = 30000")
            with closing(
                sqlite3.connect(temporary, timeout=30.0)
            ) as backup_connection:
                source_connection.backup(
                    backup_connection,
                    pages=256,
                    sleep=0.05,
                )
                integrity = backup_connection.execute(
                    "PRAGMA integrity_check"
                ).fetchone()
                backup_connection.commit()

        if integrity is None or integrity[0] != "ok":
            raise BackupError("Created backup failed integrity_check")

        os.replace(temporary, destination)
        backup_files = sorted(
            (
                path
                for path in directory.glob("backup_*.db")
                if path.is_file()
            ),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        deleted = 0
        for old_backup in backup_files[retention_limit:]:
            old_backup.unlink()
            deleted += 1
        return BackupResult(
            path=destination,
            deleted_old_backups=deleted,
        )
    except BackupError:
        try:
            temporary.unlink(missing_ok=True)
        except (OSError, UnboundLocalError):
            pass
        raise
    except (OSError, sqlite3.Error) as exc:
        try:
            temporary.unlink(missing_ok=True)
        except (OSError, UnboundLocalError):
            pass
        raise BackupError("Database backup could not be created") from exc
