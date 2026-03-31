from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from models.property import Property
from repositories.property_pipeline_repository import PropertyReelRecord
from services.social_delivery.post_copy import build_property_caption, build_property_copy_bundle

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


def build_base_social_description(
    *,
    site_id: str,
    slug: str,
    agent_name: str | None = None,
    agent_email: str | None = None,
    agent_mobile: str | None = None,
    agent_number: str | None = None,
    agency_psra: str | None = None,
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
    return build_property_caption(
        property_url=property_url,
        agent_name=agent_name,
        agent_phone=agent_mobile or agent_number,
        agent_email=agent_email,
        agency_psra=agency_psra,
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
    property_link: str | None,
    property_url_template: str,
    tracking_query_params: Mapping[str, str] | None = None,
    **_: object,
) -> str:
    del platform
    return build_base_social_description(
        site_id=site_id,
        slug=slug,
        agent_name=agent_name,
        agent_email=agent_email,
        agent_mobile=agent_mobile,
        agent_number=agent_number,
        agency_psra=agency_psra,
        property_link=property_link,
        property_url_template=property_url_template,
        tracking_query_params=tracking_query_params,
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
    copy_bundle = build_property_copy_bundle(
        property_item=property_item,
        property_url=property_url,
        platforms=platforms,
    )
    return dict(copy_bundle.captions_by_platform)


def build_tiktok_description(
    *,
    site_id: str,
    slug: str,
    agent_name: str | None = None,
    agent_email: str | None = None,
    agent_mobile: str | None = None,
    agent_number: str | None = None,
    agency_psra: str | None = None,
    property_link: str | None,
    property_url_template: str,
    tracking_query_params: Mapping[str, str] | None = None,
    **_: object,
) -> str:
    return build_base_social_description(
        site_id=site_id,
        slug=slug,
        agent_name=agent_name,
        agent_email=agent_email,
        agent_mobile=agent_mobile,
        agent_number=agent_number,
        agency_psra=agency_psra,
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
    return build_tiktok_description(
        site_id=site_id,
        slug=property_item.slug,
        agent_name=property_item.agent_name,
        agent_email=property_item.agent_email,
        agent_mobile=property_item.agent_mobile,
        agent_number=property_item.agent_number,
        agency_psra=property_item.agency_psra,
        property_link=property_item.link,
        property_url_template=property_url_template,
        tracking_query_params=tracking_query_params,
    )


def build_tiktok_description_for_record(
    record: PropertyReelRecord,
    *,
    property_url_template: str,
    tracking_query_params: Mapping[str, str] | None = None,
    max_length: int = TIKTOK_MAX_DESCRIPTION_LENGTH,
) -> str:
    del max_length
    return build_tiktok_description(
        site_id=record.site_id,
        slug=record.slug,
        agent_name=record.agent_name,
        agent_email=record.agent_email,
        agent_mobile=record.agent_mobile,
        agent_number=record.agent_number,
        agency_psra=record.agency_psra,
        property_link=record.link,
        property_url_template=property_url_template,
        tracking_query_params=tracking_query_params,
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
    cleaned_value = str(value or "").strip()
    return cleaned_value or None


__all__ = [
    "TIKTOK_MAX_DESCRIPTION_LENGTH",
    "build_base_social_description",
    "build_platform_description",
    "build_platform_descriptions_for_property",
    "build_property_public_url",
    "build_tiktok_description",
    "build_tiktok_description_for_property",
    "build_tiktok_description_for_record",
]
