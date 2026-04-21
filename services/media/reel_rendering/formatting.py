from __future__ import annotations

import html
import textwrap
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from services.media.reel_rendering.models import PropertyRenderData, PropertyReelTemplate

_BER_ICON_ASPECT_RATIO = 1800 / 582
_BER_ICON_MIN_HEIGHT = 45
_BER_ICON_HEIGHT_RATIO = 0.0675

OVERLAY_TEXT_COLOR_PRIMARY = "white"
OVERLAY_TEXT_COLOR_SUBTITLE = "0xF4D03F"

OVERLAY_TEXT_COLORS: dict[str, str] = {
    "status": OVERLAY_TEXT_COLOR_PRIMARY,
    "price": OVERLAY_TEXT_COLOR_PRIMARY,
    "address": OVERLAY_TEXT_COLOR_PRIMARY,
    "agent_name": OVERLAY_TEXT_COLOR_PRIMARY,
    "agent_phone": OVERLAY_TEXT_COLOR_PRIMARY,
    "agent_email": OVERLAY_TEXT_COLOR_PRIMARY,
    "agency_psra": OVERLAY_TEXT_COLOR_PRIMARY,
    "subtitle_caption": OVERLAY_TEXT_COLOR_SUBTITLE,
}

_PROPERTY_SIZE_NUMERIC_PATTERN = re.compile(r"^\d+(?:[.,]\d+)?$")
_NORMALIZED_STATUS_PATTERN = re.compile(r"[\s_-]+")
_SIMILAR_REQUIRED_STATUSES = frozenset({"sale agreed", "let agreed", "sold", "let"})
_HTML_BREAK_PATTERN = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_PROPERTY_SIZE_WITH_UNIT_PATTERN = re.compile(
    r"^(?P<value>\d+(?:[.,]\d+)?)\s*(?:m²|mÂ²|m2|sqm|sq\.?\s*m)$",
    re.IGNORECASE,
)

OVERLAY_FONT_SIZE_RULES: dict[str, tuple[float, int, float, int]] = {
    "status": (0.050, 68, 0.026, 34),
    "price": (0.046, 62, 0.024, 32),
    "address": (0.024, 32, 0.0, 22),
    "agent_name": (0.026, 38, 0.017, 24),
    "agent_phone": (0.020, 29, 0.0, 19),
    "agent_email": (0.020, 29, 0.0, 19),
    "agency_psra": (0.020, 29, 0.0, 19),
}


def escape_drawtext_text(value: str) -> str:
    sanitized = (
        value.replace("\r\n", " ")
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("\t", " ")
        .replace("'", "\u2019")
        .replace("`", "\u2019")
    )
    return (
        sanitized.replace("\\", "\\\\")
        .replace(":", r"\:")
        .replace(",", r"\,")
        .replace(";", r"\;")
        .replace("%", r"\%")
    )


def escape_filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", r"\:")


def resolve_text_color(block: str) -> str:
    return OVERLAY_TEXT_COLORS.get(block, OVERLAY_TEXT_COLOR_PRIMARY)


def resolve_font_size_bounds(
    block: str,
    *,
    frame_height: int,
    subtitle_font_size: int,
) -> tuple[int, int]:
    if block == "subtitle_caption":
        return subtitle_font_size, max(24, round(subtitle_font_size * 0.55))

    max_ratio, max_floor, min_ratio, min_floor = OVERLAY_FONT_SIZE_RULES.get(
        block,
        OVERLAY_FONT_SIZE_RULES["address"],
    )
    max_size = max(max_floor, round(frame_height * max_ratio))
    min_size = min_floor if min_ratio <= 0 else max(min_floor, round(frame_height * min_ratio))
    return max_size, min_size


def resolve_agent_image_size(settings: PropertyReelTemplate) -> int:
    return max(120, min(196, round(settings.height * 0.094)))


def resolve_ber_icon_size(settings: PropertyReelTemplate) -> tuple[int, int]:
    base_height = max(_BER_ICON_MIN_HEIGHT, round(settings.height * _BER_ICON_HEIGHT_RATIO))
    icon_height = max(1, round(base_height * settings.ber_icon_scale))
    icon_width = max(1, round(icon_height * _BER_ICON_ASPECT_RATIO))
    return icon_width, icon_height


def resolve_agency_logo_box_size(settings: PropertyReelTemplate) -> tuple[int, int]:
    base_width = max(96, round(settings.width * 0.18))
    base_height = max(62, round(settings.height * 0.058))
    return (
        max(1, round(base_width * settings.agency_logo_scale)),
        max(1, round(base_height * settings.agency_logo_scale)),
    )


