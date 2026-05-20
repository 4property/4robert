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


def _apply_max_chars(text: str, max_chars: int) -> str:
    """Truncate a caption to ``max_chars`` graphemes, preserving word boundaries.

    Feature 31: ``subtitle_max_chars`` lets the agency cap the caption
    length before the text-measurement engine breaks the string into
    lines. We truncate on a word boundary when possible (so a caption
    does not end mid-word) and append an ellipsis only when the cap
    actually fired — otherwise the caption is returned verbatim.
    """
    if max_chars <= 0:
        return text
    if len(text) <= max_chars:
        return text
    cutoff = text.rfind(" ", 0, max_chars)
    if cutoff <= 0:
        cutoff = max_chars
    truncated = text[:cutoff].rstrip()
    return f"{truncated}…" if truncated else text[:max_chars]


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
    # Feature 31: read the per-agency subtitle styling that travels with
    # ``property_data``. The dataclass defaults preserve the historical
    # look (bottom / center / no uppercase / 36-char wrap) when an agency
    # never opened the ``/defaults > Subtitles`` panel.
    subtitle_style = getattr(property_data, "subtitle_style", None)
    style_position = (subtitle_style.position if subtitle_style is not None else "bottom")
    style_alignment = (subtitle_style.alignment if subtitle_style is not None else "center")
    style_uppercase = bool(subtitle_style.uppercase) if subtitle_style is not None else False
    style_max_chars = int(subtitle_style.max_chars) if subtitle_style is not None else 36
    # Feature 36: when the reel carries a per-reel subtitles override,
    # bypass the autoCaptions builder and source the (start, end, text)
    # triples directly from the override cues. Geometry, font and style
    # cascade unchanged so the override video matches the agency's
    # subtitle look. The override always wins over ``slide_duration``;
    # if the caller still has no ``slide_duration`` we have no geometry
    # to anchor the segments to and fall back to the empty list (same
    # contract as the legacy code path).
    subtitles_override = getattr(property_data, "subtitles_override", None)
    if subtitles_override and slide_duration is not None:
        subtitle_gap_y = max(20, round(height * 0.018))
        subtitle_x = outer_margin_x + panel_padding_x
        subtitle_max_width = panel_width - (panel_padding_x * 2)
        subtitle_bottom_y = (
            (bottom_panel.y if bottom_panel is not None else height - outer_margin_y)
            - subtitle_gap_y
        )
        raw_segments = [
            (float(in_seconds), float(out_seconds), str(text_value))
            for (_index, text_value, in_seconds, out_seconds) in subtitles_override
        ]
        return _build_subtitle_segments_from_raw(
            raw_segments=raw_segments,
            settings=settings,
            subtitle_style=subtitle_style,
            style_position=style_position,
            style_alignment=style_alignment,
            style_uppercase=style_uppercase,
            style_max_chars=style_max_chars,
            subtitle_x=subtitle_x,
            subtitle_max_width=subtitle_max_width,
            subtitle_bottom_y=subtitle_bottom_y,
            height=height,
        )
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

        segments, more_warnings = _build_subtitle_segments_from_raw(
            raw_segments=raw_segments,
            settings=settings,
            subtitle_style=subtitle_style,
            style_position=style_position,
            style_alignment=style_alignment,
            style_uppercase=style_uppercase,
            style_max_chars=style_max_chars,
            subtitle_x=subtitle_x,
            subtitle_max_width=subtitle_max_width,
            subtitle_bottom_y=subtitle_bottom_y,
            height=height,
        )
        subtitle_segments.extend(segments)
        warnings.extend(more_warnings)

    return tuple(subtitle_segments), tuple(warnings)


