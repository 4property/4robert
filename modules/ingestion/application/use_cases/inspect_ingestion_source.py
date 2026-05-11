"""Inspect a single ingestion source by id."""

from __future__ import annotations

from modules.ingestion.application.use_cases._source_support import (
    agency_not_found_error,
    source_not_found_error,
)
from modules.ingestion.domain import IngestionSourceWithAgency
from shared.db import DatabaseUnitOfWork


class InspectIngestionSourceUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
        ingestion_source_id: str,
    ) -> IngestionSourceWithAgency:
        if uow.tenancy is None or uow.ingestion is None:
            raise RuntimeError("The unit of work is not active.")

        normalized_agency_id = str(agency_id or "").strip()
        if uow.tenancy.agencies.get_by_id(normalized_agency_id) is None:
            raise agency_not_found_error(normalized_agency_id)

        normalized_id = str(ingestion_source_id or "").strip()
        sources = uow.ingestion.sources.list_for_agency(normalized_agency_id)
        for item in sources:
            if item.source.ingestion_source_id == normalized_id:
                return item
        raise source_not_found_error(normalized_id)


__all__ = ["InspectIngestionSourceUseCase"]
