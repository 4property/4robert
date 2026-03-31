from __future__ import annotations

import re

from application.types import MediaDeliveryPlan
from models.property import Property
from services.reel_rendering.formatting import format_price

_NORMALIZED_STATUS_PATTERN = re.compile(r"[\s_-]+")
_LISTING_LIFECYCLE_MAP = {
    "for sale": "for_sale",
    "to let": "to_let",
    "sale agreed": "sale_agreed",
    "sold": "sold",
    "let agreed": "let_agreed",
    "let": "let",
}
_BANNER_TEXT_BY_LIFECYCLE = {
    "for_sale": "FOR SALE",
    "to_let": "TO LET",
    "sale_agreed": "SALE AGREED",
    "sold": "SOLD",
    "let_agreed": "LET AGREED",
    "let": "LET",
}
_STATUS_REEL_LIFECYCLES = {"sale_agreed", "sold", "let_agreed", "let"}


def normalize_listing_lifecycle(property_status: str | None) -> str:
    normalized_status = _normalise_status_text(property_status)
    return _LISTING_LIFECYCLE_MAP.get(normalized_status, "for_sale")


def build_media_delivery_plan(property_item: Property) -> MediaDeliveryPlan:
    listing_lifecycle = normalize_listing_lifecycle(property_item.property_status)
    if listing_lifecycle in _STATUS_REEL_LIFECYCLES:
        return MediaDeliveryPlan(
            listing_lifecycle=listing_lifecycle,
            artifact_kind="reel_video",
            render_profile=f"{listing_lifecycle}_status_reel",
            social_post_type="reel",
            asset_strategy="primary_only",
            banner_text=_BANNER_TEXT_BY_LIFECYCLE[listing_lifecycle],
            price_display_text="",
        )

    return MediaDeliveryPlan(
        listing_lifecycle=listing_lifecycle,
        artifact_kind="reel_video",
        render_profile=f"{listing_lifecycle}_reel",
        social_post_type="reel",
        asset_strategy="curated_selection",
        banner_text=_BANNER_TEXT_BY_LIFECYCLE[listing_lifecycle],
        price_display_text=build_price_display_text(
            property_item=property_item,
            listing_lifecycle=listing_lifecycle,
        ),
    )


def build_price_display_text(*, property_item: Property, listing_lifecycle: str) -> str | None:
    formatted_price = format_price(property_item.price)
    if not formatted_price:
        return None

    if listing_lifecycle != "to_let":
        return formatted_price

    raw_term = str(property_item.price_term or "").strip()
    if not raw_term:
        return f"{formatted_price} /month"
    if raw_term.startswith("/"):
        return f"{formatted_price} {raw_term}"
    return f"{formatted_price} {raw_term}"


def _normalise_status_text(value: str | None) -> str:
    cleaned_value = str(value or "").strip().lower()
    if not cleaned_value:
        return ""
    return _NORMALIZED_STATUS_PATTERN.sub(" ", cleaned_value).strip()


__all__ = [
    "build_media_delivery_plan",
    "build_price_display_text",
    "normalize_listing_lifecycle",
]
