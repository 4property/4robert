"""Content generator (deterministic) for property captions and titles.

Moved from ``application/pipeline/content_generation.py`` during sub-feature
18b. Sub-feature 18c migrated the deterministic-template helpers from
``services/publishing/social_delivery/`` to
``modules.publishing.infrastructure.social_copy``.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Protocol

from modules.catalog.domain.wordpress_property import Property
from modules.configuration.domain.social_templates_variables import (
    TEMPLATE_VARIABLE_PATTERN,
)
from modules.publishing.infrastructure.social_copy.description import (
    build_platform_descriptions_for_property_with_url,
    build_platform_titles_for_property,
)
from modules.publishing.infrastructure.social_copy.post_copy import build_property_caption


@dataclass(frozen=True, slots=True)
class GeneratedPropertyContent:
    default_caption: str
    captions_by_platform: dict[str, str]
    titles_by_platform: dict[str, str]
    overlay_text: dict[str, str] = field(default_factory=dict)
    narration_script: str = ""


class ContentGenerator(Protocol):
    def generate_property_content(
        self,
        *,
        property_item: Property,
        property_url: str,
        platforms: tuple[str, ...],
        templates_by_platform: dict[str, str] | None = None,
        title_templates_by_platform: dict[str, str] | None = None,
        hashtags_by_platform: dict[str, tuple[str, ...]] | None = None,
    ) -> GeneratedPropertyContent:
        ...


_TEMPLATE_VARIABLE_PATTERN = TEMPLATE_VARIABLE_PATTERN


def _build_property_template_variables(
    property_item: Property,
    *,
    property_url: str,
) -> dict[str, str]:
    """Mapping consumed by the agency's per-network description templates.

    Keys mirror `ALLOWED_TEMPLATE_VARIABLES` exactly; the PUT validator
    rejects any other placeholder, so an unknown variable never reaches the
    substitution path at runtime.
    """
    return {
        "property_title": property_item.title or "",
        "price": property_item.price or "",
        "bedrooms": str(property_item.bedrooms or "")
        if getattr(property_item, "bedrooms", None) is not None
        else "",
        "bathrooms": str(property_item.bathrooms or "")
        if getattr(property_item, "bathrooms", None) is not None
        else "",
        "size_m2": getattr(property_item, "property_size", "") or "",
        "property_type": getattr(property_item, "property_type_label", "") or "",
        "city": getattr(property_item, "property_county_label", "") or "",
        "neighborhood": getattr(property_item, "property_area_label", "") or "",
        "neighborhood_tag": (
            (getattr(property_item, "property_area_label", "") or "").lower().replace(" ", "")
        ),
        "eircode": getattr(property_item, "eircode", "") or "",
        "short_description": (getattr(property_item, "excerpt_html", "") or "").strip(),
        "agent_name": getattr(property_item, "agent_name", "") or "",
        "agent_phone": (
            getattr(property_item, "agent_mobile", "")
            or getattr(property_item, "agent_number", "")
            or ""
        ),
        "agent_email": getattr(property_item, "agent_email", "") or "",
        "booking_link": property_url,
        "property_url": property_url,
    }


def render_template_with_property(
    template: str,
    property_item: Property,
    *,
    property_url: str,
) -> str:
    """Substitute `{{variable}}` placeholders inside the agency's template.

    WordPress emits HTML entities in ``title.rendered`` and ``content.rendered``
    (e.g. ``&#8217;``, ``&amp;``, ``&quot;``, ``&#x2019;``). We decode the
    substituted output here so the rendered caption that flows into the MP4
    overlay and the GHL POST body never carries raw entities. ``html.unescape``
    is idempotent on already-decoded text, so re-running the pipeline is safe.
    """
    if not template:
        return ""
    variables = _build_property_template_variables(property_item, property_url=property_url)

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1).strip().lower()
        return str(variables.get(key, match.group(0)))

    rendered = _TEMPLATE_VARIABLE_PATTERN.sub(_replace, template).strip()
    return html.unescape(rendered)


def _normalise_hashtag_list(hashtags: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    """Drop empty/whitespace entries; preserve order; trim each tag."""
    if not hashtags:
        return ()
    normalised: list[str] = []
    for raw in hashtags:
        candidate = str(raw or "").strip()
        if candidate:
            normalised.append(candidate)
    return tuple(normalised)


def append_hashtags(description: str, hashtags: tuple[str, ...]) -> str:
    """Append `hashtags` (space-joined) to `description` with a blank-line gap.

    Returns ``description`` unchanged when ``hashtags`` is empty so the
    fallback deterministic caption never gains a stray blank tail. If the
    description is empty but hashtags exist, the joined hashtags become the
    full caption (the network would otherwise receive a blank string).
    """
    cleaned = _normalise_hashtag_list(hashtags)
    if not cleaned:
        return description
    joined = " ".join(cleaned)
    if not description:
        return joined
    return f"{description}\n\n{joined}"


class DeterministicPropertyContentGenerator:
    def generate_property_content(
        self,
        *,
        property_item: Property,
        property_url: str,
        platforms: tuple[str, ...],
        templates_by_platform: dict[str, str] | None = None,
        title_templates_by_platform: dict[str, str] | None = None,
        hashtags_by_platform: dict[str, tuple[str, ...]] | None = None,
    ) -> GeneratedPropertyContent:
        deterministic_captions = build_platform_descriptions_for_property_with_url(
            property_item,
            property_url=property_url,
            platforms=platforms,
        )
        captions_by_platform: dict[str, str] = dict(deterministic_captions)
        normalized_templates = {
            str(key).strip().lower(): str(value)
            for key, value in (templates_by_platform or {}).items()
            if str(key).strip() and str(value).strip()
        }
        normalized_title_templates = {
            str(key).strip().lower(): str(value)
            for key, value in (title_templates_by_platform or {}).items()
            if str(key).strip() and str(value).strip()
        }
        normalized_hashtags = {
            str(key).strip().lower(): _normalise_hashtag_list(value)
            for key, value in (hashtags_by_platform or {}).items()
            if str(key).strip()
        }
        for platform in platforms:
            platform_key = str(platform).lower()
            template = normalized_templates.get(platform_key)
            if template:
                rendered = render_template_with_property(
                    template,
                    property_item,
                    property_url=property_url,
                )
                if rendered:
                    captions_by_platform[platform] = rendered
            # Append hashtags to whatever caption ended up being assigned
            # (either the agency template rendered above or the deterministic
            # fallback seeded at the top of the function).
            tags = normalized_hashtags.get(platform_key, ())
            if tags:
                captions_by_platform[platform] = append_hashtags(
                    captions_by_platform.get(platform, ""),
                    tags,
                )
        titles_by_platform: dict[str, str] = dict(
            build_platform_titles_for_property(
                property_item,
                platforms=platforms,
            )
        )
        # Render agency-defined title templates on top of the deterministic
        # baseline so networks with a dedicated title slot (Pinterest,
        # YouTube) honour the admin's copy. An empty rendered title falls
        # back to the deterministic value.
        for platform in platforms:
            platform_key = str(platform).lower()
            title_template = normalized_title_templates.get(platform_key)
            if not title_template:
                continue
            rendered_title = render_template_with_property(
                title_template,
                property_item,
                property_url=property_url,
            )
            if rendered_title:
                titles_by_platform[platform] = rendered_title
        return GeneratedPropertyContent(
            default_caption=build_property_caption(
                property_url=property_url,
                agent_name=property_item.agent_name,
                agent_phone=property_item.agent_mobile or property_item.agent_number,
                agent_email=property_item.agent_email,
                agency_psra=property_item.agency_psra,
            ),
            captions_by_platform=captions_by_platform,
            titles_by_platform=titles_by_platform,
            overlay_text={},
            narration_script="",
        )


__all__ = [
    "ContentGenerator",
    "DeterministicPropertyContentGenerator",
    "GeneratedPropertyContent",
    "append_hashtags",
]
