from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from application.content_generation import ContentGenerator, DeterministicPropertyContentGenerator
from application.media_planning import build_media_delivery_plan
from application.persistence import UnitOfWork
from application.types import (
    PlatformPublishTargetPlan,
    PreparedMediaAssets,
    PropertyContext,
    PropertyVideoJob,
    PublishedMediaArtifact,
    RenderedMediaArtifact,
    SocialPublishContext,
)
from config import DEFAULT_PHOTOS_TO_SELECT, REVIEW_WORKFLOW_ENABLED, SELECTED_PHOTOS_DIRNAME
from core.media_cleanup import (
    DEFAULT_DELETE_SELECTED_PHOTOS,
    DEFAULT_DELETE_TEMPORARY_FILES,
    should_cleanup_raw_property_dir,
    should_cleanup_render_staging_dir,
    should_cleanup_selected_assets,
)
from core.errors import (
    PhotoFilteringError,
    SocialPublishingResultError,
    TransientSocialPublishingResultError,
    ValidationError,
    extract_error_details,
)
from core.logging import build_log_context, format_console_block, format_context_line, format_detail_line
from models.property import Property
from repositories.media_revision_repository import MediaRevisionRecord
from repositories.property_pipeline_repository import PropertyPipelineState
from services.property_media import download_and_filter_property_images
from services.property_media.downloads import download_image, download_images_to_directory
from services.property_media.filesystem import list_image_files, prepare_property_directories
from services.property_media.naming import PRIMARY_IMAGE_STEM, build_primary_image_filename
from services.reel_rendering import (
    PropertyRenderData,
    build_reel_template_for_render_profile,
    generate_property_reel_from_data,
    write_property_reel_manifest_from_data,
)
from services.reel_rendering.poster import (
    generate_property_poster_from_data,
    resolve_property_poster_output_path,
)
from services.reel_rendering.preparation import prepare_reel_render_assets
from services.reel_rendering.runtime import build_local_selected_slides
from services.social_delivery import (
    GoHighLevelPropertyPublisher,
    MultiPlatformPublishResult,
    build_property_public_url,
)
from services.social_delivery.platforms import get_platform_config
from services.social_delivery.platform_policy import (
    normalize_platform_name,
)
from services.webhook_transport.site_storage import resolve_site_storage_layout

logger = logging.getLogger(__name__)
_SUCCESSFUL_SOCIAL_STATUSES = {"published", "scheduled", "queued", "processing", "created", "accepted"}


def _default_pipeline_state(site_id: str, source_property_id: int) -> PropertyPipelineState:
    return PropertyPipelineState(
        site_id=site_id,
        source_property_id=source_property_id,
        content_fingerprint="",
        content_snapshot_json="",
        publish_target_fingerprint="",
        publish_target_snapshot_json="",
        selected_image_folder="",
        artifact_kind="",
        local_artifact_path="",
        local_metadata_path="",
        render_profile="",
        local_manifest_path="",
        local_video_path="",
        render_status="",
        publish_status="",
        workflow_state="",
        publish_details_json="",
        current_revision_id="",
        last_published_location_id="",
        created_at="",
        updated_at="",
    )


