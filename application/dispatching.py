from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from application.persistence import UnitOfWork
from application.types import PropertyVideoJob, SocialPublishContext
from core.errors import TransientSocialPublishingError, extract_error_details
from core.logging import format_console_block, format_context_line, format_detail_line
from services.social_delivery.gohighlevel_client import GoHighLevelApiError

logger = logging.getLogger(__name__)


class SqliteJobDispatcher:
    def __init__(
        self,
        *,
        handler: Callable[[PropertyVideoJob], object | None],
        unit_of_work_factory: Callable[[], UnitOfWork],
        worker_count: int,
        poll_interval_seconds: float,
        lease_seconds: int,
        retry_backoff_seconds: float,
        job_max_attempts: int,
    ) -> None:
        self.handler = handler
        self.unit_of_work_factory = unit_of_work_factory
        self.worker_count = max(1, worker_count)
        self.poll_interval_seconds = max(0.05, poll_interval_seconds)
        self.lease_seconds = max(30, lease_seconds)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.job_max_attempts = max(1, job_max_attempts)
        self._workers: list[threading.Thread] = []
        self._accepting_jobs = False
        self._stop_requested = threading.Event()

    def start(self) -> None:
        self._prune_workers()
        if self._workers:
            return

        self._accepting_jobs = True
        self._stop_requested.clear()
        recovered_jobs = self._recover_expired_jobs()
        for index in range(self.worker_count):
            worker = threading.Thread(
                target=self._worker_loop,
                args=(index + 1,),
                name=f"property-video-worker-{index + 1}",
                daemon=True,
            )
            worker.start()
            self._workers.append(worker)
        logger.info(
            format_console_block(
                "Job Dispatcher Started",
                format_detail_line("Worker count", self.worker_count),
                format_detail_line("Queue backend", "SQLite durable queue"),
                format_detail_line("Lease seconds", self.lease_seconds),
                format_detail_line("Poll interval (seconds)", f"{self.poll_interval_seconds:.2f}"),
                format_detail_line("Recovered stale jobs", recovered_jobs),
            )
        )

    def stop(self, timeout: float | None = None) -> None:
        self._prune_workers()
        if not self._workers:
            self._accepting_jobs = False
            return

        self._accepting_jobs = False
        drain_timeout = 5.0 if timeout is None else max(timeout, 0.0)
        logger.info(
            format_console_block(
                "Job Dispatcher Stopping",
                format_detail_line("Active jobs", self._count_active_jobs()),
                format_detail_line("Shutdown timeout (seconds)", f"{drain_timeout:.2f}"),
            )
        )
        self.wait_for_idle(timeout=drain_timeout)

        self._stop_requested.set()
        join_deadline = time.monotonic() + drain_timeout
        for worker in self._workers:
            remaining = max(join_deadline - time.monotonic(), 0.0)
            worker.join(timeout=remaining)
        self._prune_workers()
        logger.info(
            format_console_block(
                "Job Dispatcher Stopped",
                format_detail_line("Active jobs", self._count_active_jobs()),
            )
        )

    def enqueue(self, job: PropertyVideoJob) -> None:
        if not self._accepting_jobs:
            raise RuntimeError("The dispatcher is not accepting new jobs.")

        now = _now_iso()
        publish_context_json = ""
        if job.publish_context is not None:
            publish_context_json = json.dumps(
                job.publish_context.to_dict(include_access_token=True),
                ensure_ascii=False,
                sort_keys=True,
            )

        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.begin_immediate()
            superseded_event_ids = unit_of_work.job_queue_store.supersede_queued_jobs(
                site_id=job.site_id,
                property_id=job.property_id,
                superseded_by_job_id=job.job_id or job.event_id,
                finished_at=now,
            )
            for superseded_event_id in superseded_event_ids:
                unit_of_work.webhook_event_store.update_event_status(
                    superseded_event_id,
                    status="superseded",
                    error_message="Superseded by a newer queued job.",
                )

            existing_event = unit_of_work.webhook_event_store.get_event(job.event_id)
            if existing_event is None:
                unit_of_work.webhook_event_store.create_event(
                    event_id=job.event_id,
                    site_id=job.site_id,
                    property_id=job.property_id,
                    received_at=job.received_at,
                    raw_payload_hash=job.raw_payload_hash,
                    status="queued",
                )
            else:
                unit_of_work.webhook_event_store.update_event_status(
                    job.event_id,
                    status="queued",
                    error_message=None,
                )

            unit_of_work.job_queue_store.enqueue_job(
                request=_build_enqueue_request(
                    job=job,
                    publish_context_json=publish_context_json,
                    available_at=now,
                    created_at=now,
                    max_attempts=self.job_max_attempts,
                )
            )

    def wait_for_idle(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._count_active_jobs() == 0:
                return True
            time.sleep(min(self.poll_interval_seconds, 0.1))
        return self._count_active_jobs() == 0

    def is_accepting_jobs(self) -> bool:
        return self._accepting_jobs

    def _prune_workers(self) -> None:
        self._workers = [worker for worker in self._workers if worker.is_alive()]

    def _worker_loop(self, worker_index: int) -> None:
        worker_id = self._build_worker_id(worker_index)
        while True:
            if self._stop_requested.is_set():
                return

            try:
                claimed_job = self._claim_next_job(worker_id)
            except Exception:
                logger.exception(
                    format_console_block(
                        "Queue Claim Failed",
                        format_detail_line("Worker", worker_id),
                    )
                )
                time.sleep(self.poll_interval_seconds)
                continue

            if claimed_job is None:
                if self._stop_requested.is_set():
                    return
                time.sleep(self.poll_interval_seconds)
                continue

            try:
                self._process_claimed_job(claimed_job, worker_id)
            except Exception:
                logger.exception(
                    format_console_block(
                        "Background Job Failed",
                        format_detail_line("Job ID", claimed_job.job_id),
                        format_detail_line("Event ID", claimed_job.event_id),
                        format_detail_line("Site ID", claimed_job.site_id),
                        format_detail_line("Property ID", claimed_job.property_id),
                    )
                )

    def _claim_next_job(self, worker_id: str):
        now = _now_iso()
        lease_expires_at = _lease_deadline(self.lease_seconds)
        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.begin_immediate()
            unit_of_work.job_queue_store.recover_expired_processing_jobs(now=now)
            claimed_job = unit_of_work.job_queue_store.claim_next_ready_job(
                worker_id=worker_id,
                lease_expires_at=lease_expires_at,
                now=now,
            )
            if claimed_job is None:
                return None
            unit_of_work.webhook_event_store.update_event_status(
                claimed_job.event_id,
                status="processing",
                error_message=None,
            )
            return claimed_job

    def _process_claimed_job(self, claimed_job, worker_id: str) -> None:
        job = _build_property_video_job(claimed_job)
        heartbeat_stop = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(claimed_job.job_id, worker_id, heartbeat_stop),
            name=f"{worker_id}-lease-heartbeat",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            published_media = self.handler(job)
        except Exception as error:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=1.0)
            self._finalize_failure(claimed_job, error)
            return

        heartbeat_stop.set()
        heartbeat_thread.join(timeout=1.0)
        final_status = "noop" if published_media is None else "completed"
        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.begin_immediate()
            unit_of_work.job_queue_store.mark_job_completed(job_id=claimed_job.job_id)
            unit_of_work.webhook_event_store.update_event_status(
                claimed_job.event_id,
                status=final_status,
                error_message=None,
            )

    def _finalize_failure(self, claimed_job, error: Exception) -> None:
        error_details = extract_error_details(error)
        error_message = str(error_details.get("message") or error)
        error_stage = str(error_details.get("stage") or "")
        error_code = str(error_details.get("code") or "")
        error_hint = str(error_details.get("hint") or "")
        external_trace_id = str(error_details.get("external_trace_id") or "")
        error_context = (
            error_details.get("context")
            if isinstance(error_details.get("context"), dict)
            else None
        )
        should_retry = _should_retry_job(
            error=error,
            attempt_count=claimed_job.attempt_count,
            max_attempts=claimed_job.max_attempts,
        )
        if should_retry:
            retry_available_at = _now_with_delay(
                self.retry_backoff_seconds * max(claimed_job.attempt_count, 1)
            )
            with self.unit_of_work_factory() as unit_of_work:
                unit_of_work.begin_immediate()
                unit_of_work.job_queue_store.schedule_retry(
                    job_id=claimed_job.job_id,
                    error_message=error_message,
                    available_at=retry_available_at,
                )
                unit_of_work.webhook_event_store.update_event_status(
                    claimed_job.event_id,
                    status="queued",
                    error_message=error_message,
                )
            logger.warning(
                format_console_block(
                    "Queue Retry Scheduled",
                    format_detail_line("Job ID", claimed_job.job_id),
                    format_detail_line("Attempt", f"{claimed_job.attempt_count}/{claimed_job.max_attempts}"),
                    format_detail_line("Retry at", retry_available_at),
                    format_detail_line("Error stage", error_stage or "<none>"),
                    format_detail_line("Error code", error_code or "<none>"),
                    format_detail_line("Hint", error_hint or "<none>"),
                    format_detail_line("External trace", external_trace_id or "<none>"),
                    format_detail_line("Reason", error_message),
                    format_context_line(error_context),
                )
            )
            return

        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.begin_immediate()
            unit_of_work.job_queue_store.mark_job_failed(
                job_id=claimed_job.job_id,
                error_message=error_message,
            )
            unit_of_work.webhook_event_store.update_event_status(
                claimed_job.event_id,
                status="failed",
                error_message=error_message,
            )
        logger.exception(
            format_console_block(
                "Background Job Failed",
                format_detail_line("Job ID", claimed_job.job_id),
                format_detail_line("Event ID", claimed_job.event_id),
                format_detail_line("Site ID", claimed_job.site_id),
                format_detail_line("Property ID", claimed_job.property_id),
                format_detail_line("Error stage", error_stage or "<none>"),
                format_detail_line("Error code", error_code or "<none>"),
                format_detail_line("Hint", error_hint or "<none>"),
                format_detail_line("External trace", external_trace_id or "<none>"),
                format_context_line(error_context),
            ),
            exc_info=error,
        )

    def _heartbeat_loop(self, job_id: str, worker_id: str, stop_event: threading.Event) -> None:
        heartbeat_interval = max(1.0, self.lease_seconds / 3)
        while not stop_event.wait(heartbeat_interval):
            try:
                with self.unit_of_work_factory() as unit_of_work:
                    unit_of_work.begin_immediate()
                    renewed = unit_of_work.job_queue_store.renew_job_lease(
                        job_id=job_id,
                        worker_id=worker_id,
                        lease_expires_at=_lease_deadline(self.lease_seconds),
                    )
                    if not renewed:
                        return
            except Exception:
                logger.exception(
                    format_console_block(
                        "Queue Lease Renewal Failed",
                        format_detail_line("Job ID", job_id),
                        format_detail_line("Worker", worker_id),
                    )
                )
                return

    def _recover_expired_jobs(self) -> int:
        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.begin_immediate()
            return unit_of_work.job_queue_store.recover_expired_processing_jobs()

    def _count_active_jobs(self) -> int:
        with self.unit_of_work_factory() as unit_of_work:
            return unit_of_work.job_queue_store.count_active_jobs()

    @staticmethod
    def _build_worker_id(worker_index: int) -> str:
        return f"pid-{os.getpid()}-worker-{worker_index}"


