"""Look up a WordPress ingestion source by its ``site_id``.

Powers ``GET /v1/admin/wordpress-sources/{site_id}``. ``site_id`` is the
value the inbound WordPress webhook posts as ``rest_domain`` and is stored
in ``ingestion_sources.external_id`` (lowercased).
"""

from __future__ import annotations

from modules.ingestion.domain import IngestionSourceWithAgency
from modules.ingestion.application.use_cases._wordpress_support import (
    normalize_wordpress_site_id,
)
from shared.db import DatabaseUnitOfWork


class InspectWordPressSourceBySiteIdUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        site_id: str,
    ) -> IngestionSourceWithAgency | None:
        if uow.ingestion is None:
            raise RuntimeError("The unit of work is not active.")
        normalized = normalize_wordpress_site_id(site_id)
        for row in uow.ingestion.sources.list_all():
            if (row.source.kind or "").lower() != "wordpress":
                continue
            if row.source.external_id == normalized:
                return row
        return None


__all__ = ["InspectWordPressSourceBySiteIdUseCase"]
