"""Outbox subscriber loop (feature 27).

Runs alongside the :class:`apps.worker.runtime.JobDispatcher` and
polls ``outbox_events`` rows whose ``status='pending'`` matches one of
the registered event types, dispatching each to its use case. Uses
``FOR UPDATE SKIP LOCKED`` (delegated to
:meth:`modules.delivery.infrastructure.outbox_repository.OutboxRepository.claim_pending_event`)
so multiple worker processes can share the load without double
delivery.

The original ``outbox_repository`` docstring spoke of an "outbox relay"
as something that already polls pending rows. Until this feature there
was no such relay — outbox rows were only consumed indirectly via the
``status='completed'`` write path in
:mod:`modules.reels.application.use_cases.publish_reel`. This module is
the first real subscriber, scoped to notifications.
"""

from __future__ import annotations

import logging
import signal
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from modules.delivery.domain.outbox_event import OutboxEvent
from shared.db import DatabaseUnitOfWork
from shared.errors import extract_error_details
from shared.observability import format_console_block, format_detail_line

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OutboxSubscriberSettings:
    """Tuning knobs for the polling loop."""

    poll_interval_seconds: float = 1.0
    shutdown_timeout_seconds: float = 30.0
    base_dir: Path | None = None
    database_locator: str | Path | None = None


OutboxHandler = Callable[[OutboxEvent, DatabaseUnitOfWork], object]


class OutboxSubscriber:
    """Single-threaded outbox poller dispatching to per-type handlers."""

    def __init__(self, *, settings: OutboxSubscriberSettings) -> None:
        self.settings = settings
        self._handlers: dict[str, OutboxHandler] = {}
        self._thread: threading.Thread | None = None
        self._stop_requested = threading.Event()

    def register_handler(self, event_type: str, handler: OutboxHandler) -> None:
        normalised = str(event_type or "").strip()
        if not normalised:
            raise ValueError("event_type must be non-empty")
        self._handlers[normalised] = handler

    @property
    def registered_event_types(self) -> tuple[str, ...]:
        return tuple(sorted(self._handlers.keys()))

    def process_once(self) -> int:
        """Drain one pending event per registered type, if any.

        Returns the number of events processed in this pass. Designed
        to be called from tests as well as from the polling loop.
        """

        processed = 0
        for event_type, handler in list(self._handlers.items()):
            event = self._claim(event_type)
            if event is None:
                continue
            try:
                with self._unit_of_work() as uow:
                    handler(event, uow)
            except Exception as exc:  # noqa: BLE001 - logged + recorded
                logger.error(
                    "outbox subscriber crashed on %s/%s: %s",
                    event_type,
                    event.event_id,
                    exc,
                    extra=extract_error_details(exc),
                )
                self._mark_failed(event, str(exc))
            processed += 1
        return processed

    def start(self) -> None:
        if self._thread is not None:
            return
        if not self._handlers:
            logger.info(
                "Outbox subscriber: no handlers registered — skipping start()."
            )
            return
        self._stop_requested.clear()
        thread = threading.Thread(
            target=self._loop,
            name="outbox-subscriber",
            daemon=True,
        )
        thread.start()
        self._thread = thread
        logger.info(
            format_console_block(
                "Outbox Subscriber Started",
                format_detail_line(
                    "Event types", ", ".join(self.registered_event_types)
                ),
                format_detail_line(
                    "Poll interval (seconds)",
                    f"{self.settings.poll_interval_seconds:.2f}",
                ),
            )
        )

    def stop(self, timeout: float | None = None) -> None:
        if self._thread is None:
            return
        self._stop_requested.set()
        drain_timeout = (
            self.settings.shutdown_timeout_seconds if timeout is None else max(timeout, 0.0)
        )
        self._thread.join(timeout=drain_timeout)
        self._thread = None
        logger.info("Outbox subscriber stopped.")

    def run_forever(self) -> None:
        self.start()
        signal.signal(signal.SIGINT, self._signal_handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, self._signal_handler)
        try:
            while not self._stop_requested.is_set():
                time.sleep(0.5)
        finally:
            self.stop()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _signal_handler(self, signum: int, frame) -> None:  # noqa: ARG002
        logger.info("Outbox subscriber received signal %s; shutting down.", signum)
        self._stop_requested.set()

    def _loop(self) -> None:
        while not self._stop_requested.is_set():
            try:
                processed = self.process_once()
            except Exception as exc:  # noqa: BLE001 - top-level safety
                logger.error(
                    "Outbox subscriber loop crash: %s",
                    exc,
                    extra=extract_error_details(exc),
                )
                processed = 0
            if not processed:
                self._stop_requested.wait(self.settings.poll_interval_seconds)

    def _claim(self, event_type: str) -> OutboxEvent | None:
        with self._unit_of_work() as uow:
            assert uow.delivery is not None
            event = uow.delivery.outbox.claim_pending_event(event_type=event_type)
            if event is None:
                return None
            # Move it to 'processing' so a concurrent claim does not
            # pick it up while the handler UoW does its work.
            uow.delivery.outbox.mark_status(
                event_id=event.event_id,
                status="processing",
                published_at=datetime.now(timezone.utc).isoformat(),
            )
        return event

    def _mark_failed(self, event: OutboxEvent, message: str) -> None:
        try:
            with self._unit_of_work() as uow:
                assert uow.delivery is not None
                uow.delivery.outbox.mark_status(
                    event_id=event.event_id,
                    status="failed",
                    last_error=message,
                    published_at=datetime.now(timezone.utc).isoformat(),
                )
        except Exception as exc:  # noqa: BLE001 - best-effort failure write
            logger.error(
                "Failed to mark outbox event %s as failed: %s", event.event_id, exc
            )

    def _unit_of_work(self) -> DatabaseUnitOfWork:
        return DatabaseUnitOfWork(
            database_locator=self.settings.database_locator,
            base_dir=self.settings.base_dir,
        )


__all__ = [
    "OutboxHandler",
    "OutboxSubscriber",
    "OutboxSubscriberSettings",
]
