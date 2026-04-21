from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse
from uuid import uuid4

from application.persistence import UnitOfWork
from core.errors import ResourceNotFoundError, ValidationError
from repositories.stores.agency_store import AgencyRecord
from repositories.stores.wordpress_source_store import WordPressSourceDetailsRecord

_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class UpsertWordPressSourceRequest:
    site_id: str
    source_name: str
    agency_id: str | None = None
    agency_name: str | None = None
    agency_slug: str | None = None
    agency_timezone: str | None = None
    agency_status: str | None = None
    site_url: str | None = None
    normalized_host: str | None = None
    source_status: str | None = None
    webhook_secret: str | None = None
    update_webhook_secret: bool = False


@dataclass(frozen=True, slots=True)
class UpsertWordPressSourceResult:
    source: WordPressSourceDetailsRecord
    created_agency: bool
    updated_agency: bool
    created_source: bool
    updated_source: bool


class WordPressSourceAdminService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
    ) -> None:
        self.unit_of_work_factory = unit_of_work_factory

    def list_sources(self) -> tuple[WordPressSourceDetailsRecord, ...]:
        with self.unit_of_work_factory() as unit_of_work:
            return unit_of_work.wordpress_source_store.list_sources()

    def get_source(self, *, site_id: str) -> WordPressSourceDetailsRecord | None:
        normalized_site_id = _normalize_site_id(site_id)
        with self.unit_of_work_factory() as unit_of_work:
            return unit_of_work.wordpress_source_store.get_details_by_site_id(normalized_site_id)

    def ensure_source_for_testing(
        self,
        *,
        site_id: str,
    ) -> UpsertWordPressSourceResult:
        normalized_site_id = _normalize_site_id(site_id)
        existing_source = self.get_source(site_id=normalized_site_id)
        if existing_source is not None and existing_source.status == "active":
            return UpsertWordPressSourceResult(
                source=existing_source,
                created_agency=False,
                updated_agency=False,
                created_source=False,
                updated_source=False,
            )

        return self.upsert_source(
            _build_testing_upsert_request(
                site_id=normalized_site_id,
                existing_source=existing_source,
            )
        )

    def upsert_source(
        self,
        request: UpsertWordPressSourceRequest,
    ) -> UpsertWordPressSourceResult:
        normalized_site_id = _normalize_site_id(request.site_id)
        source_name = _require_text(
            request.source_name,
            code="ADMIN_SOURCE_NAME_REQUIRED",
            field_name="source_name",
        )

        with self.unit_of_work_factory() as unit_of_work:
            existing_source = unit_of_work.wordpress_source_store.get_details_by_site_id(
                normalized_site_id
            )

            created_agency = False
            updated_agency = False
            created_source = False
            updated_source = False

            if existing_source is None:
                agency = self._resolve_agency_for_create(unit_of_work, request, normalized_site_id)
                created_agency = agency.created
                active_agency = agency.record
            else:
                active_agency = self._resolve_agency_for_update(
                    unit_of_work,
                    request,
                    existing_source=existing_source,
                )

            desired_agency_name = (
                _clean_optional_text(request.agency_name)
                or active_agency.name
            )
            desired_agency_slug = _resolve_agency_slug(
                requested_slug=request.agency_slug,
                agency_name=desired_agency_name,
                fallback=normalized_site_id.replace(".", "-"),
            )
            desired_agency_timezone = (
                _clean_optional_text(request.agency_timezone)
                or active_agency.timezone
                or "Europe/Dublin"
            )
            desired_agency_status = _normalize_status(
                request.agency_status or active_agency.status or "active",
                code="ADMIN_INVALID_AGENCY_STATUS",
                field_name="agency_status",
            )

            _validate_agency_slug_conflict(
                unit_of_work,
                agency_id=active_agency.agency_id,
                desired_slug=desired_agency_slug,
            )

            if (
                desired_agency_name != active_agency.name
                or desired_agency_slug != active_agency.slug
                or desired_agency_timezone != active_agency.timezone
                or desired_agency_status != active_agency.status
            ):
                unit_of_work.agency_store.update_agency(
                    agency_id=active_agency.agency_id,
                    name=desired_agency_name,
                    slug=desired_agency_slug,
                    timezone=desired_agency_timezone,
                    status=desired_agency_status,
                )
                updated_agency = not created_agency

            current_site_url = existing_source.site_url if existing_source is not None else None
            resolved_site_url = _normalize_site_url(
                request.site_url or current_site_url,
                site_id=normalized_site_id,
            )
            current_host = existing_source.normalized_host if existing_source is not None else None
            resolved_host = _normalize_host(
                request.normalized_host or current_host or resolved_site_url or normalized_site_id
            )
            resolved_source_status = _normalize_status(
                request.source_status or (existing_source.status if existing_source is not None else "active"),
                code="ADMIN_INVALID_SOURCE_STATUS",
                field_name="source_status",
            )

            if existing_source is None:
                unit_of_work.wordpress_source_store.create_source(
                    wordpress_source_id=str(uuid4()),
                    agency_id=active_agency.agency_id,
                    site_id=normalized_site_id,
                    name=source_name,
                    site_url=resolved_site_url,
                    normalized_host=resolved_host,
                    status=resolved_source_status,
                    webhook_secret=request.webhook_secret or "",
                )
                created_source = True
            else:
                unit_of_work.wordpress_source_store.update_source(
                    wordpress_source_id=existing_source.wordpress_source_id,
                    name=source_name,
                    site_url=resolved_site_url,
                    normalized_host=resolved_host,
                    status=resolved_source_status,
                    webhook_secret=request.webhook_secret or "",
                    update_webhook_secret=request.update_webhook_secret,
                )
                updated_source = True

            persisted_source = unit_of_work.wordpress_source_store.get_details_by_site_id(
                normalized_site_id
            )

        if persisted_source is None:
            raise ResourceNotFoundError(
                "The wordpress source could not be reloaded after provisioning.",
                code="ADMIN_SOURCE_RELOAD_FAILED",
                context={"site_id": normalized_site_id},
                hint="Check the admin logs for the failed transaction and retry the provisioning request.",
            )

        return UpsertWordPressSourceResult(
            source=persisted_source,
            created_agency=created_agency,
            updated_agency=updated_agency,
            created_source=created_source,
            updated_source=updated_source,
        )

    def _resolve_agency_for_create(
        self,
        unit_of_work: UnitOfWork,
        request: UpsertWordPressSourceRequest,
        site_id: str,
    ) -> "_AgencyResolution":
        requested_agency_id = _clean_optional_text(request.agency_id)
        if requested_agency_id:
            agency = unit_of_work.agency_store.get_by_id(requested_agency_id)
            if agency is None:
                raise ResourceNotFoundError(
                    "The referenced agency does not exist.",
                    code="ADMIN_AGENCY_NOT_FOUND",
                    context={"agency_id": requested_agency_id},
                    hint="Create the agency first or omit agency_id so the admin endpoint can create it for you.",
                )
            return _AgencyResolution(record=agency, created=False)

        agency_name = _require_text(
            request.agency_name,
            code="ADMIN_AGENCY_NAME_REQUIRED",
            field_name="agency_name",
        )
        agency_slug = _resolve_agency_slug(
            requested_slug=request.agency_slug,
            agency_name=agency_name,
            fallback=site_id.replace(".", "-"),
        )
        existing_agency = unit_of_work.agency_store.get_by_slug(agency_slug)
        if existing_agency is not None:
            raise ValidationError(
                "The agency slug is already in use.",
                code="ADMIN_AGENCY_SLUG_CONFLICT",
                context={"agency_slug": agency_slug, "agency_id": existing_agency.agency_id},
                hint="Send the existing agency_id to attach the site to that agency, or choose a different agency_slug.",
            )

        agency_id = str(uuid4())
        unit_of_work.agency_store.create_agency(
            agency_id=agency_id,
            name=agency_name,
            slug=agency_slug,
            timezone=_clean_optional_text(request.agency_timezone) or "Europe/Dublin",
            status=_normalize_status(
                request.agency_status or "active",
                code="ADMIN_INVALID_AGENCY_STATUS",
                field_name="agency_status",
            ),
        )
        created_agency = unit_of_work.agency_store.get_by_id(agency_id)
        if created_agency is None:
            raise ResourceNotFoundError(
                "The agency could not be reloaded after creation.",
                code="ADMIN_AGENCY_RELOAD_FAILED",
                context={"agency_id": agency_id},
                hint="Check the admin logs for the failed transaction and retry the provisioning request.",
            )
        return _AgencyResolution(record=created_agency, created=True)

    def _resolve_agency_for_update(
        self,
        unit_of_work: UnitOfWork,
        request: UpsertWordPressSourceRequest,
        *,
        existing_source: WordPressSourceDetailsRecord,
    ) -> AgencyRecord:
        requested_agency_id = _clean_optional_text(request.agency_id)
        if requested_agency_id and requested_agency_id != existing_source.agency_id:
            raise ValidationError(
                "Reassigning a wordpress source to a different agency is not supported by this endpoint.",
                code="ADMIN_AGENCY_REASSIGNMENT_NOT_SUPPORTED",
                context={
                    "site_id": existing_source.site_id,
                    "existing_agency_id": existing_source.agency_id,
                    "requested_agency_id": requested_agency_id,
                },
                hint="Keep the existing agency_id and update its metadata, or add a dedicated transfer workflow later.",
            )

        agency = unit_of_work.agency_store.get_by_id(existing_source.agency_id)
        if agency is None:
            raise ResourceNotFoundError(
                "The agency linked to this wordpress source does not exist.",
                code="ADMIN_AGENCY_NOT_FOUND",
                context={"agency_id": existing_source.agency_id, "site_id": existing_source.site_id},
                hint="Repair the tenant data before updating this wordpress source.",
            )
        return agency


