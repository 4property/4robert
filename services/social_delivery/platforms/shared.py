from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from services.social_delivery.post_copy import build_property_caption

TIKTOK_MAX_DESCRIPTION_LENGTH = 150


@dataclass(frozen=True, slots=True)
class SocialPlatformPropertyView:
    slug: str
    title: str | None = None
    price: str | None = None
    agent_name: str | None = None
    agent_email: str | None = None
    agent_mobile: str | None = None
    agent_number: str | None = None
    agency_psra: str | None = None


def build_common_description(property_item, property_url: str) -> str:
    return build_property_caption(
        property_url=property_url,
        agent_name=property_item.agent_name,
        agent_phone=property_item.agent_mobile or property_item.agent_number,
        agent_email=property_item.agent_email,
        agency_psra=property_item.agency_psra,
    )


def build_google_business_profile_description(property_item, property_url: str) -> str:
    rendered_lines = [
        value
        for value in (
            _clean_text(property_item.title),
            _clean_text(property_item.price),
            _render_site_label(property_url),
            _clean_text(property_item.agent_name),
        )
        if value
    ]
    return "\n".join(rendered_lines)


def build_default_title(property_item) -> str | None:
    return _clean_text(property_item.title)


def build_default_upload_file_name(title: str | None) -> str | None:
    del title
    return None


def build_youtube_upload_file_name(title: str | None) -> str | None:
    normalized_title = _clean_text(title)
    return normalized_title or None


def build_empty_gohighlevel_payload(target_url: str | None, title: str | None) -> dict[str, object]:
    del target_url, title
    return {}


def build_google_business_profile_gohighlevel_payload(
    target_url: str | None,
    title: str | None,
) -> dict[str, object]:
    del title
    cleaned_target_url = _clean_text(target_url)
    if cleaned_target_url is None:
        return {}
    return {
        "gmbPostDetails": {
            "gmbEventType": "STANDARD",
            "actionType": "BOOK",
            "url": cleaned_target_url,
        }
    }


def build_youtube_gohighlevel_payload(
    target_url: str | None,
    title: str | None,
) -> dict[str, object]:
    del target_url
    youtube_post_details: dict[str, object] = {"type": "video"}
    normalized_title = _clean_text(title)
    if normalized_title is not None:
        youtube_post_details["title"] = normalized_title
    return {"youtubePostDetails": youtube_post_details}


def _render_site_label(property_url: str | None) -> str | None:
    site_label = _extract_site_label(property_url)
    if site_label is None:
        return None
    return f"More properties on {site_label}"


def _clean_text(value: str | None) -> str | None:
    cleaned_value = str(value or "").strip()
    return cleaned_value or None


def _extract_site_label(property_url: str | None) -> str | None:
    cleaned_url = _clean_text(property_url)
    if cleaned_url is None:
        return None

    parsed_url = urlsplit(cleaned_url)
    hostname = parsed_url.hostname
    if hostname:
        normalized_hostname = hostname.lower()
        if normalized_hostname.startswith("www."):
            normalized_hostname = normalized_hostname[4:]
        return normalized_hostname

    fallback_host = cleaned_url.split("/", 1)[0].strip().lower()
    if fallback_host.startswith("www."):
        fallback_host = fallback_host[4:]
    return fallback_host or cleaned_url


__all__ = [
    "SocialPlatformPropertyView",
    "TIKTOK_MAX_DESCRIPTION_LENGTH",
    "build_common_description",
    "build_default_title",
    "build_default_upload_file_name",
    "build_empty_gohighlevel_payload",
    "build_google_business_profile_gohighlevel_payload",
    "build_google_business_profile_description",
    "build_youtube_gohighlevel_payload",
    "build_youtube_upload_file_name",
]
