"""Integration tests for the PATCH ``.../reels/{site}/{property}/subtitles`` endpoint (feature 36).

Coverage:

* happy path: PATCH persists ``reels.subtitles_override`` and re-enqueues
  a fresh ``reel_publish`` job, and the response carries
  ``render_status='pending'``.
* clear semantics: ``cues=null`` AND ``cues=[]`` both wipe the override
  back to SQL ``NULL``.
* validation errors → **422** for:
    - ``in_seconds >= out_seconds`` (single cue),
    - negative ``in_seconds``,
    - cue overlap,
    - duplicate ``index``,
    - non-monotonic ``index``,
    - empty ``text``,
    - over-long ``text`` (201 chars),
    - extra field inside a cue,
    - wrong type for ``text``.
* 409 SUBTITLES_OVERRIDE_LOCKED:
    - ``workflow_state='approved'``;
    - ``publish_status='published'``.
* survives re-ingest: PATCH → trigger re-ingest → override stays set.

The renderer-side branch is exercised by
``tests/integration/rendering/test_render_with_subtitles_override.py``.
"""

from __future__ import annotations

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


def _read_subtitles_override(
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
                    "SELECT subtitles_override FROM reels "
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
    return row.subtitles_override if row is not None else None


_VALID_CUES = [
    {
        "index": 0,
        "text": "First slide caption",
        "in_seconds": 0.0,
        "out_seconds": 3.0,
    },
    {
        "index": 1,
        "text": "Second slide caption",
        "in_seconds": 3.0,
        "out_seconds": 6.0,
    },
]


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_patch_subtitles_persists_override_and_flips_render_status() -> None:
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
            )

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/subtitles",
                headers=ADMIN_BEARER,
                json={"cues": _VALID_CUES},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["subtitles_override"] == _VALID_CUES
            assert body["render_status"] == "pending"
            assert body["publish_enqueued"] is True
            assert body["event_id"]
            assert body["job_id"]

            persisted = _read_subtitles_override(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            assert persisted == _VALID_CUES

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                state = uow.reels.states.get(  # type: ignore[union-attr]
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                )
            assert state is not None
            assert state.render_status == "pending"
            assert state.subtitles_override == _VALID_CUES


def test_patch_subtitles_with_null_clears_override() -> None:
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
            )

            # Pre-seed an override so the clear has something to wipe.
            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE reels SET subtitles_override = "
                            "CAST(:override AS jsonb) "
                            "WHERE external_source_id = :site "
                            "AND source_property_id = :pid"
                        ),
                        {
                            "override": (
                                '[{"index":0,"text":"X","in_seconds":0.0,'
                                '"out_seconds":2.0}]'
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
                f"{seeded.external_source_id}/42/subtitles",
                headers=ADMIN_BEARER,
                json={"cues": None},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["subtitles_override"] is None

            persisted = _read_subtitles_override(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            assert persisted is None


def test_patch_subtitles_with_empty_list_clears_override() -> None:
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
            )

            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE reels SET subtitles_override = "
                            "CAST(:override AS jsonb) "
                            "WHERE external_source_id = :site "
                            "AND source_property_id = :pid"
                        ),
                        {
                            "override": (
                                '[{"index":0,"text":"X","in_seconds":0.0,'
                                '"out_seconds":2.0}]'
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
                f"{seeded.external_source_id}/42/subtitles",
                headers=ADMIN_BEARER,
                json={"cues": []},
            )
            assert response.status_code == 200, response.text
            assert response.json()["subtitles_override"] is None
            persisted = _read_subtitles_override(
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
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/subtitles",
                headers=ADMIN_BEARER,
                json=payload,
            )
            return response.status_code


def test_patch_subtitles_rejects_in_equals_out_with_422() -> None:
    assert _run_invalid_payload_returns_422(
        {
            "cues": [
                {"index": 0, "text": "x", "in_seconds": 5.0, "out_seconds": 5.0},
            ]
        }
    ) == 422


def test_patch_subtitles_rejects_negative_in_with_422() -> None:
    assert _run_invalid_payload_returns_422(
        {
            "cues": [
                {"index": 0, "text": "x", "in_seconds": -1.0, "out_seconds": 1.0},
            ]
        }
    ) == 422


def test_patch_subtitles_rejects_overlap_with_422() -> None:
    assert _run_invalid_payload_returns_422(
        {
            "cues": [
                {"index": 0, "text": "x", "in_seconds": 0.0, "out_seconds": 5.0},
                {"index": 1, "text": "y", "in_seconds": 4.0, "out_seconds": 8.0},
            ]
        }
    ) == 422


def test_patch_subtitles_rejects_duplicate_index_with_422() -> None:
    assert _run_invalid_payload_returns_422(
        {
            "cues": [
                {"index": 0, "text": "x", "in_seconds": 0.0, "out_seconds": 1.0},
                {"index": 0, "text": "y", "in_seconds": 1.0, "out_seconds": 2.0},
            ]
        }
    ) == 422


def test_patch_subtitles_rejects_non_monotonic_index_with_422() -> None:
    assert _run_invalid_payload_returns_422(
        {
            "cues": [
                {"index": 1, "text": "x", "in_seconds": 0.0, "out_seconds": 1.0},
                {"index": 0, "text": "y", "in_seconds": 1.0, "out_seconds": 2.0},
            ]
        }
    ) == 422


def test_patch_subtitles_rejects_empty_text_with_422() -> None:
    assert _run_invalid_payload_returns_422(
        {"cues": [{"index": 0, "text": "", "in_seconds": 0.0, "out_seconds": 1.0}]}
    ) == 422


def test_patch_subtitles_rejects_long_text_with_422() -> None:
    assert _run_invalid_payload_returns_422(
        {
            "cues": [
                {
                    "index": 0,
                    "text": "x" * 201,
                    "in_seconds": 0.0,
                    "out_seconds": 1.0,
                }
            ]
        }
    ) == 422


def test_patch_subtitles_rejects_extra_field_in_cue_with_422() -> None:
    assert _run_invalid_payload_returns_422(
        {
            "cues": [
                {
                    "index": 0,
                    "text": "x",
                    "in_seconds": 0.0,
                    "out_seconds": 1.0,
                    "extra": "y",
                }
            ]
        }
    ) == 422


def test_patch_subtitles_rejects_wrong_text_type_with_422() -> None:
    assert _run_invalid_payload_returns_422(
        {"cues": [{"index": 0, "text": 42, "in_seconds": 0.0, "out_seconds": 1.0}]}
    ) == 422


def test_patch_subtitles_rejects_extra_field_at_body_level_with_422() -> None:
    assert _run_invalid_payload_returns_422(
        {
            "cues": [
                {"index": 0, "text": "x", "in_seconds": 0.0, "out_seconds": 1.0},
            ],
            "rogue_key": True,
        }
    ) == 422


# ---------------------------------------------------------------------------
# 409 — workflow / publish locked
# ---------------------------------------------------------------------------


def test_patch_subtitles_returns_409_when_workflow_state_is_approved() -> None:
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
                workflow_state="approved",
                publish_status="pending_publish",
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/subtitles",
                headers=ADMIN_BEARER,
                json={"cues": _VALID_CUES},
            )
            assert response.status_code == 409, response.text
            body = response.json()
            assert body["code"] == "SUBTITLES_OVERRIDE_LOCKED"
            assert body["details"]["context"]["workflow_state"] == "approved"


def test_patch_subtitles_returns_409_when_publish_status_is_published() -> None:
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
                workflow_state="published",
                publish_status="published",
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/subtitles",
                headers=ADMIN_BEARER,
                json={"cues": None},
            )
            assert response.status_code == 409, response.text
            assert response.json()["code"] == "SUBTITLES_OVERRIDE_LOCKED"


