"""Read the agency's brand identity (colours, logo, watermark, outro card)."""

from __future__ import annotations

from modules.configuration.domain import BrandSettings
from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
)
from shared.db import DatabaseUnitOfWork


class ReadBrandSettingsUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> BrandSettings | None:
        if uow.configuration is None:
            raise RuntimeError("The unit of work is not active.")
        ensure_agency_exists(uow, agency_id)
        return uow.configuration.brand.get(str(agency_id or "").strip())


__all__ = ["ReadBrandSettingsUseCase"]
