import logging
import unittest

from tempfile import TemporaryDirectory

from utils.logging_config import configure_logging


class TestLoggingConfig(unittest.TestCase):

    def close_bot_handlers(self):
        root_logger = logging.getLogger()

        for handler in list(root_logger.handlers):
            if getattr(handler, "inhouse_bot_handler", False):
                root_logger.removeHandler(handler)
                handler.close()

    def tearDown(self):
        self.close_bot_handlers()

    def test_writes_general_and_error_logs_separately(self):
        with TemporaryDirectory() as temporary_dir:
            paths = configure_logging(
                log_dir=temporary_dir
            )
            logger = logging.getLogger("test.operations")

            logger.info("startup complete")
            logger.error("command failed")

            for handler in logging.getLogger().handlers:
                handler.flush()

            bot_log = paths["bot"].read_text(
                encoding="utf-8"
            )
            error_log = paths["error"].read_text(
                encoding="utf-8"
            )

            self.assertIn("startup complete", bot_log)
            self.assertNotIn("command failed", bot_log)
            self.assertIn("command failed", error_log)
            self.close_bot_handlers()

    def test_rotates_log_when_size_limit_is_reached(self):
        with TemporaryDirectory() as temporary_dir:
            paths = configure_logging(
                log_dir=temporary_dir,
                max_bytes=100,
                backup_count=2
            )
            logger = logging.getLogger("test.rotation")

            for number in range(20):
                logger.info(
                    "rotation message %s %s",
                    number,
                    "x" * 40
                )

            for handler in logging.getLogger().handlers:
                handler.flush()

            rotated_logs = list(
                paths["bot"].parent.glob("bot.log.*")
            )

            self.assertTrue(paths["bot"].exists())
            self.assertTrue(rotated_logs)
            self.assertLessEqual(len(rotated_logs), 2)
            self.close_bot_handlers()
