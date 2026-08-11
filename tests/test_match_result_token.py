import sqlite3
import unittest

from unittest.mock import patch

from storage import sqlite_db


class TestMatchResultToken(
    unittest.TestCase
):

    def setUp(self):
        """
        실제 운영 DB 대신 메모리 전용 SQLite DB를 사용합니다.
        테스트가 끝나면 데이터가 모두 사라집니다.
        """

        self.test_conn = sqlite3.connect(
            ":memory:"
        )

        self.test_conn.row_factory = (
            sqlite3.Row
        )

        self.test_cursor = (
            self.test_conn.cursor()
        )

        self.test_cursor.execute(
            """
            CREATE TABLE matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_date TEXT NOT NULL,
                winner TEXT NOT NULL,
                mvp_discord_id TEXT,
                season_id INTEGER,
                room_id TEXT NOT NULL DEFAULT '1',
                result_token TEXT
            )
            """
        )

        self.test_cursor.execute(
            """
            CREATE UNIQUE INDEX
            idx_matches_result_token
            ON matches(result_token)
            WHERE result_token IS NOT NULL
            """
        )

        self.test_conn.commit()

        # sqlite_db 함수들이 운영 DB 대신
        # 위에서 만든 메모리 DB를 사용하게 합니다.
        self.conn_patcher = patch(
            "storage.sqlite_db.conn",
            self.test_conn
        )

        self.cursor_patcher = patch(
            "storage.sqlite_db.cursor",
            self.test_cursor
        )

        self.season_patcher = patch(
            "storage.sqlite_db.get_active_season",
            return_value=None
        )

        self.conn_patcher.start()
        self.cursor_patcher.start()
        self.season_patcher.start()

    def tearDown(self):
        """
        패치를 해제하고 메모리 DB를 닫습니다.
        """

        self.season_patcher.stop()
        self.cursor_patcher.stop()
        self.conn_patcher.stop()

        self.test_conn.close()

    def test_match_can_be_found_by_result_token(
        self
    ):
        """
        저장한 결과 토큰으로 같은 경기 기록을
        다시 찾을 수 있어야 합니다.
        """

        match_id = sqlite_db.add_match(
            match_date="2026-08-05 21:00",
            winner="red",
            mvp_discord_id="1001",
            room_id="2",
            result_token="result-token-1"
        )

        saved_match = (
            sqlite_db.get_match_by_result_token(
                "result-token-1"
            )
        )

        self.assertIsNotNone(
            saved_match
        )

        self.assertEqual(
            saved_match["id"],
            match_id
        )

        self.assertEqual(
            saved_match["winner"],
            "red"
        )

        self.assertEqual(
            saved_match["room_id"],
            "2"
        )

        self.assertEqual(
            saved_match["result_token"],
            "result-token-1"
        )

    def test_duplicate_result_token_is_rejected(
        self
    ):
        """
        같은 결과 토큰으로 두 번째 경기를 저장하면
        SQLite가 중복 저장을 차단해야 합니다.
        """

        sqlite_db.add_match(
            match_date="2026-08-05 21:00",
            winner="red",
            mvp_discord_id="1001",
            room_id="1",
            result_token="duplicate-token"
        )

        with self.assertRaises(
            sqlite3.IntegrityError
        ):
            sqlite_db.add_match(
                match_date="2026-08-05 21:01",
                winner="blue",
                mvp_discord_id="2001",
                room_id="1",
                result_token="duplicate-token"
            )

        # 중복 시도 후에도 첫 번째 경기만 존재해야 합니다.
        saved_count = self.test_conn.execute(
            """
            SELECT COUNT(*)
            FROM matches
            WHERE result_token = ?
            """,
            (
                "duplicate-token",
            )
        ).fetchone()[0]

        self.assertEqual(
            saved_count,
            1
        )

    def test_null_result_tokens_are_allowed(
        self
    ):
        """
        이전 경기처럼 결과 토큰이 없는 기록은
        여러 개 저장할 수 있어야 합니다.
        """

        sqlite_db.add_match(
            match_date="2026-08-05 21:00",
            winner="red",
            mvp_discord_id=None,
            room_id="1",
            result_token=None
        )

        sqlite_db.add_match(
            match_date="2026-08-05 21:01",
            winner="blue",
            mvp_discord_id=None,
            room_id="2",
            result_token=None
        )

        saved_count = self.test_conn.execute(
            """
            SELECT COUNT(*)
            FROM matches
            WHERE result_token IS NULL
            """
        ).fetchone()[0]

        self.assertEqual(
            saved_count,
            2
        )

    def test_empty_result_token_returns_none(
        self
    ):
        """
        빈 토큰은 경기 검색을 실행하지 않고
        None을 반환해야 합니다.
        """

        self.assertIsNone(
            sqlite_db.get_match_by_result_token(
                None
            )
        )

        self.assertIsNone(
            sqlite_db.get_match_by_result_token(
                ""
            )
        )


if __name__ == "__main__":
    unittest.main()