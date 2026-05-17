"""Integration tests for :class:`EmailNotificationRepository`."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork  # noqa: F401  (used inside contexts)
from tests.support.postgres import (
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


def test_insert_pending_is_idempotent_for_repeated_inserts() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                first = uow.notifications.emails.insert_pending(
                    agency_id=seeded.agency_id,
                    event_kind="review_requested",
                    site_id=seeded.external_source_id,
                    source_property_id=42,
                    recipient_email="ops@example.com",
                )
            assert first.status == "queued"
            assert first.provider_message_id is None

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                second = uow.notifications.emails.insert_pending(
                    agency_id=seeded.agency_id,
                    event_kind="review_requested",
                    site_id=seeded.external_source_id,
                    source_property_id=42,
                    recipient_email="ops@example.com",
                )
            assert second.id == first.id

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                rows = uow.notifications.emails.list_by_agency(
                    agency_id=seeded.agency_id
                )
            assert len(rows) == 1


def test_mark_sent_transitions_row_to_sent_status() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                queued = uow.notifications.emails.insert_pending(
                    agency_id=seeded.agency_id,
                    event_kind="review_requested",
                    site_id=seeded.external_source_id,
                    source_property_id=7,
                    recipient_email="boss@example.com",
                )

            sent_at = datetime.now(timezone.utc)
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                updated = uow.notifications.emails.mark_sent(
                    email_id=queued.id,
                    provider_message_id="<msg-1@example.com>",
                    sent_at=sent_at,
                )
            assert updated.status == "sent"
            assert updated.provider_message_id == "<msg-1@example.com>"
            assert updated.error_message is None

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                sent_rows = uow.notifications.emails.list_by_status(status="sent")
                queued_rows = uow.notifications.emails.list_by_status(status="queued")
            assert {row.id for row in sent_rows} == {queued.id}
            assert queued_rows == ()


def test_mark_failed_records_error_message() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                queued = uow.notifications.emails.insert_pending(
                    agency_id=seeded.agency_id,
                    event_kind="review_requested",
                    site_id=seeded.external_source_id,
                    source_property_id=99,
                    recipient_email="fails@example.com",
                )

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                failed = uow.notifications.emails.mark_failed(
                    email_id=queued.id, error_message="SMTP 550 rejected"
                )
            assert failed.status == "failed"
            assert failed.error_message == "SMTP 550 rejected"


def test_find_recent_sent_respects_throttle_window() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                queued = uow.notifications.emails.insert_pending(
                    agency_id=seeded.agency_id,
                    event_kind="review_requested",
                    site_id=seeded.external_source_id,
                    source_property_id=1,
                    recipient_email="recent@example.com",
                )

            recent_sent_at = datetime.now(timezone.utc)
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                uow.notifications.emails.mark_sent(
                    email_id=queued.id,
                    provider_message_id="<recent@example.com>",
                    sent_at=recent_sent_at,
                )

            inside_window = recent_sent_at - timedelta(seconds=30)
            outside_window = recent_sent_at + timedelta(seconds=30)
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                hit = uow.notifications.emails.find_recent_sent(
                    agency_id=seeded.agency_id,
                    recipient_email="recent@example.com",
                    since=inside_window,
                )
                miss = uow.notifications.emails.find_recent_sent(
                    agency_id=seeded.agency_id,
                    recipient_email="recent@example.com",
                    since=outside_window,
                )
            assert hit is not None and hit.id == queued.id
            assert miss is None
