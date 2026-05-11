"""Enqueue a `scripted_render` job from a manifest.

Replaces the legacy synchronous scripted-render handler. The router now returns `202 Accepted`
immediately; the ffmpeg render runs asynchronously in the worker process via
the already-registered `scripted_render` handler in `apps/worker/runtime.py`.

Tenant resolution is inline: the manifest carries `site_id` (a WordPress
ingestion source's `external_id`), and the use case looks up the matching
`ingestion_sources` row to derive `agency_id` + `ingestion_source_id`. We
intentionally do NOT import `RenderScriptedVideoUseCase` from `modules.reels`
— that's the worker's concern, not the API's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from modules.delivery.domain import JobEnqueueRequest
from shared.db import DatabaseUnitOfWork
from shared.errors import ResourceNotFoundError, ValidationError


@dataclass(frozen=True, slots=True)
class EnqueueScriptedRenderInput:
    site_id: str
    source_property_id: int | None
    raw_payload_hash: str
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class EnqueuedScriptedRender:
    event_id: str
    job_id: str
    agency_id: str
    ingestion_source_id: str
    site_id: str
    source_property_id: int | None


class EnqueueScriptedRenderUseCase:
    """Resolve the tenant and enqueue a `scripted_render` job.

    The manifest is forwarded verbatim as the job payload; the worker's
    handler validates the manifest contents at execution time. The use case
    only validates the bare minimum (`site_id`, `source_property_id`) needed
    to route the job to the right tenant.
    """

    def __init__(self, *, job_max_attempts: int) -> None:
        self.job_max_attempts = max(1, int(job_max_attempts))

    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        data: EnqueueScriptedRenderInput,
    ) -> EnqueuedScriptedRender:
        if (
            uow.tenancy is None
            or uow.ingestion is None
            or uow.delivery is None
        ):
            raise RuntimeError("The unit of work is not active.")

        normalized_site_id = str(data.site_id or "").strip().lower()
        if not normalized_site_id:
            raise ValidationError(
                "The scripted render manifest must include a non-empty site_id.",
                code="SITE_ID_REQUIRED",
                context={"field": "site_id"},
                hint="Send the WordPress site_id matching an active ingestion_sources row.",
            )

        source = uow.ingestion.sources.get_by_kind_external_id(
            kind="wordpress",
            external_id=normalized_site_id,
        )
        if source is None or source.status != "active":
            raise ResourceNotFoundError(
                "The scripted render site is not provisioned.",
                code="UNKNOWN_WORDPRESS_SITE",
                context={"site_id": normalized_site_id},
                hint=(
                    "Provision an active ingestion_sources row "
                    "for this site_id before posting scripted renders."
                ),
            )

        agency = uow.tenancy.agencies.get_by_id(source.agency_id)
        if agency is None:
            raise ResourceNotFoundError(
                "The scripted render tenant could not be resolved.",
                code="UNKNOWN_WORDPRESS_SITE",
                context={"site_id": normalized_site_id, "agency_id": source.agency_id},
                hint="The ingestion_sources row references an agency that no longer exists.",
            )

        now = datetime.now(timezone.utc).isoformat()
        event_id = str(uuid4())
        job_id = str(uuid4())
        property_id = data.source_property_id

        uow.delivery.webhook_events.create_event(
            event_id=event_id,
            agency_id=agency.agency_id,
            ingestion_source_id=source.ingestion_source_id,
            external_source_id=source.external_id,
            property_id=property_id,
            received_at=now,
            raw_payload_hash=data.raw_payload_hash,
            status="queued",
            source_kind="scripted_api",
        )
        uow.delivery.jobs.enqueue_job(
            JobEnqueueRequest(
                job_id=job_id,
                event_id=event_id,
                agency_id=agency.agency_id,
                ingestion_source_id=source.ingestion_source_id,
                kind="scripted_render",
                external_source_id=source.external_id,
                property_id=property_id,
                received_at=now,
                raw_payload_hash=data.raw_payload_hash,
                payload=dict(data.payload),
                publish_context={},
                provider_secret_bundle="",
                max_attempts=self.job_max_attempts,
                available_at=now,
                created_at=now,
            )
        )

        return EnqueuedScriptedRender(
            event_id=event_id,
            job_id=job_id,
            agency_id=agency.agency_id,
            ingestion_source_id=source.ingestion_source_id,
            site_id=source.external_id,
            source_property_id=property_id,
        )


__all__ = [
    "EnqueueScriptedRenderInput",
    "EnqueueScriptedRenderUseCase",
    "EnqueuedScriptedRender",
]