def _build_enqueue_request(
    *,
    job: PropertyVideoJob,
    publish_context_json: str,
    available_at: str,
    created_at: str,
    max_attempts: int,
):
    from repositories.property_job_repository import PropertyJobEnqueueRequest

    return PropertyJobEnqueueRequest(
        job_id=job.job_id or job.event_id,
        event_id=job.event_id,
        site_id=job.site_id,
        property_id=job.property_id,
        received_at=job.received_at,
        raw_payload_hash=job.raw_payload_hash,
        payload_json=json.dumps(job.payload, ensure_ascii=False, sort_keys=True),
        publish_context_json=publish_context_json,
        max_attempts=max_attempts,
        available_at=available_at,
        created_at=created_at,
    )


def _build_property_video_job(claimed_job) -> PropertyVideoJob:
    payload = json.loads(claimed_job.payload_json)
    if not isinstance(payload, dict):
        raise ValueError("Queued job payload must be a JSON object.")

    publish_context = None
    if claimed_job.publish_context_json.strip():
        parsed_context = json.loads(claimed_job.publish_context_json)
        if not isinstance(parsed_context, dict):
            raise ValueError("Queued job publish context must be a JSON object.")
        publish_context = SocialPublishContext.from_dict(parsed_context)

    return PropertyVideoJob(
        event_id=claimed_job.event_id,
        site_id=claimed_job.site_id,
        property_id=claimed_job.property_id,
        received_at=claimed_job.received_at,
        raw_payload_hash=claimed_job.raw_payload_hash,
        payload=payload,
        publish_context=publish_context,
        job_id=claimed_job.job_id,
    )


def _should_retry_job(*, error: Exception, attempt_count: int, max_attempts: int) -> bool:
    if attempt_count >= max_attempts:
        return False
    if isinstance(error, TransientSocialPublishingError):
        return True
    if isinstance(error, GoHighLevelApiError):
        return error.status_code >= 500
    return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lease_deadline(lease_seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(1, lease_seconds))).isoformat()


def _now_with_delay(delay_seconds: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=max(0.0, delay_seconds))).isoformat()


__all__ = ["SqliteJobDispatcher"]

