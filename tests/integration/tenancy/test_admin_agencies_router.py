"""Integration tests for the admin agencies router."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.admin_auth import AdminAccessPolicy
from apps.api.error_handlers import register_error_handlers
from modules.tenancy.transport.http.admin_agencies_router import (
    create_admin_agencies_router,
)
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.support.postgres import seed_tenant, temporary_postgres_schema, temporary_workspace

_ADMIN_BEARER = {"Authorization": "Bearer test-admin-token"}


def test_admin_agencies_router_requires_bearer_token() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.get("/v1/admin/agencies")

            assert response.status_code == 401
            assert response.json()["code"] == "ADMIN_AUTH_REQUIRED"


def test_admin_agencies_router_can_register_list_update_and_delete() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            created = client.post(
                "/v1/admin/agencies",
                json={"name": "CKP Estate Agents", "timezone": "Europe/Dublin"},
                headers=_ADMIN_BEARER,
            )

            assert created.status_code == 201
            agency = created.json()["agency"]
            agency_id = agency["agency_id"]
            assert agency["slug"] == "ckp-estate-agents"

            listing = client.get("/v1/admin/agencies", headers=_ADMIN_BEARER)
            assert listing.status_code == 200
            assert listing.json() == {
                "count": 1,
                "items": [
                    {
                        "agency_id": agency_id,
                        "name": "CKP Estate Agents",
                        "slug": "ckp-estate-agents",
                        "timezone": "Europe/Dublin",
                        "status": "active",
                        "created_at": listing.json()["items"][0]["created_at"],
                        "updated_at": listing.json()["items"][0]["updated_at"],
                        "source_count": 0,
                        "sources": [],
                        "ghl_connection": None,
                        "reel_profile": None,
                    }
                ],
            }

            updated = client.patch(
                f"/v1/admin/agencies/{agency_id}",
                json={"name": "CKP Estate Agents Dublin", "status": "PAUSED"},
                headers=_ADMIN_BEARER,
            )

            assert updated.status_code == 200
            assert updated.json()["agency"]["slug"] == "ckp-estate-agents-dublin"
            assert updated.json()["agency"]["status"] == "paused"

            deleted = client.delete(
                f"/v1/admin/agencies/{agency_id}",
                headers=_ADMIN_BEARER,
            )

            assert deleted.status_code == 200
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.tenancy is not None
                assert uow.tenancy.agencies.get_by_id(agency_id) is None


def test_admin_agencies_router_inspect_hydrates_sources_connection_and_reel_profile() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            tenant = seed_tenant(database.url, site_id="ckp.ie")
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.publishing is not None
                assert uow.configuration is not None
                uow.publishing.connections.upsert(
                    agency_id=tenant.agency_id,
                    provider="gohighlevel",
                    external_id="loc-1",
                    config={"user_id": "user-1", "expires_at": "2026-05-01T00:00:00Z"},
                    secrets={
                        "access_token": "access-token",
                        "refresh_token": "refresh-token",
                        "expires_at": "2026-05-01T00:00:00Z",
                    },
                )
                uow.configuration.brand.upsert(
                    agency_id=tenant.agency_id,
                    primary_color="#0F172A",
                    secondary_color="#FFFFFF",
                    logo_position="top-right",
                )
                uow.configuration.defaults.upsert(
                    agency_id=tenant.agency_id,
                    platforms=["instagram", "tiktok"],
                    duration_seconds=45,
                    music_id="track-1",
                    intro_enabled=False,
                    caption_template="Fresh listing",
                    settings={"watermark": True},
                )
                uow.configuration.automation.upsert(
                    agency_id=tenant.agency_id,
                    approval_required=True,
                    publish_window_start="09:00",
                    publish_window_end="18:00",
                    publish_days=["mon", "tue"],
                    trigger_on_status=["for_sale"],
                )

            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)
            response = client.get(
                f"/v1/admin/agencies/{tenant.agency_id}",
                headers=_ADMIN_BEARER,
            )

            assert response.status_code == 200
            payload = response.json()
            assert payload["agency"]["agency_id"] == tenant.agency_id
            assert payload["sources"][0]["site_id"] == "ckp.ie"
            assert payload["sources"][0]["agency"]["agency_id"] == tenant.agency_id
            assert payload["ghl_connection"]["location_id"] == "loc-1"
            assert payload["ghl_connection"]["has_access_token"] is True
            assert payload["ghl_connection"]["has_refresh_token"] is True
            assert payload["reel_profile"]["profile_id"] == tenant.agency_id
            assert payload["reel_profile"]["platforms"] == ["instagram", "tiktok"]
            assert payload["reel_profile"]["duration_seconds"] == 45
            assert payload["reel_profile"]["approval_required"] is True
            assert payload["reel_profile"]["extra_settings"] == {"watermark": True}


def test_admin_agencies_router_returns_validation_error_for_duplicate_slug() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            first = client.post(
                "/v1/admin/agencies",
                json={"name": "First Agency", "slug": "dup-slug"},
                headers=_ADMIN_BEARER,
            )
            second = client.post(
                "/v1/admin/agencies",
                json={"name": "Second Agency", "slug": "dup-slug"},
                headers=_ADMIN_BEARER,
            )

            assert first.status_code == 201
            assert second.status_code == 400
            assert second.json()["code"] == "ADMIN_AGENCY_SLUG_TAKEN"


def test_create_agency_seeds_default_social_templates() -> None:
    """Creating a new agency must pre-populate `agency_social_templates`
    with the canonical defaults (one row per platform) so the agency
    publishes a usable caption from day one without manual configuration.
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            created = client.post(
                "/v1/admin/agencies",
                json={"name": "Defaults Test Agency"},
                headers=_ADMIN_BEARER,
            )
            assert created.status_code == 201
            agency_id = created.json()["agency"]["agency_id"]

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                rows = uow.configuration.social_templates.list_for_agency(agency_id)

            platforms = {row.platform for row in rows}
            assert platforms == {
                "instagram",
                "tiktok",
                "facebook",
                "linkedin",
                "youtube",
                "pinterest",
                "gbp",
            }
            for row in rows:
                assert row.title_template == "{{property_title}}"
                assert "{{property_title}}" in row.description_template
                assert "{{price}}" in row.description_template
                # GBP gets the agent_email variant; the rest get agent_phone.
                if row.platform == "gbp":
                    assert "{{agent_email}}" in row.description_template
                    assert "{{agent_phone}}" not in row.description_template
                else:
                    assert "{{agent_phone}}" in row.description_template


