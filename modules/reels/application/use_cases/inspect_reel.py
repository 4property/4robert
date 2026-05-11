"""Inspect one reel for an agency (admin "Reels" detail view)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from modules.reels.application.use_cases._admin_support import (
    ensure_agency_exists,
    reel_not_found_error,
)
from shared.db import DatabaseUnitOfWork

if TYPE_CHECKING:
    from modules.reels.infrastructure.reel_query import AgencyReelSummary


class InspectReelUseCase:
    """Returns the flat reel record for `(site_id, source_property_id)`.

    Reuses `list_recent_for_agency` so the JOIN logic stays in one place;
    the small linear filter is acceptable while the page-size cap is 500.
    """

    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
        site_id: str,
        source_property_id: int,
    ) -> AgencyReelSummary:
        if uow.reels is None:
            raise RuntimeError("The unit of work is not active.")
        ensure_agency_exists(uow, agency_id)
        normalized_agency_id = str(agency_id or "").strip()
        normalized_site_id = str(site_id or "").strip().lower()
        normalized_property_id = int(source_property_id)
        for item in uow.reels.queries.list_recent_for_agency(
            agency_id=normalized_agency_id,
            limit=500,
        ):
            if (
                str(item.external_source_id).strip().lower() == normalized_site_id
                and int(item.source_property_id) == normalized_property_id
            ):
                return item
        raise reel_not_found_error(
            agency_id=normalized_agency_id,
            site_id=normalized_site_id,
            source_property_id=normalized_property_id,
        )


__all__ = ["InspectReelUseCase"]
