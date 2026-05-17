"""Integration tests for feature 31's subtitle styling cascade.

Verifies that each setting persisted under
``agency_reel_defaults.settings`` (via the frontend ``/defaults > Subtitles``
panel) reaches the ffmpeg filter graph emitted by
:func:`build_overlay_filter`. We assert the filter string at the
``subtitle_caption`` ``drawtext`` segment — the rest of the overlay is
covered by the unit-level snapshot in
``tests/unit/rendering/test_overlay_filter_classic_snapshot.py``.

Setting → filter-graph mapping under test:

* ``subtitle_color`` → ``fontcolor=0xRRGGBB`` token;
* ``subtitle_bg_style`` (``block``/``outline``/``none``) → ``box=1`` /
  ``borderw=2`` / neither;
* ``subtitle_bg_color`` + ``subtitle_bg_opacity`` → ``boxcolor=...@.5``;
* ``subtitle_uppercase`` → caption text is upper-cased before drawtext;
* ``subtitle_alignment`` (``left``/``right``/``center``) → ``x=`` expr;
* ``subtitle_position`` (``top``) → ``y=`` within the top 25% of the frame;
* ``auto_captions_enabled=False`` → no subtitle drawtext at all.
"""

from __future__ import annotations

import re
from dataclasses import replace

from modules.rendering.infrastructure.ffmpeg.filters import build_overlay_filter
from modules.rendering.infrastructure.models import SubtitleStyle
from tests.unit.rendering.conftest import build_property_data, build_template


_TEMPLATE = build_template(width=1080, height=1920)


def _emit_overlay_with_style(style: SubtitleStyle, *, caption: str = "hello world") -> str:
    property_data = replace(build_property_data(), subtitle_style=style)
    return build_overlay_filter(
        property_data,
        _TEMPLATE,
        slide_captions=(caption,),
        slide_duration=2.5,
    )


def _subtitle_drawtext_segments(filter_graph: str) -> list[str]:
    """Return every drawtext fragment whose enable= expression is a subtitle.

    Subtitle drawtexts are the only ones that carry an
    ``enable='between(...)'`` time-gate. We cannot split on raw ``,``
    because the enable expression itself contains escaped commas
    (``\\,``) inside ``between(t\\,a\\,b)``. Instead, locate each
    ``enable='between(t\\,...)'`` suffix and walk back to the nearest
    ``drawtext=`` start token.
    """
    suffix_pattern = re.compile(r"enable='between\(t\\,[\d.]+\\,[\d.]+\)'")
    matches: list[str] = []
    for match in suffix_pattern.finditer(filter_graph):
        end = match.end()
        start = filter_graph.rfind("drawtext=", 0, end)
        if start == -1:
            continue
        matches.append(filter_graph[start:end])
    return matches


def test_subtitle_color_hex_appears_in_drawtext() -> None:
    graph = _emit_overlay_with_style(SubtitleStyle(color="#FF0000"))
    drawtexts = _subtitle_drawtext_segments(graph)
    assert drawtexts, "expected at least one subtitle drawtext"
    assert all("fontcolor=0xFF0000" in fragment for fragment in drawtexts), drawtexts
    assert not any("fontcolor=0xffffff" in fragment for fragment in drawtexts)


def test_subtitle_bg_style_block_emits_box_and_boxcolor() -> None:
    graph = _emit_overlay_with_style(
        SubtitleStyle(bg_style="block", bg_color="#000000", bg_opacity=50)
    )
    drawtexts = _subtitle_drawtext_segments(graph)
    assert drawtexts
    assert all("box=1" in fragment for fragment in drawtexts)
    # Opacity 50 -> 0.50 alpha; box color uses ffmpeg 0xRRGGBB form.
    assert all("boxcolor=0x000000@0.50" in fragment for fragment in drawtexts), drawtexts
    # ``:borderw=`` is the outline stroke; ``boxborderw`` is the box
    # padding for ``box=1`` and is expected on this style.
    assert all(":borderw=" not in fragment for fragment in drawtexts)


def test_subtitle_bg_style_none_omits_border_and_box() -> None:
    graph = _emit_overlay_with_style(SubtitleStyle(bg_style="none"))
    drawtexts = _subtitle_drawtext_segments(graph)
    assert drawtexts
    for fragment in drawtexts:
        assert ":borderw=" not in fragment, fragment
        assert "box=1" not in fragment, fragment


def test_subtitle_bg_style_outline_emits_borderw() -> None:
    graph = _emit_overlay_with_style(SubtitleStyle(bg_style="outline"))
    drawtexts = _subtitle_drawtext_segments(graph)
    assert drawtexts
    assert all("borderw=2:bordercolor=black@0.80" in fragment for fragment in drawtexts)
    assert all("box=1" not in fragment for fragment in drawtexts)


def test_subtitle_uppercase_uppercases_the_caption_text() -> None:
    graph = _emit_overlay_with_style(
        SubtitleStyle(uppercase=True),
        caption="hello world",
    )
    drawtexts = _subtitle_drawtext_segments(graph)
    assert drawtexts
    # The measurer may wrap the caption across lines, but no rendered
    # line may contain the original lowercase token.
    joined = "".join(drawtexts)
    assert "HELLO" in joined
    assert "text='hello" not in joined


def test_subtitle_alignment_left_emits_static_x() -> None:
    graph = _emit_overlay_with_style(SubtitleStyle(alignment="left"))
    drawtexts = _subtitle_drawtext_segments(graph)
    assert drawtexts
    for fragment in drawtexts:
        assert "max((" not in fragment, fragment  # no centering offset
        assert "max(" not in fragment.split(":x=")[1].split(":y=")[0], fragment


def test_subtitle_alignment_right_emits_max_offset() -> None:
    graph = _emit_overlay_with_style(SubtitleStyle(alignment="right"))
    drawtexts = _subtitle_drawtext_segments(graph)
    assert drawtexts
    for fragment in drawtexts:
        x_expr = fragment.split(":x=")[1].split(":y=")[0]
        assert "-text_w" in x_expr, fragment


def test_subtitle_position_top_anchors_inside_first_quarter() -> None:
    graph = _emit_overlay_with_style(SubtitleStyle(position="top"))
    drawtexts = _subtitle_drawtext_segments(graph)
    assert drawtexts
    quarter_height = _TEMPLATE.height // 4
    for fragment in drawtexts:
        # ``y=`` is followed by either an integer (no line offset on the
        # first line) or "<int> + index*line_gap"; we just need to be
        # robust to both shapes.
        y_token = fragment.split(":y=")[1].split(":")[0]
        y_value = int(y_token.split("+")[0].strip())
        assert y_value < quarter_height, (y_value, quarter_height, fragment)


def test_auto_captions_disabled_emits_no_subtitle_drawtext() -> None:
    graph = _emit_overlay_with_style(SubtitleStyle(enabled=False))
    drawtexts = _subtitle_drawtext_segments(graph)
    assert drawtexts == []
