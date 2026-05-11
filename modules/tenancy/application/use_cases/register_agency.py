"""Register a new agency in the tenancy bounded context."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from modules.tenancy.domain import Agency
from shared.db import DatabaseUnitOfWork
from shared.errors import PipelineError, ValidationError

from modules.tenancy.application.use_cases._agency_support import (
    DEFAULT_AGENCY_STATUS,
    DEFAULT_AGENCY_TIMEZONE,
    build_agency_slug,
    build_agency_write_error,
)


@dataclass(frozen=True, slots=True)
class RegisterAgencyInput:
    name: str
    slug: str | None = None
    timezone: str | None = None
    status: str | None = None


class RegisterAgencyUseCase:
    def execute(self, *, uow: DatabaseUnitOfWork, data: RegisterAgencyInput) -> Agency:
        if uow.tenancy is None:
            raise RuntimeError("The unit of work is not active.")
        normalized_name = str(data.name or "").strip()
        if not normalized_name:
            raise ValidationError(
                "The agency name is required.",
                code="ADMIN_AGENCY_NAME_REQUIRED",
                context={"field": "name"},
            )

        agency_id = str(uuid4())
        slug = build_agency_slug(data.slug or normalized_name)
        timezone = str(data.timezone or DEFAULT_AGENCY_TIMEZONE).strip() or DEFAULT_AGENCY_TIMEZONE
        status = str(data.status or DEFAULT_AGENCY_STATUS).strip().lower() or DEFAULT_AGENCY_STATUS

        try:
            uow.tenancy.agencies.create(
                agency_id=agency_id,
                name=normalized_name,
                slug=slug,
                timezone=timezone,
                status=status,
            )
        except IntegrityError as error:
            raise build_agency_write_error(
                error,
                agency_id=agency_id,
                slug=slug,
                code="ADMIN_AGENCY_CREATE_FAILED",
                message="The agency could not be created.",
            ) from error

        agency = uow.tenancy.agencies.get_by_id(agency_id)
        if agency is None:
            raise PipelineError(
                "The agency could not be created.",
                stage="persistence",
                code="ADMIN_AGENCY_CREATE_FAILED",
                retryable=False,
                context={"agency_id": agency_id, "slug": slug},
            )
        return agency


__all__ = ["RegisterAgencyInput", "RegisterAgencyUseCase"]
