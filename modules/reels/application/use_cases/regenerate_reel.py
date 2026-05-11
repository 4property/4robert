"""Regenerate a reel by enqueuing a fresh `reel_publish` job.

The legacy admin "Approve" endpoint forwarded the request through
`WebhookAcceptanceService.accept_delivery`. This use case replaces that
indirection: it writes the supersede + webhook_event + job rows directly
through the per-module repositories on a single Unit of Work.

Idempotence: any previously queued job for the same property is marked
`superseded`; the corresponding webhook events are also updated.

Prerequisites missing → return a result flagged `publish_enqueued=False`
with `reason='PUBLISH_PREREQUISITES_MISSING'`. The transport layer
preserves the legacy contract and returns 200 in that case so the
frontend can render a consistent state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from modules.delivery.domain import JobEnqueueRequest
from modules.reels.application.use_cases._admin_support import (
    ensure_agency_exists,
    reel_not_found_error,
)
from shared.db import DatabaseUnitOfWork

if TYPE_CHECKING:
    from modules.reels.infrastructure.reel_query import AgencyReelSummary


@dataclass(frozen=True, slots=True)
class RegenerateReelResult:
    publish_enqueued: bool
    reel: AgencyReelSummary
    event_id: str | None = None
    job_id: str | None = None
    reason: str | None = None
    hint: str | None = None


_PREREQ_MISSING_HINT = (
    "The reel was marked as approved, but no publish job was queued "
    "because either the original WordPress payload or the agency's GHL "
    "connection is missing."
)


class RegenerateReelUseCase:
    """Approve + re-enqueue a publish job for an existing reel."""

    def __init__(
        self,
        *,
        job_max_attempts: int,
        default_platforms: tuple[str, ...] = (),
    ) -> None:
        self.job_max_attempts = max(1, int(job_max_attempts))
        self.default_platforms = tuple(default_platforms)

    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
        site_id: str,
        source_property_id: int,
    ) -> RegenerateReelResult:
        if (
            uow.reels is None
            or uow.tenancy is None
            or uow.catalog is None
            or uow.publishing is None
            or uow.configuration is None
            or uow.delivery is None
        ):
            raise RuntimeError("The unit of work is not active.")
        ensure_agency_exists(uow, agency_id)

        normalized_agency_id = str(agency_id or "").strip()
        normalized_site_id = str(site_id or "").strip().lower()
        normalized_property_id = int(source_property_id)

        existing_state = uow.reels.states.get(
            external_source_id=normalized_site_id,
            source_property_id=normalized_property_id,
        )
        if existing_state is None:
            raise reel_not_found_error(
                agency_id=normalized_agency_id,
                site_id=normalized_site_id,
                source_property_id=normalized_property_id,
            )

        ingestion_source_id = existing_state.ingestion_source_id

        uow.reels.states.update_workflow_state(
            agency_id=existing_state.agency_id or normalized_agency_id,
            ingestion_source_id=ingestion_source_id,
            external_source_id=normalized_site_id,
            source_property_id=normalized_property_id,
            workflow_state="approved",
        )
        uow.reels.states.update_publish_status(
            agency_id=existing_state.agency_id or normalized_agency_id,
            ingestion_source_id=ingestion_source_id,
            external_source_id=normalized_site_id,
            source_property_id=normalized_property_id,
            status="pending_publish",
        )

        raw_payload = uow.catalog.properties.get_raw_payload(
            external_source_id=normalized_site_id,
            source_property_id=normalized_property_id,
        )
        ghl_connection = uow.publishing.connections.get_with_secrets(
            agency_id=normalized_agency_id,
            provider="gohighlevel",
        )
        access_token = ""
        if ghl_connection is not None:
            access_token = str(
                (ghl_connection.secrets or {}).get("access_token") or ""
            )

        prerequisites_missing = (
            not raw_payload
            or ghl_connection is None
            or not access_token.strip()
        )

        payload_dict: dict[str, Any] | None = None
        if not prerequisites_missing:
            try:
                parsed = json.loads(raw_payload)
            except json.JSONDecodeError:
                prerequisites_missing = True
            else:
                if isinstance(parsed, dict):
                    payload_dict = parsed
                else:
                    prerequisites_missing = True

        reel_summary = self._load_reel_summary(
            uow,
            agency_id=normalized_agency_id,
            site_id=normalized_site_id,
            source_property_id=normalized_property_id,
        )

        if prerequisites_missing or payload_dict is None or ghl_connection is None:
            return RegenerateReelResult(
                publish_enqueued=False,
                reel=reel_summary,
                reason="PUBLISH_PREREQUISITES_MISSING",
                hint=_PREREQ_MISSING_HINT,
            )

        defaults = uow.configuration.defaults.get(normalized_agency_id)
        automation = uow.configuration.automation.get(normalized_agency_id)
        social_templates_records = (
            uow.configuration.social_templates.list_for_agency(normalized_agency_id)
        )
        platforms = tuple(
            defaults.platforms
            if defaults is not None and defaults.platforms
            else self.default_platforms
        )
        del automation
        social_templates = tuple(
            (
                str(template.platform).strip().lower(),
                str(template.description_template or ""),
            )
            for template in social_templates_records
            if str(template.platform).strip()
        )

        publish_context: dict[str, Any] = {
            "provider": "gohighlevel",
            "location_id": ghl_connection.external_id,
            "platforms": list(platforms),
            "approval_required": False,
            "social_templates": list(social_templates),
        }
        provider_secret_bundle = json.dumps(
            {"access_token": access_token, "provider": "gohighlevel"},
            ensure_ascii=False,
            sort_keys=True,
        )

        raw_payload_hash = hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc).isoformat()
        event_id = str(uuid4())
        job_id = str(uuid4())

        superseded_event_ids = uow.delivery.jobs.supersede_queued_jobs(
            external_source_id=normalized_site_id,
            property_id=normalized_property_id,
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
            agency_id=normalized_agency_id,
            ingestion_source_id=ingestion_source_id,
            external_source_id=normalized_site_id,
            property_id=normalized_property_id,
            received_at=now,
            raw_payload_hash=raw_payload_hash,
            status="queued",
            source_kind="wordpress",
        )
        uow.delivery.jobs.enqueue_job(
            JobEnqueueRequest(
                job_id=job_id,
                event_id=event_id,
                agency_id=normalized_agency_id,
                ingestion_source_id=ingestion_source_id,
                kind="reel_publish",
                external_source_id=normalized_site_id,
                property_id=normalized_property_id,
                received_at=now,
                raw_payload_hash=raw_payload_hash,
                payload=payload_dict,
                publish_context=publish_context,
                provider_secret_bundle=provider_secret_bundle,
                max_attempts=self.job_max_attempts,
                available_at=now,
                created_at=now,
            )
        )

        return RegenerateReelResult(
            publish_enqueued=True,
            reel=reel_summary,
            event_id=event_id,
            job_id=job_id,
        )

    def _load_reel_summary(
        self,
        uow: DatabaseUnitOfWork,
        *,
        agency_id: str,
        site_id: str,
        source_property_id: int,
    ) -> AgencyReelSummary:
        if uow.reels is None:
            raise RuntimeError("The unit of work is not active.")
        for item in uow.reels.queries.list_recent_for_agency(
            agency_id=agency_id,
            limit=500,
        ):
            if (
                str(item.external_source_id).strip().lower() == site_id
                and int(item.source_property_id) == source_property_id
            ):
                return item
        raise reel_not_found_error(
            agency_id=agency_id,
            site_id=site_id,
            source_property_id=source_property_id,
        )


__all__ = ["RegenerateReelResult", "RegenerateReelUseCase"]
