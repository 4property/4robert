"""Integration tests for the configuration brand router."""

from __future__ import annotations

import pytest

from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.integration.configuration._client import (
    ADMIN_BEARER,
    build_configuration_client,
)
from tests.support.postgres import (
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


def test_brand_get_returns_defaults_when_no_record_exists() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/brand",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["agency_id"] == seeded.agency_id
            assert payload["brand"]["primary_color"] == "#0F172A"
            assert payload["brand"]["secondary_color"] == "#FFFFFF"
            assert payload["brand"]["logo_position"] == "top-right"


def test_brand_put_persists_record_in_typed_table() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/brand",
                json={
                    "primary_color": "#112233",
                    "secondary_color": "#AABBCC",
                    "logo_position": "top-left",
                    "font_family": "Roboto",
                },
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "saved"

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                saved = uow.configuration.brand.get(seeded.agency_id)
            assert saved is not None
            assert saved.primary_color == "#112233"
            assert saved.secondary_color == "#AABBCC"
            assert saved.logo_position == "top-left"
            assert saved.font_family == "Roboto"


def test_brand_put_preserves_unset_fields_via_repository_merge() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/brand",
                json={
                    "primary_color": "#111111",
                    "font_family": "Inter",
                },
                headers=ADMIN_BEARER,
            )
            client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/brand",
                json={"primary_color": "#222222"},
                headers=ADMIN_BEARER,
            )

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                saved = uow.configuration.brand.get(seeded.agency_id)
            assert saved is not None
            assert saved.primary_color == "#222222"
            # Font family was set in the first call and is preserved.
            assert saved.font_family == "Inter"


def test_brand_returns_404_for_unknown_agency() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.get(
                "/v1/admin/agencies/missing/brand", headers=ADMIN_BEARER
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_AGENCY_NOT_FOUND"


@pytest.mark.parametrize(
    "legacy_key,legacy_value",
    [
        ("font", "Roboto"),
        ("tagline", "We sell homes"),
        ("watermark_enabled", True),
        ("outro_enabled", True),
        ("outro_headline", "Thanks!"),
        ("outro_sub", "See more at ckp.ie"),
    ],
)
def test_brand_put_rejects_legacy_keys(legacy_key: str, legacy_value: object) -> None:
    """Brand PUT must reject legacy frontend keys via Pydantic `extra='forbid'`.

    Documents the canonical Brand contract: only `primary_color`,
    `secondary_color`, `logo_position`, `logo_object_key`,
    `intro_logo_object_key`, `font_family` are accepted. Any other
    key returns 422 with a detail mentioning the offending field.
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/brand",
                json={
                    "primary_color": "#0F172A",
                    legacy_key: legacy_value,
                },
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 422, response.text
            assert legacy_key in response.text
