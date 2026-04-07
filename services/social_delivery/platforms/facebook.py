from __future__ import annotations

from services.social_delivery.platforms.models import SocialPlatformConfig
from services.social_delivery.platforms.shared import (
    build_common_description,
    build_default_title,
    build_default_upload_file_name,
    build_empty_gohighlevel_payload,
)

PLATFORM_CONFIG = SocialPlatformConfig(
    platform="facebook",
    aliases=(),
    default_artifact_kind="reel_video",
    default_social_post_type="reel",
    allowed_artifact_kinds=("reel_video",),
    allowed_social_post_types=("reel",),
    max_caption_length=None,
    build_description=build_common_description,
    build_title=build_default_title,
    build_upload_file_name=build_default_upload_file_name,
    build_gohighlevel_payload=build_empty_gohighlevel_payload,
)


__all__ = ["PLATFORM_CONFIG"]
