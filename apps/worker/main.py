"""Entry point for the worker process.

Run with `python -m apps.worker` to start the dispatcher loop. Run with
`python -m apps.worker --check` to validate config + DB connectivity and
exit 0. The worker process never exposes HTTP — the API is a separate
process; both share Postgres only.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from apps.worker.runtime import (
    WorkerSettings,
    build_default_dispatcher,
    build_default_outbox_subscriber,
)
from settings import (
    DATABASE_URL,
    LOG_LEVEL,
    PERSISTENT_LOG_BACKUP_COUNT,
    PERSISTENT_LOG_DIRECTORY,
    PERSISTENT_LOG_MAX_BYTES,
    PERSISTENT_LOGGING_ENABLED,
    WORKER_COUNT,
    WORKER_JOB_MAX_ATTEMPTS,
    WORKER_JOB_RETRY_BACKOFF_SECONDS,
    WORKER_QUEUE_LEASE_SECONDS,
    WORKER_QUEUE_POLL_INTERVAL_SECONDS,
    WORKER_SHUTDOWN_TIMEOUT_SECONDS,
)
from shared.db import describe_database_binding, get_engine
from shared.observability import configure_logging

logger = logging.getLogger("apps.worker")


def _resolve_workspace_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _build_settings() -> WorkerSettings:
    return WorkerSettings(
        worker_count=WORKER_COUNT,
        poll_interval_seconds=WORKER_QUEUE_POLL_INTERVAL_SECONDS,
        lease_seconds=WORKER_QUEUE_LEASE_SECONDS,
        retry_backoff_seconds=WORKER_JOB_RETRY_BACKOFF_SECONDS,
        job_max_attempts=WORKER_JOB_MAX_ATTEMPTS,
        shutdown_timeout_seconds=WORKER_SHUTDOWN_TIMEOUT_SECONDS,
        base_dir=_resolve_workspace_dir(),
        database_locator=DATABASE_URL,
    )


def _check() -> int:
    """Validate the worker can boot: DB reachable, handlers registered."""
    binding = describe_database_binding(DATABASE_URL)
    logger.info("Worker --check: database_url=%s schema=%s", binding["database_url"], binding["database_schema"])
    engine = get_engine(DATABASE_URL)
    with engine.connect() as connection:
        result = connection.execute(__import__("sqlalchemy").text("SELECT 1")).scalar()
        if result != 1:
            logger.error("Database probe returned %r, expected 1", result)
            return 1

    settings = _build_settings()
    dispatcher = build_default_dispatcher(settings=settings)
    subscriber = build_default_outbox_subscriber(settings=settings)
    logger.info(
        "Worker --check OK: kinds=%s outbox_events=%s worker_count=%d lease=%ds poll=%.2fs",
        ", ".join(dispatcher.registered_kinds),
        ", ".join(subscriber.registered_event_types),
        settings.worker_count,
        settings.lease_seconds,
        settings.poll_interval_seconds,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="4reels worker process")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate DB connectivity and handler registration, then exit.",
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
        process_role="worker",
    )

    if args.check:
        return _check()

    settings = _build_settings()
    dispatcher = build_default_dispatcher(settings=settings)
    subscriber = build_default_outbox_subscriber(settings=settings)
    subscriber.start()
    try:
        dispatcher.run_forever()
    finally:
        subscriber.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
