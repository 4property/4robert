from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from domain.properties.model import Property
from repositories.stores.property_store import PropertyReelRecord
from services.publishing.social_delivery.platforms import get_platform_config, normalize_platform_name
from services.publishing.social_delivery.platforms.shared import (
    SocialPlatformPropertyView,
    TIKTOK_MAX_DESCRIPTION_LENGTH,
    build_common_description,
)


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


def build_base_social_description(
    *,
    site_id: str,
    slug: str,
    agent_name: str | None = None,
    agent_email: str | None = None,
    agent_mobile: str | None = None,
    agent_number: str | None = None,
    agency_psra: str | None = None,
    property_status: str | None = None,
    property_link: str | None,
    property_url_template: str,
    tracking_query_params: Mapping[str, str] | None = None,
    **_: object,
) -> str:
    property_url = build_property_public_url(
        site_id=site_id,
        slug=slug,
        property_link=property_link,
        property_url_template=property_url_template,
        tracking_query_params=tracking_query_params,
    )
    return build_common_description(
        _build_property_view(
            slug=slug,
            property_status=property_status,
            agent_name=agent_name,
            agent_email=agent_email,
            agent_mobile=agent_mobile,
            agent_number=agent_number,
            agency_psra=agency_psra,
        ),
        property_url,
    )


def build_platform_description(
    *,
    platform: str,
    site_id: str,
    slug: str,
    agent_name: str | None = None,
    agent_email: str | None = None,
    agent_mobile: str | None = None,
    agent_number: str | None = None,
    agency_psra: str | None = None,
    property_status: str | None = None,
    property_link: str | None,
    property_url_template: str,
    tracking_query_params: Mapping[str, str] | None = None,
    **_: object,
) -> str:
    property_url = build_property_public_url(
        site_id=site_id,
        slug=slug,
        property_link=property_link,
        property_url_template=property_url_template,
        tracking_query_params=tracking_query_params,
    )
    property_view = _build_property_view(
        slug=slug,
        property_status=property_status,
        agent_name=agent_name,
        agent_email=agent_email,
        agent_mobile=agent_mobile,
        agent_number=agent_number,
        agency_psra=agency_psra,
    )
    return _build_platform_description_for_source(
        property_view,
        platform=platform,
        property_url=property_url,
    )


def build_platform_description_for_property(
    property_item: Property,
    *,
    platform: str,
    property_url: str,
) -> str:
    return _build_platform_description_for_source(
        property_item,
        platform=platform,
        property_url=property_url,
    )


def build_platform_descriptions_for_property(
    property_item: Property,
    *,
    site_id: str,
    platforms: tuple[str, ...],
    property_url_template: str,
    tracking_query_params: Mapping[str, str] | None = None,
) -> dict[str, str]:
    property_url = build_property_public_url(
        site_id=site_id,
        slug=property_item.slug,
        property_link=property_item.link,
        property_url_template=property_url_template,
        tracking_query_params=tracking_query_params,
    )
    return build_platform_descriptions_for_property_with_url(
        property_item,
        property_url=property_url,
        platforms=platforms,
    )


def build_platform_descriptions_for_property_with_url(
    property_item: Property,
    *,
    property_url: str,
    platforms: tuple[str, ...],
) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    for platform in platforms:
        normalized_platform = normalize_platform_name(platform)
        if not normalized_platform:
            continue
        descriptions[normalized_platform] = build_platform_description_for_property(
            property_item,
            platform=normalized_platform,
            property_url=property_url,
        )
    return descriptions


def build_platform_title_for_property(
    property_item: Property,
    *,
    platform: str,
) -> str | None:
    normalized_platform = normalize_platform_name(platform)
    config = get_platform_config(normalized_platform)
    if config is None:
        return None
    return config.build_title(property_item)


def build_platform_titles_for_property(
    property_item: Property,
    *,
    platforms: tuple[str, ...],
) -> dict[str, str]:
    titles: dict[str, str] = {}
    for platform in platforms:
        normalized_platform = normalize_platform_name(platform)
        if not normalized_platform:
            continue
        title = build_platform_title_for_property(
            property_item,
            platform=normalized_platform,
        )
        if title:
            titles[normalized_platform] = title
    return titles


