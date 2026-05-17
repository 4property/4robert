"""Read the per-agency intro asset row (feature 34)."""

from __future__ import annotations

from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
)
from modules.configuration.domain import IntroOutroAsset
from shared.db import DatabaseUnitOfWork


class ReadIntroAssetUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> IntroOutroAsset | None:
        ensure_agency_exists(uow, agency_id)
        assert uow.configuration is not None
        return uow.configuration.intro_outro_assets.get(
            agency_id=str(agency_id or "").strip(),
            kind="intro",
        )


__all__ = ["ReadIntroAssetUseCase"]
