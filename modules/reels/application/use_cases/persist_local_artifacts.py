"""Persist local media artifacts (step 3 of the reels pipeline).

This is step 3 of the property media pipeline (was the body of
`FileSystemMediaPublisher.publish_media` in
`application/pipeline/media_services.py`).

Responsibilities:
  - resolve the canonical output directory for the rendered artifact
    (`generated_reels_root` / `generated_posters_root`) and atomically
    promote the staged mp4 + manifest + poster into it;
  - clean up the render staging directory when the cleanup flag is on;
  - persist the workflow transition: bump `reels` to
    `workflow_state='rendered'` + `render_status='completed'`, append a
    `media_revisions` row, enqueue an `outbox_events` row with
    `event_type='media_rendered'`;
  - return a `PublishedMediaArtifact` value the legacy step 4
    (`CompositeMediaPublisher`, still living in
    `application/pipeline/media_services.py`) can consume.

Bridge note (Phase 2): the legacy `FileSystemMediaPublisher` adapter in
`application/pipeline/media_services.py` accepts the historic
`unit_of_work_factory` to keep the bootstrap signature stable, but that
factory is **not** consulted from this use case — the use case opens its
own modern `DatabaseUnitOfWork`. Feature 14 will collapse the bridge once
the renderer also migrates.

Helpers `_now_iso`, `_relative_path_text`, `_build_workflow_payload` are
duplicated here from `application/pipeline/media_services.py` (where the
legacy step 4 still uses them) on purpose, so the two use cases can evolve
independently. Same trade-off as `_build_property_record` between this
module and `prepare_reel_assets.py` / `ingest_property_into_reel.py`.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from modules.reels.domain.types import (
    PropertyContext,
    PublishedMediaArtifact,
    RenderedMediaArtifact,
)
from shared.errors import ValidationError
from shared.media_cleanup import (
    DEFAULT_DELETE_TEMPORARY_FILES,
    should_cleanup_render_staging_dir,
)
from shared.observability import build_log_context, format_console_block, format_detail_line
from modules.reels.domain import MediaRevision
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
        "render_template_id": context.render_template_id,
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


class PersistLocalArtifactsUseCase:
    """Step 3 of the reel pipeline: persist locally-rendered artifacts."""

    def __init__(
        self,
        workspace_dir: str | Path,
        *,
        cleanup_temporary_files: bool = DEFAULT_DELETE_TEMPORARY_FILES,
        database_locator: str | Path | None = None,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.cleanup_temporary_files = bool(cleanup_temporary_files)
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
        revision_id = rendered_media.revision_id or uuid4().hex
        final_output_dir = self._resolve_output_dir(context, rendered_media.artifact_kind)
        final_output_dir.mkdir(parents=True, exist_ok=True)
        final_media_path = final_output_dir / rendered_media.media_path.name
        final_metadata_path = (
            None
            if rendered_media.metadata_path is None
            else final_output_dir / rendered_media.metadata_path.name
        )
        final_poster_path = self._publish_related_poster(context, rendered_media)

        if rendered_media.metadata_path is not None and final_metadata_path is not None:
            self._replace_atomically(rendered_media.metadata_path, final_metadata_path)
        self._replace_atomically(rendered_media.media_path, final_media_path)
        if should_cleanup_render_staging_dir(self.cleanup_temporary_files):
            shutil.rmtree(rendered_media.staging_dir, ignore_errors=True)

        if uow is None:
            with DatabaseUnitOfWork(
                self.database_locator, base_dir=self.workspace_dir
            ) as managed_uow:
                self._persist_with_uow(
                    context=context,
                    rendered_media=rendered_media,
                    revision_id=revision_id,
                    final_media_path=final_media_path,
                    final_metadata_path=final_metadata_path,
                    uow=managed_uow,
                )
        else:
            self._persist_with_uow(
                context=context,
                rendered_media=rendered_media,
                revision_id=revision_id,
                final_media_path=final_media_path,
                final_metadata_path=final_metadata_path,
                uow=uow,
            )

        logger.info(
            format_console_block(
                "Local Media Publish Completed",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line("Artifact kind", rendered_media.artifact_kind),
                format_detail_line("Revision ID", revision_id),
                format_detail_line(
                    "Delete temporary files",
                    "yes" if self.cleanup_temporary_files else "no",
                ),
                format_detail_line("Media path", final_media_path),
                format_detail_line("Metadata path", final_metadata_path or "<none>"),
                format_detail_line("Poster path", final_poster_path or "<none>"),
            )
        )
        return PublishedMediaArtifact(
            artifact_kind=rendered_media.artifact_kind,
            media_path=final_media_path,
            metadata_path=final_metadata_path,
            mime_type=rendered_media.mime_type,
            revision_id=revision_id,
        )

    def execute_existing(
        self,
        context: PropertyContext,
        *,
        uow: DatabaseUnitOfWork | None = None,
    ) -> PublishedMediaArtifact:
        """Publish-only retry path: validates an existing artifact is present.

        Mirrors the legacy `FileSystemMediaPublisher.publish_existing_media`
        contract (no DB writes here; the workflow transition belongs to step
        4, the composite publisher). The `uow` argument is accepted for
        signature symmetry with `execute(...)` but is unused.
        """

        del uow  # symmetry with execute(); no DB side-effects on this branch.
        if context.existing_published_media is None:
            raise ValidationError(
                "An existing published media artifact is required for publish-only retries.",
                code="EXISTING_MEDIA_REQUIRED",
                context=build_log_context(
                    site_id=context.site_id,
                    property_id=context.property.id,
                    requires_render=context.requires_render,
                ),
                hint=(
                    "Re-render the media or restore the published artifact files "
                    "before retrying a publish-only workflow."
                ),
            )
        return context.existing_published_media

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_output_dir(context: PropertyContext, artifact_kind: str) -> Path:
        if artifact_kind == "poster_image":
            return context.storage_paths.generated_posters_root
        return context.storage_paths.generated_reels_root

    @classmethod
    def _publish_related_poster(
        cls,
        context: PropertyContext,
        rendered_media: RenderedMediaArtifact,
    ) -> Path | None:
        poster_source_path = (
            rendered_media.staging_dir / f"{context.property.slug}-poster.jpg"
        )
        if not poster_source_path.exists() or poster_source_path.stat().st_size == 0:
            if rendered_media.artifact_kind == "reel_video":
                raise ValidationError(
                    "A reel render must include a non-empty poster artifact.",
                    code="POSTER_REQUIRED",
                    context=build_log_context(
                        site_id=context.site_id,
                        property_id=context.property.id,
                        artifact_kind=rendered_media.artifact_kind,
                        poster_source_path=str(poster_source_path),
                    ),
                    hint=(
                        "Verify poster rendering completed successfully before "
                        "the local publish step and keep the staging poster "
                        "alongside the reel output."
                    ),
                )
            return None
        poster_output_dir = cls._resolve_output_dir(context, "poster_image")
        poster_output_dir.mkdir(parents=True, exist_ok=True)
        final_poster_path = poster_output_dir / poster_source_path.name
        cls._replace_atomically(poster_source_path, final_poster_path)
        return final_poster_path

    @staticmethod
    def _replace_atomically(source_path: Path, destination_path: Path) -> None:
        temporary_path = destination_path.with_suffix(f"{destination_path.suffix}.tmp")
        shutil.copy2(source_path, temporary_path)
        os.replace(temporary_path, destination_path)

    @staticmethod
    def _persist_with_uow(
        *,
        context: PropertyContext,
        rendered_media: RenderedMediaArtifact,
        revision_id: str,
        final_media_path: Path,
        final_metadata_path: Path | None,
        uow: DatabaseUnitOfWork,
    ) -> None:
        if uow.reels is None or uow.delivery is None:
            raise RuntimeError("The unit of work is not active.")
        normalized_external_source_id = str(context.site_id or "").strip().lower()
        media_path_text = _relative_path_text(context.workspace_dir, final_media_path)
        metadata_path_text = _relative_path_text(context.workspace_dir, final_metadata_path)
        uow.reels.states.save_local_artifacts(
            agency_id=context.tenant.agency_id,
            ingestion_source_id=context.tenant.wordpress_source_id,
            external_source_id=normalized_external_source_id,
            source_property_id=context.property.id,
            artifact_kind=rendered_media.artifact_kind,
            artifact_path=final_media_path,
            metadata_path=final_metadata_path,
            render_profile=context.delivery_plan.render_profile,
            current_revision_id=revision_id,
        )
        uow.reels.revisions.save_revision(
            MediaRevision(
                revision_id=revision_id,
                agency_id=context.tenant.agency_id,
                ingestion_source_id=context.tenant.wordpress_source_id,
                external_source_id=normalized_external_source_id,
                source_property_id=context.property.id,
                artifact_kind=rendered_media.artifact_kind,
                render_profile=context.delivery_plan.render_profile,
                media_path=media_path_text,
                metadata_path=metadata_path_text,
                mime_type=rendered_media.mime_type,
                content_fingerprint=context.content_fingerprint,
                publish_target_fingerprint=context.publish_target_fingerprint,
                workflow_state="rendered",
                created_at=_now_iso(),
                render_template_id=context.render_template_id,
            )
        )
        uow.delivery.outbox.add_event(
            event_id=uuid4().hex,
            aggregate_type="property_media",
            aggregate_id=f"{context.site_id}:{context.property.id}",
            event_type="media_rendered",
            payload=_build_workflow_payload(
                context,
                workflow_state="rendered",
                revision_id=revision_id,
                extra={
                    "media_path": media_path_text,
                    "metadata_path": metadata_path_text,
                    "mime_type": rendered_media.mime_type,
                },
            ),
            agency_id=context.tenant.agency_id,
            ingestion_source_id=context.tenant.wordpress_source_id,
            external_source_id=normalized_external_source_id,
            source_property_id=context.property.id,
            created_at=_now_iso(),
        )


__all__ = [
    "PersistLocalArtifactsUseCase",
]
