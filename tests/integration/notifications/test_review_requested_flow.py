"""End-to-end test for the ``review_requested`` notification flow (feature 27).

The flow validates the design contract:

1. The dispatcher reads ``automation.reviewEmails`` from
   ``agency_reel_defaults`` (two recipients).
2. It writes 2 ``queued`` rows in ``email_notifications`` and enqueues
   **one** ``email_send`` job carrying both recipients.
3. The worker handler renders the template, calls the
   :class:`ConsoleEmailSender`, and transitions both rows to ``sent``
   with the same ``provider_message_id``.
4. The console output contains the canonical subject + reel URL.
"""

from __future__ import annotations

import io
import json
import uuid

from sqlalchemy import create_engine, text

from apps.worker.outbox_subscriber import (
    OutboxSubscriber,
    OutboxSubscriberSettings,
)
from modules.delivery.domain import Job
from modules.notifications.application.use_cases import (
    DispatchReviewRequestedEmailUseCase,
    SendEmailJobHandler,
)
from settings import DATABASE_URL
from settings.notifications import load_notification_settings
from shared.db import DatabaseUnitOfWork
from shared.email.backends.console_sender import ConsoleEmailSender
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
    """Insert a minimal ``properties`` row so the dispatcher can extract
    title + address from ``raw_json``."""

    raw = {
        "id": property_id,
        "slug": "casa-azul",
        "title": {"rendered": "Casa Azul"},
        "property_area_label": "Ballsbridge",
        "property_county_label": "Dublin",
    }
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
                    ":slug, :title, CAST(:raw_json AS jsonb), NOW())"
                ),
                {
                    "agency_id": agency_id,
                    "ingestion_source_id": ingestion_source_id,
                    "site_id": site_id,
                    "pid": property_id,
                    "raw_json": json.dumps(raw),
                    "slug": "casa-azul",
                    "title": "Casa Azul",
                },
            )
    finally:
        engine.dispose()


def _emit_review_requested_outbox(
    *,
    database_url: str,
    agency_id: str,
    ingestion_source_id: str,
    site_id: str,
    property_id: int,
) -> str:
    """Add an outbox event matching what ``publish_reel`` would emit."""

    event_id = uuid.uuid4().hex
    payload = {
        "site_id": site_id,
        "property_id": property_id,
        "workflow_state": "awaiting_review",
        "agency_name": "CKP Properties",
    }
    with DatabaseUnitOfWork(database_url) as uow:
        assert uow.delivery is not None
        uow.delivery.outbox.add_event(
            event_id=event_id,
            aggregate_type="property_media",
            aggregate_id=f"{site_id}:{property_id}",
            event_type="review_requested",
            payload=payload,
            agency_id=agency_id,
            ingestion_source_id=ingestion_source_id,
            external_source_id=site_id,
            source_property_id=property_id,
            status="pending",
            created_at="2026-05-15T12:00:00+00:00",
            available_at="2026-05-15T12:00:00+00:00",
        )
    return event_id


def _set_review_emails(
    *,
    database_url: str,
    workspace_dir,
    agency_id: str,
    emails: list[str] | str,
) -> None:
    with DatabaseUnitOfWork(database_url, workspace_dir) as uow:
        assert uow.configuration is not None
        uow.configuration.defaults.upsert(
            agency_id=agency_id,
            settings={"automation.reviewEmails": emails},
        )


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


