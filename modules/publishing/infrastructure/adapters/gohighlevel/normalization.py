from __future__ import annotations

from modules.publishing.infrastructure.adapters.gohighlevel.models import (
    MultiPlatformPublishResult,
    PlatformPublishTarget,
)
from modules.publishing.infrastructure.adapters.gohighlevel.platform_policy import (
    normalize_platform_name,
)
from modules.publishing.infrastructure.adapters.gohighlevel.user_selection import (
    LocationUserFallbackSelector,
)
from modules.publishing.infrastructure.adapters.platforms import list_supported_platforms

SUPPORTED_GOHIGHLEVEL_PLATFORMS = frozenset(list_supported_platforms())


def selector_name(selector: LocationUserFallbackSelector) -> str:
    return getattr(selector, "__name__", selector.__class__.__name__)


def normalise_platform_name(platform: str) -> str:
    return normalize_platform_name(platform)


def normalise_requested_platforms(platforms: tuple[str, ...]) -> tuple[str, ...]:
    normalized_platforms: list[str] = []
    seen: set[str] = set()
    for platform in platforms:
        normalized_platform = normalise_platform_name(platform)
        if not normalized_platform or normalized_platform in seen:
            continue
        seen.add(normalized_platform)
        normalized_platforms.append(normalized_platform)
    return tuple(normalized_platforms)


def normalise_publish_targets(
    targets: tuple[PlatformPublishTarget, ...],
) -> tuple[PlatformPublishTarget, ...]:
    normalized_targets: list[PlatformPublishTarget] = []
    seen_platforms: set[str] = set()
    for target in targets:
        normalized_platform = normalise_platform_name(target.platform)
        if not normalized_platform or normalized_platform in seen_platforms:
            continue
        seen_platforms.add(normalized_platform)
        normalized_targets.append(
            PlatformPublishTarget(
                platform=normalized_platform,
                media_path=target.media_path,
                description=target.description,
                title=target.title,
                upload_file_name=target.upload_file_name,
                target_url=target.target_url,
                social_post_type=target.social_post_type,
                artifact_kind=target.artifact_kind,
            )
        )
    return tuple(normalized_targets)


def extract_trace_id(raw_response: dict[str, object]) -> str | None:
    trace_id = raw_response.get("traceId")
    if isinstance(trace_id, str) and trace_id.strip():
        return trace_id.strip()
    return None


def build_failed_batch_message(result: MultiPlatformPublishResult) -> str:
    summarized_outcomes = ", ".join(
        f"{outcome.platform}={outcome.outcome}"
        + (f" ({outcome.error})" if outcome.error else "")
        for outcome in result.platform_results
    )
    return (
        "GoHighLevel multi-platform publish did not succeed on any platform. "
        f"Outcomes: {summarized_outcomes or '<none>'}"
    )


__all__ = [
    "SUPPORTED_GOHIGHLEVEL_PLATFORMS",
    "build_failed_batch_message",
    "extract_trace_id",
    "normalise_platform_name",
    "normalise_publish_targets",
    "normalise_requested_platforms",
    "selector_name",
]
