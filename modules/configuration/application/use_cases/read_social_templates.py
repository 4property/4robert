"""Read the agency's per-platform social templates."""

from __future__ import annotations

from modules.configuration.domain import SocialTemplate
from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
)
from shared.db import DatabaseUnitOfWork


class ReadSocialTemplatesUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> tuple[SocialTemplate, ...]:
        if uow.configuration is None:
            raise RuntimeError("The unit of work is not active.")
        ensure_agency_exists(uow, agency_id)
        return uow.configuration.social_templates.list_for_agency(
            str(agency_id or "").strip()
        )


__all__ = ["ReadSocialTemplatesUseCase"]
