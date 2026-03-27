from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from application.persistence import UnitOfWork
from application.types import SocialPublishContext
from repositories.property_job_repository import PropertyJobEnqueueRequest


@dataclass(frozen=True, slots=True)
class AcceptedWebhookDelivery:
    event_id: str
    job_id: str
    site_id: str
    property_id: int | None


class WebhookAcceptanceService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        job_max_attempts: int,
    ) -> None:
        self.unit_of_work_factory = unit_of_work_factory
        self.job_max_attempts = max(1, job_max_attempts)

    def accept_delivery(
        self,
        *,
        site_id: str,
        property_id: int | None,
        raw_payload_hash: str,
        payload: dict[str, object],
        publish_context: SocialPublishContext | None,
    ) -> AcceptedWebhookDelivery:
        now = datetime.now(timezone.utc).isoformat()
        event_id = str(uuid4())
        job_id = str(uuid4())
        payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        publish_context_json = ""
        if publish_context is not None:
            publish_context_json = json.dumps(
                publish_context.to_dict(include_access_token=True),
                ensure_ascii=False,
                sort_keys=True,
            )

        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.begin_immediate()
            superseded_event_ids = unit_of_work.job_queue_store.supersede_queued_jobs(
                site_id=site_id,
                property_id=property_id,
                superseded_by_job_id=job_id,
                finished_at=now,
            )
            for superseded_event_id in superseded_event_ids:
                unit_of_work.webhook_event_store.update_event_status(
                    superseded_event_id,
                    status="superseded",
                    error_message="Superseded by a newer queued job.",
                )

            unit_of_work.webhook_event_store.create_event(
                event_id=event_id,
                site_id=site_id,
                property_id=property_id,
                received_at=now,
                raw_payload_hash=raw_payload_hash,
                status="queued",
            )
            unit_of_work.job_queue_store.enqueue_job(
                PropertyJobEnqueueRequest(
                    job_id=job_id,
                    event_id=event_id,
                    site_id=site_id,
                    property_id=property_id,
                    received_at=now,
                    raw_payload_hash=raw_payload_hash,
                    payload_json=payload_json,
                    publish_context_json=publish_context_json,
                    max_attempts=self.job_max_attempts,
                    available_at=now,
                    created_at=now,
                )
            )

        return AcceptedWebhookDelivery(
            event_id=event_id,
            job_id=job_id,
            site_id=site_id,
            property_id=property_id,
        )


__all__ = ["AcceptedWebhookDelivery", "WebhookAcceptanceService"]

