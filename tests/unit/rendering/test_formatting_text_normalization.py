"""Regression tests for overlay text normalization before ffmpeg drawtext."""

from __future__ import annotations

from modules.rendering.infrastructure.formatting import (
    build_property_header_details_line,
    clean_text,
    escape_drawtext_text,
)
from tests.unit.rendering.conftest import build_property_data


def test_clean_text_repairs_common_utf8_mojibake() -> None:
    assert clean_text("DonnybrookÃ¢â‚¬â„¢s finest") == "Donnybrook’s finest"
    assert clean_text("108mÂ²") == "108m²"


def test_escape_drawtext_text_normalizes_before_escaping() -> None:
    assert escape_drawtext_text("Owner&#x2019;s suite") == "Owner’s suite"
    assert escape_drawtext_text("Apt: 2, Donnybrook") == r"Apt\: 2\, Donnybrook"


def test_side_banner_details_can_use_compact_room_labels() -> None:
    property_data = build_property_data(bedrooms=3, bathrooms=2)
    property_data.property_size = "108mÂ²"

    assert (
        build_property_header_details_line(
            property_data,
            compact_room_labels=True,
        )
        == "108m² | 3beds | 2baths"
    )
