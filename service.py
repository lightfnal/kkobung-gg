import logging
import os
import signal
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