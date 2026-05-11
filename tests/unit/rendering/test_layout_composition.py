"""Unit tests for `modules.rendering.infrastructure.layout.composition`."""

from __future__ import annotations

from modules.rendering.infrastructure.layout import build_overlay_layout
from modules.rendering.infrastructure.layout.models import OverlayLayout
from tests.unit.rendering.conftest import (
    build_property_data,
    build_slide,
    build_template,
)


def test_build_overlay_layout_returns_overlay_with_top_and_bottom_panel() -> None:
    overlay = build_overlay_layout(
        build_property_data(),
        build_template(),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
    )

    assert isinstance(overlay, OverlayLayout)
    assert overlay.frame_width == 320
    assert overlay.frame_height == 480
    assert overlay.top_panel is not None
    assert overlay.bottom_panel is not None
    assert overlay.agency_logo_box is not None


def test_build_overlay_layout_text_blocks_order_top_then_bottom() -> None:
    overlay = build_overlay_layout(
        build_property_data(),
        build_template(),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=False,
    )

    block_names = [block.block for block in overlay.text_blocks]
    top_blocks = {"status", "price", "address", "viewing_times", "address_meta"}
    bottom_blocks = {"agent_name", "agent_phone", "agent_email", "agency_psra"}

    last_top_index = -1
    first_bottom_index = len(block_names)
    for index, name in enumerate(block_names):
        if name in top_blocks:
            last_top_index = max(last_top_index, index)
        if name in bottom_blocks:
            first_bottom_index = min(first_bottom_index, index)

    assert last_top_index >= 0
    assert first_bottom_index < len(block_names)
    assert last_top_index < first_bottom_index


def test_build_overlay_layout_no_ber_badge_when_flag_false() -> None:
    overlay = build_overlay_layout(
        build_property_data(),
        build_template(),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=False,
    )
    assert overlay.ber_badge_box is None


def test_build_overlay_layout_emits_ber_badge_when_flag_true() -> None:
    overlay = build_overlay_layout(
        build_property_data(ber_rating="A1"),
        build_template(),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=True,
        has_agency_logo=False,
    )
    assert overlay.ber_badge_box is not None


def test_build_overlay_layout_no_agency_logo_when_flag_false() -> None:
    overlay = build_overlay_layout(
        build_property_data(),
        build_template(),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=False,
    )
    assert overlay.agency_logo_box is None


def test_build_overlay_layout_subtitle_segments_match_slide_count() -> None:
    overlay = build_overlay_layout(
        build_property_data(),
        build_template(),
        slides=(
            build_slide(caption="One"),
            build_slide(caption="Two"),
            build_slide(caption="Three"),
        ),
        slide_duration=2.0,
        has_ber_badge=False,
        has_agency_logo=False,
    )
    assert len(overlay.subtitle_segments) == 3


def test_build_overlay_layout_intro_subtitle_when_template_includes_intro() -> None:
    overlay = build_overlay_layout(
        build_property_data(),
        build_template(include_intro=True, intro_duration_seconds=1.5),
        slides=(build_slide(caption="Slide caption"),),
        slide_duration=2.0,
        has_ber_badge=False,
        has_agency_logo=False,
        cover_caption="Intro caption",
    )
    assert len(overlay.subtitle_segments) == 2
