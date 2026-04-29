from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from domain.properties.model import Property
from services.publishing.social_delivery.description import (
    build_platform_descriptions_for_property_with_url,
    build_platform_titles_for_property,
)
from services.publishing.social_delivery.post_copy import build_property_caption


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
    ) -> GeneratedPropertyContent:
        ...


_TEMPLATE_VARIABLE_PATTERN = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def _build_property_template_variables(
    property_item: Property,
    *,
    property_url: str,
) -> dict[str, str]:
    """Mapping consumed by the agency's per-network description templates.

    Keys mirror the catalog the frontend Social tab lists in its
    `{{variable}}` palette.
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
    """Substitute `{{variable}}` placeholders inside the agency's template."""
    if not template:
        return ""
    variables = _build_property_template_variables(property_item, property_url=property_url)

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1).strip().lower()
        return str(variables.get(key, match.group(0)))

    return _TEMPLATE_VARIABLE_PATTERN.sub(_replace, template).strip()


class DeterministicPropertyContentGenerator:
    def generate_property_content(
        self,
        *,
        property_item: Property,
        property_url: str,
        platforms: tuple[str, ...],
        templates_by_platform: dict[str, str] | None = None,
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
        for platform in platforms:
            template = normalized_templates.get(str(platform).lower())
            if template:
                rendered = render_template_with_property(
                    template,
                    property_item,
                    property_url=property_url,
                )
                if rendered:
                    captions_by_platform[platform] = rendered
        titles_by_platform = build_platform_titles_for_property(
            property_item,
            platforms=platforms,
        )
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
]
