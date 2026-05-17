"""Throttle test for the ``review_requested`` dispatcher (feature 27).

Two consecutive triggers within 60 s for the same ``(agency, recipient)``
must result in only ONE email job. The second dispatch sees the recent
``sent`` row in ``email_notifications`` and skips the recipient.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from apps.worker.outbox_subscriber import (
    OutboxSubscriber,
    OutboxSubscriberSettings,
)
from modules.notifications.application.use_cases import (
    DispatchReviewRequestedEmailUseCase,
)
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.support.postgres import (
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


_FRONTEND = "https://admin.example.com"


def _seed_property(
    *,
    database_url: str,
    agency_id: str,
    ingestion_source_id: str,
    site_id: str,
    property_id: int,
) -> None:
    raw = {"id": property_id, "title": {"rendered": "Casa"}, "slug": "casa"}
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO properties ("
                    "agency_id, ingestion_source_id, external_source_id, "
                    "source_property_id, slug, title, raw_json, fetched_at"
                    ") VALUES ("
                    ":agency_id, :ingestion_source_id, :site_id, :pid, "
                    "'casa', 'Casa', CAST(:raw AS jsonb), NOW())"
                ),
                {
                    "agency_id": agency_id,
                    "ingestion_source_id": ingestion_source_id,
                    "site_id": site_id,
                    "pid": property_id,
                    "raw": json.dumps(raw),
                },
            )
    finally:
        engine.dispose()


def _emit_outbox(
    *,
    database_url: str,
    agency_id: str,
    ingestion_source_id: str,
    site_id: str,
    property_id: int,
) -> str:
    event_id = uuid.uuid4().hex
    with DatabaseUnitOfWork(database_url) as uow:
        assert uow.delivery is not None
        uow.delivery.outbox.add_event(
            event_id=event_id,
            aggregate_type="property_media",
            aggregate_id=f"{site_id}:{property_id}",
            event_type="review_requested",
            payload={"site_id": site_id, "property_id": property_id},
            agency_id=agency_id,
            ingestion_source_id=ingestion_source_id,
            external_source_id=site_id,
            source_property_id=property_id,
            status="pending",
            created_at="2026-05-15T12:00:00+00:00",
            available_at="2026-05-15T12:00:00+00:00",
        )
    return event_id


def _build_subscriber(database_url: str, workspace_dir) -> OutboxSubscriber:
    subscriber = OutboxSubscriber(
        settings=OutboxSubscriberSettings(
            base_dir=workspace_dir,
            database_locator=database_url,
        )
    )
    use_case = DispatchReviewRequestedEmailUseCase(frontend_base_url=_FRONTEND)
    subscriber.register_handler(
        "review_requested",
        lambda event, uow: use_case.execute(event, uow=uow),
    )
    return subscriber


def test_second_dispatch_within_60s_skips_already_sent_recipient() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_property(
                database_url=database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                site_id=seeded.external_source_id,
                property_id=99,
            )
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                uow.configuration.defaults.upsert(
                    agency_id=seeded.agency_id,
                    settings={"automation.reviewEmails": ["ops@4pm.ie"]},
                )

            # First dispatch: queues + creates fake "sent" state manually
            # (so we don't have to wait for the real send to land).
            _emit_outbox(
                database_url=database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                site_id=seeded.external_source_id,
                property_id=99,
            )
            subscriber = _build_subscriber(database.url, workspace_dir)
            subscriber.process_once()

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                queued = uow.notifications.emails.list_by_agency(
                    agency_id=seeded.agency_id
                )
            assert len(queued) == 1

            # Mark first row sent NOW so the throttle window catches it.
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                uow.notifications.emails.mark_sent(
                    email_id=queued[0].id,
                    provider_message_id="<msg-1@example.com>",
                    sent_at=datetime.now(timezone.utc),
                )

            # Second dispatch — same recipient, <60s later. Outbox row
            # gets dispatched but no new queued row should appear.
            _emit_outbox(
                database_url=database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                site_id=seeded.external_source_id,
                property_id=99,
            )
            subscriber.process_once()

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                rows = uow.notifications.emails.list_by_agency(
                    agency_id=seeded.agency_id
                )
            statuses = sorted(row.status for row in rows)
            assert statuses == ["sent"]
            # Throttled — only the original row exists.
            assert len(rows) == 1
