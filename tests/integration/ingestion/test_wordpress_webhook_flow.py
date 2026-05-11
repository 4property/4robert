"""End-to-end coverage for the WordPress webhook router.

Replicates the four legacy webhook scenarios (resolves+enqueue, unknown site,
missing GHL connection, paused dispatcher) against the new ingestion router
plumbing.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.error_handlers import register_error_handlers
from modules.ingestion.transport.http.wordpress_webhook_router import (
    WordPressWebhookSettings,
    create_wordpress_webhook_router,
)
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
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
