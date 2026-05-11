"""Integration tests for the agency social-accounts admin router."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.admin_auth import AdminAccessPolicy
from apps.api.error_handlers import register_error_handlers
from modules.publishing.application.use_cases.inspect_agency_social_accounts import (
    InspectAgencySocialAccountsUseCase,
)
from modules.publishing.transport.http.social_accounts_router import (
    create_social_accounts_router,
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


def _build_client(
    database_url: str,
    workspace_dir,
    *,
    inspect_use_case: InspectAgencySocialAccountsUseCase | None = None,
) -> TestClient:
    app = FastAPI()
    factory = lambda: DatabaseUnitOfWork(database_url, workspace_dir)  # noqa: E731
    app.include_router(
        create_social_accounts_router(
            unit_of_work_factory=factory,
            admin_access_policy=AdminAccessPolicy(
                enabled=True,
                base_path="/v1/admin",
                bearer_token="test-admin-token",
                disable_auth_for_testing=False,
            ),
            inspect_agency_social_accounts=inspect_use_case,
        )
    )
    register_error_handlers(app)
    return TestClient(app)


def test_returns_disconnected_when_no_connection_exists() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(database.url, workspace_dir)

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/social-accounts",
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["connected"] is False
            assert payload["reason"] == "GHL_CONNECTION_NOT_FOUND"
            assert payload["items"] == []


def test_returns_items_when_upstream_succeeds() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-9",
                secrets={"access_token": "tok-9"},
            )
            client_calls: list[dict[str, Any]] = []

            class _StubClient:
                def __init__(self) -> None:
                    self.closed = False

                def request_json(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
                    client_calls.append({"args": args, "kwargs": kwargs})
                    return {
                        "results": {
                            "accounts": [
                                {
                                    "id": "ac-1",
                                    "name": "Brand IG",
                                    "platform": "instagram",
                                    "type": "page",
                                    "isExpired": False,
                                }
                            ]
                        }
                    }

                def close(self) -> None:
                    self.closed = True

            stub_client = _StubClient()
            inspect = InspectAgencySocialAccountsUseCase(
                client_factory=lambda: stub_client,
            )
            client = _build_client(
                database.url, workspace_dir, inspect_use_case=inspect
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/social-accounts",
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["connected"] is True
            assert payload["count"] == 1
            assert payload["items"][0]["id"] == "ac-1"
            assert payload["location_id"] == "loc-9"
            assert stub_client.closed is True
            assert client_calls and client_calls[0]["args"][0] == "GET"
