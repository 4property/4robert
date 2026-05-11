"""Dataclass value objects for the property-reel overlay layout.

Extracted verbatim from `services.media.reel_rendering.layout` as part of
feature 15 (`rendering_layout_split`). These dataclasses are the public DTO
surface consumed by `filters`, `poster`, `manifest`, `preparation` and the
ffmpeg renderers.
"""

from __future__ import annotations

from dataclasses import dataclass


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
    agency_logo_box: BoxLayout | None
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
            "agency_logo_box": None if self.agency_logo_box is None else self.agency_logo_box.to_dict(),
            "ber_badge_box": None if self.ber_badge_box is None else self.ber_badge_box.to_dict(),
            "text_blocks": [block.to_dict() for block in self.text_blocks],
            "subtitle_segments": [segment.to_dict() for segment in self.subtitle_segments],
            "warnings": [warning.to_dict() for warning in self.warnings],
        }


__all__ = [
    "BoxLayout",
    "LayoutWarning",
    "OverlayLayout",
    "TextBlockLayout",
    "TimedTextSegmentLayout",
]
