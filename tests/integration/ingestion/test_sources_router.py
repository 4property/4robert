"""Integration coverage for the ingestion sources admin router."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.admin_auth import AdminAccessPolicy
from apps.api.error_handlers import register_error_handlers
from modules.ingestion.transport.http.sources_router import create_sources_router
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.support.postgres import (
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)

_ADMIN_BEARER = {"Authorization": "Bearer test-admin-token"}


def test_sources_router_requires_bearer_token() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.get("/v1/admin/agencies/some-agency/sources")
            assert response.status_code == 401
            assert response.json()["code"] == "ADMIN_AUTH_REQUIRED"


def test_sources_router_runs_full_crud_lifecycle() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="seed.example")
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            register = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/sources",
                json={
                    "site_id": "ckp.ie",
                    "name": "CKP",
                    "site_url": "https://ckp.ie",
                },
                headers=_ADMIN_BEARER,
            )
            assert register.status_code == 201, register.text
            registered = register.json()["source"]
            ingestion_source_id = registered["ingestion_source_id"]
            assert registered["site_id"] == "ckp.ie"
            assert registered["agency"]["agency_id"] == seeded.agency_id

            listing = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/sources",
                headers=_ADMIN_BEARER,
            )
            assert listing.status_code == 200
            items = listing.json()["items"]
            ids = {item["ingestion_source_id"] for item in items}
            assert ingestion_source_id in ids
            assert seeded.ingestion_source_id in ids

            detail = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/sources/{ingestion_source_id}",
                headers=_ADMIN_BEARER,
            )
            assert detail.status_code == 200
            assert detail.json()["source"]["site_id"] == "ckp.ie"

            updated = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/sources/{ingestion_source_id}",
                json={
                    "name": "CKP Renamed",
                    "status": "paused",
                    "webhook_secret": "new-secret",
                },
                headers=_ADMIN_BEARER,
            )
            assert updated.status_code == 200
            updated_source = updated.json()["source"]
            assert updated_source["name"] == "CKP Renamed"
            assert updated_source["status"] == "paused"
            assert updated_source["has_webhook_secret"] is True

            deleted = client.delete(
                f"/v1/admin/agencies/{seeded.agency_id}/sources/{ingestion_source_id}",
                headers=_ADMIN_BEARER,
            )
            assert deleted.status_code == 200

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.ingestion is not None
                assert uow.ingestion.sources.get_by_id(ingestion_source_id) is None


def test_sources_router_returns_404_when_agency_missing() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.post(
                "/v1/admin/agencies/missing/sources",
                json={"site_id": "x.example", "name": "X"},
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_AGENCY_NOT_FOUND"


def test_sources_router_rejects_duplicate_site_id() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="dup.example")
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/sources",
                json={"site_id": "dup.example", "name": "Dup"},
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 400
            assert response.json()["code"] == "INGESTION_SOURCE_DUPLICATE"


def test_sources_router_inspect_404_when_id_unknown() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/sources/missing",
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_SOURCE_NOT_FOUND"


@pytest.mark.parametrize(
    "legacy_key,legacy_value",
    [
        ("source_name", "CKP Estate Agents"),
        ("source_status", "active"),
    ],
)
def test_sources_post_rejects_legacy_keys(
    legacy_key: str, legacy_value: object
) -> None:
    """POST /sources must reject legacy frontend keys via `extra='forbid'`.

    Documents the canonical Sources contract: `name` (not `source_name`)
    and `status` (not `source_status`). The frontend renames these as
    part of feature 6 (front-side).
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="seed.example")
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/sources",
                json={
                    "site_id": "ckp.ie",
                    "name": "CKP",
                    legacy_key: legacy_value,
                },
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 422, response.text
            assert legacy_key in response.text


def test_sources_put_persists_partial_update() -> None:
    """PUT /sources/{id} accepts a single-field partial body and persists it.

    Documents the contract the front will start using when editing a
    source (the previous implementation reused POST and 4xx-ed on
    duplicate site_id).
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="seed.example")
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            register = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/sources",
                json={
                    "site_id": "ckp.ie",
                    "name": "CKP",
                    "site_url": "https://ckp.ie",
                },
                headers=_ADMIN_BEARER,
            )
            assert register.status_code == 201, register.text
            ingestion_source_id = register.json()["source"]["ingestion_source_id"]

            updated = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/sources/{ingestion_source_id}",
                json={"name": "renamed"},
                headers=_ADMIN_BEARER,
            )
            assert updated.status_code == 200, updated.text
            assert updated.json()["source"]["name"] == "renamed"

            detail = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/sources/{ingestion_source_id}",
                headers=_ADMIN_BEARER,
            )
            assert detail.status_code == 200, detail.text
            assert detail.json()["source"]["name"] == "renamed"
            # site_url survives the partial update.
            assert detail.json()["source"]["site_url"] == "https://ckp.ie"


def _build_client(*, database_url: str, workspace_dir: Path) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(
        create_sources_router(
            unit_of_work_factory=lambda: DatabaseUnitOfWork(database_url, workspace_dir),
            admin_access_policy=AdminAccessPolicy(
                enabled=True,
                base_path="/v1/admin",
                bearer_token="test-admin-token",
                disable_auth_for_testing=False,
            ),
        )
    )
    return TestClient(app)