def build_tiktok_description(
    *,
    site_id: str,
    slug: str,
    agent_name: str | None = None,
    agent_email: str | None = None,
    agent_mobile: str | None = None,
    agent_number: str | None = None,
    agency_psra: str | None = None,
    property_status: str | None = None,
    property_link: str | None,
    property_url_template: str,
    tracking_query_params: Mapping[str, str] | None = None,
    **_: object,
) -> str:
    return build_platform_description(
        platform="tiktok",
        site_id=site_id,
        slug=slug,
        agent_name=agent_name,
        agent_email=agent_email,
        agent_mobile=agent_mobile,
        agent_number=agent_number,
        agency_psra=agency_psra,
        property_status=property_status,
        property_link=property_link,
        property_url_template=property_url_template,
        tracking_query_params=tracking_query_params,
    )


def build_tiktok_description_for_property(
    property_item: Property,
    *,
    site_id: str,
    property_url_template: str,
    tracking_query_params: Mapping[str, str] | None = None,
    max_length: int = TIKTOK_MAX_DESCRIPTION_LENGTH,
) -> str:
    del max_length
    property_url = build_property_public_url(
        site_id=site_id,
        slug=property_item.slug,
        property_link=property_item.link,
        property_url_template=property_url_template,
        tracking_query_params=tracking_query_params,
    )
    return build_platform_description_for_property(
        property_item,
        platform="tiktok",
        property_url=property_url,
    )


def build_tiktok_description_for_record(
    record: PropertyReelRecord,
    *,
    property_url_template: str,
    tracking_query_params: Mapping[str, str] | None = None,
    max_length: int = TIKTOK_MAX_DESCRIPTION_LENGTH,
) -> str:
    del max_length
    property_url = build_property_public_url(
        site_id=record.site_id,
        slug=record.slug,
        property_link=record.link,
        property_url_template=property_url_template,
        tracking_query_params=tracking_query_params,
    )
    return _build_platform_description_for_source(
        _build_property_view(
            slug=record.slug,
            title=record.title,
            price=record.price,
            property_status=record.property_status,
            agent_name=record.agent_name,
            agent_email=record.agent_email,
            agent_mobile=record.agent_mobile,
            agent_number=record.agent_number,
            agency_psra=record.agency_psra,
        ),
        platform="tiktok",
        property_url=property_url,
    )


def _build_platform_description_for_source(
    property_item,
    *,
    platform: str,
    property_url: str,
) -> str:
    normalized_platform = normalize_platform_name(platform)
    config = get_platform_config(normalized_platform)
    if config is None:
        return build_common_description(property_item, property_url)
    return config.build_description(property_item, property_url)


def _build_property_view(
    *,
    slug: str,
    title: str | None = None,
    price: str | None = None,
    property_status: str | None = None,
    agent_name: str | None = None,
    agent_email: str | None = None,
    agent_mobile: str | None = None,
    agent_number: str | None = None,
    agency_psra: str | None = None,
) -> SocialPlatformPropertyView:
    return SocialPlatformPropertyView(
        slug=slug,
        title=title,
        price=price,
        property_status=property_status,
        agent_name=agent_name,
        agent_email=agent_email,
        agent_mobile=agent_mobile,
        agent_number=agent_number,
        agency_psra=agency_psra,
    )


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
        merged_query_items = [
            (existing_key, existing_value)
            for existing_key, existing_value in merged_query_items
            if existing_key != key
        ]
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
    cleaned_value = str(value or "").strip()
    return cleaned_value or None


__all__ = [
    "TIKTOK_MAX_DESCRIPTION_LENGTH",
    "build_base_social_description",
    "build_platform_description",
    "build_platform_description_for_property",
    "build_platform_descriptions_for_property",
    "build_platform_descriptions_for_property_with_url",
    "build_platform_title_for_property",
    "build_platform_titles_for_property",
    "build_property_public_url",
    "build_tiktok_description",
    "build_tiktok_description_for_property",
    "build_tiktok_description_for_record",
]
