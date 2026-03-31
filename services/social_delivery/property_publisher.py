from __future__ import annotations

import logging

from application.types import PropertyContext, PublishedMediaArtifact
from core.logging import format_console_block, format_detail_line
from services.social_delivery.gohighlevel_publisher import GoHighLevelPublisher
from services.social_delivery.models import (
    MultiPlatformPublishRequest,
    MultiPlatformPublishResult,
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

        request = MultiPlatformPublishRequest(
            media_path=published_media.media_path,
            descriptions_by_platform=dict(context.publish_descriptions_by_platform),
            titles_by_platform={
                "youtube": (context.property.title or context.property.slug).strip()
            },
            upload_file_name=(
                (context.property.title or context.property.slug).strip()
                if "youtube" in context.pending_publish_platforms
                else None
            ),
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


__all__ = ["GoHighLevelPropertyPublisher"]
