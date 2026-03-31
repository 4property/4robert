from __future__ import annotations

from dataclasses import dataclass

from config import SOCIAL_PUBLISHING_YOUTUBE_POST_TYPE
from services.social_delivery.description import TIKTOK_MAX_DESCRIPTION_LENGTH


@dataclass(frozen=True, slots=True)
class PlatformPolicy:
    platform: str
    max_caption_length: int | None
    allowed_social_post_types: tuple[str, ...]
    allowed_artifact_kinds: tuple[str, ...]


_PLATFORM_POLICIES: dict[str, PlatformPolicy] = {
    "tiktok": PlatformPolicy(
        platform="tiktok",
        max_caption_length=TIKTOK_MAX_DESCRIPTION_LENGTH,
        allowed_social_post_types=("reel",),
        allowed_artifact_kinds=("reel_video",),
    ),
    "instagram": PlatformPolicy(
        platform="instagram",
        max_caption_length=None,
        allowed_social_post_types=("reel",),
        allowed_artifact_kinds=("reel_video",),
    ),
    "linkedin": PlatformPolicy(
        platform="linkedin",
        max_caption_length=None,
        allowed_social_post_types=("reel",),
        allowed_artifact_kinds=("reel_video",),
    ),
    "youtube": PlatformPolicy(
        platform="youtube",
        max_caption_length=None,
        allowed_social_post_types=("post",),
        allowed_artifact_kinds=("reel_video",),
    ),
}


def get_platform_policy(platform: str) -> PlatformPolicy | None:
    return _PLATFORM_POLICIES.get(platform.strip().lower())


def validate_platform_publish_request(
    *,
    platform: str,
    description: str,
    social_post_type: str,
    artifact_kind: str,
    title: str | None = None,
) -> tuple[str, ...]:
    policy = get_platform_policy(platform)
    if policy is None:
        return (f"No platform policy is registered for {platform}.",)

    warnings: list[str] = []
    if (
        policy.max_caption_length is not None
        and len(description) > policy.max_caption_length
    ):
        warnings.append(
            f"Caption exceeds the configured {platform} limit of {policy.max_caption_length} characters."
        )
    if social_post_type not in policy.allowed_social_post_types:
        warnings.append(
            f"Social post type {social_post_type!r} is not allowed by the {platform} policy."
        )
    if artifact_kind not in policy.allowed_artifact_kinds:
        warnings.append(
            f"Artifact kind {artifact_kind!r} is not allowed by the {platform} policy."
        )
    if platform.strip().lower() == "youtube" and not str(title or "").strip():
        warnings.append("YouTube posts should include a title.")
    return tuple(warnings)


def resolve_platform_social_post_type(*, platform: str, requested_social_post_type: str) -> str:
    normalized_platform = platform.strip().lower()
    normalized_type = requested_social_post_type.strip().lower()
    if normalized_platform == "youtube":
        return SOCIAL_PUBLISHING_YOUTUBE_POST_TYPE
    return normalized_type or requested_social_post_type


__all__ = [
    "PlatformPolicy",
    "get_platform_policy",
    "resolve_platform_social_post_type",
    "validate_platform_publish_request",
]