@dataclass(frozen=True, slots=True)
class _AgencyResolution:
    record: AgencyRecord
    created: bool


def _normalize_site_id(value: str | None) -> str:
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


def _normalize_site_url(value: str | None, *, site_id: str) -> str:
    raw_value = _clean_optional_text(value)
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


def _normalize_host(value: str | None) -> str:
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


def _normalize_status(value: str, *, code: str, field_name: str) -> str:
    normalized_value = str(value or "").strip().lower()
    if not normalized_value:
        raise ValidationError(
            f"The {field_name} is required.",
            code=code,
            context={"field": field_name},
            hint=f"Send a non-empty {field_name} such as active or inactive.",
        )
    return normalized_value


def _require_text(value: str | None, *, code: str, field_name: str) -> str:
    normalized_value = _clean_optional_text(value)
    if normalized_value:
        return normalized_value
    raise ValidationError(
        f"The {field_name} is required.",
        code=code,
        context={"field": field_name},
        hint=f"Send a non-empty {field_name} value in the admin request body.",
    )


def _resolve_agency_slug(
    *,
    requested_slug: str | None,
    agency_name: str,
    fallback: str,
) -> str:
    base_value = _clean_optional_text(requested_slug) or agency_name
    slug = _slugify(base_value, fallback=fallback)
    if not slug:
        raise ValidationError(
            "The agency_slug is invalid.",
            code="ADMIN_AGENCY_SLUG_INVALID",
            context={"agency_slug": requested_slug or "", "agency_name": agency_name},
            hint="Use only letters, numbers, and separators in agency_slug.",
        )
    return slug


