from __future__ import annotations

from modules.publishing.infrastructure.adapters.platforms.models import SocialPlatformConfig
from modules.publishing.infrastructure.adapters.platforms.shared import (
    build_default_title,
    build_default_upload_file_name,
    build_pinterest_gohighlevel_payload,
    build_property_link_description,
)

PLATFORM_CONFIG = SocialPlatformConfig(
    platform="pinterest",
    aliases=("pin", "pins"),
    default_artifact_kind="reel_video",
    default_social_post_type="post",
    allowed_artifact_kinds=("reel_video", "poster_image"),
    allowed_social_post_types=("post",),
    max_caption_length=500,
    build_description=build_property_link_description,
    build_title=build_default_title,
    build_upload_file_name=build_default_upload_file_name,
    build_gohighlevel_payload=build_pinterest_gohighlevel_payload,
)


__all__ = ["PLATFORM_CONFIG"]
