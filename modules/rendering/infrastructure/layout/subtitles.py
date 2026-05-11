"""Timed subtitle segment composition for the property-reel overlay.

Extracted verbatim (with kwarg-only signature) from
`services.media.reel_rendering.layout.build_overlay_layout` as part of
feature 15 (`rendering_layout_split`). The phase C body is preserved
byte-for-byte; what previously were locals in `build_overlay_layout`
(`outer_margin_x`, `panel_padding_x`, `panel_width`, ...) become explicit
keyword arguments.

Note: imports from `services.ai.photo_selection.prompting`,
`services.media.reel_rendering.formatting` and
`services.media.reel_rendering.models` are a transitional cross-frontier
dependency removed by feature 18 when `services/` is retired.
"""

from __future__ import annotations

from modules.rendering.infrastructure.layout.models import (
    BoxLayout,
    LayoutWarning,
    TimedTextSegmentLayout,
)
from modules.rendering.infrastructure.layout.text_measurement import measure_text_block
from modules.rendering.infrastructure.ai_photo_selection.prompting import normalize_caption
from modules.rendering.infrastructure.formatting import (
    build_similar_required_subtitle,
    clean_text,
    resolve_font_size_bounds,
)
from modules.rendering.infrastructure.models import (
    PropertyReelData,
    PropertyReelSlide,
    PropertyReelTemplate,
)


def _resolve_subtitle_caption(
    forced_subtitle: str | None,
    fallback_caption: str | None,
) -> str:
    if forced_subtitle is not None:
        return clean_text(forced_subtitle) or ""
    return normalize_caption(fallback_caption, "")


def compose_subtitle_segments(
    property_data: PropertyReelData,
    settings: PropertyReelTemplate,
    *,
    slides: tuple[PropertyReelSlide, ...] | list[PropertyReelSlide],
    slide_duration: float | None,
    cover_caption: str | None,
    bottom_panel: BoxLayout | None,
    panel_width: int,
    outer_margin_x: int,
    outer_margin_y: int,
    panel_padding_x: int,
) -> tuple[tuple[TimedTextSegmentLayout, ...], tuple[LayoutWarning, ...]]:
    height = settings.height
    warnings: list[LayoutWarning] = []
    subtitle_segments: list[TimedTextSegmentLayout] = []
    if slide_duration is not None:
        subtitle_gap_y = max(20, round(height * 0.018))
        subtitle_x = outer_margin_x + panel_padding_x
        subtitle_max_width = panel_width - (panel_padding_x * 2)
        subtitle_bottom_y = (
            (bottom_panel.y if bottom_panel is not None else height - outer_margin_y)
            - subtitle_gap_y
        )
        raw_segments = []
        forced_subtitle = build_similar_required_subtitle(property_data)
        intro_duration = settings.intro_duration_seconds if settings.include_intro else 0.0
        if settings.include_intro:
            intro_caption = _resolve_subtitle_caption(
                forced_subtitle,
                cover_caption if cover_caption is not None else slides[0].caption if slides else None,
            )
            raw_segments.append((0.0, intro_duration, intro_caption))
        slide_start_offset = intro_duration
        for index, slide in enumerate(slides):
            raw_segments.append(
                (
                    slide_start_offset + (index * slide_duration),
                    slide_start_offset + ((index + 1) * slide_duration),
                    _resolve_subtitle_caption(forced_subtitle, slide.caption),
                )
            )

        for start_time, end_time, caption_text in raw_segments:
            if not caption_text:
                continue
            measured_caption = measure_text_block(
                block="subtitle_caption",
                text=caption_text,
                usable_width=subtitle_max_width,
                max_lines=3,
                max_font_size=resolve_font_size_bounds(
                    "subtitle_caption",
                    frame_height=height,
                    subtitle_font_size=settings.subtitle_font_size,
                )[0],
                min_font_size=resolve_font_size_bounds(
                    "subtitle_caption",
                    frame_height=height,
                    subtitle_font_size=settings.subtitle_font_size,
                )[1],
                min_chars=14,
            )
            if measured_caption is None:
                continue
            if measured_caption.warning is not None:
                warnings.append(measured_caption.warning)
            subtitle_segments.append(
                TimedTextSegmentLayout(
                    block="subtitle_caption",
                    text=measured_caption.text,
                    lines=measured_caption.lines,
                    font_size=measured_caption.font_size,
                    x=subtitle_x,
                    y=subtitle_bottom_y - measured_caption.box_height,
                    max_width=measured_caption.max_width,
                    line_gap=measured_caption.line_gap,
                    box_height=measured_caption.box_height,
                    max_lines=measured_caption.max_lines,
                    clamped=measured_caption.clamped,
                    start_time=start_time,
                    end_time=end_time,
                )
            )

    return tuple(subtitle_segments), tuple(warnings)


__all__ = ["compose_subtitle_segments"]
