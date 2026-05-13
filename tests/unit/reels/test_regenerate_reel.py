"""Unit tests for `RegenerateReelUseCase`."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from modules.configuration.domain import AutomationRules
from modules.reels.application.use_cases.regenerate_reel import (
    RegenerateReelUseCase,
)
from shared.errors import ResourceNotFoundError
from tests.unit.reels._uow_stubs import (
    StubAgencies,
    StubAutomation,
    StubJobs,
    StubProperties,
    StubProviderConnections,
    StubReelQuery,
    StubReelStates,
    build_uow,
    make_summary,
)


def _automation_rules(
    *,
    publish_window_start: str = "09:00",
    publish_window_end: str = "17:00",
    publish_days: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri"),
    hold_window_seconds: int = 0,
    quiet_hours_enabled: bool = False,
    skip_weekends: bool = False,
) -> AutomationRules:
    return AutomationRules(
        agency_id="agency-1",
        approval_required=False,
        publish_window_start=publish_window_start,
        publish_window_end=publish_window_end,
        publish_days=publish_days,
        trigger_on_status=("for_sale",),
        hold_window_seconds=hold_window_seconds,
        quiet_hours_enabled=quiet_hours_enabled,
        skip_weekends=skip_weekends,
        created_at="",
        updated_at="",
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
    assert enqueue_request.publish_context["render_template_id"] == "classic"

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


def test_regenerate_reel_is_idempotent_when_active_job_exists() -> None:
    summary = make_summary(external_source_id="ckp.ie", source_property_id=42)
    raw_payload = json.dumps({"id": 42, "title": "x"})
    active = SimpleNamespace(
        job_id="existing-job-id",
        event_id="existing-event-id",
        status="processing",
        created_at="2026-05-12T10:00:00+00:00",
    )
    jobs = StubJobs(active_job=active)
    uow = build_uow(
        states=StubReelStates(existing=_existing_state()),
        queries=StubReelQuery(items=(summary,)),
        properties=StubProperties(raw_payload=raw_payload),
        connections=StubProviderConnections(connection=_ghl_connection()),
        jobs=jobs,
    )

    use_case = RegenerateReelUseCase(job_max_attempts=3)
    result = use_case.execute(
        uow=uow,
        agency_id="agency-1",
        site_id="ckp.ie",
        source_property_id=42,
    )

    assert result.publish_enqueued is True
    assert result.idempotent_replay is True
    assert result.job_id == "existing-job-id"
    assert result.event_id == "existing-event-id"
    # No new job was enqueued and no supersede was triggered.
    assert jobs.enqueue_calls == []
    assert jobs.supersede_calls == []
    # The active-job lookup was actually performed.
    assert jobs.find_active_calls == [
        {
            "external_source_id": "ckp.ie",
            "property_id": 42,
            "kind": "reel_publish",
        }
    ]


def test_regenerate_reel_enqueues_fresh_job_when_no_active_job() -> None:
    summary = make_summary(external_source_id="ckp.ie", source_property_id=42)
    raw_payload = json.dumps({"id": 42, "title": "x"})
    jobs = StubJobs(active_job=None)
    uow = build_uow(
        states=StubReelStates(existing=_existing_state()),
        queries=StubReelQuery(items=(summary,)),
        properties=StubProperties(raw_payload=raw_payload),
        connections=StubProviderConnections(connection=_ghl_connection()),
        jobs=jobs,
    )

    use_case = RegenerateReelUseCase(job_max_attempts=3)
    result = use_case.execute(
        uow=uow,
        agency_id="agency-1",
        site_id="ckp.ie",
        source_property_id=42,
    )

    assert result.publish_enqueued is True
    assert result.idempotent_replay is False
    assert jobs.enqueue_calls, "Expected the use case to enqueue a fresh job."
    assert jobs.find_active_calls, "Expected the active-job lookup."


# ---------------------------------------------------------------------------
# Feature 11 — scheduled_at propagation
# ---------------------------------------------------------------------------


def _build_uow_with_automation(automation_rules: AutomationRules | None) -> SimpleNamespace:
    summary = make_summary(external_source_id="ckp.ie", source_property_id=42)
    raw_payload = json.dumps({"id": 42, "title": "x"})
    return build_uow(
        states=StubReelStates(existing=_existing_state()),
        queries=StubReelQuery(items=(summary,)),
        properties=StubProperties(raw_payload=raw_payload),
        connections=StubProviderConnections(connection=_ghl_connection()),
        automation=StubAutomation(existing=automation_rules),
        jobs=StubJobs(active_job=None),
    )


def test_regenerate_reel_threads_scheduled_at_when_outside_window() -> None:
    # Friday 2026-05-15 22:00 UTC: after Mon–Fri 09:00–17:00 window,
    # so the next slot is Monday 2026-05-18 09:00 UTC.
    # Feature 14: the legacy "defer outside window" behaviour now
    # requires ``quiet_hours_enabled=True``. Stub agency timezone is UTC
    # so the window is interpreted at face value.
    fixed_now = datetime(2026, 5, 15, 22, 0, tzinfo=timezone.utc)
    expected_slot = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc).isoformat()

    uow = _build_uow_with_automation(
        _automation_rules(quiet_hours_enabled=True)
    )

    use_case = RegenerateReelUseCase(job_max_attempts=3)
    with patch(
        "modules.reels.application.use_cases.regenerate_reel.datetime"
    ) as datetime_mock:
        datetime_mock.now.return_value = fixed_now
        result = use_case.execute(
            uow=uow,
            agency_id="agency-1",
            site_id="ckp.ie",
            source_property_id=42,
        )

    assert result.scheduled_at == expected_slot
    assert uow.delivery.jobs.enqueue_calls
    enqueue_request = uow.delivery.jobs.enqueue_calls[0]
    assert enqueue_request.publish_context.get("scheduled_at") == expected_slot


def test_regenerate_reel_scheduled_at_none_when_inside_window() -> None:
    # Wednesday 2026-05-13 10:00 UTC: inside Mon–Fri 09:00–17:00 window
    # → scheduled_at must be None and the job's publish_context carries
    # the explicit ``None``.
    fixed_now = datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)
    uow = _build_uow_with_automation(_automation_rules())

    use_case = RegenerateReelUseCase(job_max_attempts=3)
    with patch(
        "modules.reels.application.use_cases.regenerate_reel.datetime"
    ) as datetime_mock:
        datetime_mock.now.return_value = fixed_now
        result = use_case.execute(
            uow=uow,
            agency_id="agency-1",
            site_id="ckp.ie",
            source_property_id=42,
        )

    assert result.scheduled_at is None
    enqueue_request = uow.delivery.jobs.enqueue_calls[0]
    assert enqueue_request.publish_context["scheduled_at"] is None


def test_regenerate_reel_scheduled_at_none_when_automation_missing() -> None:
    # No automation rules row → use case must surface ``None`` without
    # blowing up.
    fixed_now = datetime(2026, 5, 13, 10, 0, tzinfo=timezone.utc)
    uow = _build_uow_with_automation(None)

    use_case = RegenerateReelUseCase(job_max_attempts=3)
    with patch(
        "modules.reels.application.use_cases.regenerate_reel.datetime"
    ) as datetime_mock:
        datetime_mock.now.return_value = fixed_now
        result = use_case.execute(
            uow=uow,
            agency_id="agency-1",
            site_id="ckp.ie",
            source_property_id=42,
        )

    assert result.scheduled_at is None
    enqueue_request = uow.delivery.jobs.enqueue_calls[0]
    assert enqueue_request.publish_context["scheduled_at"] is None


def test_regenerate_reel_replays_scheduled_at_from_active_job() -> None:
    """An active replay must surface the original ``scheduled_at``."""
    summary = make_summary(external_source_id="ckp.ie", source_property_id=42)
    raw_payload = json.dumps({"id": 42, "title": "x"})
    persisted_slot = datetime(2026, 5, 18, 9, 0, tzinfo=timezone.utc).isoformat()
    active = SimpleNamespace(
        job_id="existing-job-id",
        event_id="existing-event-id",
        status="processing",
        created_at="2026-05-12T10:00:00+00:00",
        publish_context_json=json.dumps({"scheduled_at": persisted_slot}),
    )
    jobs = StubJobs(active_job=active)
    uow = build_uow(
        states=StubReelStates(existing=_existing_state()),
        queries=StubReelQuery(items=(summary,)),
        properties=StubProperties(raw_payload=raw_payload),
        connections=StubProviderConnections(connection=_ghl_connection()),
        jobs=jobs,
    )

    use_case = RegenerateReelUseCase(job_max_attempts=3)
    result = use_case.execute(
        uow=uow,
        agency_id="agency-1",
        site_id="ckp.ie",
        source_property_id=42,
    )

    assert result.idempotent_replay is True
    assert result.scheduled_at == persisted_slot


def test_regenerate_reel_replay_legacy_job_returns_none_for_scheduled_at() -> None:
    """A pre-feature-11 replay (no key in JSON) must surface ``None``."""
    summary = make_summary(external_source_id="ckp.ie", source_property_id=42)
    raw_payload = json.dumps({"id": 42, "title": "x"})
    active = SimpleNamespace(
        job_id="legacy-job-id",
        event_id="legacy-event-id",
        status="queued",
        created_at="2026-05-10T08:00:00+00:00",
        publish_context_json="{}",
    )
    jobs = StubJobs(active_job=active)
    uow = build_uow(
        states=StubReelStates(existing=_existing_state()),
        queries=StubReelQuery(items=(summary,)),
        properties=StubProperties(raw_payload=raw_payload),
        connections=StubProviderConnections(connection=_ghl_connection()),
        jobs=jobs,
    )

    use_case = RegenerateReelUseCase(job_max_attempts=3)
    result = use_case.execute(
        uow=uow,
        agency_id="agency-1",
        site_id="ckp.ie",
        source_property_id=42,
    )

    assert result.idempotent_replay is True
    assert result.scheduled_at is None


# ---------------------------------------------------------------------------
# Feature 14 — agency.timezone is threaded into compute_next_publish_slot
# ---------------------------------------------------------------------------


def test_regenerate_reel_forwards_agency_timezone_to_compute_slot() -> None:
    """``regenerate_reel`` must load the agency and forward its IANA tz.

    Spies the pure use case to assert the kwarg arrives intact.
    """
    summary = make_summary(external_source_id="ckp.ie", source_property_id=42)
    raw_payload = json.dumps({"id": 42, "title": "x"})
    agencies = StubAgencies(present=True, timezone="Europe/Dublin")
    uow = build_uow(
        agencies=agencies,
        states=StubReelStates(existing=_existing_state()),
        queries=StubReelQuery(items=(summary,)),
        properties=StubProperties(raw_payload=raw_payload),
        connections=StubProviderConnections(connection=_ghl_connection()),
        automation=StubAutomation(existing=_automation_rules()),
        jobs=StubJobs(active_job=None),
    )

    captured: dict[str, object] = {}

    def _spy(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return None  # immediate publish → keeps the rest of the path simple

    use_case = RegenerateReelUseCase(job_max_attempts=3)
    with patch(
        "modules.reels.application.use_cases.regenerate_reel.compute_next_publish_slot",
        side_effect=_spy,
    ):
        result = use_case.execute(
            uow=uow,
            agency_id="agency-1",
            site_id="ckp.ie",
            source_property_id=42,
        )

    assert result.publish_enqueued is True
    # The spy was called exactly once with the agency timezone kwarg.
    assert captured["kwargs"] == {"agency_timezone": "Europe/Dublin"}
    # And the underlying repo was hit through ``get_by_id``.
    assert agencies.calls and agencies.calls[-1] == "agency-1"


def test_regenerate_reel_falls_back_to_utc_when_agency_timezone_missing() -> None:
    """Empty ``agency.timezone`` collapses to ``'UTC'`` at the boundary."""
    summary = make_summary(external_source_id="ckp.ie", source_property_id=42)
    raw_payload = json.dumps({"id": 42, "title": "x"})
    agencies = StubAgencies(present=True, timezone="")
    uow = build_uow(
        agencies=agencies,
        states=StubReelStates(existing=_existing_state()),
        queries=StubReelQuery(items=(summary,)),
        properties=StubProperties(raw_payload=raw_payload),
        connections=StubProviderConnections(connection=_ghl_connection()),
        automation=StubAutomation(existing=_automation_rules()),
        jobs=StubJobs(active_job=None),
    )

    captured: dict[str, object] = {}

    def _spy(*args, **kwargs):
        captured["kwargs"] = kwargs
        return None

    use_case = RegenerateReelUseCase(job_max_attempts=3)
    with patch(
        "modules.reels.application.use_cases.regenerate_reel.compute_next_publish_slot",
        side_effect=_spy,
    ):
        use_case.execute(
            uow=uow,
            agency_id="agency-1",
            site_id="ckp.ie",
            source_property_id=42,
        )

    assert captured["kwargs"] == {"agency_timezone": "UTC"}


def test_regenerate_reel_replay_missing_publish_context_returns_none() -> None:
    """An active job without a ``publish_context_json`` attribute (legacy
    stub or NULL row) must still be safe — no crash, ``scheduled_at`` is
    ``None``."""
    summary = make_summary(external_source_id="ckp.ie", source_property_id=42)
    raw_payload = json.dumps({"id": 42, "title": "x"})
    active = SimpleNamespace(
        job_id="bare-job-id",
        event_id="bare-event-id",
        status="processing",
        created_at="2026-05-12T10:00:00+00:00",
    )
    jobs = StubJobs(active_job=active)
    uow = build_uow(
        states=StubReelStates(existing=_existing_state()),
        queries=StubReelQuery(items=(summary,)),
        properties=StubProperties(raw_payload=raw_payload),
        connections=StubProviderConnections(connection=_ghl_connection()),
        jobs=jobs,
    )

    use_case = RegenerateReelUseCase(job_max_attempts=3)
    result = use_case.execute(
        uow=uow,
        agency_id="agency-1",
        site_id="ckp.ie",
        source_property_id=42,
    )

    assert result.idempotent_replay is True
    assert result.scheduled_at is None
