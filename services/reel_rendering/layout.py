from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.ai_photo_selection.prompting import normalize_caption
from services.reel_rendering.formatting import (
    build_agent_lines,
    build_display_price,
    build_property_header_details_line,
    build_property_header_viewing_times_line,
    build_status_ribbon_text,
    build_similar_required_subtitle,
    clean_text,
    fit_wrapped_lines,
    resolve_agency_logo_box_size,
    resolve_agent_image_size,
    resolve_ber_icon_size,
    resolve_font_size_bounds,
)
from services.reel_rendering.models import PropertyReelData, PropertyReelSlide, PropertyReelTemplate


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
    return max(208, round(settings.height * 0.145)), max(500, round(settings.height * 0.34))


def _resolve_bottom_panel_y(
    *,
    frame_height: int,
    outer_margin_y: int,
    panel_height: int,
    footer_bottom_offset_px: int,
    top_panel: BoxLayout | None,
    vertical_gap: int,
) -> int:
    minimum_y = outer_margin_y
    if top_panel is not None:
        minimum_y = top_panel.y + top_panel.height + vertical_gap
    return max(
        minimum_y,
        frame_height - outer_margin_y - footer_bottom_offset_px - panel_height,
    )


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


def _build_measured_address_blocks(
    *,
    address_text: str | None,
    viewing_times_text: str | None,
    details_text: str | None,
    address_lines: tuple[str, ...],
    viewing_times_lines: tuple[str, ...],
    details_lines: tuple[str, ...],
    address_font_size: int,
    metadata_font_size: int,
    usable_width: int,
    max_lines: int,
    clamped: bool,
    warning: LayoutWarning | None,
) -> tuple[_MeasuredTextBlock, ...]:
    blocks: list[_MeasuredTextBlock] = []
    if address_lines:
        warning_target = "address"
    elif viewing_times_lines:
        warning_target = "viewing_times"
    else:
        warning_target = "address_meta"

    if address_lines:
        address_line_gap = address_font_size + max(8, round(address_font_size * 0.2))
        address_box_height = address_font_size + (
            (len(address_lines) - 1) * address_line_gap if len(address_lines) > 1 else 0
        )
        blocks.append(
            _MeasuredTextBlock(
                block="address",
                text=address_text or details_text or "",
                lines=address_lines,
                font_size=address_font_size,
                line_gap=address_line_gap,
                box_height=address_box_height,
                max_width=usable_width,
                max_lines=max_lines,
                clamped=clamped,
                warning=warning if warning is not None and warning_target == "address" else None,
            )
        )

    if viewing_times_lines:
        viewing_times_line_gap = metadata_font_size + max(8, round(metadata_font_size * 0.2))
        viewing_times_box_height = metadata_font_size + (
            (len(viewing_times_lines) - 1) * viewing_times_line_gap if len(viewing_times_lines) > 1 else 0
        )
        blocks.append(
            _MeasuredTextBlock(
                block="viewing_times",
                text=viewing_times_text or address_text or "",
                lines=viewing_times_lines,
                font_size=metadata_font_size,
                line_gap=viewing_times_line_gap,
                box_height=viewing_times_box_height,
                max_width=usable_width,
                max_lines=1,
                clamped=clamped,
                warning=warning if warning is not None and warning_target == "viewing_times" else None,
            )
        )

    if details_lines:
        details_line_gap = metadata_font_size + max(8, round(metadata_font_size * 0.2))
        details_box_height = metadata_font_size + (
            (len(details_lines) - 1) * details_line_gap if len(details_lines) > 1 else 0
        )
        blocks.append(
            _MeasuredTextBlock(
                block="address_meta",
                text=details_text or address_text or "",
                lines=details_lines,
                font_size=metadata_font_size,
                line_gap=details_line_gap,
                box_height=details_box_height,
                max_width=usable_width,
                max_lines=1,
                clamped=clamped,
                warning=warning if warning is not None and warning_target == "address_meta" else None,
            )
        )

    return tuple(blocks)


