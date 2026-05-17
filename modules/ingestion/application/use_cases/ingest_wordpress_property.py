"""Accept a WordPress property webhook and enqueue a `reel_publish` job."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from modules.delivery.domain import JobEnqueueRequest
from shared.db import DatabaseUnitOfWork
from shared.errors import ResourceNotFoundError


@dataclass(frozen=True, slots=True)
class AcceptedWebhookDelivery:
    event_id: str
    job_id: str
    agency_id: str
    ingestion_source_id: str
    site_id: str
    property_id: int | None
    tenant_auto_provisioned: bool = False


@dataclass(frozen=True, slots=True)
class IngestWordPressPropertyInput:
    site_id: str
    property_id: int | None
    raw_payload_hash: str
    payload: Mapping[str, Any]
    default_platforms: tuple[str, ...]


class IngestWordPressPropertyUseCase:
    """Webhook acceptance: tenant resolution + provider lookup + job enqueue.

    Replaces the legacy `WebhookAcceptanceService.accept_delivery`. The job
    payload shape (`payload_json`, `publish_context_json`, encrypted
    `provider_secret_bundle`) is preserved byte-for-byte so the worker
    consumes the same contract.
    """

    def __init__(self, *, job_max_attempts: int) -> None:
        self.job_max_attempts = max(1, int(job_max_attempts))

    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        data: IngestWordPressPropertyInput,
    ) -> AcceptedWebhookDelivery:
        if (
            uow.tenancy is None
            or uow.ingestion is None
            or uow.publishing is None
            or uow.configuration is None
            or uow.delivery is None
        ):
            raise RuntimeError("The unit of work is not active.")

        normalized_site_id = str(data.site_id or "").strip().lower()
        source = uow.ingestion.sources.get_by_kind_external_id(
            kind="wordpress",
            external_id=normalized_site_id,
        )
        if source is None or source.status != "active":
            raise ResourceNotFoundError(
                "The webhook site is not provisioned.",
                code="UNKNOWN_WORDPRESS_SITE",
                context={"site_id": normalized_site_id},
                hint=(
                    "Provision an active ingestion_sources row "
                    "for this site_id before sending webhooks."
                ),
            )

        ghl_connection = uow.publishing.connections.get_with_secrets(
            agency_id=source.agency_id,
            provider="gohighlevel",
        )
        if ghl_connection is None:
            raise ResourceNotFoundError(
                "The agency has no GoHighLevel connection saved.",
                code="GHL_CONNECTION_NOT_FOUND",
                context={"agency_id": source.agency_id},
                hint=(
                    "Configure the agency's GoHighLevel connection from the admin "
                    "panel before posting WordPress webhooks."
                ),
            )

        access_token = str(
            (ghl_connection.secrets or {}).get("access_token") or ""
        )

        defaults = uow.configuration.defaults.get(source.agency_id)
        automation = uow.configuration.automation.get(source.agency_id)
        social_templates_records = uow.configuration.social_templates.list_for_agency(
            source.agency_id
        )

        platforms = tuple(
            defaults.platforms
            if defaults is not None and defaults.platforms
            else data.default_platforms
        )
        render_template_id = (
            getattr(defaults, "render_template_id", "classic")
            if defaults is not None
            else "classic"
        )
        approval_required = bool(
            automation.approval_required if automation is not None else False
        )
        social_templates = tuple(
            (str(template.platform).strip().lower(), str(template.description_template or ""))
            for template in social_templates_records
            if str(template.platform).strip()
        )
        social_title_templates = tuple(
            (str(template.platform).strip().lower(), str(template.title_template or ""))
            for template in social_templates_records
            if str(template.platform).strip()
            and str(template.title_template or "").strip()
        )
        social_hashtags_map = {
            str(template.platform).strip().lower(): [
                str(tag) for tag in (template.hashtags or ()) if str(tag).strip()
            ]
            for template in social_templates_records
            if str(template.platform).strip()
            and any(str(tag).strip() for tag in (template.hashtags or ()))
        }

        publish_context: dict[str, Any] = {
            "provider": "gohighlevel",
            "location_id": ghl_connection.external_id,
            "platforms": list(platforms),
            "approval_required": approval_required,
            "social_templates": list(social_templates),
            "social_title_templates": list(social_title_templates),
            "social_hashtags": social_hashtags_map,
            "render_template_id": render_template_id or "classic",
        }
        provider_secret_bundle = json.dumps(
            {"access_token": access_token, "provider": "gohighlevel"},
            ensure_ascii=False,
            sort_keys=True,
        )

        now = datetime.now(timezone.utc).isoformat()
        event_id = str(uuid4())
        job_id = str(uuid4())

        superseded_event_ids = uow.delivery.jobs.supersede_queued_jobs(
            external_source_id=source.external_id,
            property_id=data.property_id,
            superseded_by_job_id=job_id,
            finished_at=now,
        )
        for superseded_event_id in superseded_event_ids:
            uow.delivery.webhook_events.update_event_status(
                superseded_event_id,
                status="superseded",
                error_message="Superseded by a newer queued job.",
            )

        uow.delivery.webhook_events.create_event(
            event_id=event_id,
            agency_id=source.agency_id,
            ingestion_source_id=source.ingestion_source_id,
            external_source_id=source.external_id,
            property_id=data.property_id,
            received_at=now,
            raw_payload_hash=data.raw_payload_hash,
            status="queued",
            source_kind="wordpress",
        )
        uow.delivery.jobs.enqueue_job(
            JobEnqueueRequest(
                job_id=job_id,
                event_id=event_id,
                agency_id=source.agency_id,
                ingestion_source_id=source.ingestion_source_id,
                kind="reel_publish",
                external_source_id=source.external_id,
                property_id=data.property_id,
                received_at=now,
                raw_payload_hash=data.raw_payload_hash,
                payload=dict(data.payload),
                publish_context=publish_context,
                provider_secret_bundle=provider_secret_bundle,
                max_attempts=self.job_max_attempts,
                available_at=now,
                created_at=now,
            )
        )
        uow.ingestion.sources.touch_last_event(source.ingestion_source_id)

        return AcceptedWebhookDelivery(
            event_id=event_id,
            job_id=job_id,
            agency_id=source.agency_id,
            ingestion_source_id=source.ingestion_source_id,
            site_id=source.external_id,
            property_id=data.property_id,
            tenant_auto_provisioned=False,
        )


__all__ = [
    "AcceptedWebhookDelivery",
    "IngestWordPressPropertyInput",
    "IngestWordPressPropertyUseCase",
]
