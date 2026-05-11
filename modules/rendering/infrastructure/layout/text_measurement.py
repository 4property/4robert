"""Pure typography measurement helpers for the property-reel overlay.

Extracted verbatim from `services.media.reel_rendering.layout` as part of
feature 15 (`rendering_layout_split`). The previously-private
`_MeasuredTextBlock`, `_measure_text_block` and `_measure_address_blocks`
become public so that `panels` and `subtitles` can consume them across
submodules; the remaining helpers stay private.

Note: imports from `services.media.reel_rendering.formatting` are a
transitional cross-frontier dependency removed by feature 18 when
`services/` is retired.
"""

from __future__ import annotations

from dataclasses import dataclass

from modules.rendering.infrastructure.layout.models import LayoutWarning
from modules.rendering.infrastructure.formatting import clean_text, fit_wrapped_lines


@dataclass(frozen=True, slots=True)
class MeasuredTextBlock:
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


def _wrap_width_from_pixels(
    *,
    usable_width: int,
    font_size: int,
    min_chars: int,
    char_width_floor: float = 12.0,
) -> int:
    usable_width = max(120, usable_width)
    average_character_width = max(char_width_floor, font_size * 0.58)
    return max(min_chars, round(usable_width / average_character_width))


def _estimate_line_width_pixels(
    line: str,
    *,
    font_size: int,
    char_width_floor: float,
) -> int:
    average_character_width = max(char_width_floor, font_size * 0.58)
    return round(len(line) * average_character_width)


def _lines_fit_within_width(
    lines: tuple[str, ...],
    *,
    usable_width: int,
    font_size: int,
    char_width_floor: float,
) -> bool:
    return all(
        _estimate_line_width_pixels(
            line,
            font_size=font_size,
            char_width_floor=char_width_floor,
        ) <= usable_width
        for line in lines
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


def measure_text_block(
    *,
    block: str,
    text: str | None,
    usable_width: int,
    max_lines: int,
    max_font_size: int,
    min_font_size: int,
    min_chars: int,
    char_width_floor: float = 12.0,
) -> MeasuredTextBlock | None:
    normalized_text = clean_text(text)
    if not normalized_text:
        return None

    for font_size in _candidate_font_sizes(max_font_size, min_font_size):
        width_chars = _wrap_width_from_pixels(
            usable_width=usable_width,
            font_size=font_size,
            min_chars=min_chars,
            char_width_floor=char_width_floor,
        )
        wrapped = fit_wrapped_lines(normalized_text, width=width_chars, max_lines=max_lines)
        if not _lines_fit_within_width(
            wrapped.lines,
            usable_width=usable_width,
            font_size=font_size,
            char_width_floor=char_width_floor,
        ) and width_chars > 1:
            wrapped = fit_wrapped_lines(
                normalized_text,
                width=max(1, width_chars - 1),
                max_lines=max_lines,
            )
        line_gap = font_size + max(8, round(font_size * 0.2))
        box_height = font_size + ((len(wrapped.lines) - 1) * line_gap if wrapped.lines else 0)
        if not wrapped.clamped and _lines_fit_within_width(
            wrapped.lines,
            usable_width=usable_width,
            font_size=font_size,
            char_width_floor=char_width_floor,
        ):
            return MeasuredTextBlock(
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
        char_width_floor=char_width_floor,
    )
    wrapped = fit_wrapped_lines(normalized_text, width=width_chars, max_lines=max_lines)
    if not _lines_fit_within_width(
        wrapped.lines,
        usable_width=usable_width,
        font_size=min_size,
        char_width_floor=char_width_floor,
    ) and wrapped.lines:
        wrapped = fit_wrapped_lines(
            normalized_text,
            width=max(min_chars, width_chars - 1),
            max_lines=max_lines,
        )
    line_gap = min_size + max(8, round(min_size * 0.2))
    box_height = min_size + ((len(wrapped.lines) - 1) * line_gap if wrapped.lines else 0)
    warning = LayoutWarning(
        code="TEXT_CLAMPED",
        block=block,
        message=f"{block} was clamped to fit within the reel overlay.",
        original_text=normalized_text,
    )
    return MeasuredTextBlock(
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


def _measure_text_block_with_single_line_preference(
    *,
    block: str,
    text: str | None,
    usable_width: int,
    preferred_min_chars: int,
    fallback_max_lines: int,
    max_font_size: int,
    min_font_size: int,
    fallback_min_chars: int,
    char_width_floor: float = 12.0,
) -> MeasuredTextBlock | None:
    single_line_block = measure_text_block(
        block=block,
        text=text,
        usable_width=usable_width,
        max_lines=1,
        max_font_size=max_font_size,
        min_font_size=min_font_size,
        min_chars=preferred_min_chars,
        char_width_floor=char_width_floor,
    )
    if single_line_block is not None and not single_line_block.clamped:
        return single_line_block
    return measure_text_block(
        block=block,
        text=text,
        usable_width=usable_width,
        max_lines=fallback_max_lines,
        max_font_size=max_font_size,
        min_font_size=min_font_size,
        min_chars=fallback_min_chars,
        char_width_floor=char_width_floor,
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
) -> tuple[MeasuredTextBlock, ...]:
    blocks: list[MeasuredTextBlock] = []
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
            MeasuredTextBlock(
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
            MeasuredTextBlock(
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
            MeasuredTextBlock(
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


def measure_address_blocks(
    *,
    address: str | None,
    viewing_times: str | None,
    details: str | None,
    usable_width: int,
    max_lines: int,
    max_font_size: int,
    min_font_size: int,
    min_chars: int,
) -> tuple[MeasuredTextBlock, ...]:
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
        address_fits = _lines_fit_within_width(
            address_lines,
            usable_width=usable_width,
            font_size=address_font_size,
            char_width_floor=12.0,
        )
        viewing_times_fit = _lines_fit_within_width(
            viewing_times_lines,
            usable_width=usable_width,
            font_size=metadata_font_size,
            char_width_floor=12.0,
        )
        details_fit = _lines_fit_within_width(
            details_lines,
            usable_width=usable_width,
            font_size=metadata_font_size,
            char_width_floor=12.0,
        )
        if not clamped and address_fits and viewing_times_fit and details_fit:
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


__all__ = [
    "MeasuredTextBlock",
    "measure_address_blocks",
    "measure_text_block",
]
