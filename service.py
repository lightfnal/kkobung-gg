import logging
import os
import signal
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | %(levelname)s | "
        "%(name)s | %(message)s"
    )
)

logger = logging.getLogger("service")

from storage.database_backup import BackupError, create_database_backup
from storage.paths import BACKUP_DIR, DB_PATH


KST = timezone(timedelta(hours=9))


def _integer_setting(name, default, minimum, maximum):
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} 환경 변수는 정수여야 합니다.") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(
            f"{name} 환경 변수는 {minimum}~{maximum} 범위여야 합니다."
        )
    return value


def run_scheduled_backup_if_due():
    enabled = os.getenv("AUTO_BACKUP_ENABLED", "true").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return

    backup_hour = _integer_setting("AUTO_BACKUP_HOUR_KST", 4, 0, 23)
    retention_limit = _integer_setting("ADMIN_MAX_BACKUPS", 20, 1, 1000)
    now = datetime.now(KST)
    if now.hour != backup_hour:
        return

    marker = DB_PATH.parent / ".last_auto_backup_date"
    today = now.date().isoformat()
    try:
        if marker.is_file() and marker.read_text(encoding="utf-8").strip() == today:
            return
        result = create_database_backup(
            source=DB_PATH,
            directory=BACKUP_DIR,
            retention_limit=retention_limit,
        )
        temporary_marker = marker.with_suffix(".tmp")
        temporary_marker.write_text(today, encoding="utf-8")
        os.replace(temporary_marker, marker)
        logger.info(
            "자동 DB 백업 완료: %s (오래된 백업 %s개 정리)",
            result.path,
            result.deleted_old_backups,
        )
    except (BackupError, OSError):
        logger.exception("자동 DB 백업에 실패했습니다.")


def apply_pending_restore():
    database = os.fspath(DB_PATH)
    upload = os.path.join(os.path.dirname(database), "upload.db")
    marker = os.path.join(os.path.dirname(database), "restore.request")
    if not os.path.exists(marker):
        return

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    rollback = BACKUP_DIR / f"pre_restore_{time.strftime('%Y%m%d_%H%M%S')}.db"
    logger.warning("대기 중인 데이터베이스 복원을 시작합니다.")
    try:
        with sqlite3.connect(f"file:{upload}?mode=ro", uri=True) as conn:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("업로드 DB 무결성 검사 실패")
        with sqlite3.connect(database, timeout=30) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        shutil.copy2(database, rollback)
        os.replace(upload, database)
        for suffix in ("-wal", "-shm"):
            try:
                os.unlink(database + suffix)
            except FileNotFoundError:
                pass
        with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as conn:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("복원 후 무결성 검사 실패")
        os.unlink(marker)
        logger.warning("데이터베이스 복원이 완료되었습니다: %s", rollback)
    except Exception:
        logger.exception("데이터베이스 복원 실패, 기존 DB를 복구합니다.")
        if os.path.exists(rollback):
            shutil.copy2(rollback, database)
        raise

processes = []
shutting_down = False


def stop_processes():
    global shutting_down

    if shutting_down:
        return

    shutting_down = True
    logger.info("서비스 종료를 시작합니다.")

    for name, process in processes:
        if process.poll() is None:
            logger.info("%s 프로세스를 종료합니다.", name)
            process.terminate()

    for name, process in processes:
        if process.poll() is not None:
            continue

        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            logger.warning(
                "%s 프로세스가 종료되지 않아 강제 종료합니다.",
                name
            )
            process.kill()
            process.wait()

    logger.info("모든 프로세스가 종료되었습니다.")


def handle_signal(signum, frame):
    logger.info("종료 신호를 받았습니다: %s", signum)
    stop_processes()


def start_process(name, command):
    logger.info(
        "%s 프로세스를 시작합니다: %s",
        name,
        " ".join(command)
    )

    process = subprocess.Popen(command)
    processes.append((name, process))
    return process


def main():
    apply_pending_restore()
    port = os.getenv("PORT", "10000")

    signal.signal(
        signal.SIGTERM,
        handle_signal
    )
    signal.signal(
        signal.SIGINT,
        handle_signal
    )

    web_process = start_process(
        "FastAPI",
        [
            sys.executable,
            "-m",
            "uvicorn",
            "web.app:app",
            "--host",
            "0.0.0.0",
            "--port",
            port,
            "--workers",
            "1",
            "--proxy-headers"
        ]
    )

    bot_process = start_process(
        "Discord Bot",
        [
            sys.executable,
            "bot.py"
        ]
    )

    exit_code = 0
    next_backup_check = 0.0

    try:
        while not shutting_down:
            current_time = time.monotonic()
            if current_time >= next_backup_check:
                run_scheduled_backup_if_due()
                next_backup_check = current_time + 60.0

            for name, process in processes:
                return_code = process.poll()

                if return_code is not None:
                    logger.error(
                        "%s 프로세스가 종료되었습니다. "
                        "종료 코드: %s",
                        name,
                        return_code
                    )
                    exit_code = (
                        return_code
                        if return_code != 0
                        else 1
                    )
                    return exit_code

            time.sleep(1)

    finally:
        stop_processes()

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
