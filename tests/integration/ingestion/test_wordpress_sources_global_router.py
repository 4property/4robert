"""Integration tests for the global WordPress sources admin router."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.admin_auth import AdminAccessPolicy
from apps.api.error_handlers import register_error_handlers
from modules.ingestion.transport.http.wordpress_sources_router import (
    create_wordpress_sources_router,
)
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.support.postgres import (
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)

_ADMIN_BEARER = {"Authorization": "Bearer test-admin-token"}


def _build_client(database_url: str, workspace_dir) -> TestClient:
    app = FastAPI()
    factory = lambda: DatabaseUnitOfWork(database_url, workspace_dir)  # noqa: E731
    app.include_router(
        create_wordpress_sources_router(
            unit_of_work_factory=factory,
            admin_access_policy=AdminAccessPolicy(
                enabled=True,
                base_path="/v1/admin",
                bearer_token="test-admin-token",
                disable_auth_for_testing=False,
            ),
        )
    )
    register_error_handlers(app)
    return TestClient(app)


def test_list_returns_only_wordpress_sources_seeded_by_temp_schema() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(database.url, workspace_dir)

            response = client.get("/v1/admin/wordpress-sources", headers=_ADMIN_BEARER)
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["count"] == 1
            assert payload["items"][0]["site_id"] == "ckp.ie"
            assert payload["items"][0]["agency"]["name"] == "Test Agency"


def test_get_returns_404_for_unknown_site() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(database.url, workspace_dir)

            response = client.get(
                "/v1/admin/wordpress-sources/unknown.example",
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_SOURCE_NOT_FOUND"


def test_get_returns_record_when_present() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(database.url, workspace_dir)

            response = client.get(
                "/v1/admin/wordpress-sources/ckp.ie",
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["source"]["site_id"] == "ckp.ie"
            assert payload["source"]["agency"]["agency_id"] == seeded.agency_id


def test_put_creates_agency_and_source_when_neither_exists() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(database.url, workspace_dir)

            response = client.put(
                "/v1/admin/wordpress-sources/ckp.ie",
                json={
                    "source_name": "CKP",
                    "agency_name": "CKP Estate Agents",
                    "agency_slug": "ckp",
                    "agency_timezone": "Europe/Dublin",
                },
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 201, response.text
            payload = response.json()
            assert payload["status"] == "created"
            assert payload["created_agency"] is True
            assert payload["created_source"] is True
            assert payload["source"]["site_id"] == "ckp.ie"
            assert payload["source"]["site_url"] == "https://ckp.ie"

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.ingestion is not None
                record = uow.ingestion.sources.get_by_kind_external_id(
                    kind="wordpress",
                    external_id="ckp.ie",
                )
            assert record is not None
            assert record.agency_id == payload["source"]["agency"]["agency_id"]


def test_put_updates_existing_source_without_recreating_agency() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(database.url, workspace_dir)

            response = client.put(
                "/v1/admin/wordpress-sources/ckp.ie",
                json={
                    "source_name": "Renamed CKP",
                    "agency_id": seeded.agency_id,
                    "site_url": "https://www.ckp.ie",
                },
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["status"] == "updated"
            assert payload["created_agency"] is False
            assert payload["updated_source"] is True
            assert payload["source"]["name"] == "Renamed CKP"
            assert payload["source"]["site_url"] == "https://www.ckp.ie"


def test_put_rejects_reassignment_to_a_different_agency() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seed_tenant(database.url, site_id="ckp.ie")
            other_agency = seed_tenant(database.url, site_id="other.example")
            client = _build_client(database.url, workspace_dir)

            response = client.put(
                "/v1/admin/wordpress-sources/ckp.ie",
                json={
                    "source_name": "Repointed",
                    "agency_id": other_agency.agency_id,
                },
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 400
            assert (
                response.json()["code"]
                == "ADMIN_AGENCY_REASSIGNMENT_NOT_SUPPORTED"
            )


def test_put_requires_admin_bearer() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(database.url, workspace_dir)
            response = client.put(
                "/v1/admin/wordpress-sources/ckp.ie",
                json={"source_name": "X", "agency_name": "X", "agency_slug": "x"},
            )
            assert response.status_code == 401
