from __future__ import annotations

from dataclasses import dataclass

from services.publishing.social_delivery.platforms import get_platform_config, normalize_platform_name


@dataclass(frozen=True, slots=True)
class PlatformPolicy:
    platform: str
    max_caption_length: int | None
    allowed_social_post_types: tuple[str, ...]
    allowed_artifact_kinds: tuple[str, ...]


def get_platform_policy(platform: str) -> PlatformPolicy | None:
    config = get_platform_config(platform)
    if config is None:
        return None
    return PlatformPolicy(
        platform=config.platform,
        max_caption_length=config.max_caption_length,
        allowed_social_post_types=config.allowed_social_post_types,
        allowed_artifact_kinds=config.allowed_artifact_kinds,
    )


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

    normalized_platform = normalize_platform_name(platform)
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
    if normalized_platform == "youtube" and not str(title or "").strip():
        warnings.append("YouTube posts should include a title.")
    return tuple(warnings)


def resolve_platform_social_post_type(*, platform: str, requested_social_post_type: str) -> str:
    config = get_platform_config(platform)
    normalized_type = str(requested_social_post_type or "").strip().lower()
    if config is None:
        return normalized_type or requested_social_post_type
    return config.resolve_social_post_type(requested_social_post_type)


def resolve_platform_artifact_kind(*, platform: str, requested_artifact_kind: str) -> str:
    config = get_platform_config(platform)
    normalized_kind = str(requested_artifact_kind or "").strip().lower()
    if config is None:
        return normalized_kind or requested_artifact_kind
    return config.resolve_artifact_kind(requested_artifact_kind)


__all__ = [
    "PlatformPolicy",
    "get_platform_policy",
    "normalize_platform_name",
    "resolve_platform_artifact_kind",
    "resolve_platform_social_post_type",
    "validate_platform_publish_request",
]
