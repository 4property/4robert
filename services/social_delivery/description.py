from __future__ import annotations

import textwrap
from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from models.property import Property
from repositories.property_pipeline_repository import PropertyReelRecord
from services.reel_rendering.formatting import format_price

TIKTOK_MAX_DESCRIPTION_LENGTH = 150


def build_property_public_url(
    *,
    site_id: str,
    slug: str,
    property_link: str | None,
    property_url_template: str,
    tracking_query_params: Mapping[str, str] | None = None,
) -> str:
    base_url = (
        property_link
        if property_link and property_link.startswith(("http://", "https://"))
        else property_url_template.format(site_id=site_id, slug=slug)
    )
    return _apply_tracking_query_params(
        base_url,
        site_id=site_id,
        slug=slug,
        tracking_query_params=tracking_query_params,
    )


def build_tiktok_description(
    *,
    site_id: str,
    slug: str,
    title: str | None = None,
    price: str | None = None,
    bedrooms: int | None = None,
    bathrooms: int | None = None,
    ber_rating: str | None = None,
    property_status: str | None = None,
    agent_name: str | None = None,
    agent_email: str | None = None,
    agent_mobile: str | None = None,
    agent_number: str | None = None,
    property_link: str | None,
    property_url_template: str,
    tracking_query_params: Mapping[str, str] | None = None,
    max_length: int = TIKTOK_MAX_DESCRIPTION_LENGTH,
) -> str:
    del agent_name, agent_email, agent_mobile, agent_number

    property_url = build_property_public_url(
        site_id=site_id,
        slug=slug,
        property_link=property_link,
        property_url_template=property_url_template,
        tracking_query_params=tracking_query_params,
    )
    address = _build_property_address(title=title, fallback_slug=slug)
    full_stats_line = _build_property_stats_line(
        price=price,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        ber_rating=ber_rating,
    )
    compact_stats_line = _build_property_stats_line(
        price=price,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        ber_rating=ber_rating,
        compact=True,
    )
    minimal_stats_line = _build_property_stats_line(
        price=price,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        ber_rating=None,
        compact=True,
    )
    status_line = _build_status_line(property_status)

    address_variants = _build_address_variants(address)
    stats_variants = _unique_preserving_order(
        [
            full_stats_line,
            compact_stats_line,
            minimal_stats_line,
            None,
        ]
    )
    status_variants = _unique_preserving_order([status_line, None])
    cta_variants = ("View property:", "Website:", None)

    best_candidate = ""
    best_score: tuple[int, int, int, int, int, int, int, int, int] | None = None

    for cta_index, cta_line in enumerate(cta_variants):
        for status_index, selected_status in enumerate(status_variants):
            for address_index, address_line in enumerate(address_variants):
                for stats_index, stats_line in enumerate(stats_variants):
                    candidate = _join_lines(
                        [
                            selected_status,
                            address_line,
                            stats_line,
                            cta_line,
                            property_url,
                        ]
                    )
                    if not candidate or len(candidate) > max_length:
                        continue

                    score = (
                        1 if cta_line else 0,
                        len(cta_variants) - cta_index if cta_line else 0,
                        1 if selected_status else 0,
                        len(status_variants) - status_index if selected_status else 0,
                        1 if address_line else 0,
                        len(address_variants) - address_index if address_line else 0,
                        1 if stats_line else 0,
                        len(stats_variants) - stats_index if stats_line else 0,
                        len(candidate),
                    )
                    if best_score is None or score > best_score:
                        best_candidate = candidate
                        best_score = score

    if best_candidate:
        return best_candidate

    return property_url


def build_tiktok_description_for_property(
    property_item: Property,
    *,
    site_id: str,
    property_url_template: str,
    tracking_query_params: Mapping[str, str] | None = None,
    max_length: int = TIKTOK_MAX_DESCRIPTION_LENGTH,
) -> str:
    return build_tiktok_description(
        site_id=site_id,
        slug=property_item.slug,
        title=property_item.title,
        price=property_item.price,
        bedrooms=property_item.bedrooms,
        bathrooms=property_item.bathrooms,
        ber_rating=property_item.ber_rating,
        property_status=property_item.property_status,
        agent_name=property_item.agent_name,
        agent_email=property_item.agent_email,
        agent_mobile=property_item.agent_mobile,
        agent_number=property_item.agent_number,
        property_link=property_item.link,
        property_url_template=property_url_template,
        tracking_query_params=tracking_query_params,
        max_length=max_length,
    )


