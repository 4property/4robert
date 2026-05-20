"""Integration tests for ``reels.auto_subtitles_snapshot`` (feature 41).

Feature 36 lets the editor PATCH ``subtitles_override`` to pin the
subtitle cues. Feature 41 records the renderer's autoCaptions output
(Gemini → caption per slide → timing window) in the new
``reels.auto_subtitles_snapshot`` column so the editor has a starting
value the first time the user opens the subtitle panel.

Coverage:

* Snapshot survives a re-ingest (``_build_ingested_reel_state``
  forwards the column — same propagation pattern features 25 / 35 / 36
  required for their own JSONB columns).
* ``GET /v1/admin/agencies/{id}/reels/{site}/{prop}`` returns
  ``publish_subtitles_snapshot`` populated from the column.
* When the column is NULL, the GET response carries
  ``publish_subtitles_snapshot=null``.
* The repository helpers (``update_publish_status`` /
  ``update_workflow_state`` / ``save_local_artifacts`` with the
  sentinel default) preserve the snapshot — the regression test from
  the same family as ``test_reel_subtitles_override``.

The renderer-side coverage (snapshot is refreshed on each autoCaptions
render and preserved when the override is set) lives in
``tests/integration/rendering/test_render_persists_auto_subtitles.py``.
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


def _write_auto_subtitles_snapshot(
    database_url: str,
    *,
    external_source_id: str,
    source_property_id: int,
    snapshot: str,
) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE reels SET auto_subtitles_snapshot = "
                    "CAST(:snapshot AS jsonb) "
                    "WHERE external_source_id = :site "
                    "AND source_property_id = :pid"
                ),
                {
                    "snapshot": snapshot,
                    "site": external_source_id,
                    "pid": source_property_id,
                },
            )
    finally:
        engine.dispose()


def _read_auto_subtitles_snapshot(
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
                    "SELECT auto_subtitles_snapshot FROM reels "
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
    return row.auto_subtitles_snapshot if row is not None else None


_SAMPLE_SNAPSHOT = [
    {
        "index": 0,
        "text": "Welcome to this stunning property",
        "in_seconds": 0.0,
        "out_seconds": 3.0,
    },
    {
        "index": 1,
        "text": "Spacious kitchen and dining area",
        "in_seconds": 3.0,
        "out_seconds": 6.0,
    },
    {
        "index": 2,
        "text": "Beautifully appointed bedrooms",
        "in_seconds": 6.0,
        "out_seconds": 9.0,
    },
]


def _serialized_snapshot() -> str:
    import json

    return json.dumps(_SAMPLE_SNAPSHOT, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Domain / repository round-trip
# ---------------------------------------------------------------------------


def test_reel_state_round_trips_auto_subtitles_snapshot() -> None:
    """``ReelStateRepository.save(...)`` writes and reads back the JSONB."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )

            _write_auto_subtitles_snapshot(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                snapshot=_serialized_snapshot(),
            )

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                state = uow.reels.states.get(  # type: ignore[union-attr]
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                )
            assert state is not None
            assert state.auto_subtitles_snapshot == _SAMPLE_SNAPSHOT

            # Re-saving the state via the repository must keep the
            # snapshot intact (the SAVE INSERT/UPSERT path includes the
            # column).
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                uow.reels.states.save(state)  # type: ignore[union-attr]

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                reloaded = uow.reels.states.get(  # type: ignore[union-attr]
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                )
            assert reloaded is not None
            assert reloaded.auto_subtitles_snapshot == _SAMPLE_SNAPSHOT


# ---------------------------------------------------------------------------
# Survives re-ingest (point 5 of the 6-point pattern)
# ---------------------------------------------------------------------------


def test_auto_subtitles_snapshot_survives_re_ingest() -> None:
    """``_build_ingested_reel_state`` must forward the snapshot.

    The bug feature 25 had for ``music_id`` and feature 35 / 36 / 37
    closed for their own JSONB columns is closed here too: a rebuild
    of the state via ``_build_ingested_reel_state`` (the exact code
    path used by the ingest pipeline) preserves the snapshot.
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
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            _write_auto_subtitles_snapshot(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                snapshot=_serialized_snapshot(),
            )

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                state_before = uow.reels.states.get(  # type: ignore[union-attr]
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                )
            assert state_before is not None
            assert state_before.auto_subtitles_snapshot == _SAMPLE_SNAPSHOT

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
            assert rebuilt.auto_subtitles_snapshot == _SAMPLE_SNAPSHOT

            # Persist the rebuilt state and reload — the snapshot must
            # still be there.
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                uow.reels.states.save(rebuilt)  # type: ignore[union-attr]
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                state_after = uow.reels.states.get(  # type: ignore[union-attr]
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                )
            assert state_after is not None
            assert state_after.auto_subtitles_snapshot == _SAMPLE_SNAPSHOT


def test_update_publish_status_preserves_auto_subtitles_snapshot() -> None:
    """``ReelStateRepository.update_publish_status`` must not clobber the
    snapshot column. Same regression test family as the per-feature
    overrides — the helper rebuilds the state from a peek and writes it
    back, so a missing forward of the snapshot field would drop it.
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            _write_auto_subtitles_snapshot(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                snapshot=_serialized_snapshot(),
            )

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                uow.reels.states.update_publish_status(  # type: ignore[union-attr]
                    agency_id=seeded.agency_id,
                    ingestion_source_id=seeded.ingestion_source_id,
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                    status="published",
                    details={"reason": "test"},
                )

            persisted = _read_auto_subtitles_snapshot(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            assert persisted == _SAMPLE_SNAPSHOT


def test_update_workflow_state_preserves_auto_subtitles_snapshot() -> None:
    """``update_workflow_state`` mirrors the snapshot preservation contract."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            _write_auto_subtitles_snapshot(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                snapshot=_serialized_snapshot(),
            )

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                uow.reels.states.update_workflow_state(  # type: ignore[union-attr]
                    agency_id=seeded.agency_id,
                    ingestion_source_id=seeded.ingestion_source_id,
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                    workflow_state="approved",
                )

            persisted = _read_auto_subtitles_snapshot(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            assert persisted == _SAMPLE_SNAPSHOT


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------


def test_get_reel_returns_publish_subtitles_snapshot_when_populated() -> None:
    """``GET /v1/admin/agencies/{id}/reels/{site}/{prop}`` exposes the
    column under the snake_case key ``publish_subtitles_snapshot``.
    """
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
            _write_auto_subtitles_snapshot(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                snapshot=_serialized_snapshot(),
            )

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert "reel" in body
            assert body["reel"]["publish_subtitles_snapshot"] == _SAMPLE_SNAPSHOT


def test_get_reel_publish_subtitles_snapshot_is_null_when_unset() -> None:
    """A reel that never ran an autoCaptions render returns ``null``."""
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
            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["reel"]["publish_subtitles_snapshot"] is None


def test_list_reels_returns_publish_subtitles_snapshot() -> None:
    """The listing endpoint carries the same field for every item."""
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
            _write_auto_subtitles_snapshot(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                snapshot=_serialized_snapshot(),
            )

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["count"] == 1
            item = body["items"][0]
            assert item["publish_subtitles_snapshot"] == _SAMPLE_SNAPSHOT
