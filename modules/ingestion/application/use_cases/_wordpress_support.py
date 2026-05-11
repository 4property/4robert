"""Shared helpers for WordPress-source admin use cases.

Used by ``inspect_wordpress_source_by_site_id`` and
``provision_wordpress_source``. The legacy
``WordPressSourceAdminService`` carried the same primitives; feature 9
extracted them so the new use cases can stay self-contained.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from shared.errors import ValidationError

_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


def normalize_wordpress_site_id(value: str | None) -> str:
    """Coerce arbitrary input (URL or hostname) into a lowercase hostname."""
    raw_value = str(value or "").strip().lower()
    if not raw_value:
        raise ValidationError(
            "The site_id is required.",
            code="ADMIN_SITE_ID_REQUIRED",
            context={"field": "site_id"},
            hint="Use a hostname such as ckp.ie or send a full site URL and the hostname will be extracted.",
        )
    if "://" in raw_value:
        parsed = urlparse(raw_value)
        raw_value = parsed.hostname or parsed.netloc or parsed.path
    else:
        raw_value = raw_value.split("/", 1)[0]
    normalized_value = str(raw_value or "").strip().lower()
    if normalized_value.startswith("[") and normalized_value.endswith("]"):
        normalized_value = normalized_value[1:-1]
    if normalized_value.count(":") == 1:
        hostname, port = normalized_value.rsplit(":", 1)
        if port.isdigit():
            normalized_value = hostname
    if not normalized_value:
        raise ValidationError(
            "The site_id is invalid.",
            code="ADMIN_SITE_ID_INVALID",
            context={"site_id": value or ""},
            hint="Use a hostname such as ckp.ie or a full URL such as https://ckp.ie.",
        )
    return normalized_value


def normalize_site_url(value: str | None, *, site_id: str) -> str:
    raw_value = clean_optional_text(value)
    if not raw_value:
        return f"https://{site_id}"
    if "://" not in raw_value:
        raw_value = f"https://{raw_value}"
    parsed = urlparse(raw_value)
    hostname = parsed.hostname or parsed.netloc
    if not hostname:
        raise ValidationError(
            "The site_url is invalid.",
            code="ADMIN_SITE_URL_INVALID",
            context={"site_url": value or ""},
            hint="Use a full site URL such as https://ckp.ie.",
        )
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc or hostname
    return f"{scheme}://{netloc}"


def normalize_host(value: str | None) -> str:
    raw_value = str(value or "").strip().lower()
    if not raw_value:
        raise ValidationError(
            "The normalized_host is invalid.",
            code="ADMIN_HOST_INVALID",
            context={"normalized_host": value or ""},
            hint="Send a hostname such as ckp.ie, or omit it so the endpoint derives it from site_url.",
        )
    if "://" in raw_value:
        parsed = urlparse(raw_value)
        raw_value = parsed.hostname or parsed.netloc or parsed.path
    else:
        raw_value = raw_value.split("/", 1)[0]
    normalized_value = str(raw_value or "").strip().lower()
    if normalized_value.count(":") == 1:
        hostname, port = normalized_value.rsplit(":", 1)
        if port.isdigit():
            normalized_value = hostname
    if not normalized_value:
        raise ValidationError(
            "The normalized_host is invalid.",
            code="ADMIN_HOST_INVALID",
            context={"normalized_host": value or ""},
            hint="Send a hostname such as ckp.ie, or omit it so the endpoint derives it from site_url.",
        )
    return normalized_value


def normalize_status(value: str | None, *, code: str, field_name: str) -> str:
    normalized_value = str(value or "").strip().lower()
    if not normalized_value:
        raise ValidationError(
            f"The {field_name} is required.",
            code=code,
            context={"field": field_name},
            hint=f"Send a non-empty {field_name} such as active or inactive.",
        )
    return normalized_value


def require_text(value: str | None, *, code: str, field_name: str) -> str:
    normalized_value = clean_optional_text(value)
    if normalized_value:
        return normalized_value
    raise ValidationError(
        f"The {field_name} is required.",
        code=code,
        context={"field": field_name},
        hint=f"Send a non-empty {field_name} value in the admin request body.",
    )


def resolve_agency_slug(
    *,
    requested_slug: str | None,
    agency_name: str,
    fallback: str,
) -> str:
    base_value = clean_optional_text(requested_slug) or agency_name
    slug = slugify(base_value, fallback=fallback)
    if not slug:
        raise ValidationError(
            "The agency_slug is invalid.",
            code="ADMIN_AGENCY_SLUG_INVALID",
            context={"agency_slug": requested_slug or "", "agency_name": agency_name},
            hint="Use only letters, numbers, and separators in agency_slug.",
        )
    return slug


def slugify(value: str, *, fallback: str) -> str:
    normalized_value = str(value or "").strip().lower()
    slug = _SLUG_PATTERN.sub("-", normalized_value).strip("-")
    if slug:
        return slug
    normalized_fallback = str(fallback or "").strip().lower()
    return _SLUG_PATTERN.sub("-", normalized_fallback).strip("-")


def clean_optional_text(value: str | None) -> str | None:
    normalized_value = str(value or "").strip()
    return normalized_value or None


__all__ = [
    "clean_optional_text",
    "normalize_host",
    "normalize_site_url",
    "normalize_status",
    "normalize_wordpress_site_id",
    "require_text",
    "resolve_agency_slug",
    "slugify",
]
