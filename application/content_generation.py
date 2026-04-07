from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from models.property import Property
from services.social_delivery.description import (
    build_platform_descriptions_for_property_with_url,
    build_platform_titles_for_property,
)
from services.social_delivery.post_copy import build_property_caption


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
    ) -> GeneratedPropertyContent:
        ...


class DeterministicPropertyContentGenerator:
    def generate_property_content(
        self,
        *,
        property_item: Property,
        property_url: str,
        platforms: tuple[str, ...],
    ) -> GeneratedPropertyContent:
        captions_by_platform = build_platform_descriptions_for_property_with_url(
            property_item,
            property_url=property_url,
            platforms=platforms,
        )
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
