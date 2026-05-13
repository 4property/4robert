"""Entry point for the API process.

Run with `python -m apps.api` to start uvicorn. Run with `python -m apps.api --check`
to validate configuration + DB connectivity and exit. The API process never runs the
worker dispatcher; that's the job of `apps/worker/`.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from settings import (
    DATABASE_URL,
    LOG_LEVEL,
    PERSISTENT_LOG_BACKUP_COUNT,
    PERSISTENT_LOG_DIRECTORY,
    PERSISTENT_LOG_MAX_BYTES,
    PERSISTENT_LOGGING_ENABLED,
    WEBHOOK_DISABLE_SECURITY,
    WEBHOOK_FORWARDED_ALLOW_IPS,
    WEBHOOK_HOST,
    WEBHOOK_LIMIT_CONCURRENCY,
    WEBHOOK_PATH,
    WEBHOOK_PORT,
    WEBHOOK_SITE_SECRETS,
    WEBHOOK_TRUST_PROXY_HEADERS,
    WORKER_COUNT,
)
from shared.errors import ApplicationError, extract_error_details
from shared.observability import (
    configure_logging,
    format_console_block,
    format_context_line,
    format_detail_line,
)

logger = logging.getLogger("apps.api")


def _resolve_workspace_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _log_readiness_report(readiness: dict[str, object]) -> None:
    environment = readiness.get("environment")
    if not isinstance(environment, dict):
        environment = {}
    lines = [
        format_detail_line(
            "Runtime ready",
            "Yes" if readiness.get("ready") else "No",
            highlight=True,
        ),
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
        format_detail_line("FFmpeg", environment.get("ffmpeg_binary")),
    ]
    failures = readiness.get("failures")
    if isinstance(failures, list):
        for failure in failures:
            if not isinstance(failure, dict):
                continue
            lines.append(format_detail_line("Failed check", failure.get("check")))
            lines.append(format_detail_line("Failure", failure.get("message")))
            lines.append(format_detail_line("Hint", failure.get("hint")))
    logger.info(format_console_block("API Readiness Report", *lines))


def _check(workspace_dir: Path, *, readiness_json: bool) -> int:
    from apps.api.readiness import build_readiness_report

    readiness = build_readiness_report(
        workspace_dir,
        database_locator=DATABASE_URL,
        site_secrets=WEBHOOK_SITE_SECRETS,
        worker_count=WORKER_COUNT,
        security_disabled=WEBHOOK_DISABLE_SECURITY,
    )
    _log_readiness_report(readiness)
    if readiness_json:
        print(json.dumps(readiness, indent=2))
    if not readiness.get("ready"):
        raise ApplicationError(
            "API readiness check failed.",
            context={
                "workspace_dir": readiness.get("environment", {}).get("workspace_dir"),
            },
            hint="Resolve the failed checks before starting the API process.",
        )
    return 0


def _run(workspace_dir: Path, *, host: str, port: int) -> None:
    try:
        import uvicorn
    except ModuleNotFoundError as exc:
        raise ApplicationError(
            "uvicorn is required to run the API process.",
            hint="pip install uvicorn[standard]",
            cause=exc,
        ) from exc

    from apps.api.app_factory import build_api_app

    app = build_api_app(workspace_dir=workspace_dir, database_locator=DATABASE_URL)
    logger.info(
        format_console_block(
            "Starting API Process",
            format_detail_line("Host", host),
            format_detail_line("Port", port),
            format_detail_line("Webhook path", WEBHOOK_PATH),
            format_detail_line(
                "Worker dispatcher",
                "decoupled (run apps.worker in a separate process)",
            ),
        )
    )
    uvicorn.run(
        app,
        host=host,
        port=port,
        proxy_headers=WEBHOOK_TRUST_PROXY_HEADERS,
        forwarded_allow_ips=WEBHOOK_FORWARDED_ALLOW_IPS,
        limit_concurrency=WEBHOOK_LIMIT_CONCURRENCY,
        log_level=logging.getLevelName(logger.getEffectiveLevel()).lower(),
        access_log=False,
        log_config=None,
        server_header=False,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="4reels API process")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate config + DB connectivity, run readiness report, then exit.",
    )
    parser.add_argument(
        "--readiness-json",
        action="store_true",
        help="Print the readiness report as JSON. Use together with --check.",
    )
    args = parser.parse_args(argv)

    workspace_dir = _resolve_workspace_dir()
    configure_logging(
        LOG_LEVEL,
        workspace_dir=workspace_dir,
        persistent_logging_enabled=PERSISTENT_LOGGING_ENABLED,
        persistent_log_directory=PERSISTENT_LOG_DIRECTORY,
        persistent_log_max_bytes=PERSISTENT_LOG_MAX_BYTES,
        persistent_log_backup_count=PERSISTENT_LOG_BACKUP_COUNT,
        process_role="api",
    )

    host = args.host or WEBHOOK_HOST
    port = args.port or WEBHOOK_PORT

    try:
        if args.check:
            return _check(workspace_dir, readiness_json=args.readiness_json)
        _run(workspace_dir, host=host, port=port)
        return 0
    except ApplicationError as error:
        details = extract_error_details(error)
        logger.error(
            format_console_block(
                "API Startup Failed",
                format_detail_line("Reason", details.get("message") or error, highlight=True),
                format_detail_line("Error type", details.get("type")),
                format_detail_line("Hint", details.get("hint")),
                format_context_line(
                    details.get("context") if isinstance(details.get("context"), dict) else None
                ),
            )
        )
        return 1
    except KeyboardInterrupt:
        logger.info(
            format_console_block(
                "API Stopped",
                "The API process shut down after receiving an interrupt.",
            )
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
