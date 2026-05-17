"""Worker runtime: claim, dispatch, and ack/retry/fail loop."""

from __future__ import annotations

import logging
import signal
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from modules.delivery.domain import Job
from modules.notifications.application.use_cases import (
    DispatchReviewRequestedEmailUseCase,
    SendEmailJobHandler,
)
from modules.reels.application.orchestrator import ReelPipeline
from modules.reels.application.use_cases.render_scripted_video import (
    RenderScriptedVideoUseCase,
)
from settings.notifications import load_notification_settings
from shared.db import DatabaseUnitOfWork
from shared.email.factory import build_email_sender
from shared.errors import extract_error_details
from shared.observability import format_console_block, format_detail_line

logger = logging.getLogger(__name__)


class JobHandler(Protocol):
    """Implemented by per-kind handlers."""

    def __call__(self, job: Job, /) -> object | None: ...


@dataclass(slots=True)
class WorkerSettings:
    worker_count: int = 1
    poll_interval_seconds: float = 0.5
    lease_seconds: int = 900
    retry_backoff_seconds: float = 30.0
    job_max_attempts: int = 3
    shutdown_timeout_seconds: float = 30.0
    base_dir: Path | None = None
    database_locator: str | Path | None = None


class JobDispatcher:
    """Multi-threaded, kind-discriminated dispatcher."""

    def __init__(self, *, settings: WorkerSettings) -> None:
        self.settings = settings
        self._handlers: dict[str, JobHandler] = {}
        self._workers: list[threading.Thread] = []
        self._stop_requested = threading.Event()
        self._accepting_jobs = False

    def register_handler(self, kind: str, handler: JobHandler) -> None:
        normalized_kind = str(kind or "").strip().lower()
        if not normalized_kind:
            raise ValueError("kind must be non-empty")
        self._handlers[normalized_kind] = handler

    @property
    def registered_kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers.keys()))

    def start(self) -> None:
        if self._workers:
            return
        if not self._handlers:
            raise RuntimeError(
                "JobDispatcher.start: no handlers registered. "
                "Call register_handler() for each supported kind first."
            )
        self._accepting_jobs = True
        self._stop_requested.clear()
        recovered = self._recover_expired_jobs()
        for index in range(self.settings.worker_count):
            worker = threading.Thread(
                target=self._worker_loop,
                args=(index + 1,),
                name=f"worker-{index + 1}",
                daemon=True,
            )
            worker.start()
            self._workers.append(worker)
        logger.info(
            format_console_block(
                "Worker Dispatcher Started",
                format_detail_line("Worker count", self.settings.worker_count),
                format_detail_line("Registered kinds", ", ".join(self.registered_kinds)),
                format_detail_line("Lease seconds", self.settings.lease_seconds),
                format_detail_line(
                    "Poll interval (seconds)",
                    f"{self.settings.poll_interval_seconds:.2f}",
                ),
                format_detail_line("Recovered stale jobs", recovered),
            )
        )

    def stop(self, timeout: float | None = None) -> None:
        if not self._workers:
            self._accepting_jobs = False
            return
        self._accepting_jobs = False
        drain_timeout = (
            self.settings.shutdown_timeout_seconds if timeout is None else max(timeout, 0.0)
        )
        active = self._count_active_jobs()
        logger.info(
            format_console_block(
                "Worker Dispatcher Stopping",
                format_detail_line("Active jobs", active),
                format_detail_line("Shutdown timeout (seconds)", f"{drain_timeout:.2f}"),
            )
        )
        self._stop_requested.set()
        join_deadline = time.monotonic() + drain_timeout
        for worker in self._workers:
            remaining = max(join_deadline - time.monotonic(), 0.0)
            worker.join(timeout=remaining)
        self._workers = []
        logger.info(
            format_console_block(
                "Worker Dispatcher Stopped",
                format_detail_line("Active jobs", self._count_active_jobs()),
            )
        )

    def run_forever(self) -> None:
        """Block until SIGTERM/SIGINT."""
        self.start()
        signal.signal(signal.SIGINT, self._signal_handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, self._signal_handler)
        try:
            while not self._stop_requested.is_set():
                time.sleep(0.5)
        finally:
            self.stop()

    def _signal_handler(self, signum: int, frame) -> None:  # noqa: ARG002
        logger.info("Worker received signal %s; initiating graceful shutdown.", signum)
        self._stop_requested.set()

    def _worker_loop(self, worker_index: int) -> None:
        worker_id = f"{uuid.uuid4().hex[:8]}-{worker_index}"
        while not self._stop_requested.is_set() and self._accepting_jobs:
            try:
                processed = self._process_next_job(worker_id)
            except Exception as exc:  # noqa: BLE001 - top-level worker safety
                logger.error(
                    "Worker loop crashed (worker_id=%s): %s - sleeping before retry",
                    worker_id,
                    exc,
                    extra=extract_error_details(exc),
                )
                processed = False
            if not processed:
                self._stop_requested.wait(self.settings.poll_interval_seconds)

    def _process_next_job(self, worker_id: str) -> bool:
        lease_until = (
            datetime.now(timezone.utc) + timedelta(seconds=self.settings.lease_seconds)
        ).isoformat()
        with self._unit_of_work() as uow:
            job = uow.delivery.jobs.claim_next_ready_job(
                worker_id=worker_id,
                lease_expires_at=lease_until,
                kinds=self.registered_kinds,
            )
            if job is not None:
                uow.delivery.webhook_events.update_event_status(
                    job.event_id,
                    status="processing",
                    error_message=None,
                )
        if job is None:
            return False

        handler = self._handlers.get(job.kind)
        if handler is None:
            self._mark_failed(job, f"No handler registered for kind '{job.kind}'.")
            return True

        try:
            result = handler(job)
        except Exception as exc:  # noqa: BLE001 - converted into job state below
            self._handle_job_failure(job, exc)
            return True

        final_event_status = "noop" if result is None else "completed"
        with self._unit_of_work() as uow:
            uow.delivery.jobs.mark_job_completed(job_id=job.job_id)
            uow.delivery.webhook_events.update_event_status(
                job.event_id,
                status=final_event_status,
                error_message=None,
            )
        return True

    def _handle_job_failure(self, job: Job, exc: Exception) -> None:
        details = extract_error_details(exc)
        retryable = bool(details.get("retryable")) or _is_retryable_external_error(exc)
        max_attempts = max(1, job.max_attempts)
        if retryable and job.attempt_count < max_attempts:
            backoff = max(0.0, self.settings.retry_backoff_seconds) * job.attempt_count
            available_at = (
                datetime.now(timezone.utc) + timedelta(seconds=backoff)
            ).isoformat()
            with self._unit_of_work() as uow:
                uow.delivery.jobs.schedule_retry(
                    job_id=job.job_id,
                    error_message=str(exc),
                    available_at=available_at,
                )
                uow.delivery.webhook_events.update_event_status(
                    job.event_id,
                    status="queued",
                    error_message=str(exc),
                )
            return

        self._mark_failed(job, str(exc))

    def _mark_failed(self, job: Job, message: str) -> None:
        with self._unit_of_work() as uow:
            uow.delivery.jobs.mark_job_failed(job_id=job.job_id, error_message=message)
            uow.delivery.webhook_events.update_event_status(
                job.event_id,
                status="failed",
                error_message=message,
            )

    def _recover_expired_jobs(self) -> int:
        with self._unit_of_work() as uow:
            return uow.delivery.jobs.recover_expired_processing_jobs()

    def _count_active_jobs(self) -> int:
        with self._unit_of_work() as uow:
            return uow.delivery.jobs.count_active_jobs()

    def _unit_of_work(self) -> DatabaseUnitOfWork:
        return DatabaseUnitOfWork(
            database_locator=self.settings.database_locator,
            base_dir=self.settings.base_dir,
        )


