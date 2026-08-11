import sqlite3
import unittest

from pathlib import Path
from tempfile import TemporaryDirectory

from storage.schema_migrations import (
    apply_schema_migrations,
    get_schema_version,
    set_schema_version
)


class TestSchemaMigrations(unittest.TestCase):

    def test_migrations_run_once_in_version_order(self):
        connection = sqlite3.connect(":memory:")
        calls = []

        def migration_one(conn):
            calls.append(1)
            conn.execute("CREATE TABLE first_table (id INTEGER)")

        def migration_two(conn):
            calls.append(2)
            conn.execute("CREATE TABLE second_table (id INTEGER)")

        migrations = {1: migration_one, 2: migration_two}
        apply_schema_migrations(
            connection,
            migrations=migrations,
            target_version=2,
            create_backup=False
        )
        apply_schema_migrations(
            connection,
            migrations=migrations,
            target_version=2,
            create_backup=False
        )

        self.assertEqual(calls, [1, 2])
        self.assertEqual(get_schema_version(connection), 2)
        connection.close()

    def test_failed_migration_rolls_back_version_and_schema(self):
        connection = sqlite3.connect(":memory:")
        apply_schema_migrations(
            connection,
            migrations={1: lambda conn: None},
            target_version=1,
            create_backup=False
        )

        def broken_migration(conn):
            conn.execute("CREATE TABLE should_rollback (id INTEGER)")
            raise ValueError("broken")

        with self.assertRaisesRegex(RuntimeError, "마이그레이션 2 실패"):
            apply_schema_migrations(
                connection,
                migrations={2: broken_migration},
                target_version=2,
                create_backup=False
            )

        table = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = ?",
            ("should_rollback",)
        ).fetchone()
        self.assertIsNone(table)
        self.assertEqual(get_schema_version(connection), 1)
        connection.close()

    def test_newer_database_version_is_rejected(self):
        connection = sqlite3.connect(":memory:")
        set_schema_version(connection, 99)
        connection.commit()

        with self.assertRaisesRegex(RuntimeError, "실행 코드보다 높습니다"):
            apply_schema_migrations(
                connection,
                target_version=1,
                create_backup=False
            )

        connection.close()

    def test_backup_is_created_before_first_migration(self):
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            connection = sqlite3.connect(root / "source.db")
            connection.execute("CREATE TABLE data (value TEXT)")
            connection.execute("INSERT INTO data VALUES ('before')")
            connection.commit()

            version, backup_path = apply_schema_migrations(
                connection,
                backup_dir=root / "backups",
                migrations={1: lambda conn: None},
                target_version=1
            )
            connection.close()

            self.assertEqual(version, 1)
            self.assertTrue(backup_path.is_file())
            backup = sqlite3.connect(backup_path)

            try:
                value = backup.execute(
                    "SELECT value FROM data"
                ).fetchone()[0]
            finally:
                backup.close()

            self.assertEqual(value, "before")


if __name__ == "__main__":
    unittest.main()
