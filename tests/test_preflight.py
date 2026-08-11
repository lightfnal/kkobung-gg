import unittest

from pathlib import Path
from unittest.mock import patch

import preflight


class TestPreflight(unittest.TestCase):

    def test_successful_preflight_reports_all_required_checks(self):
        with (
            patch("preflight.TOKEN", "token"),
            patch("preflight.RIOT_API_KEY", "riot-key"),
            patch("preflight.validate_runtime_paths"),
            patch(
                "preflight.check_database_integrity",
                return_value=(True, "ok")
            ),
            patch(
                "preflight.backup_database",
                return_value=Path("backup.db")
            ),
            patch(
                "preflight.check_database_file_integrity",
                return_value=(True, "ok")
            ),
            patch("preflight.importlib.import_module")
        ):
            result = preflight.run_preflight()

        self.assertTrue(result["passed"])
        self.assertEqual(result["version"], "0.3.0")
        self.assertEqual(
            result["checks"][-1]["detail"],
            "16개 정상"
        )

    def test_database_failure_blocks_deployment(self):
        with (
            patch("preflight.TOKEN", "token"),
            patch("preflight.validate_runtime_paths"),
            patch(
                "preflight.check_database_integrity",
                return_value=(False, "malformed")
            ),
            patch("preflight.importlib.import_module")
        ):
            result = preflight.run_preflight(
                create_backup=False
            )

        self.assertFalse(result["passed"])

    def test_riot_key_is_optional_but_reported(self):
        with (
            patch("preflight.TOKEN", "token"),
            patch("preflight.RIOT_API_KEY", None),
            patch("preflight.validate_runtime_paths"),
            patch(
                "preflight.check_database_integrity",
                return_value=(True, "ok")
            ),
            patch("preflight.importlib.import_module")
        ):
            result = preflight.run_preflight(
                create_backup=False
            )

        riot_check = next(
            check
            for check in result["checks"]
            if check["name"] == "Riot API 키"
        )
        self.assertFalse(riot_check["passed"])
        self.assertTrue(result["passed"])


if __name__ == "__main__":
    unittest.main()
