"""Persist a per-reel slide manifest override (feature 37).

Use case wired to
``PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/slides``.

Flow:

1. Validate the agency exists (delegates to
   :func:`modules.reels.application.use_cases._admin_support.ensure_agency_exists`).
2. Load the target reel by ``(external_source_id, source_property_id)``.
   404 ``ADMIN_REEL_NOT_FOUND`` if missing.
3. Refuse to mutate reels that have already cleared the editorial gate:
   ``workflow_state == 'approved'`` OR ``publish_status == 'published'``
   surfaces as **409 SLIDES_OVERRIDE_LOCKED**.
4. When ``slides`` is non-empty, re-validate the cross-slide invariants
   (uniqueness, position coverage, duration cap, allowed kinds) so the
   use case is self-contained for unit tests even when the Pydantic
   layer is bypassed. Failures raise ``ValidationError`` with a
   deterministic code so the router surfaces a **422**.
5. Persist the override (``None`` / empty list → SQL NULL via the
   repository's ``_manifest_override_to_jsonb_param`` helper). Flip
   ``render_status='pending'`` so the editor reflects the in-flight
   re-render.
6. Re-enqueue a fresh ``reel_publish`` job (mirroring features 25 / 35
   / 36) so the worker picks up the override and re-renders. When
   publish prerequisites are missing, the override is still persisted
   and the response carries ``publish_enqueued=False`` — same contract
   as ``regenerate_reel``.

The override itself does **not** travel on ``publish_context`` — the
renderer reads ``reels.manifest_override`` straight from the persisted
row at ingest time (via ``ingest_property_into_reel`` which forwards
it onto :class:`PropertyContext`). This keeps the job payload stable
and avoids stale ``publish_context`` reads if the override is updated
again between enqueue and dispatch.

Cross-slide validation rules (mirrors the Pydantic payload):

* ``slide_id`` is a non-empty string, unique within the array.
* ``position`` values cover the range ``[0, N)`` exactly once.
* ``duration_seconds`` is a positive float; the sum across every slide
  is ≤ ``target_duration_seconds * 1.5``. ``target_duration_seconds``
  is the agency's ``agency_reel_defaults.duration_seconds`` when a row
  exists, otherwise the system default ``REEL_TOTAL_DURATION_SECONDS``.
* ``kind`` is one of ``{"photo", "voiceover", "text", "intro_card",
  "outro_card"}``.
* Per-kind required fields are enforced (photo→``photo_position``,
  voiceover→``audio_url``, text→``text``; ``intro_card`` /
  ``outro_card`` have no extra required fields).
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
from settings import REEL_TOTAL_DURATION_SECONDS
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ValidationError


# Workflow / publish gate. Same contract as features 35 / 36: only
# reels that have already crossed the approval gate
# (``workflow_state='approved'``) or completed the external publish
# (``publish_status='published'``) are locked. This preserves the
# editor's ability to keep tweaking the slides while the reel is
# still ``needs_approval`` / ``pending`` / ``rendered`` / empty.
_LOCKED_WORKFLOW_STATES: frozenset[str] = frozenset({"approved"})
_LOCKED_PUBLISH_STATUSES: frozenset[str] = frozenset({"published"})

_ALLOWED_SLIDE_KINDS: frozenset[str] = frozenset(
    {"photo", "voiceover", "text", "intro_card", "outro_card"}
)

# Sum-of-durations multiplier vs. the agency / system target.
_DURATION_CAP_MULTIPLIER = 1.5

# Per-kind required fields beyond the base ``_SlideBase`` shape. Each
# entry maps the discriminator value to the tuple of extra keys the
# use case checks for presence + type. The Pydantic layer enforces the
# same shape; this dict keeps the use case self-contained.
_KIND_REQUIRED_FIELDS: dict[str, tuple[tuple[str, type], ...]] = {
    "photo": (("photo_position", int),),
    "voiceover": (("audio_url", str),),
    "text": (("text", str),),
    "intro_card": (),
    "outro_card": (),
}


class ReelSlidesOverrideLockedError(ApplicationError):
    """Raised when the reel cannot accept a slides override anymore.

    Mapped to **HTTP 409 SLIDES_OVERRIDE_LOCKED** by the transport
    layer so the frontend can keep the slides editor disabled with a
    clear error code that is decoupled from the music / descriptions /
    photos / subtitles locks.
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
        self.code = "SLIDES_OVERRIDE_LOCKED"
        super().__init__(
            "Cannot edit slides for a reel that has been approved or "
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
                "queue before editing the slides."
            ),
        )


