from __future__ import annotations

from typing import Protocol

from models.property import Property
from repositories.property_job_repository import PropertyJobEnqueueRequest, QueuedPropertyJobRecord
from repositories.webhook_delivery_repository import WebhookDeliveryRecord
from repositories.property_pipeline_repository import (
    DownloadedImage,
    PropertyPipelineState,
    PropertyReelRecord,
)


class PropertyRepository(Protocol):
    def save_property_data(
        self,
        property_item: Property,
        *,
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
        site_id: str,
        source_property_id: int,
        manifest_path,
        video_path,
    ) -> None:
        ...

    def update_social_publish_status(
        self,
        *,
        site_id: str,
        source_property_id: int,
        status: str,
        details: dict[str, object] | None = None,
        last_published_location_id: str = "",
    ) -> None:
        ...


class WebhookEventStore(Protocol):
    def create_event(
        self,
        *,
        event_id: str,
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


class UnitOfWork(Protocol):
    property_repository: PropertyRepository
    pipeline_state_repository: PropertyPipelineStateRepository
    webhook_event_store: WebhookEventStore
    job_queue_store: JobQueueStore

    def begin_immediate(self) -> None:
        ...

    def __enter__(self) -> "UnitOfWork":
        ...

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        ...


__all__ = [
    "JobQueueStore",
    "PropertyPipelineStateRepository",
    "PropertyRepository",
    "UnitOfWork",
    "WebhookEventStore",
]

