from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.ai_photo_selection.prompting import normalize_caption
from services.reel_rendering.formatting import (
    build_agent_lines,
    build_display_price,
    build_status_ribbon_text,
    clean_text,
    fit_wrapped_lines,
)
from services.reel_rendering.models import PropertyReelData, PropertyReelSlide, PropertyReelTemplate

_BER_ICON_ASPECT_RATIO = 1800 / 582
_BER_ICON_MIN_HEIGHT = 45
_BER_ICON_HEIGHT_RATIO = 0.0675


@dataclass(frozen=True, slots=True)
class LayoutWarning:
    code: str
    block: str
    message: str
    original_text: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "block": self.block,
            "message": self.message,
            "original_text": self.original_text,
        }


@dataclass(frozen=True, slots=True)
class BoxLayout:
    visible: bool
    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> dict[str, object]:
        return {
            "visible": self.visible,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True, slots=True)
class TextBlockLayout:
    block: str
    visible: bool
    text: str | None
    lines: tuple[str, ...]
    font_size: int
    x: int
    y: int
    max_width: int
    line_gap: int
    box_height: int
    max_lines: int
    clamped: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "block": self.block,
            "visible": self.visible,
            "text": self.text,
            "lines": list(self.lines),
            "font_size": self.font_size,
            "x": self.x,
            "y": self.y,
            "max_width": self.max_width,
            "line_gap": self.line_gap,
            "box_height": self.box_height,
            "max_lines": self.max_lines,
            "clamped": self.clamped,
        }


@dataclass(frozen=True, slots=True)
class TimedTextSegmentLayout:
    block: str
    text: str
    lines: tuple[str, ...]
    font_size: int
    x: int
    y: int
    max_width: int
    line_gap: int
    box_height: int
    max_lines: int
    clamped: bool
    start_time: float
    end_time: float

    def to_dict(self) -> dict[str, object]:
        return {
            "block": self.block,
            "text": self.text,
            "lines": list(self.lines),
            "font_size": self.font_size,
            "x": self.x,
            "y": self.y,
            "max_width": self.max_width,
            "line_gap": self.line_gap,
            "box_height": self.box_height,
            "max_lines": self.max_lines,
            "clamped": self.clamped,
            "start_time": round(self.start_time, 3),
            "end_time": round(self.end_time, 3),
        }


