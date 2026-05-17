"""Integration tests for the subtitles override branch of the renderer (feature 36).

The renderer's overlay composition step bypasses
:func:`compose_subtitle_segments`'s autoCaptions-derived loop when
``property_data.subtitles_override`` is set, and instead drives the
``drawtext`` ladder from the override cues. These tests assert the
emitted ffmpeg filter graph carries:

* exactly one ``drawtext`` per cue, with the cue text rendered verbatim;
* the ``enable='between(t,start,end)'`` window matching the cue timing;
* the override winning even when the per-agency ``auto_captions_enabled``
  toggle is ``False`` (the override is editorial intent for the reel).

When ``subtitles_override`` is ``None`` the historical behaviour is
preserved: subtitles render only when the agency keeps autoCaptions
enabled.
"""

from __future__ import annotations

import re
from dataclasses import replace

from modules.rendering.infrastructure.ffmpeg.filters import build_overlay_filter
from modules.rendering.infrastructure.models import SubtitleStyle
from tests.unit.rendering.conftest import build_property_data, build_template


_TEMPLATE = build_template(width=1080, height=1920)


def _emit_overlay(
    *,
    subtitles_override=None,
    subtitle_style: SubtitleStyle | None = None,
    caption: str = "auto generated caption",
):
    property_data = build_property_data()
    if subtitle_style is not None:
        property_data = replace(property_data, subtitle_style=subtitle_style)
    if subtitles_override is not None:
        property_data = replace(property_data, subtitles_override=subtitles_override)
    return build_overlay_filter(
        property_data,
        _TEMPLATE,
        slide_captions=(caption,),
        slide_duration=2.5,
    )


def _subtitle_drawtext_segments(filter_graph: str) -> list[str]:
    """Return every drawtext fragment that carries a time-gated enable.

    Same approach used by ``test_subtitle_settings_wiring.py``.
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


# ---------------------------------------------------------------------------
# Override wins over autoCaptions
# ---------------------------------------------------------------------------


def test_renderer_uses_override_cues_when_present() -> None:
    """Override cues replace the slide-derived captions in the filter graph."""
    override = (
        (0, "Welcome to this property", 0.0, 2.0),
        (1, "Stunning kitchen and living area", 2.0, 5.5),
    )
    graph = _emit_overlay(subtitles_override=override)
    drawtexts = _subtitle_drawtext_segments(graph)
    assert len(drawtexts) == 2, drawtexts
    joined = "\n".join(drawtexts)
    # Override text appears verbatim (escaped commas allowed but the
    # straight chars must be present).
    assert "Welcome to this property" in joined
    assert "Stunning kitchen and living area" in joined
    # AutoCaptions-derived text does NOT.
    assert "auto generated caption" not in joined
    # Timing windows from the cues.
    assert "between(t\\,0.000\\,2.000)" in joined
    assert "between(t\\,2.000\\,5.500)" in joined


def test_renderer_override_wins_when_auto_captions_disabled() -> None:
    """Override renders even with the agency-level autoCaptions toggle off."""
    override = ((0, "Override caption text", 0.5, 4.0),)
    graph = _emit_overlay(
        subtitles_override=override,
        subtitle_style=SubtitleStyle(enabled=False),
    )
    drawtexts = _subtitle_drawtext_segments(graph)
    assert len(drawtexts) == 1, drawtexts
    assert "Override caption text" in drawtexts[0]
    assert "between(t\\,0.500\\,4.000)" in drawtexts[0]


# ---------------------------------------------------------------------------
# Null / empty override → fall back to autoCaptions semantics
# ---------------------------------------------------------------------------


def test_renderer_falls_back_to_autocaptions_when_override_is_none() -> None:
    """``subtitles_override=None`` + autoCaptions enabled → slide caption renders."""
    graph = _emit_overlay(
        subtitles_override=None,
        subtitle_style=SubtitleStyle(enabled=True),
        caption="auto generated caption",
    )
    drawtexts = _subtitle_drawtext_segments(graph)
    assert drawtexts, drawtexts
    joined = "\n".join(drawtexts)
    assert "auto generated caption" in joined


def test_renderer_skips_subtitles_when_override_none_and_autocaptions_off() -> None:
    """No override, agency disabled autoCaptions → no subtitle drawtext at all."""
    graph = _emit_overlay(
        subtitles_override=None,
        subtitle_style=SubtitleStyle(enabled=False),
        caption="auto generated caption",
    )
    drawtexts = _subtitle_drawtext_segments(graph)
    assert drawtexts == []


# ---------------------------------------------------------------------------
# Override text length / encoding edge cases
# ---------------------------------------------------------------------------


def test_renderer_override_handles_single_cue() -> None:
    override = ((0, "Single line", 1.0, 3.0),)
    graph = _emit_overlay(subtitles_override=override)
    drawtexts = _subtitle_drawtext_segments(graph)
    assert len(drawtexts) == 1
    assert "Single line" in drawtexts[0]
