from __future__ import annotations

from typing import Protocol

from domain.properties.model import Property
from repositories.stores.agency_store import AgencyRecord
from repositories.stores.ghl_connection_store import GoHighLevelConnectionRecord
from repositories.stores.reel_profile_store import ReelProfileRecord
from repositories.stores.wordpress_source_store import WordPressSourceDetailsRecord, WordPressSourceRecord
from repositories.stores.media_revision_store import MediaRevisionRecord
from repositories.stores.outbox_event_store import OutboxEventRecord
from repositories.stores.job_queue_store import PropertyJobEnqueueRequest, QueuedPropertyJobRecord
from repositories.stores.pipeline_state_store import PropertyPipelineState
from repositories.stores.scripted_video_artifact_store import ScriptedVideoArtifactRecord
from repositories.stores.property_store import PropertyReelRecord
from repositories.stores.webhook_event_store import WebhookDeliveryRecord
from domain.media.types import DownloadedImage


class PropertyRepository(Protocol):
    def save_property_data(
        self,
        property_item: Property,
        *,
        agency_id: str,
        wordpress_source_id: str,
        site_id: str,
        image_folder: str = "",
        social_publish_status: str | None = None,
        social_publish_details_json: str | None = None,
    ) -> None:
        ...

    def save_property_images(
        self,
        property_item: Property,
        property_dir,
        downloaded_images: list[DownloadedImage],
        *,
        agency_id: str,
        wordpress_source_id: str,
        site_id: str,
        social_publish_status: str | None = None,
        social_publish_details_json: str | None = None,
    ) -> None:
        ...

    def get_property_reel_record(
        self,
        *,
        site_id: str,
        property_id: int | None = None,
        slug: str | None = None,
    ) -> PropertyReelRecord | None:
        ...


class PropertyPipelineStateRepository(Protocol):
    def get_property_pipeline_state(
        self,
        *,
        site_id: str,
        source_property_id: int,
    ) -> PropertyPipelineState | None:
        ...

    def save_property_pipeline_state(self, state: PropertyPipelineState) -> None:
        ...

    def save_local_artifacts(
        self,
        *,
        agency_id: str,
        wordpress_source_id: str,
        site_id: str,
        source_property_id: int,
        artifact_kind: str = "reel_video",
        artifact_path=None,
        metadata_path=None,
        render_profile: str = "",
        current_revision_id: str = "",
        manifest_path=None,
        video_path=None,
    ) -> None:
        ...

    def update_social_publish_status(
        self,
        *,
        agency_id: str,
        wordpress_source_id: str,
        site_id: str,
        source_property_id: int,
        status: str,
        details: dict[str, object] | None = None,
        last_published_location_id: str = "",
    ) -> None:
        ...

    def update_workflow_state(
        self,
        *,
        agency_id: str,
        wordpress_source_id: str,
        site_id: str,
        source_property_id: int,
        workflow_state: str,
        current_revision_id: str | None = None,
    ) -> None:
        ...


class MediaRevisionStore(Protocol):
    def save_media_revision(self, record: MediaRevisionRecord) -> None:
        ...

    def get_media_revision(self, revision_id: str) -> MediaRevisionRecord | None:
        ...

    def list_media_revisions(
        self,
        *,
        site_id: str,
        source_property_id: int,
    ) -> tuple[MediaRevisionRecord, ...]:
        ...


class OutboxEventStore(Protocol):
    def add_event(
        self,
        *,
        event_id: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, object] | None = None,
        agency_id: str = "",
        wordpress_source_id: str = "",
        site_id: str = "",
        source_property_id: int | None = None,
        status: str = "pending",
        created_at: str | None = None,
        available_at: str | None = None,
    ) -> None:
        ...

    def mark_published(self, *, event_id: str, published_at: str | None = None) -> None:
        ...

    def list_events(
        self,
        *,
        site_id: str | None = None,
        source_property_id: int | None = None,
    ) -> tuple[OutboxEventRecord, ...]:
        ...


