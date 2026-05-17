"""Persist a per-reel music override (feature 25).

Use case wired to ``PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/music``.

Flow:

1. Validate the agency exists (delegates to
   :func:`modules.reels.application.use_cases._admin_support.ensure_agency_exists`).
2. Load the target reel by ``(external_source_id, source_property_id)``.
   404 ``ADMIN_REEL_NOT_FOUND`` if missing.
3. Refuse to mutate reels that have already cleared the editorial gate
   (``publish_status`` outside the editable set, same set as feature 21).
   The endpoint surfaces this as **409** with code ``REEL_NOT_EDITABLE``.
4. If ``music_id`` is not ``None``:
   * Load the track row via ``uow.configuration.music.get``.
   * If the track does not exist OR belongs to a different agency,
     surface **404 ADMIN_MUSIC_TRACK_NOT_FOUND**. We deliberately use
     404 (not 403) for the cross-agency case so the response never leaks
     existence of a track that belongs to a foreign tenant — matching
     the cross-tenant 404 convention established by feature 22.
5. Replace ``reels.music_id`` with the supplied value (including
   ``None``, which clears the override).
6. Re-enqueue a fresh ``reel_publish`` job (mirroring the
   :class:`RegenerateReelUseCase` flow) so the worker picks up the
   override and re-renders. The override travels on the
   ``publish_context.override_music_track_id`` slot so the ingest step
   can swap the agency pool for a single-element tuple. When publish
   prerequisites are missing (no original payload, no GHL connection),
   the use case still persists the override and returns a
   ``publish_enqueued=False`` flag — same contract as
   ``regenerate_reel`` so the frontend can render a consistent state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from modules.configuration.application.use_cases.compute_next_publish_slot import (
    compute_next_publish_slot,
)
from modules.delivery.domain import JobEnqueueRequest
from modules.reels.application.use_cases._admin_support import (
    ensure_agency_exists,
    reel_not_found_error,
)
from modules.reels.application.use_cases.update_reel_descriptions_override import (
    ReelNotEditableError,
    _EDITABLE_PUBLISH_STATUSES,
)
from modules.reels.domain import ReelState
from shared.db import DatabaseUnitOfWork
from shared.errors import ResourceNotFoundError


@dataclass(frozen=True, slots=True)
class UpdateReelMusicOverrideResult:
    """Return value of the use case."""

    state: ReelState
    music_id: str | None
    publish_enqueued: bool
    event_id: str | None = None
    job_id: str | None = None
    reason: str | None = None
    hint: str | None = None


_PREREQ_MISSING_HINT = (
    "The music override was saved, but no publish job was queued because "
    "either the original WordPress payload or the agency's GHL "
    "connection is missing. The override will apply the next time the "
    "reel is approved."
)


def _music_track_not_found_error(
    *,
    agency_id: str,
    music_id: str,
) -> ResourceNotFoundError:
    """Surfaces 404 for both "unknown id" and "cross-agency id" cases.

    We deliberately fold both into the same 404 ``ADMIN_MUSIC_TRACK_NOT_FOUND``
    code so the endpoint never leaks the existence of a track owned by
    a different agency (consistent with the cross-tenant convention
    used by feature 22 / configuration music endpoints).
    """
    return ResourceNotFoundError(
        "The music track does not exist for this agency.",
        code="ADMIN_MUSIC_TRACK_NOT_FOUND",
        context={
            "agency_id": str(agency_id or "").strip(),
            "music_id": str(music_id or "").strip(),
        },
        hint=(
            "Pick a track returned by "
            "GET /v1/admin/agencies/{agency_id}/music."
        ),
    )


class UpdateReelMusicOverrideUseCase:
    """Persist the music override and re-enqueue a render job."""

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
        music_id: str | None,
    ) -> UpdateReelMusicOverrideResult:
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
        normalized_music_id = (
            str(music_id).strip() if music_id is not None else None
        ) or None

        existing = uow.reels.states.get(
            external_source_id=normalized_site_id,
            source_property_id=normalized_property_id,
        )
        if existing is None:
            raise reel_not_found_error(
                agency_id=normalized_agency_id,
                site_id=normalized_site_id,
                source_property_id=normalized_property_id,
            )

        if existing.publish_status not in _EDITABLE_PUBLISH_STATUSES:
            raise ReelNotEditableError(
                agency_id=normalized_agency_id,
                site_id=normalized_site_id,
                source_property_id=normalized_property_id,
                publish_status=existing.publish_status,
            )

        if normalized_music_id is not None:
            track = uow.configuration.music.get(music_id=normalized_music_id)
            if track is None:
                raise _music_track_not_found_error(
                    agency_id=normalized_agency_id,
                    music_id=normalized_music_id,
                )
            if str(track.agency_id).strip() != normalized_agency_id:
                # Cross-agency request: 404 (not 403) so we never leak the
                # existence of a track owned by another tenant.
                raise _music_track_not_found_error(
                    agency_id=normalized_agency_id,
                    music_id=normalized_music_id,
                )

        next_state = ReelState(
            agency_id=existing.agency_id or normalized_agency_id,
            ingestion_source_id=existing.ingestion_source_id,
            external_source_id=existing.external_source_id,
            source_property_id=existing.source_property_id,
            content_fingerprint=existing.content_fingerprint,
            content_snapshot=existing.content_snapshot,
            publish_target_fingerprint=existing.publish_target_fingerprint,
            publish_target_snapshot=existing.publish_target_snapshot,
            render_template_id=existing.render_template_id,
            selected_image_folder=existing.selected_image_folder,
            artifact_kind=existing.artifact_kind,
            local_artifact_path=existing.local_artifact_path,
            local_metadata_path=existing.local_metadata_path,
            render_profile=existing.render_profile,
            local_manifest_path=existing.local_manifest_path,
            local_video_path=existing.local_video_path,
            render_status=existing.render_status,
            publish_status=existing.publish_status,
            workflow_state=existing.workflow_state,
            publish_details=existing.publish_details,
            current_revision_id=existing.current_revision_id,
            last_published_provider_external_id=(
                existing.last_published_provider_external_id
            ),
            created_at=existing.created_at,
            updated_at=existing.updated_at,
            descriptions_override=existing.descriptions_override,
            music_id=normalized_music_id,
        )
        uow.reels.states.save(next_state)

        enqueue_result = self._maybe_enqueue_publish_job(
            uow=uow,
            agency_id=normalized_agency_id,
            site_id=normalized_site_id,
            source_property_id=normalized_property_id,
            ingestion_source_id=existing.ingestion_source_id,
            override_music_track_id=normalized_music_id,
        )
        return UpdateReelMusicOverrideResult(
            state=next_state,
            music_id=normalized_music_id,
            **enqueue_result,
        )

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _maybe_enqueue_publish_job(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
        site_id: str,
        source_property_id: int,
        ingestion_source_id: str,
        override_music_track_id: str | None,
    ) -> dict[str, Any]:
        """Mirror ``RegenerateReelUseCase`` for the music-override re-render.

        Builds a fresh ``reel_publish`` job with ``approval_required=False``
        and ``override_music_track_id`` set on ``publish_context``. Returns
        the kwargs used to populate :class:`UpdateReelMusicOverrideResult`.
        """
        assert uow.catalog is not None
        assert uow.publishing is not None
        assert uow.configuration is not None
        assert uow.delivery is not None
        assert uow.tenancy is not None

        raw_payload = uow.catalog.properties.get_raw_payload(
            external_source_id=site_id,
            source_property_id=source_property_id,
        )
        ghl_connection = uow.publishing.connections.get_with_secrets(
            agency_id=agency_id,
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

        if prerequisites_missing or payload_dict is None or ghl_connection is None:
            return {
                "publish_enqueued": False,
                "event_id": None,
                "job_id": None,
                "reason": "PUBLISH_PREREQUISITES_MISSING",
                "hint": _PREREQ_MISSING_HINT,
            }

        defaults = uow.configuration.defaults.get(agency_id)
        automation = uow.configuration.automation.get(agency_id)
        social_templates_records = (
            uow.configuration.social_templates.list_for_agency(agency_id)
        )
        platforms = tuple(
            defaults.platforms
            if defaults is not None and defaults.platforms
            else self.default_platforms
        )
        render_template_id = (
            getattr(defaults, "render_template_id", "classic")
            if defaults is not None
            else "classic"
        )
        agency = uow.tenancy.agencies.get_by_id(agency_id)
        agency_timezone = (
            agency.timezone
            if agency is not None and getattr(agency, "timezone", "")
            else "UTC"
        )
        scheduled_slot = compute_next_publish_slot(
            automation,
            datetime.now(timezone.utc),
            agency_timezone=agency_timezone,
        )
        scheduled_at_iso: str | None = (
            scheduled_slot.isoformat() if scheduled_slot is not None else None
        )
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
            "scheduled_at": scheduled_at_iso,
            "render_template_id": render_template_id or "classic",
            # Feature 25: forward the override to the worker so the
            # ingest step swaps the agency pool for a single-element
            # tuple. The key is only set when the user provided one; a
            # cleared override falls through to the default pool
            # resolver (features 23 / 24).
            "override_music_track_id": override_music_track_id,
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
            external_source_id=site_id,
            property_id=source_property_id,
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
            agency_id=agency_id,
            ingestion_source_id=ingestion_source_id,
            external_source_id=site_id,
            property_id=source_property_id,
            received_at=now,
            raw_payload_hash=raw_payload_hash,
            status="queued",
            source_kind="wordpress",
        )
        uow.delivery.jobs.enqueue_job(
            JobEnqueueRequest(
                job_id=job_id,
                event_id=event_id,
                agency_id=agency_id,
                ingestion_source_id=ingestion_source_id,
                kind="reel_publish",
                external_source_id=site_id,
                property_id=source_property_id,
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

        return {
            "publish_enqueued": True,
            "event_id": event_id,
            "job_id": job_id,
            "reason": None,
            "hint": None,
        }


__all__ = [
    "UpdateReelMusicOverrideResult",
    "UpdateReelMusicOverrideUseCase",
]
