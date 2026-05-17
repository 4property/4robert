"""Persist a per-reel subtitle override (feature 36).

Use case wired to
``PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/subtitles``.

Flow:

1. Validate the agency exists (delegates to
   :func:`modules.reels.application.use_cases._admin_support.ensure_agency_exists`).
2. Load the target reel by ``(external_source_id, source_property_id)``.
   404 ``ADMIN_REEL_NOT_FOUND`` if missing.
3. Refuse to mutate reels that have already cleared the editorial gate:
   ``workflow_state == 'approved'`` OR ``publish_status == 'published'``
   surfaces as **409 SUBTITLES_OVERRIDE_LOCKED**.
4. When ``cues`` is non-empty, re-validate the cue invariants
   (uniqueness / monotonicity / window / text length) so the use case is
   self-contained for unit tests even when the Pydantic layer is
   bypassed. Failures raise ``ValidationError`` with a deterministic
   code so the router surfaces a **422**.
5. Persist the override (``None`` / empty list → SQL NULL via the
   repository's ``_subtitles_override_to_jsonb_param`` helper). Flip
   ``render_status='pending'`` so the editor reflects the in-flight
   re-render.
6. Re-enqueue a fresh ``reel_publish`` job (mirroring features 25 / 35)
   so the worker picks up the override and re-renders. When publish
   prerequisites are missing, the override is still persisted and the
   response carries ``publish_enqueued=False`` — same contract as
   ``regenerate_reel``.

The override itself does **not** travel on ``publish_context`` — the
renderer reads ``reels.subtitles_override`` straight from the persisted
row at ingest time (via ``ingest_property_into_reel`` which forwards it
onto :class:`PropertyContext`). This keeps the job payload stable and
avoids stale ``publish_context`` reads if the override is updated again
between enqueue and dispatch.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence
from uuid import uuid4

from modules.configuration.application.use_cases.compute_next_publish_slot import (
    compute_next_publish_slot,
)
from modules.delivery.domain import JobEnqueueRequest
from modules.reels.application.use_cases._admin_support import (
    ensure_agency_exists,
    reel_not_found_error,
)
from modules.reels.domain import ReelState
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ValidationError


# Workflow / publish gate. The leader's contract for feature 36 is the
# same as feature 35: only reels that have already crossed the approval
# gate (``workflow_state='approved'``) or completed the external publish
# (``publish_status='published'``) are locked. This preserves the
# editor's ability to keep tweaking subtitles while the reel is still
# ``needs_approval`` / ``pending`` / ``rendered`` / empty.
_LOCKED_WORKFLOW_STATES: frozenset[str] = frozenset({"approved"})
_LOCKED_PUBLISH_STATUSES: frozenset[str] = frozenset({"published"})

_MAX_TEXT_LENGTH = 200


class ReelSubtitlesOverrideLockedError(ApplicationError):
    """Raised when the reel cannot accept a subtitles override anymore.

    Mapped to **HTTP 409 SUBTITLES_OVERRIDE_LOCKED** by the transport
    layer so the frontend can keep the subtitle editor disabled with a
    clear error code that is decoupled from the music / descriptions /
    photos locks.
    """

    def __init__(
        self,
        *,
        agency_id: str,
        site_id: str,
        source_property_id: int,
        workflow_state: str,
        publish_status: str,
    ) -> None:
        self.code = "SUBTITLES_OVERRIDE_LOCKED"
        super().__init__(
            "Cannot edit subtitles for a reel that has been approved or "
            "published.",
            context={
                "agency_id": agency_id,
                "site_id": site_id,
                "source_property_id": source_property_id,
                "workflow_state": workflow_state,
                "publish_status": publish_status,
            },
            hint=(
                "Reject the reel or wait until it returns to the review "
                "queue before editing the subtitles."
            ),
        )


@dataclass(frozen=True, slots=True)
class UpdateReelSubtitlesOverrideResult:
    """Return value of the use case."""

    state: ReelState
    subtitles_override: list[dict[str, Any]] | None
    publish_enqueued: bool
    event_id: str | None = None
    job_id: str | None = None
    reason: str | None = None
    hint: str | None = None


_PREREQ_MISSING_HINT = (
    "The subtitles override was saved, but no publish job was queued "
    "because either the original WordPress payload or the agency's GHL "
    "connection is missing. The override will apply the next time the "
    "reel is approved."
)


def _normalize_cue_entries(
    entries: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Coerce the incoming cues into plain dicts.

    Pydantic objects, plain dicts and ``None`` / empty lists are all
    accepted. ``None`` / ``[]`` collapse to ``None`` so callers do not
    have to special-case the "clear" semantics.
    """
    if entries is None:
        return None
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, dict):
            data = dict(entry)
        else:
            data = {
                "index": int(getattr(entry, "index")),
                "text": str(getattr(entry, "text")),
                "in_seconds": float(getattr(entry, "in_seconds")),
                "out_seconds": float(getattr(entry, "out_seconds")),
            }
        normalized.append(
            {
                "index": int(data["index"]),
                "text": str(data["text"]),
                "in_seconds": float(data["in_seconds"]),
                "out_seconds": float(data["out_seconds"]),
            }
        )
    return normalized or None


