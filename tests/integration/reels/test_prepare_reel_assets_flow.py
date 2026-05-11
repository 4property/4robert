"""Integration test for `PrepareReelAssetsUseCase` against Postgres.

Runs ingest first to materialise the `reels` row + base `properties` row,
then runs prepare — with the HTTP downloader stubbed via monkeypatch — and
asserts that:
  * the `reels` row transitions to `workflow_state='assets_prepared'`,
  * `property_images` rows reflect the downloaded selection,
  * the on-disk `selected_photos/` directory contains the prepared image.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from modules.reels.domain.types import PropertyMediaJob
from modules.tenancy.domain.context import TenantContext
from modules.reels.application.use_cases.ingest_property_into_reel import (
    IngestPropertyIntoReelUseCase,
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
    "id": 84,
    "slug": "casa-grande",
    "title": {"rendered": "Casa Grande"},
    "link": "https://ckp.ie/casa-grande",
    "property_status": "for sale",
    "price": "350000",
    "wppd_pics": ["https://ckp.ie/img1.jpg", "https://ckp.ie/img2.jpg"],
}


def _build_job(*, agency_id: str, ingestion_source_id: str, site_id: str) -> PropertyMediaJob:
    tenant = TenantContext(
        site_id=site_id,
        agency_id=agency_id,
        wordpress_source_id=ingestion_source_id,
    )
    return PropertyMediaJob(
        event_id="event-1",
        tenant=tenant,
        property_id=84,
        received_at="2026-05-02T10:00:00+00:00",
        raw_payload_hash="hash-1",
        payload=_PAYLOAD,
        publish_context=None,
        job_id="job-1",
    )


def test_execute_writes_assets_prepared_state_and_property_images_on_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
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

            # Stub the engine to avoid network and Gemini calls. The fake
            # selection produces a curated dir with one image whose path is
            # written to `property_images.local_path`.
            selected_dir = (
                context.storage_paths.filtered_images_root
                / context.property.folder_name
                / "selected_photos"
            )
            selected_dir.mkdir(parents=True, exist_ok=True)
            curated_image_path = selected_dir / "01_curated.jpg"
            curated_image_path.write_bytes(b"curated-bytes")
            primary_image_path = selected_dir / "primary_image.jpg"
            primary_image_path.write_bytes(b"primary-bytes")

            def _fake_select_photos(self, *, property_item, raw_images_root, filtered_images_root):  # type: ignore[no-untyped-def]
                return selected_dir, [
                    (1, "https://ckp.ie/img1.jpg", curated_image_path),
                    (2, "https://ckp.ie/img2.jpg", None),
                ]

            monkeypatch.setattr(
                LocalPhotoSelectionEngine, "select_photos", _fake_select_photos
            )

            prepare = PrepareReelAssetsUseCase(
                workspace_dir=workspace_dir,
                database_locator=database.url,
            )
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                result = prepare.execute(context, uow=uow)

            # Returned value reflects the on-disk selection.
            assert result.selected_dir == selected_dir
            assert curated_image_path in result.selected_photo_paths
            assert result.primary_image_path == primary_image_path

            engine = create_engine(database.url, future=True)
            try:
                with engine.connect() as connection:
                    reel_row = connection.execute(
                        text(
                            "SELECT workflow_state FROM reels "
                            "WHERE external_source_id = :site_id "
                            "AND source_property_id = :pid"
                        ),
                        {"site_id": seeded.external_source_id, "pid": 84},
                    ).first()
                    assert reel_row is not None
                    assert reel_row.workflow_state == "assets_prepared"

                    property_row = connection.execute(
                        text(
                            "SELECT record_id FROM properties "
                            "WHERE external_source_id = :site_id "
                            "AND source_property_id = :pid"
                        ),
                        {"site_id": seeded.external_source_id, "pid": 84},
                    ).first()
                    assert property_row is not None
                    record_id = int(property_row.record_id)

                    image_rows = connection.execute(
                        text(
                            "SELECT position, image_url, local_path "
                            "FROM property_images WHERE record_id = :rid "
                            "ORDER BY position ASC"
                        ),
                        {"rid": record_id},
                    ).all()
                    assert len(image_rows) == 2
                    assert image_rows[0].position == 1
                    assert image_rows[0].image_url == "https://ckp.ie/img1.jpg"
                    assert image_rows[0].local_path  # non-empty (relative path)
                    assert image_rows[1].position == 2
                    assert image_rows[1].image_url == "https://ckp.ie/img2.jpg"
                    assert image_rows[1].local_path is None
            finally:
                engine.dispose()

            # The on-disk directory survives (cleanup is a separate step).
            assert selected_dir.exists()
            assert (selected_dir / "01_curated.jpg").exists()