def format_price(value: str | None) -> str | None:
    if value is None:
        return None

    compact_value = value.replace(",", "").strip()
    if not compact_value:
        return None

    try:
        amount = int(float(compact_value))
    except ValueError:
        return value.strip()

    return f"\u20ac{amount:,}"


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def format_property_size(value: str | None) -> str | None:
    normalized = clean_text(value)
    if not normalized:
        return None

    compact = re.sub(r"\s+", " ", normalized)
    unit_match = _PROPERTY_SIZE_WITH_UNIT_PATTERN.fullmatch(compact)
    if unit_match is not None:
        return _format_square_meter_value(unit_match.group("value"))

    compact_numeric = compact.replace(",", ".")
    if _PROPERTY_SIZE_NUMERIC_PATTERN.fullmatch(compact_numeric):
        return _format_square_meter_value(compact_numeric)

    return compact


def format_property_size_header(value: str | None) -> str | None:
    normalized = clean_text(value)
    if not normalized:
        return None

    compact = re.sub(r"\s+", " ", normalized)
    unit_match = _PROPERTY_SIZE_WITH_UNIT_PATTERN.fullmatch(compact)
    if unit_match is not None:
        return _format_square_meter_header_value(unit_match.group("value"))

    compact_numeric = compact.replace(",", ".")
    if _PROPERTY_SIZE_NUMERIC_PATTERN.fullmatch(compact_numeric):
        return _format_square_meter_header_value(compact_numeric)

    return compact.replace(" ", "")


def _format_square_meter_value(value: str) -> str:
    try:
        numeric_value = float(value)
    except ValueError:
        return value
    if numeric_value.is_integer():
        return f"{int(numeric_value)} m²"
    return f"{numeric_value:g} m²"


def _format_square_meter_header_value(value: str) -> str:
    try:
        numeric_value = float(value)
    except ValueError:
        return value
    if numeric_value.is_integer():
        return f"{int(numeric_value)}m²"
    return f"{numeric_value:g}m²"


@dataclass(frozen=True, slots=True)
class WrappedTextResult:
    lines: tuple[str, ...]
    clamped: bool


def _rebalance_wrapped_lines(lines: list[str], *, width: int) -> tuple[str, ...]:
    if len(lines) < 2:
        return tuple(lines)

    last_words = lines[-1].split()
    if len(last_words) != 1:
        return tuple(lines)

    previous_words = lines[-2].split()
    if len(previous_words) <= 1:
        return tuple(lines)

    best_previous = lines[-2]
    best_last = lines[-1]
    best_difference = abs(len(best_previous) - len(best_last))
    moved_words = list(last_words)
    remaining_words = previous_words[:]

    while len(remaining_words) > 1:
        moved_words.insert(0, remaining_words.pop())
        candidate_last = " ".join(moved_words)
        if len(candidate_last) > width:
            break

        candidate_previous = " ".join(remaining_words)
        candidate_difference = abs(len(candidate_previous) - len(candidate_last))
        if candidate_difference <= best_difference:
            best_previous = candidate_previous
            best_last = candidate_last
            best_difference = candidate_difference

    if best_previous == lines[-2]:
        return tuple(lines)

    rebalanced_lines = list(lines)
    rebalanced_lines[-2] = best_previous
    rebalanced_lines[-1] = best_last
    return tuple(rebalanced_lines)


def fit_wrapped_lines(
    value: str | None,
    *,
    width: int,
    max_lines: int,
    rebalance_last_line: bool = False,
) -> WrappedTextResult:
    if not value:
        return WrappedTextResult(lines=(), clamped=False)

    wrapped = textwrap.wrap(value, width=width)
    if not wrapped:
        return WrappedTextResult(lines=(), clamped=False)
    if len(wrapped) <= max_lines:
        lines = (
            _rebalance_wrapped_lines(wrapped, width=width)
            if rebalance_last_line
            else tuple(wrapped)
        )
        return WrappedTextResult(lines=lines, clamped=False)

    lines = wrapped[: max_lines - 1]
    remaining = " ".join(wrapped[max_lines - 1 :])
    lines.append(textwrap.shorten(remaining, width=width, placeholder="..."))
    return WrappedTextResult(lines=tuple(lines), clamped=True)


def wrap_lines(
    value: str | None,
    *,
    width: int,
    max_lines: int,
    rebalance_last_line: bool = False,
) -> list[str]:
    return list(
        fit_wrapped_lines(
            value,
            width=width,
            max_lines=max_lines,
            rebalance_last_line=rebalance_last_line,
        ).lines
    )


