from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from core.errors import ApplicationError, extract_error_details
from core.logging import configure_logging, format_console_block, format_context_line, format_detail_line


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the WordPress webhook server.")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run startup and deployment checks without starting the server.",
    )
    parser.add_argument(
        "--readiness-json",
        action="store_true",
        help="Print the readiness report as JSON. Useful together with --check.",
    )
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parent
    configure_logging("INFO", persistent_logging_enabled=False)
    logger = logging.getLogger(__name__)

    try:
        from application.bootstrap.runtime import build_default_job_dispatcher
        from settings import (
            DATABASE_URL,
            LOG_LEVEL,
            PERSISTENT_LOG_BACKUP_COUNT,
            PERSISTENT_LOG_DIRECTORY,
            PERSISTENT_LOG_MAX_BYTES,
            PERSISTENT_LOGGING_ENABLED,
            WEBHOOK_DISABLE_SECURITY,
            WEBHOOK_HOST,
            WEBHOOK_PORT,
            WEBHOOK_SITE_SECRETS,
            WEBHOOK_WORKER_COUNT,
        )
        from services.transport.http.operations import build_readiness_report
        from services.transport.http.server import run_wordpress_webhook_server

        configure_logging(
            LOG_LEVEL,
            workspace_dir=base_dir,
            persistent_logging_enabled=PERSISTENT_LOGGING_ENABLED,
            persistent_log_directory=PERSISTENT_LOG_DIRECTORY,
            persistent_log_max_bytes=PERSISTENT_LOG_MAX_BYTES,
            persistent_log_backup_count=PERSISTENT_LOG_BACKUP_COUNT,
        )
        host = args.host or WEBHOOK_HOST
        port = args.port or WEBHOOK_PORT

        if args.check:
            readiness = build_readiness_report(
                base_dir,
                database_locator=DATABASE_URL,
                site_secrets=WEBHOOK_SITE_SECRETS,
                worker_count=WEBHOOK_WORKER_COUNT,
                security_disabled=WEBHOOK_DISABLE_SECURITY,
            )
            _log_readiness_report(logger, readiness)
            if args.readiness_json:
                print(json.dumps(readiness, indent=2))
            if not readiness.get("production_ready", readiness["ready"]):
                raise ApplicationError(
                    "Production readiness check failed.",
                    context={
                        "workspace_dir": readiness.get("environment", {}).get("workspace_dir"),
                    },
                    hint="Resolve the failed readiness checks before enabling the production service.",
                )
            return

        dispatcher = build_default_job_dispatcher(base_dir, database_locator=DATABASE_URL)
        run_wordpress_webhook_server(
            base_dir,
            dispatcher=dispatcher,
            database_locator=DATABASE_URL,
            host=host,
            port=port,
        )
    except ApplicationError as error:
        error_details = extract_error_details(error)
        logger.error(
            format_console_block(
                "Application Startup Failed",
                format_detail_line("Reason", error_details.get("message") or error, highlight=True),
                format_detail_line("Error type", error_details.get("type")),
                format_detail_line("Hint", error_details.get("hint")),
                format_context_line(
                    error_details.get("context")
                    if isinstance(error_details.get("context"), dict)
                    else None
                ),
            )
        )
        raise SystemExit(1) from error
    except ModuleNotFoundError as error:
        missing_module = error.name or "<unknown>"
        wrapped_error = ApplicationError(
            f"A required Python dependency is missing: {missing_module}",
            context={"missing_module": missing_module},
            hint=(
                "Activate the project virtual environment or install the runtime dependencies with "
                "`pip install -r requirements.txt` before starting the service."
            ),
            cause=error,
        )
        error_details = extract_error_details(wrapped_error)
        logger.error(
            format_console_block(
                "Application Startup Failed",
                format_detail_line("Reason", error_details.get("message") or wrapped_error, highlight=True),
                format_detail_line("Error type", error_details.get("type")),
                format_detail_line("Hint", error_details.get("hint")),
                format_context_line(
                    error_details.get("context")
                    if isinstance(error_details.get("context"), dict)
                    else None
                ),
            )
        )
        raise SystemExit(1) from error
    except KeyboardInterrupt:
        logger.info(
            format_console_block(
                "Server Stopped",
                "The webhook server shut down after receiving an interrupt.",
            )
        )


def _log_readiness_report(logger: logging.Logger, readiness: dict[str, object]) -> None:
    environment = readiness.get("environment")
    if not isinstance(environment, dict):
        environment = {}
    lines = [
        format_detail_line("Runtime ready", "Yes" if readiness.get("ready") else "No", highlight=True),
        format_detail_line(
            "Production ready",
            "Yes" if readiness.get("production_ready", readiness.get("ready")) else "No",
            highlight=True,
        ),
        format_detail_line("Workspace", environment.get("workspace_dir")),
        format_detail_line("Database", environment.get("database_url")),
        format_detail_line("Database schema", environment.get("database_schema")),
        format_detail_line("Python", environment.get("python_executable")),
        format_detail_line("Python version", environment.get("python_version")),
        format_detail_line("Platform", environment.get("platform")),
        format_detail_line("FFmpeg", environment.get("ffmpeg_binary")),
        format_detail_line("Subtitle font", environment.get("reel_font_path")),
        format_detail_line("Background audio", environment.get("background_audio_path")),
    ]

    warnings = readiness.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings:
            lines.append(format_detail_line("Warning", warning))

    failures = readiness.get("failures")
    if isinstance(failures, list):
        for failure in failures:
            if not isinstance(failure, dict):
                continue
            lines.append(format_detail_line("Failed check", failure.get("check")))
            lines.append(format_detail_line("Failure", failure.get("message")))
            lines.append(format_detail_line("Hint", failure.get("hint")))

    logger.info(format_console_block("Runtime Readiness Report", *lines))


if __name__ == "__main__":
    main()
