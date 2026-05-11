"""Inspect one agency by id."""

from __future__ import annotations

from modules.tenancy.domain import Agency
from shared.db import DatabaseUnitOfWork

from modules.tenancy.application.use_cases._agency_support import agency_not_found_error


class InspectAgencyUseCase:
    def execute(self, *, uow: DatabaseUnitOfWork, agency_id: str) -> Agency:
        if uow.tenancy is None:
            raise RuntimeError("The unit of work is not active.")
        agency = uow.tenancy.agencies.get_by_id(agency_id)
        if agency is None:
            raise agency_not_found_error(agency_id)
        return agency


__all__ = ["InspectAgencyUseCase"]
