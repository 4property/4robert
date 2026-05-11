"""Reconfigure mutable agency fields."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from modules.tenancy.domain import Agency
from shared.db import DatabaseUnitOfWork
from shared.errors import PipelineError

from modules.tenancy.application.use_cases._agency_support import (
    agency_not_found_error,
    build_agency_write_error,
    slugify_agency,
)


@dataclass(frozen=True, slots=True)
class ReconfigureAgencyInput:
    agency_id: str
    name: str | None = None
    slug: str | None = None
    timezone: str | None = None
    status: str | None = None


class ReconfigureAgencyUseCase:
    def execute(self, *, uow: DatabaseUnitOfWork, data: ReconfigureAgencyInput) -> Agency:
        if uow.tenancy is None:
            raise RuntimeError("The unit of work is not active.")
        agency = uow.tenancy.agencies.get_by_id(data.agency_id)
        if agency is None:
            raise agency_not_found_error(data.agency_id)

        next_name = data.name if data.name is not None else agency.name
        next_slug = (
            slugify_agency(data.slug or data.name or agency.slug)
            if data.slug is not None or data.name is not None
            else agency.slug
        )
        next_timezone = data.timezone if data.timezone is not None else agency.timezone
        next_status = str(data.status or agency.status).lower()

        try:
            uow.tenancy.agencies.update(
                agency_id=agency.agency_id,
                name=next_name,
                slug=next_slug,
                timezone=next_timezone,
                status=next_status,
            )
        except IntegrityError as error:
            raise build_agency_write_error(
                error,
                agency_id=agency.agency_id,
                slug=next_slug,
                code="ADMIN_AGENCY_UPDATE_FAILED",
                message="The agency could not be updated.",
            ) from error

        updated = uow.tenancy.agencies.get_by_id(agency.agency_id)
        if updated is None:
            raise PipelineError(
                "The agency could not be updated.",
                stage="persistence",
                code="ADMIN_AGENCY_UPDATE_FAILED",
                retryable=False,
                context={"agency_id": agency.agency_id, "slug": next_slug},
            )
        return updated


__all__ = ["ReconfigureAgencyInput", "ReconfigureAgencyUseCase"]
