"""Private helpers shared by ingestion source use cases."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from shared.errors import ResourceNotFoundError, ValidationError

DEFAULT_SOURCE_KIND = "wordpress"
DEFAULT_SOURCE_STATUS = "active"


def normalize_external_id(value: str | None, *, field: str = "external_id") -> str:
    raw_value = str(value or "").strip().lower()
    if not raw_value:
        raise ValidationError(
            f"The {field} is required.",
            code="INGESTION_SOURCE_EXTERNAL_ID_REQUIRED",
            context={"field": field},
            hint="Send the source hostname (e.g. ckp.ie) as external_id.",
        )
    if "://" in raw_value:
        parsed = urlparse(raw_value)
        raw_value = parsed.hostname or parsed.netloc or parsed.path or ""
    else:
        raw_value = raw_value.split("/", 1)[0]
    if raw_value.startswith("[") and raw_value.endswith("]"):
        raw_value = raw_value[1:-1]
    if raw_value.count(":") == 1:
        host, port = raw_value.rsplit(":", 1)
        if port.isdigit():
            raw_value = host
    normalized = raw_value.strip().lower()
    if not normalized:
        raise ValidationError(
            f"The {field} is invalid.",
            code="INGESTION_SOURCE_EXTERNAL_ID_INVALID",
            context={field: value or ""},
            hint="Use a hostname such as ckp.ie or a full URL such as https://ckp.ie.",
        )
    return normalized


def normalize_kind(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        raise ValidationError(
            "The source kind is required.",
            code="INGESTION_SOURCE_KIND_REQUIRED",
            context={"field": "kind"},
            hint="Send a non-empty kind such as 'wordpress'.",
        )
    return normalized


def normalize_name(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValidationError(
            "The source name is required.",
            code="INGESTION_SOURCE_NAME_REQUIRED",
            context={"field": "name"},
            hint="Send a non-empty name in the request body.",
        )
    return normalized


def normalize_status(value: str | None) -> str:
    normalized = str(value or DEFAULT_SOURCE_STATUS).strip().lower()
    return normalized or DEFAULT_SOURCE_STATUS


def source_not_found_error(ingestion_source_id: str) -> ResourceNotFoundError:
    return ResourceNotFoundError(
        "The ingestion source does not exist.",
        code="ADMIN_SOURCE_NOT_FOUND",
        context={"ingestion_source_id": str(ingestion_source_id or "").strip()},
    )


def agency_not_found_error(agency_id: str) -> ResourceNotFoundError:
    return ResourceNotFoundError(
        "The agency does not exist.",
        code="ADMIN_AGENCY_NOT_FOUND",
        context={"agency_id": str(agency_id or "").strip()},
    )


_SITE_URL_PATTERN = re.compile(r"^[a-z][a-z0-9+\-.]*://", re.IGNORECASE)


def normalize_site_url(value: str | None, *, fallback_host: str) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return f"https://{fallback_host}"
    if not _SITE_URL_PATTERN.match(raw_value):
        raw_value = f"https://{raw_value}"
    parsed = urlparse(raw_value)
    hostname = parsed.hostname or parsed.netloc
    if not hostname:
        raise ValidationError(
            "The site_url is invalid.",
            code="INGESTION_SITE_URL_INVALID",
            context={"site_url": value or ""},
            hint="Use a full site URL such as https://ckp.ie.",
        )
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc or hostname
    return f"{scheme}://{netloc}"


__all__ = [
    "DEFAULT_SOURCE_KIND",
    "DEFAULT_SOURCE_STATUS",
    "agency_not_found_error",
    "normalize_external_id",
    "normalize_kind",
    "normalize_name",
    "normalize_site_url",
    "normalize_status",
    "source_not_found_error",
]
