"""Integration tests for the PATCH ``.../reels/{site}/{property}/music`` endpoint (feature 25).

Coverage:

* happy path: PATCH persists ``reels.music_id`` and re-enqueues a
  ``reel_publish`` job carrying ``override_music_track_id`` on the
  ``publish_context_json``;
* cross-agency rejection: a track owned by a different agency surfaces
  **404 ADMIN_MUSIC_TRACK_NOT_FOUND** (we collapse cross-agency into 404
  to avoid leaking existence — matches the convention used by feature
  22);
* unknown ``music_id``: same 404 ``ADMIN_MUSIC_TRACK_NOT_FOUND``;
* 409 ``REEL_NOT_EDITABLE`` when the reel has already cleared the
  review gate (``publish_status='published'``);
* idempotent reset: ``music_id=null`` returns 200 and clears the
  column;
* prereqs-missing: the override is still saved, but
  ``publish_enqueued=False`` is surfaced (mirrors the
  ``regenerate_reel`` contract).

The renderer-side branch (the worker swaps the agency pool for the
overridden track when the job arrives) is exercised by the unit tests
in ``tests/unit/reels/test_ingest_applies_music_override.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import create_engine, text

from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.integration.reels._client import (
    ADMIN_BEARER,
    build_admin_reels_client,
    seed_property_with_reel,
)
from tests.support.postgres import (
    seed_provider_connection,
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


def _seed_reel_defaults(database_url: str, *, agency_id: str) -> None:
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
                    "platforms": ["instagram"],
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )
    finally:
        engine.dispose()


def _seed_property_raw_payload(
    database_url: str,
    *,
    external_source_id: str,
    source_property_id: int,
) -> None:
    """Make sure ``properties.raw_json`` round-trips back the dict the
    enqueue path requires (a non-empty dict). ``seed_property_with_reel``
    already inserts a minimal one but we re-assert it here so a future
    refactor of the helper does not silently break this contract.
    """
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT raw_json FROM properties "
                    "WHERE external_source_id = :site "
                    "AND source_property_id = :pid"
                ),
                {"site": external_source_id, "pid": source_property_id},
            ).first()
            assert row is not None, "seed_property_with_reel must insert a property row"
    finally:
        engine.dispose()


def _seed_music_track(
    database_url: str,
    *,
    agency_id: str,
    display_name: str = "Sample",
    object_key: str | None = None,
) -> str:
    timestamp = datetime.now(timezone.utc)
    music_id = str(uuid4())
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO agency_music_tracks ("
                    "id, agency_id, display_name, object_key, "
                    "duration_seconds, is_default, created_at"
                    ") VALUES (:id, :agency_id, :display_name, "
                    ":object_key, :duration, :is_default, :created_at)"
                ),
                {
                    "id": music_id,
                    "agency_id": agency_id,
                    "display_name": display_name,
                    "object_key": (
                        object_key
                        or f"agencies/{agency_id}/music/{music_id}.mp3"
                    ),
                    "duration": 30,
                    "is_default": False,
                    "created_at": timestamp,
                },
            )
    finally:
        engine.dispose()
    return music_id


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_patch_music_persists_override_and_enqueues_job() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            seed_provider_connection(database.url, agency_id=seeded.agency_id)
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                publish_status="needs-approval",
            )
            _seed_property_raw_payload(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            music_id = _seed_music_track(database.url, agency_id=seeded.agency_id)

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/music",
                headers=ADMIN_BEARER,
                json={"music_id": music_id},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["status"] == "saved"
            assert body["music_id"] == music_id
            assert body["publish_enqueued"] is True
            assert body["event_id"]
            assert body["job_id"]

            # Reel row carries the override.
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                state = uow.reels.states.get(  # type: ignore[union-attr]
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                )
            assert state is not None
            assert state.music_id == music_id

            # The fresh job carries ``override_music_track_id`` on the
            # publish_context_json column.
            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    row = connection.execute(
                        text(
                            "SELECT publish_context_json FROM jobs "
                            "WHERE job_id = :job_id"
                        ),
                        {"job_id": body["job_id"]},
                    ).first()
            finally:
                engine.dispose()
            assert row is not None
            assert row.publish_context_json["override_music_track_id"] == music_id


def test_patch_music_with_null_clears_override() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            seed_provider_connection(database.url, agency_id=seeded.agency_id)
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                publish_status="needs-approval",
            )
            music_id = _seed_music_track(database.url, agency_id=seeded.agency_id)

            # Pre-seed an override so we can verify it gets cleared.
            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE reels SET music_id = :music_id "
                            "WHERE external_source_id = :site "
                            "AND source_property_id = :pid"
                        ),
                        {
                            "music_id": music_id,
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
                f"{seeded.external_source_id}/42/music",
                headers=ADMIN_BEARER,
                json={"music_id": None},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["music_id"] is None

            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    row = connection.execute(
                        text(
                            "SELECT music_id FROM reels "
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
            assert row.music_id is None


def test_patch_music_without_publish_prereqs_returns_publish_enqueued_false() -> None:
    """No GHL connection → override saved, but ``publish_enqueued=False``."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                publish_status="needs-approval",
            )
            music_id = _seed_music_track(database.url, agency_id=seeded.agency_id)

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/music",
                headers=ADMIN_BEARER,
                json={"music_id": music_id},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["music_id"] == music_id
            assert body["publish_enqueued"] is False
            assert body["reason"] == "PUBLISH_PREREQUISITES_MISSING"
            assert body["hint"]

            # Override still persists even though the job was not enqueued.
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                state = uow.reels.states.get(  # type: ignore[union-attr]
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                )
            assert state is not None
            assert state.music_id == music_id


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_patch_music_returns_404_for_unknown_music_id() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
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
                f"{seeded.external_source_id}/42/music",
                headers=ADMIN_BEARER,
                json={"music_id": str(uuid4())},
            )
            assert response.status_code == 404, response.text
            assert response.json()["code"] == "ADMIN_MUSIC_TRACK_NOT_FOUND"


