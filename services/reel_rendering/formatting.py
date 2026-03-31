from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.reel_rendering.models import PropertyRenderData


def escape_drawtext_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace(",", r"\,")
        .replace("%", r"\%")
    )


def escape_filter_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(":", r"\:")


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


@dataclass(frozen=True, slots=True)
class WrappedTextResult:
    lines: tuple[str, ...]
    clamped: bool


def fit_wrapped_lines(value: str | None, *, width: int, max_lines: int) -> WrappedTextResult:
    if not value:
        return WrappedTextResult(lines=(), clamped=False)

    wrapped = textwrap.wrap(value, width=width)
    if not wrapped:
        return WrappedTextResult(lines=(), clamped=False)
    if len(wrapped) <= max_lines:
        return WrappedTextResult(lines=tuple(wrapped), clamped=False)

    lines = wrapped[: max_lines - 1]
    remaining = " ".join(wrapped[max_lines - 1 :])
    lines.append(textwrap.shorten(remaining, width=width, placeholder="..."))
    return WrappedTextResult(lines=tuple(lines), clamped=True)


def wrap_lines(value: str | None, *, width: int, max_lines: int) -> list[str]:
    return list(fit_wrapped_lines(value, width=width, max_lines=max_lines).lines)


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


def build_display_price(property_data: PropertyRenderData) -> str | None:
    if property_data.price_display_text is not None:
        return clean_text(property_data.price_display_text)
    return format_price(property_data.price)


__all__ = [
    "WrappedTextResult",
    "build_agent_lines",
    "build_display_price",
    "build_property_facts_line",
    "build_property_overlay_facts_line",
    "build_status_ribbon_text",
    "clean_text",
    "escape_drawtext_text",
    "escape_filter_path",
    "fit_wrapped_lines",
    "format_price",
    "wrap_lines",
]