class WebhookEventStore(Protocol):
    def create_event(
        self,
        *,
        event_id: str,
        agency_id: str,
        wordpress_source_id: str,
        site_id: str,
        property_id: int | None,
        received_at: str,
        raw_payload_hash: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        ...

    def update_event_status(
        self,
        event_id: str,
        *,
        status: str,
        error_message: str | None = None,
    ) -> None:
        ...

    def get_event(self, event_id: str) -> WebhookDeliveryRecord | None:
        ...


class JobQueueStore(Protocol):
    def enqueue_job(self, request: PropertyJobEnqueueRequest) -> None:
        ...

    def supersede_queued_jobs(
        self,
        *,
        site_id: str,
        property_id: int | None,
        superseded_by_job_id: str,
        finished_at: str | None = None,
    ) -> tuple[str, ...]:
        ...

    def recover_expired_processing_jobs(self, *, now: str | None = None) -> int:
        ...

    def claim_next_ready_job(
        self,
        *,
        worker_id: str,
        lease_expires_at: str,
        now: str | None = None,
    ) -> QueuedPropertyJobRecord | None:
        ...

    def renew_job_lease(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_expires_at: str,
        now: str | None = None,
    ) -> bool:
        ...

    def mark_job_completed(self, *, job_id: str, finished_at: str | None = None) -> None:
        ...

    def mark_job_failed(
        self,
        *,
        job_id: str,
        error_message: str,
        finished_at: str | None = None,
    ) -> None:
        ...

    def schedule_retry(
        self,
        *,
        job_id: str,
        error_message: str,
        available_at: str,
        now: str | None = None,
    ) -> None:
        ...

    def count_active_jobs(self) -> int:
        ...

    def get_job(self, job_id: str) -> QueuedPropertyJobRecord | None:
        ...

    def list_jobs_for_property(
        self,
        *,
        site_id: str,
        property_id: int | None,
    ) -> tuple[QueuedPropertyJobRecord, ...]:
        ...


class ScriptedVideoArtifactStore(Protocol):
    def save_artifact(self, record: ScriptedVideoArtifactRecord) -> None:
        ...

    def get_artifact(self, render_id: str) -> ScriptedVideoArtifactRecord | None:
        ...

    def list_artifacts_for_property(
        self,
        *,
        site_id: str,
        source_property_id: int,
    ) -> tuple[ScriptedVideoArtifactRecord, ...]:
        ...


class WordPressSourceStore(Protocol):
    def get_by_site_id(self, site_id: str) -> WordPressSourceRecord | None:
        ...

    def get_details_by_site_id(self, site_id: str) -> WordPressSourceDetailsRecord | None:
        ...

    def list_sources(self) -> tuple[WordPressSourceDetailsRecord, ...]:
        ...

    def list_sources_for_agency(
        self, agency_id: str
    ) -> tuple[WordPressSourceDetailsRecord, ...]:
        ...

    def create_source(
        self,
        *,
        wordpress_source_id: str,
        agency_id: str,
        site_id: str,
        name: str,
        site_url: str | None = None,
        normalized_host: str | None = None,
        status: str = "active",
        webhook_secret: str = "",
    ) -> None:
        ...

    def update_source(
        self,
        *,
        wordpress_source_id: str,
        name: str,
        site_url: str | None = None,
        normalized_host: str | None = None,
        status: str = "active",
        webhook_secret: str = "",
        update_webhook_secret: bool = False,
    ) -> None:
        ...

    def delete_source(self, wordpress_source_id: str) -> bool:
        ...


class AgencyStore(Protocol):
    def get_by_id(self, agency_id: str) -> AgencyRecord | None:
        ...

    def get_by_slug(self, slug: str) -> AgencyRecord | None:
        ...

    def list_agencies(self) -> tuple[AgencyRecord, ...]:
        ...

    def create_agency(
        self,
        *,
        agency_id: str,
        name: str,
        slug: str,
        timezone: str = "UTC",
        status: str = "active",
    ) -> None:
        ...

    def update_agency(
        self,
        *,
        agency_id: str,
        name: str,
        slug: str,
        timezone: str,
        status: str,
    ) -> None:
        ...

    def delete_agency(self, agency_id: str) -> bool:
        ...


class GoHighLevelConnectionStore(Protocol):
    def get_by_agency_id(self, agency_id: str) -> GoHighLevelConnectionRecord | None:
        ...

    def list_connections(self) -> tuple[GoHighLevelConnectionRecord, ...]:
        ...

    def upsert_for_agency(
        self,
        *,
        agency_id: str,
        location_id: str,
        user_id: str,
        access_token: str,
        refresh_token: str = "",
        expires_at: str = "",
        status: str = "active",
    ) -> GoHighLevelConnectionRecord:
        ...

    def delete_by_agency_id(self, agency_id: str) -> bool:
        ...

    def require_for_agency(self, agency_id: str) -> GoHighLevelConnectionRecord:
        ...


class ReelProfileStore(Protocol):
    def get_by_agency_id(self, agency_id: str) -> ReelProfileRecord | None:
        ...

    def upsert_for_agency(
        self,
        *,
        agency_id: str,
        name: str | None = None,
        platforms: list | tuple | None = None,
        duration_seconds: int | None = None,
        music_id: str | None = None,
        intro_enabled: bool | None = None,
        logo_position: str | None = None,
        brand_primary_color: str | None = None,
        brand_secondary_color: str | None = None,
        caption_template: str | None = None,
        approval_required: bool | None = None,
        extra_settings: dict | None = None,
    ) -> ReelProfileRecord:
        ...

    def delete_by_agency_id(self, agency_id: str) -> bool:
        ...


class UnitOfWork(Protocol):
    property_repository: PropertyRepository
    pipeline_state_repository: PropertyPipelineStateRepository
    media_revision_store: MediaRevisionStore
    outbox_event_store: OutboxEventStore
    webhook_event_store: WebhookEventStore
    job_queue_store: JobQueueStore
    scripted_video_store: ScriptedVideoArtifactStore
    wordpress_source_store: WordPressSourceStore
    agency_store: AgencyStore
    ghl_connection_store: GoHighLevelConnectionStore
    reel_profile_store: ReelProfileStore

    def begin_immediate(self) -> None:
        ...

    def __enter__(self) -> "UnitOfWork":
        ...

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        ...


__all__ = [
    "AgencyStore",
    "GoHighLevelConnectionStore",
    "JobQueueStore",
    "MediaRevisionStore",
    "OutboxEventStore",
    "PropertyPipelineStateRepository",
    "PropertyRepository",
    "ReelProfileStore",
    "ScriptedVideoArtifactStore",
    "UnitOfWork",
    "WebhookEventStore",
    "WordPressSourceStore",
]