def _measure_address_blocks(
    *,
    address: str | None,
    viewing_times: str | None,
    details: str | None,
    usable_width: int,
    max_lines: int,
    max_font_size: int,
    min_font_size: int,
    min_chars: int,
) -> tuple[_MeasuredTextBlock, ...]:
    normalized_address = clean_text(address)
    normalized_viewing_times = clean_text(viewing_times)
    normalized_details = clean_text(details)
    if not normalized_address and not normalized_viewing_times and not normalized_details:
        return ()

    full_text = "\n".join(
        part
        for part in (normalized_address, normalized_viewing_times, normalized_details)
        if part
    )

    for address_font_size in _candidate_font_sizes(max_font_size, min_font_size):
        address_width_chars = _wrap_width_from_pixels(
            usable_width=usable_width,
            font_size=address_font_size,
            min_chars=min_chars,
        )
        metadata_font_size = address_font_size
        viewing_times_lines: tuple[str, ...] = ()
        details_lines: tuple[str, ...] = ()
        metadata_clamped = False
        reserved_metadata_lines = 0
        metadata_width_chars = _wrap_width_from_pixels(
            usable_width=usable_width,
            font_size=metadata_font_size,
            min_chars=max(12, min_chars - 4),
        )
        if normalized_viewing_times:
            wrapped_viewing_times = fit_wrapped_lines(
                normalized_viewing_times,
                width=metadata_width_chars,
                max_lines=1,
            )
            viewing_times_lines = wrapped_viewing_times.lines
            metadata_clamped = wrapped_viewing_times.clamped
            reserved_metadata_lines += len(viewing_times_lines) or 1
        if normalized_details:
            wrapped_details = fit_wrapped_lines(
                normalized_details,
                width=metadata_width_chars,
                max_lines=1,
            )
            details_lines = wrapped_details.lines
            metadata_clamped = metadata_clamped or wrapped_details.clamped
            reserved_metadata_lines += len(details_lines) or 1

        address_lines_allowed = max(1, max_lines - reserved_metadata_lines)
        wrapped_address = (
            fit_wrapped_lines(
                normalized_address,
                width=address_width_chars,
                max_lines=address_lines_allowed,
                rebalance_last_line=True,
            )
            if normalized_address
            else None
        )
        address_lines = () if wrapped_address is None else wrapped_address.lines
        clamped = metadata_clamped or (False if wrapped_address is None else wrapped_address.clamped)
        if not clamped:
            return _build_measured_address_blocks(
                address_text=normalized_address,
                viewing_times_text=normalized_viewing_times,
                details_text=normalized_details,
                address_lines=address_lines,
                viewing_times_lines=viewing_times_lines,
                details_lines=details_lines,
                address_font_size=address_font_size,
                metadata_font_size=metadata_font_size,
                usable_width=usable_width,
                max_lines=max_lines,
                clamped=False,
                warning=None,
            )

    min_size = min(max_font_size, max_font_size if max_font_size <= min_font_size else min_font_size)
    metadata_font_size = min_size
    address_width_chars = _wrap_width_from_pixels(
        usable_width=usable_width,
        font_size=min_size,
        min_chars=min_chars,
    )
    metadata_width_chars = _wrap_width_from_pixels(
        usable_width=usable_width,
        font_size=metadata_font_size,
        min_chars=max(12, min_chars - 4),
    )
    viewing_times_lines = ()
    details_lines = ()
    reserved_metadata_lines = 0
    if normalized_viewing_times:
        wrapped_viewing_times = fit_wrapped_lines(
            normalized_viewing_times,
            width=metadata_width_chars,
            max_lines=1,
        )
        viewing_times_lines = wrapped_viewing_times.lines
        reserved_metadata_lines += len(viewing_times_lines) or 1
    if normalized_details:
        wrapped_details = fit_wrapped_lines(
            normalized_details,
            width=metadata_width_chars,
            max_lines=1,
        )
        details_lines = wrapped_details.lines
        reserved_metadata_lines += len(details_lines) or 1
    address_lines_allowed = max(1, max_lines - reserved_metadata_lines)
    wrapped_address = (
        fit_wrapped_lines(
            normalized_address,
            width=address_width_chars,
            max_lines=address_lines_allowed,
            rebalance_last_line=True,
        )
        if normalized_address
        else None
    )
    address_lines = () if wrapped_address is None else wrapped_address.lines
    warning = LayoutWarning(
        code="TEXT_CLAMPED",
        block="address",
        message="address was clamped to fit within the reel overlay.",
        original_text=full_text,
    )
    return _build_measured_address_blocks(
        address_text=normalized_address,
        viewing_times_text=normalized_viewing_times,
        details_text=normalized_details,
        address_lines=address_lines,
        viewing_times_lines=viewing_times_lines,
        details_lines=details_lines,
        address_font_size=min_size,
        metadata_font_size=metadata_font_size,
        usable_width=usable_width,
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
    has_agency_logo: bool = False,
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
    ber_icon_width, ber_icon_height = resolve_ber_icon_size(settings)
    header_text_width = panel_width - (panel_padding_x * 2)
    if has_ber_badge:
        header_text_width = max(260, header_text_width - ber_icon_width - ber_icon_gap)

    address_max_font_size, address_min_font_size = resolve_font_size_bounds(
        "address",
        frame_height=height,
        subtitle_font_size=settings.subtitle_font_size,
    )

    top_blocks: list[_MeasuredTextBlock] = []
    for measured_block in (
        _measure_text_block(
            block="status",
            text=build_status_ribbon_text(property_data),
            usable_width=header_text_width,
            max_lines=2,
            max_font_size=resolve_font_size_bounds(
                "status",
                frame_height=height,
                subtitle_font_size=settings.subtitle_font_size,
            )[0],
            min_font_size=resolve_font_size_bounds(
                "status",
                frame_height=height,
                subtitle_font_size=settings.subtitle_font_size,
            )[1],
            min_chars=8,
        ),
        _measure_text_block(
            block="price",
            text=build_display_price(property_data),
            usable_width=header_text_width,
            max_lines=2,
            max_font_size=resolve_font_size_bounds(
                "price",
                frame_height=height,
                subtitle_font_size=settings.subtitle_font_size,
            )[0],
            min_font_size=resolve_font_size_bounds(
                "price",
                frame_height=height,
                subtitle_font_size=settings.subtitle_font_size,
            )[1],
            min_chars=8,
        ),
    ):
        if measured_block is None:
            continue
        top_blocks.append(measured_block)
        if measured_block.warning is not None:
            warnings.append(measured_block.warning)

    for measured_block in _measure_address_blocks(
        address=property_data.title,
        viewing_times=build_property_header_viewing_times_line(property_data),
        details=build_property_header_details_line(property_data),
        usable_width=header_text_width,
        max_lines=4,
        max_font_size=address_max_font_size,
        min_font_size=address_min_font_size,
        min_chars=18,
    ):
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

    agent_image_size = resolve_agent_image_size(settings)
    agent_lines = build_agent_lines(property_data)
    logo_box_width, logo_box_height = (
        resolve_agency_logo_box_size(settings) if has_agency_logo else (0, 0)
    )
    content_width = panel_width - (panel_padding_x * 2)
    minimum_text_width = max(220, round(width * 0.24))
    agent_gap = panel_padding_x if agent_image_size > 0 else 0
    logo_gap = panel_padding_x if has_agency_logo else 0
    text_width = content_width - agent_image_size - agent_gap - logo_box_width - logo_gap

    logo_min_width = max(72, round(width * 0.11)) if has_agency_logo else 0
    if has_agency_logo and text_width < minimum_text_width:
        reducible_logo_width = max(0, logo_box_width - logo_min_width)
        reduction = min(reducible_logo_width, minimum_text_width - text_width)
        logo_box_width -= reduction
        text_width += reduction

    agent_min_size = max(92, round(height * 0.07))
    if agent_image_size > 0 and text_width < minimum_text_width:
        reducible_agent_width = max(0, agent_image_size - agent_min_size)
        reduction = min(reducible_agent_width, minimum_text_width - text_width)
        agent_image_size -= reduction
        text_width += reduction

    if text_width < minimum_text_width and agent_image_size > 0:
        text_width += agent_image_size + agent_gap
        agent_image_size = 0
        agent_gap = 0

    if has_agency_logo and text_width < minimum_text_width:
        text_width += max(0, logo_box_width - logo_min_width)
        logo_box_width = logo_min_width

    text_width = max(180, text_width)

    bottom_blocks: list[_MeasuredTextBlock] = []
    agent_name_text = agent_lines[0] if agent_lines else None
    for measured_block in (
        _measure_text_block(
            block="agent_name",
            text=agent_name_text,
            usable_width=text_width,
            max_lines=2,
            max_font_size=resolve_font_size_bounds(
                "agent_name",
                frame_height=height,
                subtitle_font_size=settings.subtitle_font_size,
            )[0],
            min_font_size=resolve_font_size_bounds(
                "agent_name",
                frame_height=height,
                subtitle_font_size=settings.subtitle_font_size,
            )[1],
            min_chars=14,
        ),
        *(
            _measure_text_block(
                block=block_name,
                text=block_text,
                usable_width=text_width,
                max_lines=2,
                max_font_size=resolve_font_size_bounds(
                    block_name,
                    frame_height=height,
                    subtitle_font_size=settings.subtitle_font_size,
                )[0],
                min_font_size=resolve_font_size_bounds(
                    block_name,
                    frame_height=height,
                    subtitle_font_size=settings.subtitle_font_size,
                )[1],
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

    show_agent_panel = bool(bottom_blocks or agent_image_size > 0 or has_agency_logo)
    bottom_panel: BoxLayout | None = None
    agent_image_box: BoxLayout | None = None
    agency_logo_box: BoxLayout | None = None
    if show_agent_panel:
        bottom_gap = max(6, round(height * 0.004))
        text_height = (
            sum(block.box_height for block in bottom_blocks)
            + (bottom_gap * (len(bottom_blocks) - 1 if bottom_blocks else 0))
        )
        bottom_min_height, bottom_max_height = _resolve_bottom_panel_height_range(settings)
        bottom_panel_height = min(
            bottom_max_height,
            max(bottom_min_height, max(text_height, agent_image_size, logo_box_height) + (panel_padding_y * 2)),
        )
        bottom_panel = BoxLayout(
            visible=True,
            x=outer_margin_x,
            y=_resolve_bottom_panel_y(
                frame_height=height,
                outer_margin_y=outer_margin_y,
                panel_height=bottom_panel_height,
                footer_bottom_offset_px=max(0, settings.footer_bottom_offset_px),
                top_panel=top_panel,
                vertical_gap=max(panel_padding_y, round(height * 0.02)),
            ),
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
        if has_agency_logo and logo_box_width > 0 and logo_box_height > 0:
            agency_logo_box = BoxLayout(
                visible=True,
                x=bottom_panel.x + bottom_panel.width - panel_padding_x - logo_box_width,
                y=bottom_panel.y + max(panel_padding_y, round((bottom_panel.height - logo_box_height) / 2)),
                width=logo_box_width,
                height=logo_box_height,
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
            measured_caption = _measure_text_block(
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
        agency_logo_box=agency_logo_box,
        ber_badge_box=ber_badge_box,
        text_blocks=tuple(text_blocks),
        subtitle_segments=tuple(subtitle_segments),
        warnings=tuple(warnings),
    )


def _resolve_subtitle_caption(
    forced_subtitle: str | None,
    fallback_caption: str | None,
) -> str:
    if forced_subtitle is not None:
        return clean_text(forced_subtitle) or ""
    return normalize_caption(fallback_caption, "")


__all__ = [
    "BoxLayout",
    "LayoutWarning",
    "OverlayLayout",
    "TextBlockLayout",
    "TimedTextSegmentLayout",
    "build_overlay_layout",
]