@dataclass(frozen=True, slots=True)
class UpdateReelSlidesOverrideResult:
    """Return value of the use case."""

    state: ReelState
    manifest_override: list[dict[str, Any]] | None
    publish_enqueued: bool
    event_id: str | None = None
    job_id: str | None = None
    reason: str | None = None
    hint: str | None = None


_PREREQ_MISSING_HINT = (
    "The slides override was saved, but no publish job was queued "
    "because either the original WordPress payload or the agency's GHL "
    "connection is missing. The override will apply the next time the "
    "reel is approved."
)


def _normalize_slide_entries(
    entries: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Coerce the incoming slides into plain dicts.

    Pydantic objects, plain dicts and ``None`` / empty lists are all
    accepted. ``None`` / ``[]`` collapse to ``None`` so callers do not
    have to special-case the "clear" semantics.

    Optional per-kind fields with ``None`` values are dropped so the
    persisted JSONB stays minimal and round-trips byte-for-byte with
    the input the editor submitted. The required base fields
    (``slide_id``, ``position``, ``duration_seconds``, ``kind``) and
    the required per-kind fields are always preserved.
    """
    if entries is None:
        return None
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if isinstance(entry, dict):
            data = dict(entry)
        elif hasattr(entry, "model_dump"):
            data = entry.model_dump(exclude_none=True)
        else:
            data = dict(entry)
        normalized.append(dict(data))
    return normalized or None


def _resolve_target_duration_seconds(
    *,
    uow: DatabaseUnitOfWork,
    agency_id: str,
) -> float:
    """Resolve the target duration the duration-cap rule uses.

    Reads ``agency_reel_defaults.duration_seconds`` for the agency.
    Falls back to the system default ``REEL_TOTAL_DURATION_SECONDS``
    when the row is missing or carries a non-positive value (the
    frontend onboarding flow seeds the row, but the validator must not
    explode for a freshly-provisioned agency).
    """
    if uow.configuration is None:
        return float(REEL_TOTAL_DURATION_SECONDS)
    defaults = uow.configuration.defaults.get(agency_id)
    if defaults is None:
        return float(REEL_TOTAL_DURATION_SECONDS)
    raw_value = getattr(defaults, "duration_seconds", 0) or 0
    try:
        coerced = float(raw_value)
    except (TypeError, ValueError):
        coerced = 0.0
    if coerced <= 0:
        return float(REEL_TOTAL_DURATION_SECONDS)
    return coerced


def _validate_slides(
    *,
    slides: list[dict[str, Any]],
    agency_id: str,
    site_id: str,
    source_property_id: int,
    target_duration_seconds: float,
) -> None:
    """Re-check the slides invariants at the use case layer."""
    if not slides:
        # Caller already collapses empty → None.
        return
    seen_ids: set[str] = set()
    seen_positions: set[int] = set()
    total_duration = 0.0
    for index, slide in enumerate(slides):
        # ``kind`` discriminator.
        raw_kind = slide.get("kind")
        if not isinstance(raw_kind, str) or raw_kind not in _ALLOWED_SLIDE_KINDS:
            raise ValidationError(
                "Unknown slide ``kind``.",
                code="SLIDES_OVERRIDE_INVALID_KIND",
                context={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                    "slide_index": index,
                    "received": raw_kind,
                    "allowed": sorted(_ALLOWED_SLIDE_KINDS),
                },
                hint="Use one of: " + ", ".join(sorted(_ALLOWED_SLIDE_KINDS)),
            )
        # ``slide_id``.
        raw_slide_id = slide.get("slide_id")
        slide_id = str(raw_slide_id).strip() if raw_slide_id is not None else ""
        if not slide_id:
            raise ValidationError(
                "Slide ``slide_id`` must be a non-empty string.",
                code="SLIDES_OVERRIDE_EMPTY_SLIDE_ID",
                context={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                    "slide_index": index,
                },
            )
        if slide_id in seen_ids:
            raise ValidationError(
                "Duplicate ``slide_id`` in the slides override array.",
                code="SLIDES_OVERRIDE_DUPLICATE_SLIDE_ID",
                context={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                    "slide_index": index,
                    "slide_id": slide_id,
                },
            )
        seen_ids.add(slide_id)
        # ``position``.
        raw_position = slide.get("position")
        try:
            position = int(raw_position)
        except (TypeError, ValueError):
            raise ValidationError(
                "Slide ``position`` must be a non-negative integer.",
                code="SLIDES_OVERRIDE_INVALID_POSITION",
                context={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                    "slide_index": index,
                    "received": raw_position,
                },
            )
        if position < 0:
            raise ValidationError(
                "Slide ``position`` must be a non-negative integer.",
                code="SLIDES_OVERRIDE_INVALID_POSITION",
                context={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                    "slide_index": index,
                    "received": raw_position,
                },
            )
        if position in seen_positions:
            raise ValidationError(
                "Duplicate ``position`` in the slides override array.",
                code="SLIDES_OVERRIDE_DUPLICATE_POSITION",
                context={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                    "slide_index": index,
                    "position": position,
                },
            )
        seen_positions.add(position)
        # ``duration_seconds``.
        raw_duration = slide.get("duration_seconds")
        try:
            duration_value = float(raw_duration)
        except (TypeError, ValueError):
            raise ValidationError(
                "Slide ``duration_seconds`` must be a positive float.",
                code="SLIDES_OVERRIDE_INVALID_DURATION",
                context={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                    "slide_index": index,
                    "received": raw_duration,
                },
            )
        if duration_value <= 0:
            raise ValidationError(
                "Slide ``duration_seconds`` must be a positive float.",
                code="SLIDES_OVERRIDE_INVALID_DURATION",
                context={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                    "slide_index": index,
                    "received": raw_duration,
                },
            )
        total_duration += duration_value
        # Per-kind required fields.
        for field_name, field_type in _KIND_REQUIRED_FIELDS[raw_kind]:
            if field_name not in slide:
                raise ValidationError(
                    f"Slide of kind {raw_kind!r} is missing required "
                    f"field {field_name!r}.",
                    code="SLIDES_OVERRIDE_MISSING_KIND_FIELD",
                    context={
                        "agency_id": agency_id,
                        "site_id": site_id,
                        "source_property_id": source_property_id,
                        "slide_index": index,
                        "slide_id": slide_id,
                        "kind": raw_kind,
                        "missing_field": field_name,
                    },
                )
            raw_field_value = slide[field_name]
            if field_type is int:
                try:
                    coerced_int = int(raw_field_value)
                except (TypeError, ValueError):
                    raise ValidationError(
                        f"Slide field {field_name!r} must be an integer.",
                        code="SLIDES_OVERRIDE_INVALID_KIND_FIELD",
                        context={
                            "agency_id": agency_id,
                            "site_id": site_id,
                            "source_property_id": source_property_id,
                            "slide_index": index,
                            "kind": raw_kind,
                            "field": field_name,
                            "received": raw_field_value,
                        },
                    )
                if coerced_int < 0:
                    raise ValidationError(
                        f"Slide field {field_name!r} must be >= 0.",
                        code="SLIDES_OVERRIDE_INVALID_KIND_FIELD",
                        context={
                            "agency_id": agency_id,
                            "site_id": site_id,
                            "source_property_id": source_property_id,
                            "slide_index": index,
                            "kind": raw_kind,
                            "field": field_name,
                            "received": raw_field_value,
                        },
                    )
            elif field_type is str:
                if not isinstance(raw_field_value, str) or not raw_field_value.strip():
                    raise ValidationError(
                        f"Slide field {field_name!r} must be a non-empty string.",
                        code="SLIDES_OVERRIDE_INVALID_KIND_FIELD",
                        context={
                            "agency_id": agency_id,
                            "site_id": site_id,
                            "source_property_id": source_property_id,
                            "slide_index": index,
                            "kind": raw_kind,
                            "field": field_name,
                            "received": raw_field_value,
                        },
                    )
    # Position coverage check.
    expected_positions = list(range(len(slides)))
    if sorted(seen_positions) != expected_positions:
        raise ValidationError(
            "Slide ``position`` values must cover the range "
            f"``[0, {len(slides)})`` exactly once.",
            code="SLIDES_OVERRIDE_POSITION_GAP",
            context={
                "agency_id": agency_id,
                "site_id": site_id,
                "source_property_id": source_property_id,
                "expected_positions": expected_positions,
                "received_positions": sorted(seen_positions),
            },
        )
    # Duration cap.
    cap = target_duration_seconds * _DURATION_CAP_MULTIPLIER
    # Tolerate float rounding (rendered durations are float-encoded
    # through JSONB).
    if total_duration > cap + 1e-6:
        raise ValidationError(
            "Sum of slide ``duration_seconds`` exceeds "
            f"``target_duration_seconds * {_DURATION_CAP_MULTIPLIER}``.",
            code="SLIDES_OVERRIDE_DURATION_CAP_EXCEEDED",
            context={
                "agency_id": agency_id,
                "site_id": site_id,
                "source_property_id": source_property_id,
                "target_duration_seconds": target_duration_seconds,
                "cap_multiplier": _DURATION_CAP_MULTIPLIER,
                "cap_seconds": cap,
                "received_total_seconds": total_duration,
            },
            hint=(
                "Trim slide durations so the total stays within "
                f"{cap:.3f} seconds, or raise the agency's "
                "``duration_seconds`` default."
            ),
        )


class UpdateReelSlidesOverrideUseCase:
    """Persist the slides override and re-enqueue a render job."""

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
        slides: Sequence[Mapping[str, Any]] | None,
    ) -> UpdateReelSlidesOverrideResult:
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
        normalized_override = _normalize_slide_entries(slides)

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
            raise ReelSlidesOverrideLockedError(
                agency_id=normalized_agency_id,
                site_id=normalized_site_id,
                source_property_id=normalized_property_id,
                workflow_state=existing.workflow_state,
                publish_status=existing.publish_status,
            )

        if normalized_override is not None:
            target_duration = _resolve_target_duration_seconds(
                uow=uow,
                agency_id=normalized_agency_id,
            )
            _validate_slides(
                slides=normalized_override,
                agency_id=normalized_agency_id,
                site_id=normalized_site_id,
                source_property_id=normalized_property_id,
                target_duration_seconds=target_duration,
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
            subtitles_override=existing.subtitles_override,
            manifest_override=normalized_override,
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
        return UpdateReelSlidesOverrideResult(
            state=next_state,
            manifest_override=normalized_override,
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
        slides override re-render.

        Returns the kwargs used to populate
        :class:`UpdateReelSlidesOverrideResult`. The override itself
        does **not** travel on ``publish_context`` — the renderer reads
        ``reels.manifest_override`` straight from the persisted row at
        ingest time (via :class:`PropertyContext`). This keeps the job
        payload stable and avoids stale ``publish_context`` reads if
        the override is updated again between enqueue and dispatch.
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
            # the slides-driven re-enqueue.
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
    "ReelSlidesOverrideLockedError",
    "UpdateReelSlidesOverrideResult",
    "UpdateReelSlidesOverrideUseCase",
]
