"""Internal helpers for ``Property``: text/int coercion and serialization.

Kept out of ``wordpress_property.py`` so the main aggregate file stays under
the ~500 LoC guideline. The helpers are private to the catalog domain
package; importers should reach for ``Property`` (and its methods) instead
of these primitives.
"""

from __future__ import annotations

import json
import re
import zlib
from typing import Any, Mapping


_SLUG_INVALID_CHARS_RE = re.compile(r"[^a-z0-9-]+")
_MULTIPLE_DASHES_RE = re.compile(r"-{2,}")


def json_safe_copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except TypeError:
        return value


def to_text(value: Any) -> str | None:
    if value is None:
        return None

    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None

    if isinstance(value, bool):
        return "true" if value else "false"

    if isinstance(value, int | float):
        return str(value)

    return json.dumps(value, ensure_ascii=False, default=str)


def to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None

    if isinstance(value, bool):
        return int(value)

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return int(value)

    text = to_text(value)
    if text is None:
        return None

    try:
        return int(float(text.replace(",", "")))
    except ValueError:
        return None


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None

    if isinstance(value, bool):
        return float(int(value))

    if isinstance(value, int | float):
        return float(value)

    text = to_text(value)
    if text is None:
        return None

    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def extract_rendered_text(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return to_text(value.get("rendered"))
    return to_text(value)


def to_text_tuple(value: Any, *, split_pipes: bool = False) -> tuple[str, ...]:
    if value is None or value == "":
        return ()

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if parsed is not None:
                return to_text_tuple(parsed, split_pipes=split_pipes)
        if split_pipes and "|" in text:
            return tuple(
                segment
                for segment in (part.strip() for part in text.split("|"))
                if segment
            )
        return (text,)

    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for item in value:
            items.extend(to_text_tuple(item, split_pipes=split_pipes))
        return tuple(items)

    text = to_text(value)
    return (text,) if text else ()


def to_int_tuple(value: Any) -> tuple[int, ...]:
    if value is None or value == "":
        return ()

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if parsed is not None:
                return to_int_tuple(parsed)

    if isinstance(value, (list, tuple, set)):
        items: list[int] = []
        for item in value:
            integer = to_int(item)
            if integer is not None:
                items.append(integer)
        return tuple(items)

    integer = to_int(value)
    return (integer,) if integer is not None else ()


def to_serialised_text(value: Any) -> str | None:
    if value is None or value == "" or value == [] or value == {} or value == ():
        return None

    if isinstance(value, Mapping | list | tuple | set):
        safe_value = json_safe_copy(value)
        if safe_value in (None, "", [], {}, ()):
            return None
        return json.dumps(safe_value, ensure_ascii=False, sort_keys=True)

    return to_text(value)


def sequence_to_json(values: tuple[Any, ...]) -> str | None:
    if not values:
        return None
    return json.dumps(list(values), ensure_ascii=False)


def normalise_slug(candidate: Any, fallback_seed: Any) -> str:
    base_slug = to_text(candidate) or f"property-{fallback_seed}"
    normalised = base_slug.lower().replace("_", "-")
    normalised = _SLUG_INVALID_CHARS_RE.sub("-", normalised)
    normalised = _MULTIPLE_DASHES_RE.sub("-", normalised).strip("-")
    if normalised:
        return normalised

    crc32 = zlib.crc32(str(fallback_seed).encode("utf-8")) & 0xFFFFFFFF
    return f"property-{crc32}"


def build_property_db_record(property_item: object, *, image_folder: str, fetched_at: str) -> dict[str, Any]:
    p = property_item
    return {
        "source_property_id": p.id,  # type: ignore[attr-defined]
        "slug": p.slug,  # type: ignore[attr-defined]
        "title": p.title,  # type: ignore[attr-defined]
        "link": p.link,  # type: ignore[attr-defined]
        "guid": p.guid,  # type: ignore[attr-defined]
        "status": p.status,  # type: ignore[attr-defined]
        "resource_type": p.resource_type,  # type: ignore[attr-defined]
        "author_id": p.author_id,  # type: ignore[attr-defined]
        "importer_id": p.importer_id,  # type: ignore[attr-defined]
        "list_reference": p.list_reference,  # type: ignore[attr-defined]
        "date": p.date,  # type: ignore[attr-defined]
        "date_gmt": p.date_gmt,  # type: ignore[attr-defined]
        "modified": p.modified,  # type: ignore[attr-defined]
        "modified_gmt": p.modified_gmt,  # type: ignore[attr-defined]
        "excerpt_html": p.excerpt_html,  # type: ignore[attr-defined]
        "content_html": p.content_html,  # type: ignore[attr-defined]
        "price": p.price,  # type: ignore[attr-defined]
        "price_sold": p.price_sold,  # type: ignore[attr-defined]
        "price_term": p.price_term,  # type: ignore[attr-defined]
        "property_status": p.property_status,  # type: ignore[attr-defined]
        "property_market": p.property_market,  # type: ignore[attr-defined]
        "property_type_label": p.property_type_label,  # type: ignore[attr-defined]
        "property_county_label": p.property_county_label,  # type: ignore[attr-defined]
        "property_area_label": p.property_area_label,  # type: ignore[attr-defined]
        "property_size": p.property_size,  # type: ignore[attr-defined]
        "property_land_size": p.property_land_size,  # type: ignore[attr-defined]
        "property_accommodation": p.property_accommodation,  # type: ignore[attr-defined]
        "property_disclaimer": p.property_disclaimer,  # type: ignore[attr-defined]
        "bedrooms": p.bedrooms,  # type: ignore[attr-defined]
        "bathrooms": p.bathrooms,  # type: ignore[attr-defined]
        "ber_rating": p.ber_rating,  # type: ignore[attr-defined]
        "ber_number": p.ber_number,  # type: ignore[attr-defined]
        "energy_details": p.energy_details,  # type: ignore[attr-defined]
        "bidding_method": p.bidding_method,  # type: ignore[attr-defined]
        "living_type": p.living_type,  # type: ignore[attr-defined]
        "country": p.country,  # type: ignore[attr-defined]
        "eircode": p.eircode,  # type: ignore[attr-defined]
        "directions": p.directions,  # type: ignore[attr-defined]
        "latitude": p.latitude,  # type: ignore[attr-defined]
        "longitude": p.longitude,  # type: ignore[attr-defined]
        "agent_name": p.agent_name,  # type: ignore[attr-defined]
        "agent_photo_url": p.agent_photo_url,  # type: ignore[attr-defined]
        "agent_email": p.agent_email,  # type: ignore[attr-defined]
        "agent_mobile": p.agent_mobile,  # type: ignore[attr-defined]
        "agent_number": p.agent_number,  # type: ignore[attr-defined]
        "agent_qualification": p.agent_qualification,  # type: ignore[attr-defined]
        "agency_psra": p.agency_psra,  # type: ignore[attr-defined]
        "agency_logo_url": p.agency_logo_url,  # type: ignore[attr-defined]
        "featured_media_id": p.featured_media_id,  # type: ignore[attr-defined]
        "featured_image_url": p.featured_image_url,  # type: ignore[attr-defined]
        "amenities": p.amenities,  # type: ignore[attr-defined]
        "property_order": p.property_order,  # type: ignore[attr-defined]
        "wppd_parent_id": p.wppd_parent_id,  # type: ignore[attr-defined]
        "wppd_accent_text_color": p.wppd_accent_text_color,  # type: ignore[attr-defined]
        "wppd_accent_background_color": p.wppd_accent_background_color,  # type: ignore[attr-defined]
        "property_type_ids": sequence_to_json(p.property_type_ids),  # type: ignore[attr-defined]
        "property_county_ids": sequence_to_json(p.property_county_ids),  # type: ignore[attr-defined]
        "property_area_ids": sequence_to_json(p.property_area_ids),  # type: ignore[attr-defined]
        "property_features": sequence_to_json(p.property_features),  # type: ignore[attr-defined]
        "media_attachments_json": p.media_attachments_json,  # type: ignore[attr-defined]
        "brochure_urls": sequence_to_json(p.brochure_urls),  # type: ignore[attr-defined]
        "floorplan_urls": sequence_to_json(p.floorplan_urls),  # type: ignore[attr-defined]
        "tour_urls": sequence_to_json(p.tour_urls),  # type: ignore[attr-defined]
        "viewing_times": sequence_to_json(p.viewing_times),  # type: ignore[attr-defined]
        "image_folder": image_folder,
        "image_count": p.image_count,  # type: ignore[attr-defined]
        "raw_json": p.raw_json,  # type: ignore[attr-defined]
        "fetched_at": fetched_at,
    }


def build_property_dict(property_item: object) -> dict[str, Any]:
    p = property_item
    return {
        "id": p.id,  # type: ignore[attr-defined]
        "slug": p.slug,  # type: ignore[attr-defined]
        "title": p.title,  # type: ignore[attr-defined]
        "link": p.link,  # type: ignore[attr-defined]
        "guid": p.guid,  # type: ignore[attr-defined]
        "status": p.status,  # type: ignore[attr-defined]
        "resource_type": p.resource_type,  # type: ignore[attr-defined]
        "author_id": p.author_id,  # type: ignore[attr-defined]
        "importer_id": p.importer_id,  # type: ignore[attr-defined]
        "list_reference": p.list_reference,  # type: ignore[attr-defined]
        "date": p.date,  # type: ignore[attr-defined]
        "date_gmt": p.date_gmt,  # type: ignore[attr-defined]
        "modified": p.modified,  # type: ignore[attr-defined]
        "modified_gmt": p.modified_gmt,  # type: ignore[attr-defined]
        "excerpt_html": p.excerpt_html,  # type: ignore[attr-defined]
        "content_html": p.content_html,  # type: ignore[attr-defined]
        "price": p.price,  # type: ignore[attr-defined]
        "price_sold": p.price_sold,  # type: ignore[attr-defined]
        "price_term": p.price_term,  # type: ignore[attr-defined]
        "property_status": p.property_status,  # type: ignore[attr-defined]
        "property_market": p.property_market,  # type: ignore[attr-defined]
        "property_type_label": p.property_type_label,  # type: ignore[attr-defined]
        "property_county_label": p.property_county_label,  # type: ignore[attr-defined]
        "property_area_label": p.property_area_label,  # type: ignore[attr-defined]
        "property_size": p.property_size,  # type: ignore[attr-defined]
        "property_land_size": p.property_land_size,  # type: ignore[attr-defined]
        "property_accommodation": p.property_accommodation,  # type: ignore[attr-defined]
        "property_disclaimer": p.property_disclaimer,  # type: ignore[attr-defined]
        "bedrooms": p.bedrooms,  # type: ignore[attr-defined]
        "bathrooms": p.bathrooms,  # type: ignore[attr-defined]
        "ber_rating": p.ber_rating,  # type: ignore[attr-defined]
        "ber_number": p.ber_number,  # type: ignore[attr-defined]
        "energy_details": p.energy_details,  # type: ignore[attr-defined]
        "bidding_method": p.bidding_method,  # type: ignore[attr-defined]
        "living_type": p.living_type,  # type: ignore[attr-defined]
        "country": p.country,  # type: ignore[attr-defined]
        "eircode": p.eircode,  # type: ignore[attr-defined]
        "directions": p.directions,  # type: ignore[attr-defined]
        "latitude": p.latitude,  # type: ignore[attr-defined]
        "longitude": p.longitude,  # type: ignore[attr-defined]
        "agent_name": p.agent_name,  # type: ignore[attr-defined]
        "agent_photo_url": p.agent_photo_url,  # type: ignore[attr-defined]
        "agent_email": p.agent_email,  # type: ignore[attr-defined]
        "agent_mobile": p.agent_mobile,  # type: ignore[attr-defined]
        "agent_number": p.agent_number,  # type: ignore[attr-defined]
        "agent_qualification": p.agent_qualification,  # type: ignore[attr-defined]
        "agency_psra": p.agency_psra,  # type: ignore[attr-defined]
        "agency_logo_url": p.agency_logo_url,  # type: ignore[attr-defined]
        "featured_media_id": p.featured_media_id,  # type: ignore[attr-defined]
        "featured_image_url": p.featured_image_url,  # type: ignore[attr-defined]
        "amenities": p.amenities,  # type: ignore[attr-defined]
        "property_order": p.property_order,  # type: ignore[attr-defined]
        "wppd_parent_id": p.wppd_parent_id,  # type: ignore[attr-defined]
        "wppd_accent_text_color": p.wppd_accent_text_color,  # type: ignore[attr-defined]
        "wppd_accent_background_color": p.wppd_accent_background_color,  # type: ignore[attr-defined]
        "property_type_ids": list(p.property_type_ids),  # type: ignore[attr-defined]
        "property_county_ids": list(p.property_county_ids),  # type: ignore[attr-defined]
        "property_area_ids": list(p.property_area_ids),  # type: ignore[attr-defined]
        "property_features": list(p.property_features),  # type: ignore[attr-defined]
        "image_urls": list(p.image_urls),  # type: ignore[attr-defined]
        "media_attachments_json": p.media_attachments_json,  # type: ignore[attr-defined]
        "brochure_urls": list(p.brochure_urls),  # type: ignore[attr-defined]
        "floorplan_urls": list(p.floorplan_urls),  # type: ignore[attr-defined]
        "tour_urls": list(p.tour_urls),  # type: ignore[attr-defined]
        "viewing_times": list(p.viewing_times),  # type: ignore[attr-defined]
        "raw_data": p.raw_data,  # type: ignore[attr-defined]
    }
