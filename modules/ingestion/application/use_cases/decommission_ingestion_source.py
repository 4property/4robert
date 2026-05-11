"""Delete an ingestion source from an agency."""

from __future__ import annotations

from modules.ingestion.application.use_cases._source_support import (
    agency_not_found_error,
    source_not_found_error,
)
from shared.db import DatabaseUnitOfWork
from shared.errors import ValidationError


class DecommissionIngestionSourceUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
        ingestion_source_id: str,
    ) -> None:
        if uow.tenancy is None or uow.ingestion is None:
            raise RuntimeError("The unit of work is not active.")

        normalized_agency_id = str(agency_id or "").strip()
        if uow.tenancy.agencies.get_by_id(normalized_agency_id) is None:
            raise agency_not_found_error(normalized_agency_id)

        normalized_id = str(ingestion_source_id or "").strip()
        existing = uow.ingestion.sources.get_by_id(normalized_id)
        if existing is None:
            raise source_not_found_error(normalized_id)
        if existing.agency_id != normalized_agency_id:
            raise ValidationError(
                "The ingestion source belongs to another agency.",
                code="ADMIN_SOURCE_AGENCY_MISMATCH",
                context={
                    "ingestion_source_id": normalized_id,
                    "expected_agency_id": existing.agency_id,
                    "requested_agency_id": normalized_agency_id,
                },
            )

        deleted = uow.ingestion.sources.delete(normalized_id)
        if not deleted:
            raise source_not_found_error(normalized_id)


__all__ = ["DecommissionIngestionSourceUseCase"]