def _normalize_positive_count(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        numeric_value = int(value)
    except (TypeError, ValueError):
        return None
    if numeric_value <= 0:
        return None
    return numeric_value


def build_property_header_details_line(property_data: PropertyRenderData) -> str | None:
    facts: list[str] = []

    property_size = format_property_size_header(property_data.property_size)
    if property_size:
        facts.append(property_size)

    bedrooms = _normalize_positive_count(property_data.bedrooms)
    if bedrooms is not None:
        bedroom_label = "bed" if bedrooms == 1 else "beds"
        facts.append(f"{bedrooms} {bedroom_label}")

    bathrooms = _normalize_positive_count(property_data.bathrooms)
    if bathrooms is not None:
        bathroom_label = "bath" if bathrooms == 1 else "baths"
        facts.append(f"{bathrooms} {bathroom_label}")

    if not facts:
        return None
    return " | ".join(facts)


def format_viewing_times(values: tuple[str, ...] | list[str] | None) -> str | None:
    if not values:
        return None

    normalized_items: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        normalized_value = clean_text(raw_value)
        if not normalized_value:
            continue

        text = _HTML_BREAK_PATTERN.sub(" | ", normalized_value)
        text = _HTML_TAG_PATTERN.sub(" ", text)
        text = html.unescape(text)
        for part in text.split("|"):
            cleaned_part = re.sub(r"\s+", " ", part).strip(" ,;")
            if not cleaned_part:
                continue
            lowered = cleaned_part.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            normalized_items.append(cleaned_part)

    if not normalized_items:
        return None
    return " | ".join(normalized_items)


def build_property_header_viewing_times_line(property_data: PropertyRenderData) -> str | None:
    return format_viewing_times(property_data.viewing_times)


def build_property_facts_line(property_data: PropertyRenderData) -> str:
    facts: list[str] = []
    if property_data.bedrooms is not None:
        facts.append(f"{property_data.bedrooms} bed")
    if property_data.bathrooms is not None:
        facts.append(f"{property_data.bathrooms} bath")
    if property_data.property_type_label:
        facts.append(property_data.property_type_label)

    location_parts = [
        part
        for part in (
            property_data.property_area_label,
            property_data.property_county_label,
            property_data.eircode,
        )
        if part
    ]
    if location_parts:
        facts.append(", ".join(location_parts))

    return " | ".join(facts)


def build_property_overlay_facts_line(property_data: PropertyRenderData) -> str:
    facts: list[str] = []
    if property_data.bedrooms is not None:
        facts.append(f"{property_data.bedrooms} bed")
    if property_data.bathrooms is not None:
        facts.append(f"{property_data.bathrooms} bath")
    if property_data.ber_rating:
        facts.append(f"BER {property_data.ber_rating}")
    return " | ".join(facts)


def build_agent_lines(property_data: PropertyRenderData) -> list[str]:
    lines: list[str] = []
    if property_data.agent_name:
        lines.append(property_data.agent_name)

    phone_number = property_data.agent_mobile or property_data.agent_number
    if phone_number:
        lines.append(phone_number)
    if property_data.agent_email:
        lines.append(property_data.agent_email)
    return lines


def build_status_ribbon_text(property_data: PropertyRenderData) -> str | None:
    status = clean_text(property_data.banner_text) or clean_text(property_data.property_status)
    if not status:
        return None
    return status.upper()


def build_similar_required_subtitle(property_data: PropertyRenderData) -> str | None:
    normalized_status = _normalize_listing_status(property_data.property_status)
    if normalized_status not in _SIMILAR_REQUIRED_STATUSES:
        return None

    site_url = _extract_site_display_url(property_data.link) or clean_text(property_data.site_id)
    if not site_url:
        return None
    return f"Similar required? {site_url}"


def build_display_price(property_data: PropertyRenderData) -> str | None:
    if property_data.price_display_text is not None:
        return clean_text(property_data.price_display_text)
    return format_price(property_data.price)


def _normalize_listing_status(value: str | None) -> str:
    cleaned_value = clean_text(value)
    if not cleaned_value:
        return ""
    return _NORMALIZED_STATUS_PATTERN.sub(" ", cleaned_value.lower()).strip()


def _extract_site_display_url(url: str | None) -> str | None:
    cleaned_url = clean_text(url)
    if not cleaned_url:
        return None
    text = cleaned_url.removeprefix("http://").removeprefix("https://")
    host, _, _ = text.partition("/")
    return host or text


__all__ = [
    "OVERLAY_FONT_SIZE_RULES",
    "OVERLAY_TEXT_COLORS",
    "OVERLAY_TEXT_COLOR_PRIMARY",
    "OVERLAY_TEXT_COLOR_SUBTITLE",
    "WrappedTextResult",
    "build_agent_lines",
    "build_display_price",
    "build_property_header_details_line",
    "build_property_header_viewing_times_line",
    "build_property_facts_line",
    "build_property_overlay_facts_line",
    "build_similar_required_subtitle",
    "build_status_ribbon_text",
    "clean_text",
    "escape_drawtext_text",
    "escape_filter_path",
    "fit_wrapped_lines",
    "format_price",
    "format_property_size_header",
    "format_property_size",
    "format_viewing_times",
    "resolve_agency_logo_box_size",
    "resolve_agent_image_size",
    "resolve_ber_icon_size",
    "resolve_font_size_bounds",
    "resolve_text_color",
    "wrap_lines",
]
