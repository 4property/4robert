"""Unit tests for `modules.rendering.infrastructure.layout.subtitles`."""

from __future__ import annotations

import pytest

from modules.rendering.infrastructure.layout.models import BoxLayout
from modules.rendering.infrastructure.layout.subtitles import (
    _resolve_subtitle_caption,
    compose_subtitle_segments,
)
from tests.unit.rendering.conftest import (
    build_property_data,
    build_slide,
    build_template,
)


def _layout_kwargs(template) -> dict[str, int]:
    width = template.width
    outer_margin_x = max(36, round(width * 0.04))
    outer_margin_y = max(36, round(template.height * 0.03))
    panel_padding_x = max(26, round(width * 0.024))
    panel_width = width - (outer_margin_x * 2)
    return {
        "outer_margin_x": outer_margin_x,
        "outer_margin_y": outer_margin_y,
        "panel_padding_x": panel_padding_x,
        "panel_width": panel_width,
    }


def test_compose_subtitle_segments_returns_empty_when_slide_duration_is_none() -> None:
    property_data = build_property_data()
    template = build_template()
    slide = build_slide()
    segments, warnings = compose_subtitle_segments(
        property_data,
        template,
        slides=(slide,),
        slide_duration=None,
        cover_caption=None,
        bottom_panel=None,
        **_layout_kwargs(template),
    )
    assert segments == ()
    assert warnings == ()


def test_compose_subtitle_segments_emits_one_segment_per_slide() -> None:
    property_data = build_property_data()
    template = build_template()
    slide_a = build_slide(caption="Caption A")
    slide_b = build_slide(caption="Caption B")
    segments, _warnings = compose_subtitle_segments(
        property_data,
        template,
        slides=(slide_a, slide_b),
        slide_duration=2.5,
        cover_caption=None,
        bottom_panel=None,
        **_layout_kwargs(template),
    )
    assert len(segments) == 2
    assert segments[0].text.startswith("Caption A")
    assert segments[1].text.startswith("Caption B")
    assert segments[0].start_time == pytest.approx(0.0)
    assert segments[0].end_time == pytest.approx(2.5)
    assert segments[1].start_time == pytest.approx(2.5)
    assert segments[1].end_time == pytest.approx(5.0)


def test_compose_subtitle_segments_emits_intro_segment_when_intro_enabled() -> None:
    property_data = build_property_data()
    template = build_template(include_intro=True, intro_duration_seconds=1.5)
    slide = build_slide(caption="Slide caption")
    segments, _warnings = compose_subtitle_segments(
        property_data,
        template,
        slides=(slide,),
        slide_duration=2.0,
        cover_caption="Cover caption",
        bottom_panel=None,
        **_layout_kwargs(template),
    )
    assert len(segments) == 2
    intro_segment = segments[0]
    assert intro_segment.text.startswith("Cover caption")
    assert intro_segment.start_time == pytest.approx(0.0)
    assert intro_segment.end_time == pytest.approx(1.5)
    slide_segment = segments[1]
    assert slide_segment.start_time == pytest.approx(1.5)
    assert slide_segment.end_time == pytest.approx(3.5)


def test_compose_subtitle_segments_y_aligns_above_bottom_panel() -> None:
    property_data = build_property_data()
    template = build_template()
    slide = build_slide(caption="Bright family home.")
    bottom_panel = BoxLayout(visible=True, x=10, y=320, width=300, height=140)
    segments, _warnings = compose_subtitle_segments(
        property_data,
        template,
        slides=(slide,),
        slide_duration=2.5,
        cover_caption=None,
        bottom_panel=bottom_panel,
        **_layout_kwargs(template),
    )
    assert segments
    for segment in segments:
        assert segment.y + segment.box_height < bottom_panel.y


def test_resolve_subtitle_caption_prefers_forced_subtitle() -> None:
    assert _resolve_subtitle_caption("FORCED", "ignored") == "FORCED"


def test_resolve_subtitle_caption_falls_back_to_caption_when_no_forced() -> None:
    assert _resolve_subtitle_caption(None, "Hello") != ""
