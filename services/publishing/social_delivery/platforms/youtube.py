from __future__ import annotations

from settings import SOCIAL_PUBLISHING_YOUTUBE_POST_TYPE
from services.publishing.social_delivery.platforms.models import SocialPlatformConfig
from services.publishing.social_delivery.platforms.shared import (
    build_common_description,
    build_default_title,
    build_youtube_gohighlevel_payload,
    build_youtube_upload_file_name,
)

PLATFORM_CONFIG = SocialPlatformConfig(
    platform="youtube",
    aliases=("you-tube", "you_tube"),
    default_artifact_kind="reel_video",
    default_social_post_type=SOCIAL_PUBLISHING_YOUTUBE_POST_TYPE,
    allowed_artifact_kinds=("reel_video",),
    allowed_social_post_types=("post",),
    max_caption_length=None,
    build_description=build_common_description,
    build_title=build_default_title,
    build_upload_file_name=build_youtube_upload_file_name,
    build_gohighlevel_payload=build_youtube_gohighlevel_payload,
)


__all__ = ["PLATFORM_CONFIG"]
