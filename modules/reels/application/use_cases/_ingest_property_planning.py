"""Planning helpers for :class:`IngestPropertyIntoReelUseCase`.

This module hosts the pure-data helpers that translate the inbound
WordPress payload + delivery plan into:

- the resolved publish inputs (provider, target URL, per-platform
  descriptions / titles / publish targets);
- the canonical content snapshot + its fingerprint;
- the canonical publish-target snapshot + its fingerprint.

Helpers that compare *previous* state with *new* inputs (snapshot
coercion, pending-platform diff, publish-history reset) live in
:mod:`_ingest_property_assets`. All public symbols here are private
(`_`-prefixed) and consumed only from ``ingest_property_into_reel.py``.
"""

from __future__ import annotations

import hashlib
import json
import logging

from modules.catalog.domain.wordpress_property import Property
from modules.publishing.infrastructure.adapters.gohighlevel.platform_policy import (
    normalize_platform_name,
)
from modules.publishing.infrastructure.adapters.platforms import get_platform_config
from modules.publishing.infrastructure.social_copy.description import (
    build_property_public_url,
)
from modules.reels.application.content_generator import ContentGenerator
from modules.reels.domain.types import (
    PlatformPublishTargetPlan,
    PropertyMediaJob,
    SocialPublishContext,
)
from shared.observability import format_console_block, format_detail_line

logger = logging.getLogger(__name__)


