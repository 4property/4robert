from __future__ import annotations

from settings.app import APP_SETTINGS

WORKER_COUNT = APP_SETTINGS.worker_count
WORKER_JOB_MAX_ATTEMPTS = APP_SETTINGS.worker_job_max_attempts
WORKER_JOB_RETRY_BACKOFF_SECONDS = APP_SETTINGS.worker_job_retry_backoff_seconds
WORKER_QUEUE_POLL_INTERVAL_SECONDS = APP_SETTINGS.worker_queue_poll_interval_seconds
WORKER_QUEUE_LEASE_SECONDS = APP_SETTINGS.worker_queue_lease_seconds
WORKER_SHUTDOWN_TIMEOUT_SECONDS = APP_SETTINGS.worker_shutdown_timeout_seconds

__all__ = [
    "WORKER_COUNT",
    "WORKER_JOB_MAX_ATTEMPTS",
    "WORKER_JOB_RETRY_BACKOFF_SECONDS",
    "WORKER_QUEUE_LEASE_SECONDS",
    "WORKER_QUEUE_POLL_INTERVAL_SECONDS",
    "WORKER_SHUTDOWN_TIMEOUT_SECONDS",
]
