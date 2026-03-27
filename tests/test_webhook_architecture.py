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
from application.default_services import DefaultPropertyInfoService
from application.types import PropertyVideoJob, SocialPublishContext
from application.webhook_acceptance import WebhookAcceptanceService
from config import DATABASE_FILENAME, GEMINI_SELECTION_AUDIT_FILENAME
from core.errors import TransientSocialPublishingError
from models.property import Property
from repositories.property_job_repository import PropertyJobRepository
from repositories.sqlite_work_unit import SqliteWorkUnit
from repositories.webhook_delivery_repository import WebhookDeliveryRepository
from repositories.property_pipeline_repository import PropertyPipelineRepository
from services.reel_rendering.formatting import escape_filter_path
from services.reel_rendering.filters import build_overlay_filter
from services.reel_rendering.manifest import build_property_reel_manifest_from_data
from services.reel_rendering.models import PropertyRenderData, PropertyReelTemplate
from services.reel_rendering.runtime import resolve_ber_icon_path, resolve_font_path
from services.webhook_transport.security import build_signature
from services.webhook_transport.server import WordPressWebhookApplication, create_fastapi_app
from services.webhook_transport.site_storage import resolve_site_storage_layout

SIMULATOR_ROOT = Path(__file__).resolve().parents[2] / "wordpress-webhook-simulator"
if str(SIMULATOR_ROOT) not in sys.path:
    sys.path.insert(0, str(SIMULATOR_ROOT))

import send_webhook  # type: ignore[import-not-found]

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
) -> dict[str, object]:
    return {
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
        "wppd_primary_image": "https://example.com/property-primary.jpg",
        "wppd_pics": [
            "https://example.com/property-primary.jpg",
            "https://example.com/property-secondary.jpg",
        ],
        "property_features": property_features or ["Private patio", "Open-plan kitchen"],
    }


def build_job(
    *,
    event_id: str = "event-1",
    site_id: str = "site-a",
    payload: dict[str, object] | None = None,
    location_id: str = "location-a",
    access_token: str = "token-a",
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
            platform="tiktok",
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

        self.assertIn("agent_photo_url", property_columns)
        self.assertIn("content_fingerprint", pipeline_columns)
        self.assertIn("content_snapshot_json", pipeline_columns)
        self.assertIn("publish_target_fingerprint", pipeline_columns)
        self.assertIn("publish_target_snapshot_json", pipeline_columns)
        self.assertIn("last_published_location_id", pipeline_columns)
        self.assertFalse(any("access_token" in column for column in property_columns))
        self.assertFalse(any("access_token" in column for column in pipeline_columns))


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
        manifest_path = storage_paths.reels_root / f"{property_item.slug}-reel.json"
        video_path = storage_paths.reels_root / f"{property_item.slug}-reel.mp4"
        manifest_path.write_text("{}", encoding="utf-8")
        video_path.write_bytes(b"video")

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
                details={"post_id": "post-1"},
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
        self.assertIsNone(context.publish_description)
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

    def test_changed_normalized_field_outside_legacy_subset_forces_new_render(self) -> None:
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

    def test_raw_gohighlevel_token_is_not_persisted(self) -> None:
        with workspace_temp_dir() as workspace_dir:
            service = self._build_service(workspace_dir)
            service.ingest_property(build_job(access_token="token-keep-out"))

            database_path = workspace_dir / DATABASE_FILENAME
            database_bytes = database_path.read_bytes()
            wal_path = Path(f"{database_path}-wal")
            wal_bytes = wal_path.read_bytes() if wal_path.exists() else b""

        self.assertNotIn(b"token-keep-out", database_bytes)
        self.assertNotIn(b"token-keep-out", wal_bytes)


class WebhookTransportTests(unittest.TestCase):
    def _build_client(
        self,
        dispatcher: RecordingDispatcher | None = None,
    ) -> tuple[TestClient, RecordingDispatcher]:
        active_dispatcher = dispatcher or RecordingDispatcher()
        workspace_dir = TEST_TEMP_ROOT / uuid4().hex
        workspace_dir.mkdir(parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, workspace_dir, True)
        application = WordPressWebhookApplication(
            workspace_dir=workspace_dir,
            dispatcher=active_dispatcher,
            site_secrets={"site-a": "secret-a"},
            security_disabled=False,
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

    @staticmethod
    def _build_signed_headers(
        payload: dict[str, object],
        *,
        site_id: str = "site-a",
        location_id: str = "location-a",
        access_token: str = "token-a",
        timestamp: str | None = None,
    ) -> dict[str, str]:
        body = json.dumps(payload).encode("utf-8")
        timestamp_value = str(int(time.time())) if timestamp is None else timestamp
        return {
            "Content-Type": "application/json",
            "X-WordPress-Site-ID": site_id,
            "X-GoHighLevel-Location-ID": location_id,
            "X-GoHighLevel-Access-Token": access_token,
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
        self.assertIn('"access_token": "token-a"', job.publish_context_json)
        self.assertIn('"platform": "tiktok"', job.publish_context_json)

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
        self.assertEqual(jobs[1].job_id, second_delivery.job_id)
        self.assertEqual(jobs[1].status, "queued")
        self.assertIn('"access_token": "token-second"', jobs[1].publish_context_json)
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
                    platform="tiktok",
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
                    platform="tiktok",
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
                    platform="tiktok",
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
        self.assertIn("temporary social outage", first_job.last_error or "")
        self.assertEqual(second_job.status, "completed")
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
                    platform="tiktok",
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
        self.assertNotIn("color=black@0.40:t=fill:enable=", filter_text)
        self.assertLess(filter_text.index("FOR SALE"), filter_text.index("650\\,000"))

    def test_overlay_filter_truncates_long_caption_to_fit_two_lines(self) -> None:
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
        template = PropertyReelTemplate()

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

        self.assertIn("...", filter_text)
        self.assertNotIn("Key features", filter_text)
        self.assertIn("€650\\,000", filter_text)

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
            (assets_dir / "ncs-music.mp3").write_bytes(b"audio")
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
        self.assertEqual(manifest["ber_icon_path"], str(ber_icons_dir / "B2.png"))


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

