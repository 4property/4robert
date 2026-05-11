"""Unit tests for `RegenerateReelUseCase`."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from modules.reels.application.use_cases.regenerate_reel import (
    RegenerateReelUseCase,
)
from shared.errors import ResourceNotFoundError
from tests.unit.reels._uow_stubs import (
    StubProperties,
    StubProviderConnections,
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


def _ghl_connection() -> SimpleNamespace:
    return SimpleNamespace(
        external_id="loc-1",
        secrets={"access_token": "tok-1"},
    )


def test_regenerate_reel_enqueues_job_with_full_prereqs() -> None:
    summary = make_summary(external_source_id="ckp.ie", source_property_id=42)
    raw_payload = json.dumps({"id": 42, "title": "x"})
    uow = build_uow(
        states=StubReelStates(existing=_existing_state()),
        queries=StubReelQuery(items=(summary,)),
        properties=StubProperties(raw_payload=raw_payload),
        connections=StubProviderConnections(connection=_ghl_connection()),
    )

    use_case = RegenerateReelUseCase(
        job_max_attempts=3, default_platforms=("instagram",)
    )
    result = use_case.execute(
        uow=uow,
        agency_id="agency-1",
        site_id="CKP.IE",
        source_property_id=42,
    )

    assert result.publish_enqueued is True
    assert result.event_id and result.job_id
    assert result.reel is summary

    assert uow.delivery.jobs.enqueue_calls
    enqueue_request = uow.delivery.jobs.enqueue_calls[0]
    assert enqueue_request.kind == "reel_publish"
    assert enqueue_request.payload == {"id": 42, "title": "x"}
    bundle = json.loads(enqueue_request.provider_secret_bundle)
    assert bundle["access_token"] == "tok-1"
    assert bundle["provider"] == "gohighlevel"
    assert enqueue_request.publish_context["approval_required"] is False
    assert enqueue_request.publish_context["location_id"] == "loc-1"

    assert uow.reels.states.workflow_calls
    assert uow.reels.states.workflow_calls[0]["workflow_state"] == "approved"
    assert uow.reels.states.publish_calls
    assert uow.reels.states.publish_calls[0]["status"] == "pending_publish"


def test_regenerate_reel_returns_prereq_missing_when_no_payload() -> None:
    summary = make_summary(external_source_id="ckp.ie", source_property_id=42)
    uow = build_uow(
        states=StubReelStates(existing=_existing_state()),
        queries=StubReelQuery(items=(summary,)),
        properties=StubProperties(raw_payload=None),
        connections=StubProviderConnections(connection=_ghl_connection()),
    )

    use_case = RegenerateReelUseCase(job_max_attempts=3)
    result = use_case.execute(
        uow=uow,
        agency_id="agency-1",
        site_id="ckp.ie",
        source_property_id=42,
    )

    assert result.publish_enqueued is False
    assert result.reason == "PUBLISH_PREREQUISITES_MISSING"
    assert not uow.delivery.jobs.enqueue_calls


def test_regenerate_reel_returns_prereq_missing_when_no_ghl() -> None:
    summary = make_summary(external_source_id="ckp.ie", source_property_id=42)
    raw_payload = json.dumps({"id": 42})
    uow = build_uow(
        states=StubReelStates(existing=_existing_state()),
        queries=StubReelQuery(items=(summary,)),
        properties=StubProperties(raw_payload=raw_payload),
        connections=StubProviderConnections(connection=None),
    )

    use_case = RegenerateReelUseCase(job_max_attempts=3)
    result = use_case.execute(
        uow=uow,
        agency_id="agency-1",
        site_id="ckp.ie",
        source_property_id=42,
    )

    assert result.publish_enqueued is False
    assert result.reason == "PUBLISH_PREREQUISITES_MISSING"


def test_regenerate_reel_raises_when_agency_missing() -> None:
    uow = build_uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        RegenerateReelUseCase(job_max_attempts=3).execute(
            uow=uow, agency_id="x", site_id="y", source_property_id=1
        )
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"


def test_regenerate_reel_raises_when_reel_state_missing() -> None:
    uow = build_uow(states=StubReelStates(existing=None))
    with pytest.raises(ResourceNotFoundError) as exc_info:
        RegenerateReelUseCase(job_max_attempts=3).execute(
            uow=uow,
            agency_id="agency-1",
            site_id="ckp.ie",
            source_property_id=42,
        )
    assert exc_info.value.code == "ADMIN_REEL_NOT_FOUND"
