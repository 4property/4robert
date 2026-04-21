from __future__ import annotations

import logging
from pathlib import Path

from application.types import PlatformPublishTargetPlan, PropertyContext, PublishedMediaArtifact
from settings import SELECTED_PHOTOS_DIRNAME
from core.errors import SocialPublishingError
from core.logging import format_console_block, format_detail_line
from services.media.property_media.filesystem import list_image_files
from services.media.reel_rendering.models import PropertyRenderData
from services.media.reel_rendering.poster import (
    generate_property_poster_from_data,
    resolve_property_poster_output_path,
)
from services.media.reel_rendering.runtime import build_local_selected_slides
from services.publishing.social_delivery.gohighlevel_publisher import GoHighLevelPublisher
from services.publishing.social_delivery.models import (
    MultiPlatformPublishRequest,
    MultiPlatformPublishResult,
    PlatformPublishTarget,
)
from services.publishing.social_delivery.platforms import get_platform_config
from services.publishing.social_delivery.platform_policy import (
    normalize_platform_name,
)

logger = logging.getLogger(__name__)


class GoHighLevelPropertyPublisher:
    def __init__(
        self,
        *,
        publisher: GoHighLevelPublisher,
    ) -> None:
        self.publisher = publisher

    def publish_property_media(
        self,
        context: PropertyContext,
        published_media: PublishedMediaArtifact,
    ) -> MultiPlatformPublishResult | None:
        if context.publish_context is None:
            logger.info(
                format_console_block(
                    "Social Publish Skipped",
                    format_detail_line("Site ID", context.site_id),
                    format_detail_line("Property ID", context.property.id),
                    "No publish context was attached to this job.",
                )
            )
            return None

        publish_targets = self._build_publish_targets(
            context=context,
            published_media=published_media,
        )
        logger.info(
            format_console_block(
                "Social Publish Batch Planned",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line("Location ID", context.publish_context.location_id),
                format_detail_line(
                    "Targets",
                    ", ".join(
                        f"{target.platform}:{target.artifact_kind}"
                        for target in publish_targets
                    ) or "<none>",
                ),
            )
        )

        request = MultiPlatformPublishRequest(
            media_path=published_media.media_path,
            descriptions_by_platform=dict(context.publish_descriptions_by_platform),
            titles_by_platform=dict(context.publish_titles_by_platform),
            publish_targets=publish_targets,
            upload_file_name=self._resolve_batch_upload_file_name(publish_targets),
            target_url=context.publish_target_url,
            provider=context.publish_context.provider,
            location_id=context.publish_context.location_id,
            access_token=context.publish_context.access_token,
            platforms=context.pending_publish_platforms,
            source_site_id=context.site_id,
            social_post_type=context.delivery_plan.social_post_type,
            artifact_kind=context.delivery_plan.artifact_kind,
        )
        publish_to_platforms = getattr(self.publisher, "publish_media_to_platforms", None)
        if publish_to_platforms is None:
            publish_to_platforms = getattr(self.publisher, "publish_video_to_platforms")
        return publish_to_platforms(request)

    def publish_property_reel(
        self,
        context: PropertyContext,
        published_video: PublishedMediaArtifact,
    ) -> MultiPlatformPublishResult | None:
        return self.publish_property_media(context, published_video)

    def _build_publish_targets(
        self,
        *,
        context: PropertyContext,
        published_media: PublishedMediaArtifact,
    ) -> tuple[PlatformPublishTarget, ...]:
        normalized_pending_platforms = tuple(
            normalized_platform
            for platform in context.pending_publish_platforms
            if (normalized_platform := normalize_platform_name(platform))
        )
        planned_targets_by_platform = {
            normalize_platform_name(target.platform): target
            for target in context.publish_targets
            if normalize_platform_name(target.platform) in normalized_pending_platforms
        }
        planned_targets: list[PlatformPublishTargetPlan] = []
        for platform in normalized_pending_platforms:
            normalized_platform = normalize_platform_name(platform)
            if not normalized_platform:
                continue
            platform_config = get_platform_config(normalized_platform)
            if platform_config is None:
                continue
            existing_target = planned_targets_by_platform.get(normalized_platform)
            resolved_title = (
                str(existing_target.title or "").strip() or None
                if existing_target is not None
                else None
            ) or self._resolve_target_title(
                context=context,
                platform=normalized_platform,
            )
            description = (
                str(existing_target.description or "").strip()
                if existing_target is not None
                else ""
            ) or str(
                context.publish_descriptions_by_platform.get(normalized_platform)
                or context.publish_descriptions_by_platform.get(platform)
                or platform_config.build_description(
                    context.property,
                    str(context.publish_target_url or context.property.link or ""),
                )
            )
            planned_targets.append(
                PlatformPublishTargetPlan(
                    platform=normalized_platform,
                    artifact_kind=platform_config.resolve_artifact_kind(
                        (
                            existing_target.artifact_kind
                            if existing_target is not None
                            else context.delivery_plan.artifact_kind
                        )
                    ),
                    social_post_type=platform_config.resolve_social_post_type(
                        (
                            existing_target.social_post_type
                            if existing_target is not None
                            else context.delivery_plan.social_post_type
                        )
                    ),
                    description=description,
                    title=resolved_title,
                    target_url=(
                        existing_target.target_url
                        if existing_target is not None and existing_target.target_url is not None
                        else context.publish_target_url
                    ),
                )
            )
        poster_path: Path | None = None
        publish_targets: list[PlatformPublishTarget] = []
        for target in planned_targets:
            resolved_title = target.title or self._resolve_target_title(
                context=context,
                platform=target.platform,
            )
            if target.artifact_kind == published_media.artifact_kind:
                media_path = published_media.media_path
            elif target.artifact_kind == "poster_image":
                if poster_path is None:
                    poster_path = self._ensure_poster_artifact(context)
                media_path = poster_path
            else:
                raise SocialPublishingError(
                    f"Unsupported publish artifact kind for social delivery: {target.artifact_kind}",
                )

            publish_targets.append(
                PlatformPublishTarget(
                    platform=target.platform,
                    media_path=media_path,
                    description=target.description,
                    title=resolved_title,
                    upload_file_name=self._resolve_target_upload_file_name(
                        platform=target.platform,
                        title=resolved_title,
                    ),
                    target_url=target.target_url,
                    social_post_type=target.social_post_type,
                    artifact_kind=target.artifact_kind,
                )
            )
        return tuple(publish_targets)

    def _ensure_poster_artifact(self, context: PropertyContext) -> Path:
        existing_poster_path = resolve_property_poster_output_path(
            context.workspace_dir,
            site_id=context.site_id,
            slug=context.property.slug,
        )
        if existing_poster_path.exists() and existing_poster_path.stat().st_size > 0:
            logger.info(
                format_console_block(
                    "Poster Reused",
                    format_detail_line("Site ID", context.site_id),
                    format_detail_line("Property ID", context.property.id),
                    format_detail_line("Poster path", existing_poster_path),
                )
            )
            return existing_poster_path

        selected_dir = (
            context.storage_paths.filtered_images_root
            / context.property.folder_name
            / SELECTED_PHOTOS_DIRNAME
        ).resolve()
        selected_image_paths = tuple(list_image_files(selected_dir)) if selected_dir.exists() else ()
        if not selected_image_paths:
            raise SocialPublishingError(
                "Poster publish target could not be prepared because no selected property images were found.",
            )

        logger.info(
            format_console_block(
                "Poster Render Started",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line("Selected images", len(selected_image_paths)),
            )
        )
        poster_path = generate_property_poster_from_data(
            context.workspace_dir,
            self._build_property_render_data(
                context=context,
                selected_dir=selected_dir,
                selected_image_paths=selected_image_paths,
            ),
        )
        logger.info(
            format_console_block(
                "Poster Render Completed",
                format_detail_line("Site ID", context.site_id),
                format_detail_line("Property ID", context.property.id),
                format_detail_line("Poster path", poster_path),
            )
        )
        return poster_path

    @staticmethod
    def _resolve_target_upload_file_name(*, platform: str, title: str | None) -> str | None:
        platform_config = get_platform_config(platform)
        if platform_config is None:
            return None
        return platform_config.build_upload_file_name(title)

    @classmethod
    def _resolve_batch_upload_file_name(
        cls,
        publish_targets: tuple[PlatformPublishTarget, ...],
    ) -> str | None:
        for target in publish_targets:
            upload_file_name = cls._resolve_target_upload_file_name(
                platform=target.platform,
                title=target.title,
            )
            if upload_file_name:
                return upload_file_name
        return None

    @staticmethod
    def _resolve_target_title(*, context: PropertyContext, platform: str) -> str | None:
        normalized_title = str(context.publish_titles_by_platform.get(platform) or "").strip()
        if normalized_title:
            return normalized_title
        platform_config = get_platform_config(platform)
        if platform_config is None:
            return None
        return platform_config.build_title(context.property)

    @staticmethod
    def _build_property_render_data(
        *,
        context: PropertyContext,
        selected_dir: Path,
        selected_image_paths: tuple[Path, ...],
    ) -> PropertyRenderData:
        selected_slides = build_local_selected_slides(
            selected_dir,
            selected_image_paths=selected_image_paths,
        )
        return PropertyRenderData(
            site_id=context.site_id,
            property_id=context.property.id,
            slug=context.property.slug,
            title=context.property.title or context.property.slug,
            link=context.property.link,
            property_status=context.property.property_status,
            listing_lifecycle=context.delivery_plan.listing_lifecycle,
            banner_text=context.delivery_plan.banner_text,
            selected_image_dir=selected_dir,
            selected_image_paths=selected_image_paths,
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
            viewing_times=context.property.viewing_times,
            selected_slides=tuple(selected_slides),
        )


__all__ = ["GoHighLevelPropertyPublisher"]
