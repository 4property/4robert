"""End-to-end coverage for the scripted render router.

Asserts that `POST /v1/videos/scripted/render` resolves the tenant from the
body's `site_id`, persists the audit row in `webhook_events`, enqueues a
`scripted_render` job with the manifest as `payload_json`, and returns 202.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from apps.api.error_handlers import register_error_handlers
from modules.rendering.transport.http.scripted_router import (
    create_scripted_router,
)
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.support.postgres import (
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)

SCRIPTED_RENDER_PATH = "/v1/videos/scripted/render"
LEGACY_SCRIPTED_RENDER_PATH = SCRIPTED_RENDER_PATH.removeprefix("/v1")


def test_scripted_render_enqueues_job_and_returns_202() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            manifest = {
                "site_id": seeded.site_id,
                "source_property_id": 170800,
                "title": "Sample Property",
                "property_status": "For Sale",
                "slides": [{"image_path": "uploads/slide-01.jpg"}],
            }
            response = client.post(
                SCRIPTED_RENDER_PATH,
                json=manifest,
                headers={"Content-Type": "application/json"},
            )

            assert response.status_code == 202, response.text
            payload = response.json()
            assert payload["status"] == "accepted"
            assert payload["site_id"] == seeded.site_id
            assert payload["source_property_id"] == 170800
            assert payload["job_id"]
            assert payload["event_id"]

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.delivery is not None
                event = uow.delivery.webhook_events.get_event(payload["event_id"])
                job = uow.delivery.jobs.get_job(payload["job_id"])
            assert event is not None
            assert event.agency_id == seeded.agency_id
            assert event.ingestion_source_id == seeded.ingestion_source_id
            assert event.external_source_id == seeded.external_source_id
            assert event.status == "queued"
            assert job is not None
            assert job.kind == "scripted_render"
            assert job.status == "queued"
            assert job.external_source_id == seeded.external_source_id
            assert job.property_id == 170800
            assert job.payload == manifest
            assert job.publish_context == {}
            assert job.provider_secret_bundle == ""

            engine = create_engine(database.url, future=True)
            try:
                with engine.connect() as connection:
                    row = connection.execute(
                        text(
                            "SELECT source_kind FROM webhook_events "
                            "WHERE event_id = :event_id"
                        ),
                        {"event_id": payload["event_id"]},
                    ).first()
            finally:
                engine.dispose()
            assert row is not None
            assert str(row.source_kind) == "scripted_api"


def test_scripted_render_rejects_unknown_site() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.post(
                SCRIPTED_RENDER_PATH,
                json={
                    "site_id": "ghost.example",
                    "source_property_id": 1,
                    "slides": [{"image_path": "x.jpg"}],
                },
                headers={"Content-Type": "application/json"},
            )

            assert response.status_code == 404
            body = response.json()
            assert body["code"] == "UNKNOWN_WORDPRESS_SITE"


def test_scripted_render_rejects_missing_site_id() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.post(
                SCRIPTED_RENDER_PATH,
                json={"source_property_id": 1, "slides": []},
                headers={"Content-Type": "application/json"},
            )

            assert response.status_code == 400
            assert response.json()["code"] == "SITE_ID_REQUIRED"


def test_scripted_render_rejects_missing_source_property_id() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.post(
                SCRIPTED_RENDER_PATH,
                json={"site_id": seeded.site_id, "slides": []},
                headers={"Content-Type": "application/json"},
            )

            assert response.status_code == 400
            assert response.json()["code"] == "SOURCE_PROPERTY_ID_REQUIRED"


def test_scripted_render_rejects_non_json_body() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.post(
                SCRIPTED_RENDER_PATH,
                content=b"not-json{{{",
                headers={"Content-Type": "application/json"},
            )

            assert response.status_code == 400
            assert response.json()["code"] == "INVALID_SCRIPTED_RENDER_PAYLOAD"


def test_scripted_render_rejects_non_json_content_type() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.post(
                SCRIPTED_RENDER_PATH,
                content=b"{}",
                headers={"Content-Type": "text/plain"},
            )

            assert response.status_code == 400
            assert response.json()["code"] == "INVALID_CONTENT_TYPE"


def test_scripted_render_does_not_expose_legacy_unversioned_route() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.post(
                LEGACY_SCRIPTED_RENDER_PATH,
                json={
                    "site_id": seeded.site_id,
                    "source_property_id": 170800,
                    "slides": [{"image_path": "uploads/slide-01.jpg"}],
                },
                headers={"Content-Type": "application/json"},
            )

            assert response.status_code == 404


def _build_client(*, database_url: str, workspace_dir: Path) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(
        create_scripted_router(
            unit_of_work_factory=lambda: DatabaseUnitOfWork(database_url, workspace_dir),
            job_max_attempts=3,
            max_payload_bytes=1_048_576,
        )
    )
    return TestClient(app)
