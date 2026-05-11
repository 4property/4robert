"""List every WordPress ingestion source across all agencies.

Powers ``GET /v1/admin/wordpress-sources``. Returns a flat snapshot the
admin UI uses for source provisioning. Filters by ``kind == 'wordpress'``
because the global endpoint is WordPress-specific.
"""

from __future__ import annotations

from modules.ingestion.domain import IngestionSourceWithAgency
from shared.db import DatabaseUnitOfWork


class ListGlobalWordPressSourcesUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
    ) -> tuple[IngestionSourceWithAgency, ...]:
        if uow.ingestion is None:
            raise RuntimeError("The unit of work is not active.")
        return tuple(
            row
            for row in uow.ingestion.sources.list_all()
            if (row.source.kind or "").lower() == "wordpress"
        )


__all__ = ["ListGlobalWordPressSourcesUseCase"]
