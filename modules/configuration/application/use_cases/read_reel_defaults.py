"""Read the agency's reel rendering defaults."""

from __future__ import annotations

from modules.configuration.domain import ReelDefaults
from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
)
from shared.db import DatabaseUnitOfWork


class ReadReelDefaultsUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> ReelDefaults | None:
        if uow.configuration is None:
            raise RuntimeError("The unit of work is not active.")
        ensure_agency_exists(uow, agency_id)
        return uow.configuration.defaults.get(str(agency_id or "").strip())


__all__ = ["ReadReelDefaultsUseCase"]