# ---------------------------------------------------------------------------
# 404 paths
# ---------------------------------------------------------------------------


def test_patch_subtitles_returns_404_for_unknown_reel() -> None:
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
                f"{seeded.external_source_id}/99/subtitles",
                headers=ADMIN_BEARER,
                json={"cues": None},
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_REEL_NOT_FOUND"


# ---------------------------------------------------------------------------
# Survives re-ingest (point 5/6 of the 6-point pattern)
# ---------------------------------------------------------------------------


def test_subtitles_override_survives_re_ingest() -> None:
    """A re-save of the ReelState via the repository must preserve the
    persisted ``subtitles_override`` value, even when the rebuilt state
    is constructed from ``_build_ingested_reel_state`` (which historical
    bugs in features 25 / 35 used to clobber).
    """
    from modules.reels.application.use_cases._ingest_property_assets import (
        _build_ingested_reel_state,
    )
    from modules.reels.domain.types import (
        MediaDeliveryPlan,
        PropertyMediaJob,
    )
    from modules.tenancy.domain.context import TenantContext
    from modules.catalog.domain.wordpress_property import Property

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
            )

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.patch(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/subtitles",
                headers=ADMIN_BEARER,
                json={"cues": _VALID_CUES},
            )
            assert response.status_code == 200, response.text

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                state_before = uow.reels.states.get(  # type: ignore[union-attr]
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                )
            assert state_before is not None
            assert state_before.subtitles_override == _VALID_CUES

            # Simulate a re-ingest: rebuild the state via
            # ``_build_ingested_reel_state`` and save it back. The
            # rebuilt state must inherit ``subtitles_override`` from the
            # peek (which is the bug feature 25 had for ``music_id`` and
            # feature 35 closed for ``photos_override``).
            tenant = TenantContext(
                site_id=seeded.external_source_id,
                agency_id=seeded.agency_id,
                wordpress_source_id=seeded.ingestion_source_id,
            )
            property_item = Property.from_api_payload(
                {
                    "id": 42,
                    "slug": "sample",
                    "title": {"rendered": "Sample"},
                }
            )
            delivery_plan = MediaDeliveryPlan(
                listing_lifecycle="for_sale",
                artifact_kind="reel_video",
                render_profile="for_sale_reel",
                social_post_type="reel",
                asset_strategy="curated_selection",
                banner_text="FOR SALE",
            )
            job = PropertyMediaJob(
                event_id="evt-1",
                tenant=tenant,
                property_id=42,
                received_at=datetime.now(timezone.utc).isoformat(),
                raw_payload_hash="hash-1",
                payload={"id": 42},
            )
            rebuilt = _build_ingested_reel_state(
                job=job,
                property_item=property_item,
                state=state_before,
                delivery_plan=delivery_plan,
                content_fingerprint=state_before.content_fingerprint,
                content_snapshot=dict(state_before.content_snapshot),
                publish_target_fingerprint=state_before.publish_target_fingerprint,
                publish_target_snapshot=dict(state_before.publish_target_snapshot),
                requires_asset_preparation=True,
                requires_render=True,
                publish_context=None,
                pending_publish_platforms=(),
                reset_publish_history=False,
                normalized_external_source_id=seeded.external_source_id,
                render_template_id=state_before.render_template_id,
            )
            assert rebuilt.subtitles_override == _VALID_CUES

            # Persist the rebuilt state and reload — the override must
            # still be there.
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                uow.reels.states.save(rebuilt)  # type: ignore[union-attr]
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                state_after = uow.reels.states.get(  # type: ignore[union-attr]
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                )
            assert state_after is not None
            assert state_after.subtitles_override == _VALID_CUES
