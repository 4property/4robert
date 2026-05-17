"""End-to-end dispatcher flow test for feature 16.

Exercises ``claim`` -> handler (real) -> outbox on a temporary Postgres
schema. Compared with ``tests/integration/test_worker_runtime.py`` which
uses handler mocks, this test wires the **real** ``ReelPipeline.handle``
(and ``RenderScriptedVideoUseCase.execute``) and asserts that the
modern worker handlers produce the right side effects:

* ``delivery.jobs.status`` flips to ``completed``;
* ``delivery.webhook_events.status`` flips to ``completed``;
* ``outbox_events`` rows are appended with the expected
  ``event_type`` (``publish_completed``/``publish_skipped`` for the
  reel pipeline; ``media_rendered`` is also produced when the render
  step runs).

The render step is faked (``DefaultMediaRenderer.render_media`` /
``ScriptedVideoRenderService.render_from_manifest`` patched) to avoid
ffmpeg/disk costs in CI. The social provider is faked similarly to
``tests/integration/reels/test_publish_reel_flow.py``.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import mock
from uuid import uuid4

from sqlalchemy import create_engine, text

from apps.worker.runtime import JobDispatcher, WorkerSettings
from modules.delivery.domain import JobEnqueueRequest
from modules.reels.application.orchestrator import ReelPipeline
from modules.reels.application.use_cases.prepare_reel_assets import (
    LocalPhotoSelectionEngine,
)
from modules.reels.application.use_cases.render_scripted_video import (
    RenderScriptedVideoUseCase,
)
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.support.postgres import (
    seed_provider_connection,
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


_REEL_PAYLOAD = {
    "id": 137,
    "slug": "casa-azul",
    "title": {"rendered": "Casa Azul"},
    "link": "https://ckp.ie/casa-azul",
    "property_status": "for sale",
    "price": "525000",
    "wppd_pics": ["https://ckp.ie/imgZ.jpg"],
}


class _FakePropertyPublisher:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    def publish_property_media(self, context, published_media):  # type: ignore[no-untyped-def]
        self.calls.append((context, published_media))
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


class WorkerDispatcherFlowTests(unittest.TestCase):
    def test_reel_publish_handler_completes_job_and_writes_outbox(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                tenant = seed_tenant(
                    database.url, site_id="ckp.ie", workspace_dir=workspace_dir
                )
                seed_provider_connection(
                    database.url,
                    agency_id=tenant.agency_id,
                    provider="gohighlevel",
                    external_id="loc-test",
                )

                # Pre-create the curated photo so the prepare step can find
                # an existing selected dir without running the AI engine
                # over the network.
                selected_dir = (
                    workspace_dir
                    / "property_media"
                    / tenant.external_source_id
                    / "casa-azul-137"
                    / "selected_photos"
                )
                selected_dir.mkdir(parents=True, exist_ok=True)
                (selected_dir / "01_curated.jpg").write_bytes(b"curated-bytes")

                def _fake_select_photos(
                    self,
                    *,
                    property_item,
                    raw_images_root,
                    filtered_images_root,
                ):  # type: ignore[no-untyped-def]
                    return selected_dir, [
                        (1, "https://ckp.ie/imgZ.jpg", selected_dir / "01_curated.jpg"),
                    ]

                fake_publisher = _FakePropertyPublisher()
                job_id, event_id = _enqueue_reel_publish_job(
                    database.url,
                    agency_id=tenant.agency_id,
                    ingestion_source_id=tenant.ingestion_source_id,
                    external_source_id=tenant.external_source_id,
                    property_id=137,
                )

                with mock.patch.object(
                    LocalPhotoSelectionEngine,
                    "select_photos",
                    _fake_select_photos,
                ), mock.patch(
                    "modules.reels.application.orchestrator."
                    "DefaultMediaRenderer.render_media",
                    autospec=True,
                    side_effect=_fake_render_media,
                ), mock.patch(
                    "modules.reels.application.orchestrator."
                    "_build_default_social_property_publisher",
                    return_value=fake_publisher,
                ), mock.patch(
                    # Force social_publishing_active=True regardless of the
                    # operator's local ``.env`` (``SOCIAL_PUBLISHING_LOCAL_ONLY``
                    # may be ``true`` for offline development) so the
                    # orchestrator wires the fake publisher and the
                    # ``IngestPropertyIntoReelUseCase`` produces pending
                    # publish platforms.
                    "modules.reels.application.orchestrator."
                    "SOCIAL_PUBLISHING_LOCAL_ONLY",
                    False,
                ), mock.patch(
                    "modules.reels.application.orchestrator."
                    "SOCIAL_PUBLISHING_ENABLED",
                    True,
                ):
                    dispatcher = JobDispatcher(
                        settings=WorkerSettings(
                            base_dir=workspace_dir,
                            database_locator=database.url,
                        )
                    )
                    pipeline = ReelPipeline(
                        workspace_dir=workspace_dir,
                        database_locator=database.url,
                    )
                    # Inject a fake social publisher into the pipeline so
                    # the publish step does not attempt a real
                    # GoHighLevel call.
                    pipeline._publish.social_publisher = fake_publisher
                    pipeline._social_publisher = fake_publisher
                    dispatcher.register_handler("reel_publish", pipeline.handle)

                    processed = dispatcher._process_next_job("worker-test")

                self.assertTrue(processed)

                with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                    job = uow.delivery.jobs.get_job(job_id)
                    event = uow.delivery.webhook_events.get_event(event_id)
                self.assertIsNotNone(job)
                self.assertEqual(job.status, "completed")
                self.assertIsNotNone(event)
                self.assertEqual(event.status, "completed")
                self.assertEqual(len(fake_publisher.calls), 1)

                engine = create_engine(database.url, future=True)
                try:
                    with engine.connect() as connection:
                        outbox_rows = connection.execute(
                            text(
                                "SELECT event_type, status FROM outbox_events "
                                "WHERE source_property_id = :pid "
                                "ORDER BY created_at"
                            ),
                            {"pid": 137},
                        ).all()
                finally:
                    engine.dispose()

                outbox_event_types = [row.event_type for row in outbox_rows]
                self.assertIn("publish_completed", outbox_event_types)
                publish_row = next(
                    row
                    for row in outbox_rows
                    if row.event_type == "publish_completed"
                )
                self.assertEqual(publish_row.status, "completed")

    def test_scripted_render_handler_processes_job(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                tenant = seed_tenant(database.url, site_id="ckp.ie")
                manifest_payload: dict[str, Any] = {
                    "title": "Sample Property",
                    "property_status": "For Sale",
                    "slides": [{"image_path": "uploads/slide-01.jpg"}],
                }
                job_id, event_id = _enqueue_scripted_render_job(
                    database.url,
                    agency_id=tenant.agency_id,
                    ingestion_source_id=tenant.ingestion_source_id,
                    external_source_id=tenant.external_source_id,
                    property_id=170800,
                    payload=manifest_payload,
                )

                fake_result = SimpleNamespace(
                    artifact_id=str(uuid4()),
                    site_id=tenant.external_source_id,
                    source_property_id=170800,
                )

                def _fake_render_from_manifest(self, payload):  # type: ignore[no-untyped-def]
                    self.calls.append(dict(payload))
                    return fake_result

                with mock.patch(
                    "modules.rendering.application.scripted_video.render_service."
                    "ScriptedVideoRenderService.__init__",
                    lambda self, workspace_dir, *, unit_of_work_factory: setattr(
                        self, "calls", []
                    ),
                ), mock.patch(
                    "modules.rendering.application.scripted_video.render_service."
                    "ScriptedVideoRenderService.render_from_manifest",
                    _fake_render_from_manifest,
                ):
                    dispatcher = JobDispatcher(
                        settings=WorkerSettings(
                            base_dir=workspace_dir,
                            database_locator=database.url,
                        )
                    )
                    scripted = RenderScriptedVideoUseCase(
                        workspace_dir=workspace_dir,
                        database_locator=database.url,
                    )
                    dispatcher.register_handler(
                        "scripted_render", scripted.execute
                    )

                    processed = dispatcher._process_next_job("worker-test")

                self.assertTrue(processed)
                with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                    job = uow.delivery.jobs.get_job(job_id)
                    event = uow.delivery.webhook_events.get_event(event_id)
                self.assertIsNotNone(job)
                self.assertEqual(job.status, "completed")
                self.assertIsNotNone(event)
                self.assertEqual(event.status, "completed")


def _fake_render_media(self, context, prepared_assets):  # type: ignore[no-untyped-def]
    """Minimal stand-in for ``DefaultMediaRenderer.render_media``.

    Builds a synthetic ``RenderedMediaArtifact`` with on-disk media,
    manifest, and poster files so the persist step can atomically
    promote them and the publish step can stamp the workflow.
    """
    from modules.reels.domain.types import RenderedMediaArtifact

    staging_root = context.storage_paths.generated_reels_root / "_staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(prefix=f"{context.property.slug}-", dir=staging_root)
    )
    media_path = staging_dir / f"{context.property.slug}-reel.mp4"
    manifest_path = staging_dir / f"{context.property.slug}-reel.json"
    poster_path = staging_dir / f"{context.property.slug}-poster.jpg"
    media_path.write_bytes(b"\x00\x00\x00 ftypmp42")
    manifest_path.write_bytes(b'{"version": 1}')
    poster_path.write_bytes(b"\xff\xd8\xff\xe0")
    return RenderedMediaArtifact(
        staging_dir=staging_dir,
        artifact_kind="reel_video",
        media_path=media_path,
        metadata_path=manifest_path,
        revision_id=uuid4().hex,
    )


def _enqueue_reel_publish_job(
    database_url: str,
    *,
    agency_id: str,
    ingestion_source_id: str,
    external_source_id: str,
    property_id: int,
) -> tuple[str, str]:
    now = datetime.now(timezone.utc).isoformat()
    job_id = str(uuid4())
    event_id = str(uuid4())
    with DatabaseUnitOfWork(database_url) as uow:
        uow.delivery.webhook_events.create_event(
            event_id=event_id,
            agency_id=agency_id,
            ingestion_source_id=ingestion_source_id,
            external_source_id=external_source_id,
            source_kind="wordpress",
            property_id=property_id,
            received_at=now,
            raw_payload_hash="hash-test",
            status="queued",
        )
        uow.delivery.jobs.enqueue_job(
            JobEnqueueRequest(
                job_id=job_id,
                event_id=event_id,
                agency_id=agency_id,
                ingestion_source_id=ingestion_source_id,
                kind="reel_publish",
                external_source_id=external_source_id,
                property_id=property_id,
                received_at=now,
                raw_payload_hash="hash-test",
                payload=_REEL_PAYLOAD,
                publish_context={
                    "provider": "gohighlevel",
                    "location_id": "loc-test",
                    "platforms": ["tiktok"],
                    "approval_required": False,
                },
                provider_secret_bundle=json.dumps(
                    {"access_token": "token-test", "provider": "gohighlevel"}
                ),
                max_attempts=3,
                available_at=now,
                created_at=now,
            )
        )
    return job_id, event_id


def _enqueue_scripted_render_job(
    database_url: str,
    *,
    agency_id: str,
    ingestion_source_id: str,
    external_source_id: str,
    property_id: int,
    payload: dict[str, Any],
) -> tuple[str, str]:
    now = datetime.now(timezone.utc).isoformat()
    job_id = str(uuid4())
    event_id = str(uuid4())
    full_payload = dict(payload)
    full_payload.setdefault("site_id", external_source_id)
    full_payload.setdefault("source_property_id", property_id)
    with DatabaseUnitOfWork(database_url) as uow:
        uow.delivery.webhook_events.create_event(
            event_id=event_id,
            agency_id=agency_id,
            ingestion_source_id=ingestion_source_id,
            external_source_id=external_source_id,
            source_kind="scripted_api",
            property_id=property_id,
            received_at=now,
            raw_payload_hash="hash-scripted",
            status="queued",
        )
        uow.delivery.jobs.enqueue_job(
            JobEnqueueRequest(
                job_id=job_id,
                event_id=event_id,
                agency_id=agency_id,
                ingestion_source_id=ingestion_source_id,
                kind="scripted_render",
                external_source_id=external_source_id,
                property_id=property_id,
                received_at=now,
                raw_payload_hash="hash-scripted",
                payload=full_payload,
                publish_context={},
                provider_secret_bundle="",
                max_attempts=1,
                available_at=now,
                created_at=now,
            )
        )
    return job_id, event_id


if __name__ == "__main__":
    unittest.main()
