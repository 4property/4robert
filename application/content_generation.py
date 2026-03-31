from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from models.property import Property
from services.social_delivery.post_copy import build_property_copy_bundle


@dataclass(frozen=True, slots=True)
class GeneratedPropertyContent:
    default_caption: str
    captions_by_platform: dict[str, str]
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
        copy_bundle = build_property_copy_bundle(
            property_item=property_item,
            property_url=property_url,
            platforms=platforms,
        )
        return GeneratedPropertyContent(
            default_caption=copy_bundle.default_caption,
            captions_by_platform=dict(copy_bundle.captions_by_platform),
            overlay_text={},
            narration_script="",
        )


__all__ = [
    "ContentGenerator",
    "DeterministicPropertyContentGenerator",
    "GeneratedPropertyContent",
]
