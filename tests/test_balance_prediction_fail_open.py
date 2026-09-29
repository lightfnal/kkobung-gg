import sqlite3
import unittest
from unittest.mock import patch

from storage.sqlite_db import add_match_balance_prediction


class TestBalancePredictionFailOpen(unittest.TestCase):
    def test_optional_prediction_failure_does_not_rollback_parent_transaction(self):
        with (
            patch("storage.sqlite_db.cursor") as mocked_cursor,
            patch("storage.sqlite_db.conn") as mocked_connection
        ):
            mocked_cursor.execute.side_effect = sqlite3.OperationalError("missing table")
            saved = add_match_balance_prediction(
                1, 50.0, 1.0, auto_commit=False
            )
            self.assertFalse(saved)
            mocked_connection.rollback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
