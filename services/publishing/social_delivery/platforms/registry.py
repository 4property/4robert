from __future__ import annotations

from services.publishing.social_delivery.platforms.facebook import PLATFORM_CONFIG as FACEBOOK_PLATFORM_CONFIG
from services.publishing.social_delivery.platforms.google_business_profile import (
    PLATFORM_CONFIG as GOOGLE_BUSINESS_PROFILE_PLATFORM_CONFIG,
)
from services.publishing.social_delivery.platforms.instagram import PLATFORM_CONFIG as INSTAGRAM_PLATFORM_CONFIG
from services.publishing.social_delivery.platforms.linkedin import PLATFORM_CONFIG as LINKEDIN_PLATFORM_CONFIG
from services.publishing.social_delivery.platforms.models import SocialPlatformConfig
from services.publishing.social_delivery.platforms.tiktok import PLATFORM_CONFIG as TIKTOK_PLATFORM_CONFIG
from services.publishing.social_delivery.platforms.youtube import PLATFORM_CONFIG as YOUTUBE_PLATFORM_CONFIG

_PLATFORM_CONFIG_SEQUENCE = (
    TIKTOK_PLATFORM_CONFIG,
    INSTAGRAM_PLATFORM_CONFIG,
    LINKEDIN_PLATFORM_CONFIG,
    YOUTUBE_PLATFORM_CONFIG,
    FACEBOOK_PLATFORM_CONFIG,
    GOOGLE_BUSINESS_PROFILE_PLATFORM_CONFIG,
)

PLATFORM_CONFIGS = {
    config.platform: config
    for config in _PLATFORM_CONFIG_SEQUENCE
}
_PLATFORM_ALIASES = {
    alias: config.platform
    for config in _PLATFORM_CONFIG_SEQUENCE
    for alias in config.aliases
}


def normalize_platform_name(platform: str) -> str:
    normalized_platform = str(platform or "").strip().lower()
    return _PLATFORM_ALIASES.get(normalized_platform, normalized_platform)


def get_platform_config(platform: str) -> SocialPlatformConfig | None:
    return PLATFORM_CONFIGS.get(normalize_platform_name(platform))


def list_supported_platforms() -> tuple[str, ...]:
    return tuple(PLATFORM_CONFIGS)


__all__ = [
    "PLATFORM_CONFIGS",
    "get_platform_config",
    "list_supported_platforms",
    "normalize_platform_name",
]
