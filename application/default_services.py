from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from application.persistence import UnitOfWork
from application.types import (
    PropertyContext,
    PropertyVideoJob,
    PublishedVideoArtifact,
    RenderedVideoArtifact,
    SelectedPhotoSet,
)
from config import DEFAULT_PHOTOS_TO_SELECT
from core.logging import format_console_block, format_detail_line
from models.property import Property
from repositories.property_pipeline_repository import PropertyPipelineState
from services.reel_rendering import (
    PropertyRenderData,
    generate_property_reel_from_data,
    write_property_reel_manifest_from_data,
)
from services.reel_rendering.runtime import build_local_selected_slides
from services.social_delivery import (
    GoHighLevelPropertyPublisher,
    PublishVideoResult,
    build_property_public_url,
    build_tiktok_description_for_property,
)
from services.webhook_transport.site_storage import resolve_site_storage_layout
from services.property_media import download_and_filter_property_images
from services.property_media.filesystem import list_image_files

logger = logging.getLogger(__name__)


def _default_pipeline_state(site_id: str, source_property_id: int) -> PropertyPipelineState:
    return PropertyPipelineState(
        site_id=site_id,
        source_property_id=source_property_id,
        content_fingerprint="",
        content_snapshot_json="",
        publish_target_fingerprint="",
        publish_target_snapshot_json="",
        selected_image_folder="",
        local_manifest_path="",
        local_video_path="",
        render_status="",
        publish_status="",
        publish_details_json="",
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


class LocalPhotoSelectionEngine:
    def __init__(self, *, photos_to_select: int = DEFAULT_PHOTOS_TO_SELECT) -> None:
        self.photos_to_select = photos_to_select

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
    ) -> None:
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.unit_of_work_factory = unit_of_work_factory
        self.property_url_template = property_url_template
        self.property_url_tracking_params = dict(property_url_tracking_params or {})
        self.social_publishing_enabled = social_publishing_enabled

    def ingest_property(self, job: PropertyVideoJob) -> PropertyContext:
        storage_paths = resolve_site_storage_layout(self.workspace_dir, job.site_id)
        property_item = Property.from_api_payload(job.payload)
        publish_context = job.publish_context if self.social_publishing_enabled else None
        publish_target_url = (
            build_property_public_url(
                site_id=job.site_id,
                slug=property_item.slug,
                property_link=property_item.link,
                property_url_template=self.property_url_template,
                tracking_query_params=self.property_url_tracking_params,
            )
            if publish_context is not None
            else None
        )
        publish_description = (
            build_tiktok_description_for_property(
                property_item,
                site_id=job.site_id,
                property_url_template=self.property_url_template,
                tracking_query_params=self.property_url_tracking_params,
            )
            if publish_context is not None
            else None
        )
        content_snapshot = self._build_content_snapshot(property_item)
        content_snapshot_json = _json_text(content_snapshot)
        content_fingerprint = _json_hash(content_snapshot)
        publish_target_snapshot = self._build_publish_target_snapshot(
            publish_context=publish_context,
            description=publish_description,
            target_url=publish_target_url,
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
            state = existing_state or _default_pipeline_state(job.site_id, property_item.id)

            has_local_artifacts = self._has_local_artifacts(state)
            content_changed = (
                state.content_snapshot_json != content_snapshot_json
                or state.content_fingerprint != content_fingerprint
            )
            publish_target_changed = (
                state.publish_target_snapshot_json != publish_target_snapshot_json
                or state.publish_target_fingerprint != publish_target_fingerprint
            )
            publish_complete = publish_context is None or self._is_social_publish_complete(state)

            is_noop = (
                not content_changed
                and not publish_target_changed
                and has_local_artifacts
                and publish_complete
            )
            requires_render = content_changed or not has_local_artifacts
            requires_photo_selection = requires_render
            requires_external_publish = publish_context is not None and (
                requires_render
                or publish_target_changed
                or not self._is_social_publish_complete(state)
            )

            existing_published_video = None
            if has_local_artifacts:
                manifest_path = _resolve_absolute_path(self.workspace_dir, state.local_manifest_path)
                video_path = _resolve_absolute_path(self.workspace_dir, state.local_video_path)
                if manifest_path is not None and video_path is not None:
                    existing_published_video = PublishedVideoArtifact(
                        manifest_path=manifest_path,
                        video_path=video_path,
                    )

            if not is_noop:
                next_state = PropertyPipelineState(
                    site_id=job.site_id,
                    source_property_id=property_item.id,
                    content_fingerprint=content_fingerprint,
                    content_snapshot_json=content_snapshot_json,
                    publish_target_fingerprint=publish_target_fingerprint,
                    publish_target_snapshot_json=publish_target_snapshot_json,
                    selected_image_folder=(
                        state.selected_image_folder if not requires_render else ""
                    ),
                    local_manifest_path=state.local_manifest_path if not requires_render else "",
                    local_video_path=state.local_video_path if not requires_render else "",
                    render_status="pending" if requires_render else "completed",
                    publish_status=(
                        "pending" if publish_context is not None else "skipped"
                    ),
                    publish_details_json="" if publish_context is not None else state.publish_details_json,
                    last_published_location_id=(
                        state.last_published_location_id
                        if not publish_target_changed
                        else ""
                    ),
                    created_at=state.created_at,
                    updated_at=state.updated_at,
                )
                unit_of_work.pipeline_state_repository.save_property_pipeline_state(next_state)

        if is_noop:
            logger.info(
                format_console_block(
                    "Property Delivery Skipped",
                    format_detail_line("Event ID", job.event_id),
                    format_detail_line("Site ID", job.site_id),
                    format_detail_line("Property ID", property_item.id),
                    "The property content, publish target, and local artifacts are unchanged.",
                )
            )
        else:
            logger.info(
                format_console_block(
                    "Property Metadata Saved",
                    format_detail_line("Event ID", job.event_id),
                    format_detail_line("Site ID", job.site_id),
                    format_detail_line("Property ID", property_item.id),
                    format_detail_line("Requires render", "Yes" if requires_render else "No"),
                    format_detail_line(
                        "Requires external publish",
                        "Yes" if requires_external_publish else "No",
                    ),
                )
            )

        return PropertyContext(
            workspace_dir=self.workspace_dir,
            storage_paths=storage_paths,
            site_id=job.site_id,
            property=property_item,
            publish_context=publish_context,
            publish_description=publish_description,
            publish_target_url=publish_target_url,
            content_fingerprint=content_fingerprint,
            content_snapshot_json=content_snapshot_json,
            publish_target_fingerprint=publish_target_fingerprint,
            publish_target_snapshot_json=publish_target_snapshot_json,
            requires_photo_selection=requires_photo_selection,
            requires_render=requires_render,
            requires_external_publish=requires_external_publish,
            existing_published_video=existing_published_video,
            is_noop=is_noop,
        )

    @staticmethod
    def _build_content_snapshot(property_item: Property) -> dict[str, object]:
        snapshot = property_item.to_dict()
        snapshot.pop("raw_data", None)
        return snapshot

    @staticmethod
    def _build_publish_target_snapshot(
        *,
        publish_context,
        description: str | None,
        target_url: str | None,
    ) -> dict[str, object]:
        if publish_context is None:
            return {}
        return {
            "provider": publish_context.provider,
            "platform": publish_context.platform,
            "location_id": publish_context.location_id,
            "description": description or "",
            "target_url": target_url or "",
        }

    def _has_local_artifacts(self, state: PropertyPipelineState) -> bool:
        manifest_path = _resolve_absolute_path(self.workspace_dir, state.local_manifest_path)
        video_path = _resolve_absolute_path(self.workspace_dir, state.local_video_path)
        return bool(
            manifest_path
            and video_path
            and manifest_path.exists()
            and manifest_path.stat().st_size > 0
            and video_path.exists()
            and video_path.stat().st_size > 0
            and state.render_status == "completed"
        )

    @staticmethod
    def _is_social_publish_complete(state: PropertyPipelineState) -> bool:
        if state.publish_status == "skipped":
            return True
        if state.publish_status != "published":
            return False

        details = _parse_json_object(state.publish_details_json)
        post_id = str(details.get("post_id") or "").strip()
        post_status = str(details.get("post_status") or "").strip().lower()
        if post_id:
            return True
        return post_status in {"published", "scheduled", "queued", "processing", "created", "accepted"}


class DefaultPhotoSelectionService:
    def __init__(
        self,
        workspace_dir: str | Path,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        engine: LocalPhotoSelectionEngine | None = None,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.unit_of_work_factory = unit_of_work_factory
        self.engine = engine or LocalPhotoSelectionEngine()

    def select_photos(self, context: PropertyContext) -> SelectedPhotoSet:
        selected_dir, downloaded_images = self.engine.select_photos(
            property_item=context.property,
            raw_images_root=context.storage_paths.raw_images_root,
            filtered_images_root=context.storage_paths.filtered_images_root,
        )
        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.property_repository.save_property_images(
                context.property,
                selected_dir,
                downloaded_images,
                site_id=context.site_id,
            )
        selected_photo_paths = tuple(list_image_files(selected_dir))
        logger.info(
            format_console_block(
                "Photo Selection Completed",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line("Selected photo count", len(selected_photo_paths)),
                format_detail_line("Selected directory", selected_dir),
            )
        )

        return SelectedPhotoSet(
            selected_dir=selected_dir,
            selected_photo_paths=selected_photo_paths,
            downloaded_images=tuple(downloaded_images),
        )


class DefaultVideoRenderer:
    def __init__(self, workspace_dir: str | Path) -> None:
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()

    def render_video(
        self,
        context: PropertyContext,
        selected_photos: SelectedPhotoSet,
    ) -> RenderedVideoArtifact:
        staging_root = context.storage_paths.reels_root / "_staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        staging_dir = Path(
            tempfile.mkdtemp(prefix=f"{context.property.slug}-", dir=staging_root)
        )

        manifest_path = staging_dir / f"{context.property.slug}-reel.json"
        video_path = staging_dir / f"{context.property.slug}-reel.mp4"
        selected_slides = build_local_selected_slides(
            selected_photos.selected_dir,
            selected_photos.selected_photo_paths,
        )
        property_render_data = PropertyRenderData(
            site_id=context.site_id,
            property_id=context.property.id,
            slug=context.property.slug,
            title=context.property.title or context.property.slug,
            link=context.property.link,
            property_status=context.property.property_status,
            selected_image_dir=selected_photos.selected_dir,
            selected_image_paths=selected_photos.selected_photo_paths,
            featured_image_url=context.property.featured_image_url,
            bedrooms=context.property.bedrooms,
            bathrooms=context.property.bathrooms,
            ber_rating=context.property.ber_rating,
            agent_name=context.property.agent_name,
            agent_photo_url=context.property.agent_photo_url,
            agent_email=context.property.agent_email,
            agent_mobile=context.property.agent_mobile,
            agent_number=context.property.agent_number,
            price=context.property.price,
            property_type_label=context.property.property_type_label,
            property_area_label=context.property.property_area_label,
            property_county_label=context.property.property_county_label,
            eircode=context.property.eircode,
            selected_slides=selected_slides,
        )

        write_property_reel_manifest_from_data(
            self.workspace_dir,
            property_render_data,
            output_path=manifest_path,
        )
        generate_property_reel_from_data(
            self.workspace_dir,
            property_render_data,
            output_path=video_path,
        )
        logger.info(
            format_console_block(
                "Video Render Completed",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line("Staging directory", staging_dir),
                format_detail_line("Manifest path", manifest_path),
                format_detail_line("Video path", video_path),
            )
        )

        return RenderedVideoArtifact(
            staging_dir=staging_dir,
            manifest_path=manifest_path,
            video_path=video_path,
        )


class FileSystemVideoPublisher:
    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self.unit_of_work_factory = unit_of_work_factory

    def publish_video(
        self,
        context: PropertyContext,
        rendered_video: RenderedVideoArtifact,
    ) -> PublishedVideoArtifact:
        final_output_dir = context.storage_paths.reels_root
        final_output_dir.mkdir(parents=True, exist_ok=True)

        final_manifest_path = final_output_dir / rendered_video.manifest_path.name
        final_video_path = final_output_dir / rendered_video.video_path.name

        self._replace_atomically(rendered_video.manifest_path, final_manifest_path)
        self._replace_atomically(rendered_video.video_path, final_video_path)
        shutil.rmtree(rendered_video.staging_dir, ignore_errors=True)
        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.pipeline_state_repository.save_local_artifacts(
                site_id=context.site_id,
                source_property_id=context.property.id,
                manifest_path=final_manifest_path,
                video_path=final_video_path,
            )
        logger.info(
            format_console_block(
                "Local Reel Publish Completed",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line("Manifest path", final_manifest_path),
                format_detail_line("Video path", final_video_path),
            )
        )

        return PublishedVideoArtifact(
            manifest_path=final_manifest_path,
            video_path=final_video_path,
        )

    @staticmethod
    def _replace_atomically(source_path: Path, destination_path: Path) -> None:
        temporary_path = destination_path.with_suffix(f"{destination_path.suffix}.tmp")
        shutil.copy2(source_path, temporary_path)
        os.replace(temporary_path, destination_path)


class CompositeVideoPublisher:
    def __init__(
        self,
        *,
        local_publisher: FileSystemVideoPublisher,
        unit_of_work_factory: Callable[[], UnitOfWork],
        social_publisher: GoHighLevelPropertyPublisher | None = None,
    ) -> None:
        self.local_publisher = local_publisher
        self.unit_of_work_factory = unit_of_work_factory
        self.social_publisher = social_publisher

    def publish_video(
        self,
        context: PropertyContext,
        rendered_video: RenderedVideoArtifact,
    ) -> PublishedVideoArtifact:
        published_video = self.local_publisher.publish_video(context, rendered_video)
        return self._publish_externally(context, published_video)

    def publish_existing_video(self, context: PropertyContext) -> PublishedVideoArtifact:
        if context.existing_published_video is None:
            raise RuntimeError("An existing published video is required for publish-only retries.")
        return self._publish_externally(context, context.existing_published_video)

    def _publish_externally(
        self,
        context: PropertyContext,
        published_video: PublishedVideoArtifact,
    ) -> PublishedVideoArtifact:
        if (
            self.social_publisher is None
            or not context.requires_external_publish
            or context.publish_context is None
        ):
            with self.unit_of_work_factory() as unit_of_work:
                unit_of_work.pipeline_state_repository.update_social_publish_status(
                    site_id=context.site_id,
                    source_property_id=context.property.id,
                    status="skipped",
                    details={"reason": "not_required"},
                )
            return published_video

        try:
            publish_result = self.social_publisher.publish_property_reel(context, published_video)
        except Exception as error:
            with self.unit_of_work_factory() as unit_of_work:
                unit_of_work.pipeline_state_repository.update_social_publish_status(
                    site_id=context.site_id,
                    source_property_id=context.property.id,
                    status="failed",
                    details={"error": str(error)},
                    last_published_location_id=context.publish_context.location_id,
                )
            raise

        if publish_result is None:
            with self.unit_of_work_factory() as unit_of_work:
                unit_of_work.pipeline_state_repository.update_social_publish_status(
                    site_id=context.site_id,
                    source_property_id=context.property.id,
                    status="skipped",
                    details={"reason": "not_required"},
                )
            return published_video

        with self.unit_of_work_factory() as unit_of_work:
            unit_of_work.pipeline_state_repository.update_social_publish_status(
                site_id=context.site_id,
                source_property_id=context.property.id,
                status="published",
                details=self._build_publish_details(publish_result),
                last_published_location_id=context.publish_context.location_id,
            )
        logger.info(
            format_console_block(
                "Social Publish Completed",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line("Platform", context.publish_context.platform),
                format_detail_line("Location ID", context.publish_context.location_id),
            )
        )
        return published_video

    @staticmethod
    def _build_publish_details(publish_result: PublishVideoResult) -> dict[str, object]:
        return {
            "account_id": publish_result.selected_account.id,
            "platform": publish_result.selected_account.platform,
            "post_id": publish_result.created_post.post_id,
            "post_status": publish_result.created_post.status,
            "message": publish_result.created_post.message,
            "trace_id": publish_result.created_post.raw_response.get("traceId"),
            "uploaded_media_url": publish_result.uploaded_media.url,
            "description": publish_result.description,
        }


__all__ = [
    "CompositeVideoPublisher",
    "DefaultPhotoSelectionService",
    "DefaultPropertyInfoService",
    "DefaultVideoRenderer",
    "FileSystemVideoPublisher",
    "LocalPhotoSelectionEngine",
]

