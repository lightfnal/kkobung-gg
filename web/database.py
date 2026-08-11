import sqlite3

from contextlib import contextmanager

from storage.paths import DB_PATH


# ==============================
# 웹 전용 DB 연결 생성
# ==============================

def create_connection():
    """
    웹 요청에서 사용할 새로운 SQLite 연결을 생성합니다.

    각 웹 요청마다 별도 연결을 사용하기 때문에
    FastAPI의 여러 요청이 동시에 들어와도
    하나의 전역 연결을 공유하지 않습니다.
    """

    connection = sqlite3.connect(
        DB_PATH,
        timeout=10
    )

    connection.row_factory = (
        sqlite3.Row
    )

    connection.execute(
        "PRAGMA foreign_keys = ON"
    )

    connection.execute(
        "PRAGMA busy_timeout = 10000"
    )

    return connection


# ==============================
# context manager 방식
# ==============================

@contextmanager
def get_db_connection():
    """
    사용 예시:

    with get_db_connection() as conn:

        cursor = conn.cursor()

        cursor.execute(...)

        rows = cursor.fetchall()

    with 블록이 끝나면
    connection은 자동으로 닫힙니다.
    """

    connection = (
        create_connection()
    )

    try:

        yield connection

    finally:

        connection.close()