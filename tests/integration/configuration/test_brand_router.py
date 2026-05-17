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
            # Hotfix 2026-05-15: defaults flipped from `#0F172A` /
            # `#FFFFFF` (legacy near-black / white) to neutral greys
            # (`gray-700` / `gray-400`) so an unconfigured agency
            # renders with the same greys as `Reset to default`.
            assert payload["brand"]["primary_color"] == "#374151"
            assert payload["brand"]["secondary_color"] == "#9CA3AF"
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


def test_brand_put_accepts_font_family_from_catalogue() -> None:
    """``font_family='Manrope'`` is in the catalogue and persists verbatim."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/brand",
                json={"font_family": "Manrope"},
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                saved = uow.configuration.brand.get(seeded.agency_id)
            assert saved is not None
            assert saved.font_family == "Manrope"


def test_brand_put_accepts_font_family_null_and_persists_null() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/brand",
                json={"font_family": None},
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                saved = uow.configuration.brand.get(seeded.agency_id)
            assert saved is not None
            assert saved.font_family in (None, "")


def test_brand_put_empty_string_font_family_is_normalised_to_clear() -> None:
    """Hotfix 2026-05-15: ``font_family=""`` (older bundles / select with
    no real choice) is accepted as ``null`` so the override is cleared
    without surfacing a 422 to the user.

    The validator still rejects non-empty values outside the
    catalogue; this is exclusively a tolerance for the empty string.
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/brand",
                json={"font_family": ""},
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                saved = uow.configuration.brand.get(seeded.agency_id)
            assert saved is not None
            # The repo persists an empty string for the cleared column.
            assert saved.font_family == ""


def test_brand_put_null_clears_primary_and_secondary_color_overrides() -> None:
    """Reset to default: explicit ``null`` clears the override, omission preserves.

    Hotfix 2026-05-15: the frontend's "Reset to default" button sends
    ``null`` for the field. The repository must persist an empty string
    (the column is NOT NULL with a server default) so the renderer's
    fallback cascade kicks in (webhook → hardcoded default). A second
    PUT that omits the key entirely must preserve the cleared value.
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            # 1) Set a real colour first.
            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/brand",
                json={"primary_color": "#FF0000", "secondary_color": "#00FF00"},
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                saved = uow.configuration.brand.get(seeded.agency_id)
            assert saved is not None
            assert saved.primary_color == "#FF0000"
            assert saved.secondary_color == "#00FF00"

            # 2) Reset to default: send null on both colours, omit font.
            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/brand",
                json={"primary_color": None, "secondary_color": None},
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                saved = uow.configuration.brand.get(seeded.agency_id)
            assert saved is not None
            assert saved.primary_color == ""
            assert saved.secondary_color == ""

            # 3) A subsequent PUT that omits the colour keys preserves
            #    the cleared empty string (no surprise revert to the
            #    server default ``#0F172A`` / ``#FFFFFF``).
            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/brand",
                json={"font_family": "Inter"},
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                saved = uow.configuration.brand.get(seeded.agency_id)
            assert saved is not None
            assert saved.primary_color == ""
            assert saved.secondary_color == ""
            assert saved.font_family == "Inter"


@pytest.mark.parametrize(
    "rejected_family",
    ["Söhne", "Helvetica", "NotAFont", "inter"],  # case-sensitive
)
def test_brand_put_rejects_font_family_outside_catalogue(
    rejected_family: str,
) -> None:
    """422 with UNKNOWN_FONT_FAMILY for families not in the catalogue.

    The MVP error path is the Pydantic default 422 ``{"detail": [...]}``
    body. The custom ``UNKNOWN_FONT_FAMILY`` code is embedded in the
    field validator's error message so the frontend can still parse it
    out of ``detail[0].msg``. The list of allowed families is appended
    to the same message so the operator has the full catalogue in one
    response.
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/brand",
                json={"font_family": rejected_family},
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 422, response.text
            body = response.json()
            assert "UNKNOWN_FONT_FAMILY" in response.text
            # The allowed-families list is included in the validator
            # message so the frontend can surface the catalogue.
            assert "Allowed families" in response.text
            # Sanity-check the FastAPI default validation envelope.
            assert "detail" in body or "error" in body


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
