"""List ingestion sources for one agency."""

from __future__ import annotations

from modules.ingestion.application.use_cases._source_support import (
    agency_not_found_error,
)
from modules.ingestion.domain import IngestionSourceWithAgency
from shared.db import DatabaseUnitOfWork


class ListIngestionSourcesUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> tuple[IngestionSourceWithAgency, ...]:
        if uow.tenancy is None or uow.ingestion is None:
            raise RuntimeError("The unit of work is not active.")
        normalized_agency_id = str(agency_id or "").strip()
        if uow.tenancy.agencies.get_by_id(normalized_agency_id) is None:
            raise agency_not_found_error(normalized_agency_id)
        return uow.ingestion.sources.list_for_agency(normalized_agency_id)


__all__ = ["ListIngestionSourcesUseCase"]