def _validate_cues(
    *,
    cues: list[dict[str, Any]],
    agency_id: str,
    site_id: str,
    source_property_id: int,
) -> None:
    """Re-check the cue invariants at the use case layer.

    The Pydantic ``ReelSubtitlesOverridePayload`` already enforces the
    same rules; this method ensures the use case is self-contained for
    unit tests and surfaces deterministic error codes consumed by the
    router (``422`` mapping).
    """
    previous_index: int | None = None
    previous_out: float | None = None
    for cue in cues:
        index = int(cue["index"])
        text_value = str(cue["text"])
        in_seconds = float(cue["in_seconds"])
        out_seconds = float(cue["out_seconds"])
        if index < 0:
            raise ValidationError(
                "Subtitle cue index must be non-negative.",
                code="SUBTITLES_OVERRIDE_INVALID_INDEX",
                context={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                    "index": index,
                },
            )
        if not text_value:
            raise ValidationError(
                "Subtitle cue text must not be empty.",
                code="SUBTITLES_OVERRIDE_EMPTY_TEXT",
                context={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                    "index": index,
                },
            )
        if len(text_value) > _MAX_TEXT_LENGTH:
            raise ValidationError(
                "Subtitle cue text is too long.",
                code="SUBTITLES_OVERRIDE_TEXT_TOO_LONG",
                context={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                    "index": index,
                    "max_length": _MAX_TEXT_LENGTH,
                    "received_length": len(text_value),
                },
            )
        if in_seconds < 0:
            raise ValidationError(
                "Subtitle cue in_seconds must be non-negative.",
                code="SUBTITLES_OVERRIDE_NEGATIVE_TIME",
                context={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                    "index": index,
                    "in_seconds": in_seconds,
                },
            )
        if out_seconds <= in_seconds:
            raise ValidationError(
                "Subtitle cue out_seconds must be strictly greater "
                "than in_seconds.",
                code="SUBTITLES_OVERRIDE_INVALID_WINDOW",
                context={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                    "index": index,
                    "in_seconds": in_seconds,
                    "out_seconds": out_seconds,
                },
            )
        if previous_index is not None and index <= previous_index:
            raise ValidationError(
                "Subtitle cue indices must be unique and monotonically "
                "increasing.",
                code="SUBTITLES_OVERRIDE_NON_MONOTONIC_INDEX",
                context={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                    "previous_index": previous_index,
                    "received_index": index,
                },
            )
        if previous_out is not None and in_seconds < previous_out:
            raise ValidationError(
                "Subtitle cue windows must not overlap.",
                code="SUBTITLES_OVERRIDE_OVERLAP",
                context={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                    "previous_out": previous_out,
                    "next_in": in_seconds,
                },
            )
        previous_index = index
        previous_out = out_seconds


class UpdateReelSubtitlesOverrideUseCase:
    """Persist the subtitles override and re-enqueue a render job."""

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
        cues: Sequence[Mapping[str, Any]] | None,
    ) -> UpdateReelSubtitlesOverrideResult:
        if (
            uow.reels is None
            or uow.tenancy is None
            or uow.publishing is None
            or uow.configuration is None
            or uow.delivery is None
            or uow.catalog is None
        ):
            raise RuntimeError("The unit of work is not active.")
        ensure_agency_exists(uow, agency_id)

        normalized_agency_id = str(agency_id or "").strip()
        normalized_site_id = str(site_id or "").strip().lower()
        normalized_property_id = int(source_property_id)
        normalized_override = _normalize_cue_entries(cues)

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

        if (
            existing.workflow_state in _LOCKED_WORKFLOW_STATES
            or existing.publish_status in _LOCKED_PUBLISH_STATUSES
        ):
            raise ReelSubtitlesOverrideLockedError(
                agency_id=normalized_agency_id,
                site_id=normalized_site_id,
                source_property_id=normalized_property_id,
                workflow_state=existing.workflow_state,
                publish_status=existing.publish_status,
            )

        if normalized_override is not None:
            _validate_cues(
                cues=normalized_override,
                agency_id=normalized_agency_id,
                site_id=normalized_site_id,
                source_property_id=normalized_property_id,
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
            # The contract requires the render status to flip to
            # ``pending`` so the editor can show a "rendering" badge
            # while the new job is in flight. The worker will re-stamp
            # it to ``completed`` once the artifacts are persisted.
            render_status="pending",
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
            music_id=existing.music_id,
            photos_override=existing.photos_override,
            subtitles_override=normalized_override,
        )
        uow.reels.states.save(next_state)

        enqueue_result = self._maybe_enqueue_publish_job(
            uow=uow,
            agency_id=normalized_agency_id,
            site_id=normalized_site_id,
            source_property_id=normalized_property_id,
            ingestion_source_id=existing.ingestion_source_id,
            music_id=existing.music_id,
        )
        return UpdateReelSubtitlesOverrideResult(
            state=next_state,
            subtitles_override=normalized_override,
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
        music_id: str | None,
    ) -> dict[str, Any]:
        """Mirror :class:`UpdateReelPhotosOverrideUseCase` for the
        subtitle override re-render.

        Returns the kwargs used to populate
        :class:`UpdateReelSubtitlesOverrideResult`. The override itself
        does **not** travel on ``publish_context`` — the renderer reads
        ``reels.subtitles_override`` straight from the persisted row at
        ingest time (via :class:`PropertyContext`). This keeps the job
        payload stable and avoids stale ``publish_context`` reads if the
        override is updated again between enqueue and dispatch.
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
            # Preserve the per-reel music override on the publish_context
            # so the music swap logic (feature 25) keeps working through
            # the subtitles-driven re-enqueue.
            "override_music_track_id": music_id or None,
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
    "ReelSubtitlesOverrideLockedError",
    "UpdateReelSubtitlesOverrideResult",
    "UpdateReelSubtitlesOverrideUseCase",
]