@dataclass(frozen=True, slots=True)
class OverlayLayout:
    frame_width: int
    frame_height: int
    top_panel: BoxLayout | None
    bottom_panel: BoxLayout | None
    agent_image_box: BoxLayout | None
    ber_badge_box: BoxLayout | None
    text_blocks: tuple[TextBlockLayout, ...]
    subtitle_segments: tuple[TimedTextSegmentLayout, ...]
    warnings: tuple[LayoutWarning, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "top_panel": None if self.top_panel is None else self.top_panel.to_dict(),
            "bottom_panel": None if self.bottom_panel is None else self.bottom_panel.to_dict(),
            "agent_image_box": None if self.agent_image_box is None else self.agent_image_box.to_dict(),
            "ber_badge_box": None if self.ber_badge_box is None else self.ber_badge_box.to_dict(),
            "text_blocks": [block.to_dict() for block in self.text_blocks],
            "subtitle_segments": [segment.to_dict() for segment in self.subtitle_segments],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


@dataclass(frozen=True, slots=True)
class _MeasuredTextBlock:
    block: str
    text: str
    lines: tuple[str, ...]
    font_size: int
    line_gap: int
    box_height: int
    max_width: int
    max_lines: int
    clamped: bool
    warning: LayoutWarning | None = None


def _wrap_width_from_pixels(*, usable_width: int, font_size: int, min_chars: int) -> int:
    usable_width = max(120, usable_width)
    average_character_width = max(12.0, font_size * 0.58)
    return max(min_chars, round(usable_width / average_character_width))


def _resolve_top_panel_height_range(settings: PropertyReelTemplate) -> tuple[int, int]:
    return max(160, round(settings.height * 0.13)), max(340, round(settings.height * 0.34))


def _resolve_bottom_panel_height_range(settings: PropertyReelTemplate) -> tuple[int, int]:
    return max(170, round(settings.height * 0.11)), max(420, round(settings.height * 0.28))


def _resolve_ber_icon_size(settings: PropertyReelTemplate) -> tuple[int, int]:
    icon_height = max(_BER_ICON_MIN_HEIGHT, round(settings.height * _BER_ICON_HEIGHT_RATIO))
    icon_width = max(1, round(icon_height * _BER_ICON_ASPECT_RATIO))
    return icon_width, icon_height


def _candidate_font_sizes(max_size: int, min_size: int, *, step: int = 4) -> tuple[int, ...]:
    normalized_max = max(max_size, min_size)
    sizes: list[int] = []
    for candidate in range(normalized_max, min_size - 1, -step):
        if candidate not in sizes:
            sizes.append(candidate)
    if min_size not in sizes:
        sizes.append(min_size)
    return tuple(sizes)


def _measure_text_block(
    *,
    block: str,
    text: str | None,
    usable_width: int,
    max_lines: int,
    max_font_size: int,
    min_font_size: int,
    min_chars: int,
) -> _MeasuredTextBlock | None:
    normalized_text = clean_text(text)
    if not normalized_text:
        return None

    for font_size in _candidate_font_sizes(max_font_size, min_font_size):
        width_chars = _wrap_width_from_pixels(
            usable_width=usable_width,
            font_size=font_size,
            min_chars=min_chars,
        )
        wrapped = fit_wrapped_lines(normalized_text, width=width_chars, max_lines=max_lines)
        line_gap = font_size + max(8, round(font_size * 0.2))
        box_height = font_size + ((len(wrapped.lines) - 1) * line_gap if wrapped.lines else 0)
        if not wrapped.clamped:
            return _MeasuredTextBlock(
                block=block,
                text=normalized_text,
                lines=wrapped.lines,
                font_size=font_size,
                line_gap=line_gap,
                box_height=box_height,
                max_width=usable_width,
                max_lines=max_lines,
                clamped=False,
            )

    min_size = min(max_font_size, max_font_size if max_font_size <= min_font_size else min_font_size)
    width_chars = _wrap_width_from_pixels(
        usable_width=usable_width,
        font_size=min_size,
        min_chars=min_chars,
    )
    wrapped = fit_wrapped_lines(normalized_text, width=width_chars, max_lines=max_lines)
    line_gap = min_size + max(8, round(min_size * 0.2))
    box_height = min_size + ((len(wrapped.lines) - 1) * line_gap if wrapped.lines else 0)
    warning = LayoutWarning(
        code="TEXT_CLAMPED",
        block=block,
        message=f"{block} was clamped to fit within the reel overlay.",
        original_text=normalized_text,
    )
    return _MeasuredTextBlock(
        block=block,
        text=normalized_text,
        lines=wrapped.lines,
        font_size=min_size,
        line_gap=line_gap,
        box_height=box_height,
        max_width=usable_width,
        max_lines=max_lines,
        clamped=True,
        warning=warning,
    )


def build_overlay_layout(
    property_data: PropertyReelData,
    settings: PropertyReelTemplate,
    *,
    slides: tuple[PropertyReelSlide, ...] | list[PropertyReelSlide],
    slide_duration: float | None,
    has_ber_badge: bool,
    cover_caption: str | None = None,
) -> OverlayLayout:
    width = settings.width
    height = settings.height
    outer_margin_x = max(36, round(width * 0.04))
    outer_margin_y = max(36, round(height * 0.03))
    panel_padding_x = max(26, round(width * 0.024))
    panel_padding_y = max(22, round(height * 0.018))
    panel_width = width - (outer_margin_x * 2)

    warnings: list[LayoutWarning] = []
    ber_badge_box: BoxLayout | None = None
    ber_icon_gap = max(24, round(width * 0.018))
    ber_icon_width, ber_icon_height = _resolve_ber_icon_size(settings)
    header_text_width = panel_width - (panel_padding_x * 2)
    if has_ber_badge:
        header_text_width = max(260, header_text_width - ber_icon_width - ber_icon_gap)

    top_blocks: list[_MeasuredTextBlock] = []
    for measured_block in (
        _measure_text_block(
            block="status",
            text=build_status_ribbon_text(property_data),
            usable_width=header_text_width,
            max_lines=2,
            max_font_size=max(68, round(height * 0.05)),
            min_font_size=max(34, round(height * 0.026)),
            min_chars=8,
        ),
        _measure_text_block(
            block="price",
            text=build_display_price(property_data),
            usable_width=header_text_width,
            max_lines=2,
            max_font_size=max(62, round(height * 0.046)),
            min_font_size=max(32, round(height * 0.024)),
            min_chars=8,
        ),
        _measure_text_block(
            block="address",
            text=property_data.title,
            usable_width=header_text_width,
            max_lines=4,
            max_font_size=max(32, round(height * 0.024)),
            min_font_size=22,
            min_chars=18,
        ),
    ):
        if measured_block is None:
            continue
        top_blocks.append(measured_block)
        if measured_block.warning is not None:
            warnings.append(measured_block.warning)

    top_panel: BoxLayout | None = None
    text_blocks: list[TextBlockLayout] = []
    if top_blocks:
        top_gap = max(8, round(height * 0.006))
        top_content_height = sum(block.box_height for block in top_blocks) + (top_gap * (len(top_blocks) - 1))
        top_min_height, top_max_height = _resolve_top_panel_height_range(settings)
        top_panel_height = min(top_max_height, max(top_min_height, top_content_height + (panel_padding_y * 2)))
        top_panel = BoxLayout(
            visible=True,
            x=outer_margin_x,
            y=outer_margin_y,
            width=panel_width,
            height=top_panel_height,
        )
        cursor_y = top_panel.y + panel_padding_y
        text_x = top_panel.x + panel_padding_x
        for block in top_blocks:
            text_blocks.append(
                TextBlockLayout(
                    block=block.block,
                    visible=True,
                    text=block.text,
                    lines=block.lines,
                    font_size=block.font_size,
                    x=text_x,
                    y=cursor_y,
                    max_width=block.max_width,
                    line_gap=block.line_gap,
                    box_height=block.box_height,
                    max_lines=block.max_lines,
                    clamped=block.clamped,
                )
            )
            cursor_y += block.box_height + top_gap
        if has_ber_badge:
            ber_badge_box = BoxLayout(
                visible=True,
                x=top_panel.x + top_panel.width - panel_padding_x - ber_icon_width,
                y=top_panel.y + max(0, round((top_panel.height - ber_icon_height) / 2)),
                width=ber_icon_width,
                height=ber_icon_height,
            )

    agent_image_size = max(108, min(180, round(height * 0.085)))
    agent_lines = build_agent_lines(property_data)
    text_width = panel_width - agent_image_size - (panel_padding_x * 3)
    if text_width < 220:
        text_width = panel_width - (panel_padding_x * 2)
        agent_image_size = 0

    bottom_blocks: list[_MeasuredTextBlock] = []
    agent_name_text = agent_lines[0] if agent_lines else None
    for measured_block in (
        _measure_text_block(
            block="agent_name",
            text=agent_name_text,
            usable_width=text_width,
            max_lines=2,
            max_font_size=max(34, round(height * 0.024)),
            min_font_size=max(22, round(height * 0.016)),
            min_chars=14,
        ),
        *(
            _measure_text_block(
                block=block_name,
                text=block_text,
                usable_width=text_width,
                max_lines=2,
                max_font_size=max(26, round(height * 0.018)),
                min_font_size=18,
                min_chars=16,
            )
            for block_name, block_text in zip(
                ("agent_phone", "agent_email", "agency_psra"),
                agent_lines[1:4],
                strict=False,
            )
        ),
    ):
        if measured_block is None:
            continue
        bottom_blocks.append(measured_block)
        if measured_block.warning is not None:
            warnings.append(measured_block.warning)

    show_agent_panel = bool(bottom_blocks or agent_image_size > 0)
    bottom_panel: BoxLayout | None = None
    agent_image_box: BoxLayout | None = None
    if show_agent_panel:
        bottom_gap = max(6, round(height * 0.004))
        text_height = (
            sum(block.box_height for block in bottom_blocks)
            + (bottom_gap * (len(bottom_blocks) - 1 if bottom_blocks else 0))
        )
        bottom_min_height, bottom_max_height = _resolve_bottom_panel_height_range(settings)
        bottom_panel_height = min(
            bottom_max_height,
            max(bottom_min_height, max(text_height, agent_image_size) + (panel_padding_y * 2)),
        )
        bottom_panel = BoxLayout(
            visible=True,
            x=outer_margin_x,
            y=height - outer_margin_y - bottom_panel_height,
            width=panel_width,
            height=bottom_panel_height,
        )
        if agent_image_size > 0:
            agent_image_box = BoxLayout(
                visible=True,
                x=bottom_panel.x + panel_padding_x,
                y=bottom_panel.y + max(panel_padding_y, round((bottom_panel.height - agent_image_size) / 2)),
                width=agent_image_size,
                height=agent_image_size,
            )
        text_x = (
            bottom_panel.x + panel_padding_x
            if agent_image_box is None
            else agent_image_box.x + agent_image_box.width + panel_padding_x
        )
        cursor_y = bottom_panel.y + panel_padding_y
        for block in bottom_blocks:
            text_blocks.append(
                TextBlockLayout(
                    block=block.block,
                    visible=True,
                    text=block.text,
                    lines=block.lines,
                    font_size=block.font_size,
                    x=text_x,
                    y=cursor_y,
                    max_width=block.max_width,
                    line_gap=block.line_gap,
                    box_height=block.box_height,
                    max_lines=block.max_lines,
                    clamped=block.clamped,
                )
            )
            cursor_y += block.box_height + bottom_gap

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
        if settings.include_intro:
            intro_caption = normalize_caption(cover_caption if cover_caption is not None else slides[0].caption if slides else None, "")
            raw_segments.append((0.0, settings.intro_duration_seconds, intro_caption))
        slide_start_offset = settings.intro_duration_seconds
        for index, slide in enumerate(slides):
            raw_segments.append(
                (
                    slide_start_offset + (index * slide_duration),
                    slide_start_offset + ((index + 1) * slide_duration),
                    normalize_caption(slide.caption, ""),
                )
            )

        for start_time, end_time, caption_text in raw_segments:
            if not caption_text:
                continue
            measured_caption = _measure_text_block(
                block="subtitle_caption",
                text=caption_text,
                usable_width=subtitle_max_width,
                max_lines=3,
                max_font_size=settings.subtitle_font_size,
                min_font_size=max(24, round(settings.subtitle_font_size * 0.55)),
                min_chars=18,
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

    return OverlayLayout(
        frame_width=width,
        frame_height=height,
        top_panel=top_panel,
        bottom_panel=bottom_panel,
        agent_image_box=agent_image_box,
        ber_badge_box=ber_badge_box,
        text_blocks=tuple(text_blocks),
        subtitle_segments=tuple(subtitle_segments),
        warnings=tuple(warnings),
    )


__all__ = [
    "BoxLayout",
    "LayoutWarning",
    "OverlayLayout",
    "TextBlockLayout",
    "TimedTextSegmentLayout",
    "build_overlay_layout",
]
