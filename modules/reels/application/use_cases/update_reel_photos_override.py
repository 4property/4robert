"""Persist a per-reel photo override (feature 35).

Use case wired to
``PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/photos``.

Flow:

1. Validate the agency exists (delegates to
   :func:`modules.reels.application.use_cases._admin_support.ensure_agency_exists`).
2. Load the target reel by ``(external_source_id, source_property_id)``.
   404 ``ADMIN_REEL_NOT_FOUND`` if missing.
3. Refuse to mutate reels that have already cleared the editorial gate:
   ``workflow_state == 'approved'`` OR ``publish_status == 'published'``
   surfaces as **409 PHOTOS_OVERRIDE_LOCKED**.
4. When ``photos`` is non-empty, compute ``N`` from
   ``uow.catalog.images.list_for_property`` and validate the entries:

   * positions must be unique (the Pydantic layer already rejects the
     duplicate case, but the use case re-checks to keep the contract
     self-contained for unit tests);
   * every entry's ``position`` must be inside ``[0, N)``;
   * the positions must cover the range ``[0, N)`` exactly once.

   Any of those failures raise ``ValidationError`` with a deterministic
   code so the router can surface a **422**.
5. Persist the override (``None`` / empty list → SQL NULL via the
   repository's ``_photos_override_to_jsonb_param`` helper).
6. Re-enqueue a fresh ``reel_publish`` job (mirroring feature 25's
   :class:`UpdateReelMusicOverrideUseCase`) so the worker picks up the
   override and re-renders with the new order. When publish
   prerequisites are missing (no original payload, no GHL connection),
   the use case still persists the override and returns
   ``publish_enqueued=False`` — same contract as ``regenerate_reel``.
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


# Workflow / publish gate. The leader's contract for feature 35 is more
# permissive than feature 21/25: only reels that have already crossed
# the approval gate (``workflow_state='approved'``) or completed the
# external publish (``publish_status='published'``) are locked. This
# preserves the editor's ability to edit a reel that is still
# ``needs_approval`` / ``pending`` / ``rendered`` / empty.
_LOCKED_WORKFLOW_STATES: frozenset[str] = frozenset({"approved"})
_LOCKED_PUBLISH_STATUSES: frozenset[str] = frozenset({"published"})


class ReelPhotosOverrideLockedError(ApplicationError):
    """Raised when the reel cannot accept a photos override anymore.

    Mapped to **HTTP 409 PHOTOS_OVERRIDE_LOCKED** by the transport layer
    so the frontend can keep the photo editor disabled with a clear
    error code that is decoupled from the music / descriptions locks.
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
        self.code = "PHOTOS_OVERRIDE_LOCKED"
        super().__init__(
            "Cannot edit photos for a reel that has been approved or "
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
                "queue before editing the photo order."
            ),
        )


@dataclass(frozen=True, slots=True)
class UpdateReelPhotosOverrideResult:
    """Return value of the use case."""

    state: ReelState
    photos_override: list[dict[str, Any]] | None
    publish_enqueued: bool
    event_id: str | None = None
    job_id: str | None = None
    reason: str | None = None
    hint: str | None = None


_PREREQ_MISSING_HINT = (
    "The photos override was saved, but no publish job was queued "
    "because either the original WordPress payload or the agency's GHL "
    "connection is missing. The override will apply the next time the "
    "reel is approved."
)


def _normalize_override_entries(
    entries: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Coerce the incoming entries into plain dicts.

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
                "position": int(getattr(entry, "position")),
                "selected": bool(getattr(entry, "selected")),
            }
        normalized.append(
            {
                "position": int(data["position"]),
                "selected": bool(data["selected"]),
            }
        )
    return normalized or None