def test_patch_music_returns_404_for_cross_agency_music_id() -> None:
    """Cross-agency 404 (NOT 403) — never leaks the existence."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded_a = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            seeded_b = seed_tenant(
                database.url,
                site_id="other-tenant.example",
                workspace_dir=workspace_dir,
            )
            _seed_reel_defaults(database.url, agency_id=seeded_a.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded_a.agency_id,
                ingestion_source_id=seeded_a.ingestion_source_id,
                external_source_id=seeded_a.external_source_id,
                source_property_id=42,
                publish_status="needs-approval",
            )
            foreign_music_id = _seed_music_track(
                database.url, agency_id=seeded_b.agency_id
            )

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded_a.agency_id}/reels/"
                f"{seeded_a.external_source_id}/42/music",
                headers=ADMIN_BEARER,
                json={"music_id": foreign_music_id},
            )
            assert response.status_code == 404, response.text
            assert response.json()["code"] == "ADMIN_MUSIC_TRACK_NOT_FOUND"


def test_patch_music_returns_404_for_unknown_reel() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/99/music",
                headers=ADMIN_BEARER,
                json={"music_id": None},
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_REEL_NOT_FOUND"


def test_patch_music_returns_404_for_unknown_agency() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                "/v1/admin/agencies/missing/reels/ckp.ie/42/music",
                headers=ADMIN_BEARER,
                json={"music_id": None},
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_AGENCY_NOT_FOUND"


def test_patch_music_returns_409_when_reel_already_published() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
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
            music_id = _seed_music_track(database.url, agency_id=seeded.agency_id)

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/music",
                headers=ADMIN_BEARER,
                json={"music_id": music_id},
            )
            assert response.status_code == 409, response.text
            payload = response.json()
            assert payload["code"] == "REEL_NOT_EDITABLE"
            assert payload["details"]["context"]["publish_status"] == "published"


def test_patch_music_rejects_extra_keys_with_422() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
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
                f"{seeded.external_source_id}/42/music",
                headers=ADMIN_BEARER,
                json={"music_id": None, "extra_field": "nope"},
            )
            assert response.status_code == 422
