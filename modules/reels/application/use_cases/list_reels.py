"""List the most recent reels for an agency (admin "Reels" view)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from modules.reels.application.use_cases._admin_support import ensure_agency_exists
from shared.db import DatabaseUnitOfWork

if TYPE_CHECKING:
    from modules.reels.infrastructure.reel_query import AgencyReelSummary


class ListReelsUseCase:
    """Read-only use case that returns the agency's recent reels.

    The heavy lifting (cross-aggregate JOIN) lives in
    `uow.reels.queries.list_recent_for_agency`. This use case adds tenant
    existence validation and limit clamping.
    """

    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
        limit: int = 50,
    ) -> tuple[AgencyReelSummary, ...]:
        if uow.reels is None:
            raise RuntimeError("The unit of work is not active.")
        ensure_agency_exists(uow, agency_id)
        return uow.reels.queries.list_recent_for_agency(
            agency_id=str(agency_id or "").strip(),
            limit=int(limit),
        )


__all__ = ["ListReelsUseCase"]