def _validate_positions_against_n(
    *,
    entries: list[dict[str, Any]],
    photo_count: int,
    agency_id: str,
    site_id: str,
    source_property_id: int,
) -> None:
    if photo_count <= 0:
        raise ValidationError(
            "Cannot persist a photos override because the property has "
            "no images registered yet.",
            code="PHOTOS_OVERRIDE_NO_PHOTOS",
            context={
                "agency_id": agency_id,
                "site_id": site_id,
                "source_property_id": source_property_id,
                "photo_count": int(photo_count),
            },
            hint=(
                "Ingest the property first so the catalog has the "
                "photo set before sending an override."
            ),
        )
    positions = [int(entry["position"]) for entry in entries]
    if len(positions) != photo_count:
        raise ValidationError(
            "The photos override must reference every available photo "
            "exactly once.",
            code="PHOTOS_OVERRIDE_LENGTH_MISMATCH",
            context={
                "agency_id": agency_id,
                "site_id": site_id,
                "source_property_id": source_property_id,
                "expected_count": int(photo_count),
                "received_count": int(len(positions)),
            },
        )
    seen: set[int] = set()
    for position in positions:
        if position in seen:
            raise ValidationError(
                "Duplicate photo position in the override array.",
                code="PHOTOS_OVERRIDE_DUPLICATE_POSITION",
                context={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                    "position": int(position),
                },
            )
        seen.add(position)
        if position < 0 or position >= photo_count:
            raise ValidationError(
                "Photo position is out of range.",
                code="PHOTOS_OVERRIDE_POSITION_OUT_OF_RANGE",
                context={
                    "agency_id": agency_id,
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                    "position": int(position),
                    "photo_count": int(photo_count),
                },
            )
    # Coverage check: positions are unique, in range and the count
    # matches ``photo_count`` — by pigeonhole they must cover ``[0, N)``
    # exactly once. The explicit ``sorted(seen) == range(...)`` is
    # redundant but kept as a defensive guard in case the invariants
    # above are ever weakened.
    if sorted(seen) != list(range(photo_count)):  # pragma: no cover
        raise ValidationError(
            "Photo positions do not cover the [0, N) range.",
            code="PHOTOS_OVERRIDE_GAP",
            context={
                "agency_id": agency_id,
                "site_id": site_id,
                "source_property_id": source_property_id,
                "photo_count": int(photo_count),
            },
        )


class UpdateReelPhotosOverrideUseCase:
    """Persist the photos override and re-enqueue a render job."""

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
        photos: Sequence[Mapping[str, Any]] | None,
    ) -> UpdateReelPhotosOverrideResult:
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
        normalized_override = _normalize_override_entries(photos)

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
            raise ReelPhotosOverrideLockedError(
                agency_id=normalized_agency_id,
                site_id=normalized_site_id,
                source_property_id=normalized_property_id,
                workflow_state=existing.workflow_state,
                publish_status=existing.publish_status,
            )

        if normalized_override is not None:
            photos_in_catalog = uow.catalog.images.list_for_property(
                external_source_id=normalized_site_id,
                source_property_id=normalized_property_id,
            )
            _validate_positions_against_n(
                entries=normalized_override,
                photo_count=len(photos_in_catalog),
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
            # The leader's contract requires the render status to flip
            # to ``pending`` so the editor can show a "rendering" badge
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
            photos_override=normalized_override,
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
        return UpdateReelPhotosOverrideResult(
            state=next_state,
            photos_override=normalized_override,
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
        """Mirror :class:`UpdateReelMusicOverrideUseCase` for the photos
        override re-render.

        Returns the kwargs used to populate
        :class:`UpdateReelPhotosOverrideResult`. The override itself
        does **not** travel on ``publish_context`` — the renderer reads
        ``reels.photos_override`` straight from the persisted row at
        render time (via the ingest use case, which forwards it onto
        :class:`PropertyContext`). This keeps the job payload stable and
        avoids stale ``publish_context`` reads if the override is
        updated again between enqueue and dispatch.
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
            # the photos-driven re-enqueue.
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
    "ReelPhotosOverrideLockedError",
    "UpdateReelPhotosOverrideResult",
    "UpdateReelPhotosOverrideUseCase",
]
