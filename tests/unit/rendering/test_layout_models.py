"""Unit tests for `modules.rendering.infrastructure.layout.models`."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from modules.rendering.infrastructure.layout.models import (
    BoxLayout,
    LayoutWarning,
    OverlayLayout,
    TextBlockLayout,
    TimedTextSegmentLayout,
)


def _make_box(*, x: int = 10, y: int = 20) -> BoxLayout:
    return BoxLayout(visible=True, x=x, y=y, width=100, height=80)


def _make_text_block() -> TextBlockLayout:
    return TextBlockLayout(
        block="address",
        visible=True,
        text="110 Example Road",
        lines=("110 Example Road",),
        font_size=32,
        x=40,
        y=120,
        max_width=400,
        line_gap=40,
        box_height=32,
        max_lines=2,
        clamped=False,
    )


def _make_timed_segment() -> TimedTextSegmentLayout:
    return TimedTextSegmentLayout(
        block="subtitle_caption",
        text="A bright home.",
        lines=("A bright home.",),
        font_size=28,
        x=20,
        y=440,
        max_width=280,
        line_gap=36,
        box_height=28,
        max_lines=3,
        clamped=False,
        start_time=1.23456,
        end_time=4.56789,
    )


def test_box_layout_to_dict_round_trips_all_fields() -> None:
    box = _make_box()
    assert box.to_dict() == {
        "visible": True,
        "x": 10,
        "y": 20,
        "width": 100,
        "height": 80,
    }


def test_text_block_layout_to_dict_renders_lines_as_list() -> None:
    block = _make_text_block()
    payload = block.to_dict()
    assert payload["lines"] == ["110 Example Road"]
    assert isinstance(payload["lines"], list)
    assert payload["block"] == "address"
    assert payload["font_size"] == 32
    assert payload["clamped"] is False


def test_timed_text_segment_to_dict_rounds_times_to_three_decimals() -> None:
    segment = _make_timed_segment()
    payload = segment.to_dict()
    assert payload["start_time"] == 1.235
    assert payload["end_time"] == 4.568
    assert payload["lines"] == ["A bright home."]


def test_layout_warning_to_dict_includes_original_text() -> None:
    warning = LayoutWarning(
        code="TEXT_CLAMPED",
        block="address",
        message="address was clamped to fit within the reel overlay.",
        original_text="long original text",
    )
    assert warning.to_dict() == {
        "code": "TEXT_CLAMPED",
        "block": "address",
        "message": "address was clamped to fit within the reel overlay.",
        "original_text": "long original text",
    }


def test_overlay_layout_to_dict_serializes_nested_boxes_and_text_blocks() -> None:
    overlay = OverlayLayout(
        frame_width=320,
        frame_height=480,
        top_panel=_make_box(x=10, y=20),
        bottom_panel=_make_box(x=10, y=320),
        agent_image_box=_make_box(x=20, y=340),
        agency_logo_box=_make_box(x=200, y=340),
        ber_badge_box=_make_box(x=260, y=30),
        text_blocks=(_make_text_block(),),
        subtitle_segments=(_make_timed_segment(),),
        warnings=(
            LayoutWarning(
                code="TEXT_CLAMPED",
                block="address",
                message="m",
                original_text="orig",
            ),
        ),
    )

    payload = overlay.to_dict()

    assert payload["frame_width"] == 320
    assert payload["frame_height"] == 480
    assert payload["top_panel"] == {
        "visible": True,
        "x": 10,
        "y": 20,
        "width": 100,
        "height": 80,
    }
    assert payload["bottom_panel"]["y"] == 320
    assert payload["agent_image_box"]["x"] == 20
    assert payload["agency_logo_box"]["x"] == 200
    assert payload["ber_badge_box"]["x"] == 260
    assert isinstance(payload["text_blocks"], list)
    assert payload["text_blocks"][0]["block"] == "address"
    assert isinstance(payload["subtitle_segments"], list)
    assert payload["subtitle_segments"][0]["block"] == "subtitle_caption"
    assert payload["warnings"][0]["original_text"] == "orig"


def test_overlay_layout_to_dict_handles_none_panels() -> None:
    overlay = OverlayLayout(
        frame_width=320,
        frame_height=480,
        top_panel=None,
        bottom_panel=None,
        agent_image_box=None,
        agency_logo_box=None,
        ber_badge_box=None,
        text_blocks=(),
        subtitle_segments=(),
        warnings=(),
    )

    payload = overlay.to_dict()

    assert payload["top_panel"] is None
    assert payload["bottom_panel"] is None
    assert payload["agent_image_box"] is None
    assert payload["agency_logo_box"] is None
    assert payload["ber_badge_box"] is None
    assert payload["text_blocks"] == []
    assert payload["subtitle_segments"] == []
    assert payload["warnings"] == []


def test_dataclasses_are_frozen() -> None:
    box = _make_box()
    with pytest.raises(FrozenInstanceError):
        box.x = 999  # type: ignore[misc]
    warning = LayoutWarning(code="X", block="b", message="m")
    with pytest.raises(FrozenInstanceError):
        warning.code = "Y"  # type: ignore[misc]
