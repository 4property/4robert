"""Integration tests for the PATCH ``.../reels/{site}/{property}/descriptions`` endpoint (feature 21).

Coverage:

* happy path: PATCH persists the override and the row reflects it;
* 404 ``ADMIN_REEL_NOT_FOUND`` for an unknown reel;
* 409 ``REEL_NOT_EDITABLE`` when the reel has already cleared the
  review gate (``publish_status='approved'``);
* 422 ``PLATFORM_NOT_ENABLED`` when the payload references a platform
  outside ``agency_reel_defaults.platforms``;
* idempotent reset: PATCH with an empty mapping clears the override.

The publish-worker side of the contract (merging the override into the
``PropertyContext.publish_descriptions_by_platform``) is exercised by
the unit tests in ``tests/unit/reels/test_publish_reel_uses_override.py``
because the worker assembles ``PropertyContext`` in pure Python and
does not need a fresh Postgres schema.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.integration.reels._client import (
    ADMIN_BEARER,
    build_admin_reels_client,
    seed_property_with_reel,
)
from tests.support.postgres import (
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


def _seed_reel_defaults(
    database_url: str,
    *,
    agency_id: str,
    platforms: tuple[str, ...] = (
        "tiktok",
        "instagram",
        "linkedin",
        "youtube",
        "facebook",
        "gbp",
        "pinterest",
    ),
) -> None:
    """Insert an ``agency_reel_defaults`` row with the requested platforms."""
    timestamp = datetime.now(timezone.utc)
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO agency_reel_defaults ("
                    "agency_id, platforms, duration_seconds, music_id, "
                    "intro_enabled, caption_template, render_template_id, "
                    "settings, created_at, updated_at"
                    ") VALUES ("
                    ":agency_id, :platforms, 30, '', TRUE, '', 'classic', "
                    "CAST('{}' AS jsonb), :created_at, :updated_at"
                    ")"
                ),
                {
                    "agency_id": agency_id,
                    "platforms": list(platforms),
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Happy path + persistence
# ---------------------------------------------------------------------------


def test_patch_descriptions_persists_override_and_returns_200() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                publish_status="needs-approval",
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/descriptions",
                headers=ADMIN_BEARER,
                json={
                    "descriptions_by_platform": {
                        "instagram": "Custom IG caption.",
                        "linkedin": "Polished LI copy.",
                    }
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["status"] == "updated"
            assert body["descriptions_by_platform"] == {
                "instagram": "Custom IG caption.",
                "linkedin": "Polished LI copy.",
            }

            # Verify persistence via the repository.
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.reels is not None
                state = uow.reels.states.get(
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                )
            assert state is not None
            assert state.descriptions_override == {
                "instagram": "Custom IG caption.",
                "linkedin": "Polished LI copy.",
            }


def test_patch_descriptions_with_empty_mapping_clears_override() -> None:
    """Submitting ``{}`` returns 200 and resets the column to NULL."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                publish_status="needs-approval",
            )
            # Pre-seed an override so we can verify it gets cleared.
            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE reels SET descriptions_override = "
                            "CAST(:override AS jsonb) "
                            "WHERE external_source_id = :site "
                            "AND source_property_id = :pid"
                        ),
                        {
                            "override": json.dumps({"instagram": "Old"}),
                            "site": seeded.external_source_id,
                            "pid": 42,
                        },
                    )
            finally:
                engine.dispose()

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/descriptions",
                headers=ADMIN_BEARER,
                json={"descriptions_by_platform": {}},
            )
            assert response.status_code == 200
            assert response.json()["descriptions_by_platform"] == {}

            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    row = connection.execute(
                        text(
                            "SELECT descriptions_override FROM reels "
                            "WHERE external_source_id = :site "
                            "AND source_property_id = :pid"
                        ),
                        {
                            "site": seeded.external_source_id,
                            "pid": 42,
                        },
                    ).first()
            finally:
                engine.dispose()
            assert row is not None
            assert row.descriptions_override is None


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_patch_descriptions_returns_404_for_unknown_reel() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/99/descriptions",
                headers=ADMIN_BEARER,
                json={"descriptions_by_platform": {"instagram": "Hello"}},
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_REEL_NOT_FOUND"


def test_patch_descriptions_returns_404_for_unknown_agency() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                "/v1/admin/agencies/missing/reels/ckp.ie/42/descriptions",
                headers=ADMIN_BEARER,
                json={"descriptions_by_platform": {"instagram": "Hello"}},
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_AGENCY_NOT_FOUND"


def test_patch_descriptions_returns_409_when_reel_already_approved() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                publish_status="published",
                workflow_state="published",
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/descriptions",
                headers=ADMIN_BEARER,
                json={"descriptions_by_platform": {"instagram": "Too late"}},
            )
            assert response.status_code == 409, response.text
            payload = response.json()
            assert payload["code"] == "REEL_NOT_EDITABLE"
            assert "context" in payload.get("details", {})
            assert payload["details"]["context"]["publish_status"] == "published"


def test_patch_descriptions_returns_422_for_unknown_platform() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_reel_defaults(
                database.url,
                agency_id=seeded.agency_id,
                # Pinterest intentionally omitted from this agency.
                platforms=("instagram", "linkedin"),
            )
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                publish_status="needs-approval",
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/descriptions",
                headers=ADMIN_BEARER,
                json={
                    "descriptions_by_platform": {
                        "instagram": "ok",
                        "telegram": "unknown platform",
                    }
                },
            )
            assert response.status_code == 422, response.text
            payload = response.json()
            assert payload["code"] == "PLATFORM_NOT_ENABLED"
            context = payload["details"]["context"]
            assert "telegram" in context["unknown_platforms"]


def test_patch_descriptions_rejects_extra_keys_with_422() -> None:
    """Pydantic's ``extra='forbid'`` keeps unknown keys out."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                publish_status="needs-approval",
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/descriptions",
                headers=ADMIN_BEARER,
                json={
                    "descriptions_by_platform": {"instagram": "ok"},
                    "extra_payload_field": "should-be-rejected",
                },
            )
            # FastAPI's default validation error path returns 422 with
            # ``detail`` set by Pydantic.
            assert response.status_code == 422
