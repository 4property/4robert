from __future__ import annotations

import json
import os
import shutil
import sys
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

APPLICATION_ROOT = Path(__file__).resolve().parents[1]
if str(APPLICATION_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLICATION_ROOT))

from application.dispatching import SqliteJobDispatcher
from application.default_services import (
    DefaultMediaPreparationService,
    DefaultPropertyInfoService,
    FileSystemMediaPublisher,
)
from application.media_planning import build_media_delivery_plan, normalize_listing_lifecycle
from application.types import (
    PreparedMediaAssets,
    PropertyVideoJob,
    RenderedMediaArtifact,
    SocialPublishContext,
)
from application.webhook_acceptance import WebhookAcceptanceService
from config import (
    DATABASE_FILENAME,
    GEMINI_SELECTION_AUDIT_FILENAME,
    PERSISTENT_LOG_DIRECTORY,
    SOCIAL_PUBLISHING_DEFAULT_PLATFORMS,
)
from core.errors import TransientSocialPublishingError
from models.property import Property
from repositories.media_revision_repository import MediaRevisionRepository
from repositories.outbox_event_repository import OutboxEventRepository
from repositories.property_job_repository import PropertyJobEnqueueRequest, PropertyJobRepository
from repositories.scripted_video_artifact_repository import (
    SCRIPTED_VIDEO_ARTIFACT_TABLE_NAME,
    ScriptedVideoArtifactRecord,
    ScriptedVideoArtifactRepository,
)
from repositories.sqlite_work_unit import SqliteWorkUnit
from repositories.webhook_delivery_repository import WebhookDeliveryRepository
from repositories.property_pipeline_repository import PropertyPipelineRepository
from services.reel_rendering.formatting import (
    build_property_header_details_line,
    escape_filter_path,
    fit_wrapped_lines,
    format_property_size,
    format_property_size_header,
)
from services.reel_rendering.filters import build_filter_complex, build_overlay_filter
from services.reel_rendering.layout import build_overlay_layout
from services.reel_rendering.manifest import build_property_reel_manifest_from_data
from services.reel_rendering.models import (
    PreparedReelAssets,
    PreparedReelSlide,
    PropertyRenderData,
    PropertyReelSlide,
    PropertyReelTemplate,
)
from services.reel_rendering.render import build_reel_template_for_render_profile
from services.reel_rendering.runtime import prepare_cover_logo_image, resolve_ber_icon_path, resolve_font_path
from services.webhook_transport.operations import build_readiness_report
from services.webhook_transport.uvicorn_protocols import (
    build_invalid_http_request_preview,
    format_invalid_http_request_warning,
    infer_invalid_http_request_hint,
)
from services.webhook_transport.security import build_signature
from services.webhook_transport.server import WordPressWebhookApplication, create_fastapi_app
from services.webhook_transport.site_storage import resolve_site_storage_layout

SIMULATOR_ROOT = Path(__file__).resolve().parents[2] / "wordpress-webhook-simulator"
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

try:
    import send_webhook  # type: ignore[import-not-found]
except ModuleNotFoundError:
    send_webhook = None

TEST_TEMP_ROOT = APPLICATION_ROOT / ".tmp_test_cases"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)


@contextmanager
def workspace_temp_dir():
    temp_dir = TEST_TEMP_ROOT / uuid4().hex
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def build_sample_payload(
    *,
    property_id: int = 170800,
    property_status: str = "For Sale",
    modified_gmt: str = "2026-03-24T10:43:19",
    property_features: list[str] | None = None,
    viewing_times: list[str] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": property_id,
        "slug": "sample-property",
        "title": {"rendered": "46 Example Street, Dublin 4"},
        "modified_gmt": modified_gmt,
        "property_status": property_status,
        "price": "650000",
        "bedrooms": 3,
        "bathrooms": 2,
        "ber_rating": "B2",
        "link": "https://ckp.ie/property/sample-property",
        "agent_name": "Jane Doe",
        "agent_photo": "https://example.com/agent.jpg",
        "agent_email": "jane@example.com",
        "agent_number": "+353 1 234 5678",
        "agency_logo": "https://example.com/agency-logo.png",
        "wppd_primary_image": "https://example.com/property-primary.jpg",
        "wppd_pics": [
            "https://example.com/property-primary.jpg",
            "https://example.com/property-secondary.jpg",
        ],
        "property_features": property_features or ["Private patio", "Open-plan kitchen"],
    }
    if viewing_times is not None:
        payload["wppd_property_viewing_times"] = viewing_times
    return payload


def build_job(
    *,
    event_id: str = "event-1",
    site_id: str = "site-a",
    payload: dict[str, object] | None = None,
    location_id: str = "location-a",
    access_token: str = "token-a",
    platforms: tuple[str, ...] = ("tiktok",),
) -> PropertyVideoJob:
    active_payload = payload or build_sample_payload()
    return PropertyVideoJob(
        event_id=event_id,
        site_id=site_id,
        property_id=int(active_payload["id"]),
        received_at="2026-03-24T12:00:00+00:00",
        raw_payload_hash="hash",
        payload=active_payload,
        publish_context=SocialPublishContext(
            provider="gohighlevel",
            location_id=location_id,
            access_token=access_token,
            platforms=platforms,
        ),
    )


def build_unit_of_work_factory(workspace_dir: Path):
    database_path = workspace_dir / DATABASE_FILENAME
    return lambda: SqliteWorkUnit(database_path, workspace_dir)


class RecordingDispatcher:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self, timeout: float | None = None) -> None:
        self.stopped = True
        self.started = False

    def enqueue(self, job: PropertyVideoJob) -> None:
        return None

    def wait_for_idle(self, timeout: float = 5.0) -> bool:
        return True

    def is_accepting_jobs(self) -> bool:
        return self.started and not self.stopped


class RejectingDispatcher(RecordingDispatcher):
    def is_accepting_jobs(self) -> bool:
        return False


class FakeHTTPResponse:
    def __init__(self, *, status: int, body: str) -> None:
        self.status = status
        self._body = body.encode("utf-8")

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


