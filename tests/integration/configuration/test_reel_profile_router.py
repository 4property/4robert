"""Integration tests for the aggregated reel-profile admin router."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.admin_auth import AdminAccessPolicy
from apps.api.error_handlers import register_error_handlers
from modules.configuration.transport.http.reel_profile_router import (
    create_reel_profile_router,
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
        create_reel_profile_router(
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


def test_get_returns_null_for_a_fresh_agency() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url, site_id="ckp.ie", seed_default_music=False
            )
            client = _build_client(database.url, workspace_dir)

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reel-profile",
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 200
            assert response.json() == {"reel_profile": None}


def test_get_returns_404_for_unknown_agency() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(database.url, workspace_dir)
            response = client.get(
                "/v1/admin/agencies/missing/reel-profile", headers=_ADMIN_BEARER
            )
            assert response.status_code == 404


def test_put_aggregated_payload_writes_typed_sections() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(database.url, workspace_dir)

            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/reel-profile",
                json={
                    "name": "Default",
                    "platforms": ["instagram", "tiktok"],
                    "duration_seconds": 45,
                    "music_id": "track-1",
                    "intro_enabled": False,
                    "logo_position": "bottom-right",
                    "brand_primary_color": "#112233",
                    "brand_secondary_color": "#445566",
                    "caption_template": "{{title}}",
                    "approval_required": True,
                    "extra_settings": {"watermark": True},
                },
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["status"] == "saved"
            profile = payload["reel_profile"]
            assert profile["platforms"] == ["instagram", "tiktok"]
            assert profile["duration_seconds"] == 45
            assert profile["approval_required"] is True
            assert profile["brand_primary_color"] == "#112233"
            assert profile["extra_settings"]["watermark"] is True

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                brand = uow.configuration.brand.get(seeded.agency_id)
                defaults = uow.configuration.defaults.get(seeded.agency_id)
                automation = uow.configuration.automation.get(seeded.agency_id)
            assert brand is not None
            assert brand.primary_color == "#112233"
            assert brand.secondary_color == "#445566"
            assert brand.logo_position == "bottom-right"
            assert defaults is not None
            assert tuple(defaults.platforms) == ("instagram", "tiktok")
            assert defaults.duration_seconds == 45
            assert defaults.music_id == "track-1"
            assert defaults.intro_enabled is False
            assert defaults.caption_template == "{{title}}"
            assert dict(defaults.settings) == {"watermark": True}
            assert automation is not None
            assert automation.approval_required is True


def test_put_does_not_touch_brand_when_payload_omits_brand_fields() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = _build_client(database.url, workspace_dir)

            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/reel-profile",
                json={
                    "platforms": ["instagram"],
                    "approval_required": True,
                },
                headers=_ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                brand = uow.configuration.brand.get(seeded.agency_id)
                defaults = uow.configuration.defaults.get(seeded.agency_id)
                automation = uow.configuration.automation.get(seeded.agency_id)
            assert brand is None  # Brand row was not touched.
            assert defaults is not None
            assert tuple(defaults.platforms) == ("instagram",)
            assert automation is not None
            assert automation.approval_required is True
