import shutil
import sqlite3
import unittest

from pathlib import Path
from tempfile import TemporaryDirectory

from storage.sqlite_db import (
    backup_database,
    check_database_file_integrity
)


class TestDatabaseBackup(unittest.TestCase):

    def create_source_database(self, database_path):
        connection = sqlite3.connect(database_path)
        connection.execute(
            "CREATE TABLE players ("
            "discord_id TEXT PRIMARY KEY, "
            "rating INTEGER NOT NULL)"
        )
        connection.execute(
            "INSERT INTO players VALUES (?, ?)",
            ("1001", 1234)
        )
        connection.commit()
        return connection

    def test_backup_can_restore_original_data(self):
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source_path = root / "source.db"
            restored_path = root / "restored.db"
            backup_dir = root / "backups"
            source_connection = self.create_source_database(
                source_path
            )

            try:
                backup_path = backup_database(
                    source_connection=source_connection,
                    backup_dir=backup_dir
                )

                source_connection.execute(
                    "DELETE FROM players"
                )
                source_connection.commit()

            finally:
                source_connection.close()

            shutil.copy2(backup_path, restored_path)

            integrity_ok, integrity_result = (
                check_database_file_integrity(
                    restored_path
                )
            )

            self.assertTrue(
                integrity_ok,
                integrity_result
            )

            restored_connection = sqlite3.connect(
                restored_path
            )

            try:
                row = restored_connection.execute(
                    "SELECT discord_id, rating FROM players"
                ).fetchone()
            finally:
                restored_connection.close()

            self.assertEqual(row, ("1001", 1234))

    def test_reports_missing_and_corrupt_database_files(self):
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            missing_path = root / "missing.db"
            corrupt_path = root / "corrupt.db"
            corrupt_path.write_bytes(b"not a sqlite database")

            missing_ok, missing_result = (
                check_database_file_integrity(
                    missing_path
                )
            )
            corrupt_ok, corrupt_result = (
                check_database_file_integrity(
                    corrupt_path
                )
            )

            self.assertFalse(missing_ok)
            self.assertIn("파일이 없습니다", missing_result)
            self.assertFalse(corrupt_ok)
            self.assertTrue(corrupt_result)

    def test_backup_retention_keeps_only_newest_files(self):
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            backup_dir = root / "backups"
            connection = self.create_source_database(
                root / "source.db"
            )

            try:
                for rating in range(4):
                    connection.execute(
                        "UPDATE players SET rating = ?",
                        (1200 + rating,)
                    )
                    connection.commit()
                    backup_database(
                        max_backups=2,
                        source_connection=connection,
                        backup_dir=backup_dir
                    )
            finally:
                connection.close()

            backup_files = list(
                backup_dir.glob("blooming_*.db")
            )

            self.assertEqual(len(backup_files), 2)


if __name__ == "__main__":
    unittest.main()