def _is_retryable_external_error(error: Exception) -> bool:
    if error.__class__.__name__ in {
        "TransientSocialPublishingError",
        "TransientSocialPublishingResultError",
    }:
        return True
    status_code = getattr(error, "status_code", None)
    return isinstance(status_code, int) and status_code >= 500


def build_default_dispatcher(*, settings: WorkerSettings) -> JobDispatcher:
    """Build the production dispatcher with canonical Phase 2 bridge handlers."""
    dispatcher = JobDispatcher(settings=settings)
    workspace_dir = settings.base_dir or Path(__file__).resolve().parents[2]
    reel_pipeline = ReelPipeline(
        workspace_dir=workspace_dir,
        database_locator=settings.database_locator,
    )
    scripted_render = RenderScriptedVideoUseCase(
        workspace_dir=workspace_dir,
        database_locator=settings.database_locator,
    )
    dispatcher.register_handler(
        "reel_publish",
        reel_pipeline.handle,
    )
    dispatcher.register_handler(
        "scripted_render",
        scripted_render.execute,
    )

    # Feature 27: email_send handler. Resolves the SMTP/console backend
    # at boot via :func:`shared.email.factory.build_email_sender` so
    # the worker honours ``EMAIL_BACKEND`` without per-job overhead.
    notification_settings = load_notification_settings()
    email_sender = build_email_sender(notification_settings)
    email_handler = SendEmailJobHandler(
        sender=email_sender,
        notification_settings=notification_settings,
        database_locator=settings.database_locator,
    )
    dispatcher.register_handler("email_send", email_handler)
    return dispatcher


def build_default_outbox_subscriber(*, settings: WorkerSettings):
    """Build the production outbox subscriber for the notifications bridge.

    Imported lazily by callers that want to run the subscriber loop
    alongside the job dispatcher (typically ``apps.worker.main``).
    The subscriber binds ``review_requested`` outbox events to the
    feature-27 dispatcher use case.
    """

    # Imported here (vs at module top) so unit tests of the job
    # dispatcher do not pay the cost of touching the subscriber tree.
    from apps.worker.outbox_subscriber import (
        OutboxSubscriber,
        OutboxSubscriberSettings,
    )

    notification_settings = load_notification_settings()
    subscriber = OutboxSubscriber(
        settings=OutboxSubscriberSettings(
            base_dir=settings.base_dir,
            database_locator=settings.database_locator,
        )
    )
    dispatcher_use_case = DispatchReviewRequestedEmailUseCase(
        frontend_base_url=notification_settings.frontend_base_url,
        job_max_attempts=settings.job_max_attempts,
    )

    def _review_requested(event, uow):  # type: ignore[no-untyped-def]
        return dispatcher_use_case.execute(event, uow=uow)

    subscriber.register_handler("review_requested", _review_requested)
    return subscriber


__all__ = [
    "JobDispatcher",
    "JobHandler",
    "WorkerSettings",
    "build_default_dispatcher",
    "build_default_outbox_subscriber",
]
