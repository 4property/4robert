from __future__ import annotations

import textwrap
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


def wrap_lines(value: str | None, *, width: int, max_lines: int) -> list[str]:
    if not value:
        return []

    wrapped = textwrap.wrap(value, width=width)
    if not wrapped:
        return []
    if len(wrapped) <= max_lines:
        return wrapped

    lines = wrapped[: max_lines - 1]
    remaining = " ".join(wrapped[max_lines - 1 :])
    lines.append(textwrap.shorten(remaining, width=width, placeholder="..."))
    return lines


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

    contact_parts = [
        part
        for part in (
            property_data.agent_mobile or property_data.agent_number,
            property_data.agent_email,
        )
        if part
    ]
    if contact_parts:
        lines.append(" | ".join(contact_parts))

    if not lines:
        lines.append("Agent details unavailable")
    return lines


def build_status_ribbon_text(property_data: PropertyRenderData) -> str | None:
    status = clean_text(property_data.property_status)
    if not status:
        return None
    normalized = status.upper()
    if len(normalized) <= 18:
        return normalized
    return textwrap.shorten(normalized, width=18, placeholder="...")


__all__ = [
    "build_agent_lines",
    "build_property_facts_line",
    "build_property_overlay_facts_line",
    "build_status_ribbon_text",
    "clean_text",
    "escape_drawtext_text",
    "escape_filter_path",
    "format_price",
    "wrap_lines",
]