def _build_subtitle_segments_from_raw(
    *,
    raw_segments: list[tuple[float, float, str]],
    settings: PropertyReelTemplate,
    subtitle_style,
    style_position: str,
    style_alignment: str,
    style_uppercase: bool,
    style_max_chars: int,
    subtitle_x: int,
    subtitle_max_width: int,
    subtitle_bottom_y: int,
    height: int,
) -> tuple[tuple[TimedTextSegmentLayout, ...], tuple[LayoutWarning, ...]]:
    """Materialise a sequence of ``(start, end, text)`` triples into
    ``TimedTextSegmentLayout`` objects.

    Extracted from the body of :func:`compose_subtitle_segments` so the
    autoCaptions flow and the feature-36 override flow can share the
    same measurement / geometry pipeline. The behaviour is preserved
    byte-for-byte versus the legacy inline loop; only the source of the
    ``raw_segments`` differs (slide.caption vs override cues).
    """
    measured_segments: list[TimedTextSegmentLayout] = []
    accumulated_warnings: list[LayoutWarning] = []
    for start_time, end_time, caption_text in raw_segments:
        if not caption_text:
            continue
        caption_text = _apply_max_chars(caption_text, style_max_chars)
        if style_uppercase:
            caption_text = caption_text.upper()
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
            accumulated_warnings.append(measured_caption.warning)
        if style_position == "top":
            segment_y = round(height * 0.10)
        elif style_position == "middle":
            segment_y = max(
                0,
                round((height - measured_caption.box_height) / 2),
            )
        else:
            segment_y = subtitle_bottom_y - measured_caption.box_height
        measured_segments.append(
            TimedTextSegmentLayout(
                block="subtitle_caption",
                text=measured_caption.text,
                lines=measured_caption.lines,
                font_size=measured_caption.font_size,
                x=subtitle_x,
                y=segment_y,
                max_width=measured_caption.max_width,
                line_gap=measured_caption.line_gap,
                box_height=measured_caption.box_height,
                max_lines=measured_caption.max_lines,
                clamped=measured_caption.clamped,
                start_time=start_time,
                end_time=end_time,
                alignment=style_alignment,
            )
        )
    return tuple(measured_segments), tuple(accumulated_warnings)


def build_auto_subtitles_snapshot(
    *,
    slides: tuple[PropertyReelSlide, ...] | list[PropertyReelSlide],
    settings: PropertyReelTemplate,
    property_data: PropertyReelData,
    slide_duration: float | None = None,
) -> list[dict[str, object]]:
    """Materialise the autoCaptions cues into the snapshot shape persisted
    in ``reels.auto_subtitles_snapshot`` (feature 41).

    Mirrors the cue construction the renderer uses inside
    :func:`compose_subtitle_segments` for the autoCaptions branch: the
    intro caption (when present), then one cue per slide spanning
    ``[slide_start, slide_start + slide_duration)``. The ``text`` field
    is the resolved caption ahead of the per-frame text-measurement
    pass (we keep the raw text rather than the truncated / uppercased
    variant the renderer paints onscreen so the editor sees what the
    Gemini captioner produced verbatim). When the caller has no
    ``slide_duration`` (the renderer cannot anchor cues), this function
    returns an empty list — same fall-back contract as the autoCaptions
    composer.

    The returned cues use the same shape as ``subtitles_override`` so
    the editor (feature 36) can swap one for the other without
    translation.
    """
    if not slides:
        return []
    resolved_slide_duration = (
        float(slide_duration)
        if slide_duration is not None
        else float(settings.seconds_per_slide)
    )
    if resolved_slide_duration <= 0:
        return []
    forced_subtitle = build_similar_required_subtitle(property_data)
    intro_duration = (
        float(settings.intro_duration_seconds)
        if settings.include_intro
        else 0.0
    )
    cues: list[dict[str, object]] = []
    cue_index = 0
    if settings.include_intro:
        intro_caption = _resolve_subtitle_caption(
            forced_subtitle,
            slides[0].caption if slides else None,
        )
        if intro_caption:
            cues.append(
                {
                    "index": cue_index,
                    "text": intro_caption,
                    "in_seconds": 0.0,
                    "out_seconds": intro_duration,
                }
            )
            cue_index += 1
    slide_start_offset = intro_duration
    for slide_index, slide in enumerate(slides):
        caption_text = _resolve_subtitle_caption(forced_subtitle, slide.caption)
        if not caption_text:
            continue
        in_seconds = slide_start_offset + (slide_index * resolved_slide_duration)
        out_seconds = in_seconds + resolved_slide_duration
        cues.append(
            {
                "index": cue_index,
                "text": caption_text,
                "in_seconds": float(in_seconds),
                "out_seconds": float(out_seconds),
            }
        )
        cue_index += 1
    return cues


__all__ = ["build_auto_subtitles_snapshot", "compose_subtitle_segments"]
