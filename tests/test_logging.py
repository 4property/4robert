from __future__ import annotations

import logging
import shutil
import unittest
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from core.logging import (
    DailyDirectoryRotatingFileHandler,
    configure_logging,
    log_persistent_event,
    resolve_dated_log_directory,
)


@contextmanager
def _workspace_temp_dir():
    temp_root = Path(__file__).resolve().parents[1] / ".tmp_test_cases"
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_dir = temp_root / f"logging_{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _reset_logging() -> None:
    logging.shutdown()
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()

    audit_logger = logging.getLogger("cpihed.audit")
    for handler in list(audit_logger.handlers):
        audit_logger.removeHandler(handler)
        handler.close()
    audit_logger.propagate = False


class LoggingTests(unittest.TestCase):
    def tearDown(self) -> None:
        _reset_logging()

    def test_resolve_dated_log_directory_groups_logs_by_month_and_day(self) -> None:
        with _workspace_temp_dir() as workspace_dir:
            log_root = workspace_dir / "logs"

            resolved = resolve_dated_log_directory(log_root, log_date=date(2026, 4, 23))

            self.assertEqual(
                resolved,
                log_root.resolve() / "04-2026" / "23-04-2026",
            )

    def test_daily_directory_handler_switches_to_new_day_without_reconfigure(self) -> None:
        with _workspace_temp_dir() as workspace_dir:
            active_date = {"value": date(2026, 4, 23)}

            def current_date_provider() -> date:
                return active_date["value"]

            handler = DailyDirectoryRotatingFileHandler(
                workspace_dir / "logs",
                "application.log",
                maxBytes=50_000,
                backupCount=2,
                current_date_provider=current_date_provider,
            )
            handler.setFormatter(logging.Formatter("%(message)s"))

            logger = logging.getLogger("tests.daily_directory")
            logger.handlers.clear()
            logger.propagate = False
            logger.setLevel(logging.INFO)
            logger.addHandler(handler)

            logger.info("day one")
            active_date["value"] = date(2026, 4, 24)
            logger.info("day two")

            handler.close()

            day_one_log = workspace_dir / "logs" / "04-2026" / "23-04-2026" / "application.log"
            day_two_log = workspace_dir / "logs" / "04-2026" / "24-04-2026" / "application.log"
            self.assertEqual(day_one_log.read_text(encoding="utf-8").strip(), "day one")
            self.assertEqual(day_two_log.read_text(encoding="utf-8").strip(), "day two")

    def test_configure_logging_writes_all_persistent_logs_inside_dated_directory(self) -> None:
        with _workspace_temp_dir() as workspace_dir:
            frozen_date = date(2026, 4, 23)
            with patch("core.logging._current_log_date", return_value=frozen_date):
                configure_logging(
                    "INFO",
                    workspace_dir=workspace_dir,
                    persistent_logging_enabled=True,
                    persistent_log_directory="logs",
                )

                logger = logging.getLogger("tests.configure_logging")
                logger.info("application entry")
                logger.warning("warning entry")
                logger.error("error entry")
                log_persistent_event("publish_completed", property_id=123)

            logging.shutdown()

            dated_dir = workspace_dir / "logs" / "04-2026" / "23-04-2026"
            application_log = dated_dir / "application.log"
            errors_log = dated_dir / "errors.log"
            warnings_log = dated_dir / "warnings-errors.log"
            audit_log = dated_dir / "audit.jsonl"

            self.assertTrue(application_log.exists())
            self.assertTrue(errors_log.exists())
            self.assertTrue(warnings_log.exists())
            self.assertTrue(audit_log.exists())

            application_content = application_log.read_text(encoding="utf-8")
            self.assertIn("23/04/2026", application_content)
            self.assertIn("application entry", application_content)
            self.assertIn("warning entry", warnings_log.read_text(encoding="utf-8"))
            self.assertIn("error entry", warnings_log.read_text(encoding="utf-8"))
            self.assertIn("error entry", errors_log.read_text(encoding="utf-8"))
            self.assertIn('"event_type": "publish_completed"', audit_log.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
