"""Unit tests for `apps.api.readiness.build_readiness_report`.

The readiness builder mixes filesystem checks, settings inspection and a
DB smoke test. The integration-side checks that hit Postgres live in
`tests/integration/apps_api/`; this module focuses on the pure-Python
shape and short-circuits the DB and ffmpeg dependencies via patching.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from apps.api import readiness as readiness_module
from apps.api.readiness import build_readiness_report
from shared.errors import ApplicationError


def _patch_runtime_dependencies(workspace_dir: Path):
    """Stub the optional capability checks so the test focuses on shape."""

    return [
        patch.object(
            readiness_module,
            "_resolve_ffmpeg_binary",
            return_value=str(workspace_dir / "ffmpeg"),
        ),
        patch.object(
            readiness_module,
            "_resolve_font_path",
            return_value=workspace_dir / "font.ttf",
        ),
        patch.object(
            readiness_module,
            "_resolve_background_audio_paths",
            return_value=(workspace_dir / "audio.mp3",),
        ),
    ]


class BuildReadinessReportTests(unittest.TestCase):
    def test_report_marks_ready_when_database_and_storage_pass(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace_dir = Path(tmp)
            patches = _patch_runtime_dependencies(workspace_dir)
            with patch.object(readiness_module, "_ensure_database_writable", return_value=None):
                for context in patches:
                    context.start()
                try:
                    report = build_readiness_report(
                        workspace_dir,
                        database_locator="postgresql://stub:stub@stub/stub",
                        site_secrets={"acme": "supersecret-not-placeholder"},
                        worker_count=1,
                        security_disabled=False,
                    )
                finally:
                    for context in patches:
                        context.stop()

        self.assertTrue(report["ready"])
        self.assertTrue(report["production_ready"])
        for key in (
            "ready",
            "production_ready",
            "checks",
            "capabilities",
            "errors",
            "warnings",
            "failures",
            "environment",
        ):
            self.assertIn(key, report)
        self.assertTrue(report["checks"]["database_writable"])
        self.assertTrue(report["checks"]["storage_writable"])
        self.assertTrue(report["checks"]["ffmpeg_available"])
        self.assertTrue(report["checks"]["reel_font_available"])
        self.assertTrue(report["checks"]["background_audio_available"])
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["failures"], [])
        environment = report["environment"]
        self.assertEqual(environment["workspace_dir"], str(workspace_dir.resolve()))
        self.assertIn("database_url", environment)

    def test_report_flags_database_failure(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace_dir = Path(tmp)
            db_error = ApplicationError(
                "PostgreSQL is unreachable.",
                context={"database_url": "postgresql://***/stub"},
            )

            patches = _patch_runtime_dependencies(workspace_dir)
            with patch.object(
                readiness_module,
                "_ensure_database_writable",
                side_effect=db_error,
            ):
                for context in patches:
                    context.start()
                try:
                    report = build_readiness_report(
                        workspace_dir,
                        database_locator="postgresql://stub:stub@stub/stub",
                        site_secrets={"acme": "supersecret-not-placeholder"},
                        worker_count=1,
                        security_disabled=False,
                    )
                finally:
                    for context in patches:
                        context.stop()

        self.assertFalse(report["ready"])
        self.assertFalse(report["checks"]["database_writable"])
        self.assertTrue(report["checks"]["storage_writable"])
        self.assertEqual(len(report["failures"]), 1)
        self.assertEqual(report["failures"][0]["check"], "database_writable")
        self.assertTrue(report["errors"])

    def test_report_flags_storage_failure_when_workspace_unwritable(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace_dir = Path(tmp)
            patches = _patch_runtime_dependencies(workspace_dir)
            with patch.object(readiness_module, "_ensure_database_writable", return_value=None):
                with patch.object(
                    readiness_module,
                    "_ensure_storage_writable",
                    side_effect=ApplicationError(
                        "Workspace volume is read-only.",
                        context={"directory": str(workspace_dir)},
                    ),
                ):
                    for context in patches:
                        context.start()
                    try:
                        report = build_readiness_report(
                            workspace_dir,
                            database_locator="postgresql://stub:stub@stub/stub",
                            site_secrets={"acme": "supersecret-not-placeholder"},
                            worker_count=1,
                            security_disabled=False,
                        )
                    finally:
                        for context in patches:
                            context.stop()

        self.assertFalse(report["ready"])
        self.assertFalse(report["checks"]["storage_writable"])
        self.assertTrue(any(f["check"] == "storage_writable" for f in report["failures"]))

    def test_report_flags_missing_site_secrets_unless_security_disabled(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace_dir = Path(tmp)
            patches = _patch_runtime_dependencies(workspace_dir)
            with patch.object(readiness_module, "_ensure_database_writable", return_value=None):
                for context in patches:
                    context.start()
                try:
                    report = build_readiness_report(
                        workspace_dir,
                        database_locator="postgresql://stub:stub@stub/stub",
                        site_secrets={},
                        worker_count=1,
                        security_disabled=False,
                    )
                finally:
                    for context in patches:
                        context.stop()

        self.assertFalse(report["checks"]["site_secrets_configured"])
        self.assertFalse(report["ready"])
        self.assertTrue(any(f["check"] == "site_secrets_configured" for f in report["failures"]))

    def test_report_warns_when_security_disabled(self) -> None:
        with TemporaryDirectory() as tmp:
            workspace_dir = Path(tmp)
            patches = _patch_runtime_dependencies(workspace_dir)
            with patch.object(readiness_module, "_ensure_database_writable", return_value=None):
                for context in patches:
                    context.start()
                try:
                    report = build_readiness_report(
                        workspace_dir,
                        database_locator="postgresql://stub:stub@stub/stub",
                        site_secrets={},
                        worker_count=1,
                        security_disabled=True,
                    )
                finally:
                    for context in patches:
                        context.stop()

        self.assertTrue(report["checks"]["site_secrets_configured"])
        self.assertFalse(report["checks"]["site_secrets_effective"])
        self.assertFalse(report["production_ready"])
        self.assertTrue(any("disabled" in warning.lower() for warning in report["warnings"]))


if __name__ == "__main__":
    unittest.main()
