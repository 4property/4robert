"""Publish a rendered reel to social platforms (step 4 of the pipeline).

This use case takes a locally-persisted reel artifact and delivers it to
the configured social provider (today: GoHighLevel). It owns the
publish-side workflow transition: bumps `reels` to
`workflow_state='published'/'partial'/'awaiting_review'/'skipped'/'failed'`,
appends a `media_revisions` row mirroring the new state, and emits an
`outbox_events` row whose `event_type`
(`publish_completed` / `publish_skipped` / `publish_failed` /
`review_requested`) reflects the final decision. When the provider
returns a 2xx aggregate result and the workflow lands on
`publish_completed`, the outbox row is written with `status='completed'`
so consumers see it as already delivered (the relay only picks up
`status='pending'`).

Replaces the body of `CompositeMediaPublisher` from
`application/pipeline/media_services.py`. The legacy class survives as a
thin adapter so `application/bootstrap/{runtime,__init__}.py` keep
working without structural changes; feature 14 collapses both.

Helpers `_now_iso`, `_relative_path_text`, `_build_workflow_payload` are
duplicated here from features 11/12 (`prepare_reel_assets.py` and
`persist_local_artifacts.py`). Same trade-off documented there: feature
14 will unify.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from modules.reels.domain.types import (
    PropertyContext,
    PublishedMediaArtifact,
    RenderedMediaArtifact,
)
from shared.errors import (
    SocialPublishingResultError,
    TransientSocialPublishingResultError,
    extract_error_details,
)
from shared.observability import (
    format_console_block,
    format_context_line,
    format_detail_line,
)
from modules.reels.domain import MediaRevision
from settings import REVIEW_WORKFLOW_ENABLED
from shared.db import DatabaseUnitOfWork

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module helpers (duplicated from media_services.py — see module docstring).
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _relative_path_text(base_dir: Path, path: Path | None) -> str:
    if path is None:
        return ""
    resolved_path = path.resolve()
    try:
        return str(resolved_path.relative_to(base_dir))
    except ValueError:
        return str(resolved_path)


def _build_workflow_payload(
    context: PropertyContext,
    *,
    workflow_state: str,
    revision_id: str = "",
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "site_id": context.site_id,
        "property_id": context.property.id,
        "slug": context.property.slug,
        "listing_lifecycle": context.delivery_plan.listing_lifecycle,
        "render_profile": context.delivery_plan.render_profile,
        "artifact_kind": context.delivery_plan.artifact_kind,
        "workflow_state": workflow_state,
    }
    if revision_id:
        payload["revision_id"] = revision_id
    if context.publish_context is not None:
        payload["location_id"] = context.publish_context.location_id
        payload["platforms"] = list(
            context.pending_publish_platforms or context.publish_context.platforms
        )
    if context.publish_targets:
        payload["publish_targets"] = {
            target.platform: {
                "artifact_kind": target.artifact_kind,
                "social_post_type": target.social_post_type,
            }
            for target in context.publish_targets
        }
    if extra:
        payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Use case
# ---------------------------------------------------------------------------


class PublishReelUseCase:
    """Step 4 of the reel pipeline: publish locally-persisted artifacts.

    Coordinates the local publisher (step 3, `PersistLocalArtifactsUseCase`
    via the `FileSystemMediaPublisher` adapter) and the social provider
    publisher. The workflow transition to `published`/`partial`/`failed`/
    `awaiting_review`/`skipped` plus the matching `media_revisions` /
    `outbox_events` rows are owned by this use case.
    """

    def __init__(
        self,
        *,
        local_publisher: Any,
        workspace_dir: str | Path | None = None,
        social_publisher: Any | None = None,
        database_locator: str | Path | None = None,
    ) -> None:
        self.local_publisher = local_publisher
        self.workspace_dir = (
            None
            if workspace_dir is None
            else Path(workspace_dir).expanduser().resolve()
        )
        self.social_publisher = social_publisher
        if database_locator is None:
            from settings import DATABASE_URL

            database_locator = DATABASE_URL
        self.database_locator = database_locator

    def execute(
        self,
        context: PropertyContext,
        rendered_media: RenderedMediaArtifact,
        *,
        uow: DatabaseUnitOfWork | None = None,
    ) -> PublishedMediaArtifact:
        published_media = self.local_publisher.publish_media(context, rendered_media)
        return self._publish_externally(context, published_media, uow=uow)

    def execute_existing(
        self,
        context: PropertyContext,
        *,
        uow: DatabaseUnitOfWork | None = None,
    ) -> PublishedMediaArtifact:
        published_media = self.local_publisher.publish_existing_media(context)
        return self._publish_externally(context, published_media, uow=uow)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _publish_externally(
        self,
        context: PropertyContext,
        published_media: PublishedMediaArtifact,
        *,
        uow: DatabaseUnitOfWork | None,
    ) -> PublishedMediaArtifact:
        if (
            self.social_publisher is None
            or not context.requires_external_publish
            or context.publish_context is None
        ):
            self._publish_with_uow(
                context=context,
                published_media=published_media,
                workflow_state="skipped",
                outbox_event_type="publish_skipped",
                publish_status="skipped",
                details={"reason": "not_required"},
                uow=uow,
            )
            return published_media

        # Per-agency setting wins over the global env flag. Either signal
        # holds the reel in `awaiting_review` until a human approves it
        # via the editor's Approve / Reject controls.
        agency_review_required = bool(
            getattr(context.publish_context, "approval_required", False)
        )
        logger.info(
            format_console_block(
                "Publish Gating Decision",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line(
                    "Agency approval_required",
                    "Yes" if agency_review_required else "No",
                ),
                format_detail_line(
                    "REVIEW_WORKFLOW_ENABLED env",
                    "Yes" if REVIEW_WORKFLOW_ENABLED else "No",
                ),
                format_detail_line(
                    "Will hold for review",
                    "Yes" if (agency_review_required or REVIEW_WORKFLOW_ENABLED) else "No",
                ),
            )
        )
        if agency_review_required or REVIEW_WORKFLOW_ENABLED:
            self._publish_with_uow(
                context=context,
                published_media=published_media,
                workflow_state="awaiting_review",
                outbox_event_type="review_requested",
                publish_status="pending_review",
                details={
                    "reason": (
                        "agency_approval_required"
                        if agency_review_required
                        else "review_workflow_enabled"
                    ),
                },
                last_published_provider_external_id=context.publish_context.location_id,
                uow=uow,
            )
            logger.info(
                format_console_block(
                    "Review Requested",
                    format_detail_line("Site ID", context.site_id),
                    format_detail_line("Property ID", context.property.id),
                    format_detail_line(
                        "Revision ID", published_media.revision_id or "<none>"
                    ),
                    format_detail_line("Location ID", context.publish_context.location_id),
                )
            )
            return published_media

        logger.info(
            format_console_block(
                "Social Media Publish Started",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line("Artifact kind", published_media.artifact_kind),
                format_detail_line(
                    "Revision ID", published_media.revision_id or "<none>"
                ),
                format_detail_line("Location ID", context.publish_context.location_id),
                format_detail_line(
                    "Desired platforms", ", ".join(context.pending_publish_platforms)
                ),
                format_detail_line(
                    "Publish targets",
                    ", ".join(
                        f"{target.platform}:{target.artifact_kind}"
                        for target in context.publish_targets
                        if target.platform in context.pending_publish_platforms
                    )
                    or "<none>",
                ),
            )
        )

        try:
            publish_result = self.social_publisher.publish_property_media(
                context, published_media
            )
        except Exception as error:
            failure_details = extract_error_details(error)
            if isinstance(
                error,
                (SocialPublishingResultError, TransientSocialPublishingResultError),
            ) and getattr(error, "result", None) is not None:
                result = error.result
                to_dict = getattr(result, "to_dict", None)
                if callable(to_dict):
                    failure_details = to_dict()
            logger.error(
                format_console_block(
                    "Social Media Publish Failed",
                    format_detail_line("Site ID", context.site_id),
                    format_detail_line("Property ID", context.property.id),
                    format_detail_line("Location ID", context.publish_context.location_id),
                    format_detail_line("Error stage", failure_details.get("stage")),
                    format_detail_line("Error code", failure_details.get("code")),
                    format_detail_line(
                        "Error", failure_details.get("message") or error
                    ),
                    format_context_line(
                        failure_details.get("context")
                        if isinstance(failure_details.get("context"), dict)
                        else None
                    ),
                )
            )
            self._publish_with_uow(
                context=context,
                published_media=published_media,
                workflow_state="failed",
                outbox_event_type="publish_failed",
                publish_status="failed",
                details=failure_details,
                last_published_provider_external_id=context.publish_context.location_id,
                uow=uow,
            )
            raise

        if publish_result is None:
            self._publish_with_uow(
                context=context,
                published_media=published_media,
                workflow_state="skipped",
                outbox_event_type="publish_skipped",
                publish_status="skipped",
                details={"reason": "not_required"},
                uow=uow,
            )
            return published_media

        publish_details = self._build_publish_details(publish_result)
        aggregate_status = publish_result.aggregate_status
        is_completed_path = aggregate_status in {"published", "partial"}
        outbox_event_type = (
            "publish_completed" if is_completed_path else "publish_failed"
        )
        outbox_status = "completed" if is_completed_path else "pending"
        self._publish_with_uow(
            context=context,
            published_media=published_media,
            workflow_state=aggregate_status,
            outbox_event_type=outbox_event_type,
            publish_status=aggregate_status,
            details=publish_details,
            last_published_provider_external_id=context.publish_context.location_id,
            outbox_status=outbox_status,
            uow=uow,
        )

        logger.info(
            format_console_block(
                "Social Media Publish Completed",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line("Artifact kind", published_media.artifact_kind),
                format_detail_line(
                    "Revision ID", published_media.revision_id or "<none>"
                ),
                format_detail_line(
                    "Desired platforms", ", ".join(context.pending_publish_platforms)
                ),
                format_detail_line(
                    "Successful platforms",
                    ", ".join(publish_result.successful_platforms),
                ),
                format_detail_line("Aggregate status", aggregate_status),
                format_detail_line("Location ID", context.publish_context.location_id),
            )
        )
        return published_media

    def _publish_with_uow(
        self,
        *,
        context: PropertyContext,
        published_media: PublishedMediaArtifact,
        workflow_state: str,
        outbox_event_type: str,
        publish_status: str | None = None,
        details: dict[str, object] | None = None,
        last_published_provider_external_id: str = "",
        outbox_status: str = "pending",
        uow: DatabaseUnitOfWork | None,
    ) -> None:
        if uow is None:
            with DatabaseUnitOfWork(
                self.database_locator, base_dir=self.workspace_dir
            ) as managed_uow:
                self._persist_with_uow(
                    context=context,
                    published_media=published_media,
                    workflow_state=workflow_state,
                    outbox_event_type=outbox_event_type,
                    publish_status=publish_status,
                    details=details,
                    last_published_provider_external_id=last_published_provider_external_id,
                    outbox_status=outbox_status,
                    uow=managed_uow,
                )
        else:
            self._persist_with_uow(
                context=context,
                published_media=published_media,
                workflow_state=workflow_state,
                outbox_event_type=outbox_event_type,
                publish_status=publish_status,
                details=details,
                last_published_provider_external_id=last_published_provider_external_id,
                outbox_status=outbox_status,
                uow=uow,
            )

    @staticmethod
    def _persist_with_uow(
        *,
        context: PropertyContext,
        published_media: PublishedMediaArtifact,
        workflow_state: str,
        outbox_event_type: str,
        publish_status: str | None,
        details: dict[str, object] | None,
        last_published_provider_external_id: str,
        outbox_status: str,
        uow: DatabaseUnitOfWork,
    ) -> None:
        if uow.reels is None or uow.delivery is None:
            raise RuntimeError("The unit of work is not active.")
        normalized_external_source_id = str(context.site_id or "").strip().lower()
        if publish_status is not None:
            uow.reels.states.update_publish_status(
                agency_id=context.tenant.agency_id,
                ingestion_source_id=context.tenant.wordpress_source_id,
                external_source_id=normalized_external_source_id,
                source_property_id=context.property.id,
                status=publish_status,
                details=details,
                last_published_provider_external_id=last_published_provider_external_id,
            )
        uow.reels.states.update_workflow_state(
            agency_id=context.tenant.agency_id,
            ingestion_source_id=context.tenant.wordpress_source_id,
            external_source_id=normalized_external_source_id,
            source_property_id=context.property.id,
            workflow_state=workflow_state,
            current_revision_id=published_media.revision_id or None,
        )
        if published_media.revision_id:
            uow.reels.revisions.save_revision(
                MediaRevision(
                    revision_id=published_media.revision_id,
                    agency_id=context.tenant.agency_id,
                    ingestion_source_id=context.tenant.wordpress_source_id,
                    external_source_id=normalized_external_source_id,
                    source_property_id=context.property.id,
                    artifact_kind=published_media.artifact_kind,
                    render_profile=context.delivery_plan.render_profile,
                    media_path=_relative_path_text(
                        context.workspace_dir, published_media.media_path
                    ),
                    metadata_path=_relative_path_text(
                        context.workspace_dir, published_media.metadata_path
                    ),
                    mime_type=published_media.mime_type,
                    content_fingerprint=context.content_fingerprint,
                    publish_target_fingerprint=context.publish_target_fingerprint,
                    workflow_state=workflow_state,
                    created_at=_now_iso(),
                )
            )
        uow.delivery.outbox.add_event(
            event_id=uuid4().hex,
            aggregate_type="property_media",
            aggregate_id=f"{context.site_id}:{context.property.id}",
            event_type=outbox_event_type,
            payload=_build_workflow_payload(
                context,
                workflow_state=workflow_state,
                revision_id=published_media.revision_id,
                extra=details,
            ),
            agency_id=context.tenant.agency_id,
            ingestion_source_id=context.tenant.wordpress_source_id,
            external_source_id=normalized_external_source_id,
            source_property_id=context.property.id,
            status=outbox_status,
            created_at=_now_iso(),
        )

    @staticmethod
    def _build_publish_details(publish_result: Any) -> dict[str, object]:
        return publish_result.to_dict()


__all__ = [
    "PublishReelUseCase",
]