def test_create_agency_seeds_default_music_tracks() -> None:
    """Creating a new agency must pre-populate ``agency_music_tracks``
    with the canonical NCS defaults (Feature 23) plus matching blobs
    under ``workspace/generated_media/_agency_music/<agency>/`` so the
    reel renderer always has something to play.
    """
    from modules.configuration.domain import DEFAULT_NCS_MUSIC_TRACK_SEEDS
    from shared.storage.site_layout import (
        AGENCY_MUSIC_UPLOAD_DIRNAME,
        GENERATED_MEDIA_ROOT_DIRNAME,
    )

    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            created = client.post(
                "/v1/admin/agencies",
                json={"name": "Music Seed Test Agency"},
                headers=_ADMIN_BEARER,
            )
            assert created.status_code == 201
            agency_id = created.json()["agency"]["agency_id"]

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                tracks = uow.configuration.music.list_for_agency(agency_id)

            assert len(tracks) == len(DEFAULT_NCS_MUSIC_TRACK_SEEDS)
            display_names = {track.display_name for track in tracks}
            expected_names = {seed.display_name for seed in DEFAULT_NCS_MUSIC_TRACK_SEEDS}
            assert display_names == expected_names
            for track in tracks:
                assert track.is_default is True
                assert track.object_key.startswith(f"agencies/{agency_id}/music/")

            music_dir = (
                workspace_dir
                / GENERATED_MEDIA_ROOT_DIRNAME
                / AGENCY_MUSIC_UPLOAD_DIRNAME
                / agency_id
            )
            assert music_dir.exists()
            blobs = sorted(p.name for p in music_dir.iterdir())
            expected_blobs = sorted(
                seed.destination_filename for seed in DEFAULT_NCS_MUSIC_TRACK_SEEDS
            )
            assert blobs == expected_blobs
            for blob_name in blobs:
                assert (music_dir / blob_name).stat().st_size > 0


def _build_client(*, database_url: str, workspace_dir: Path) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(
        create_admin_agencies_router(
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
