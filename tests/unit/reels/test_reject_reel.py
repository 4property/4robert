"""Unit tests for `RejectReelUseCase`."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.reels.application.use_cases.reject_reel import RejectReelUseCase
from shared.errors import ResourceNotFoundError
from tests.unit.reels._uow_stubs import (
    StubReelQuery,
    StubReelStates,
    build_uow,
    make_summary,
)


def _existing_state() -> SimpleNamespace:
    return SimpleNamespace(
        agency_id="agency-1",
        ingestion_source_id="ingestion-1",
    )


def test_reject_reel_marks_workflow_and_publish_as_rejected() -> None:
    summary = make_summary(
        external_source_id="ckp.ie",
        source_property_id=42,
        workflow_state="rejected",
        publish_status="rejected",
    )
    states = StubReelStates(existing=_existing_state())
    queries = StubReelQuery(items=(summary,))
    uow = build_uow(states=states, queries=queries)

    result = RejectReelUseCase().execute(
        uow=uow,
        agency_id="agency-1",
        site_id="CKP.IE",
        source_property_id=42,
    )

    assert result is summary
    assert states.workflow_calls
    assert states.workflow_calls[0]["workflow_state"] == "rejected"
    assert states.publish_calls
    assert states.publish_calls[0]["status"] == "rejected"


def test_reject_reel_raises_when_agency_missing() -> None:
    uow = build_uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        RejectReelUseCase().execute(
            uow=uow, agency_id="x", site_id="y", source_property_id=1
        )
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"


def test_reject_reel_raises_when_reel_state_missing() -> None:
    uow = build_uow(states=StubReelStates(existing=None))
    with pytest.raises(ResourceNotFoundError) as exc_info:
        RejectReelUseCase().execute(
            uow=uow,
            agency_id="agency-1",
            site_id="ckp.ie",
            source_property_id=42,
        )
    assert exc_info.value.code == "ADMIN_REEL_NOT_FOUND"
