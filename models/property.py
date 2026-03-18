from __future__ import annotations

import json
import re
import zlib
from dataclasses import dataclass, field
from typing import Any, Mapping


_SLUG_INVALID_CHARS_RE = re.compile(r"[^a-z0-9-]+")
_MULTIPLE_DASHES_RE = re.compile(r"-{2,}")


def _json_safe_copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except TypeError:
        return value


def _to_text(value: Any) -> str | None:
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


def _to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None

    if isinstance(value, bool):
        return int(value)

    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return int(value)

    text = _to_text(value)
    if text is None:
        return None

    try:
        return int(float(text.replace(",", "")))
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None

    if isinstance(value, bool):
        return float(int(value))

    if isinstance(value, int | float):
        return float(value)

    text = _to_text(value)
    if text is None:
        return None

    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _extract_rendered_text(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return _to_text(value.get("rendered"))
    return _to_text(value)


def _to_text_tuple(value: Any, *, split_pipes: bool = False) -> tuple[str, ...]:
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
                return _to_text_tuple(parsed, split_pipes=split_pipes)
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
            items.extend(_to_text_tuple(item, split_pipes=split_pipes))
        return tuple(items)

    text = _to_text(value)
    return (text,) if text else ()


def _to_int_tuple(value: Any) -> tuple[int, ...]:
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
                return _to_int_tuple(parsed)

    if isinstance(value, (list, tuple, set)):
        items: list[int] = []
        for item in value:
            integer = _to_int(item)
            if integer is not None:
                items.append(integer)
        return tuple(items)

    integer = _to_int(value)
    return (integer,) if integer is not None else ()


def _to_serialised_text(value: Any) -> str | None:
    if value is None or value == "" or value == [] or value == {} or value == ():
        return None

    if isinstance(value, Mapping | list | tuple | set):
        safe_value = _json_safe_copy(value)
        if safe_value in (None, "", [], {}, ()):
            return None
        return json.dumps(safe_value, ensure_ascii=False, sort_keys=True)

    return _to_text(value)


def _sequence_to_json(values: tuple[Any, ...]) -> str | None:
    if not values:
        return None
    return json.dumps(list(values), ensure_ascii=False)


def _normalise_slug(candidate: Any, fallback_seed: Any) -> str:
    base_slug = _to_text(candidate) or f"property-{fallback_seed}"
    normalised = base_slug.lower().replace("_", "-")
    normalised = _SLUG_INVALID_CHARS_RE.sub("-", normalised)
    normalised = _MULTIPLE_DASHES_RE.sub("-", normalised).strip("-")
    if normalised:
        return normalised

    crc32 = zlib.crc32(str(fallback_seed).encode("utf-8")) & 0xFFFFFFFF
    return f"property-{crc32}"


@dataclass(slots=True)
class Property:
    id: int
    slug: str
    title: str | None = None
    link: str | None = None
    guid: str | None = None
    status: str | None = None
    resource_type: str | None = None
    author_id: int | None = None
    importer_id: str | None = None
    list_reference: str | None = None
    date: str | None = None
    date_gmt: str | None = None
    modified: str | None = None
    modified_gmt: str | None = None
    excerpt_html: str | None = None
    content_html: str | None = None
    price: str | None = None
    price_sold: str | None = None
    price_term: str | None = None
    property_status: str | None = None
    property_market: str | None = None
    property_type_label: str | None = None
    property_county_label: str | None = None
    property_area_label: str | None = None
    property_size: str | None = None
    property_land_size: str | None = None
    property_accommodation: str | None = None
    property_disclaimer: str | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    ber_rating: str | None = None
    ber_number: str | None = None
    energy_details: str | None = None
    bidding_method: str | None = None
    living_type: str | None = None
    country: str | None = None
    eircode: str | None = None
    directions: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    agent_name: str | None = None
    agent_email: str | None = None
    agent_mobile: str | None = None
    agent_number: str | None = None
    agent_qualification: str | None = None
    featured_media_id: int | None = None
    featured_image_url: str | None = None
    amenities: str | None = None
    property_order: int | None = None
    wppd_parent_id: str | None = None
    property_type_ids: tuple[int, ...] = field(default_factory=tuple)
    property_county_ids: tuple[int, ...] = field(default_factory=tuple)
    property_area_ids: tuple[int, ...] = field(default_factory=tuple)
    property_features: tuple[str, ...] = field(default_factory=tuple)
    image_urls: tuple[str, ...] = field(default_factory=tuple)
    media_attachments_json: str | None = None
    brochure_urls: tuple[str, ...] = field(default_factory=tuple)
    floorplan_urls: tuple[str, ...] = field(default_factory=tuple)
    tour_urls: tuple[str, ...] = field(default_factory=tuple)
    viewing_times: tuple[str, ...] = field(default_factory=tuple)
    raw_data: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api_payload(cls, payload: Mapping[str, Any]) -> "Property":
        if not isinstance(payload, Mapping):
            raise TypeError("Property payload must be a mapping.")

        raw_data = _json_safe_copy(dict(payload))
        fallback_seed = payload.get("id") or payload.get("importer_id") or payload.get("slug") or "unknown"
        property_id = _to_int(payload.get("id"))
        if property_id is None:
            property_id = _to_int(payload.get("importer_id"))
        if property_id is None:
            property_id = zlib.crc32(str(fallback_seed).encode("utf-8")) & 0xFFFFFFFF

        image_urls = _to_text_tuple(payload.get("wppd_pics"))
        featured_image_url = _to_text(payload.get("wppd_primary_image"))
        if not image_urls and featured_image_url:
            image_urls = (featured_image_url,)

        return cls(
            id=property_id,
            slug=_normalise_slug(payload.get("slug"), property_id),
            title=_extract_rendered_text(payload.get("title")),
            link=_to_text(payload.get("link")),
            guid=_extract_rendered_text(payload.get("guid")),
            status=_to_text(payload.get("status")),
            resource_type=_to_text(payload.get("type")),
            author_id=_to_int(payload.get("author")),
            importer_id=_to_text(payload.get("importer_id")),
            list_reference=_to_text(payload.get("list_reference")),
            date=_to_text(payload.get("date")),
            date_gmt=_to_text(payload.get("date_gmt")),
            modified=_to_text(payload.get("modified")),
            modified_gmt=_to_text(payload.get("modified_gmt")),
            excerpt_html=_extract_rendered_text(payload.get("excerpt")),
            content_html=_extract_rendered_text(payload.get("content")),
            price=_to_text(payload.get("price")),
            price_sold=_to_text(payload.get("price_sold")),
            price_term=_to_text(payload.get("price_term")),
            property_status=_to_text(payload.get("property_status")),
            property_market=_to_text(payload.get("property_market")),
            property_type_label=_to_text(payload.get("property_type_label")),
            property_county_label=_to_text(payload.get("property_county_label")),
            property_area_label=_to_text(payload.get("property_area_label")),
            property_size=_to_text(payload.get("property_size")),
            property_land_size=_to_text(payload.get("property_land_size")),
            property_accommodation=_to_text(payload.get("property_accommodation")),
            property_disclaimer=_to_text(payload.get("property_disclaimer")),
            bedrooms=_to_int(payload.get("bedrooms")),
            bathrooms=_to_int(payload.get("bathrooms")),
            ber_rating=_to_text(payload.get("ber_rating")),
            ber_number=_to_serialised_text(payload.get("ber_number")),
            energy_details=_to_text(payload.get("energy_details")),
            bidding_method=_to_text(payload.get("bidding_method")),
            living_type=_to_text(payload.get("living_type")),
            country=_to_text(payload.get("country")),
            eircode=_to_text(payload.get("eircode")),
            directions=_to_text(payload.get("directions")),
            latitude=_to_float(payload.get("latitude")),
            longitude=_to_float(payload.get("longitude")),
            agent_name=_to_text(payload.get("agent_name")),
            agent_email=_to_text(payload.get("agent_email")),
            agent_mobile=_to_text(payload.get("agent_mobile")),
            agent_number=_to_text(payload.get("agent_number")),
            agent_qualification=_to_text(payload.get("agent_qualification")),
            featured_media_id=_to_int(payload.get("featured_media")),
            featured_image_url=featured_image_url,
            amenities=_to_text(payload.get("amenities")),
            property_order=_to_int(payload.get("property_order")),
            wppd_parent_id=_to_text(payload.get("wppd_parent_id")),
            property_type_ids=_to_int_tuple(payload.get("property_type")),
            property_county_ids=_to_int_tuple(payload.get("property_county")),
            property_area_ids=_to_int_tuple(payload.get("property_area")),
            property_features=_to_text_tuple(
                payload.get("property_features"),
                split_pipes=True,
            ),
            image_urls=image_urls,
            media_attachments_json=_to_serialised_text(payload.get("media_attachments")),
            brochure_urls=_to_text_tuple(payload.get("wppd_property_brochures")),
            floorplan_urls=_to_text_tuple(payload.get("wppd_property_floorplans")),
            tour_urls=_to_text_tuple(payload.get("wppd_property_tours")),
            viewing_times=_to_text_tuple(payload.get("wppd_property_viewing_times")),
            raw_data=raw_data if isinstance(raw_data, dict) else {},
        )

    @property
    def image_count(self) -> int:
        return len(self.image_urls)

    @property
    def folder_name(self) -> str:
        return self.slug

    @property
    def raw_json(self) -> str:
        return json.dumps(self.raw_data, ensure_ascii=False, sort_keys=True)

    def to_db_record(self, *, image_folder: str, fetched_at: str) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "title": self.title,
            "link": self.link,
            "guid": self.guid,
            "status": self.status,
            "resource_type": self.resource_type,
            "author_id": self.author_id,
            "importer_id": self.importer_id,
            "list_reference": self.list_reference,
            "date": self.date,
            "date_gmt": self.date_gmt,
            "modified": self.modified,
            "modified_gmt": self.modified_gmt,
            "excerpt_html": self.excerpt_html,
            "content_html": self.content_html,
            "price": self.price,
            "price_sold": self.price_sold,
            "price_term": self.price_term,
            "property_status": self.property_status,
            "property_market": self.property_market,
            "property_type_label": self.property_type_label,
            "property_county_label": self.property_county_label,
            "property_area_label": self.property_area_label,
            "property_size": self.property_size,
            "property_land_size": self.property_land_size,
            "property_accommodation": self.property_accommodation,
            "property_disclaimer": self.property_disclaimer,
            "bedrooms": self.bedrooms,
            "bathrooms": self.bathrooms,
            "ber_rating": self.ber_rating,
            "ber_number": self.ber_number,
            "energy_details": self.energy_details,
            "bidding_method": self.bidding_method,
            "living_type": self.living_type,
            "country": self.country,
            "eircode": self.eircode,
            "directions": self.directions,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "agent_name": self.agent_name,
            "agent_email": self.agent_email,
            "agent_mobile": self.agent_mobile,
            "agent_number": self.agent_number,
            "agent_qualification": self.agent_qualification,
            "featured_media_id": self.featured_media_id,
            "featured_image_url": self.featured_image_url,
            "amenities": self.amenities,
            "property_order": self.property_order,
            "wppd_parent_id": self.wppd_parent_id,
            "property_type_ids": _sequence_to_json(self.property_type_ids),
            "property_county_ids": _sequence_to_json(self.property_county_ids),
            "property_area_ids": _sequence_to_json(self.property_area_ids),
            "property_features": _sequence_to_json(self.property_features),
            "media_attachments_json": self.media_attachments_json,
            "brochure_urls": _sequence_to_json(self.brochure_urls),
            "floorplan_urls": _sequence_to_json(self.floorplan_urls),
            "tour_urls": _sequence_to_json(self.tour_urls),
            "viewing_times": _sequence_to_json(self.viewing_times),
            "image_folder": image_folder,
            "image_count": self.image_count,
            "raw_json": self.raw_json,
            "fetched_at": fetched_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "title": self.title,
            "link": self.link,
            "guid": self.guid,
            "status": self.status,
            "resource_type": self.resource_type,
            "author_id": self.author_id,
            "importer_id": self.importer_id,
            "list_reference": self.list_reference,
            "date": self.date,
            "date_gmt": self.date_gmt,
            "modified": self.modified,
            "modified_gmt": self.modified_gmt,
            "excerpt_html": self.excerpt_html,
            "content_html": self.content_html,
            "price": self.price,
            "price_sold": self.price_sold,
            "price_term": self.price_term,
            "property_status": self.property_status,
            "property_market": self.property_market,
            "property_type_label": self.property_type_label,
            "property_county_label": self.property_county_label,
            "property_area_label": self.property_area_label,
            "property_size": self.property_size,
            "property_land_size": self.property_land_size,
            "property_accommodation": self.property_accommodation,
            "property_disclaimer": self.property_disclaimer,
            "bedrooms": self.bedrooms,
            "bathrooms": self.bathrooms,
            "ber_rating": self.ber_rating,
            "ber_number": self.ber_number,
            "energy_details": self.energy_details,
            "bidding_method": self.bidding_method,
            "living_type": self.living_type,
            "country": self.country,
            "eircode": self.eircode,
            "directions": self.directions,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "agent_name": self.agent_name,
            "agent_email": self.agent_email,
            "agent_mobile": self.agent_mobile,
            "agent_number": self.agent_number,
            "agent_qualification": self.agent_qualification,
            "featured_media_id": self.featured_media_id,
            "featured_image_url": self.featured_image_url,
            "amenities": self.amenities,
            "property_order": self.property_order,
            "wppd_parent_id": self.wppd_parent_id,
            "property_type_ids": list(self.property_type_ids),
            "property_county_ids": list(self.property_county_ids),
            "property_area_ids": list(self.property_area_ids),
            "property_features": list(self.property_features),
            "image_urls": list(self.image_urls),
            "media_attachments_json": self.media_attachments_json,
            "brochure_urls": list(self.brochure_urls),
            "floorplan_urls": list(self.floorplan_urls),
            "tour_urls": list(self.tour_urls),
            "viewing_times": list(self.viewing_times),
            "raw_data": self.raw_data,
        }


__all__ = ["Property"]
