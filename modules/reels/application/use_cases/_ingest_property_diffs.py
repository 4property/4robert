"""Previous-state diff helpers for :class:`IngestPropertyIntoReelUseCase`.

This module hosts the helpers that compare the previously-stored
publish-target snapshot + publish-details against the freshly-resolved
inputs to decide:

- which platforms still need to publish (``_determine_pending_publish_platforms``);
- whether the persisted publish history must be reset
  (``_should_reset_publish_history``);

Plus the snapshot coercion + per-platform success extractors used by
those decisions and by the orchestrator. All public symbols are private
(``_``-prefixed) and consumed only from ``ingest_property_into_reel.py``.
"""

from __future__ import annotations

from typing import Any

from modules.publishing.infrastructure.adapters.gohighlevel.platform_policy import (
    normalize_platform_name,
)
from modules.reels.domain import ReelState
from modules.reels.domain.types import PlatformPublishTargetPlan


_SUCCESSFUL_SOCIAL_STATUSES = {
    "published",
    "scheduled",
    "queued",
    "processing",
    "created",
    "accepted",
}


def _normalise_platforms(value: object) -> tuple[str, ...]:
    raw_values: tuple[object, ...]
    if isinstance(value, (list, tuple)):
        raw_values = tuple(value)
    elif value is None:
        raw_values = ()
    else:
        raw_values = (value,)

    normalized_values: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        normalized_value = normalize_platform_name(str(raw_value or "").strip().lower())
        if not normalized_value or normalized_value in seen:
            continue
        seen.add(normalized_value)
        normalized_values.append(normalized_value)
    return tuple(normalized_values)


def _coerce_publish_target_snapshot(
    snapshot: dict[str, Any] | None,
) -> dict[str, object]:
    if not snapshot:
        return {
            "provider": "",
            "location_id": "",
            "platforms": (),
            "descriptions_by_platform": {},
            "titles_by_platform": {},
            "targets_by_platform": {},
            "target_url": "",
            "artifact_kind": "",
            "render_profile": "",
            "listing_lifecycle": "",
            "social_post_type": "",
        }

    raw_descriptions = snapshot.get("descriptions_by_platform")
    descriptions_by_platform: dict[str, str] = {}
    if isinstance(raw_descriptions, dict):
        for raw_platform, raw_description in raw_descriptions.items():
            platform = normalize_platform_name(str(raw_platform or "").strip().lower())
            if not platform:
                continue
            descriptions_by_platform[platform] = str(raw_description or "")

    raw_titles = snapshot.get("titles_by_platform")
    titles_by_platform: dict[str, str] = {}
    if isinstance(raw_titles, dict):
        for raw_platform, raw_title in raw_titles.items():
            platform = normalize_platform_name(str(raw_platform or "").strip().lower())
            title = str(raw_title or "").strip()
            if not platform or not title:
                continue
            titles_by_platform[platform] = title

    raw_targets = snapshot.get("targets_by_platform")
    targets_by_platform: dict[str, dict[str, str]] = {}
    if isinstance(raw_targets, dict):
        for raw_platform, raw_target in raw_targets.items():
            if not isinstance(raw_target, dict):
                continue
            platform = normalize_platform_name(str(raw_platform or "").strip().lower())
            if not platform:
                continue
            targets_by_platform[platform] = {
                "artifact_kind": str(raw_target.get("artifact_kind") or "").strip(),
                "social_post_type": str(raw_target.get("social_post_type") or "").strip(),
                "description": str(raw_target.get("description") or ""),
                "title": str(raw_target.get("title") or "").strip(),
                "target_url": str(raw_target.get("target_url") or "").strip(),
            }

    platforms = _normalise_platforms(snapshot.get("platforms"))

    return {
        "provider": str(snapshot.get("provider") or "").strip().lower(),
        "location_id": str(snapshot.get("location_id") or "").strip(),
        "platforms": platforms,
        "descriptions_by_platform": descriptions_by_platform,
        "titles_by_platform": titles_by_platform,
        "targets_by_platform": targets_by_platform,
        "target_url": str(snapshot.get("target_url") or "").strip(),
        "artifact_kind": str(snapshot.get("artifact_kind") or "").strip(),
        "render_profile": str(snapshot.get("render_profile") or "").strip(),
        "listing_lifecycle": str(snapshot.get("listing_lifecycle") or "").strip(),
        "social_post_type": str(snapshot.get("social_post_type") or "").strip(),
    }


def _extract_platform_results(details: dict[str, object]) -> dict[str, dict[str, object]]:
    raw_results = details.get("platform_results")
    platform_results: dict[str, dict[str, object]] = {}
    if isinstance(raw_results, dict):
        for raw_platform, raw_result in raw_results.items():
            if not isinstance(raw_result, dict):
                continue
            platform = str(raw_result.get("platform") or raw_platform or "").strip().lower()
            if not platform:
                continue
            platform_results[platform] = dict(raw_result)
        if platform_results:
            return platform_results

    return platform_results


