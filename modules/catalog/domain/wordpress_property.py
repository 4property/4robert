"""WordPress-payload property aggregate.

Moved from ``domain/properties/model.py`` during sub-feature 18b. Co-located
with the DB-backed ``CatalogProperty`` value object because both belong to
the catalog bounded context, but kept in its own module so the file stays
under the ~500 LoC guideline. Coercion and serialization helpers live in
``_property_conversions.py``.

Consumers (use cases, rendering, scripted-video, publishing copy) import
``Property`` from this module or from the package ``__init__`` re-export.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from typing import Any, Mapping

from ._property_conversions import (
    build_property_db_record,
    build_property_dict,
    extract_rendered_text,
    json_safe_copy,
    normalise_slug,
    to_float,
    to_int,
    to_int_tuple,
    to_serialised_text,
    to_text,
    to_text_tuple,
)


def _contains_n_digits(value: str | None, *, n: int) -> bool:
    """Return True if *value* contains at least *n* digit characters.

    Helper for the defensive promotion of mis-labelled email payloads to
    ``agent_mobile`` (see ``Property.from_api_payload``). Kept intentionally
    private to this module — it is too narrow to belong in ``shared/``.
    """

    if not value:
        return False
    return sum(1 for c in value if c.isdigit()) >= n


def _resolve_agent_contact(
    payload: Mapping[str, Any],
) -> tuple[str | None, str | None, str | None]:
    """Resolve ``(agent_mobile, agent_email, agent_number)`` from *payload*.

    Real-world payloads (e.g. Century 21 webhooks) sometimes ship the agent
    phone under the ``agent_phone`` key — which the historical mapper
    ignored — and occasionally duplicate that phone into ``agent_email``
    (also without an ``@``). To keep the renderer's "phone" / "email"
    lines aligned with reality we apply, in order:

    1. ``agent_mobile`` (explicit) wins; otherwise fall back to
       ``agent_phone``.
    2. ``agent_email`` is discarded if it does not contain ``'@'``.
    3. If after (1) ``agent_mobile`` is still ``None`` *and* the raw
       ``agent_email`` looked like a phone (no ``@``, 6+ digits), promote
       it to ``agent_mobile``. This only kicks in when both phone slots
       were empty — we never overwrite an operator-supplied value.
    """

    mobile_explicit = to_text(payload.get("agent_mobile"))
    mobile_fallback = to_text(payload.get("agent_phone"))
    mobile_candidate = mobile_explicit or mobile_fallback

    email_raw = to_text(payload.get("agent_email"))
    email_looks_valid = bool(email_raw) and "@" in (email_raw or "")

    if (
        email_raw is not None
        and not email_looks_valid
        and mobile_candidate is None
        and _contains_n_digits(email_raw, n=6)
    ):
        mobile_candidate = email_raw

    agent_email = email_raw if email_looks_valid else None
    agent_number = to_text(payload.get("agent_number"))
    return mobile_candidate, agent_email, agent_number


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
    agent_photo_url: str | None = None
    agent_email: str | None = None
    agent_mobile: str | None = None
    agent_number: str | None = None
    agent_qualification: str | None = None
    agency_psra: str | None = None
    agency_logo_url: str | None = None
    featured_media_id: int | None = None
    featured_image_url: str | None = None
    amenities: str | None = None
    property_order: int | None = None
    wppd_parent_id: str | None = None
    wppd_accent_text_color: str | None = None
    wppd_accent_background_color: str | None = None
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

        raw_data = json_safe_copy(dict(payload))
        fallback_seed = (
            payload.get("id")
            or payload.get("importer_id")
            or payload.get("slug")
            or "unknown"
        )
        property_id = to_int(payload.get("id"))
        if property_id is None:
            property_id = to_int(payload.get("importer_id"))
        if property_id is None:
            property_id = zlib.crc32(str(fallback_seed).encode("utf-8")) & 0xFFFFFFFF

        image_urls = to_text_tuple(payload.get("wppd_pics"))
        featured_image_url = to_text(payload.get("wppd_primary_image"))
        if not image_urls and featured_image_url:
            image_urls = (featured_image_url,)

        agent_mobile, agent_email, agent_number = _resolve_agent_contact(payload)

        return cls(
            id=property_id,
            slug=normalise_slug(payload.get("slug"), property_id),
            title=extract_rendered_text(payload.get("title")),
            link=to_text(payload.get("link")),
            guid=extract_rendered_text(payload.get("guid")),
            status=to_text(payload.get("status")),
            resource_type=to_text(payload.get("type")),
            author_id=to_int(payload.get("author")),
            importer_id=to_text(payload.get("importer_id")),
            list_reference=to_text(payload.get("list_reference")),
            date=to_text(payload.get("date")),
            date_gmt=to_text(payload.get("date_gmt")),
            modified=to_text(payload.get("modified")),
            modified_gmt=to_text(payload.get("modified_gmt")),
            excerpt_html=extract_rendered_text(payload.get("excerpt")),
            content_html=extract_rendered_text(payload.get("content")),
            price=to_text(payload.get("price")),
            price_sold=to_text(payload.get("price_sold")),
            price_term=to_text(payload.get("price_term")),
            property_status=to_text(payload.get("property_status")),
            property_market=to_text(payload.get("property_market")),
            property_type_label=to_text(payload.get("property_type_label")),
            property_county_label=to_text(payload.get("property_county_label")),
            property_area_label=to_text(payload.get("property_area_label")),
            property_size=to_text(payload.get("property_size")),
            property_land_size=to_text(payload.get("property_land_size")),
            property_accommodation=to_text(payload.get("property_accommodation")),
            property_disclaimer=to_text(payload.get("property_disclaimer")),
            bedrooms=to_int(payload.get("bedrooms")),
            bathrooms=to_int(payload.get("bathrooms")),
            ber_rating=to_text(payload.get("ber_rating")),
            ber_number=to_serialised_text(payload.get("ber_number")),
            energy_details=to_text(payload.get("energy_details")),
            bidding_method=to_text(payload.get("bidding_method")),
            living_type=to_text(payload.get("living_type")),
            country=to_text(payload.get("country")),
            eircode=to_text(payload.get("eircode")),
            directions=to_text(payload.get("directions")),
            latitude=to_float(payload.get("latitude")),
            longitude=to_float(payload.get("longitude")),
            agent_name=to_text(payload.get("agent_name")),
            agent_photo_url=to_text(payload.get("agent_photo")),
            agent_email=agent_email,
            agent_mobile=agent_mobile,
            agent_number=agent_number,
            agent_qualification=to_text(payload.get("agent_qualification")),
            agency_psra=to_text(payload.get("agency_psra")),
            agency_logo_url=to_text(payload.get("agency_logo")),
            featured_media_id=to_int(payload.get("featured_media")),
            featured_image_url=featured_image_url,
            amenities=to_text(payload.get("amenities")),
            property_order=to_int(payload.get("property_order")),
            wppd_parent_id=to_text(payload.get("wppd_parent_id")),
            wppd_accent_text_color=to_text(payload.get("wppd_accent_text_color")),
            wppd_accent_background_color=to_text(payload.get("wppd_accent_background_color")),
            property_type_ids=to_int_tuple(payload.get("property_type")),
            property_county_ids=to_int_tuple(payload.get("property_county")),
            property_area_ids=to_int_tuple(payload.get("property_area")),
            property_features=to_text_tuple(
                payload.get("property_features"),
                split_pipes=True,
            ),
            image_urls=image_urls,
            media_attachments_json=to_serialised_text(payload.get("media_attachments")),
            brochure_urls=to_text_tuple(payload.get("wppd_property_brochures")),
            floorplan_urls=to_text_tuple(payload.get("wppd_property_floorplans")),
            tour_urls=to_text_tuple(payload.get("wppd_property_tours")),
            viewing_times=to_text_tuple(payload.get("wppd_property_viewing_times")),
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
        import json
        return json.dumps(self.raw_data, ensure_ascii=False, sort_keys=True)

    def to_db_record(self, *, image_folder: str, fetched_at: str) -> dict[str, Any]:
        return build_property_db_record(self, image_folder=image_folder, fetched_at=fetched_at)

    def to_dict(self) -> dict[str, Any]:
        return build_property_dict(self)


__all__ = ["Property"]
