from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

from models.property import Property

CaptionLayout = tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class PropertyCaptionContext:
    property_url: str
    agent_name: str | None = None
    agent_phone: str | None = None
    agent_email: str | None = None
    agency_psra: str | None = None


@dataclass(frozen=True, slots=True)
class SocialCopyBundle:
    default_caption: str
    captions_by_platform: dict[str, str]


def build_property_caption(
    *,
    property_url: str,
    agent_name: str | None,
    agent_phone: str | None,
    agent_email: str | None,
    agency_psra: str | None = None,
    layout: CaptionLayout | None = None,
) -> str:
    return render_property_caption(
        PropertyCaptionContext(
            property_url=property_url,
            agent_name=agent_name,
            agent_phone=agent_phone,
            agent_email=agent_email,
            agency_psra=agency_psra,
        ),
        layout=layout,
    )


def render_property_caption(
    context: PropertyCaptionContext,
    *,
    layout: CaptionLayout | None = None,
) -> str:
    active_layout = layout or DEFAULT_PROPERTY_CAPTION_LAYOUT
    rendered_lines: list[str] = []
    pending_blank_line = False

    for section in active_layout:
        if not section:
            pending_blank_line = bool(rendered_lines)
            continue

        section_lines = [
            rendered_line
            for rendered_line in (
                _FIELD_RENDERERS[field_name](context)
                for field_name in section
                if field_name in _FIELD_RENDERERS
            )
            if rendered_line
        ]
        if not section_lines:
            continue
        if pending_blank_line and rendered_lines:
            rendered_lines.append("")
            pending_blank_line = False
        rendered_lines.extend(section_lines)

    return "\n".join(rendered_lines)


def build_property_copy_bundle(
    *,
    property_item: Property,
    property_url: str,
    platforms: tuple[str, ...],
    layout: CaptionLayout | None = None,
) -> SocialCopyBundle:
    context = PropertyCaptionContext(
        property_url=property_url,
        agent_name=property_item.agent_name,
        agent_phone=property_item.agent_mobile or property_item.agent_number,
        agent_email=property_item.agent_email,
        agency_psra=property_item.agency_psra,
    )
    default_caption = render_property_caption(context, layout=layout)
    return SocialCopyBundle(
        default_caption=default_caption,
        captions_by_platform={platform: default_caption for platform in platforms},
    )


def _render_property_url(context: PropertyCaptionContext) -> str | None:
    site_label = _extract_site_label(context.property_url)
    if site_label is None:
        return None
    return f"More properties on {site_label}"


def _render_property_link(context: PropertyCaptionContext) -> str | None:
    property_url = _clean_text(context.property_url)
    if property_url is None:
        return None
    return f"Property: {property_url}"


def _render_agent_name(context: PropertyCaptionContext) -> str | None:
    return _clean_text(context.agent_name)


def _render_agent_phone(context: PropertyCaptionContext) -> str | None:
    return _clean_text(context.agent_phone)


def _render_agent_email(context: PropertyCaptionContext) -> str | None:
    return _clean_text(context.agent_email)


def _render_agency_psra(context: PropertyCaptionContext) -> str | None:
    normalized_value = _clean_text(context.agency_psra)
    if not normalized_value:
        return None
    return f"Agency PSRA: {normalized_value}"


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


DEFAULT_PROPERTY_CAPTION_LAYOUT: CaptionLayout = (
    ("property_url",),
    (),
    ("agent_name", "agent_phone", "agent_email"),
    (),
    ("agency_psra",),
)

_FIELD_RENDERERS: dict[str, Callable[[PropertyCaptionContext], str | None]] = {
    "property_url": _render_property_url,
    "property_link": _render_property_link,
    "agent_name": _render_agent_name,
    "agent_phone": _render_agent_phone,
    "agent_email": _render_agent_email,
    "agency_psra": _render_agency_psra,
}


__all__ = [
    "CaptionLayout",
    "DEFAULT_PROPERTY_CAPTION_LAYOUT",
    "PropertyCaptionContext",
    "SocialCopyBundle",
    "build_property_caption",
    "build_property_copy_bundle",
    "render_property_caption",
]