def build_tiktok_description_for_record(
    record: PropertyReelRecord,
    *,
    property_url_template: str,
    tracking_query_params: Mapping[str, str] | None = None,
    max_length: int = TIKTOK_MAX_DESCRIPTION_LENGTH,
) -> str:
    return build_tiktok_description(
        site_id=record.site_id,
        slug=record.slug,
        title=record.title,
        price=record.price,
        bedrooms=record.bedrooms,
        bathrooms=record.bathrooms,
        ber_rating=record.ber_rating,
        property_status=record.property_status,
        agent_name=record.agent_name,
        agent_email=record.agent_email,
        agent_mobile=record.agent_mobile,
        agent_number=record.agent_number,
        property_link=record.link,
        property_url_template=property_url_template,
        tracking_query_params=tracking_query_params,
        max_length=max_length,
    )


def _build_property_address(*, title: str | None, fallback_slug: str) -> str:
    cleaned_title = _clean_text(title)
    if cleaned_title:
        return cleaned_title
    return fallback_slug.replace("-", " ").strip()


def _build_property_stats_line(
    *,
    price: str | None,
    bedrooms: int | None,
    bathrooms: int | None,
    ber_rating: str | None,
    compact: bool = False,
) -> str | None:
    parts: list[str] = []
    formatted_price = format_price(price)
    if formatted_price:
        parts.append(formatted_price)
    if bedrooms is not None:
        parts.append(f"{bedrooms}bd" if compact else f"{bedrooms} bed")
    if bathrooms is not None:
        parts.append(f"{bathrooms}ba" if compact else f"{bathrooms} bath")
    cleaned_ber_rating = _clean_text(ber_rating)
    if cleaned_ber_rating:
        parts.append(f"BER {cleaned_ber_rating}")
    if not parts:
        return None
    return " | ".join(parts)


def _build_address_variants(address: str) -> tuple[str | None, ...]:
    return _unique_preserving_order(
        [
            address,
            _shorten_text(address, 64),
            _shorten_text(address, 52),
            _shorten_text(address, 40),
            None,
        ]
    )


def _build_status_line(property_status: str | None) -> str | None:
    cleaned_status = _clean_text(property_status)
    if not cleaned_status:
        return None
    return cleaned_status.upper()


def _apply_tracking_query_params(
    url: str,
    *,
    site_id: str,
    slug: str,
    tracking_query_params: Mapping[str, str] | None,
) -> str:
    if not tracking_query_params:
        return url

    parsed_url = urlsplit(url)
    merged_query_items = [
        (key, value)
        for key, value in parse_qsl(parsed_url.query, keep_blank_values=True)
        if _clean_text(key) is not None
    ]
    for raw_key, raw_value in tracking_query_params.items():
        key = _clean_text(str(raw_key))
        value = _clean_text(str(raw_value))
        if key is None or value is None:
            continue
        formatted_value = _expand_tracking_value(
            value,
            site_id=site_id,
            slug=slug,
        )
        merged_query_items = [(existing_key, existing_value) for existing_key, existing_value in merged_query_items if existing_key != key]
        merged_query_items.append((key, formatted_value))

    return urlunsplit(
        (
            parsed_url.scheme,
            parsed_url.netloc,
            parsed_url.path,
            urlencode(merged_query_items, doseq=True),
            parsed_url.fragment,
        )
    )


def _expand_tracking_value(value: str, *, site_id: str, slug: str) -> str:
    return value.replace("{site_id}", site_id).replace("{slug}", slug)


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned_value = value.strip()
    return cleaned_value or None


def _join_lines(lines: list[str | None]) -> str:
    return "\n".join(line for line in lines if line)


def _shorten_text(value: str | None, max_length: int) -> str | None:
    cleaned_value = _clean_text(value)
    if not cleaned_value:
        return None
    if len(cleaned_value) <= max_length:
        return cleaned_value
    return textwrap.shorten(cleaned_value, width=max_length, placeholder="...")


def _unique_preserving_order(values: list[str | None] | list[tuple[str | None, ...]]) -> tuple:
    unique_values: list[object] = []
    seen: set[object] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique_values.append(value)
    return tuple(unique_values)


__all__ = [
    "TIKTOK_MAX_DESCRIPTION_LENGTH",
    "build_property_public_url",
    "build_tiktok_description",
    "build_tiktok_description_for_property",
    "build_tiktok_description_for_record",
]

