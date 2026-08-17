import logging
import os
import signal
import shutil
import sqlite3
import subprocess
import sys
import time


logging.basicConfig(
    level=logging.INFO,
    format=(
        "%(asctime)s | %(levelname)s | "
        "%(name)s | %(message)s"
    )
)

logger = logging.getLogger("service")

from storage.paths import BACKUP_DIR, DB_PATH


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

    try:
        while not shutting_down:
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