def _slugify(value: str, *, fallback: str) -> str:
    normalized_value = str(value or "").strip().lower()
    slug = _SLUG_PATTERN.sub("-", normalized_value).strip("-")
    if slug:
        return slug
    normalized_fallback = str(fallback or "").strip().lower()
    return _SLUG_PATTERN.sub("-", normalized_fallback).strip("-")


def _validate_agency_slug_conflict(
    unit_of_work: UnitOfWork,
    *,
    agency_id: str,
    desired_slug: str,
) -> None:
    existing_agency = unit_of_work.agency_store.get_by_slug(desired_slug)
    if existing_agency is None or existing_agency.agency_id == agency_id:
        return
    raise ValidationError(
        "The agency slug is already in use.",
        code="ADMIN_AGENCY_SLUG_CONFLICT",
        context={"agency_slug": desired_slug, "agency_id": existing_agency.agency_id},
        hint="Use a different agency_slug or reference the existing agency_id explicitly.",
    )


def _clean_optional_text(value: str | None) -> str | None:
    normalized_value = str(value or "").strip()
    return normalized_value or None


def _build_testing_upsert_request(
    *,
    site_id: str,
    existing_source: WordPressSourceDetailsRecord | None,
) -> UpsertWordPressSourceRequest:
    default_name = f"Auto Provisioned {site_id}"
    default_slug = f"auto-{site_id.replace('.', '-')}"
    if existing_source is None:
        return UpsertWordPressSourceRequest(
            site_id=site_id,
            source_name=default_name,
            agency_name=default_name,
            agency_slug=default_slug,
            agency_timezone="UTC",
            agency_status="active",
            site_url=f"https://{site_id}",
            normalized_host=site_id,
            source_status="active",
        )
    return UpsertWordPressSourceRequest(
        site_id=site_id,
        source_name=existing_source.name or default_name,
        agency_id=existing_source.agency_id,
        agency_name=existing_source.agency_name or default_name,
        agency_slug=existing_source.agency_slug or default_slug,
        agency_timezone=existing_source.agency_timezone or "UTC",
        agency_status="active",
        site_url=existing_source.site_url or f"https://{site_id}",
        normalized_host=existing_source.normalized_host or site_id,
        source_status="active",
    )


__all__ = [
    "UpsertWordPressSourceRequest",
    "UpsertWordPressSourceResult",
    "WordPressSourceAdminService",
]
