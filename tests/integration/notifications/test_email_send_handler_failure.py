"""Failure path for :class:`SendEmailJobHandler` (feature 27).

When the injected :class:`~shared.email.sender.EmailSender` raises an
exception, every ``email_notifications`` row referenced in the payload
must be transitioned to ``status='failed'`` with the error string
persisted. The handler then re-raises so the worker treats the job as
a failed attempt.
"""

from __future__ import annotations

import pytest

from modules.delivery.domain import Job
from modules.notifications.application.use_cases import SendEmailJobHandler
from settings import DATABASE_URL
from settings.notifications import load_notification_settings
from shared.db import DatabaseUnitOfWork
from shared.email.sender import EmailMessage, SentEmail
from tests.support.postgres import (
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


class _ExplodingSender:
    """Email sender stub that raises a deterministic error."""

    def send(self, message: EmailMessage) -> SentEmail:  # pragma: no cover
        raise RuntimeError("SMTP server rejected: 550 5.1.1 user unknown")


def _build_job(payload: dict) -> Job:
    return Job(
        job_id="job-failure",
        event_id="event-failure",
        agency_id="agency-x",
        ingestion_source_id="",
        kind="email_send",
        external_source_id="ckp.ie",
        property_id=137,
        received_at="2026-05-15T12:00:00+00:00",
        raw_payload_hash="",
        status="processing",
        payload=payload,
        publish_context={},
        provider_secret_bundle="",
        attempt_count=1,
        max_attempts=3,
        available_at="2026-05-15T12:00:00+00:00",
        lease_expires_at=None,
        worker_id="worker-test",
        last_error=None,
        created_at="2026-05-15T12:00:00+00:00",
        updated_at="2026-05-15T12:00:00+00:00",
        finished_at=None,
        superseded_by_job_id="",
    )


def test_handler_marks_rows_failed_and_reraises_when_sender_errors() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")

            # Pre-seed two queued rows that the handler will later mark
            # failed.
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                a = uow.notifications.emails.insert_pending(
                    agency_id=seeded.agency_id,
                    event_kind="review_requested",
                    site_id=seeded.external_source_id,
                    source_property_id=137,
                    recipient_email="a@x.com",
                )
                b = uow.notifications.emails.insert_pending(
                    agency_id=seeded.agency_id,
                    event_kind="review_requested",
                    site_id=seeded.external_source_id,
                    source_property_id=137,
                    recipient_email="b@x.com",
                )

            handler = SendEmailJobHandler(
                sender=_ExplodingSender(),
                notification_settings=load_notification_settings(),
                database_locator=database.url,
            )
            job = _build_job(
                {
                    "event_kind": "review_requested",
                    "agency_id": seeded.agency_id,
                    "site_id": seeded.external_source_id,
                    "source_property_id": 137,
                    "email_notification_ids": [a.id, b.id],
                    "recipient_emails": ["a@x.com", "b@x.com"],
                    "context": {
                        "agency_name": "CKP",
                        "property_title": "Casa",
                        "property_address": "Dublin",
                        "reel_url": "https://admin.example.com/reels",
                    },
                }
            )

            with pytest.raises(RuntimeError, match="SMTP server rejected"):
                handler.handle(job)

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                rows = uow.notifications.emails.list_by_agency(
                    agency_id=seeded.agency_id
                )
            assert len(rows) == 2
            assert {row.status for row in rows} == {"failed"}
            assert all(
                row.error_message and "SMTP server rejected" in row.error_message
                for row in rows
            )
