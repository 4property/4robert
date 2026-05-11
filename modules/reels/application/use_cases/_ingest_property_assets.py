"""Asset / state helpers for :class:`IngestPropertyIntoReelUseCase`.

This module hosts the helpers that decide what local artefacts already
exist on disk, whether asset preparation is needed, and how the next
``ReelState`` row should look once the orchestrator has gathered all
inputs. Splitting them out keeps the orchestrator file under the LoC
budget without changing semantics.

Previous-state diff helpers (snapshot coercion, pending-platform diff,
publish-history reset) live in :mod:`_ingest_property_diffs`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from modules.catalog.domain.wordpress_property import Property
from modules.reels.domain import ReelState
from modules.reels.domain.types import (
    PropertyMediaJob,
    SocialPublishContext,
)


def _resolve_absolute_path(base_dir: Path, relative_path: str) -> Path | None:
    if not relative_path:
        return None
    return (base_dir / relative_path).resolve()


def _build_property_record(
    property_item: Property,
    *,
    agency_id: str,
    ingestion_source_id: str,
    external_source_id: str,
    fetched_at: str,
) -> dict[str, Any]:
    """Mirror of legacy `PropertyStore._save_property_record` column mapping.

    Translates the legacy column names (`site_id`, `wordpress_source_id`)
    onto the modern ones (`external_source_id`, `ingestion_source_id`) and
    drops legacy-only columns the modern schema does not expose.
    """

    record = property_item.to_db_record(image_folder="", fetched_at=fetched_at)
    record["agency_id"] = agency_id
    record["ingestion_source_id"] = ingestion_source_id
    record["external_source_id"] = external_source_id
    for legacy_column in ("image_folder", "social_publish_status", "social_publish_details_json"):
        record.pop(legacy_column, None)
    return record


def _should_prepare_assets(
    *,
    state: ReelState,
    property_item: Property,
    storage_paths,
    delivery_plan,
    requires_render: bool,
) -> bool:
    if not requires_render:
        return False
    if not delivery_plan.uses_primary_image_only:
        return True
    from modules.reels.application.use_cases.prepare_reel_assets import (
        PrepareReelAssetsUseCase,
    )

    selected_dir = PrepareReelAssetsUseCase.resolve_selected_dir(
        storage_paths=storage_paths,
        property_item=property_item,
        state=state,
    )
    return PrepareReelAssetsUseCase.resolve_primary_image_from_dir(selected_dir) is None


def _has_local_artifacts(
    *,
    state: ReelState,
    storage_root: Path,
    artifact_kind: str,
    site_id: str,
    property_slug: str,
) -> bool:
    from modules.rendering.infrastructure.poster import (
        resolve_property_poster_output_path,
    )

    artifact_path = _resolve_absolute_path(
        storage_root,
        state.local_artifact_path or state.local_video_path,
    )
    metadata_path = _resolve_absolute_path(
        storage_root,
        state.local_metadata_path or state.local_manifest_path,
    )
    if artifact_kind == "reel_video":
        poster_path = resolve_property_poster_output_path(
            storage_root,
            site_id=site_id,
            slug=property_slug,
        )
        return bool(
            artifact_path
            and metadata_path
            and artifact_path.exists()
            and artifact_path.stat().st_size > 0
            and metadata_path.exists()
            and metadata_path.stat().st_size > 0
            and poster_path.exists()
            and poster_path.stat().st_size > 0
            and state.render_status == "completed"
        )
    return bool(
        artifact_path
        and artifact_path.exists()
        and artifact_path.stat().st_size > 0
        and state.render_status == "completed"
    )


def _build_existing_published_media(
    *,
    state: ReelState,
    storage_root: Path,
):
    from modules.reels.domain.types import PublishedMediaArtifact

    artifact_kind = state.artifact_kind or ("reel_video" if state.local_video_path else "")
    artifact_path = _resolve_absolute_path(
        storage_root,
        state.local_artifact_path or state.local_video_path,
    )
    metadata_path = _resolve_absolute_path(
        storage_root,
        state.local_metadata_path or state.local_manifest_path,
    )
    if artifact_kind and artifact_path is not None and artifact_path.exists():
        return PublishedMediaArtifact(
            artifact_kind=artifact_kind,
            media_path=artifact_path,
            metadata_path=metadata_path,
            revision_id=state.current_revision_id,
        )
    return None


def _build_ingested_reel_state(
    *,
    job: PropertyMediaJob,
    property_item: Property,
    state: ReelState,
    delivery_plan,
    content_fingerprint: str,
    content_snapshot: dict[str, object],
    publish_target_fingerprint: str,
    publish_target_snapshot: dict[str, object],
    requires_asset_preparation: bool,
    requires_render: bool,
    publish_context: SocialPublishContext | None,
    pending_publish_platforms: tuple[str, ...],
    reset_publish_history: bool,
    normalized_external_source_id: str,
) -> ReelState:
    selected_image_folder = state.selected_image_folder
    if requires_asset_preparation:
        selected_image_folder = ""

    local_artifact_path = state.local_artifact_path
    local_metadata_path = state.local_metadata_path
    local_manifest_path = state.local_manifest_path
    local_video_path = state.local_video_path
    current_revision_id = state.current_revision_id
    render_status = "completed"

    if requires_render:
        local_artifact_path = ""
        local_metadata_path = ""
        local_manifest_path = ""
        local_video_path = ""
        current_revision_id = ""
        render_status = "pending"

    publish_status = state.publish_status
    if publish_context is None:
        publish_status = "skipped"
    elif pending_publish_platforms:
        publish_status = "pending"

    publish_details: dict[str, Any] = dict(state.publish_details or {})
    last_published_provider_external_id = state.last_published_provider_external_id
    if publish_context is not None and reset_publish_history:
        publish_details = {}
        last_published_provider_external_id = ""

    return ReelState(
        agency_id=job.tenant.agency_id or state.agency_id,
        ingestion_source_id=job.tenant.wordpress_source_id or state.ingestion_source_id,
        external_source_id=normalized_external_source_id,
        source_property_id=property_item.id,
        content_fingerprint=content_fingerprint,
        content_snapshot=content_snapshot,
        publish_target_fingerprint=publish_target_fingerprint,
        publish_target_snapshot=publish_target_snapshot,
        selected_image_folder=selected_image_folder,
        artifact_kind=delivery_plan.artifact_kind,
        local_artifact_path=local_artifact_path,
        local_metadata_path=local_metadata_path,
        render_profile=delivery_plan.render_profile,
        local_manifest_path=local_manifest_path,
        local_video_path=local_video_path,
        render_status=render_status,
        publish_status=publish_status,
        workflow_state="ingested",
        publish_details=publish_details,
        current_revision_id=current_revision_id,
        last_published_provider_external_id=last_published_provider_external_id,
        created_at=state.created_at,
        updated_at=state.updated_at,
    )


__all__ = [
    "_build_existing_published_media",
    "_build_ingested_reel_state",
    "_build_property_record",
    "_has_local_artifacts",
    "_resolve_absolute_path",
    "_should_prepare_assets",
]
