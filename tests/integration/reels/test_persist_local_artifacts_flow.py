"""Integration test for `PersistLocalArtifactsUseCase` against Postgres.

Chains ingest -> prepare -> persist on a temporary schema with seeded
tenant. The render step is faked: a `RenderedMediaArtifact` pointing at a
`tempfile.TemporaryDirectory()` staging is built directly with synthetic
mp4/manifest/poster bytes. After `execute(...)`, the test asserts that:
  * the `reels` row transitions to `workflow_state='rendered'` +
    `render_status='completed'` and stores relative artifact/metadata paths,
  * a `media_revisions` row is appended with `workflow_state='rendered'`,
  * an `outbox_events` row exists with `event_type='media_rendered'` and
    payload containing the relative paths,
  * the on-disk artifacts (mp4, manifest, poster) live in the canonical
    output directories.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from modules.reels.domain.types import PropertyMediaJob, RenderedMediaArtifact
from modules.tenancy.domain.context import TenantContext
from modules.reels.application.use_cases.ingest_property_into_reel import (
    IngestPropertyIntoReelUseCase,
)
from modules.reels.application.use_cases.persist_local_artifacts import (
    PersistLocalArtifactsUseCase,
)
from modules.reels.application.use_cases.prepare_reel_assets import (
    LocalPhotoSelectionEngine,
    PrepareReelAssetsUseCase,
)
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.support.postgres import (
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


_PAYLOAD = {
    "id": 91,
    "slug": "casa-morena",
    "title": {"rendered": "Casa Morena"},
    "link": "https://ckp.ie/casa-morena",
    "property_status": "for sale",
    "price": "475000",
    "wppd_pics": ["https://ckp.ie/imgA.jpg"],
}


def _build_job(
    *, agency_id: str, ingestion_source_id: str, site_id: str
) -> PropertyMediaJob:
    tenant = TenantContext(
        site_id=site_id,
        agency_id=agency_id,
        wordpress_source_id=ingestion_source_id,
    )
    return PropertyMediaJob(
        event_id="event-persist",
        tenant=tenant,
        property_id=91,
        received_at="2026-05-04T09:00:00+00:00",
        raw_payload_hash="hash-persist",
        payload=_PAYLOAD,
        publish_context=None,
        job_id="job-persist",
    )


def test_execute_writes_rendered_state_revision_and_outbox_event_on_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url, site_id="ckp.ie", workspace_dir=workspace_dir
            )

            # Step 1 — ingest creates the reels + properties rows.
            ingest = IngestPropertyIntoReelUseCase(
                workspace_dir=workspace_dir,
                property_url_template="",
                property_url_tracking_params=None,
                social_publishing_enabled=False,
                database_locator=database.url,
            )
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                context = ingest.execute(
                    _build_job(
                        agency_id=seeded.agency_id,
                        ingestion_source_id=seeded.ingestion_source_id,
                        site_id=seeded.external_source_id,
                    ),
                    uow=uow,
                )

            # Step 2 — prepare assets (engine stubbed so no network).
            selected_dir = (
                context.storage_paths.filtered_images_root
                / context.property.folder_name
                / "selected_photos"
            )
            selected_dir.mkdir(parents=True, exist_ok=True)
            curated_image_path = selected_dir / "01_curated.jpg"
            curated_image_path.write_bytes(b"curated-bytes")

            def _fake_select_photos(
                self, *, property_item, raw_images_root, filtered_images_root
            ):  # type: ignore[no-untyped-def]
                return selected_dir, [
                    (1, "https://ckp.ie/imgA.jpg", curated_image_path),
                ]

            monkeypatch.setattr(
                LocalPhotoSelectionEngine, "select_photos", _fake_select_photos
            )

            prepare = PrepareReelAssetsUseCase(
                workspace_dir=workspace_dir,
                database_locator=database.url,
            )
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                prepare.execute(context, uow=uow)

            # Step 3 — persist: build a synthetic rendered artifact in a
            # temp staging dir and exercise the use case end-to-end.
            with tempfile.TemporaryDirectory() as staging_root:
                staging_dir = Path(staging_root) / "render-staging"
                staging_dir.mkdir(parents=True, exist_ok=True)
                slug = context.property.slug
                media_path = staging_dir / f"{slug}-reel.mp4"
                manifest_path = staging_dir / f"{slug}-reel.json"
                poster_path = staging_dir / f"{slug}-poster.jpg"
                media_path.write_bytes(b"\x00\x00\x00 ftypmp42")
                manifest_path.write_bytes(b'{"version": 1}')
                poster_path.write_bytes(b"\xff\xd8\xff\xe0")
                rendered = RenderedMediaArtifact(
                    staging_dir=staging_dir,
                    artifact_kind="reel_video",
                    media_path=media_path,
                    metadata_path=manifest_path,
                    revision_id="revision-persist",
                )

                persist = PersistLocalArtifactsUseCase(
                    workspace_dir=workspace_dir,
                    cleanup_temporary_files=False,
                    database_locator=database.url,
                )
                with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                    published = persist.execute(context, rendered, uow=uow)

            # On-disk artifacts now in canonical output directories.
            final_reels_dir = context.storage_paths.generated_reels_root
            final_posters_dir = context.storage_paths.generated_posters_root
            assert (final_reels_dir / f"{slug}-reel.mp4").exists()
            assert (final_reels_dir / f"{slug}-reel.json").exists()
            assert (final_posters_dir / f"{slug}-poster.jpg").exists()
            assert published.media_path == final_reels_dir / f"{slug}-reel.mp4"
            assert published.metadata_path == final_reels_dir / f"{slug}-reel.json"
            assert published.revision_id == "revision-persist"

            engine = create_engine(database.url, future=True)
            try:
                with engine.connect() as connection:
                    reel_row = connection.execute(
                        text(
                            "SELECT workflow_state, render_status, "
                            "local_artifact_path, local_metadata_path, "
                            "current_revision_id FROM reels "
                            "WHERE external_source_id = :site_id "
                            "AND source_property_id = :pid"
                        ),
                        {"site_id": seeded.external_source_id, "pid": 91},
                    ).first()
                    assert reel_row is not None
                    assert reel_row.workflow_state == "rendered"
                    assert reel_row.render_status == "completed"
                    assert reel_row.local_artifact_path  # relative path string
                    assert reel_row.local_metadata_path
                    assert reel_row.current_revision_id == "revision-persist"

                    revision_row = connection.execute(
                        text(
                            "SELECT revision_id, workflow_state, artifact_kind, "
                            "media_path, metadata_path, mime_type "
                            "FROM media_revisions "
                            "WHERE external_source_id = :site_id "
                            "AND source_property_id = :pid"
                        ),
                        {"site_id": seeded.external_source_id, "pid": 91},
                    ).first()
                    assert revision_row is not None
                    assert revision_row.revision_id == "revision-persist"
                    assert revision_row.workflow_state == "rendered"
                    assert revision_row.artifact_kind == "reel_video"
                    assert revision_row.media_path
                    assert revision_row.metadata_path
                    assert revision_row.mime_type  # mime guessed from extension

                    event_rows = connection.execute(
                        text(
                            "SELECT event_type, payload FROM outbox_events "
                            "WHERE external_source_id = :site_id "
                            "AND source_property_id = :pid "
                            "AND event_type = 'media_rendered'"
                        ),
                        {"site_id": seeded.external_source_id, "pid": 91},
                    ).all()
                    assert len(event_rows) == 1
                    payload_raw = event_rows[0].payload
                    payload = (
                        payload_raw
                        if isinstance(payload_raw, dict)
                        else json.loads(payload_raw)
                    )
                    assert payload["workflow_state"] == "rendered"
                    assert payload["revision_id"] == "revision-persist"
                    assert payload["media_path"]
                    assert payload["metadata_path"]
            finally:
                engine.dispose()