def _json_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _json_text(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _parse_json_object(value: str) -> dict[str, object]:
    if not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _resolve_absolute_path(base_dir: Path, relative_path: str) -> Path | None:
    if not relative_path:
        return None
    return (base_dir / relative_path).resolve()


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
        payload["platforms"] = list(context.pending_publish_platforms or context.publish_context.platforms)
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


def _normalise_platforms(value: object) -> tuple[str, ...]:
    raw_values: tuple[object, ...]
    if isinstance(value, (list, tuple)):
        raw_values = tuple(value)
    elif value is None:
        raw_values = ()
    else:
        raw_values = (value,)

    normalized_values: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        normalized_value = normalize_platform_name(str(raw_value or "").strip().lower())
        if not normalized_value or normalized_value in seen:
            continue
        seen.add(normalized_value)
        normalized_values.append(normalized_value)
    return tuple(normalized_values)


def _parse_publish_target_snapshot(value: str) -> dict[str, object]:
    raw_snapshot = _parse_json_object(value)
    if not raw_snapshot:
        return {
            "provider": "",
            "location_id": "",
            "platforms": (),
            "descriptions_by_platform": {},
            "titles_by_platform": {},
            "targets_by_platform": {},
            "target_url": "",
            "artifact_kind": "",
            "render_profile": "",
            "listing_lifecycle": "",
            "social_post_type": "",
        }

    raw_descriptions = raw_snapshot.get("descriptions_by_platform")
    descriptions_by_platform: dict[str, str] = {}
    if isinstance(raw_descriptions, dict):
        for raw_platform, raw_description in raw_descriptions.items():
            platform = normalize_platform_name(str(raw_platform or "").strip().lower())
            if not platform:
                continue
            descriptions_by_platform[platform] = str(raw_description or "")

    raw_titles = raw_snapshot.get("titles_by_platform")
    titles_by_platform: dict[str, str] = {}
    if isinstance(raw_titles, dict):
        for raw_platform, raw_title in raw_titles.items():
            platform = normalize_platform_name(str(raw_platform or "").strip().lower())
            title = str(raw_title or "").strip()
            if not platform or not title:
                continue
            titles_by_platform[platform] = title

    raw_targets = raw_snapshot.get("targets_by_platform")
    targets_by_platform: dict[str, dict[str, str]] = {}
    if isinstance(raw_targets, dict):
        for raw_platform, raw_target in raw_targets.items():
            if not isinstance(raw_target, dict):
                continue
            platform = normalize_platform_name(str(raw_platform or "").strip().lower())
            if not platform:
                continue
            targets_by_platform[platform] = {
                "artifact_kind": str(raw_target.get("artifact_kind") or "").strip(),
                "social_post_type": str(raw_target.get("social_post_type") or "").strip(),
                "description": str(raw_target.get("description") or ""),
                "title": str(raw_target.get("title") or "").strip(),
                "target_url": str(raw_target.get("target_url") or "").strip(),
            }

    platforms = _normalise_platforms(raw_snapshot.get("platforms"))

    return {
        "provider": str(raw_snapshot.get("provider") or "").strip().lower(),
        "location_id": str(raw_snapshot.get("location_id") or "").strip(),
        "platforms": platforms,
        "descriptions_by_platform": descriptions_by_platform,
        "titles_by_platform": titles_by_platform,
        "targets_by_platform": targets_by_platform,
        "target_url": str(raw_snapshot.get("target_url") or "").strip(),
        "artifact_kind": str(raw_snapshot.get("artifact_kind") or "").strip(),
        "render_profile": str(raw_snapshot.get("render_profile") or "").strip(),
        "listing_lifecycle": str(raw_snapshot.get("listing_lifecycle") or "").strip(),
        "social_post_type": str(raw_snapshot.get("social_post_type") or "").strip(),
    }


def _extract_platform_results(details: dict[str, object]) -> dict[str, dict[str, object]]:
    raw_results = details.get("platform_results")
    platform_results: dict[str, dict[str, object]] = {}
    if isinstance(raw_results, dict):
        for raw_platform, raw_result in raw_results.items():
            if not isinstance(raw_result, dict):
                continue
            platform = str(raw_result.get("platform") or raw_platform or "").strip().lower()
            if not platform:
                continue
            platform_results[platform] = dict(raw_result)
        if platform_results:
            return platform_results

    return platform_results


def _is_successful_platform_result(result: dict[str, object]) -> bool:
    outcome = str(result.get("outcome") or "").strip().lower()
    post_id = str(result.get("post_id") or "").strip()
    post_status = str(result.get("post_status") or "").strip().lower()
    if post_id:
        return True
    return outcome in _SUCCESSFUL_SOCIAL_STATUSES or post_status in _SUCCESSFUL_SOCIAL_STATUSES


def _extract_successful_platforms(
    details_json: str,
    *,
    fallback_platforms: tuple[str, ...] = (),
) -> tuple[str, ...]:
    details = _parse_json_object(details_json)
    successful_platforms: list[str] = []
    platform_results = _extract_platform_results(details)
    for platform, result in platform_results.items():
        if _is_successful_platform_result(result):
            successful_platforms.append(platform)
    if successful_platforms:
        return tuple(successful_platforms)
    if fallback_platforms and _is_successful_platform_result(details):
        return tuple(
            platform
            for platform in fallback_platforms
            if platform.strip()
        )
    return tuple(successful_platforms)


class LocalPhotoSelectionEngine:
    def __init__(
        self,
        *,
        photos_to_select: int = DEFAULT_PHOTOS_TO_SELECT,
        cleanup_temporary_files: bool = DEFAULT_DELETE_TEMPORARY_FILES,
    ) -> None:
        self.photos_to_select = photos_to_select
        self.cleanup_temporary_files = bool(cleanup_temporary_files)

    def select_photos(
        self,
        *,
        property_item: Property,
        raw_images_root: Path,
        filtered_images_root: Path,
    ) -> tuple[Path, list[tuple[int, str, Path | None]]]:
        return download_and_filter_property_images(
            property_item,
            raw_images_root,
            filtered_images_root,
            photos_to_select=self.photos_to_select,
            cleanup_temporary_files=self.cleanup_temporary_files,
        )


class DefaultPropertyInfoService:
    def __init__(
        self,
        workspace_dir: str | Path,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        property_url_template: str,
        property_url_tracking_params: dict[str, str] | None,
        social_publishing_enabled: bool,
        content_generator: ContentGenerator | None = None,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.unit_of_work_factory = unit_of_work_factory
        self.property_url_template = property_url_template
        self.property_url_tracking_params = dict(property_url_tracking_params or {})
        self.social_publishing_enabled = social_publishing_enabled
        self.content_generator = content_generator or DeterministicPropertyContentGenerator()

    def ingest_property(self, job: PropertyVideoJob) -> PropertyContext:
        storage_paths = resolve_site_storage_layout(self.workspace_dir, job.site_id)
        property_item = Property.from_api_payload(job.payload)
        delivery_plan = build_media_delivery_plan(property_item)

        (
            publish_context,
            desired_platforms,
            publish_target_url,
            publish_descriptions_by_platform,
            publish_titles_by_platform,
            publish_targets,
        ) = self._resolve_publish_inputs(
            job=job,
            property_item=property_item,
            delivery_plan=delivery_plan,
        )
        content_snapshot = self._build_content_snapshot(
            property_item=property_item,
            delivery_plan=delivery_plan,
        )
        content_snapshot_json = _json_text(content_snapshot)
        content_fingerprint = _json_hash(content_snapshot)
        publish_target_snapshot = self._build_publish_target_snapshot(
            publish_context=publish_context,
            descriptions_by_platform=publish_descriptions_by_platform,
            titles_by_platform=publish_titles_by_platform,
            publish_targets=publish_targets,
            target_url=publish_target_url,
            delivery_plan=delivery_plan,
        )
        publish_target_snapshot_json = _json_text(publish_target_snapshot)
        publish_target_fingerprint = _json_hash(publish_target_snapshot)

        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.property_repository.save_property_data(
                property_item,
                site_id=job.site_id,
            )
            existing_state = unit_of_work.pipeline_state_repository.get_property_pipeline_state(
                site_id=job.site_id,
                source_property_id=property_item.id,
            )
            state = existing_state
            if state is None:
                state = _default_pipeline_state(job.site_id, property_item.id)
            previous_target_snapshot = _parse_publish_target_snapshot(state.publish_target_snapshot_json)

            has_local_artifacts = self._has_local_artifacts(
                state=state,
                storage_root=self.workspace_dir,
                artifact_kind=delivery_plan.artifact_kind,
                site_id=job.site_id,
                property_slug=property_item.slug,
            )
            content_changed = (
                state.content_snapshot_json != content_snapshot_json
                or state.content_fingerprint != content_fingerprint
            )
            requires_render = content_changed or not has_local_artifacts
            requires_asset_preparation = self._should_prepare_assets(
                state=state,
                property_item=property_item,
                storage_paths=storage_paths,
                delivery_plan=delivery_plan,
                requires_render=requires_render,
            )
            pending_publish_platforms = self._determine_pending_publish_platforms(
                state=state,
                publish_context=publish_context,
                desired_platforms=desired_platforms,
                publish_descriptions_by_platform=publish_descriptions_by_platform,
                publish_titles_by_platform=publish_titles_by_platform,
                publish_targets=publish_targets,
                publish_target_url=publish_target_url,
                delivery_plan=delivery_plan,
                requires_render=requires_render,
            )
            requires_external_publish = bool(pending_publish_platforms)
            is_noop = not requires_render and not requires_external_publish and has_local_artifacts
            existing_published_media = self._build_existing_published_media(
                state=state,
                storage_root=self.workspace_dir,
            )

            if not is_noop:
                reset_publish_history = self._should_reset_publish_history(
                    previous_target_snapshot=previous_target_snapshot,
                    publish_context=publish_context,
                    requires_render=requires_render,
                )
                next_state = self._build_ingested_pipeline_state(
                    job=job,
                    property_item=property_item,
                    state=state,
                    delivery_plan=delivery_plan,
                    content_fingerprint=content_fingerprint,
                    content_snapshot_json=content_snapshot_json,
                    publish_target_fingerprint=publish_target_fingerprint,
                    publish_target_snapshot_json=publish_target_snapshot_json,
                    requires_asset_preparation=requires_asset_preparation,
                    requires_render=requires_render,
                    publish_context=publish_context,
                    pending_publish_platforms=pending_publish_platforms,
                    reset_publish_history=reset_publish_history,
                )
                unit_of_work.pipeline_state_repository.save_property_pipeline_state(next_state)

        logger.info(
            format_console_block(
                "Property Ingest Decision",
                format_detail_line("Site ID", job.site_id),
                format_detail_line("Property ID", property_item.id),
                format_detail_line("Content changed", "yes" if content_changed else "no"),
                format_detail_line("Has local artifacts", "yes" if has_local_artifacts else "no"),
                format_detail_line(
                    "Requires asset preparation",
                    "yes" if requires_asset_preparation else "no",
                ),
                format_detail_line("Requires render", "yes" if requires_render else "no"),
                format_detail_line(
                    "Pending publish platforms",
                    ", ".join(pending_publish_platforms) or "<none>",
                ),
                format_detail_line(
                    "Publish targets",
                    ", ".join(
                        f"{target.platform}:{target.artifact_kind}"
                        for target in publish_targets
                    ) or "<none>",
                ),
                format_detail_line("Noop", "yes" if is_noop else "no"),
            )
        )

        return PropertyContext(
            workspace_dir=self.workspace_dir,
            storage_paths=storage_paths,
            site_id=job.site_id,
            property=property_item,
            delivery_plan=delivery_plan,
            publish_context=publish_context,
            publish_descriptions_by_platform=publish_descriptions_by_platform,
            publish_titles_by_platform=publish_titles_by_platform,
            publish_targets=publish_targets,
            publish_target_url=publish_target_url,
            content_fingerprint=content_fingerprint,
            content_snapshot_json=content_snapshot_json,
            publish_target_fingerprint=publish_target_fingerprint,
            publish_target_snapshot_json=publish_target_snapshot_json,
            pending_publish_platforms=pending_publish_platforms,
            requires_asset_preparation=requires_asset_preparation,
            requires_render=requires_render,
            requires_external_publish=requires_external_publish,
            existing_published_media=existing_published_media,
            is_noop=is_noop,
        )

    def _resolve_publish_inputs(
        self,
        *,
        job: PropertyVideoJob,
        property_item: Property,
        delivery_plan,
    ) -> tuple[
        SocialPublishContext | None,
        tuple[str, ...],
        str | None,
        dict[str, str],
        dict[str, str],
        tuple[PlatformPublishTargetPlan, ...],
    ]:
        publish_context: SocialPublishContext | None = None
        desired_platforms: tuple[str, ...] = ()
        publish_target_url: str | None = None
        publish_descriptions_by_platform: dict[str, str] = {}
        publish_titles_by_platform: dict[str, str] = {}
        publish_targets: tuple[PlatformPublishTargetPlan, ...] = ()

        if self.social_publishing_enabled:
            publish_context = job.publish_context

        if publish_context is not None:
            desired_platforms = publish_context.platforms
            publish_target_url = build_property_public_url(
                site_id=job.site_id,
                slug=property_item.slug,
                property_link=property_item.link,
                property_url_template=self.property_url_template,
                tracking_query_params=self.property_url_tracking_params,
            )

        if publish_context is not None and publish_target_url is not None:
            logger.info(
                format_console_block(
                    "Property Content Generation Started",
                    format_detail_line("Site ID", job.site_id),
                    format_detail_line("Property ID", property_item.id),
                    format_detail_line("Platforms", ", ".join(desired_platforms)),
                    format_detail_line("Target URL", publish_target_url),
                )
            )
            generated_content = self.content_generator.generate_property_content(
                property_item=property_item,
                property_url=publish_target_url,
                platforms=desired_platforms,
            )
            publish_descriptions_by_platform = dict(generated_content.captions_by_platform)
            publish_titles_by_platform = dict(generated_content.titles_by_platform)
            publish_targets = self._build_publish_targets(
                property_item=property_item,
                desired_platforms=desired_platforms,
                publish_descriptions_by_platform=publish_descriptions_by_platform,
                publish_titles_by_platform=publish_titles_by_platform,
                publish_target_url=publish_target_url,
                delivery_plan=delivery_plan,
            )
            logger.info(
                format_console_block(
                    "Property Content Generation Completed",
                    format_detail_line("Site ID", job.site_id),
                    format_detail_line("Property ID", property_item.id),
                    format_detail_line("Generated captions", len(publish_descriptions_by_platform)),
                    format_detail_line("Generated titles", len(publish_titles_by_platform)),
                    format_detail_line("Publish targets", len(publish_targets)),
                )
            )

        return (
            publish_context,
            desired_platforms,
            publish_target_url,
            publish_descriptions_by_platform,
            publish_titles_by_platform,
            publish_targets,
        )

    @staticmethod
    def _build_ingested_pipeline_state(
        *,
        job: PropertyVideoJob,
        property_item: Property,
        state: PropertyPipelineState,
        delivery_plan,
        content_fingerprint: str,
        content_snapshot_json: str,
        publish_target_fingerprint: str,
        publish_target_snapshot_json: str,
        requires_asset_preparation: bool,
        requires_render: bool,
        publish_context: SocialPublishContext | None,
        pending_publish_platforms: tuple[str, ...],
        reset_publish_history: bool,
    ) -> PropertyPipelineState:
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

        publish_details_json = state.publish_details_json
        last_published_location_id = state.last_published_location_id
        if publish_context is not None and reset_publish_history:
            publish_details_json = ""
            last_published_location_id = ""

        return PropertyPipelineState(
            site_id=job.site_id,
            source_property_id=property_item.id,
            content_fingerprint=content_fingerprint,
            content_snapshot_json=content_snapshot_json,
            publish_target_fingerprint=publish_target_fingerprint,
            publish_target_snapshot_json=publish_target_snapshot_json,
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
            publish_details_json=publish_details_json,
            current_revision_id=current_revision_id,
            last_published_location_id=last_published_location_id,
            created_at=state.created_at,
            updated_at=state.updated_at,
        )

    @staticmethod
    def _build_content_snapshot(*, property_item: Property, delivery_plan) -> dict[str, object]:
        snapshot = property_item.to_dict()
        snapshot.pop("raw_data", None)
        snapshot["delivery_plan"] = {
            "listing_lifecycle": delivery_plan.listing_lifecycle,
            "artifact_kind": delivery_plan.artifact_kind,
            "render_profile": delivery_plan.render_profile,
            "social_post_type": delivery_plan.social_post_type,
            "asset_strategy": delivery_plan.asset_strategy,
            "banner_text": delivery_plan.banner_text,
            "price_display_text": delivery_plan.price_display_text,
        }
        return snapshot

    @staticmethod
    def _build_publish_target_snapshot(
        *,
        publish_context,
        descriptions_by_platform: dict[str, str],
        titles_by_platform: dict[str, str],
        publish_targets: tuple[PlatformPublishTargetPlan, ...],
        target_url: str | None,
        delivery_plan,
    ) -> dict[str, object]:
        if publish_context is None:
            return {}
        return {
            "provider": publish_context.provider,
            "location_id": publish_context.location_id,
            "platforms": list(publish_context.platforms),
            "descriptions_by_platform": dict(descriptions_by_platform),
            "titles_by_platform": dict(titles_by_platform),
            "targets_by_platform": {
                target.platform: {
                    "artifact_kind": target.artifact_kind,
                    "social_post_type": target.social_post_type,
                    "description": target.description,
                    "title": target.title or "",
                    "target_url": target.target_url or "",
                }
                for target in publish_targets
            },
            "target_url": target_url or "",
            "artifact_kind": delivery_plan.artifact_kind,
            "render_profile": delivery_plan.render_profile,
            "listing_lifecycle": delivery_plan.listing_lifecycle,
            "social_post_type": delivery_plan.social_post_type,
        }

    @staticmethod
    def _build_publish_targets(
        *,
        property_item: Property,
        desired_platforms: tuple[str, ...],
        publish_descriptions_by_platform: dict[str, str],
        publish_titles_by_platform: dict[str, str],
        publish_target_url: str | None,
        delivery_plan,
    ) -> tuple[PlatformPublishTargetPlan, ...]:
        publish_targets: list[PlatformPublishTargetPlan] = []
        for platform in desired_platforms:
            normalized_platform = normalize_platform_name(platform)
            if not normalized_platform:
                continue
            platform_config = get_platform_config(normalized_platform)
            if platform_config is None:
                continue
            publish_targets.append(
                PlatformPublishTargetPlan(
                    platform=normalized_platform,
                    artifact_kind=platform_config.resolve_artifact_kind(
                        delivery_plan.artifact_kind,
                    ),
                    social_post_type=platform_config.resolve_social_post_type(
                        delivery_plan.social_post_type,
                    ),
                    description=str(
                        publish_descriptions_by_platform.get(normalized_platform)
                        or platform_config.build_description(
                            property_item,
                            str(publish_target_url or property_item.link or ""),
                        )
                    ),
                    title=(
                        str(publish_titles_by_platform.get(normalized_platform) or "").strip() or None
                    )
                    or platform_config.build_title(property_item),
                    target_url=publish_target_url or None,
                )
            )
        return tuple(publish_targets)

    @staticmethod
    def _determine_pending_publish_platforms(
        *,
        state: PropertyPipelineState,
        publish_context,
        desired_platforms: tuple[str, ...],
        publish_descriptions_by_platform: dict[str, str],
        publish_titles_by_platform: dict[str, str],
        publish_targets: tuple[PlatformPublishTargetPlan, ...],
        publish_target_url: str | None,
        delivery_plan,
        requires_render: bool,
    ) -> tuple[str, ...]:
        if publish_context is None:
            return ()
        if requires_render:
            return desired_platforms

        previous_target_snapshot = _parse_publish_target_snapshot(state.publish_target_snapshot_json)
        successful_platforms = set(
            _extract_successful_platforms(
                state.publish_details_json,
                fallback_platforms=desired_platforms,
            )
        )
        previous_descriptions = previous_target_snapshot["descriptions_by_platform"]
        if not isinstance(previous_descriptions, dict):
            previous_descriptions = {}
        previous_titles = previous_target_snapshot["titles_by_platform"]
        if not isinstance(previous_titles, dict):
            previous_titles = {}
        previous_targets = previous_target_snapshot["targets_by_platform"]
        if not isinstance(previous_targets, dict):
            previous_targets = {}
        current_targets = {
            target.platform: target
            for target in publish_targets
        }

        pending_publish_platforms: list[str] = []
        for platform in desired_platforms:
            current_target = current_targets.get(platform)
            if current_target is None:
                pending_publish_platforms.append(platform)
                continue
            if platform not in successful_platforms:
                pending_publish_platforms.append(platform)
                continue
            if str(previous_target_snapshot.get("provider") or "") != publish_context.provider:
                pending_publish_platforms.append(platform)
                continue
            if str(previous_target_snapshot.get("location_id") or "") != publish_context.location_id:
                pending_publish_platforms.append(platform)
                continue
            previous_target_entry = previous_targets.get(platform)
            previous_target_url = str(
                (previous_target_entry or {}).get("target_url")
                or previous_target_snapshot.get("target_url")
                or ""
            )
            if previous_target_url != (current_target.target_url or publish_target_url or ""):
                pending_publish_platforms.append(platform)
                continue
            previous_artifact_kind = str(
                (previous_target_entry or {}).get("artifact_kind")
                or previous_target_snapshot.get("artifact_kind")
                or ""
            )
            if previous_artifact_kind != current_target.artifact_kind:
                pending_publish_platforms.append(platform)
                continue
            if str(previous_target_snapshot.get("render_profile") or "") != delivery_plan.render_profile:
                pending_publish_platforms.append(platform)
                continue
            previous_social_post_type = str(
                (previous_target_entry or {}).get("social_post_type")
                or previous_target_snapshot.get("social_post_type")
                or ""
            )
            if previous_social_post_type != current_target.social_post_type:
                pending_publish_platforms.append(platform)
                continue
            if str(previous_target_snapshot.get("listing_lifecycle") or "") != delivery_plan.listing_lifecycle:
                pending_publish_platforms.append(platform)
                continue
            previous_description = str(
                (previous_target_entry or {}).get("description")
                or previous_descriptions.get(platform)
                or ""
            )
            current_description = current_target.description or str(
                publish_descriptions_by_platform.get(platform) or ""
            )
            if previous_description != current_description:
                pending_publish_platforms.append(platform)
                continue
            previous_title = str(
                (previous_target_entry or {}).get("title")
                or previous_titles.get(platform)
                or ""
            )
            current_title = str(current_target.title or publish_titles_by_platform.get(platform) or "")
            if previous_title != current_title:
                pending_publish_platforms.append(platform)

        return tuple(pending_publish_platforms)

    @staticmethod
    def _should_prepare_assets(
        *,
        state: PropertyPipelineState,
        property_item: Property,
        storage_paths,
        delivery_plan,
        requires_render: bool,
    ) -> bool:
        if not requires_render:
            return False
        if not delivery_plan.uses_primary_image_only:
            return True
        selected_dir = DefaultMediaPreparationService.resolve_selected_dir(
            storage_paths=storage_paths,
            property_item=property_item,
            state=state,
        )
        return DefaultMediaPreparationService.resolve_primary_image_from_dir(selected_dir) is None

    @staticmethod
    def _has_local_artifacts(
        *,
        state: PropertyPipelineState,
        storage_root: Path,
        artifact_kind: str,
        site_id: str,
        property_slug: str,
    ) -> bool:
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

    @staticmethod
    def _build_existing_published_media(
        *,
        state: PropertyPipelineState,
        storage_root: Path,
    ) -> PublishedMediaArtifact | None:
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

    @staticmethod
    def _should_reset_publish_history(
        *,
        previous_target_snapshot: dict[str, object],
        publish_context,
        requires_render: bool,
    ) -> bool:
        if publish_context is None:
            return False
        if requires_render:
            return True
        previous_provider = str(previous_target_snapshot.get("provider") or "")
        previous_location_id = str(previous_target_snapshot.get("location_id") or "")
        return (
            previous_provider != publish_context.provider
            or previous_location_id != publish_context.location_id
        )


class DefaultMediaPreparationService:
    def __init__(
        self,
        workspace_dir: str | Path,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        engine: LocalPhotoSelectionEngine | None = None,
        cleanup_temporary_files: bool = DEFAULT_DELETE_TEMPORARY_FILES,
        cleanup_selected_photos: bool = DEFAULT_DELETE_SELECTED_PHOTOS,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.unit_of_work_factory = unit_of_work_factory
        self.cleanup_temporary_files = bool(cleanup_temporary_files)
        self.cleanup_selected_photos = bool(cleanup_selected_photos)
        self.engine = engine or LocalPhotoSelectionEngine(
            cleanup_temporary_files=self.cleanup_temporary_files
        )

    def prepare_assets(self, context: PropertyContext) -> PreparedMediaAssets:
        if not context.requires_asset_preparation:
            existing_assets = self._load_existing_assets(context)
            if existing_assets.selected_photo_paths or existing_assets.primary_image_path is not None:
                return existing_assets

        if context.delivery_plan.uses_primary_image_only:
            return self._prepare_primary_only_assets(context)
        return self._prepare_curated_assets(context)

    def select_photos(self, context: PropertyContext) -> PreparedMediaAssets:
        return self.prepare_assets(context)

    def cleanup_prepared_assets(
        self,
        context: PropertyContext,
        prepared_assets: PreparedMediaAssets,
    ) -> None:
        if not should_cleanup_selected_assets(self.cleanup_selected_photos):
            return
        if not prepared_assets.selected_dir.exists():
            return
        shutil.rmtree(prepared_assets.selected_dir, ignore_errors=True)
        logger.info(
            format_console_block(
                "Prepared Media Assets Cleaned",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line(
                    "Delete selected photos",
                    "yes" if self.cleanup_selected_photos else "no",
                ),
                format_detail_line("Selected directory", prepared_assets.selected_dir),
            )
        )

    @staticmethod
    def resolve_selected_dir(*, storage_paths, property_item: Property, state: PropertyPipelineState | None = None) -> Path:
        if state is not None and state.selected_image_folder:
            return (storage_paths.workspace_dir / state.selected_image_folder).resolve()
        return (storage_paths.filtered_images_root / property_item.folder_name / SELECTED_PHOTOS_DIRNAME).resolve()

    @staticmethod
    def resolve_primary_image_from_dir(selected_dir: Path) -> Path | None:
        if not selected_dir.exists():
            return None
        image_paths = tuple(list_image_files(selected_dir))
        for image_path in image_paths:
            if image_path.stem.lower() == PRIMARY_IMAGE_STEM:
                return image_path
        return image_paths[0] if image_paths else None

    def _load_existing_assets(self, context: PropertyContext) -> PreparedMediaAssets:
        selected_dir = self.resolve_selected_dir(
            storage_paths=context.storage_paths,
            property_item=context.property,
        )
        selected_photo_paths = tuple(list_image_files(selected_dir)) if selected_dir.exists() else ()
        return PreparedMediaAssets(
            selected_dir=selected_dir,
            selected_photo_paths=selected_photo_paths,
            downloaded_images=(),
            primary_image_path=self.resolve_primary_image_from_dir(selected_dir),
        )

    def _prepare_curated_assets(self, context: PropertyContext) -> PreparedMediaAssets:
        try:
            selected_dir, downloaded_images = self.engine.select_photos(
                property_item=context.property,
                raw_images_root=context.storage_paths.raw_images_root,
                filtered_images_root=context.storage_paths.filtered_images_root,
            )
        except PhotoFilteringError:
            raise
        except Exception as exc:
            raise PhotoFilteringError(
                f"Failed to prepare curated property images for property {context.property.id}.",
                code="CURATED_ASSET_PREPARATION_FAILED",
                context=build_log_context(
                    site_id=context.site_id,
                    property_id=context.property.id,
                    asset_strategy=context.delivery_plan.asset_strategy,
                ),
                cause=exc,
            ) from exc

        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.property_repository.save_property_images(
                context.property,
                selected_dir,
                downloaded_images,
                site_id=context.site_id,
            )
            unit_of_work.pipeline_state_repository.update_workflow_state(
                site_id=context.site_id,
                source_property_id=context.property.id,
                workflow_state="assets_prepared",
            )

        selected_photo_paths = tuple(list_image_files(selected_dir)) if selected_dir.exists() else ()
        primary_image_path = self.resolve_primary_image_from_dir(selected_dir)
        if not selected_photo_paths and primary_image_path is None:
            raise PhotoFilteringError(
                f"No curated images were prepared for property {context.property.id}.",
                code="CURATED_ASSET_SET_EMPTY",
                context=build_log_context(
                    site_id=context.site_id,
                    property_id=context.property.id,
                    selected_dir=selected_dir,
                ),
            )

        logger.info(
            format_console_block(
                "Curated Media Assets Prepared",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line("Selected image count", len(selected_photo_paths)),
                format_detail_line("Selected directory", selected_dir),
                format_detail_line("Primary image", primary_image_path or "<none>"),
            )
        )
        return PreparedMediaAssets(
            selected_dir=selected_dir,
            selected_photo_paths=selected_photo_paths,
            downloaded_images=tuple(downloaded_images),
            primary_image_path=primary_image_path,
        )

    def _prepare_primary_only_assets(self, context: PropertyContext) -> PreparedMediaAssets:
        _, raw_property_dir, raw_dir, selected_dir = prepare_property_directories(
            context.storage_paths.raw_images_root,
            context.storage_paths.filtered_images_root,
            context.property,
            clear_selected_dir=True,
        )
        selected_dir.mkdir(parents=True, exist_ok=True)

        primary_source_url = context.property.featured_image_url or next(
            iter(context.property.image_urls),
            None,
        )
        if not primary_source_url:
            shutil.rmtree(raw_property_dir, ignore_errors=True)
            raise PhotoFilteringError(
                f"Property {context.property.id} does not have an image available for status reel generation.",
                code="PRIMARY_IMAGE_MISSING",
                context=build_log_context(
                    site_id=context.site_id,
                    property_id=context.property.id,
                    asset_strategy=context.delivery_plan.asset_strategy,
                ),
            )

        downloaded_images = [
            (position, image_url, None)
            for position, image_url in enumerate(context.property.image_urls, start=1)
        ]
        primary_selected_path: Path | None = None
        try:
            raw_primary_path = raw_dir / build_primary_image_filename(primary_source_url)
            download_image(primary_source_url, raw_primary_path)
            primary_selected_path = selected_dir / build_primary_image_filename(
                primary_source_url,
                raw_primary_path,
            )
            shutil.copy2(raw_primary_path, primary_selected_path)
        except Exception as exc:
            raise PhotoFilteringError(
                "Failed to prepare the primary property image for status reel rendering. "
                f"Property ID: {context.property.id} | Source URL: {primary_source_url}",
                code="PRIMARY_ASSET_DOWNLOAD_FAILED",
                context=build_log_context(
                    site_id=context.site_id,
                    property_id=context.property.id,
                    source_url=primary_source_url,
                ),
                cause=exc,
            ) from exc
        finally:
            if should_cleanup_raw_property_dir(self.cleanup_temporary_files):
                shutil.rmtree(raw_property_dir, ignore_errors=True)

        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.property_repository.save_property_images(
                context.property,
                selected_dir,
                downloaded_images,
                site_id=context.site_id,
            )
            unit_of_work.pipeline_state_repository.update_workflow_state(
                site_id=context.site_id,
                source_property_id=context.property.id,
                workflow_state="assets_prepared",
            )

        logger.info(
            format_console_block(
                "Primary Status Reel Asset Prepared",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line("Selected directory", selected_dir),
                format_detail_line("Primary image", primary_selected_path or "<none>"),
                format_detail_line("Source URL", primary_source_url),
            )
        )
        return PreparedMediaAssets(
            selected_dir=selected_dir,
            selected_photo_paths=((primary_selected_path,) if primary_selected_path is not None else ()),
            downloaded_images=tuple(downloaded_images),
            primary_image_path=primary_selected_path,
        )


class DefaultPhotoSelectionService(DefaultMediaPreparationService):
    pass


class DefaultMediaRenderer:
    def __init__(self, workspace_dir: str | Path) -> None:
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()

    def render_media(
        self,
        context: PropertyContext,
        prepared_assets: PreparedMediaAssets,
    ) -> RenderedMediaArtifact:
        return self._render_reel(context, prepared_assets)

    def render_video(
        self,
        context: PropertyContext,
        selected_photos: PreparedMediaAssets,
    ) -> RenderedMediaArtifact:
        return self.render_media(context, selected_photos)

    def _render_reel(
        self,
        context: PropertyContext,
        prepared_assets: PreparedMediaAssets,
    ) -> RenderedMediaArtifact:
        revision_id = uuid4().hex
        template = build_reel_template_for_render_profile(context.delivery_plan.render_profile)
        staging_root = context.storage_paths.generated_reels_root / "_staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(
            tempfile.mkdtemp(prefix=f"{context.property.slug}-", dir=staging_root)
        )
        manifest_path = staging_dir / f"{context.property.slug}-reel.json"
        media_path = staging_dir / f"{context.property.slug}-reel.mp4"
        poster_path = staging_dir / f"{context.property.slug}-poster.jpg"
        selected_slides = build_local_selected_slides(
            prepared_assets.selected_dir,
            prepared_assets.selected_photo_paths,
        )
        property_render_data = self._build_render_data(
            context=context,
            prepared_assets=prepared_assets,
            selected_slides=selected_slides,
        )
        render_working_dir = staging_dir / "_prepared"
        prepared_render_assets = prepare_reel_render_assets(
            self.workspace_dir,
            property_render_data,
            template=template,
            working_dir=render_working_dir,
        )

        write_property_reel_manifest_from_data(
            self.workspace_dir,
            property_render_data,
            output_path=manifest_path,
            template=template,
            render_profile=context.delivery_plan.render_profile,
            prepared_assets=prepared_render_assets,
            working_dir=render_working_dir,
        )
        generate_property_reel_from_data(
            self.workspace_dir,
            property_render_data,
            output_path=media_path,
            template=template,
            prepared_assets=prepared_render_assets,
            working_dir=render_working_dir,
        )
        generate_property_poster_from_data(
            self.workspace_dir,
            property_render_data,
            output_path=poster_path,
        )
        logger.info(
            format_console_block(
                "Reel Render Completed",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line("Render profile", context.delivery_plan.render_profile),
                format_detail_line("Revision ID", revision_id),
                format_detail_line("Staging directory", staging_dir),
                format_detail_line("Manifest path", manifest_path),
                format_detail_line("Media path", media_path),
                format_detail_line("Poster path", poster_path),
            )
        )
        return RenderedMediaArtifact(
            staging_dir=staging_dir,
            artifact_kind="reel_video",
            media_path=media_path,
            metadata_path=manifest_path,
            revision_id=revision_id,
        )

    @staticmethod
    def _build_render_data(
        *,
        context: PropertyContext,
        prepared_assets: PreparedMediaAssets,
        selected_slides,
    ) -> PropertyRenderData:
        return PropertyRenderData(
            site_id=context.site_id,
            property_id=context.property.id,
            slug=context.property.slug,
            title=context.property.title or context.property.slug,
            link=context.property.link,
            property_status=context.property.property_status,
            listing_lifecycle=context.delivery_plan.listing_lifecycle,
            banner_text=context.delivery_plan.banner_text,
            selected_image_dir=prepared_assets.selected_dir,
            selected_image_paths=prepared_assets.selected_photo_paths,
            featured_image_url=context.property.featured_image_url,
            bedrooms=context.property.bedrooms,
            bathrooms=context.property.bathrooms,
            ber_rating=context.property.ber_rating,
            agent_name=context.property.agent_name,
            agent_photo_url=context.property.agent_photo_url,
            agent_email=context.property.agent_email,
            agent_mobile=context.property.agent_mobile,
            agent_number=context.property.agent_number,
            agency_psra=context.property.agency_psra,
            agency_logo_url=context.property.agency_logo_url,
            price=context.property.price,
            price_display_text=context.delivery_plan.price_display_text,
            property_type_label=context.property.property_type_label,
            property_area_label=context.property.property_area_label,
            property_county_label=context.property.property_county_label,
            eircode=context.property.eircode,
            property_size=context.property.property_size,
            selected_slides=tuple(selected_slides),
        )


class DefaultVideoRenderer(DefaultMediaRenderer):
    pass


class FileSystemMediaPublisher:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        cleanup_temporary_files: bool = DEFAULT_DELETE_TEMPORARY_FILES,
    ) -> None:
        self.unit_of_work_factory = unit_of_work_factory
        self.cleanup_temporary_files = bool(cleanup_temporary_files)

    def publish_media(
        self,
        context: PropertyContext,
        rendered_media: RenderedMediaArtifact,
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

        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.pipeline_state_repository.save_local_artifacts(
                site_id=context.site_id,
                source_property_id=context.property.id,
                artifact_kind=rendered_media.artifact_kind,
                artifact_path=final_media_path,
                metadata_path=final_metadata_path,
                render_profile=context.delivery_plan.render_profile,
                current_revision_id=revision_id,
            )
            unit_of_work.media_revision_store.save_media_revision(
                MediaRevisionRecord(
                    revision_id=revision_id,
                    site_id=context.site_id,
                    source_property_id=context.property.id,
                    artifact_kind=rendered_media.artifact_kind,
                    render_profile=context.delivery_plan.render_profile,
                    media_path=_relative_path_text(context.workspace_dir, final_media_path),
                    metadata_path=_relative_path_text(context.workspace_dir, final_metadata_path),
                    mime_type=rendered_media.mime_type,
                    content_fingerprint=context.content_fingerprint,
                    publish_target_fingerprint=context.publish_target_fingerprint,
                    workflow_state="rendered",
                    created_at=_now_iso(),
                )
            )
            unit_of_work.outbox_event_store.add_event(
                event_id=uuid4().hex,
                aggregate_type="property_media",
                aggregate_id=f"{context.site_id}:{context.property.id}",
                event_type="media_rendered",
                payload=_build_workflow_payload(
                    context,
                    workflow_state="rendered",
                    revision_id=revision_id,
                    extra={
                        "media_path": _relative_path_text(context.workspace_dir, final_media_path),
                        "metadata_path": _relative_path_text(context.workspace_dir, final_metadata_path),
                        "mime_type": rendered_media.mime_type,
                    },
                ),
                site_id=context.site_id,
                source_property_id=context.property.id,
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

    def publish_video(
        self,
        context: PropertyContext,
        rendered_video: RenderedMediaArtifact,
    ) -> PublishedMediaArtifact:
        return self.publish_media(context, rendered_video)

    def publish_existing_media(self, context: PropertyContext) -> PublishedMediaArtifact:
        if context.existing_published_media is None:
            raise ValidationError(
                "An existing published media artifact is required for publish-only retries.",
                code="EXISTING_MEDIA_REQUIRED",
                context=build_log_context(
                    site_id=context.site_id,
                    property_id=context.property.id,
                    requires_render=context.requires_render,
                ),
                hint="Re-render the media or restore the published artifact files before retrying a publish-only workflow.",
            )
        return context.existing_published_media

    def publish_existing_video(self, context: PropertyContext) -> PublishedMediaArtifact:
        return self.publish_existing_media(context)

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
        poster_source_path = rendered_media.staging_dir / f"{context.property.slug}-poster.jpg"
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
                        "Verify poster rendering completed successfully before the local publish step "
                        "and keep the staging poster alongside the reel output."
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


class FileSystemVideoPublisher(FileSystemMediaPublisher):
    pass


class CompositeMediaPublisher:
    def __init__(
        self,
        *,
        local_publisher: FileSystemMediaPublisher,
        unit_of_work_factory: Callable[[], UnitOfWork],
        social_publisher: GoHighLevelPropertyPublisher | None = None,
    ) -> None:
        self.local_publisher = local_publisher
        self.unit_of_work_factory = unit_of_work_factory
        self.social_publisher = social_publisher

    def publish_media(
        self,
        context: PropertyContext,
        rendered_media: RenderedMediaArtifact,
    ) -> PublishedMediaArtifact:
        published_media = self.local_publisher.publish_media(context, rendered_media)
        return self._publish_externally(context, published_media)

    def publish_video(
        self,
        context: PropertyContext,
        rendered_video: RenderedMediaArtifact,
    ) -> PublishedMediaArtifact:
        return self.publish_media(context, rendered_video)

    def publish_existing_media(self, context: PropertyContext) -> PublishedMediaArtifact:
        if context.existing_published_media is None:
            raise ValidationError(
                "An existing published media artifact is required for publish-only retries.",
                code="EXISTING_MEDIA_REQUIRED",
                context=build_log_context(
                    site_id=context.site_id,
                    property_id=context.property.id,
                    requires_render=context.requires_render,
                ),
                hint="Re-render the media or restore the published artifact files before retrying a publish-only workflow.",
            )
        return self._publish_externally(context, context.existing_published_media)

    def publish_existing_video(self, context: PropertyContext) -> PublishedMediaArtifact:
        return self.publish_existing_media(context)

    def _publish_externally(
        self,
        context: PropertyContext,
        published_media: PublishedMediaArtifact,
    ) -> PublishedMediaArtifact:
        if (
            self.social_publisher is None
            or not context.requires_external_publish
            or context.publish_context is None
        ):
            self._persist_workflow_transition(
                context,
                published_media,
                workflow_state="skipped",
                outbox_event_type="publish_skipped",
                publish_status="skipped",
                details={"reason": "not_required"},
            )
            return published_media

        if REVIEW_WORKFLOW_ENABLED:
            self._persist_workflow_transition(
                context,
                published_media,
                workflow_state="awaiting_review",
                outbox_event_type="review_requested",
                publish_status="pending_review",
                details={"reason": "review_workflow_enabled"},
                last_published_location_id=context.publish_context.location_id,
            )
            logger.info(
                format_console_block(
                    "Review Requested",
                    format_detail_line("Site ID", context.site_id),
                    format_detail_line("Property ID", context.property.id),
                    format_detail_line("Revision ID", published_media.revision_id or "<none>"),
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
                format_detail_line("Revision ID", published_media.revision_id or "<none>"),
                format_detail_line("Location ID", context.publish_context.location_id),
                format_detail_line("Desired platforms", ", ".join(context.pending_publish_platforms)),
                format_detail_line(
                    "Publish targets",
                    ", ".join(
                        f"{target.platform}:{target.artifact_kind}"
                        for target in context.publish_targets
                        if target.platform in context.pending_publish_platforms
                    ) or "<none>",
                ),
            )
        )

        try:
            publish_result = self.social_publisher.publish_property_media(context, published_media)
        except Exception as error:
            failure_details = extract_error_details(error)
            if isinstance(
                error,
                (SocialPublishingResultError, TransientSocialPublishingResultError),
            ) and isinstance(error.result, MultiPlatformPublishResult):
                failure_details = self._build_publish_details(error.result)
            logger.error(
                format_console_block(
                    "Social Media Publish Failed",
                    format_detail_line("Site ID", context.site_id),
                    format_detail_line("Property ID", context.property.id),
                    format_detail_line("Location ID", context.publish_context.location_id),
                    format_detail_line("Error stage", failure_details.get("stage")),
                    format_detail_line("Error code", failure_details.get("code")),
                    format_detail_line("Error", failure_details.get("message") or error),
                    format_context_line(
                        failure_details.get("context")
                        if isinstance(failure_details.get("context"), dict)
                        else None
                    ),
                )
            )
            self._persist_workflow_transition(
                context,
                published_media,
                workflow_state="failed",
                outbox_event_type="publish_failed",
                publish_status="failed",
                details=failure_details,
                last_published_location_id=context.publish_context.location_id,
            )
            raise

        if publish_result is None:
            self._persist_workflow_transition(
                context,
                published_media,
                workflow_state="skipped",
                outbox_event_type="publish_skipped",
                publish_status="skipped",
                details={"reason": "not_required"},
            )
            return published_media

        publish_details = self._build_publish_details(publish_result)
        aggregate_status = publish_result.aggregate_status
        self._persist_workflow_transition(
            context,
            published_media,
            workflow_state=aggregate_status,
            outbox_event_type=(
                "publish_completed"
                if aggregate_status in {"published", "partial"}
                else "publish_failed"
            ),
            publish_status=aggregate_status,
            details=publish_details,
            last_published_location_id=context.publish_context.location_id,
        )

        logger.info(
            format_console_block(
                "Social Media Publish Completed",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line("Artifact kind", published_media.artifact_kind),
                format_detail_line("Revision ID", published_media.revision_id or "<none>"),
                format_detail_line("Desired platforms", ", ".join(context.pending_publish_platforms)),
                format_detail_line("Successful platforms", ", ".join(publish_result.successful_platforms)),
                format_detail_line("Aggregate status", aggregate_status),
                format_detail_line("Location ID", context.publish_context.location_id),
            )
        )
        return published_media

    def _persist_workflow_transition(
        self,
        context: PropertyContext,
        published_media: PublishedMediaArtifact,
        *,
        workflow_state: str,
        outbox_event_type: str,
        publish_status: str | None = None,
        details: dict[str, object] | None = None,
        last_published_location_id: str = "",
    ) -> None:
        with self.unit_of_work_factory() as unit_of_work:
            if publish_status is not None:
                unit_of_work.pipeline_state_repository.update_social_publish_status(
                    site_id=context.site_id,
                    source_property_id=context.property.id,
                    status=publish_status,
                    details=details,
                    last_published_location_id=last_published_location_id,
                )
            unit_of_work.pipeline_state_repository.update_workflow_state(
                site_id=context.site_id,
                source_property_id=context.property.id,
                workflow_state=workflow_state,
                current_revision_id=published_media.revision_id or None,
            )
            if published_media.revision_id:
                unit_of_work.media_revision_store.save_media_revision(
                    MediaRevisionRecord(
                        revision_id=published_media.revision_id,
                        site_id=context.site_id,
                        source_property_id=context.property.id,
                        artifact_kind=published_media.artifact_kind,
                        render_profile=context.delivery_plan.render_profile,
                        media_path=_relative_path_text(context.workspace_dir, published_media.media_path),
                        metadata_path=_relative_path_text(context.workspace_dir, published_media.metadata_path),
                        mime_type=published_media.mime_type,
                        content_fingerprint=context.content_fingerprint,
                        publish_target_fingerprint=context.publish_target_fingerprint,
                        workflow_state=workflow_state,
                        created_at=_now_iso(),
                    )
                )
            unit_of_work.outbox_event_store.add_event(
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
                site_id=context.site_id,
                source_property_id=context.property.id,
            )

    @staticmethod
    def _build_publish_details(publish_result: MultiPlatformPublishResult) -> dict[str, object]:
        return publish_result.to_dict()


class CompositeVideoPublisher(CompositeMediaPublisher):
    pass


__all__ = [
    "CompositeMediaPublisher",
    "CompositeVideoPublisher",
    "DefaultMediaPreparationService",
    "DefaultMediaRenderer",
    "DefaultPhotoSelectionService",
    "DefaultPropertyInfoService",
    "DefaultVideoRenderer",
    "FileSystemMediaPublisher",
    "FileSystemVideoPublisher",
    "LocalPhotoSelectionEngine",
]
