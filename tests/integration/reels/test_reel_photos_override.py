"""Integration tests for the PATCH ``.../reels/{site}/{property}/photos`` endpoint (feature 35).

Coverage:

* happy path: PATCH persists ``reels.photos_override`` and re-enqueues
  a fresh ``reel_publish`` job, and the response carries
  ``render_status='pending'``.
* clear semantics: ``photos=null`` AND ``photos=[]`` both wipe the
  override back to SQL ``NULL``.
* validation errors → **422** for gap, duplicate, out-of-range,
  wrong-type ``selected``, and extra-field at the entry level.
* 409 PHOTOS_OVERRIDE_LOCKED:
    - ``workflow_state='approved'``;
    - ``publish_status='published'``.

The renderer-side branch is exercised by
``tests/integration/rendering/test_render_with_photos_override.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.integration.reels._client import (
    ADMIN_BEARER,
    build_admin_reels_client,
    seed_property_image,
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


def _seed_property_with_n_images(
    database_url: str,
    *,
    agency_id: str,
    ingestion_source_id: str,
    external_source_id: str,
    source_property_id: int,
    photo_count: int,
    publish_status: str = "needs-approval",
    workflow_state: str = "rendered",
) -> None:
    seed_property_with_reel(
        database_url,
        agency_id=agency_id,
        ingestion_source_id=ingestion_source_id,
        external_source_id=external_source_id,
        source_property_id=source_property_id,
        publish_status=publish_status,
        workflow_state=workflow_state,
    )
    for index in range(photo_count):
        seed_property_image(
            database_url,
            external_source_id=external_source_id,
            source_property_id=source_property_id,
            position=index + 1,  # historical 1-indexed
            image_url=f"https://example.com/img-{index}.jpg",
            local_path=f"property_media/photo_{index}.jpg",
        )


def _read_photos_override(
    database_url: str,
    *,
    external_source_id: str,
    source_property_id: int,
):
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT photos_override FROM reels "
                    "WHERE external_source_id = :site "
                    "AND source_property_id = :pid"
                ),
                {
                    "site": external_source_id,
                    "pid": source_property_id,
                },
            ).first()
    finally:
        engine.dispose()
    return row.photos_override if row is not None else None


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_patch_photos_persists_override_and_flips_render_status() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            seed_provider_connection(database.url, agency_id=seeded.agency_id)
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            _seed_property_with_n_images(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                photo_count=3,
            )

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            payload = {
                "photos": [
                    {"position": 0, "selected": True},
                    {"position": 1, "selected": False},
                    {"position": 2, "selected": True},
                ]
            }
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/photos",
                headers=ADMIN_BEARER,
                json=payload,
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["photos_override"] == payload["photos"]
            assert body["render_status"] == "pending"
            assert body["publish_enqueued"] is True
            assert body["event_id"]
            assert body["job_id"]

            persisted = _read_photos_override(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            assert persisted == payload["photos"]

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                state = uow.reels.states.get(  # type: ignore[union-attr]
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                )
            assert state is not None
            assert state.render_status == "pending"
            assert state.photos_override == payload["photos"]


def test_patch_photos_with_null_clears_override() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            _seed_property_with_n_images(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                photo_count=2,
            )

            # Pre-seed an override so the clear has something to wipe.
            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE reels SET photos_override = "
                            "CAST(:override AS jsonb) "
                            "WHERE external_source_id = :site "
                            "AND source_property_id = :pid"
                        ),
                        {
                            "override": (
                                '[{"position":0,"selected":true},'
                                '{"position":1,"selected":true}]'
                            ),
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
                f"{seeded.external_source_id}/42/photos",
                headers=ADMIN_BEARER,
                json={"photos": None},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["photos_override"] is None

            persisted = _read_photos_override(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            assert persisted is None


def test_patch_photos_with_empty_list_clears_override() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            _seed_property_with_n_images(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                photo_count=2,
            )

            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE reels SET photos_override = "
                            "CAST(:override AS jsonb) "
                            "WHERE external_source_id = :site "
                            "AND source_property_id = :pid"
                        ),
                        {
                            "override": (
                                '[{"position":0,"selected":true},'
                                '{"position":1,"selected":true}]'
                            ),
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
                f"{seeded.external_source_id}/42/photos",
                headers=ADMIN_BEARER,
                json={"photos": []},
            )
            assert response.status_code == 200, response.text
            assert response.json()["photos_override"] is None
            persisted = _read_photos_override(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            assert persisted is None


# ---------------------------------------------------------------------------
# Validation errors (422)
# ---------------------------------------------------------------------------


def _run_invalid_payload_returns_422(payload: dict) -> int:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            _seed_property_with_n_images(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                photo_count=2,
            )

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/photos",
                headers=ADMIN_BEARER,
                json=payload,
            )
            return response.status_code


def test_patch_photos_rejects_gap_with_422() -> None:
    assert _run_invalid_payload_returns_422(
        {
            "photos": [
                {"position": 0, "selected": True},
                {"position": 2, "selected": True},
            ]
        }
    ) == 422


def test_patch_photos_rejects_duplicate_position_with_422() -> None:
    assert _run_invalid_payload_returns_422(
        {
            "photos": [
                {"position": 0, "selected": True},
                {"position": 0, "selected": True},
            ]
        }
    ) == 422


def test_patch_photos_rejects_out_of_range_with_422() -> None:
    """``photo_count=2`` but the override references position 99."""
    assert _run_invalid_payload_returns_422(
        {
            "photos": [
                {"position": 0, "selected": True},
                {"position": 99, "selected": True},
            ]
        }
    ) == 422


def test_patch_photos_rejects_non_bool_selected_with_422() -> None:
    assert _run_invalid_payload_returns_422(
        {"photos": [{"position": 0, "selected": "yes"}]}
    ) == 422


def test_patch_photos_rejects_extra_field_in_entry_with_422() -> None:
    assert _run_invalid_payload_returns_422(
        {
            "photos": [
                {"position": 0, "selected": True, "extra": "x"},
                {"position": 1, "selected": True},
            ]
        }
    ) == 422


def test_patch_photos_rejects_extra_field_at_body_level_with_422() -> None:
    assert _run_invalid_payload_returns_422(
        {
            "photos": [
                {"position": 0, "selected": True},
                {"position": 1, "selected": True},
            ],
            "rogue_key": True,
        }
    ) == 422


# ---------------------------------------------------------------------------
# 409 — workflow / publish locked
# ---------------------------------------------------------------------------


def test_patch_photos_returns_409_when_workflow_state_is_approved() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            _seed_property_with_n_images(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                photo_count=2,
                workflow_state="approved",
                publish_status="pending_publish",
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/photos",
                headers=ADMIN_BEARER,
                json={
                    "photos": [
                        {"position": 0, "selected": True},
                        {"position": 1, "selected": True},
                    ]
                },
            )
            assert response.status_code == 409, response.text
            body = response.json()
            assert body["code"] == "PHOTOS_OVERRIDE_LOCKED"
            assert body["details"]["context"]["workflow_state"] == "approved"


def test_patch_photos_returns_409_when_publish_status_is_published() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            _seed_property_with_n_images(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                photo_count=2,
                workflow_state="published",
                publish_status="published",
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/photos",
                headers=ADMIN_BEARER,
                json={"photos": None},
            )
            assert response.status_code == 409, response.text
            assert response.json()["code"] == "PHOTOS_OVERRIDE_LOCKED"


# ---------------------------------------------------------------------------
# 404 paths
# ---------------------------------------------------------------------------


def test_patch_photos_returns_404_for_unknown_reel() -> None:
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
                f"{seeded.external_source_id}/99/photos",
                headers=ADMIN_BEARER,
                json={"photos": None},
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_REEL_NOT_FOUND"


def test_patch_photos_returns_404_for_unknown_agency() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                "/v1/admin/agencies/missing/reels/ckp.ie/42/photos",
                headers=ADMIN_BEARER,
                json={"photos": None},
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_AGENCY_NOT_FOUND"
