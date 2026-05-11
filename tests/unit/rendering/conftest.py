"""Shared fixtures for the `tests/unit/rendering/test_layout_*.py` suite.

Helpers build minimally realistic `PropertyReelData`/`PropertyReelTemplate`/
`PropertyReelSlide` instances so each layout submodule can be exercised in
isolation without depending on `tests/test_reel_pipeline.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.rendering.infrastructure.models import (
    PropertyReelSlide,
    PropertyReelTemplate,
    PropertyRenderData,
)


def build_property_data(
    *,
    title: str = "110 Example Road, Dublin 14",
    price: str | None = "500000",
    property_status: str | None = "For Sale",
    agent_name: str | None = "Jane Doe",
    agent_email: str | None = "jane@example.com",
    agent_number: str | None = "+353 1 234 5678",
    bedrooms: int | None = 3,
    bathrooms: int | None = 2,
    ber_rating: str | None = None,
    banner_text: str | None = None,
    price_display_text: str | None = None,
    viewing_times: tuple[str, ...] = (),
    agency_psra: str | None = None,
) -> PropertyRenderData:
    return PropertyRenderData(
        site_id="ckp.ie",
        property_id=173637,
        slug="sample-property",
        title=title,
        link="https://ckp.ie/property/sample-property",
        property_status=property_status,
        selected_image_dir=Path("selected_photos"),
        selected_image_paths=(Path("selected_photos/primary_image.png"),),
        featured_image_url=None,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        ber_rating=ber_rating,
        agent_name=agent_name,
        agent_photo_url=None,
        agent_email=agent_email,
        agent_mobile=None,
        agent_number=agent_number,
        price=price,
        property_type_label="Apartment",
        property_area_label="Dublin 14",
        property_county_label="Dublin",
        eircode="D14 TEST",
        banner_text=banner_text,
        price_display_text=price_display_text,
        agency_psra=agency_psra,
        viewing_times=viewing_times,
    )


def build_template(
    *,
    width: int = 320,
    height: int = 480,
    subtitle_font_size: int = 28,
    include_intro: bool = False,
    intro_duration_seconds: float = 1.5,
    footer_bottom_offset_px: int = 0,
) -> PropertyReelTemplate:
    return PropertyReelTemplate(
        width=width,
        height=height,
        subtitle_font_size=subtitle_font_size,
        include_intro=include_intro,
        intro_duration_seconds=intro_duration_seconds,
        footer_bottom_offset_px=footer_bottom_offset_px,
    )


def build_slide(
    *,
    image_path: Path = Path("selected_photos/primary_image.png"),
    caption: str | None = "Bright family home.",
) -> PropertyReelSlide:
    return PropertyReelSlide(image_path=image_path, caption=caption)


@pytest.fixture()
def property_data() -> PropertyRenderData:
    return build_property_data()


@pytest.fixture()
def template() -> PropertyReelTemplate:
    return build_template()


@pytest.fixture()
def slide() -> PropertyReelSlide:
    return build_slide()
