"""Read the agency's publish-automation rules."""

from __future__ import annotations

from modules.configuration.domain import AutomationRules
from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
)
from shared.db import DatabaseUnitOfWork


class ReadAutomationRulesUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> AutomationRules | None:
        if uow.configuration is None:
            raise RuntimeError("The unit of work is not active.")
        ensure_agency_exists(uow, agency_id)
        return uow.configuration.automation.get(str(agency_id or "").strip())


__all__ = ["ReadAutomationRulesUseCase"]
