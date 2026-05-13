"""Unit tests for UpdateAutomationRulesUseCase."""

from __future__ import annotations

import pytest

from modules.configuration.application.use_cases.update_automation_rules import (
    UpdateAutomationRulesInput,
    UpdateAutomationRulesUseCase,
)
from shared.errors import ResourceNotFoundError
from tests.unit.configuration._uow_stubs import StubAutomation, build_uow


def test_update_automation_forwards_payload_to_repository() -> None:
    automation = StubAutomation()
    uow = build_uow(automation=automation)
    UpdateAutomationRulesUseCase().execute(
        uow=uow,
        data=UpdateAutomationRulesInput(
            agency_id="agency-1",
            approval_required=True,
            publish_window_start="09:00",
            publish_window_end="20:00",
            publish_days=["mon", "tue", "wed"],
            trigger_on_status=["for_sale", "to_let"],
            hold_window_seconds=1800,
            quiet_hours_enabled=True,
            skip_weekends=True,
        ),
    )
    call = automation.upsert_calls[0]
    assert call["agency_id"] == "agency-1"
    assert call["approval_required"] is True
    assert call["publish_window_start"] == "09:00"
    assert call["publish_window_end"] == "20:00"
    assert list(call["publish_days"]) == ["mon", "tue", "wed"]
    assert list(call["trigger_on_status"]) == ["for_sale", "to_let"]
    assert call["hold_window_seconds"] == 1800
    assert call["quiet_hours_enabled"] is True
    assert call["skip_weekends"] is True


def test_update_automation_omits_new_fields_when_not_provided() -> None:
    """When the PUT omits hold/quiet/skip, the use case must forward None to
    the repository so the merge layer preserves the previously stored values
    (defaults only apply on the initial INSERT)."""

    automation = StubAutomation()
    uow = build_uow(automation=automation)
    UpdateAutomationRulesUseCase().execute(
        uow=uow,
        data=UpdateAutomationRulesInput(
            agency_id="agency-1",
            approval_required=True,
        ),
    )
    call = automation.upsert_calls[0]
    assert call["hold_window_seconds"] is None
    assert call["quiet_hours_enabled"] is None
    assert call["skip_weekends"] is None


def test_update_automation_does_not_accept_platforms_field() -> None:
    # The dataclass intentionally has no `platforms` field — the test fails
    # at type-check / runtime if a future refactor reintroduces it. This
    # encodes the "defaults owns platforms" invariant.
    fields = UpdateAutomationRulesInput.__dataclass_fields__
    assert "platforms" not in fields


def test_update_automation_raises_when_agency_missing() -> None:
    uow = build_uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        UpdateAutomationRulesUseCase().execute(
            uow=uow,
            data=UpdateAutomationRulesInput(agency_id="missing"),
        )
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"
