"""Provision (create or update) a WordPress ingestion source by ``site_id``.

Powers ``PUT /v1/admin/wordpress-sources/{site_id}``. Replaces the legacy
``WordPressSourceAdminService.upsert_source`` that lived in
``application/admin/wordpress_source_management.py``. The use case writes
directly to the typed namespaces ``uow.tenancy.agencies`` and
``uow.ingestion.sources`` — no legacy stores.

Auto-create rules:

- If ``agency_id`` is supplied, it must already exist (404 otherwise) and
  reassignment of an existing source to a different agency is refused.
- If ``agency_id`` is omitted *and* the source does not exist yet, the
  endpoint creates a placeholder agency from ``agency_name`` /
  ``agency_slug`` (slug must be unique).

The site URL and normalised hostname are persisted on
``ingestion_sources.config_json`` so the legacy WordPress source view can
keep reading them through the same JSON document.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from modules.ingestion.application.use_cases._wordpress_support import (
    clean_optional_text,
    normalize_host,
    normalize_site_url,
    normalize_status,
    normalize_wordpress_site_id,
    require_text,
    resolve_agency_slug,
)
from modules.ingestion.domain import IngestionSource, IngestionSourceWithAgency
from modules.tenancy.domain import Agency
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError, ResourceNotFoundError, ValidationError


@dataclass(frozen=True, slots=True)
class ProvisionWordPressSourceInput:
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
class ProvisionWordPressSourceResult:
    source: IngestionSourceWithAgency
    created_agency: bool
    updated_agency: bool
    created_source: bool
    updated_source: bool


class ProvisionWordPressSourceUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        data: ProvisionWordPressSourceInput,
    ) -> ProvisionWordPressSourceResult:
        if uow.tenancy is None or uow.ingestion is None:
            raise RuntimeError("The unit of work is not active.")

        normalized_site_id = normalize_wordpress_site_id(data.site_id)
        source_name = require_text(
            data.source_name,
            code="ADMIN_SOURCE_NAME_REQUIRED",
            field_name="source_name",
        )

        existing_source = _get_existing_source(uow, normalized_site_id)

        created_agency = False
        updated_agency = False
        if existing_source is None:
            agency, created_agency = _resolve_agency_for_create(
                uow,
                data,
                site_id=normalized_site_id,
            )
        else:
            agency = _resolve_agency_for_update(
                uow,
                data,
                existing_source=existing_source,
            )

        desired_agency_name = clean_optional_text(data.agency_name) or agency.name
        desired_agency_slug = resolve_agency_slug(
            requested_slug=data.agency_slug,
            agency_name=desired_agency_name,
            fallback=normalized_site_id.replace(".", "-"),
        )
        desired_agency_timezone = (
            clean_optional_text(data.agency_timezone)
            or agency.timezone
            or "Europe/Dublin"
        )
        desired_agency_status = normalize_status(
            data.agency_status or agency.status or "active",
            code="ADMIN_INVALID_AGENCY_STATUS",
            field_name="agency_status",
        )
        _validate_agency_slug_conflict(
            uow,
            agency_id=agency.agency_id,
            desired_slug=desired_agency_slug,
        )
        if (
            desired_agency_name != agency.name
            or desired_agency_slug != agency.slug
            or desired_agency_timezone != agency.timezone
            or desired_agency_status != agency.status
        ):
            uow.tenancy.agencies.update(
                agency_id=agency.agency_id,
                name=desired_agency_name,
                slug=desired_agency_slug,
                timezone=desired_agency_timezone,
                status=desired_agency_status,
            )
            updated_agency = not created_agency

        existing_config = (
            dict(existing_source.source.config) if existing_source is not None else {}
        )
        current_site_url = str(existing_config.get("site_url") or "") if existing_source else None
        resolved_site_url = normalize_site_url(
            data.site_url or current_site_url,
            site_id=normalized_site_id,
        )
        current_host = (
            str(existing_config.get("normalized_host") or "")
            if existing_source is not None
            else None
        )
        resolved_host = normalize_host(
            data.normalized_host or current_host or resolved_site_url or normalized_site_id
        )
        resolved_source_status = normalize_status(
            data.source_status
            or (existing_source.source.status if existing_source is not None else "active"),
            code="ADMIN_INVALID_SOURCE_STATUS",
            field_name="source_status",
        )

        config_json: dict[str, Any] = {
            **existing_config,
            "site_url": resolved_site_url,
            "normalized_host": resolved_host,
        }

        created_source = False
        updated_source = False
        if existing_source is None:
            uow.ingestion.sources.create(
                ingestion_source_id=str(uuid4()),
                agency_id=agency.agency_id,
                kind="wordpress",
                external_id=normalized_site_id,
                name=source_name,
                config=config_json,
                secret=str(data.webhook_secret or ""),
                status=resolved_source_status,
            )
            created_source = True
        else:
            secret_value: str | None = None
            if data.update_webhook_secret:
                secret_value = str(data.webhook_secret or "")
            uow.ingestion.sources.update(
                ingestion_source_id=existing_source.source.ingestion_source_id,
                name=source_name,
                config=config_json,
                status=resolved_source_status,
                secret=secret_value,
            )
            updated_source = True

        persisted = _get_existing_source(uow, normalized_site_id)
        if persisted is None:
            raise ApplicationError(
                "The wordpress source could not be reloaded after provisioning.",
                code="ADMIN_SOURCE_RELOAD_FAILED",
                context={"site_id": normalized_site_id},
                hint="Check the admin logs for the failed transaction and retry the provisioning request.",
            )

        return ProvisionWordPressSourceResult(
            source=persisted,
            created_agency=created_agency,
            updated_agency=updated_agency,
            created_source=created_source,
            updated_source=updated_source,
        )


def _get_existing_source(
    uow: DatabaseUnitOfWork,
    site_id: str,
) -> IngestionSourceWithAgency | None:
    if uow.ingestion is None:
        return None
    for row in uow.ingestion.sources.list_all():
        if (row.source.kind or "").lower() != "wordpress":
            continue
        if row.source.external_id == site_id:
            return row
    return None


def _resolve_agency_for_create(
    uow: DatabaseUnitOfWork,
    data: ProvisionWordPressSourceInput,
    *,
    site_id: str,
) -> tuple[Agency, bool]:
    if uow.tenancy is None:
        raise RuntimeError("The unit of work is not active.")
    requested_agency_id = clean_optional_text(data.agency_id)
    if requested_agency_id:
        agency = uow.tenancy.agencies.get_by_id(requested_agency_id)
        if agency is None:
            raise ResourceNotFoundError(
                "The referenced agency does not exist.",
                code="ADMIN_AGENCY_NOT_FOUND",
                context={"agency_id": requested_agency_id},
                hint="Create the agency first or omit agency_id so the admin endpoint can create it for you.",
            )
        return agency, False

    agency_name = require_text(
        data.agency_name,
        code="ADMIN_AGENCY_NAME_REQUIRED",
        field_name="agency_name",
    )
    agency_slug = resolve_agency_slug(
        requested_slug=data.agency_slug,
        agency_name=agency_name,
        fallback=site_id.replace(".", "-"),
    )
    existing_agency = uow.tenancy.agencies.get_by_slug(agency_slug)
    if existing_agency is not None:
        raise ValidationError(
            "The agency slug is already in use.",
            code="ADMIN_AGENCY_SLUG_CONFLICT",
            context={"agency_slug": agency_slug, "agency_id": existing_agency.agency_id},
            hint="Send the existing agency_id to attach the site to that agency, or choose a different agency_slug.",
        )

    new_agency_id = str(uuid4())
    uow.tenancy.agencies.create(
        agency_id=new_agency_id,
        name=agency_name,
        slug=agency_slug,
        timezone=clean_optional_text(data.agency_timezone) or "Europe/Dublin",
        status=normalize_status(
            data.agency_status or "active",
            code="ADMIN_INVALID_AGENCY_STATUS",
            field_name="agency_status",
        ),
    )
    created = uow.tenancy.agencies.get_by_id(new_agency_id)
    if created is None:
        raise ApplicationError(
            "The agency could not be reloaded after creation.",
            code="ADMIN_AGENCY_RELOAD_FAILED",
            context={"agency_id": new_agency_id},
            hint="Check the admin logs for the failed transaction and retry the provisioning request.",
        )
    return created, True


def _resolve_agency_for_update(
    uow: DatabaseUnitOfWork,
    data: ProvisionWordPressSourceInput,
    *,
    existing_source: IngestionSourceWithAgency,
) -> Agency:
    if uow.tenancy is None:
        raise RuntimeError("The unit of work is not active.")
    requested_agency_id = clean_optional_text(data.agency_id)
    if requested_agency_id and requested_agency_id != existing_source.source.agency_id:
        raise ValidationError(
            "Reassigning a wordpress source to a different agency is not supported by this endpoint.",
            code="ADMIN_AGENCY_REASSIGNMENT_NOT_SUPPORTED",
            context={
                "site_id": existing_source.source.external_id,
                "existing_agency_id": existing_source.source.agency_id,
                "requested_agency_id": requested_agency_id,
            },
            hint="Keep the existing agency_id and update its metadata, or add a dedicated transfer workflow later.",
        )
    agency = uow.tenancy.agencies.get_by_id(existing_source.source.agency_id)
    if agency is None:
        raise ResourceNotFoundError(
            "The agency linked to this wordpress source does not exist.",
            code="ADMIN_AGENCY_NOT_FOUND",
            context={
                "agency_id": existing_source.source.agency_id,
                "site_id": existing_source.source.external_id,
            },
            hint="Repair the tenant data before updating this wordpress source.",
        )
    return agency


def _validate_agency_slug_conflict(
    uow: DatabaseUnitOfWork,
    *,
    agency_id: str,
    desired_slug: str,
) -> None:
    if uow.tenancy is None:
        raise RuntimeError("The unit of work is not active.")
    existing_agency = uow.tenancy.agencies.get_by_slug(desired_slug)
    if existing_agency is None or existing_agency.agency_id == agency_id:
        return
    raise ValidationError(
        "The agency slug is already in use.",
        code="ADMIN_AGENCY_SLUG_CONFLICT",
        context={"agency_slug": desired_slug, "agency_id": existing_agency.agency_id},
        hint="Use a different agency_slug or reference the existing agency_id explicitly.",
    )


# `IngestionSource` is re-exported only to keep the type hint readable for
# callers; remove if PEP 8 lint flags it.
_ = IngestionSource


__all__ = [
    "ProvisionWordPressSourceInput",
    "ProvisionWordPressSourceResult",
    "ProvisionWordPressSourceUseCase",
]