def _build_job(*, payload: dict, agency_id: str, site_id: str, property_id: int) -> Job:
    return Job(
        job_id="job-test",
        event_id="event-test",
        agency_id=agency_id,
        ingestion_source_id="",
        kind="email_send",
        external_source_id=site_id,
        property_id=property_id,
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


def _claim_email_job(*, database_url: str, workspace_dir) -> Job:
    """Use the production claim flow so the test exercises FOR UPDATE
    SKIP LOCKED + lease semantics."""

    with DatabaseUnitOfWork(database_url, workspace_dir) as uow:
        assert uow.delivery is not None
        job = uow.delivery.jobs.claim_next_ready_job(
            worker_id="test-worker",
            lease_expires_at="2099-01-01T00:00:00+00:00",
            kinds=("email_send",),
        )
    assert job is not None, "expected an email_send job to be queued"
    return job


def test_full_review_requested_pipeline_marks_two_rows_sent() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_property(
                database_url=database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                site_id=seeded.external_source_id,
                property_id=137,
            )
            _set_review_emails(
                database_url=database.url,
                workspace_dir=workspace_dir,
                agency_id=seeded.agency_id,
                emails=["Ops@4pm.ie", "boss@4pm.ie"],
            )
            _emit_review_requested_outbox(
                database_url=database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                site_id=seeded.external_source_id,
                property_id=137,
            )

            # Step 1: outbox subscriber dispatches the event → inserts
            # 2 queued rows + enqueues 1 email_send job.
            subscriber = _build_subscriber(database.url, workspace_dir)
            processed = subscriber.process_once()
            assert processed == 1

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                queued_rows = uow.notifications.emails.list_by_agency(
                    agency_id=seeded.agency_id
                )
            assert len(queued_rows) == 2
            assert {row.status for row in queued_rows} == {"queued"}
            assert {row.recipient_email for row in queued_rows} == {
                "ops@4pm.ie",
                "boss@4pm.ie",
            }

            # Step 2: claim the job and run the handler manually with a
            # ConsoleEmailSender capturing stdout.
            job = _claim_email_job(
                database_url=database.url, workspace_dir=workspace_dir
            )
            assert job.kind == "email_send"
            buffer = io.StringIO()
            sender = ConsoleEmailSender(stream=buffer)
            handler = SendEmailJobHandler(
                sender=sender,
                notification_settings=load_notification_settings(),
                database_locator=database.url,
            )
            result = handler.handle(job)
            assert result is not None
            assert set(result["recipients"]) == {"ops@4pm.ie", "boss@4pm.ie"}

            console_output = buffer.getvalue()
            assert "Subject: Reel ready for review — Casa Azul" in console_output
            assert "CKP Properties" in console_output
            assert "https://admin.example.com/reels?site_id=ckp.ie&property_id=137" in console_output
            assert "Ballsbridge" in console_output  # property_address fallback

            # Step 3: both rows must transition to sent with the SAME
            # provider_message_id (None for console backend, but shared).
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                sent_rows = uow.notifications.emails.list_by_agency(
                    agency_id=seeded.agency_id
                )
            assert len(sent_rows) == 2
            assert {row.status for row in sent_rows} == {"sent"}
            assert {row.provider_message_id for row in sent_rows} == {None}
            assert all(row.sent_at for row in sent_rows)

            # Outbox row must be in 'dispatched' status.
            engine = create_engine(database.url, future=True)
            try:
                with engine.connect() as connection:
                    outbox_status = connection.execute(
                        text(
                            "SELECT status FROM outbox_events "
                            "WHERE event_type = 'review_requested'"
                        )
                    ).scalar()
                assert outbox_status == "dispatched"
            finally:
                engine.dispose()


def test_csv_legacy_payload_is_accepted_and_normalised() -> None:
    """The CSV legacy shape ``"a@x.com, b@y.com"`` round-trips through
    the dispatcher and produces two email rows lowercased."""

    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_property(
                database_url=database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                site_id=seeded.external_source_id,
                property_id=42,
            )
            _set_review_emails(
                database_url=database.url,
                workspace_dir=workspace_dir,
                agency_id=seeded.agency_id,
                emails="OPS@4pm.ie, boss@4pm.ie, ops@4pm.ie",  # dup + casing
            )
            _emit_review_requested_outbox(
                database_url=database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                site_id=seeded.external_source_id,
                property_id=42,
            )

            subscriber = _build_subscriber(database.url, workspace_dir)
            subscriber.process_once()

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                rows = uow.notifications.emails.list_by_agency(
                    agency_id=seeded.agency_id
                )
            recipients = sorted(row.recipient_email for row in rows)
            assert recipients == ["boss@4pm.ie", "ops@4pm.ie"]


def test_invalid_recipient_is_filtered_silently() -> None:
    """One bad email + one good email → only the good one is queued."""

    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_property(
                database_url=database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                site_id=seeded.external_source_id,
                property_id=11,
            )
            _set_review_emails(
                database_url=database.url,
                workspace_dir=workspace_dir,
                agency_id=seeded.agency_id,
                emails=["not-an-email", "valid@x.com"],
            )
            _emit_review_requested_outbox(
                database_url=database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                site_id=seeded.external_source_id,
                property_id=11,
            )

            subscriber = _build_subscriber(database.url, workspace_dir)
            subscriber.process_once()

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                rows = uow.notifications.emails.list_by_agency(
                    agency_id=seeded.agency_id
                )
            assert [row.recipient_email for row in rows] == ["valid@x.com"]


def test_empty_review_emails_results_in_no_op_dispatched() -> None:
    """If reviewEmails is unset, outbox row goes to dispatched with no
    side effects."""

    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_property(
                database_url=database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                site_id=seeded.external_source_id,
                property_id=9,
            )
            # No upsert of defaults → settings absent.
            _emit_review_requested_outbox(
                database_url=database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                site_id=seeded.external_source_id,
                property_id=9,
            )

            subscriber = _build_subscriber(database.url, workspace_dir)
            processed = subscriber.process_once()
            assert processed == 1

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.notifications is not None
                rows = uow.notifications.emails.list_by_agency(
                    agency_id=seeded.agency_id
                )
            assert rows == ()

            engine = create_engine(database.url, future=True)
            try:
                with engine.connect() as connection:
                    outbox_status = connection.execute(
                        text(
                            "SELECT status FROM outbox_events "
                            "WHERE event_type = 'review_requested'"
                        )
                    ).scalar()
                assert outbox_status == "dispatched"
            finally:
                engine.dispose()
