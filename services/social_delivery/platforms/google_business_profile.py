from __future__ import annotations

from services.social_delivery.platforms.models import SocialPlatformConfig
from services.social_delivery.platforms.shared import (
    build_default_title,
    build_default_upload_file_name,
    build_empty_gohighlevel_payload,
    build_google_business_profile_description,
)

PLATFORM_CONFIG = SocialPlatformConfig(
    platform="google_business_profile",
    aliases=("gmb", "gbp"),
    default_artifact_kind="poster_image",
    default_social_post_type="post",
    allowed_artifact_kinds=("poster_image",),
    allowed_social_post_types=("post",),
    max_caption_length=None,
    build_description=build_google_business_profile_description,
    build_title=build_default_title,
    build_upload_file_name=build_default_upload_file_name,
    build_gohighlevel_payload=build_empty_gohighlevel_payload,
)


__all__ = ["PLATFORM_CONFIG"]
