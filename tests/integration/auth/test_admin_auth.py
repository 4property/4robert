"""Integration tests for the admin auth matrix introduced in feature 5.

Covers the super-admin / agency-scoped JWT split documented in
``progress/explore_feature_5_back_auth.md`` §2.4.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.admin_auth import AdminAccessPolicy
from apps.api.agency_token import issue_agency_token
from apps.api.error_handlers import register_error_handlers
from modules.configuration.transport.http.brand_router import create_brand_router
from modules.tenancy.transport.http.admin_agencies_router import (
    create_admin_agencies_router,
)
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.support.postgres import (
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


_AGENCY_TOKEN_SECRET = "test-agency-secret-please-make-it-32-bytes-long-okay"
_SUPER_ADMIN_TOKEN = "test-admin-token"


def _build_client(*, database_url: str, workspace_dir: Path) -> TestClient:
    policy = AdminAccessPolicy(
        enabled=True,
        base_path="/v1/admin",
        bearer_token=_SUPER_ADMIN_TOKEN,
        disable_auth_for_testing=False,
        agency_token_secret=_AGENCY_TOKEN_SECRET,
        agency_token_ttl_seconds=3600,
    )
    factory = lambda: DatabaseUnitOfWork(database_url, workspace_dir)  # noqa: E731
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(
        create_admin_agencies_router(
            unit_of_work_factory=factory, admin_access_policy=policy
        )
    )
    app.include_router(
        create_brand_router(
            unit_of_work_factory=factory, admin_access_policy=policy
        )
    )
    return TestClient(app)


def _agency_token(*, agency_id: str, ttl_seconds: int = 3600) -> str:
    token, _ = issue_agency_token(
        agency_id=agency_id,
        location_id="loc-test",
        user_id="user-test",
        secret=_AGENCY_TOKEN_SECRET,
        ttl_seconds=ttl_seconds,
    )
    return token


def test_no_token_returns_401_admin_auth_required() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.get("/v1/admin/agencies")
            assert response.status_code == 401
            assert response.json()["code"] == "ADMIN_AUTH_REQUIRED"


def test_super_admin_token_can_list_global_agencies() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.get(
                "/v1/admin/agencies",
                headers={"Authorization": f"Bearer {_SUPER_ADMIN_TOKEN}"},
            )
            assert response.status_code == 200
            assert response.json() == {"count": 0, "items": []}


def test_agency_token_can_access_its_own_brand_route() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            tenant = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            token = _agency_token(agency_id=tenant.agency_id)
            response = client.get(
                f"/v1/admin/agencies/{tenant.agency_id}/brand",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200
            assert response.json()["agency_id"] == tenant.agency_id


def test_agency_token_against_other_agency_returns_403_mismatch() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            tenant_a = seed_tenant(database.url, site_id="a.example")
            tenant_b = seed_tenant(database.url, site_id="b.example")
            client = _build_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            token = _agency_token(agency_id=tenant_a.agency_id)
            response = client.get(
                f"/v1/admin/agencies/{tenant_b.agency_id}/brand",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 403
            assert response.json()["code"] == "AGENCY_TOKEN_AGENCY_MISMATCH"


def test_agency_token_against_global_route_returns_403_forbidden_global() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            tenant = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            token = _agency_token(agency_id=tenant.agency_id)
            response = client.get(
                "/v1/admin/agencies",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 403
            assert response.json()["code"] == "AGENCY_TOKEN_FORBIDDEN_GLOBAL_ROUTE"


def test_expired_agency_token_returns_401_invalid_admin_token() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            tenant = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            past = datetime.now(timezone.utc) - timedelta(hours=2)
            token, _ = issue_agency_token(
                agency_id=tenant.agency_id,
                location_id="loc-1",
                user_id="user-1",
                secret=_AGENCY_TOKEN_SECRET,
                ttl_seconds=60,
                now=past,
            )
            response = client.get(
                f"/v1/admin/agencies/{tenant.agency_id}/brand",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 401
            assert response.json()["code"] == "INVALID_ADMIN_TOKEN"


def test_jwt_with_invalid_signature_returns_401_invalid_admin_token() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            tenant = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            token, _ = issue_agency_token(
                agency_id=tenant.agency_id,
                location_id="loc-1",
                user_id="user-1",
                secret="some-other-secret-not-the-server-one",
                ttl_seconds=3600,
            )
            response = client.get(
                f"/v1/admin/agencies/{tenant.agency_id}/brand",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 401
            assert response.json()["code"] == "INVALID_ADMIN_TOKEN"
