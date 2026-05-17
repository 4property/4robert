"""Persist a per-reel caption override (feature 21).

Use case wired to ``PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/descriptions``.

Flow:

1. Validate the agency exists (delegates to
   :func:`modules.reels.application.use_cases._admin_support.ensure_agency_exists`).
2. Load the target reel by ``(external_source_id, source_property_id)``.
   404 ``ADMIN_REEL_NOT_FOUND`` if missing.
3. Refuse to mutate reels that have already cleared the editorial gate
   (``publish_status`` outside ``{"needs-approval", "pending_review"}``).
   The endpoint surfaces this as **409** with code
   ``REEL_NOT_EDITABLE`` so the frontend can keep the editor disabled.
4. Validate every platform key against
   ``agency_reel_defaults.platforms``. Unknown platforms produce a
   **422** with code ``PLATFORM_NOT_ENABLED``.
5. Replace ``reels.descriptions_override`` wholesale with the supplied
   payload (the client always submits the complete shape, matching the
   editor's UX where every enabled platform is rendered side-by-side).

The use case never opens its own UoW — the router owns the lifecycle so
the override write commits in the same transaction as any future
side-effects the same request may add. No ``session.commit()`` is
called from inside the repository: the UoW context manager handles it
on a clean exit, matching the layer rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from modules.reels.application.use_cases._admin_support import (
    ensure_agency_exists,
    reel_not_found_error,
)
from modules.reels.domain import ReelState
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ValidationError


_EDITABLE_PUBLISH_STATUSES: frozenset[str] = frozenset(
    {
        # ``needs-approval`` is the canonical post-render gate emitted
        # by the worker when ``approval_required=True`` or
        # ``REVIEW_WORKFLOW_ENABLED`` keeps a reel parked until a human
        # approves it. ``pending_review`` is the legacy alias still
        # carried by older rows seeded before feature 14; we accept
        # both so the editor stays usable across deployments.
        "needs-approval",
        "pending_review",
        # Brand-new reels in the renderer pipeline can still be edited:
        # the override sits dormant until the worker re-runs ingest and
        # picks it up. ``pending`` covers the freshly-ingested state
        # (set by ``_build_ingested_reel_state``) so the editor remains
        # usable while the render is in flight.
        "pending",
        # An empty publish_status is the case for a reel that was
        # ingested but never queued for external publishing — the
        # editor is still relevant because the agency may flip the
        # toggle later.
        "",
    }
)


class ReelNotEditableError(ApplicationError):
    """Raised when the reel's ``publish_status`` no longer allows edits.

    Mapped to HTTP **409 RESOURCE_LOCKED** by the transport layer. The
    code (``REEL_NOT_EDITABLE``) is the canonical signal for the
    frontend: it disables the description editor and surfaces a
    "reel already approved/published" banner.
    """

    def __init__(
        self,
        *,
        agency_id: str,
        site_id: str,
        source_property_id: int,
        publish_status: str,
    ) -> None:
        self.code = "REEL_NOT_EDITABLE"
        super().__init__(
            "The reel can no longer be edited because it has cleared the "
            "review gate.",
            context={
                "agency_id": agency_id,
                "site_id": site_id,
                "source_property_id": source_property_id,
                "publish_status": publish_status,
            },
            hint=(
                "Only reels still pending review accept caption overrides. "
                "Reject the reel and re-approve it to edit the captions."
            ),
        )


@dataclass(frozen=True, slots=True)
class UpdateReelDescriptionsOverrideResult:
    """Return value of the use case (the post-update reel state)."""

    state: ReelState


class UpdateReelDescriptionsOverrideUseCase:
    """Persist the override payload for ``(site_id, source_property_id)``."""

    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
        site_id: str,
        source_property_id: int,
        descriptions_by_platform: Mapping[str, str],
    ) -> UpdateReelDescriptionsOverrideResult:
        if uow.reels is None or uow.configuration is None:
            raise RuntimeError("The unit of work is not active.")
        ensure_agency_exists(uow, agency_id)

        normalized_agency_id = str(agency_id or "").strip()
        normalized_site_id = str(site_id or "").strip().lower()
        normalized_property_id = int(source_property_id)

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

        defaults = uow.configuration.defaults.get(normalized_agency_id)
        enabled_platforms: tuple[str, ...] = (
            tuple(defaults.platforms) if defaults is not None else ()
        )
        normalized_enabled = {str(p).strip().lower() for p in enabled_platforms}

        # Validate every payload key. We require *all* keys to be known
        # — partial-acceptance would silently swallow a typo and let the
        # editor save an override that never reaches publish time.
        unknown_platforms = sorted(
            str(platform).strip()
            for platform in descriptions_by_platform.keys()
            if str(platform).strip().lower() not in normalized_enabled
        )
        if unknown_platforms:
            raise ValidationError(
                "One or more platforms are not enabled for this agency.",
                code="PLATFORM_NOT_ENABLED",
                context={
                    "agency_id": normalized_agency_id,
                    "site_id": normalized_site_id,
                    "source_property_id": normalized_property_id,
                    "unknown_platforms": unknown_platforms,
                    "enabled_platforms": list(enabled_platforms),
                },
                hint=(
                    "Edit only platforms present in the agency's "
                    "``agency_reel_defaults.platforms`` list."
                ),
            )

        # Replace semantics: the editor always submits the full shape,
        # so we wipe-and-write. ``None``/empty payload is normalised to
        # SQL ``NULL`` by the repository (``_override_to_jsonb_param``).
        coerced_override: dict[str, str] = {
            str(platform): str(text) for platform, text in descriptions_by_platform.items()
        }

        next_state = ReelState(
            agency_id=existing.agency_id,
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
            descriptions_override=coerced_override or None,
        )
        uow.reels.states.save(next_state)

        return UpdateReelDescriptionsOverrideResult(state=next_state)


__all__ = [
    "ReelNotEditableError",
    "UpdateReelDescriptionsOverrideResult",
    "UpdateReelDescriptionsOverrideUseCase",
]
