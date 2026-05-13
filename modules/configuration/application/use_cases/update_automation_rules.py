"""Update the publish-automation rules for an agency.

This use case writes only to `agency_automation_rules`. `platforms` is
the canonical responsibility of `update_reel_defaults`; automation never
writes that column.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from modules.configuration.domain import AutomationRules
from modules.configuration.application.use_cases._agency_support import (
    ensure_agency_exists,
)
from shared.db import DatabaseUnitOfWork


@dataclass(frozen=True, slots=True)
class UpdateAutomationRulesInput:
    agency_id: str
    approval_required: bool | None = None
    publish_window_start: str | None = None
    publish_window_end: str | None = None
    publish_days: Iterable[str] | None = None
    trigger_on_status: Iterable[str] | None = None
    hold_window_seconds: int | None = None
    quiet_hours_enabled: bool | None = None
    skip_weekends: bool | None = None


class UpdateAutomationRulesUseCase:
    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        data: UpdateAutomationRulesInput,
    ) -> AutomationRules:
        if uow.configuration is None:
            raise RuntimeError("The unit of work is not active.")
        agency_id = str(data.agency_id or "").strip()
        ensure_agency_exists(uow, agency_id)
        return uow.configuration.automation.upsert(
            agency_id=agency_id,
            approval_required=data.approval_required,
            publish_window_start=data.publish_window_start,
            publish_window_end=data.publish_window_end,
            publish_days=data.publish_days,
            trigger_on_status=data.trigger_on_status,
            hold_window_seconds=data.hold_window_seconds,
            quiet_hours_enabled=data.quiet_hours_enabled,
            skip_weekends=data.skip_weekends,
        )


__all__ = ["UpdateAutomationRulesInput", "UpdateAutomationRulesUseCase"]
