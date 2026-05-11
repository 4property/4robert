"""Unit tests for ReadAutomationRulesUseCase."""

from __future__ import annotations

import pytest

from modules.configuration.application.use_cases.read_automation_rules import (
    ReadAutomationRulesUseCase,
)
from modules.configuration.domain import AutomationRules
from shared.errors import ResourceNotFoundError
from tests.unit.configuration._uow_stubs import StubAutomation, build_uow


def test_read_automation_returns_existing_record() -> None:
    record = AutomationRules(
        agency_id="agency-1",
        approval_required=True,
        publish_window_start="09:00",
        publish_window_end="20:00",
        publish_days=("mon", "tue"),
        trigger_on_status=("for_sale",),
        created_at="",
        updated_at="",
    )
    uow = build_uow(automation=StubAutomation(existing=record))
    result = ReadAutomationRulesUseCase().execute(uow=uow, agency_id="agency-1")
    assert result is record


def test_read_automation_returns_none_when_no_record() -> None:
    uow = build_uow(automation=StubAutomation(existing=None))
    assert (
        ReadAutomationRulesUseCase().execute(uow=uow, agency_id="agency-1")
        is None
    )


def test_read_automation_raises_when_agency_missing() -> None:
    uow = build_uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        ReadAutomationRulesUseCase().execute(uow=uow, agency_id="missing")
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"
