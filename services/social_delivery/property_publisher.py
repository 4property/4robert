from __future__ import annotations

import logging

from application.types import PropertyContext, PublishedVideoArtifact
from core.logging import format_console_block, format_detail_line
from services.social_delivery.gohighlevel_publisher import GoHighLevelPublisher
from services.social_delivery.models import PublishVideoResult, PublishVideoRequest

logger = logging.getLogger(__name__)


class GoHighLevelPropertyPublisher:
    def __init__(
        self,
        *,
        publisher: GoHighLevelPublisher,
    ) -> None:
        self.publisher = publisher

    def publish_property_reel(
        self,
        context: PropertyContext,
        published_video: PublishedVideoArtifact,
    ) -> PublishVideoResult | None:
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

        description = context.publish_description or ""
        return self.publisher.publish_video(
            PublishVideoRequest(
                video_path=published_video.video_path,
                description=description,
                target_url=context.publish_target_url,
                provider=context.publish_context.provider,
                location_id=context.publish_context.location_id,
                access_token=context.publish_context.access_token,
                platform=context.publish_context.platform,
                source_site_id=context.site_id,
            )
        )


__all__ = ["GoHighLevelPropertyPublisher"]

