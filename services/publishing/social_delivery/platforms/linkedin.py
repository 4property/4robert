from __future__ import annotations

from services.publishing.social_delivery.platforms.models import SocialPlatformConfig
from services.publishing.social_delivery.platforms.shared import (
    build_default_upload_file_name,
    build_empty_gohighlevel_payload,
    build_property_link_description,
)

PLATFORM_CONFIG = SocialPlatformConfig(
    platform="linkedin",
    aliases=("linked-in", "linked_in"),
    default_artifact_kind="reel_video",
    default_social_post_type="reel",
    allowed_artifact_kinds=("reel_video",),
    allowed_social_post_types=("reel",),
    max_caption_length=None,
    build_description=build_property_link_description,
    build_title=lambda _property_item: None,
    build_upload_file_name=build_default_upload_file_name,
    build_gohighlevel_payload=build_empty_gohighlevel_payload,
)


__all__ = ["PLATFORM_CONFIG"]
