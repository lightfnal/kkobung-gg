"""Authenticated database administration endpoints."""

from __future__ import annotations

import hmac
import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from storage.paths import BACKUP_DIR, DB_PATH


router = APIRouter(prefix="/admin", tags=["Admin"])
templates = Jinja2Templates(directory="web/templates")

_backup_lock = threading.Lock()
_upload_lock = threading.Lock()
_DEFAULT_MAX_UPLOAD_BYTES = 100 * 1024 * 1024
_SQLITE_HEADER = b"SQLite format 3\x00"


class DatabaseInfo(BaseModel):
    database: str
    size_mb: float
    players: int
    matches: int
    backup_count: int


class BackupItem(BaseModel):
    name: str
    size_mb: float
    created_at: str


class BackupCreated(BaseModel):
    success: bool
    backup: str


class DatabaseUploaded(BaseModel):
    success: bool
    upload: str
    size_mb: float
    integrity_check: str


class RestoreScheduled(BaseModel):
    success: bool
    message: str


def _authenticate(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Validate an RFC 6750-style Authorization: Bearer token header."""
    configured_token = os.getenv("ADMIN_TOKEN")
    if not configured_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin API is not configured",
        )

    scheme, separator, supplied_token = (authorization or "").partition(" ")
    if (
        not separator
        or scheme.lower() != "bearer"
        or not supplied_token
        or not hmac.compare_digest(supplied_token, configured_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _db_path() -> Path:
    path = Path(DB_PATH).expanduser().resolve()
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database file is unavailable",
        )
    return path


def _backup_dir(*, create: bool = False) -> Path:
    path = Path(BACKUP_DIR).expanduser().resolve()
    try:
        if create:
            path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Backup directory could not be created",
        ) from exc

    if path.exists() and not path.is_dir():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Configured backup path is not a directory",
        )
    return path


def _backup_files() -> list[Path]:
    directory = _backup_dir()
    if not directory.exists():
        return []
    try:
        files = [
            path
            for path in directory.iterdir()
            if path.is_file() and path.name.startswith("backup_") and path.suffix == ".db"
        ]
        return sorted(files, key=lambda path: path.stat().st_mtime_ns, reverse=True)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Backups could not be listed",
        ) from exc


def _table_count(connection: sqlite3.Connection, table: str) -> int:
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if exists is None:
        return 0
    # The identifier is selected only from constants inside this module.
    row = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
    return int(row[0]) if row else 0


def _database_counts(path: Path) -> tuple[int, int]:
    try:
        uri = path.as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5.0) as connection:
            connection.execute("PRAGMA query_only = ON")
            return (
                _table_count(connection, "players"),
                _table_count(connection, "matches"),
            )
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database information could not be read",
        ) from exc


def _max_upload_bytes() -> int:
    raw_value = os.getenv("ADMIN_MAX_UPLOAD_MB", "100")
    try:
        megabytes = int(raw_value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_MAX_UPLOAD_MB must be an integer",
        ) from exc
    if megabytes < 1:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_MAX_UPLOAD_MB must be at least 1",
        )
    return megabytes * 1024 * 1024


def _validate_uploaded_database(path: Path) -> None:
    try:
        with path.open("rb") as uploaded_file:
            if uploaded_file.read(len(_SQLITE_HEADER)) != _SQLITE_HEADER:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Uploaded file is not a SQLite 3 database",
                )

        uri = path.as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=10.0) as connection:
            connection.execute("PRAGMA query_only = ON")
            result = connection.execute("PRAGMA integrity_check").fetchone()
        if result is None or result[0] != "ok":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded database failed integrity_check",
            )
    except HTTPException:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded database could not be validated",
        ) from exc


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def admin_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={},
    )


@router.get(
    "/db-info",
    response_model=DatabaseInfo,
    dependencies=[Depends(_authenticate)],
)
def get_database_info() -> DatabaseInfo:
    path = _db_path()
    try:
        size_mb = round(path.stat().st_size / (1024 * 1024), 2)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database file information could not be read",
        ) from exc

    players, matches = _database_counts(path)
    return DatabaseInfo(
        database=str(path),
        size_mb=size_mb,
        players=players,
        matches=matches,
        backup_count=len(_backup_files()),
    )


@router.get(
    "/backups",
    response_model=list[BackupItem],
    dependencies=[Depends(_authenticate)],
)
def list_backups() -> list[BackupItem]:
    result: list[BackupItem] = []
    try:
        for path in _backup_files():
            stat = path.stat()
            result.append(
                BackupItem(
                    name=path.name,
                    size_mb=round(stat.st_size / (1024 * 1024), 2),
                    created_at=datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
                )
            )
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Backup metadata could not be read",
        ) from exc
    return result


@router.get(
    "/backups/{filename}/download",
    response_class=FileResponse,
    dependencies=[Depends(_authenticate)],
)
def download_backup(filename: str) -> FileResponse:
    """Download a backup created by the admin backup endpoint."""
    if (
        Path(filename).name != filename
        or not filename.startswith("backup_")
        or not filename.endswith(".db")
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid backup filename",
        )

    directory = _backup_dir()
    target = (directory / filename).resolve()
    if target.parent != directory or not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Backup file was not found",
        )

    return FileResponse(
        path=target,
        media_type="application/vnd.sqlite3",
        filename=target.name,
    )


@router.post(
    "/backup",
    response_model=BackupCreated,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_authenticate)],
)
def create_backup() -> BackupCreated:
    source = _db_path()
    directory = _backup_dir(create=True)

    with _backup_lock:
        timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
        destination = directory / f"backup_{timestamp}.db"
        temporary = directory / f".{destination.name}.tmp"
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Database backup could not be created",
            ) from exc

    return BackupCreated(success=True, backup=destination.name)


@router.post(
    "/upload-db",
    response_model=DatabaseUploaded,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_authenticate)],
)
def upload_database(
    database: Annotated[UploadFile, File(description="SQLite database file")],
) -> DatabaseUploaded:
    """Validate and stage a database upload without replacing the live database."""
    live_database = _db_path()
    destination = live_database.parent / "upload.db"
    temporary = live_database.parent / ".upload.db.tmp"
    max_bytes = _max_upload_bytes()
    bytes_written = 0

    with _upload_lock:
        try:
            with temporary.open("wb") as output:
                while chunk := database.file.read(1024 * 1024):
                    bytes_written += len(chunk)
                    if bytes_written > max_bytes:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="Uploaded database exceeds the configured size limit",
                        )
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())

            if bytes_written == 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Uploaded file is empty",
                )

            _validate_uploaded_database(temporary)
            os.replace(temporary, destination)
        except HTTPException:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        except OSError as exc:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Uploaded database could not be stored",
            ) from exc

    return DatabaseUploaded(
        success=True,
        upload=destination.name,
        size_mb=round(bytes_written / (1024 * 1024), 2),
        integrity_check="ok",
    )


@router.post(
    "/restore",
    response_model=RestoreScheduled,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(_authenticate)],
)
def schedule_restore() -> RestoreScheduled:
    live_database = _db_path()
    upload = live_database.parent / "upload.db"
    marker = live_database.parent / "restore.request"
    if not upload.is_file():
        raise HTTPException(status_code=404, detail="No uploaded database is staged")
    _validate_uploaded_database(upload)
    marker.write_text("restore\n", encoding="utf-8")

    def stop_web_process():
        time.sleep(1.0)
        os._exit(75)

    threading.Thread(target=stop_web_process, daemon=True).start()
    return RestoreScheduled(
        success=True,
        message="Restore scheduled; service restart requested",
    )
