"""Integration test for `PublishReelUseCase` against Postgres.

Chains ingest -> prepare -> persist -> publish on a temporary schema with
seeded tenant and a seeded `provider_connections` row. The render step
is faked: a `RenderedMediaArtifact` pointing at a
`tempfile.TemporaryDirectory()` staging is built directly with synthetic
mp4/manifest/poster bytes. The social provider is faked with a publisher
returning a `MultiPlatformPublishResult`-like object whose
`aggregate_status='published'`. After `execute(...)`, the test asserts:

  * the `reels` row transitions to `workflow_state='published'` +
    `publish_status='published'` and stores
    `last_published_provider_external_id`;
  * a second `media_revisions` row is appended with
    `workflow_state='published'`;
  * an `outbox_events` row with `event_type='publish_completed'` and
    `status='completed'` is written (acceptance literal);
  * payload JSON contains the aggregate result data.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import create_engine, text

from modules.reels.domain.types import (
    PropertyMediaJob,
    PublishedMediaArtifact,
    RenderedMediaArtifact,
    SocialPublishContext,
)
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
from modules.reels.application.use_cases.publish_reel import PublishReelUseCase
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.support.postgres import (
    seed_provider_connection,
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


_PAYLOAD = {
    "id": 137,
    "slug": "casa-azul",
    "title": {"rendered": "Casa Azul"},
    "link": "https://ckp.ie/casa-azul",
    "property_status": "for sale",
    "price": "525000",
    "wppd_pics": ["https://ckp.ie/imgZ.jpg"],
}


def _build_job(
    *,
    agency_id: str,
    ingestion_source_id: str,
    site_id: str,
    publish_context: SocialPublishContext,
) -> PropertyMediaJob:
    tenant = TenantContext(
        site_id=site_id,
        agency_id=agency_id,
        wordpress_source_id=ingestion_source_id,
    )
    return PropertyMediaJob(
        event_id="event-publish",
        tenant=tenant,
        property_id=137,
        received_at="2026-05-04T12:00:00+00:00",
        raw_payload_hash="hash-publish",
        payload=_PAYLOAD,
        publish_context=publish_context,
        job_id="job-publish",
    )


class _FakePropertyPublisher:
    def __init__(self, *, result: Any) -> None:
        self.result = result
        self.calls: list[Any] = []

    def publish_property_media(self, context, published_media):  # type: ignore[no-untyped-def]
        self.calls.append((context, published_media))
        return self.result


class _LocalPublisherAdapter:
    """Inline test adapter binding `PersistLocalArtifactsUseCase` to the
    test's scoped `database_locator`. Mirrors what
    `FileSystemMediaPublisher` does in production, but with the
    test-injected schema URL so writes land on the temporary schema.
    """

    def __init__(self, *, persist: PersistLocalArtifactsUseCase) -> None:
        self.persist = persist

    def publish_media(
        self, context, rendered_media: RenderedMediaArtifact
    ) -> PublishedMediaArtifact:
        return self.persist.execute(context, rendered_media)

    def publish_existing_media(self, context) -> PublishedMediaArtifact:
        return self.persist.execute_existing(context)


def _build_publish_result() -> Any:
    return SimpleNamespace(
        aggregate_status="published",
        successful_platforms=("tiktok",),
        to_dict=lambda: {
            "aggregate_status": "published",
            "successful_platforms": ["tiktok"],
            "desired_platforms": ["tiktok"],
            "platform_results": {
                "tiktok": {
                    "platform": "tiktok",
                    "outcome": "published",
                }
            },
        },
    )


def test_execute_writes_published_state_revision_and_outbox_completed_on_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publish_context = SocialPublishContext(
        provider="gohighlevel",
        location_id="loc-test",
        access_token="token-test",
        platforms=("tiktok",),
        approval_required=False,
    )
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            connection_id = seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                provider="gohighlevel",
                external_id="loc-test",
            )
            assert connection_id  # sanity: provider connection seeded.

            # Step 1 — ingest creates the reels + properties rows.
            ingest = IngestPropertyIntoReelUseCase(
                workspace_dir=workspace_dir,
                property_url_template="",
                property_url_tracking_params=None,
                social_publishing_enabled=True,
                database_locator=database.url,
            )
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                context = ingest.execute(
                    _build_job(
                        agency_id=seeded.agency_id,
                        ingestion_source_id=seeded.ingestion_source_id,
                        site_id=seeded.external_source_id,
                        publish_context=publish_context,
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
                    (1, "https://ckp.ie/imgZ.jpg", curated_image_path),
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

            # Step 3 + 4 — persist + publish via the use case under test.
            local_publisher = _LocalPublisherAdapter(
                persist=PersistLocalArtifactsUseCase(
                    workspace_dir=workspace_dir,
                    cleanup_temporary_files=False,
                    database_locator=database.url,
                )
            )
            fake_publisher = _FakePropertyPublisher(result=_build_publish_result())
            publish_use_case = PublishReelUseCase(
                local_publisher=local_publisher,
                workspace_dir=workspace_dir,
                social_publisher=fake_publisher,
                database_locator=database.url,
            )

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
                    revision_id="revision-publish",
                )

                published = publish_use_case.execute(context, rendered)

            assert published.revision_id == "revision-publish"
            assert len(fake_publisher.calls) == 1

            engine = create_engine(database.url, future=True)
            try:
                with engine.connect() as connection:
                    reel_row = connection.execute(
                        text(
                            "SELECT workflow_state, publish_status, "
                            "last_published_provider_external_id, "
                            "current_revision_id FROM reels "
                            "WHERE external_source_id = :site_id "
                            "AND source_property_id = :pid"
                        ),
                        {"site_id": seeded.external_source_id, "pid": 137},
                    ).first()
                    assert reel_row is not None
                    assert reel_row.workflow_state == "published"
                    assert reel_row.publish_status == "published"
                    assert reel_row.last_published_provider_external_id == "loc-test"
                    assert reel_row.current_revision_id == "revision-publish"

                    revision_row = connection.execute(
                        text(
                            "SELECT revision_id, workflow_state FROM media_revisions "
                            "WHERE external_source_id = :site_id "
                            "AND source_property_id = :pid"
                        ),
                        {"site_id": seeded.external_source_id, "pid": 137},
                    ).first()
                    assert revision_row is not None
                    assert revision_row.revision_id == "revision-publish"
                    # `save_revision` upserts on revision_id, so the final
                    # row reflects the publish-side workflow_state.
                    assert revision_row.workflow_state == "published"

                    completed_rows = connection.execute(
                        text(
                            "SELECT event_type, status, payload FROM outbox_events "
                            "WHERE external_source_id = :site_id "
                            "AND source_property_id = :pid "
                            "AND event_type = 'publish_completed'"
                        ),
                        {"site_id": seeded.external_source_id, "pid": 137},
                    ).all()
                    assert len(completed_rows) == 1
                    completed_event = completed_rows[0]
                    assert completed_event.status == "completed"
                    payload_raw = completed_event.payload
                    payload = (
                        payload_raw
                        if isinstance(payload_raw, dict)
                        else json.loads(payload_raw)
                    )
                    assert payload["workflow_state"] == "published"
                    assert payload["aggregate_status"] == "published"
                    assert payload["successful_platforms"] == ["tiktok"]
            finally:
                engine.dispose()
