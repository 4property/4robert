"""End-to-end coverage for the WordPress webhook router.

Replicates the four legacy webhook scenarios (resolves+enqueue, unknown site,
missing GHL connection, paused dispatcher) against the new ingestion router
plumbing.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.error_handlers import register_error_handlers
from modules.ingestion.transport.http.wordpress_webhook_router import (
    WordPressWebhookSettings,
    create_wordpress_webhook_router,
)
from modules.reels.application.orchestrator import build_property_media_job
from modules.reels.application.use_cases import ingest_property_into_reel as ipir
from modules.reels.application.use_cases.ingest_property_into_reel import (
    IngestPropertyIntoReelUseCase,
)
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.integration.reels._client import seed_automation_rules
from tests.support.postgres import (
    seed_provider_connection,
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


def test_wordpress_webhook_resolves_agency_and_enqueues_job() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "tok-1"},
            )

            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.post(
                "/v1/ingest/wordpress/property",
                json={
                    "id": 1234,
                    "slug": "sample-property",
                    "rest_domain": seeded.site_id,
                },
                headers={"Content-Type": "application/json"},
            )

            assert response.status_code == 202, response.text
            payload = response.json()
            assert payload["status"] == "accepted"
            assert payload["site_id"] == seeded.site_id
            assert payload["property_id"] == 1234

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.delivery is not None
                event = uow.delivery.webhook_events.get_event(payload["event_id"])
                job = uow.delivery.jobs.get_job(payload["job_id"])
            assert event is not None
            assert event.agency_id == seeded.agency_id
            assert event.ingestion_source_id == seeded.ingestion_source_id
            assert event.external_source_id == seeded.external_source_id
            assert job is not None
            assert job.kind == "reel_publish"
            assert job.external_source_id == seeded.external_source_id
            assert job.property_id == 1234
            bundle = json.loads(job.provider_secret_bundle)
            assert bundle == {"access_token": "tok-1", "provider": "gohighlevel"}


def test_wordpress_webhook_rejects_unknown_site() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.post(
                "/v1/ingest/wordpress/property",
                json={"id": 1, "slug": "ghost", "rest_domain": "ghost.example"},
                headers={"Content-Type": "application/json"},
            )

            assert response.status_code == 404
            assert response.json()["code"] == "UNKNOWN_WORDPRESS_SITE"


def test_wordpress_webhook_rejects_when_agency_has_no_ghl_connection() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.post(
                "/v1/ingest/wordpress/property",
                json={"id": 9, "slug": "no-conn", "rest_domain": seeded.site_id},
                headers={"Content-Type": "application/json"},
            )

            assert response.status_code == 404
            assert response.json()["code"] == "GHL_CONNECTION_NOT_FOUND"


def test_wordpress_webhook_still_enqueues_when_dispatcher_paused() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_provider_connection(database.url, agency_id=seeded.agency_id)
            client = _build_client(
                database_url=database.url,
                workspace_dir=workspace_dir,
                accepting_jobs=False,
            )

            response = client.post(
                "/v1/ingest/wordpress/property",
                json={"id": 17, "slug": "paused", "rest_domain": seeded.site_id},
                headers={"Content-Type": "application/json"},
            )

            assert response.status_code == 202
            payload = response.json()
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.delivery is not None
                job = uow.delivery.jobs.get_job(payload["job_id"])
            assert job is not None


def test_wordpress_webhook_supersedes_previous_queued_job_for_same_property() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_provider_connection(database.url, agency_id=seeded.agency_id)
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            first = client.post(
                "/v1/ingest/wordpress/property",
                json={"id": 42, "slug": "first", "rest_domain": seeded.site_id},
                headers={"Content-Type": "application/json"},
            )
            second = client.post(
                "/v1/ingest/wordpress/property",
                json={"id": 42, "slug": "second", "rest_domain": seeded.site_id},
                headers={"Content-Type": "application/json"},
            )

            assert first.status_code == 202
            assert second.status_code == 202
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.delivery is not None
                first_job = uow.delivery.jobs.get_job(first.json()["job_id"])
                second_job = uow.delivery.jobs.get_job(second.json()["job_id"])
            assert first_job is not None and second_job is not None
            assert first_job.status == "superseded"
            assert first_job.superseded_by_job_id == second_job.job_id
            assert second_job.status == "queued"


def test_wordpress_webhook_then_worker_ingest_includes_scheduled_at_for_quiet_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: webhook → persisted job → worker ingest → ``scheduled_at``.

    Feature 15: the auto-publish branch must honour the same Automation
    window the manual approve flow uses (feature 11/14). This test wires
    the full path:

    1. Seed a tenant with ``timezone="Europe/Dublin"`` (default of
       :func:`seed_tenant`) plus an automation rule with
       ``quiet_hours_enabled=True`` and window 09:00–18:00.
    2. POST the webhook → the row in ``jobs`` is enqueued. The webhook
       use case (``IngestWordPressPropertyUseCase``) intentionally does
       **not** compute the slot itself — feature 15's contract is that
       the slot is computed when the worker pulls the job and runs
       :class:`IngestPropertyIntoReelUseCase`.
    3. Replay the worker step by hand: load the persisted job, rebuild
       the ``PropertyMediaJob``, run the ingest use case. Pin the wall
       clock to a moment 23:00 Dublin so quiet hours defers the slot to
       the next 09:00 Dublin (= 08:00 UTC).
    4. Assert the returned :attr:`PropertyContext.publish_context.scheduled_at`
       matches the expected next 09:00 Dublin and is strictly in the
       future relative to the pinned wall clock.
    """

    class _FrozenDateTime:
        """``datetime``-compatible wrapper pinning ``now`` to a UTC instant."""

        def __init__(self, frozen_now_utc: datetime) -> None:
            self._frozen_now = frozen_now_utc

        def now(self, tz: Any = None) -> datetime:
            if tz is None:
                return self._frozen_now.replace(tzinfo=None)
            return self._frozen_now.astimezone(tz)

        def __getattr__(self, name: str) -> Any:
            return getattr(datetime, name)

    # Tuesday 2026-05-12 23:00 Dublin → 22:00 UTC (Dublin is on BST in May).
    frozen_now_utc = datetime(2026, 5, 12, 22, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(ipir, "datetime", _FrozenDateTime(frozen_now_utc))

    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            # ``seed_tenant`` defaults to ``timezone="Europe/Dublin"`` so
            # we exercise the timezone-conversion path without an extra
            # helper. The quiet-hours window is the working day in local
            # time.
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "tok-1"},
            )
            seed_automation_rules(
                database.url,
                agency_id=seeded.agency_id,
                approval_required=False,
                publish_window_start="09:00",
                publish_window_end="18:00",
                publish_days=("mon", "tue", "wed", "thu", "fri"),
                hold_window_seconds=0,
                quiet_hours_enabled=True,
                skip_weekends=False,
            )

            client = _build_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.post(
                "/v1/ingest/wordpress/property",
                json={
                    "id": 4242,
                    "slug": "deferred-listing",
                    "rest_domain": seeded.site_id,
                    "property_status": "for sale",
                    "title": {"rendered": "Deferred Listing"},
                },
                headers={"Content-Type": "application/json"},
            )
            assert response.status_code == 202, response.text
            payload = response.json()
            job_id = payload["job_id"]

            # Load the persisted job row and rebuild the worker DTO. The
            # webhook persists ``publish_context_json`` *without*
            # ``scheduled_at`` — that field is the worker's
            # responsibility per feature 15's design.
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.delivery is not None
                persisted_job = uow.delivery.jobs.get_job(job_id)
            assert persisted_job is not None
            persisted_publish_context = dict(persisted_job.publish_context or {})
            assert "scheduled_at" not in persisted_publish_context or (
                persisted_publish_context.get("scheduled_at") is None
            )

            property_media_job = build_property_media_job(persisted_job)
            assert property_media_job.publish_context is not None
            assert property_media_job.publish_context.scheduled_at is None

            # Run the worker step the orchestrator would normally run.
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                use_case = IngestPropertyIntoReelUseCase(
                    workspace_dir=workspace_dir,
                    property_url_template="",
                    property_url_tracking_params=None,
                    social_publishing_enabled=True,
                    database_locator=database.url,
                )
                context = use_case.execute(property_media_job, uow=uow)

            assert context.publish_context is not None
            scheduled_at_iso = context.publish_context.scheduled_at
            assert scheduled_at_iso is not None and scheduled_at_iso

            parsed = datetime.fromisoformat(scheduled_at_iso)
            assert parsed.tzinfo is not None
            parsed_dublin = parsed.astimezone(ZoneInfo("Europe/Dublin"))
            assert parsed_dublin.date().isoformat() == "2026-05-13"
            assert parsed_dublin.hour == 9 and parsed_dublin.minute == 0
            assert parsed.astimezone(timezone.utc) > frozen_now_utc


def _build_client(
    *,
    database_url: str,
    workspace_dir: Path,
    accepting_jobs: bool = True,
) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(
        create_wordpress_webhook_router(
            unit_of_work_factory=lambda: DatabaseUnitOfWork(database_url, workspace_dir),
            settings=WordPressWebhookSettings(
                path="/v1/ingest/wordpress/property",
                security_disabled=True,
                default_platforms=("tiktok",),
            ),
            job_max_attempts=3,
            dispatcher_state=lambda: accepting_jobs,
        )
    )
    return TestClient(app)
