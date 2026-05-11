"""Delete an agency and rely on FK cascades for dependent rows."""

from __future__ import annotations

from shared.db import DatabaseUnitOfWork

from modules.tenancy.application.use_cases._agency_support import agency_not_found_error


class DecommissionAgencyUseCase:
    def execute(self, *, uow: DatabaseUnitOfWork, agency_id: str) -> None:
        if uow.tenancy is None:
            raise RuntimeError("The unit of work is not active.")
        deleted = uow.tenancy.agencies.delete(agency_id)
        if not deleted:
            raise agency_not_found_error(agency_id)


__all__ = ["DecommissionAgencyUseCase"]
