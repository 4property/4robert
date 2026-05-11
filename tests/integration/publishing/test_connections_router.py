"""Integration tests for the agency-scoped GoHighLevel connections router."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.admin_auth import AdminAccessPolicy
from apps.api.error_handlers import register_error_handlers
from modules.publishing.application.use_cases.probe_provider_connection import (
    ProbeProviderConnectionUseCase,
)
from modules.publishing.transport.http.connections_router import (
    create_connections_router,
)
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.support.postgres import (
    seed_provider_connection,
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


_ADMIN_BEARER = {"Authorization": "Bearer test-admin-token"}


@dataclass(frozen=True, slots=True)
class _Account:
    id: str
    name: str
    platform: str
    account_type: str
    is_expired: bool


def _build_client(
    *,
    database_url: str,
    workspace_dir: Path,
    probe_provider_connection: ProbeProviderConnectionUseCase | None = None,
) -> TestClient:
    policy = AdminAccessPolicy(
        enabled=True,
        base_path="/v1/admin",
        bearer_token="test-admin-token",
        disable_auth_for_testing=False,
    )
    app = FastAPI()
    app.include_router(
        create_connections_router(
            unit_of_work_factory=lambda: DatabaseUnitOfWork(database_url, workspace_dir),
            admin_access_policy=policy,
            probe_provider_connection=probe_provider_connection,
        )
    )
    register_error_handlers(app)
    return TestClient(app)


def test_attach_persists_connection_with_encrypted_tokens() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/ghl-connection",
                json={
                    "location_id": "loc-1",
                    "user_id": "user-1",
                    "access_token": "secret-token",
                    "refresh_token": "secret-refresh",
                    "expires_at": "2027-01-01T00:00:00Z",
                },
                headers=_ADMIN_BEARER,
            )

            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["status"] == "saved"
            connection = payload["ghl_connection"]
            assert connection["location_id"] == "loc-1"
            assert connection["user_id"] == "user-1"
            assert connection["status"] == "active"
            assert connection["has_access_token"] is True
            assert connection["has_refresh_token"] is True
            assert "secret-token" not in response.text
            assert "secret-refresh" not in response.text

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.publishing is not None
                stored = uow.publishing.connections.get_with_secrets(
                    agency_id=seeded.agency_id,
                    provider="gohighlevel",
                )
            assert stored is not None
            assert stored.external_id == "loc-1"
            assert stored.secrets["access_token"] == "secret-token"
            assert stored.secrets["refresh_token"] == "secret-refresh"


def test_attach_returns_404_for_unknown_agency() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)
            response = client.post(
                "/v1/admin/agencies/agency-missing/ghl-connection",
                json={
                    "location_id": "loc-1",
                    "access_token": "tok-1",
                },
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_AGENCY_NOT_FOUND"


def test_attach_rejects_empty_access_token_with_400() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/ghl-connection",
                json={"location_id": "loc-1", "access_token": ""},
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 422


def test_inspect_returns_redacted_view_when_connection_exists() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                config={"user_id": "user-1", "expires_at": "2026-12-31T00:00:00Z"},
                secrets={
                    "access_token": "stored-token",
                    "refresh_token": "stored-refresh",
                    "expires_at": "2026-12-31T00:00:00Z",
                },
            )
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/ghl-connection",
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            connection = response.json()["ghl_connection"]
            assert connection["location_id"] == "loc-1"
            assert connection["user_id"] == "user-1"
            assert connection["has_secret"] is True
            assert "stored-token" not in response.text
            assert "stored-refresh" not in response.text


def test_inspect_returns_404_when_no_connection_saved() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)
            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/ghl-connection",
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 404
            assert response.json()["code"] == "GHL_CONNECTION_NOT_FOUND"


def test_rotate_replaces_tokens_for_existing_connection() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-old",
                secrets={"access_token": "old-token"},
            )
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/ghl-connection",
                json={
                    "location_id": "loc-new",
                    "user_id": "user-2",
                    "access_token": "new-token",
                },
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "rotated"

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.publishing is not None
                stored = uow.publishing.connections.get_with_secrets(
                    agency_id=seeded.agency_id,
                    provider="gohighlevel",
                )
            assert stored is not None
            assert stored.external_id == "loc-new"
            assert stored.secrets["access_token"] == "new-token"


def test_rotate_returns_404_when_no_connection_yet() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)
            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/ghl-connection",
                json={"location_id": "loc-1", "access_token": "tok-1"},
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 404
            assert response.json()["code"] == "GHL_CONNECTION_NOT_FOUND"


def test_detach_deletes_connection_and_returns_status() -> None:
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

            response = client.delete(
                f"/v1/admin/agencies/{seeded.agency_id}/ghl-connection",
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 200
            assert response.json()["status"] == "deleted"

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.publishing is not None
                stored = uow.publishing.connections.get_by_agency_and_provider(
                    agency_id=seeded.agency_id,
                    provider="gohighlevel",
                )
            assert stored is None


def test_detach_returns_404_when_already_absent() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.delete(
                f"/v1/admin/agencies/{seeded.agency_id}/ghl-connection",
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 404
            assert response.json()["code"] == "GHL_CONNECTION_NOT_FOUND"


def test_probe_uses_saved_token_and_returns_social_accounts() -> None:
    captured: dict[str, str] = {}

    def account_lister(*, location_id: str, access_token: str) -> tuple[_Account, ...]:
        captured["location_id"] = location_id
        captured["access_token"] = access_token
        return (
            _Account(
                id="acct-1",
                name="Instagram",
                platform="instagram",
                account_type="business",
                is_expired=False,
            ),
        )

    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "stored-token"},
            )
            client = _build_client(
                database_url=database.url,
                workspace_dir=workspace_dir,
                probe_provider_connection=ProbeProviderConnectionUseCase(
                    account_lister=account_lister,
                ),
            )
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/ghl-connection/test",
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            assert captured == {"location_id": "loc-1", "access_token": "stored-token"}
            payload = response.json()
            assert payload["account_count"] == 1
            assert payload["accounts"][0]["platform"] == "instagram"
            assert "stored-token" not in response.text


def test_probe_returns_404_when_agency_has_no_connection() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/ghl-connection/test",
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 404
            assert response.json()["code"] == "GHL_CONNECTION_NOT_FOUND"


def test_endpoints_require_admin_bearer_token() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)
            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/ghl-connection",
            )
            assert response.status_code == 401
            assert response.json()["code"] == "ADMIN_AUTH_REQUIRED"