def _is_successful_platform_result(result: dict[str, object]) -> bool:
    outcome = str(result.get("outcome") or "").strip().lower()
    post_id = str(result.get("post_id") or "").strip()
    post_status = str(result.get("post_status") or "").strip().lower()
    if post_id:
        return True
    return outcome in _SUCCESSFUL_SOCIAL_STATUSES or post_status in _SUCCESSFUL_SOCIAL_STATUSES


def _extract_successful_platforms(
    details: dict[str, Any],
    *,
    fallback_platforms: tuple[str, ...] = (),
) -> tuple[str, ...]:
    successful_platforms: list[str] = []
    platform_results = _extract_platform_results(details)
    for platform, result in platform_results.items():
        if _is_successful_platform_result(result):
            successful_platforms.append(platform)
    if successful_platforms:
        return tuple(successful_platforms)
    if fallback_platforms and _is_successful_platform_result(details):
        return tuple(platform for platform in fallback_platforms if platform.strip())
    return tuple(successful_platforms)


def _determine_pending_publish_platforms(
    *,
    state: ReelState,
    publish_context,
    desired_platforms: tuple[str, ...],
    publish_descriptions_by_platform: dict[str, str],
    publish_titles_by_platform: dict[str, str],
    publish_targets: tuple[PlatformPublishTargetPlan, ...],
    publish_target_url: str | None,
    delivery_plan,
    requires_render: bool,
) -> tuple[str, ...]:
    if publish_context is None:
        return ()
    if requires_render:
        return desired_platforms

    previous_target_snapshot = _coerce_publish_target_snapshot(
        dict(state.publish_target_snapshot or {})
    )
    successful_platforms = set(
        _extract_successful_platforms(
            dict(state.publish_details or {}),
            fallback_platforms=desired_platforms,
        )
    )
    previous_descriptions = previous_target_snapshot["descriptions_by_platform"]
    if not isinstance(previous_descriptions, dict):
        previous_descriptions = {}
    previous_titles = previous_target_snapshot["titles_by_platform"]
    if not isinstance(previous_titles, dict):
        previous_titles = {}
    previous_targets = previous_target_snapshot["targets_by_platform"]
    if not isinstance(previous_targets, dict):
        previous_targets = {}
    current_targets = {target.platform: target for target in publish_targets}

    pending_publish_platforms: list[str] = []
    for platform in desired_platforms:
        current_target = current_targets.get(platform)
        if current_target is None:
            pending_publish_platforms.append(platform)
            continue
        if platform not in successful_platforms:
            pending_publish_platforms.append(platform)
            continue
        if str(previous_target_snapshot.get("provider") or "") != publish_context.provider:
            pending_publish_platforms.append(platform)
            continue
        if str(previous_target_snapshot.get("location_id") or "") != publish_context.location_id:
            pending_publish_platforms.append(platform)
            continue
        previous_target_entry = previous_targets.get(platform)
        previous_target_url = str(
            (previous_target_entry or {}).get("target_url")
            or previous_target_snapshot.get("target_url")
            or ""
        )
        if previous_target_url != (current_target.target_url or publish_target_url or ""):
            pending_publish_platforms.append(platform)
            continue
        previous_artifact_kind = str(
            (previous_target_entry or {}).get("artifact_kind")
            or previous_target_snapshot.get("artifact_kind")
            or ""
        )
        if previous_artifact_kind != current_target.artifact_kind:
            pending_publish_platforms.append(platform)
            continue
        if str(previous_target_snapshot.get("render_profile") or "") != delivery_plan.render_profile:
            pending_publish_platforms.append(platform)
            continue
        previous_social_post_type = str(
            (previous_target_entry or {}).get("social_post_type")
            or previous_target_snapshot.get("social_post_type")
            or ""
        )
        if previous_social_post_type != current_target.social_post_type:
            pending_publish_platforms.append(platform)
            continue
        if str(previous_target_snapshot.get("listing_lifecycle") or "") != delivery_plan.listing_lifecycle:
            pending_publish_platforms.append(platform)
            continue
        previous_description = str(
            (previous_target_entry or {}).get("description")
            or previous_descriptions.get(platform)
            or ""
        )
        current_description = current_target.description or str(
            publish_descriptions_by_platform.get(platform) or ""
        )
        if previous_description != current_description:
            pending_publish_platforms.append(platform)
            continue
        previous_title = str(
            (previous_target_entry or {}).get("title")
            or previous_titles.get(platform)
            or ""
        )
        current_title = str(current_target.title or publish_titles_by_platform.get(platform) or "")
        if previous_title != current_title:
            pending_publish_platforms.append(platform)

    return tuple(pending_publish_platforms)


def _should_reset_publish_history(
    *,
    previous_target_snapshot: dict[str, object],
    publish_context,
    requires_render: bool,
) -> bool:
    if publish_context is None:
        return False
    if requires_render:
        return True
    previous_provider = str(previous_target_snapshot.get("provider") or "")
    previous_location_id = str(previous_target_snapshot.get("location_id") or "")
    return (
        previous_provider != publish_context.provider
        or previous_location_id != publish_context.location_id
    )


__all__ = [
    "_coerce_publish_target_snapshot",
    "_determine_pending_publish_platforms",
    "_extract_successful_platforms",
    "_should_reset_publish_history",
]
