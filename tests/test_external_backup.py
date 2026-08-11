import sqlite3
import unittest

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from external_backup import (
    get_default_external_backup_dir,
    run_external_backup
)


class TestExternalBackup(unittest.TestCase):

    def test_default_path_uses_separate_onedrive_folder(self):
        with patch.dict(
            "os.environ",
            {"OneDrive": "C:/OneDrive"},
            clear=False
        ):
            backup_dir = get_default_external_backup_dir()

        self.assertEqual(
            backup_dir,
            Path("C:/OneDrive") / "꼬붕봇_외부백업"
        )

    def test_external_backup_contains_committed_data(self):
        with TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            source = sqlite3.connect(root / "source.db")
            source.execute(
                "CREATE TABLE status (value TEXT NOT NULL)"
            )
            source.execute(
                "INSERT INTO status VALUES ('ready')"
            )
            source.commit()

            try:
                backup_path = run_external_backup(
                    backup_dir=root / "external",
                    source_connection=source
                )
            finally:
                source.close()

            restored = sqlite3.connect(backup_path)

            try:
                value = restored.execute(
                    "SELECT value FROM status"
                ).fetchone()[0]
            finally:
                restored.close()

            self.assertEqual(value, "ready")

    def test_missing_onedrive_path_is_reported(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(
                RuntimeError,
                "OneDrive 경로"
            ):
                get_default_external_backup_dir()


if __name__ == "__main__":
    unittest.main()