class RepositorySchemaTests(unittest.TestCase):
    def test_repository_initialises_pipeline_state_schema_without_token_columns(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            database_path = workspace_dir / DATABASE_FILENAME

            with PropertyPipelineRepository(database_path, workspace_dir) as repository:
                property_columns = {
                    str(row[1])
                    for row in repository.connection.execute("PRAGMA table_info(properties)")
                }
                pipeline_columns = {
                    str(row[1])
                    for row in repository.connection.execute("PRAGMA table_info(property_pipeline_state)")
                }
            with MediaRevisionRepository(database_path) as media_revision_repository:
                media_revision_tables = {
                    str(row[0])
                    for row in media_revision_repository.connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            with OutboxEventRepository(database_path) as outbox_repository:
                outbox_tables = {
                    str(row[0])
                    for row in outbox_repository.connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            with ScriptedVideoArtifactRepository(database_path) as scripted_video_repository:
                scripted_video_tables = {
                    str(row[0])
                    for row in scripted_video_repository.connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            with PropertyJobRepository(database_path) as job_repository:
                job_columns = {
                    str(row[1])
                    for row in job_repository.connection.execute("PRAGMA table_info(job_queue)")
                }

        self.assertIn("agent_photo_url", property_columns)
        self.assertIn("content_fingerprint", pipeline_columns)
        self.assertIn("content_snapshot_json", pipeline_columns)
        self.assertIn("publish_target_fingerprint", pipeline_columns)
        self.assertIn("publish_target_snapshot_json", pipeline_columns)
        self.assertIn("workflow_state", pipeline_columns)
        self.assertIn("current_revision_id", pipeline_columns)
        self.assertIn("last_published_location_id", pipeline_columns)
        self.assertIn("media_revisions", media_revision_tables)
        self.assertIn("outbox_events", outbox_tables)
        self.assertIn(SCRIPTED_VIDEO_ARTIFACT_TABLE_NAME, scripted_video_tables)
        self.assertIn("gohighlevel_access_token", job_columns)
        self.assertFalse(any("access_token" in column for column in property_columns))
        self.assertFalse(any("access_token" in column for column in pipeline_columns))

    def test_repository_persists_viewing_times_from_payload(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            database_path = workspace_dir / DATABASE_FILENAME
            property_item = Property.from_api_payload(
                build_sample_payload(
                    viewing_times=["Saturday 20 April 12:00pm - 12:30pm"],
                )
            )

            with PropertyPipelineRepository(database_path, workspace_dir) as repository:
                repository.save_property_data(property_item, site_id="site-a")
                row = repository.connection.execute(
                    (
                        "SELECT viewing_times FROM properties "
                        "WHERE site_id = ? AND source_property_id = ?"
                    ),
                    ("site-a", property_item.id),
                ).fetchone()

        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(
            json.loads(str(row["viewing_times"])),
            ["Saturday 20 April 12:00pm - 12:30pm"],
        )

    def test_job_queue_initialise_adds_gohighlevel_token_column_to_legacy_table(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            database_path = workspace_dir / DATABASE_FILENAME
            with PropertyJobRepository(database_path) as repository:
                repository.connection.executescript(
                    """
                    DROP TABLE IF EXISTS job_queue;
                    CREATE TABLE job_queue (
                        job_id TEXT PRIMARY KEY,
                        event_id TEXT NOT NULL,
                        site_id TEXT NOT NULL,
                        property_id INTEGER,
                        received_at TEXT NOT NULL DEFAULT '',
                        raw_payload_hash TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        publish_context_json TEXT NOT NULL DEFAULT '',
                        attempt_count INTEGER NOT NULL DEFAULT 0,
                        max_attempts INTEGER NOT NULL DEFAULT 1,
                        available_at TEXT NOT NULL,
                        lease_expires_at TEXT NOT NULL DEFAULT '',
                        worker_id TEXT NOT NULL DEFAULT '',
                        last_error TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        finished_at TEXT NOT NULL DEFAULT '',
                        superseded_by_job_id TEXT NOT NULL DEFAULT ''
                    );
                    """
                )
                repository.initialise()
                job_columns = {
                    str(row[1])
                    for row in repository.connection.execute("PRAGMA table_info(job_queue)")
                }

        self.assertIn("gohighlevel_access_token", job_columns)

    def test_job_queue_claim_serializes_work_for_same_property(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            database_path = workspace_dir / DATABASE_FILENAME
            with PropertyJobRepository(database_path) as repository:
                repository.enqueue_job(
                    PropertyJobEnqueueRequest(
                        job_id="job-1",
                        event_id="event-1",
                        site_id="site-a",
                        property_id=101,
                        received_at="2026-03-31T10:00:00+00:00",
                        raw_payload_hash="hash-1",
                        payload_json='{"id":101}',
                        publish_context_json="",
                        gohighlevel_access_token="",
                        max_attempts=1,
                        available_at="2026-03-31T10:00:00+00:00",
                        created_at="2026-03-31T10:00:00+00:00",
                    )
                )
                repository.enqueue_job(
                    PropertyJobEnqueueRequest(
                        job_id="job-2",
                        event_id="event-2",
                        site_id="site-a",
                        property_id=101,
                        received_at="2026-03-31T10:00:01+00:00",
                        raw_payload_hash="hash-2",
                        payload_json='{"id":101}',
                        publish_context_json="",
                        gohighlevel_access_token="",
                        max_attempts=1,
                        available_at="2026-03-31T10:00:01+00:00",
                        created_at="2026-03-31T10:00:01+00:00",
                    )
                )
                repository.enqueue_job(
                    PropertyJobEnqueueRequest(
                        job_id="job-3",
                        event_id="event-3",
                        site_id="site-a",
                        property_id=202,
                        received_at="2026-03-31T10:00:02+00:00",
                        raw_payload_hash="hash-3",
                        payload_json='{"id":202}',
                        publish_context_json="",
                        gohighlevel_access_token="",
                        max_attempts=1,
                        available_at="2026-03-31T10:00:02+00:00",
                        created_at="2026-03-31T10:00:02+00:00",
                    )
                )

                first_claim = repository.claim_next_ready_job(
                    worker_id="worker-1",
                    lease_expires_at="2026-03-31T10:05:00+00:00",
                    now="2026-03-31T10:00:03+00:00",
                )
                second_claim = repository.claim_next_ready_job(
                    worker_id="worker-2",
                    lease_expires_at="2026-03-31T10:05:00+00:00",
                    now="2026-03-31T10:00:03+00:00",
                )

        self.assertIsNotNone(first_claim)
        self.assertIsNotNone(second_claim)
        self.assertEqual(first_claim.job_id, "job-1")
        self.assertEqual(first_claim.property_id, 101)
        self.assertEqual(second_claim.job_id, "job-3")
        self.assertEqual(second_claim.property_id, 202)


class PropertyInfoServiceTests(unittest.TestCase):
    def _build_service(
        self,
        workspace_dir: Path,
        *,
        social_publishing_enabled: bool = True,
    ) -> DefaultPropertyInfoService:
        return DefaultPropertyInfoService(
            workspace_dir,
            unit_of_work_factory=build_unit_of_work_factory(workspace_dir),
            property_url_template="https://{site_id}/property/{slug}",
            property_url_tracking_params={},
            social_publishing_enabled=social_publishing_enabled,
        )

    def _materialise_completed_artifacts(
        self,
        *,
        workspace_dir: Path,
        site_id: str,
        property_item: Property,
        location_id: str,
    ) -> None:
        storage_paths = resolve_site_storage_layout(workspace_dir, site_id)
        selected_dir = storage_paths.filtered_images_root / property_item.slug / "selected_photos"
        selected_dir.mkdir(parents=True, exist_ok=True)
        selected_image_path = selected_dir / "primary.jpg"
        selected_image_path.write_bytes(b"image")
        storage_paths.reels_root.mkdir(parents=True, exist_ok=True)
        storage_paths.generated_posters_root.mkdir(parents=True, exist_ok=True)
        manifest_path = storage_paths.reels_root / f"{property_item.slug}-reel.json"
        video_path = storage_paths.reels_root / f"{property_item.slug}-reel.mp4"
        poster_path = storage_paths.generated_posters_root / f"{property_item.slug}-poster.jpg"
        manifest_path.write_text("{}", encoding="utf-8")
        video_path.write_bytes(b"video")
        poster_path.write_bytes(b"poster")

        with PropertyPipelineRepository(workspace_dir / DATABASE_FILENAME, workspace_dir) as repository:
            repository.save_property_images(
                property_item,
                selected_dir,
                [(1, property_item.featured_image_url or "https://example.com/image.jpg", selected_image_path)],
                site_id=site_id,
            )
            repository.save_local_artifacts(
                site_id=site_id,
                source_property_id=property_item.id,
                manifest_path=manifest_path,
                video_path=video_path,
            )
            repository.update_social_publish_status(
                site_id=site_id,
                source_property_id=property_item.id,
                status="published",
                details={
                    "aggregate_status": "published",
                    "desired_platforms": ["tiktok"],
                    "successful_platforms": ["tiktok"],
                    "platform_results": {
                        "tiktok": {
                            "platform": "tiktok",
                            "outcome": "published",
                            "post_id": "post-1",
                            "post_status": "published",
                        }
                    },
                },
                last_published_location_id=location_id,
            )

    def test_identical_payload_and_target_becomes_noop_after_completed_publish(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            service = self._build_service(workspace_dir)
            job = build_job()
            first_context = service.ingest_property(job)
            self._materialise_completed_artifacts(
                workspace_dir=workspace_dir,
                site_id="site-a",
                property_item=first_context.property,
                location_id="location-a",
            )

            second_context = service.ingest_property(job)

        self.assertFalse(first_context.is_noop)
        self.assertTrue(second_context.is_noop)
        self.assertFalse(second_context.requires_render)
        self.assertFalse(second_context.requires_external_publish)

    def test_disabled_social_publishing_keeps_pipeline_local_only(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            service = self._build_service(
                workspace_dir,
                social_publishing_enabled=False,
            )

            context = service.ingest_property(build_job())

        self.assertIsNone(context.publish_context)
        self.assertEqual(context.publish_descriptions_by_platform, {})
        self.assertIsNone(context.publish_target_url)
        self.assertFalse(context.requires_external_publish)

    def test_changed_property_status_forces_new_render(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            service = self._build_service(workspace_dir)
            first_context = service.ingest_property(build_job())
            self._materialise_completed_artifacts(
                workspace_dir=workspace_dir,
                site_id="site-a",
                property_item=first_context.property,
                location_id="location-a",
            )

            changed_context = service.ingest_property(
                build_job(payload=build_sample_payload(property_status="Sold"))
            )

        self.assertFalse(changed_context.is_noop)
        self.assertTrue(changed_context.requires_render)
        self.assertTrue(changed_context.requires_external_publish)

    def test_changed_location_reuses_local_reel_and_republishes(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            service = self._build_service(workspace_dir)
            first_context = service.ingest_property(build_job())
            self._materialise_completed_artifacts(
                workspace_dir=workspace_dir,
                site_id="site-a",
                property_item=first_context.property,
                location_id="location-a",
            )

            republish_context = service.ingest_property(
                build_job(location_id="location-b", access_token="token-b")
            )

        self.assertFalse(republish_context.is_noop)
        self.assertFalse(republish_context.requires_render)
        self.assertTrue(republish_context.requires_external_publish)
        self.assertIsNotNone(republish_context.existing_published_video)

    def test_ambiguous_social_publish_result_triggers_publish_retry(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            service = self._build_service(workspace_dir)
            first_context = service.ingest_property(build_job())
            self._materialise_completed_artifacts(
                workspace_dir=workspace_dir,
                site_id="site-a",
                property_item=first_context.property,
                location_id="location-a",
            )

            with PropertyPipelineRepository(workspace_dir / DATABASE_FILENAME, workspace_dir) as repository:
                repository.update_social_publish_status(
                    site_id="site-a",
                    source_property_id=first_context.property.id,
                    status="published",
                    details={"message": "Created Post", "post_id": None, "post_status": None},
                    last_published_location_id="location-a",
                )

            retry_context = service.ingest_property(build_job())

        self.assertFalse(retry_context.is_noop)
        self.assertFalse(retry_context.requires_render)
        self.assertTrue(retry_context.requires_external_publish)
        self.assertIsNotNone(retry_context.existing_published_video)

    def test_created_social_publish_result_is_treated_as_complete(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            service = self._build_service(workspace_dir)
            first_context = service.ingest_property(build_job())
            self._materialise_completed_artifacts(
                workspace_dir=workspace_dir,
                site_id="site-a",
                property_item=first_context.property,
                location_id="location-a",
            )

            with PropertyPipelineRepository(workspace_dir / DATABASE_FILENAME, workspace_dir) as repository:
                repository.update_social_publish_status(
                    site_id="site-a",
                    source_property_id=first_context.property.id,
                    status="published",
                    details={
                        "message": "Created Post",
                        "post_id": None,
                        "post_status": "created",
                        "trace_id": "3629e807-81db-4a8c-9b73-34b11280e539",
                    },
                    last_published_location_id="location-a",
                )

            second_context = service.ingest_property(build_job())

        self.assertTrue(second_context.is_noop)
        self.assertFalse(second_context.requires_render)
        self.assertFalse(second_context.requires_external_publish)

    def test_partial_social_publish_retries_only_pending_platforms(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            service = self._build_service(workspace_dir)
            first_context = service.ingest_property(
                build_job(platforms=("tiktok", "instagram"))
            )
            self._materialise_completed_artifacts(
                workspace_dir=workspace_dir,
                site_id="site-a",
                property_item=first_context.property,
                location_id="location-a",
            )

            with PropertyPipelineRepository(workspace_dir / DATABASE_FILENAME, workspace_dir) as repository:
                repository.update_social_publish_status(
                    site_id="site-a",
                    source_property_id=first_context.property.id,
                    status="partial",
                    details={
                        "aggregate_status": "partial",
                        "desired_platforms": ["tiktok", "instagram"],
                        "successful_platforms": ["tiktok"],
                        "platform_results": {
                            "tiktok": {
                                "platform": "tiktok",
                                "outcome": "published",
                                "post_id": "post-1",
                                "post_status": "published",
                            },
                            "instagram": {
                                "platform": "instagram",
                                "outcome": "skipped_missing_account",
                                "message": "No connected instagram account was found.",
                            },
                        },
                    },
                    last_published_location_id="location-a",
                )

            retry_context = service.ingest_property(
                build_job(platforms=("tiktok", "instagram"))
            )

        self.assertFalse(retry_context.is_noop)
        self.assertFalse(retry_context.requires_render)
        self.assertTrue(retry_context.requires_external_publish)
        self.assertEqual(retry_context.pending_publish_platforms, ("instagram",))
        self.assertIsNotNone(retry_context.existing_published_video)

    def test_changed_property_features_force_new_render(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            service = self._build_service(workspace_dir)
            first_context = service.ingest_property(build_job())
            self._materialise_completed_artifacts(
                workspace_dir=workspace_dir,
                site_id="site-a",
                property_item=first_context.property,
                location_id="location-a",
            )

            changed_context = service.ingest_property(
                build_job(
                    payload=build_sample_payload(
                        property_features=[
                            "Private patio",
                            "Open-plan kitchen",
                            "Underfloor heating",
                        ]
                    )
                )
            )

        self.assertFalse(changed_context.is_noop)
        self.assertTrue(changed_context.requires_render)
        self.assertTrue(changed_context.requires_external_publish)

    def test_changed_normalized_field_forces_new_render(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            service = self._build_service(workspace_dir)
            first_context = service.ingest_property(build_job())
            self._materialise_completed_artifacts(
                workspace_dir=workspace_dir,
                site_id="site-a",
                property_item=first_context.property,
                location_id="location-a",
            )

            changed_payload = build_sample_payload()
            changed_payload["price_term"] = "per month"
            changed_context = service.ingest_property(build_job(payload=changed_payload))

        self.assertFalse(changed_context.is_noop)
        self.assertTrue(changed_context.requires_render)
        self.assertTrue(changed_context.requires_external_publish)

    def test_raw_gohighlevel_token_is_persisted_only_in_job_queue_token_column(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            acceptance_service = WebhookAcceptanceService(
                unit_of_work_factory=build_unit_of_work_factory(workspace_dir),
                job_max_attempts=2,
            )
            job = build_job(access_token="token-keep-out")
            acceptance_service.accept_delivery(
                site_id=job.site_id,
                property_id=job.property_id,
                raw_payload_hash=job.raw_payload_hash,
                payload=job.payload,
                publish_context=job.publish_context,
            )

            with PropertyJobRepository(workspace_dir / DATABASE_FILENAME) as repository:
                jobs = repository.list_jobs_for_property(site_id="site-a", property_id=170800)

        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].gohighlevel_access_token, "token-keep-out")
        self.assertNotIn('"access_token"', jobs[0].publish_context_json)


class ScriptedVideoArtifactRepositoryTests(unittest.TestCase):
    def test_save_and_get_scripted_video_artifact(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            database_path = workspace_dir / DATABASE_FILENAME
            with ScriptedVideoArtifactRepository(database_path) as repository:
                repository.save_artifact(
                    ScriptedVideoArtifactRecord(
                        render_id="render-1",
                        site_id="site-a",
                        source_property_id=170800,
                        property_slug="sample-property",
                        render_profile="for_sale_reel",
                        status="rendered",
                        request_manifest_json='{"title":"Sample"}',
                        request_manifest_path="generated_media/site-a/scripted_videos/sample-property/render-1/request-manifest.json",
                        resolved_manifest_path="generated_media/site-a/scripted_videos/sample-property/render-1/resolved-manifest.json",
                        media_path="generated_media/site-a/scripted_videos/sample-property/render-1/video.mp4",
                        error_message="",
                        created_at="",
                        updated_at="",
                    )
                )

                stored = repository.get_artifact("render-1")
                by_property = repository.list_artifacts_for_property(
                    site_id="site-a",
                    source_property_id=170800,
                )

        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.status, "rendered")
        self.assertEqual(stored.media_path, "generated_media/site-a/scripted_videos/sample-property/render-1/video.mp4")
        self.assertEqual(len(by_property), 1)


class WorkflowPersistenceTests(unittest.TestCase):
    def test_local_media_publish_creates_revision_and_outbox_event(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            service = DefaultPropertyInfoService(
                workspace_dir,
                unit_of_work_factory=build_unit_of_work_factory(workspace_dir),
                property_url_template="https://{site_id}/property/{slug}",
                property_url_tracking_params={},
                social_publishing_enabled=True,
            )
            context = service.ingest_property(build_job())
            staging_dir = workspace_dir / "staging"
            staging_dir.mkdir(parents=True, exist_ok=True)
            staged_manifest_path = staging_dir / "sample-property-reel.json"
            staged_media_path = staging_dir / "sample-property-reel.mp4"
            staged_poster_path = staging_dir / "sample-property-poster.jpg"
            staged_manifest_path.write_text("{}", encoding="utf-8")
            staged_media_path.write_bytes(b"video")
            staged_poster_path.write_bytes(b"poster")

            publisher = FileSystemMediaPublisher(
                unit_of_work_factory=build_unit_of_work_factory(workspace_dir),
            )
            published_media = publisher.publish_media(
                context,
                RenderedMediaArtifact(
                    staging_dir=staging_dir,
                    media_path=staged_media_path,
                    metadata_path=staged_manifest_path,
                    revision_id="revision-1",
                ),
            )

            with PropertyPipelineRepository(workspace_dir / DATABASE_FILENAME, workspace_dir) as repository:
                state = repository.get_property_pipeline_state(
                    site_id=context.site_id,
                    source_property_id=context.property.id,
                )
            with MediaRevisionRepository(workspace_dir / DATABASE_FILENAME) as revision_repository:
                revisions = revision_repository.list_media_revisions(
                    site_id=context.site_id,
                    source_property_id=context.property.id,
                )
            with OutboxEventRepository(workspace_dir / DATABASE_FILENAME) as outbox_repository:
                events = outbox_repository.list_events(
                    site_id=context.site_id,
                    source_property_id=context.property.id,
                )
            poster_exists = (
                workspace_dir
                / "generated_media"
                / context.storage_paths.safe_site_dir
                / "posters"
                / "sample-property-poster.jpg"
            ).exists()
            staging_exists = staging_dir.exists()

        self.assertIsNotNone(state)
        assert state is not None
        self.assertEqual(state.workflow_state, "rendered")
        self.assertEqual(state.current_revision_id, "revision-1")
        self.assertEqual(published_media.revision_id, "revision-1")
        self.assertEqual(len(revisions), 1)
        self.assertEqual(revisions[0].revision_id, "revision-1")
        self.assertEqual(revisions[0].workflow_state, "rendered")
        self.assertEqual(events[-1].event_type, "media_rendered")
        self.assertEqual(events[-1].payload["revision_id"], "revision-1")
        self.assertTrue(poster_exists)
        self.assertFalse(staging_exists)

    def test_local_media_publish_keeps_staging_when_cleanup_mode_is_none(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            service = DefaultPropertyInfoService(
                workspace_dir,
                unit_of_work_factory=build_unit_of_work_factory(workspace_dir),
                property_url_template="https://{site_id}/property/{slug}",
                property_url_tracking_params={},
                social_publishing_enabled=True,
            )
            context = service.ingest_property(build_job())
            staging_dir = workspace_dir / "staging"
            staging_dir.mkdir(parents=True, exist_ok=True)
            staged_manifest_path = staging_dir / "sample-property-reel.json"
            staged_media_path = staging_dir / "sample-property-reel.mp4"
            staged_poster_path = staging_dir / "sample-property-poster.jpg"
            staged_manifest_path.write_text("{}", encoding="utf-8")
            staged_media_path.write_bytes(b"video")
            staged_poster_path.write_bytes(b"poster")

            publisher = FileSystemMediaPublisher(
                unit_of_work_factory=build_unit_of_work_factory(workspace_dir),
                cleanup_temporary_files=False,
            )
            publisher.publish_media(
                context,
                RenderedMediaArtifact(
                    staging_dir=staging_dir,
                    media_path=staged_media_path,
                    metadata_path=staged_manifest_path,
                    revision_id="revision-1",
                ),
            )

            staging_exists = staging_dir.exists()

        self.assertTrue(staging_exists)

    def test_local_media_publish_requires_poster_for_reel_artifacts(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            service = DefaultPropertyInfoService(
                workspace_dir,
                unit_of_work_factory=build_unit_of_work_factory(workspace_dir),
                property_url_template="https://{site_id}/property/{slug}",
                property_url_tracking_params={},
                social_publishing_enabled=True,
            )
            context = service.ingest_property(build_job())
            staging_dir = workspace_dir / "staging"
            staging_dir.mkdir(parents=True, exist_ok=True)
            staged_manifest_path = staging_dir / "sample-property-reel.json"
            staged_media_path = staging_dir / "sample-property-reel.mp4"
            staged_manifest_path.write_text("{}", encoding="utf-8")
            staged_media_path.write_bytes(b"video")

            publisher = FileSystemMediaPublisher(
                unit_of_work_factory=build_unit_of_work_factory(workspace_dir),
            )

            with self.assertRaises(ValidationError) as error_context:
                publisher.publish_media(
                    context,
                    RenderedMediaArtifact(
                        staging_dir=staging_dir,
                        media_path=staged_media_path,
                        metadata_path=staged_manifest_path,
                        revision_id="revision-1",
                    ),
                )

        self.assertEqual(error_context.exception.code, "POSTER_REQUIRED")

    def test_media_preparation_cleanup_removes_selected_dir_when_flag_is_enabled(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            service = DefaultPropertyInfoService(
                workspace_dir,
                unit_of_work_factory=build_unit_of_work_factory(workspace_dir),
                property_url_template="https://{site_id}/property/{slug}",
                property_url_tracking_params={},
                social_publishing_enabled=True,
            )
            context = service.ingest_property(build_job())
            selected_dir = context.storage_paths.filtered_images_root / context.property.slug / "selected_photos"
            selected_dir.mkdir(parents=True, exist_ok=True)
            (selected_dir / "primary.jpg").write_bytes(b"image")

            preparation_service = DefaultMediaPreparationService(
                workspace_dir,
                unit_of_work_factory=build_unit_of_work_factory(workspace_dir),
                cleanup_selected_photos=True,
            )
            preparation_service.cleanup_prepared_assets(
                context,
                PreparedMediaAssets(
                    selected_dir=selected_dir,
                    selected_photo_paths=(selected_dir / "primary.jpg",),
                    downloaded_images=(),
                    primary_image_path=selected_dir / "primary.jpg",
                ),
            )

            selected_dir_exists = selected_dir.exists()

        self.assertFalse(selected_dir_exists)

    def test_missing_local_poster_forces_rerender(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            service = DefaultPropertyInfoService(
                workspace_dir,
                unit_of_work_factory=build_unit_of_work_factory(workspace_dir),
                property_url_template="https://{site_id}/property/{slug}",
                property_url_tracking_params={},
                social_publishing_enabled=True,
            )
            first_context = service.ingest_property(build_job())
            storage_paths = resolve_site_storage_layout(workspace_dir, "site-a")
            selected_dir = storage_paths.filtered_images_root / first_context.property.slug / "selected_photos"
            selected_dir.mkdir(parents=True, exist_ok=True)
            selected_image_path = selected_dir / "primary.jpg"
            selected_image_path.write_bytes(b"image")
            storage_paths.reels_root.mkdir(parents=True, exist_ok=True)
            storage_paths.generated_posters_root.mkdir(parents=True, exist_ok=True)
            manifest_path = storage_paths.reels_root / f"{first_context.property.slug}-reel.json"
            video_path = storage_paths.reels_root / f"{first_context.property.slug}-reel.mp4"
            poster_path = storage_paths.generated_posters_root / f"{first_context.property.slug}-poster.jpg"
            manifest_path.write_text("{}", encoding="utf-8")
            video_path.write_bytes(b"video")
            poster_path.write_bytes(b"poster")

            with PropertyPipelineRepository(workspace_dir / DATABASE_FILENAME, workspace_dir) as repository:
                repository.save_property_images(
                    first_context.property,
                    selected_dir,
                    [
                        (
                            1,
                            first_context.property.featured_image_url or "https://example.com/image.jpg",
                            selected_image_path,
                        )
                    ],
                    site_id="site-a",
                )
                repository.save_local_artifacts(
                    site_id="site-a",
                    source_property_id=first_context.property.id,
                    manifest_path=manifest_path,
                    video_path=video_path,
                )
                repository.update_social_publish_status(
                    site_id="site-a",
                    source_property_id=first_context.property.id,
                    status="published",
                    details={
                        "aggregate_status": "published",
                        "desired_platforms": ["tiktok"],
                        "successful_platforms": ["tiktok"],
                        "platform_results": {
                            "tiktok": {
                                "platform": "tiktok",
                                "outcome": "published",
                                "post_id": "post-1",
                                "post_status": "published",
                            }
                        },
                    },
                    last_published_location_id="location-a",
                )
            poster_path = (
                first_context.storage_paths.generated_posters_root
                / f"{first_context.property.slug}-poster.jpg"
            )
            poster_path.unlink()

            rerender_context = service.ingest_property(build_job())

        self.assertFalse(rerender_context.is_noop)
        self.assertTrue(rerender_context.requires_render)

    def test_readiness_report_exposes_optional_capabilities_without_blocking_core(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            assets_dir = workspace_dir / "assets" / "music"
            assets_dir.mkdir(parents=True, exist_ok=True)
            (assets_dir / "ncs-music.mp3").write_bytes(b"audio")
            with patch(
                "services.webhook_transport.operations.resolve_ffmpeg_binary",
                return_value=workspace_dir / "ffmpeg.exe",
            ):
                readiness = build_readiness_report(
                    workspace_dir,
                    site_secrets={},
                    worker_count=1,
                    security_disabled=True,
                )

        self.assertTrue(readiness["ready"])
        self.assertFalse(readiness["production_ready"])
        self.assertEqual(readiness["ready"], readiness["capabilities"]["core"]["ready"])
        self.assertTrue(readiness["checks"]["background_audio_available"])
        self.assertIn("ai_photo_selection", readiness["capabilities"])
        self.assertIsInstance(readiness["capabilities"]["ai_photo_selection"]["ready"], bool)
        self.assertGreaterEqual(len(readiness["warnings"]), 1)

    def test_readiness_report_requires_effective_site_secret_when_security_is_enabled(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            assets_dir = workspace_dir / "assets" / "music"
            assets_dir.mkdir(parents=True, exist_ok=True)
            (assets_dir / "ncs-music.mp3").write_bytes(b"audio")
            with patch(
                "services.webhook_transport.operations.resolve_ffmpeg_binary",
                return_value=workspace_dir / "ffmpeg.exe",
            ):
                readiness = build_readiness_report(
                    workspace_dir,
                    site_secrets={"site-a": "change-me"},
                    worker_count=1,
                    security_disabled=False,
                )

        self.assertFalse(readiness["ready"])
        self.assertFalse(readiness["production_ready"])
        self.assertFalse(readiness["checks"]["site_secrets_effective"])
        self.assertTrue(
            any(
                failure.get("check") == "site_secrets_configured"
                for failure in readiness["failures"]
                if isinstance(failure, dict)
            )
        )

    def test_readiness_report_treats_placeholder_gemini_key_as_not_configured(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            assets_dir = workspace_dir / "assets" / "music"
            assets_dir.mkdir(parents=True, exist_ok=True)
            (assets_dir / "ncs-music.mp3").write_bytes(b"audio")
            with (
                patch(
                    "services.webhook_transport.operations.resolve_ffmpeg_binary",
                    return_value=workspace_dir / "ffmpeg.exe",
                ),
                patch("services.webhook_transport.operations.GEMINI_API_KEY", "replace-me"),
                patch("services.webhook_transport.operations.GEMINI_MODEL", "gemini-2.5-flash"),
            ):
                readiness = build_readiness_report(
                    workspace_dir,
                    site_secrets={"site-a": "secret-a"},
                    worker_count=1,
                    security_disabled=False,
                )

        self.assertFalse(readiness["capabilities"]["ai_photo_selection"]["ready"])


class MediaPlanningTests(unittest.TestCase):
    def test_normalize_listing_lifecycle_accepts_new_state_variants(self) -> None:
        self.assertEqual(normalize_listing_lifecycle("For Sale"), "for_sale")
        self.assertEqual(normalize_listing_lifecycle("to-let"), "to_let")
        self.assertEqual(normalize_listing_lifecycle("sale_agreed"), "sale_agreed")
        self.assertEqual(normalize_listing_lifecycle("Sold"), "sold")
        self.assertEqual(normalize_listing_lifecycle("let agreed"), "let_agreed")
        self.assertEqual(normalize_listing_lifecycle("LET"), "let")

    def test_build_media_delivery_plan_uses_status_reel_for_closing_states(self) -> None:
        property_item = Property.from_api_payload(
            build_sample_payload(property_status="Let Agreed")
        )

        delivery_plan = build_media_delivery_plan(property_item)

        self.assertEqual(delivery_plan.artifact_kind, "reel_video")
        self.assertEqual(delivery_plan.asset_strategy, "primary_only")
        self.assertEqual(delivery_plan.social_post_type, "reel")
        self.assertEqual(delivery_plan.render_profile, "let_agreed_status_reel")
        self.assertEqual(delivery_plan.banner_text, "LET AGREED")
        self.assertEqual(delivery_plan.price_display_text, "")

    def test_build_media_delivery_plan_keeps_full_reel_for_to_let(self) -> None:
        payload = build_sample_payload(property_status="To Let")
        payload["price"] = "1750"
        payload["price_term"] = "per month"
        property_item = Property.from_api_payload(payload)

        delivery_plan = build_media_delivery_plan(property_item)

        self.assertEqual(delivery_plan.artifact_kind, "reel_video")
        self.assertEqual(delivery_plan.asset_strategy, "curated_selection")
        self.assertEqual(delivery_plan.social_post_type, "reel")
        self.assertEqual(delivery_plan.render_profile, "to_let_reel")
        self.assertEqual(delivery_plan.price_display_text, "€1,750 per month")


class WebhookTransportTests(unittest.TestCase):
    @staticmethod
    def _save_property_for_scripted_render(
        *,
        workspace_dir: Path,
        site_id: str = "site-a",
        property_id: int = 170800,
        slug: str = "sample-property",
    ) -> None:
        property_item = Property(
            id=property_id,
            slug=slug,
            title="46 Example Street, Dublin 4",
            property_status="For Sale",
        )
        with PropertyPipelineRepository(workspace_dir / DATABASE_FILENAME, workspace_dir) as repository:
            repository.save_property_data(
                property_item,
                site_id=site_id,
            )

    @staticmethod
    def _build_scripted_render_payload(
        slide_path: Path,
        *,
        render_settings: dict[str, object] | None = None,
    ) -> dict[str, object]:
        payload: dict[str, object] = {
            "site_id": "site-a",
            "source_property_id": 170800,
            "title": "46 Example Street, Dublin 4",
            "property_status": "For Sale",
            "slides": [
                {
                    "image_path": str(slide_path),
                    "caption": "Bright living room.",
                }
            ],
        }
        if render_settings is not None:
            payload["render_settings"] = render_settings
        return payload

    def _build_client(
        self,
        dispatcher: RecordingDispatcher | None = None,
        *,
        host: str = "127.0.0.1",
        allowed_hosts: tuple[str, ...] = ("testserver",),
        security_disabled: bool = False,
        enable_docs: bool = False,
        site_secrets: dict[str, str] | None = None,
    ) -> tuple[TestClient, RecordingDispatcher]:
        active_dispatcher = dispatcher or RecordingDispatcher()
        workspace_dir = TEST_TEMP_ROOT / uuid4().hex
        workspace_dir.mkdir(parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, workspace_dir, True)
        application = WordPressWebhookApplication(
            workspace_dir=workspace_dir,
            dispatcher=active_dispatcher,
            host=host,
            allowed_hosts=allowed_hosts,
            site_secrets=site_secrets or {"site-a": "secret-a"},
            security_disabled=security_disabled,
            enable_docs=enable_docs,
            worker_count=1,
        )
        app = create_fastapi_app(application=application)
        startup_patch = patch("services.webhook_transport.server.run_startup_checks", return_value={"ready": True})
        readiness_patch = patch(
            "services.webhook_transport.server.build_readiness_report",
            return_value={"ready": True, "checks": {}, "errors": []},
        )
        startup_patch.start()
        readiness_patch.start()
        self.addCleanup(startup_patch.stop)
        self.addCleanup(readiness_patch.stop)
        return TestClient(app), active_dispatcher

    def test_docs_are_available_when_running_on_localhost(self) -> None:
        client, _ = self._build_client(host="127.0.0.1")

        with client:
            docs_response = client.get("/docs")
            openapi_response = client.get("/openapi.json")

        self.assertEqual(docs_response.status_code, 200)
        self.assertIn("Swagger UI", docs_response.text)
        self.assertEqual(openapi_response.status_code, 200)
        self.assertEqual(openapi_response.json()["info"]["title"], "CPIHED Webhook API")

    def test_docs_are_disabled_when_not_running_on_localhost(self) -> None:
        client, _ = self._build_client(host="0.0.0.0")

        with client:
            docs_response = client.get("/docs")
            openapi_response = client.get("/openapi.json")

        self.assertEqual(docs_response.status_code, 404)
        self.assertEqual(openapi_response.status_code, 404)

    def test_docs_can_be_enabled_explicitly_for_lan_hosts(self) -> None:
        client, _ = self._build_client(host="0.0.0.0", enable_docs=True)

        with client:
            docs_response = client.get("/docs")
            openapi_response = client.get("/openapi.json")

        self.assertEqual(docs_response.status_code, 200)
        self.assertIn("Swagger UI", docs_response.text)
        self.assertEqual(openapi_response.status_code, 200)

    def test_openapi_includes_webhook_examples_and_header_docs(self) -> None:
        client, _ = self._build_client(host="127.0.0.1")

        with client:
            openapi_schema = client.get("/openapi.json").json()

        operation = openapi_schema["paths"]["/webhooks/wordpress/property"]["post"]
        parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
        request_examples = operation["requestBody"]["content"]["application/json"]["examples"]
        accepted_example = operation["responses"]["202"]["content"]["application/json"]["example"]

        self.assertIn("postman_collection", request_examples)
        self.assertEqual(request_examples["postman_collection"]["value"]["id"], 173637)
        self.assertEqual(parameters["X-GoHighLevel-Location-ID"]["example"], "v8H1XNB3YCQmVHRhqDoM")
        self.assertIn("X-GHL-Location-Id", parameters["X-GoHighLevel-Location-ID"]["description"])
        self.assertEqual(accepted_example["status"], "accepted")
        self.assertEqual(accepted_example["site_id"], "ckp.ie")

    def test_openapi_includes_scripted_render_examples(self) -> None:
        client, _ = self._build_client(host="127.0.0.1")

        with client:
            openapi_schema = client.get("/openapi.json").json()

        operation = openapi_schema["paths"]["/videos/scripted/render"]["post"]
        request_examples = operation["requestBody"]["content"]["application/json"]["examples"]
        request_schema = operation["requestBody"]["content"]["application/json"]["schema"]
        response_example = operation["responses"]["201"]["content"]["application/json"]["example"]

        self.assertIn("image_path", request_examples)
        self.assertIn("sources", request_examples)
        self.assertEqual(request_examples["image_path"]["value"]["slides"][0]["image_path"], "uploads/slide-01.jpg")
        self.assertEqual(request_examples["sources"]["value"]["slides"][0]["sources"][0]["path"], "uploads/slide-01.jpg")
        self.assertIn("render_settings", request_examples["image_path"]["value"])
        self.assertEqual(
            request_examples["image_path"]["value"]["render_settings"]["footer_bottom_offset_px"],
            72,
        )
        self.assertIn("render_settings", request_schema["properties"])
        self.assertIn(
            "footer_bottom_offset_px",
            request_schema["properties"]["render_settings"]["properties"],
        )
        self.assertEqual(response_example["status"], "rendered")
        self.assertIn("generated_media/site-a/scripted_videos", response_example["video_path"])

    @staticmethod
    def _build_signed_headers(
        payload: dict[str, object] | list[dict[str, object]],
        *,
        site_id: str = "site-a",
        location_id: str = "location-a",
        access_token: str = "token-a",
        timestamp: str | None = None,
        include_site_header: bool = True,
        use_alt_ghl_headers: bool = False,
    ) -> dict[str, str]:
        body = json.dumps(payload).encode("utf-8")
        timestamp_value = str(int(time.time())) if timestamp is None else timestamp
        headers = {
            "Content-Type": "application/json",
            "X-WordPress-Timestamp": timestamp_value,
            "X-WordPress-Signature": build_signature(
                "secret-a",
                timestamp_value,
                site_id,
                location_id,
                access_token,
                body,
            ),
        }
        if include_site_header:
            headers["X-WordPress-Site-ID"] = site_id
        if use_alt_ghl_headers:
            headers["X-GHL-Location-Id"] = location_id
            headers["X-GHL-Token"] = access_token
        else:
            headers["X-GoHighLevel-Location-ID"] = location_id
            headers["X-GoHighLevel-Access-Token"] = access_token
        return headers

    def test_valid_signed_request_enqueues_job_with_publish_context(self) -> None:
        payload = build_sample_payload()
        client, dispatcher = self._build_client()
        request_body = json.dumps(payload)

        with client:
            response = client.post(
                "/webhooks/wordpress/property",
                content=request_body,
                headers=self._build_signed_headers(payload),
            )

        self.assertEqual(response.status_code, 202)
        response_payload = response.json()
        job_id = str(response_payload["job_id"])
        event_id = str(response_payload["event_id"])
        runtime = client.app.state.runtime
        with PropertyJobRepository(runtime.workspace_dir / DATABASE_FILENAME) as repository:
            job = repository.get_job(job_id)
        with WebhookDeliveryRepository(runtime.workspace_dir / DATABASE_FILENAME) as repository:
            event = repository.get_event(event_id)

        self.assertIsNotNone(job)
        self.assertIsNotNone(event)
        assert job is not None
        assert event is not None
        self.assertEqual(job.status, "queued")
        self.assertEqual(event.status, "queued")
        self.assertIn('"location_id": "location-a"', job.publish_context_json)
        self.assertNotIn('"access_token": "token-a"', job.publish_context_json)
        self.assertEqual(job.gohighlevel_access_token, "token-a")
        self.assertEqual(
            json.loads(job.publish_context_json)["platforms"],
            list(SOCIAL_PUBLISHING_DEFAULT_PLATFORMS),
        )

    def test_valid_signed_request_persists_application_and_audit_logs(self) -> None:
        payload = build_sample_payload()
        client, _ = self._build_client()
        request_body = json.dumps(payload)

        with client:
            response = client.post(
                "/webhooks/wordpress/property",
                content=request_body,
                headers=self._build_signed_headers(payload),
            )

        self.assertEqual(response.status_code, 202)
        runtime = client.app.state.runtime
        log_dir = runtime.workspace_dir / PERSISTENT_LOG_DIRECTORY
        application_log = log_dir / "application.log"
        audit_log = log_dir / "audit.jsonl"

        self.assertTrue(application_log.exists())
        self.assertTrue(audit_log.exists())

        application_log_text = application_log.read_text(encoding="utf-8")
        self.assertIn("WEBHOOK ACCEPTED", application_log_text)

        audit_entries = [
            json.loads(line)
            for line in audit_log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        request_entry = next(
            entry
            for entry in audit_entries
            if entry.get("event_type") == "http.request"
            and entry.get("path") == "/webhooks/wordpress/property"
        )
        response_entry = next(
            entry
            for entry in audit_entries
            if entry.get("event_type") == "http.response"
            and entry.get("path") == "/webhooks/wordpress/property"
            and entry.get("status_code") == 202
        )
        accepted_entry = next(
            entry
            for entry in audit_entries
            if entry.get("event_type") == "webhook.accepted"
        )
        request_headers = {
            str(key).lower(): value
            for key, value in request_entry["headers"].items()
        }

        self.assertEqual(
            request_headers["x-gohighlevel-access-token"],
            "<redacted>",
        )
        self.assertIn("46 Example Street, Dublin 4", request_entry["body"])
        self.assertEqual(response_entry["status_code"], 202)
        self.assertEqual(accepted_entry["site_id"], "site-a")

    def test_scripted_render_endpoint_renders_and_persists_separate_artifact(self) -> None:
        client, _ = self._build_client(security_disabled=True)
        runtime = client.app.state.runtime
        workspace_dir = runtime.workspace_dir
        self._save_property_for_scripted_render(workspace_dir=workspace_dir)
        slide_path = workspace_dir / "uploads" / "slide-01.jpg"
        slide_path.parent.mkdir(parents=True, exist_ok=True)
        slide_path.write_bytes(b"image")
        captured_template: dict[str, object] = {}

        def fake_prepare_reel_render_assets(base_dir, property_data, *, template=None, working_dir):
            captured_template["template"] = template
            prepared_dir = Path(working_dir).expanduser().resolve()
            prepared_dir.mkdir(parents=True, exist_ok=True)
            slide_working_path = prepared_dir / "slide_01.png"
            slide_working_path.write_bytes(b"slide")
            agent_path = prepared_dir / "agent.png"
            agent_path.write_bytes(b"agent")
            audio_path = prepared_dir / "audio.mp3"
            audio_path.write_bytes(b"audio")
            return PreparedReelAssets(
                working_dir=prepared_dir,
                slides=(
                    PreparedReelSlide(
                        original_path=property_data.selected_slides[0].image_path,
                        working_path=slide_working_path,
                        caption=property_data.selected_slides[0].caption,
                    ),
                ),
                cover_background_path=slide_working_path,
                cover_logo_path=None,
                agent_image_path=agent_path,
                ber_icon_path=None,
                background_audio_path=audio_path,
            )

        def fake_write_property_reel_manifest_from_data(
            base_dir,
            property_data,
            *,
            output_path=None,
            template=None,
            render_profile=None,
            prepared_assets=None,
            working_dir=None,
        ):
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "site_id": property_data.site_id,
                        "property_id": property_data.property_id,
                        "title": property_data.title,
                        "render_profile": render_profile,
                        "render_settings": {
                            "subtitle_font_size": template.subtitle_font_size if template is not None else None,
                            "footer_bottom_offset_px": (
                                template.footer_bottom_offset_px if template is not None else None
                            ),
                        },
                    }
                ),
                encoding="utf-8",
            )
            return path

        def fake_generate_property_reel_from_data(
            base_dir,
            property_data,
            *,
            output_path=None,
            template=None,
            prepared_assets=None,
            working_dir=None,
        ):
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"video")
            return path

        with (
            patch(
                "application.scripted_video_service.prepare_reel_render_assets",
                side_effect=fake_prepare_reel_render_assets,
            ),
            patch(
                "application.scripted_video_service.write_property_reel_manifest_from_data",
                side_effect=fake_write_property_reel_manifest_from_data,
            ),
            patch(
                "application.scripted_video_service.generate_property_reel_from_data",
                side_effect=fake_generate_property_reel_from_data,
            ),
            client,
        ):
            payload = self._build_scripted_render_payload(
                slide_path,
                render_settings={
                    "subtitle_font_size": 62,
                    "footer_bottom_offset_px": 88,
                },
            )
            response = client.post(
                "/videos/scripted/render",
                content=json.dumps(payload),
                headers={"Content-Type": "application/json"},
            )

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["status"], "rendered")
        video_path = workspace_dir / payload["video_path"]
        manifest_path = workspace_dir / payload["manifest_path"]
        request_manifest_path = workspace_dir / payload["request_manifest_path"]
        self.assertTrue(video_path.exists())
        self.assertTrue(manifest_path.exists())
        self.assertTrue(request_manifest_path.exists())
        self.assertIn("scripted_videos", payload["video_path"])
        self.assertNotIn("\\reels\\", payload["video_path"])
        self.assertIn("template", captured_template)
        assert isinstance(captured_template["template"], PropertyReelTemplate)
        self.assertEqual(captured_template["template"].subtitle_font_size, 62)
        self.assertEqual(captured_template["template"].footer_bottom_offset_px, 88)

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["render_profile"], "for_sale_reel")
        self.assertEqual(manifest["render_settings"]["subtitle_font_size"], 62)
        self.assertEqual(manifest["render_settings"]["footer_bottom_offset_px"], 88)

        with ScriptedVideoArtifactRepository(workspace_dir / DATABASE_FILENAME) as repository:
            record = repository.get_artifact(payload["render_id"])
        self.assertIsNotNone(record)
        assert record is not None
        self.assertEqual(record.status, "rendered")
        self.assertEqual(record.media_path, payload["video_path"])
        self.assertEqual(record.resolved_manifest_path, payload["manifest_path"])
        self.assertEqual(record.request_manifest_path, payload["request_manifest_path"])

        with PropertyPipelineRepository(workspace_dir / DATABASE_FILENAME, workspace_dir) as repository:
            state = repository.get_property_pipeline_state(site_id="site-a", source_property_id=170800)
        self.assertIsNone(state)

    def test_scripted_render_endpoint_returns_404_when_property_is_missing(self) -> None:
        client, _ = self._build_client(security_disabled=True)
        with client:
            response = client.post(
                "/videos/scripted/render",
                content=json.dumps(
                    {
                        "site_id": "site-a",
                        "source_property_id": 170800,
                        "title": "46 Example Street, Dublin 4",
                        "property_status": "For Sale",
                        "slides": [{"image_path": "uploads/slide-01.jpg"}],
                    }
                ),
                headers={"Content-Type": "application/json"},
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "PROPERTY_NOT_FOUND")

    def test_scripted_render_endpoint_rejects_missing_slides(self) -> None:
        client, _ = self._build_client(security_disabled=True)
        runtime = client.app.state.runtime
        self._save_property_for_scripted_render(workspace_dir=runtime.workspace_dir)

        with client:
            response = client.post(
                "/videos/scripted/render",
                content=json.dumps(
                    {
                        "site_id": "site-a",
                        "source_property_id": 170800,
                        "title": "46 Example Street, Dublin 4",
                        "property_status": "For Sale",
                    }
                ),
                headers={"Content-Type": "application/json"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "SLIDES_REQUIRED")

    def test_scripted_render_endpoint_rejects_multi_source_slides(self) -> None:
        client, _ = self._build_client(security_disabled=True)
        runtime = client.app.state.runtime
        workspace_dir = runtime.workspace_dir
        self._save_property_for_scripted_render(workspace_dir=workspace_dir)
        first_slide_path = workspace_dir / "uploads" / "slide-01.jpg"
        second_slide_path = workspace_dir / "uploads" / "slide-02.jpg"
        first_slide_path.parent.mkdir(parents=True, exist_ok=True)
        first_slide_path.write_bytes(b"image")
        second_slide_path.write_bytes(b"image")

        with client:
            response = client.post(
                "/videos/scripted/render",
                content=json.dumps(
                    {
                        "site_id": "site-a",
                        "source_property_id": 170800,
                        "title": "46 Example Street, Dublin 4",
                        "property_status": "For Sale",
                        "slides": [
                            {
                                "sources": [
                                    {"path": str(first_slide_path)},
                                    {"path": str(second_slide_path)},
                                ]
                            }
                        ],
                    }
                ),
                headers={"Content-Type": "application/json"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "COMPOSITE_SLIDE_NOT_SUPPORTED")

    def test_scripted_render_endpoint_rejects_slide_paths_outside_workspace(self) -> None:
        client, _ = self._build_client(security_disabled=True)
        runtime = client.app.state.runtime
        workspace_dir = runtime.workspace_dir
        self._save_property_for_scripted_render(workspace_dir=workspace_dir)
        outside_path = workspace_dir.parent / "outside-slide.jpg"
        outside_path.write_bytes(b"image")
        self.addCleanup(lambda: outside_path.unlink(missing_ok=True))

        with client:
            response = client.post(
                "/videos/scripted/render",
                content=json.dumps(self._build_scripted_render_payload(outside_path)),
                headers={"Content-Type": "application/json"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "INVALID_SLIDE_IMAGE_PATH")

    def test_scripted_render_endpoint_rejects_missing_slide_paths(self) -> None:
        client, _ = self._build_client(security_disabled=True)
        runtime = client.app.state.runtime
        workspace_dir = runtime.workspace_dir
        self._save_property_for_scripted_render(workspace_dir=workspace_dir)
        missing_path = workspace_dir / "uploads" / "missing-slide.jpg"

        with client:
            response = client.post(
                "/videos/scripted/render",
                content=json.dumps(self._build_scripted_render_payload(missing_path)),
                headers={"Content-Type": "application/json"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "INVALID_SLIDE_IMAGE_PATH")

    def test_missing_gohighlevel_headers_is_rejected(self) -> None:
        payload = build_sample_payload()
        client, _ = self._build_client()
        request_body = json.dumps(payload)

        with client:
            response = client.post(
                "/webhooks/wordpress/property",
                content=request_body,
                headers={
                    "Content-Type": "application/json",
                    "X-WordPress-Site-ID": "site-a",
                    "X-WordPress-Timestamp": "1700000000",
                    "X-WordPress-Signature": "invalid",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "MISSING_GHL_HEADERS")
        self.assertIn("hint", response.json())

    def test_tampering_with_location_id_breaks_signature_validation(self) -> None:
        payload = build_sample_payload()
        client, _ = self._build_client()
        headers = self._build_signed_headers(payload, location_id="location-a")
        headers["X-GoHighLevel-Location-ID"] = "location-b"
        request_body = json.dumps(payload)

        with client:
            response = client.post(
                "/webhooks/wordpress/property",
                content=request_body,
                headers=headers,
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["code"], "INVALID_WEBHOOK_CREDENTIALS")
        self.assertEqual(response.json()["error"], "Invalid webhook credentials.")
        self.assertNotIn("signature does not match", json.dumps(response.json()).lower())

    def test_health_endpoints_return_minimal_payloads(self) -> None:
        client, _ = self._build_client()

        with client:
            live_response = client.get("/health/live")
            ready_response = client.get("/health/ready")

        self.assertEqual(live_response.status_code, 200)
        self.assertEqual(live_response.json(), {"status": "ok"})
        self.assertEqual(ready_response.status_code, 200)
        self.assertEqual(ready_response.json(), {"status": "ready"})

    def test_allowed_hosts_rejects_unknown_host_headers(self) -> None:
        client, _ = self._build_client(allowed_hosts=("example.com",))

        with client:
            response = client.get(
                "/health/live",
                headers={"Host": "evil.example"},
            )

        self.assertEqual(response.status_code, 400)

    def test_dispatcher_not_accepting_returns_503(self) -> None:
        payload = build_sample_payload()
        client, _ = self._build_client(dispatcher=RejectingDispatcher())
        request_body = json.dumps(payload)

        with client:
            response = client.post(
                "/webhooks/wordpress/property",
                content=request_body,
                headers=self._build_signed_headers(payload),
            )

        self.assertEqual(response.status_code, 503)

    def test_security_disabled_accepts_ghl_headers_and_single_item_array_payload(self) -> None:
        payload = build_sample_payload()
        payload["link"] = "https://dev76.designbricks.ie/property/sample-property"
        payload["guid"] = {
            "rendered": "https://dev76.designbricks.ie/property/sample-property"
        }
        client, _ = self._build_client(security_disabled=True)
        request_body = json.dumps([payload])

        with client:
            response = client.post(
                "/webhooks/wordpress/property",
                content=request_body,
                headers={
                    "Content-Type": "application/json; charset=UTF-8",
                    "Accept": "application/json",
                    "X-GHL-Location-Id": "location-a",
                    "X-GHL-Token": "token-a",
                },
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["site_id"], "dev76.designbricks.ie")

    def test_signed_single_item_array_payload_can_infer_site_id_without_header(self) -> None:
        payload = build_sample_payload()
        payload["link"] = "https://site-a/property/sample-property"
        payload["guid"] = {"rendered": "https://site-a/property/sample-property"}
        client, _ = self._build_client()
        request_body = json.dumps([payload])

        with client:
            response = client.post(
                "/webhooks/wordpress/property",
                content=request_body,
                headers=self._build_signed_headers(
                    [payload],
                    include_site_header=False,
                    use_alt_ghl_headers=True,
                ),
            )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["site_id"], "site-a")

    def test_multi_item_array_payload_is_rejected(self) -> None:
        payload = build_sample_payload()
        client, _ = self._build_client(security_disabled=True)
        request_body = json.dumps([payload, payload])

        with client:
            response = client.post(
                "/webhooks/wordpress/property",
                content=request_body,
                headers={
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-GHL-Location-Id": "location-a",
                    "X-GHL-Token": "token-a",
                },
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "Webhook payload array must contain exactly one JSON object.",
        )


class InvalidHttpRequestLoggingTests(unittest.TestCase):
    def test_tls_handshake_hint_is_descriptive(self) -> None:
        hint = infer_invalid_http_request_hint(b"\x16\x03\x01\x02\x00\x01\x00")

        self.assertIn("TLS handshake", hint)

    def test_http_preview_keeps_text_readable(self) -> None:
        preview = build_invalid_http_request_preview(b"GET /bad HTTP/1.1\r\nHost: example.com\r\n")

        self.assertIn("GET /bad HTTP/1.1", preview)
        self.assertIn("\\r\\n", preview)

    def test_invalid_http_request_warning_includes_client_and_hint(self) -> None:
        warning = format_invalid_http_request_warning(
            client=("10.0.0.5", 43122),
            data=b"\x16\x03\x01\x02\x00",
            parser_name="httptools",
            error=ValueError("bad framing"),
        )

        self.assertIn("INVALID HTTP REQUEST RECEIVED", warning)
        self.assertIn("10.0.0.5:43122", warning)
        self.assertIn("httptools", warning)
        self.assertIn("TLS handshake", warning)


class SqliteJobDispatcherTests(unittest.TestCase):
    def _build_dispatcher(
        self,
        workspace_dir: Path,
        *,
        handler,
        worker_count: int = 1,
        retry_backoff_seconds: float = 0.1,
        job_max_attempts: int = 2,
        poll_interval_seconds: float = 0.05,
        lease_seconds: int = 30,
    ) -> SqliteJobDispatcher:
        return SqliteJobDispatcher(
            handler=handler,
            unit_of_work_factory=build_unit_of_work_factory(workspace_dir),
            worker_count=worker_count,
            poll_interval_seconds=poll_interval_seconds,
            lease_seconds=lease_seconds,
            retry_backoff_seconds=retry_backoff_seconds,
            job_max_attempts=job_max_attempts,
        )

    def _acceptance_service(self, workspace_dir: Path, *, job_max_attempts: int = 2) -> WebhookAcceptanceService:
        return WebhookAcceptanceService(
            unit_of_work_factory=build_unit_of_work_factory(workspace_dir),
            job_max_attempts=job_max_attempts,
        )

    def test_acceptance_service_supersedes_older_queued_job_for_same_property(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            acceptance_service = self._acceptance_service(workspace_dir)
            first_job = build_job(event_id="event-1", access_token="token-first")
            second_job = build_job(event_id="event-2", access_token="token-second")

            first_delivery = acceptance_service.accept_delivery(
                site_id=first_job.site_id,
                property_id=first_job.property_id,
                raw_payload_hash=first_job.raw_payload_hash,
                payload=first_job.payload,
                publish_context=first_job.publish_context,
            )
            second_delivery = acceptance_service.accept_delivery(
                site_id=second_job.site_id,
                property_id=second_job.property_id,
                raw_payload_hash=second_job.raw_payload_hash,
                payload=second_job.payload,
                publish_context=second_job.publish_context,
            )

            with PropertyJobRepository(workspace_dir / DATABASE_FILENAME) as repository:
                jobs = repository.list_jobs_for_property(site_id="site-a", property_id=first_job.property_id)
            with WebhookDeliveryRepository(workspace_dir / DATABASE_FILENAME) as repository:
                first_event = repository.get_event(first_delivery.event_id)
                second_event = repository.get_event(second_delivery.event_id)

        self.assertEqual(len(jobs), 2)
        self.assertEqual(jobs[0].job_id, first_delivery.job_id)
        self.assertEqual(jobs[0].status, "superseded")
        self.assertEqual(jobs[0].superseded_by_job_id, second_delivery.job_id)
        self.assertEqual(jobs[0].publish_context_json, "")
        self.assertEqual(jobs[0].gohighlevel_access_token, "")
        self.assertEqual(jobs[1].job_id, second_delivery.job_id)
        self.assertEqual(jobs[1].status, "queued")
        self.assertNotIn('"access_token": "token-second"', jobs[1].publish_context_json)
        self.assertEqual(jobs[1].gohighlevel_access_token, "token-second")
        self.assertIsNotNone(first_event)
        self.assertIsNotNone(second_event)
        assert first_event is not None
        assert second_event is not None
        self.assertEqual(first_event.status, "superseded")
        self.assertEqual(second_event.status, "queued")

    def test_dispatcher_processes_queued_job_and_scrubs_publish_context(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            acceptance_service = self._acceptance_service(workspace_dir)
            delivery = acceptance_service.accept_delivery(
                site_id="site-a",
                property_id=170800,
                raw_payload_hash="hash",
                payload=build_sample_payload(),
                publish_context=SocialPublishContext(
                    provider="gohighlevel",
                    location_id="location-a",
                    access_token="token-persist-until-complete",
                    platforms=("tiktok",),
                ),
            )
            dispatcher = self._build_dispatcher(
                workspace_dir,
                handler=lambda job: object(),
            )

            dispatcher.start()
            try:
                self.assertTrue(dispatcher.wait_for_idle(timeout=5.0))
            finally:
                dispatcher.stop(timeout=1.0)

            with PropertyJobRepository(workspace_dir / DATABASE_FILENAME) as repository:
                job = repository.get_job(delivery.job_id)
            with WebhookDeliveryRepository(workspace_dir / DATABASE_FILENAME) as repository:
                event = repository.get_event(delivery.event_id)

        self.assertIsNotNone(job)
        self.assertIsNotNone(event)
        assert job is not None
        assert event is not None
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.publish_context_json, "")
        self.assertEqual(job.gohighlevel_access_token, "")
        self.assertIsNone(job.last_error)
        self.assertEqual(event.status, "completed")

    def test_transient_failure_retries_without_blocking_next_job(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            acceptance_service = self._acceptance_service(workspace_dir, job_max_attempts=2)
            first_delivery = acceptance_service.accept_delivery(
                site_id="site-a",
                property_id=170800,
                raw_payload_hash="hash-1",
                payload=build_sample_payload(property_id=170800),
                publish_context=SocialPublishContext(
                    provider="gohighlevel",
                    location_id="location-a",
                    access_token="token-first",
                    platforms=("tiktok",),
                ),
            )
            second_delivery = acceptance_service.accept_delivery(
                site_id="site-a",
                property_id=170801,
                raw_payload_hash="hash-2",
                payload=build_sample_payload(property_id=170801),
                publish_context=SocialPublishContext(
                    provider="gohighlevel",
                    location_id="location-a",
                    access_token="token-second",
                    platforms=("tiktok",),
                ),
            )
            completed_property_ids: list[int | None] = []

            def handler(job: PropertyVideoJob) -> object:
                if job.property_id == 170800:
                    raise TransientSocialPublishingError("temporary social outage")
                completed_property_ids.append(job.property_id)
                return object()

            dispatcher = self._build_dispatcher(
                workspace_dir,
                handler=handler,
                retry_backoff_seconds=0.1,
                job_max_attempts=2,
            )

            dispatcher.start()
            try:
                deadline = time.time() + 5.0
                while time.time() < deadline:
                    with PropertyJobRepository(workspace_dir / DATABASE_FILENAME) as repository:
                        retrying_job = repository.get_job(first_delivery.job_id)
                        successful_job = repository.get_job(second_delivery.job_id)
                    if (
                        retrying_job is not None
                        and successful_job is not None
                        and retrying_job.status == "failed"
                        and successful_job.status == "completed"
                    ):
                        break
                    time.sleep(0.05)
                self.assertTrue(dispatcher.wait_for_idle(timeout=5.0))
            finally:
                dispatcher.stop(timeout=1.0)

            with PropertyJobRepository(workspace_dir / DATABASE_FILENAME) as repository:
                first_job = repository.get_job(first_delivery.job_id)
                second_job = repository.get_job(second_delivery.job_id)
            with WebhookDeliveryRepository(workspace_dir / DATABASE_FILENAME) as repository:
                first_event = repository.get_event(first_delivery.event_id)
                second_event = repository.get_event(second_delivery.event_id)

        self.assertEqual(completed_property_ids, [170801])
        self.assertIsNotNone(first_job)
        self.assertIsNotNone(second_job)
        self.assertIsNotNone(first_event)
        self.assertIsNotNone(second_event)
        assert first_job is not None
        assert second_job is not None
        assert first_event is not None
        assert second_event is not None
        self.assertEqual(first_job.status, "failed")
        self.assertEqual(first_job.attempt_count, 2)
        self.assertEqual(first_job.publish_context_json, "")
        self.assertEqual(first_job.gohighlevel_access_token, "")
        self.assertIn("temporary social outage", first_job.last_error or "")
        self.assertEqual(second_job.status, "completed")
        self.assertEqual(second_job.gohighlevel_access_token, "")
        self.assertEqual(first_event.status, "failed")
        self.assertEqual(second_event.status, "completed")

    def test_dispatcher_recovers_expired_processing_job(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            acceptance_service = self._acceptance_service(workspace_dir)
            delivery = acceptance_service.accept_delivery(
                site_id="site-a",
                property_id=170800,
                raw_payload_hash="hash",
                payload=build_sample_payload(),
                publish_context=SocialPublishContext(
                    provider="gohighlevel",
                    location_id="location-a",
                    access_token="token-a",
                    platforms=("tiktok",),
                ),
            )
            with PropertyJobRepository(workspace_dir / DATABASE_FILENAME) as repository:
                repository.connection.execute(
                    """
                    UPDATE job_queue
                    SET status = 'processing',
                        attempt_count = 1,
                        worker_id = 'stale-worker',
                        lease_expires_at = '2000-01-01T00:00:00+00:00'
                    WHERE job_id = ?
                    """,
                    (delivery.job_id,),
                )

            dispatcher = self._build_dispatcher(
                workspace_dir,
                handler=lambda job: object(),
            )

            dispatcher.start()
            try:
                self.assertTrue(dispatcher.wait_for_idle(timeout=5.0))
            finally:
                dispatcher.stop(timeout=1.0)

            with PropertyJobRepository(workspace_dir / DATABASE_FILENAME) as repository:
                job = repository.get_job(delivery.job_id)
            with WebhookDeliveryRepository(workspace_dir / DATABASE_FILENAME) as repository:
                event = repository.get_event(delivery.event_id)

        self.assertIsNotNone(job)
        self.assertIsNotNone(event)
        assert job is not None
        assert event is not None
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.attempt_count, 2)
        self.assertEqual(event.status, "completed")


class RenderOverlayTests(unittest.TestCase):
    def test_overlay_filter_includes_ber_icon_overlay_when_present(self) -> None:
        property_data = PropertyRenderData(
            site_id="ckp.ie",
            property_id=170800,
            slug="sample-property",
            title="46 Example Street, Dublin 4",
            link="https://ckp.ie/property/sample-property",
            property_status="Sale Agreed",
            selected_image_dir=Path("images"),
            selected_image_paths=(),
            featured_image_url=None,
            bedrooms=3,
            bathrooms=2,
            ber_rating="B2",
            agent_name="Jane Doe",
            agent_photo_url=None,
            agent_email="jane@example.com",
            agent_mobile=None,
            agent_number="+353 1 234 5678",
            price="650000",
            property_type_label=None,
            property_area_label=None,
            property_county_label=None,
            eircode=None,
        )
        template = PropertyReelTemplate(subtitle_font_size=36)

        filter_text = build_overlay_filter(
            property_data,
            template,
            cover_caption="Bright open-plan living area.",
            slide_captions=("Bright open-plan living area.",),
            slide_duration=template.seconds_per_slide,
            ber_icon_label="ber_header_icon",
        )

        self.assertIn("[video_with_property_panels][ber_header_icon]overlay=", filter_text)
        self.assertIn("SALE AGREED", filter_text)
        self.assertIn("650\\,000", filter_text)

    def test_overlay_filter_places_status_as_header_text_above_price(self) -> None:
        property_data = PropertyRenderData(
            site_id="ckp.ie",
            property_id=170800,
            slug="sample-property",
            title="46 Example Street, Dublin 4",
            link="https://ckp.ie/property/sample-property",
            property_status="Sale Agreed",
            selected_image_dir=Path("images"),
            selected_image_paths=(),
            featured_image_url=None,
            bedrooms=3,
            bathrooms=2,
            ber_rating="B2",
            agent_name="Jane Doe",
            agent_photo_url=None,
            agent_email="jane@example.com",
            agent_mobile=None,
            agent_number="+353 1 234 5678",
            price="650000",
            property_type_label=None,
            property_area_label=None,
            property_county_label=None,
            eircode=None,
        )
        template = PropertyReelTemplate(subtitle_font_size=36)

        filter_text = build_overlay_filter(
            property_data,
            template,
            cover_caption="Bright open-plan living area.",
            slide_captions=("Bright open-plan living area.",),
            slide_duration=template.seconds_per_slide,
        )

        self.assertIn("SALE AGREED", filter_text)
        self.assertNotIn("rotate=-0.78539816339", filter_text)
        self.assertNotIn("status_ribbon_source", filter_text)
        self.assertNotIn("color=0xD97706@0.96:t=fill", filter_text)
        self.assertLess(filter_text.index("SALE AGREED"), filter_text.index("650\\,000"))

    def test_overlay_filter_uses_price_and_address_with_captions_as_subtitles(self) -> None:
        property_data = PropertyRenderData(
            site_id="ckp.ie",
            property_id=170800,
            slug="sample-property",
            title="46 Example Street, Dublin 4",
            link="https://ckp.ie/property/sample-property",
            property_status="For Sale",
            selected_image_dir=Path("images"),
            selected_image_paths=(),
            featured_image_url=None,
            bedrooms=3,
            bathrooms=2,
            ber_rating="B2",
            agent_name="Jane Doe",
            agent_photo_url=None,
            agent_email="jane@example.com",
            agent_mobile=None,
            agent_number="+353 1 234 5678",
            price="650000",
            property_type_label="Apartment",
            property_area_label="Dublin 4",
            property_county_label="Dublin",
            eircode="D04 TEST",
        )
        template = PropertyReelTemplate(subtitle_font_size=36)

        filter_text = build_overlay_filter(
            property_data,
            template,
            cover_caption="Key features: Bright open-plan living area.",
            slide_captions=("Key features: Bright open-plan living area.",),
            slide_duration=template.seconds_per_slide,
        )

        self.assertIn("€650\\,000", filter_text)
        self.assertIn("46 Example Street\\, Dublin 4", filter_text)
        self.assertIn("Bright open-plan living", filter_text)
        self.assertIn("area.", filter_text)
        self.assertNotIn("Key features", filter_text)
        self.assertNotIn("3 bed", filter_text)
        self.assertNotIn("Listed by", filter_text)
        self.assertIn("fontcolor=0xF4D03F", filter_text)
        self.assertIn("enable='between(t\\,", filter_text)
        self.assertNotIn("enable='between(t,", filter_text)
        self.assertNotIn("color=black@0.40:t=fill:enable=", filter_text)
        self.assertLess(filter_text.index("FOR SALE"), filter_text.index("650\\,000"))

    def test_overlay_filter_renders_header_details_below_address(self) -> None:
        property_data = PropertyRenderData(
            site_id="ckp.ie",
            property_id=170800,
            slug="sample-property",
            title="46 Example Street, Dublin 4",
            link="https://ckp.ie/property/sample-property",
            property_status="For Sale",
            selected_image_dir=Path("images"),
            selected_image_paths=(),
            featured_image_url=None,
            bedrooms=3,
            bathrooms=2,
            ber_rating="B2",
            agent_name="Jane Doe",
            agent_photo_url=None,
            agent_email="jane@example.com",
            agent_mobile=None,
            agent_number="+353 1 234 5678",
            price="650000",
            property_type_label="Apartment",
            property_area_label="Dublin 4",
            property_county_label="Dublin",
            eircode="D04 TEST",
            property_size="285",
        )
        template = PropertyReelTemplate(subtitle_font_size=36)

        filter_text = build_overlay_filter(
            property_data,
            template,
            cover_caption="Bright open-plan living area.",
            slide_captions=("Bright open-plan living area.",),
            slide_duration=template.seconds_per_slide,
        )

        self.assertIn("46 Example Street\\, Dublin 4", filter_text)
        self.assertIn("285m² | 3 beds | 2 baths", filter_text)
        self.assertLess(
            filter_text.index("46 Example Street\\, Dublin 4"),
            filter_text.index("285m² | 3 beds | 2 baths"),
        )

    def test_overlay_filter_renders_viewing_times_between_address_and_features(self) -> None:
        property_data = PropertyRenderData(
            site_id="ckp.ie",
            property_id=170800,
            slug="sample-property",
            title="46 Example Street, Dublin 4",
            link="https://ckp.ie/property/sample-property",
            property_status="For Sale",
            selected_image_dir=Path("images"),
            selected_image_paths=(),
            featured_image_url=None,
            bedrooms=3,
            bathrooms=2,
            ber_rating="B2",
            agent_name="Jane Doe",
            agent_photo_url=None,
            agent_email="jane@example.com",
            agent_mobile=None,
            agent_number="+353 1 234 5678",
            price="650000",
            property_type_label="Apartment",
            property_area_label="Dublin 4",
            property_county_label="Dublin",
            eircode="D04 TEST",
            property_size="285",
            viewing_times=("Saturday 20 April 12:00pm - 12:30pm",),
        )
        template = PropertyReelTemplate(subtitle_font_size=36)

        filter_text = build_overlay_filter(
            property_data,
            template,
            cover_caption="Bright open-plan living area.",
            slide_captions=("Bright open-plan living area.",),
            slide_duration=template.seconds_per_slide,
        )

        self.assertIn("46 Example Street\\, Dublin 4", filter_text)
        self.assertIn("Saturday 20 April 12\\:00pm - 12\\:30pm", filter_text)
        self.assertIn("285m² | 3 beds | 2 baths", filter_text)
        self.assertLess(
            filter_text.index("46 Example Street\\, Dublin 4"),
            filter_text.index("Saturday 20 April 12\\:00pm - 12\\:30pm"),
        )
        self.assertLess(
            filter_text.index("Saturday 20 April 12\\:00pm - 12\\:30pm"),
            filter_text.index("285m² | 3 beds | 2 baths"),
        )

    def test_format_property_size_normalizes_square_meter_units(self) -> None:
        self.assertEqual(format_property_size("285"), "285 m²")
        self.assertEqual(format_property_size("285 sqm"), "285 m²")
        self.assertEqual(format_property_size("285 m2"), "285 m²")

    def test_format_property_size_header_compacts_square_meter_units(self) -> None:
        self.assertEqual(format_property_size_header("285"), "285m²")
        self.assertEqual(format_property_size_header("285 sqm"), "285m²")
        self.assertEqual(format_property_size_header("285 m2"), "285m²")

    def test_build_property_header_details_line_skips_zero_counts_and_uses_singular_bath(self) -> None:
        property_data = PropertyRenderData(
            site_id="ckp.ie",
            property_id=170800,
            slug="sample-property",
            title="46 Example Street, Dublin 4",
            link="https://ckp.ie/property/sample-property",
            property_status="For Sale",
            selected_image_dir=Path("images"),
            selected_image_paths=(),
            featured_image_url=None,
            bedrooms=0,
            bathrooms=1,
            ber_rating="B2",
            agent_name="Jane Doe",
            agent_photo_url=None,
            agent_email="jane@example.com",
            agent_mobile=None,
            agent_number="+353 1 234 5678",
            price="650000",
            property_type_label="Apartment",
            property_area_label="Dublin 4",
            property_county_label="Dublin",
            eircode="D04 TEST",
            property_size="122",
        )

        self.assertEqual(build_property_header_details_line(property_data), "122m² | 1 bath")

    def test_fit_wrapped_lines_rebalances_orphaned_last_address_word(self) -> None:
        wrapped = fit_wrapped_lines(
            "Apartment 12, Willow Court, Blackrock, County Dublin",
            width=24,
            max_lines=3,
            rebalance_last_line=True,
        )

        self.assertEqual(
            wrapped.lines,
            ("Apartment 12, Willow", "Court, Blackrock,", "County Dublin"),
        )
        self.assertFalse(wrapped.clamped)

    def test_overlay_filter_allows_up_to_three_subtitle_lines_before_clamping(self) -> None:
        property_data = PropertyRenderData(
            site_id="ckp.ie",
            property_id=170800,
            slug="sample-property",
            title="46 Example Street, Dublin 4",
            link="https://ckp.ie/property/sample-property",
            property_status="For Sale",
            selected_image_dir=Path("images"),
            selected_image_paths=(),
            featured_image_url=None,
            bedrooms=3,
            bathrooms=2,
            ber_rating="B2",
            agent_name="Jane Doe",
            agent_photo_url=None,
            agent_email="jane@example.com",
            agent_mobile=None,
            agent_number="+353 1 234 5678",
            price="650000",
            property_type_label="Apartment",
            property_area_label="Dublin 4",
            property_county_label="Dublin",
            eircode="D04 TEST",
        )
        template = PropertyReelTemplate(include_intro=True)

        filter_text = build_overlay_filter(
            property_data,
            template,
            cover_caption=(
                "Key features: Bright open-plan living area with breakfast counter, fitted "
                "appliances, private patio access and additional built-in storage."
            ),
            slide_captions=(),
            slide_duration=template.seconds_per_slide,
        )

        self.assertNotIn("...", filter_text)
        self.assertNotIn("Key features", filter_text)
        self.assertIn("Bright open-plan living area with breakfast", filter_text)
        self.assertIn("counter\\, fitted appliances\\, private patio", filter_text)
        self.assertIn("access and additional built-in storage.", filter_text)
        self.assertIn("€650\\,000", filter_text)

    def test_overlay_filter_wraps_long_address_more_gracefully(self) -> None:
        property_data = PropertyRenderData(
            site_id="ckp.ie",
            property_id=170800,
            slug="sample-property",
            title=(
                "Apartment 12, The Extremely Long Residential Development Name, "
                "Sandymount, Dublin 4, Ireland"
            ),
            link="https://ckp.ie/property/sample-property",
            property_status="For Sale",
            selected_image_dir=Path("images"),
            selected_image_paths=(),
            featured_image_url=None,
            bedrooms=3,
            bathrooms=2,
            ber_rating="B2",
            agent_name="Jane Doe",
            agent_photo_url=None,
            agent_email="jane@example.com",
            agent_mobile=None,
            agent_number="+353 1 234 5678",
            price="650000",
            property_type_label="Apartment",
            property_area_label="Dublin 4",
            property_county_label="Dublin",
            eircode="D04 TEST",
        )
        template = PropertyReelTemplate(subtitle_font_size=36)

        filter_text = build_overlay_filter(
            property_data,
            template,
            cover_caption="Bright open-plan living area.",
            slide_captions=("Bright open-plan living area.",),
            slide_duration=template.seconds_per_slide,
        )

        self.assertIn("Extremely Long Residential", filter_text)
        self.assertIn("Development Name\\, Sandymount\\, Dublin 4\\,", filter_text)
        self.assertIn("Ireland", filter_text)

    def test_overlay_filter_renders_phone_and_email_on_separate_lines(self) -> None:
        property_data = PropertyRenderData(
            site_id="ckp.ie",
            property_id=170800,
            slug="sample-property",
            title="46 Example Street, Dublin 4",
            link="https://ckp.ie/property/sample-property",
            property_status="For Sale",
            selected_image_dir=Path("images"),
            selected_image_paths=(),
            featured_image_url=None,
            bedrooms=3,
            bathrooms=2,
            ber_rating="B2",
            agent_name="Jane Doe",
            agent_photo_url=None,
            agent_email="jane@example.com",
            agent_mobile=None,
            agent_number="+353 1 234 5678",
            price="650000",
            property_type_label="Apartment",
            property_area_label="Dublin 4",
            property_county_label="Dublin",
            eircode="D04 TEST",
        )
        template = PropertyReelTemplate(subtitle_font_size=36)

        filter_text = build_overlay_filter(
            property_data,
            template,
            cover_caption="Bright open-plan living area.",
            slide_captions=("Bright open-plan living area.",),
            slide_duration=template.seconds_per_slide,
        )

        self.assertIn("+353 1 234 5678", filter_text)
        self.assertIn("jane@example.com", filter_text)
        self.assertNotIn("+353 1 234 5678 | jane@example.com", filter_text)
        self.assertLess(filter_text.index("+353 1 234 5678"), filter_text.index("jane@example.com"))

    def test_overlay_layout_hides_missing_agent_text_blocks(self) -> None:
        property_data = PropertyRenderData(
            site_id="ckp.ie",
            property_id=170800,
            slug="sample-property",
            title="46 Example Street, Dublin 4",
            link="https://ckp.ie/property/sample-property",
            property_status="For Sale",
            selected_image_dir=Path("images"),
            selected_image_paths=(),
            featured_image_url=None,
            bedrooms=3,
            bathrooms=2,
            ber_rating=None,
            agent_name=None,
            agent_photo_url=None,
            agent_email=None,
            agent_mobile=None,
            agent_number=None,
            agency_psra=None,
            price=None,
            property_type_label="Apartment",
            property_area_label="Dublin 4",
            property_county_label="Dublin",
            eircode="D04 TEST",
        )
        template = PropertyReelTemplate(subtitle_font_size=36)
        slide = PropertyReelSlide(image_path=Path("primary_image.jpg"), caption=None)

        overlay_layout = build_overlay_layout(
            property_data,
            template,
            slides=(slide,),
            slide_duration=template.seconds_per_slide,
            has_ber_badge=False,
            cover_caption=None,
        )

        rendered_blocks = {block.block for block in overlay_layout.text_blocks}
        self.assertNotIn("agent_name", rendered_blocks)
        self.assertNotIn("agent_phone", rendered_blocks)
        self.assertNotIn("agent_email", rendered_blocks)
        self.assertNotIn("agency_psra", rendered_blocks)

    def test_overlay_layout_records_clamp_warning_for_extreme_title(self) -> None:
        property_data = PropertyRenderData(
            site_id="ckp.ie",
            property_id=170800,
            slug="sample-property",
            title=" ".join(["Exceptional"] * 40),
            link="https://ckp.ie/property/sample-property",
            property_status="For Sale",
            selected_image_dir=Path("images"),
            selected_image_paths=(),
            featured_image_url=None,
            bedrooms=3,
            bathrooms=2,
            ber_rating="B2",
            agent_name="Jane Doe",
            agent_photo_url=None,
            agent_email="jane@example.com",
            agent_mobile=None,
            agent_number="+353 1 234 5678",
            agency_psra="PSRA-1234",
            price="650000",
            property_type_label="Apartment",
            property_area_label="Dublin 4",
            property_county_label="Dublin",
            eircode="D04 TEST",
        )
        template = PropertyReelTemplate(subtitle_font_size=36)
        slide = PropertyReelSlide(image_path=Path("primary_image.jpg"), caption=None)

        overlay_layout = build_overlay_layout(
            property_data,
            template,
            slides=(slide,),
            slide_duration=template.seconds_per_slide,
            has_ber_badge=True,
            cover_caption=None,
        )

        address_block = next(block for block in overlay_layout.text_blocks if block.block == "address")
        self.assertTrue(address_block.clamped)
        self.assertTrue(any(warning.code == "TEXT_CLAMPED" for warning in overlay_layout.warnings))

    def test_overlay_layout_keeps_property_size_visible_when_address_clamps(self) -> None:
        property_data = PropertyRenderData(
            site_id="ckp.ie",
            property_id=170800,
            slug="sample-property",
            title=" ".join(["Exceptional"] * 40),
            link="https://ckp.ie/property/sample-property",
            property_status="For Sale",
            selected_image_dir=Path("images"),
            selected_image_paths=(),
            featured_image_url=None,
            bedrooms=3,
            bathrooms=2,
            ber_rating="B2",
            agent_name="Jane Doe",
            agent_photo_url=None,
            agent_email="jane@example.com",
            agent_mobile=None,
            agent_number="+353 1 234 5678",
            agency_psra="PSRA-1234",
            price="650000",
            property_type_label="Apartment",
            property_area_label="Dublin 4",
            property_county_label="Dublin",
            eircode="D04 TEST",
            property_size="285",
        )
        template = PropertyReelTemplate(subtitle_font_size=36)
        slide = PropertyReelSlide(image_path=Path("primary_image.jpg"), caption=None)

        overlay_layout = build_overlay_layout(
            property_data,
            template,
            slides=(slide,),
            slide_duration=template.seconds_per_slide,
            has_ber_badge=True,
            cover_caption=None,
        )

        address_block = next(block for block in overlay_layout.text_blocks if block.block == "address")
        address_meta_block = next(
            block for block in overlay_layout.text_blocks if block.block == "address_meta"
        )
        self.assertTrue(address_block.clamped)
        self.assertEqual(address_meta_block.lines[0], "285m² | 3 beds | 2 baths")
        self.assertEqual(address_block.font_size, address_meta_block.font_size)
        self.assertLessEqual(len(address_block.lines), address_block.max_lines)

    def test_overlay_layout_renders_header_details_two_points_smaller_than_title(self) -> None:
        property_data = PropertyRenderData(
            site_id="ckp.ie",
            property_id=170800,
            slug="sample-property",
            title="46 Example Street, Dublin 4",
            link="https://ckp.ie/property/sample-property",
            property_status="For Sale",
            selected_image_dir=Path("images"),
            selected_image_paths=(),
            featured_image_url=None,
            bedrooms=3,
            bathrooms=2,
            ber_rating="B2",
            agent_name="Jane Doe",
            agent_photo_url=None,
            agent_email="jane@example.com",
            agent_mobile=None,
            agent_number="+353 1 234 5678",
            agency_psra="PSRA-1234",
            price="650000",
            property_type_label="Apartment",
            property_area_label="Dublin 4",
            property_county_label="Dublin",
            eircode="D04 TEST",
            property_size="285",
        )
        template = PropertyReelTemplate(subtitle_font_size=36)
        slide = PropertyReelSlide(image_path=Path("primary_image.jpg"), caption=None)

        overlay_layout = build_overlay_layout(
            property_data,
            template,
            slides=(slide,),
            slide_duration=template.seconds_per_slide,
            has_ber_badge=False,
            cover_caption=None,
        )

        address_block = next(block for block in overlay_layout.text_blocks if block.block == "address")
        address_meta_block = next(
            block for block in overlay_layout.text_blocks if block.block == "address_meta"
        )
        self.assertEqual(address_meta_block.lines[0], "285m² | 3 beds | 2 baths")
        self.assertEqual(address_block.font_size, address_meta_block.font_size)
        self.assertGreater(address_meta_block.y, address_block.y)

    def test_overlay_layout_inserts_viewing_times_between_address_and_features(self) -> None:
        property_data = PropertyRenderData(
            site_id="ckp.ie",
            property_id=170800,
            slug="sample-property",
            title="46 Example Street, Dublin 4",
            link="https://ckp.ie/property/sample-property",
            property_status="For Sale",
            selected_image_dir=Path("images"),
            selected_image_paths=(),
            featured_image_url=None,
            bedrooms=3,
            bathrooms=2,
            ber_rating="B2",
            agent_name="Jane Doe",
            agent_photo_url=None,
            agent_email="jane@example.com",
            agent_mobile=None,
            agent_number="+353 1 234 5678",
            agency_psra="PSRA-1234",
            price="650000",
            property_type_label="Apartment",
            property_area_label="Dublin 4",
            property_county_label="Dublin",
            eircode="D04 TEST",
            property_size="285",
            viewing_times=("Saturday 20 April 12:00pm - 12:30pm",),
        )
        template = PropertyReelTemplate(subtitle_font_size=36)
        slide = PropertyReelSlide(image_path=Path("primary_image.jpg"), caption=None)

        overlay_layout = build_overlay_layout(
            property_data,
            template,
            slides=(slide,),
            slide_duration=template.seconds_per_slide,
            has_ber_badge=False,
            cover_caption=None,
        )

        address_block = next(block for block in overlay_layout.text_blocks if block.block == "address")
        viewing_times_block = next(
            block for block in overlay_layout.text_blocks if block.block == "viewing_times"
        )
        address_meta_block = next(
            block for block in overlay_layout.text_blocks if block.block == "address_meta"
        )
        self.assertEqual(viewing_times_block.lines[0], "Saturday 20 April 12:00pm - 12:30pm")
        self.assertEqual(address_meta_block.lines[0], "285m² | 3 beds | 2 baths")
        self.assertEqual(address_block.font_size, viewing_times_block.font_size)
        self.assertEqual(viewing_times_block.font_size, address_meta_block.font_size)
        self.assertGreater(viewing_times_block.y, address_block.y)
        self.assertGreater(address_meta_block.y, viewing_times_block.y)

    def test_overlay_filter_uses_configured_subtitle_font_and_size(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            regular_font = workspace_dir / "regular.ttf"
            bold_font = workspace_dir / "bold.ttf"
            subtitle_font = workspace_dir / "subtitle.ttf"
            regular_font.write_text("font", encoding="utf-8")
            bold_font.write_text("font", encoding="utf-8")
            subtitle_font.write_text("font", encoding="utf-8")

            property_data = PropertyRenderData(
                site_id="ckp.ie",
                property_id=170800,
                slug="sample-property",
                title="46 Example Street, Dublin 4",
                link="https://ckp.ie/property/sample-property",
                property_status="For Sale",
                selected_image_dir=Path("images"),
                selected_image_paths=(),
                featured_image_url=None,
                bedrooms=3,
                bathrooms=2,
                ber_rating="B2",
                agent_name="Jane Doe",
                agent_photo_url=None,
                agent_email="jane@example.com",
                agent_mobile=None,
                agent_number="+353 1 234 5678",
                price="650000",
                property_type_label="Apartment",
                property_area_label="Dublin 4",
                property_county_label="Dublin",
                eircode="D04 TEST",
            )
            template = PropertyReelTemplate(
                font_path=regular_font,
                bold_font_path=bold_font,
                subtitle_font_path=subtitle_font,
                subtitle_font_size=52,
            )

            filter_text = build_overlay_filter(
                property_data,
                template,
                cover_caption="Bright open-plan living area.",
                slide_captions=("Bright open-plan living area.",),
                slide_duration=template.seconds_per_slide,
            )

            self.assertIn(f"fontfile='{escape_filter_path(subtitle_font)}'", filter_text)
            self.assertIn("fontsize=52", filter_text)


class StatusReelRenderTests(unittest.TestCase):
    def test_status_reel_template_disables_intro_and_limits_to_one_slide(self) -> None:
        template = build_reel_template_for_render_profile("sale_agreed_status_reel")

        self.assertFalse(template.include_intro)
        self.assertEqual(template.intro_duration_seconds, 0.0)
        self.assertEqual(template.max_slide_count, 1)
        self.assertEqual(template.total_duration_seconds, template.seconds_per_slide)

    def test_status_reel_filter_omits_cover_logo_intro(self) -> None:
        property_data = PropertyRenderData(
            site_id="ckp.ie",
            property_id=170800,
            slug="sample-property",
            title="46 Example Street, Dublin 4",
            link="https://ckp.ie/property/sample-property",
            property_status="Sale Agreed",
            selected_image_dir=Path("images"),
            selected_image_paths=(),
            featured_image_url=None,
            bedrooms=3,
            bathrooms=2,
            ber_rating="B2",
            agent_name="Jane Doe",
            agent_photo_url=None,
            agent_email="jane@example.com",
            agent_mobile=None,
            agent_number="+353 1 234 5678",
            price="650000",
            property_type_label=None,
            property_area_label=None,
            property_county_label=None,
            eircode=None,
            banner_text="SALE AGREED",
            price_display_text="",
        )
        template = build_reel_template_for_render_profile("sale_agreed_status_reel")
        slide = PropertyReelSlide(image_path=Path("primary_image.jpg"), caption=None)

        filter_text = build_filter_complex(
            property_data,
            template,
            slides=(slide,),
            slide_frames=120,
            slide_duration=template.seconds_per_slide,
            logo_input_index=None,
            agent_image_input_index=1,
            ber_icon_input_index=2,
        )

        self.assertNotIn("[coverbg][logo]overlay=", filter_text)
        self.assertNotIn("concat=n=2:v=1:a=0[video_base]", filter_text)
        self.assertIn("[slideshow]null[video_base]", filter_text)
        self.assertNotIn("fade=t=in:st=0:d=", filter_text)
        self.assertIn("fade=t=out:st=", filter_text)
        self.assertIn("SALE AGREED", filter_text)
        self.assertNotIn("650\\,000", filter_text)

    def test_status_reel_filter_uses_similar_required_as_subtitle(self) -> None:
        property_data = PropertyRenderData(
            site_id="ckp.ie",
            property_id=170800,
            slug="sample-property",
            title="46 Example Street, Dublin 4",
            link="https://ckp.ie/property/sample-property",
            property_status="Let Agreed",
            selected_image_dir=Path("images"),
            selected_image_paths=(),
            featured_image_url=None,
            bedrooms=3,
            bathrooms=2,
            ber_rating="B2",
            agent_name="Jane Doe",
            agent_photo_url=None,
            agent_email="jane@example.com",
            agent_mobile=None,
            agent_number="+353 1 234 5678",
            price="650000",
            property_type_label=None,
            property_area_label=None,
            property_county_label=None,
            eircode=None,
            banner_text="LET AGREED",
            price_display_text="",
        )
        template = build_reel_template_for_render_profile("let_agreed_status_reel")
        slide = PropertyReelSlide(
            image_path=Path("primary_image.jpg"),
            caption="Bright open-plan living area.",
        )

        filter_text = build_filter_complex(
            property_data,
            template,
            slides=(slide,),
            slide_frames=120,
            slide_duration=template.seconds_per_slide,
            logo_input_index=None,
            agent_image_input_index=1,
            ber_icon_input_index=2,
        )

        self.assertIn("Similar required? ckp.ie", filter_text)
        self.assertNotIn("Similar required? ckp.ie.", filter_text)
        self.assertNotIn("Bright open-plan living area.", filter_text)

    def test_full_reel_filter_supports_intro_without_cover_logo_input(self) -> None:
        property_data = PropertyRenderData(
            site_id="ckp.ie",
            property_id=170800,
            slug="sample-property",
            title="46 Example Street, Dublin 4",
            link="https://ckp.ie/property/sample-property",
            property_status="For Sale",
            selected_image_dir=Path("images"),
            selected_image_paths=(),
            featured_image_url=None,
            bedrooms=3,
            bathrooms=2,
            ber_rating="B2",
            agent_name="Jane Doe",
            agent_photo_url=None,
            agent_email="jane@example.com",
            agent_mobile=None,
            agent_number="+353 1 234 5678",
            price="650000",
            property_type_label="Apartment",
            property_area_label="Dublin 4",
            property_county_label="Dublin",
            eircode="D04 TEST",
        )
        template = PropertyReelTemplate(include_intro=True)
        slide = PropertyReelSlide(image_path=Path("primary_image.jpg"), caption=None)

        filter_text = build_filter_complex(
            property_data,
            template,
            slides=(slide,),
            slide_frames=120,
            slide_duration=template.seconds_per_slide,
            logo_input_index=None,
            agent_image_input_index=1,
            ber_icon_input_index=2,
        )

        self.assertIn("[coverbg]null[cover]", filter_text)
        self.assertIn("[cover][slideshow]concat=n=2:v=1:a=0[video_base]", filter_text)
        self.assertNotIn("[coverbg][logo]overlay=", filter_text)
        self.assertNotIn("fade=t=in:st=0:d=", filter_text)

    def test_multi_slide_filter_only_applies_fade_in_after_first_slide(self) -> None:
        property_data = PropertyRenderData(
            site_id="ckp.ie",
            property_id=170800,
            slug="sample-property",
            title="46 Example Street, Dublin 4",
            link="https://ckp.ie/property/sample-property",
            property_status="For Sale",
            selected_image_dir=Path("images"),
            selected_image_paths=(),
            featured_image_url=None,
            bedrooms=3,
            bathrooms=2,
            ber_rating="B2",
            agent_name="Jane Doe",
            agent_photo_url=None,
            agent_email="jane@example.com",
            agent_mobile=None,
            agent_number="+353 1 234 5678",
            price="650000",
            property_type_label="Apartment",
            property_area_label="Dublin 4",
            property_county_label="Dublin",
            eircode="D04 TEST",
        )
        template = build_reel_template_for_render_profile("for_sale_reel")
        slides = (
            PropertyReelSlide(image_path=Path("primary_image.jpg"), caption=None),
            PropertyReelSlide(image_path=Path("secondary_image.jpg"), caption=None),
        )

        filter_text = build_filter_complex(
            property_data,
            template,
            slides=slides,
            slide_frames=120,
            slide_duration=template.seconds_per_slide,
            logo_input_index=None,
            agent_image_input_index=2,
            ber_icon_input_index=3,
        )

        self.assertEqual(filter_text.count("fade=t=in:st=0:d="), 1)
        self.assertEqual(filter_text.count("fade=t=out:st="), 2)


class BerIconRuntimeTests(unittest.TestCase):
    def test_resolve_ber_icon_path_normalizes_supported_values(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            ber_dir = workspace_dir / "assets" / "ber-icons"
            ber_dir.mkdir(parents=True, exist_ok=True)
            icon_path = ber_dir / "B2.png"
            icon_path.write_bytes(b"png")
            template = PropertyReelTemplate()
            self.assertEqual(resolve_ber_icon_path(workspace_dir, template, "B2"), icon_path)
            self.assertEqual(resolve_ber_icon_path(workspace_dir, template, "ber b2"), icon_path)
            self.assertEqual(resolve_ber_icon_path(workspace_dir, template, "B 2"), icon_path)

    def test_resolve_ber_icon_path_returns_none_for_unknown_or_missing_icon(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            template = PropertyReelTemplate()

            self.assertIsNone(resolve_ber_icon_path(workspace_dir, template, None))
            self.assertIsNone(resolve_ber_icon_path(workspace_dir, template, "Z9"))
            self.assertIsNone(resolve_ber_icon_path(workspace_dir, template, "B2"))


class AgencyLogoRuntimeTests(unittest.TestCase):
    def test_prepare_cover_logo_image_downloads_agency_logo_when_available(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            property_data = PropertyRenderData(
                site_id="ckp.ie",
                property_id=170800,
                slug="sample-property",
                title="46 Example Street, Dublin 4",
                link="https://ckp.ie/property/sample-property",
                property_status="For Sale",
                selected_image_dir=Path("images"),
                selected_image_paths=(),
                featured_image_url=None,
                bedrooms=3,
                bathrooms=2,
                ber_rating="B2",
                agent_name="Jane Doe",
                agent_photo_url=None,
                agent_email="jane@example.com",
                agent_mobile=None,
                agent_number="+353 1 234 5678",
                agency_logo_url="https://example.com/agency-logo.png",
                price="650000",
                property_type_label="Apartment",
                property_area_label="Dublin 4",
                property_county_label="Dublin",
                eircode="D04 TEST",
            )

            def fake_download(image_url: str, destination: Path) -> Path:
                self.assertEqual(image_url, "https://example.com/agency-logo.png")
                destination.write_bytes(b"logo")
                return destination

            with patch("services.reel_rendering.runtime.download_remote_image", side_effect=fake_download):
                cover_logo_path = prepare_cover_logo_image(
                    workspace_dir,
                    property_data,
                    PropertyReelTemplate(),
                )

        self.assertIsNotNone(cover_logo_path)
        assert cover_logo_path is not None
        self.assertTrue(cover_logo_path.name.startswith("sample-property-agency-logo-"))
        self.assertEqual(cover_logo_path.suffix, ".png")

    def test_prepare_cover_logo_image_returns_none_when_download_fails(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            property_data = PropertyRenderData(
                site_id="ckp.ie",
                property_id=170800,
                slug="sample-property",
                title="46 Example Street, Dublin 4",
                link="https://ckp.ie/property/sample-property",
                property_status="For Sale",
                selected_image_dir=Path("images"),
                selected_image_paths=(),
                featured_image_url=None,
                bedrooms=3,
                bathrooms=2,
                ber_rating="B2",
                agent_name="Jane Doe",
                agent_photo_url=None,
                agent_email="jane@example.com",
                agent_mobile=None,
                agent_number="+353 1 234 5678",
                agency_logo_url="https://example.com/agency-logo.png",
                price="650000",
                property_type_label="Apartment",
                property_area_label="Dublin 4",
                property_county_label="Dublin",
                eircode="D04 TEST",
            )

            with patch(
                "services.reel_rendering.runtime.download_remote_image",
                side_effect=OSError("network failure"),
            ):
                cover_logo_path = prepare_cover_logo_image(
                    workspace_dir,
                    property_data,
                    PropertyReelTemplate(),
                )

        self.assertIsNone(cover_logo_path)

    def test_prepare_cover_logo_image_skips_duplicate_agent_photo_filename(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            property_data = PropertyRenderData(
                site_id="ckp.ie",
                property_id=170800,
                slug="sample-property",
                title="46 Example Street, Dublin 4",
                link="https://ckp.ie/property/sample-property",
                property_status="For Sale",
                selected_image_dir=Path("images"),
                selected_image_paths=(),
                featured_image_url=None,
                bedrooms=3,
                bathrooms=2,
                ber_rating="B2",
                agent_name="Jane Doe",
                agent_photo_url="https://cdn.example.com/team/agent-portrait.jpg",
                agent_email="jane@example.com",
                agent_mobile=None,
                agent_number="+353 1 234 5678",
                agency_logo_url="https://example.com/branding/agent-portrait.jpg",
                price="650000",
                property_type_label="Apartment",
                property_area_label="Dublin 4",
                property_county_label="Dublin",
                eircode="D04 TEST",
            )

            with patch(
                "services.reel_rendering.runtime.download_remote_image",
                side_effect=AssertionError("duplicate agency logo should not be downloaded"),
            ):
                cover_logo_path = prepare_cover_logo_image(
                    workspace_dir,
                    property_data,
                    PropertyReelTemplate(),
                )

        self.assertIsNone(cover_logo_path)

    def test_prepare_cover_logo_image_normalizes_case_and_query_when_matching_agent_photo(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            property_data = PropertyRenderData(
                site_id="ckp.ie",
                property_id=170800,
                slug="sample-property",
                title="46 Example Street, Dublin 4",
                link="https://ckp.ie/property/sample-property",
                property_status="For Sale",
                selected_image_dir=Path("images"),
                selected_image_paths=(),
                featured_image_url=None,
                bedrooms=3,
                bathrooms=2,
                ber_rating="B2",
                agent_name="Jane Doe",
                agent_photo_url="https://cdn.example.com/team/AGENT-PORTRAIT.JPG?version=2",
                agent_email="jane@example.com",
                agent_mobile=None,
                agent_number="+353 1 234 5678",
                agency_logo_url="https://example.com/branding/agent-portrait.jpg#logo",
                price="650000",
                property_type_label="Apartment",
                property_area_label="Dublin 4",
                property_county_label="Dublin",
                eircode="D04 TEST",
            )

            with patch(
                "services.reel_rendering.runtime.download_remote_image",
                side_effect=AssertionError("normalized duplicate agency logo should not be downloaded"),
            ):
                cover_logo_path = prepare_cover_logo_image(
                    workspace_dir,
                    property_data,
                    PropertyReelTemplate(),
                )

        self.assertIsNone(cover_logo_path)


class ReelRuntimePathTests(unittest.TestCase):
    def test_resolve_font_path_supports_project_relative_paths(self) -> None:
        original_cwd = Path.cwd()
        with workspace_temp_dir() as workspace_dir:
            os.chdir(workspace_dir)
            try:
                resolved_path = resolve_font_path(Path("assets/fonts/Inter/static/Inter_28pt-Bold.ttf"))
            finally:
                os.chdir(original_cwd)

        self.assertTrue(resolved_path.exists())
        self.assertEqual(resolved_path.name, "Inter_28pt-Bold.ttf")


class ReelManifestTests(unittest.TestCase):
    def test_manifest_includes_slide_captions_and_duration_delta(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            assets_dir = workspace_dir / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            (assets_dir / "ckp-logo.png").write_bytes(b"logo")
            music_dir = assets_dir / "music"
            music_dir.mkdir(parents=True, exist_ok=True)
            (music_dir / "ncs-music.mp3").write_bytes(b"audio")
            ber_icons_dir = assets_dir / "ber-icons"
            ber_icons_dir.mkdir(parents=True, exist_ok=True)
            (ber_icons_dir / "B2.png").write_bytes(b"png")

            selected_dir = workspace_dir / "selected_photos"
            selected_dir.mkdir(parents=True, exist_ok=True)
            primary_image = selected_dir / "primary_image.jpg"
            living_image = selected_dir / "01_living-room.jpg"
            primary_image.write_bytes(b"image")
            living_image.write_bytes(b"image")

            audit_path = selected_dir.parent / GEMINI_SELECTION_AUDIT_FILENAME
            audit_path.write_text(
                json.dumps(
                    {
                        "selected_images": [
                            {
                                "file": "primary_image.jpg",
                                "reserved": True,
                                "caption": "Key features: Apartment in Dublin 4.",
                            },
                            {
                                "file": "living-room.jpg",
                                "caption": "Key features: Bright open-plan living area.",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            property_data = PropertyRenderData(
                site_id="ckp.ie",
                property_id=170800,
                slug="sample-property",
                title="46 Example Street, Dublin 4",
                link="https://ckp.ie/property/sample-property",
                property_status="For Sale",
                selected_image_dir=selected_dir,
                selected_image_paths=(primary_image, living_image),
                featured_image_url="https://example.com/property-primary.jpg",
                bedrooms=3,
                bathrooms=2,
                ber_rating="B2",
                agent_name="Jane Doe",
                agent_photo_url=None,
                agent_email="jane@example.com",
                agent_mobile=None,
                agent_number="+353 1 234 5678",
                price="650000",
                property_type_label="Apartment",
                property_area_label="Dublin 4",
                property_county_label="Dublin",
                eircode="D04 TEST",
            )

            manifest = build_property_reel_manifest_from_data(
                workspace_dir,
                property_data,
                template=PropertyReelTemplate(
                    include_intro=True,
                    intro_duration_seconds=3.0,
                    seconds_per_slide=4.0,
                    total_duration_seconds=10.0,
                ),
            )

        self.assertEqual(manifest["slides"][0]["caption"], "Apartment in Dublin 4.")
        self.assertEqual(
            manifest["slides"][1]["caption"],
            "Bright open-plan living area.",
        )
        self.assertEqual(manifest["configured_total_duration_seconds"], 10.0)
        self.assertEqual(manifest["actual_total_duration_seconds"], 11.0)
        self.assertEqual(manifest["duration_delta_seconds"], 1.0)
        self.assertEqual(manifest["estimated_duration_seconds"], 11.0)
        self.assertEqual(manifest["slide_count"], 2)
        self.assertIsNone(manifest["render_profile"])
        self.assertEqual(manifest["render_settings"]["include_intro"], True)
        self.assertEqual(manifest["render_settings"]["intro_duration_seconds"], 3.0)
        self.assertEqual(manifest["render_settings"]["footer_bottom_offset_px"], 0)
        self.assertEqual(manifest["ber_icon_path"], str(ber_icons_dir / "B2.png"))
        self.assertEqual(
            manifest["agent_lines"],
            ["Jane Doe", "+353 1 234 5678", "jane@example.com"],
        )
        self.assertIn("overlay_layout", manifest)
        self.assertIn("text_blocks", manifest["overlay_layout"])
        self.assertIn("warnings", manifest["overlay_layout"])

    def test_manifest_omits_cover_logo_when_agency_logo_is_unavailable(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            assets_dir = workspace_dir / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            music_dir = assets_dir / "music"
            music_dir.mkdir(parents=True, exist_ok=True)
            (music_dir / "ncs-music.mp3").write_bytes(b"audio")
            ber_icons_dir = assets_dir / "ber-icons"
            ber_icons_dir.mkdir(parents=True, exist_ok=True)
            (ber_icons_dir / "B2.png").write_bytes(b"png")

            selected_dir = workspace_dir / "selected_photos"
            selected_dir.mkdir(parents=True, exist_ok=True)
            primary_image = selected_dir / "primary_image.jpg"
            primary_image.write_bytes(b"image")

            property_data = PropertyRenderData(
                site_id="ckp.ie",
                property_id=170800,
                slug="sample-property",
                title="46 Example Street, Dublin 4",
                link="https://ckp.ie/property/sample-property",
                property_status="For Sale",
                selected_image_dir=selected_dir,
                selected_image_paths=(primary_image,),
                featured_image_url="https://example.com/property-primary.jpg",
                bedrooms=3,
                bathrooms=2,
                ber_rating="B2",
                agent_name="Jane Doe",
                agent_photo_url=None,
                agent_email="jane@example.com",
                agent_mobile=None,
                agent_number="+353 1 234 5678",
                agency_logo_url="https://example.com/agency-logo.png",
                price="650000",
                property_type_label="Apartment",
                property_area_label="Dublin 4",
                property_county_label="Dublin",
                eircode="D04 TEST",
            )

            with patch(
                "services.reel_rendering.runtime.download_remote_image",
                side_effect=OSError("network failure"),
            ):
                manifest = build_property_reel_manifest_from_data(
                    workspace_dir,
                    property_data,
                )

        self.assertIsNone(manifest["cover_logo_path"])

    def test_manifest_keeps_logo_box_when_duplicate_logo_is_suppressed(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            assets_dir = workspace_dir / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            music_dir = assets_dir / "music"
            music_dir.mkdir(parents=True, exist_ok=True)
            (music_dir / "ncs-music.mp3").write_bytes(b"audio")

            selected_dir = workspace_dir / "selected_photos"
            selected_dir.mkdir(parents=True, exist_ok=True)
            primary_image = selected_dir / "primary_image.jpg"
            primary_image.write_bytes(b"image")

            property_data = PropertyRenderData(
                site_id="ckp.ie",
                property_id=170800,
                slug="sample-property",
                title="46 Example Street, Dublin 4",
                link="https://ckp.ie/property/sample-property",
                property_status="For Sale",
                selected_image_dir=selected_dir,
                selected_image_paths=(primary_image,),
                featured_image_url="https://example.com/property-primary.jpg",
                bedrooms=3,
                bathrooms=2,
                ber_rating=None,
                agent_name="Jane Doe",
                agent_photo_url="https://cdn.example.com/team/AGENT-PORTRAIT.JPG?version=2",
                agent_email="jane@example.com",
                agent_mobile=None,
                agent_number="+353 1 234 5678",
                agency_logo_url="https://example.com/branding/agent-portrait.jpg#logo",
                price="650000",
                property_type_label="Apartment",
                property_area_label="Dublin 4",
                property_county_label="Dublin",
                eircode="D04 TEST",
            )

            with patch(
                "services.reel_rendering.runtime.download_remote_image",
                side_effect=AssertionError("duplicate agency logo should not be downloaded for manifest"),
            ):
                manifest = build_property_reel_manifest_from_data(
                    workspace_dir,
                    property_data,
                )

        self.assertIsNone(manifest["cover_logo_path"])
        self.assertIsNotNone(manifest["overlay_layout"]["agency_logo_box"])
        assert manifest["overlay_layout"]["agency_logo_box"] is not None
        self.assertTrue(manifest["overlay_layout"]["agency_logo_box"]["visible"])

    def test_status_reel_manifest_does_not_include_cover_logo_and_uses_single_slide_duration(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            assets_dir = workspace_dir / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            music_dir = assets_dir / "music"
            music_dir.mkdir(parents=True, exist_ok=True)
            (music_dir / "ncs-music.mp3").write_bytes(b"audio")
            ber_icons_dir = assets_dir / "ber-icons"
            ber_icons_dir.mkdir(parents=True, exist_ok=True)
            (ber_icons_dir / "B2.png").write_bytes(b"png")

            selected_dir = workspace_dir / "selected_photos"
            selected_dir.mkdir(parents=True, exist_ok=True)
            primary_image = selected_dir / "primary_image.jpg"
            primary_image.write_bytes(b"image")

            property_data = PropertyRenderData(
                site_id="ckp.ie",
                property_id=170800,
                slug="sample-property",
                title="46 Example Street, Dublin 4",
                link="https://ckp.ie/property/sample-property",
                property_status="Sale Agreed",
                selected_image_dir=selected_dir,
                selected_image_paths=(primary_image,),
                featured_image_url="https://example.com/property-primary.jpg",
                bedrooms=3,
                bathrooms=2,
                ber_rating="B2",
                agent_name="Jane Doe",
                agent_photo_url=None,
                agent_email="jane@example.com",
                agent_mobile=None,
                agent_number="+353 1 234 5678",
                price="650000",
                property_type_label="Apartment",
                property_area_label="Dublin 4",
                property_county_label="Dublin",
                eircode="D04 TEST",
                banner_text="SALE AGREED",
                price_display_text="",
            )

            template = build_reel_template_for_render_profile("sale_agreed_status_reel")
            manifest = build_property_reel_manifest_from_data(
                workspace_dir,
                property_data,
                template=template,
            )

        self.assertIsNone(manifest["cover_logo_path"])
        self.assertEqual(manifest["slide_count"], 1)
        self.assertEqual(manifest["configured_total_duration_seconds"], template.seconds_per_slide)
        self.assertEqual(manifest["actual_total_duration_seconds"], template.seconds_per_slide)
        self.assertEqual(manifest["price"], None)


@unittest.skipUnless(send_webhook is not None, "wordpress-webhook-simulator is not available")
class SimulatorContractTests(unittest.TestCase):
    def test_send_payload_includes_gohighlevel_headers_and_matching_signature(self) -> None:
        captured_request: dict[str, object] = {}

        def fake_urlopen(request, timeout):
            captured_request["headers"] = {key.lower(): value for key, value in request.header_items()}
            captured_request["body"] = request.data
            captured_request["timeout"] = timeout
            return FakeHTTPResponse(status=202, body='{"status":"accepted"}')

        with (
            patch.object(send_webhook, "SIMULATOR_BASE_URL", "http://127.0.0.1:8000"),
            patch.object(send_webhook, "SIMULATOR_WEBHOOK_PATH", "/webhooks/wordpress/property"),
            patch.object(send_webhook, "SIMULATOR_TIMEOUT_SECONDS", 15),
            patch.object(send_webhook, "SIMULATOR_SITE_SECRETS", {"site-a": "secret-a"}),
            patch.object(send_webhook, "SIMULATOR_GOHIGHLEVEL_LOCATION_IDS", {"site-a": "location-a"}),
            patch.object(send_webhook, "SIMULATOR_GOHIGHLEVEL_ACCESS_TOKENS", {"site-a": "token-a"}),
            patch.object(send_webhook, "urlopen", side_effect=fake_urlopen),
            patch("send_webhook.time.time", return_value=1700000000),
        ):
            status_code, response_body = send_webhook.send_payload(
                site_id="site-a",
                payload={"id": 321},
            )

        self.assertEqual(status_code, 202)
        self.assertEqual(response_body, '{"status":"accepted"}')
        self.assertEqual(captured_request["headers"]["x-wordpress-site-id"], "site-a")
        self.assertEqual(captured_request["headers"]["x-gohighlevel-location-id"], "location-a")
        self.assertEqual(captured_request["headers"]["x-gohighlevel-access-token"], "token-a")
        self.assertEqual(captured_request["headers"]["x-wordpress-timestamp"], "1700000000")
        self.assertEqual(
            captured_request["headers"]["x-wordpress-signature"],
            build_signature(
                "secret-a",
                "1700000000",
                "site-a",
                "location-a",
                "token-a",
                captured_request["body"],
            ),
        )


if __name__ == "__main__":
    unittest.main()