def _json_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _json_text(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


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


def _build_publish_targets(
    *,
    property_item: Property,
    desired_platforms: tuple[str, ...],
    publish_descriptions_by_platform: dict[str, str],
    publish_titles_by_platform: dict[str, str],
    publish_target_url: str | None,
    delivery_plan,
) -> tuple[PlatformPublishTargetPlan, ...]:
    publish_targets: list[PlatformPublishTargetPlan] = []
    for platform in desired_platforms:
        normalized_platform = normalize_platform_name(platform)
        if not normalized_platform:
            continue
        platform_config = get_platform_config(normalized_platform)
        if platform_config is None:
            continue
        publish_targets.append(
            PlatformPublishTargetPlan(
                platform=normalized_platform,
                artifact_kind=platform_config.resolve_artifact_kind(
                    delivery_plan.artifact_kind,
                ),
                social_post_type=platform_config.resolve_social_post_type(
                    delivery_plan.social_post_type,
                ),
                description=str(
                    publish_descriptions_by_platform.get(normalized_platform)
                    or platform_config.build_description(
                        property_item,
                        str(publish_target_url or property_item.link or ""),
                    )
                ),
                title=(
                    str(publish_titles_by_platform.get(normalized_platform) or "").strip() or None
                )
                or platform_config.build_title(property_item),
                target_url=publish_target_url or None,
            )
        )
    return tuple(publish_targets)


def _resolve_publish_inputs(
    *,
    job: PropertyMediaJob,
    property_item: Property,
    delivery_plan,
    social_publishing_enabled: bool,
    property_url_template: str,
    property_url_tracking_params: dict[str, str],
    content_generator: ContentGenerator,
) -> tuple[
    SocialPublishContext | None,
    tuple[str, ...],
    str | None,
    dict[str, str],
    dict[str, str],
    tuple[PlatformPublishTargetPlan, ...],
]:
    publish_context: SocialPublishContext | None = None
    desired_platforms: tuple[str, ...] = ()
    publish_target_url: str | None = None
    publish_descriptions_by_platform: dict[str, str] = {}
    publish_titles_by_platform: dict[str, str] = {}
    publish_targets: tuple[PlatformPublishTargetPlan, ...] = ()

    if social_publishing_enabled:
        publish_context = job.publish_context

    if publish_context is not None:
        desired_platforms = publish_context.platforms
        publish_target_url = build_property_public_url(
            site_id=job.site_id,
            slug=property_item.slug,
            property_link=property_item.link,
            property_url_template=property_url_template,
            tracking_query_params=property_url_tracking_params,
        )

    if publish_context is not None and publish_target_url is not None:
        logger.info(
            format_console_block(
                "Property Content Generation Started",
                format_detail_line("Site ID", job.site_id),
                format_detail_line("Property ID", property_item.id),
                format_detail_line("Platforms", ", ".join(desired_platforms)),
                format_detail_line("Target URL", publish_target_url),
            )
        )
        generated_content = content_generator.generate_property_content(
            property_item=property_item,
            property_url=publish_target_url,
            platforms=desired_platforms,
            templates_by_platform=getattr(
                publish_context, "social_templates_map", {}
            ),
            title_templates_by_platform=getattr(
                publish_context, "social_title_templates_map", {}
            ),
            hashtags_by_platform=getattr(
                publish_context, "social_hashtags_map", {}
            ),
        )
        publish_descriptions_by_platform = dict(generated_content.captions_by_platform)
        publish_titles_by_platform = dict(generated_content.titles_by_platform)
        publish_targets = _build_publish_targets(
            property_item=property_item,
            desired_platforms=desired_platforms,
            publish_descriptions_by_platform=publish_descriptions_by_platform,
            publish_titles_by_platform=publish_titles_by_platform,
            publish_target_url=publish_target_url,
            delivery_plan=delivery_plan,
        )
        logger.info(
            format_console_block(
                "Property Content Generation Completed",
                format_detail_line("Site ID", job.site_id),
                format_detail_line("Property ID", property_item.id),
                format_detail_line("Generated captions", len(publish_descriptions_by_platform)),
                format_detail_line("Generated titles", len(publish_titles_by_platform)),
                format_detail_line("Publish targets", len(publish_targets)),
            )
        )

    return (
        publish_context,
        desired_platforms,
        publish_target_url,
        publish_descriptions_by_platform,
        publish_titles_by_platform,
        publish_targets,
    )


def _build_content_snapshot(
    *,
    property_item: Property,
    delivery_plan,
    render_template_snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    snapshot = property_item.to_dict()
    snapshot.pop("raw_data", None)
    snapshot["delivery_plan"] = {
        "listing_lifecycle": delivery_plan.listing_lifecycle,
        "artifact_kind": delivery_plan.artifact_kind,
        "render_profile": delivery_plan.render_profile,
        "social_post_type": delivery_plan.social_post_type,
        "asset_strategy": delivery_plan.asset_strategy,
        "banner_text": delivery_plan.banner_text,
        "price_display_text": delivery_plan.price_display_text,
    }
    if render_template_snapshot is not None:
        snapshot["render_template"] = dict(render_template_snapshot)
    return snapshot


def _build_publish_target_snapshot(
    *,
    publish_context,
    descriptions_by_platform: dict[str, str],
    titles_by_platform: dict[str, str],
    publish_targets: tuple[PlatformPublishTargetPlan, ...],
    target_url: str | None,
    delivery_plan,
) -> dict[str, object]:
    if publish_context is None:
        return {}
    return {
        "provider": publish_context.provider,
        "location_id": publish_context.location_id,
        "platforms": list(publish_context.platforms),
        "descriptions_by_platform": dict(descriptions_by_platform),
        "titles_by_platform": dict(titles_by_platform),
        "targets_by_platform": {
            target.platform: {
                "artifact_kind": target.artifact_kind,
                "social_post_type": target.social_post_type,
                "description": target.description,
                "title": target.title or "",
                "target_url": target.target_url or "",
            }
            for target in publish_targets
        },
        "target_url": target_url or "",
        "artifact_kind": delivery_plan.artifact_kind,
        "render_profile": delivery_plan.render_profile,
        "listing_lifecycle": delivery_plan.listing_lifecycle,
        "social_post_type": delivery_plan.social_post_type,
    }


__all__ = [
    "_build_content_snapshot",
    "_build_publish_target_snapshot",
    "_build_publish_targets",
    "_json_hash",
    "_json_text",
    "_resolve_publish_inputs",
]
