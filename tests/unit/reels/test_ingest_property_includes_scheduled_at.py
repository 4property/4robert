"""Unit tests for feature 15: ``ingest_property_into_reel`` ``scheduled_at``.

Coverage matrix for :class:`IngestPropertyIntoReelUseCase`'s
``_apply_scheduled_publish_slot`` helper (and its observable effect on
the returned ``PropertyContext.publish_context.scheduled_at``):

1. Quiet hours active, weekday outside the window, ``approval_required=False``
   → context has ``scheduled_at`` populated with a future ISO8601 UTC.
2. All Automation toggles off → ``scheduled_at`` stays ``None`` (preserves
   the pre-feature-13 "publish immediately" contract).
3. ``approval_required=True`` with quiet hours active → the slot **is
   still computed** (design decision: the helper is pure and cheap;
   ``regenerate_reel`` can take advantage of it on approve). The test
   asserts that ``scheduled_at`` is populated even though downstream the
   flow will park the reel.
4. ``social_publishing_enabled=False`` → ``publish_context is None`` and
   the helper returns ``None`` without attempting a ``replace(None, ...)``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from modules.configuration.domain import AutomationRules
from modules.reels.application.use_cases import ingest_property_into_reel as ipir
from modules.reels.application.use_cases.ingest_property_into_reel import (
    IngestPropertyIntoReelUseCase,
)
from modules.reels.domain.types import PropertyMediaJob, SocialPublishContext
from modules.tenancy.domain.context import TenantContext


_PAYLOAD: dict[str, Any] = {
    "id": 7,
    "slug": "casa-feliz",
    "title": {"rendered": "Casa Feliz"},
    "link": "https://example.com/casa-feliz",
    "property_status": "for sale",
    "price": "100000",
    "wppd_pics": ["https://example.com/img1.jpg"],
}


# ---------------------------------------------------------------------------
# Stubs (intentionally lightweight — reuse the pattern of
# tests/unit/reels/test_ingest_property_into_reel.py instead of the
# delivery-heavy ``_uow_stubs.py`` ``build_uow`` since this test only
# needs the slot-computation path).
# ---------------------------------------------------------------------------


class _StubProperties:
    def __init__(self) -> None:
        self.upserts: list[dict[str, Any]] = []

    def upsert_property(self, record: dict[str, Any]) -> int:
        self.upserts.append(dict(record))
        return 1


class _StubReelStates:
    def __init__(self) -> None:
        self.saved: list[Any] = []

    def get(self, *, external_source_id: str, source_property_id: int) -> Any:
        del external_source_id, source_property_id
        return None

    def save(self, state: Any) -> None:
        self.saved.append(state)


class _StubAutomation:
    def __init__(self, rules: AutomationRules | None) -> None:
        self.rules = rules
        self.calls: list[str] = []

    def get(self, agency_id: str) -> AutomationRules | None:
        self.calls.append(str(agency_id or ""))
        return self.rules


class _StubAgencies:
    def __init__(self, *, timezone: str = "UTC", present: bool = True) -> None:
        self.timezone = timezone
        self.present = present
        self.calls: list[str] = []

    def get_by_id(self, agency_id: str) -> Any:
        self.calls.append(str(agency_id or ""))
        if not self.present:
            return None
        return SimpleNamespace(agency_id=agency_id, timezone=self.timezone)


class _StubDefaults:
    def get(self, agency_id: str) -> Any:
        del agency_id
        return None


class _StubRenderTemplates:
    def get(self, template_id: str) -> Any:
        del template_id
        return None


class _StubBrand:
    def get(self, agency_id: str) -> Any:
        del agency_id
        return None


def _build_automation_rules(
    *,
    agency_id: str = "agency-1",
    approval_required: bool = False,
    hold_window_seconds: int = 0,
    quiet_hours_enabled: bool = False,
    skip_weekends: bool = False,
    publish_window_start: str = "09:00",
    publish_window_end: str = "18:00",
    publish_days: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri"),
) -> AutomationRules:
    return AutomationRules(
        agency_id=agency_id,
        approval_required=approval_required,
        publish_window_start=publish_window_start,
        publish_window_end=publish_window_end,
        publish_days=publish_days,
        trigger_on_status=("for_sale",),
        hold_window_seconds=int(hold_window_seconds),
        quiet_hours_enabled=quiet_hours_enabled,
        skip_weekends=skip_weekends,
        created_at="",
        updated_at="",
    )


def _build_uow(
    *,
    automation_rules: AutomationRules | None = None,
    agency_timezone: str = "Europe/Dublin",
    agency_present: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        catalog=SimpleNamespace(properties=_StubProperties()),
        reels=SimpleNamespace(states=_StubReelStates()),
        configuration=SimpleNamespace(
            defaults=_StubDefaults(),
            automation=_StubAutomation(automation_rules),
            render_templates=_StubRenderTemplates(),
            brand=_StubBrand(),
        ),
        tenancy=SimpleNamespace(
            agencies=_StubAgencies(timezone=agency_timezone, present=agency_present),
        ),
    )


def _build_publish_context() -> SocialPublishContext:
    """Build a ``SocialPublishContext`` so ``social_publishing_enabled=True``
    has something to forward through the use case."""
    return SocialPublishContext(
        provider="gohighlevel",
        location_id="loc-1",
        access_token="tok-1",
        platforms=("tiktok",),
        approval_required=False,
        social_templates=(),
        scheduled_at=None,
        render_template_id="classic",
    )


def _build_job(
    *,
    publish_context: SocialPublishContext | None,
) -> PropertyMediaJob:
    tenant = TenantContext(
        site_id="site-a",
        agency_id="agency-1",
        wordpress_source_id="ingestion-1",
    )
    return PropertyMediaJob(
        event_id="event-1",
        tenant=tenant,
        property_id=7,
        received_at="2026-05-02T10:00:00+00:00",
        raw_payload_hash="hash-1",
        payload=_PAYLOAD,
        publish_context=publish_context,
        job_id="job-1",
    )


# ---------------------------------------------------------------------------
# Time freezing helper — patches the module-local ``datetime`` reference
# used by ``_apply_scheduled_publish_slot`` so we get a deterministic
# ``now`` without touching the real clock.
# ---------------------------------------------------------------------------


class _FrozenDateTime:
    """``datetime``-compatible wrapper that returns a fixed ``now``."""

    def __init__(self, frozen_now: datetime) -> None:
        self._frozen_now = frozen_now

    def now(self, tz: Any = None) -> datetime:
        if tz is None:
            return self._frozen_now.replace(tzinfo=None)
        return self._frozen_now.astimezone(tz)

    def __getattr__(self, name: str) -> Any:
        # Delegate everything else (``fromisoformat``, ``timedelta``-arithmetic
        # constructors, ``combine``, ``date``, ``time`` …) to the real class so
        # downstream callers (``compute_next_publish_slot``) keep working.
        return getattr(datetime, name)


def _freeze_now(monkeypatch: pytest.MonkeyPatch, frozen_now: datetime) -> None:
    """Pin ``datetime.now(timezone.utc)`` inside the ingest use case."""
    monkeypatch.setattr(ipir, "datetime", _FrozenDateTime(frozen_now))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_ingest_property_includes_scheduled_at_when_quiet_hours_active(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Webhook auto-publish honours the next Automation slot.

    Seeds quiet hours 09:00–18:00 in Europe/Dublin and pins ``now`` to
    23:00 Dublin (= 22:00 UTC on a Tuesday). The expected slot is the
    next 09:00 Dublin (= 08:00 UTC on Wednesday).
    """
    rules = _build_automation_rules(
        quiet_hours_enabled=True,
        publish_window_start="09:00",
        publish_window_end="18:00",
        publish_days=("mon", "tue", "wed", "thu", "fri"),
    )
    uow = _build_uow(automation_rules=rules, agency_timezone="Europe/Dublin")

    # Tuesday 2026-05-12 23:00 Dublin → 22:00 UTC. Dublin observes BST
    # in May (UTC+1), so we feed UTC and let the algorithm convert.
    frozen_now_utc = datetime(2026, 5, 12, 22, 0, tzinfo=timezone.utc)
    _freeze_now(monkeypatch, frozen_now_utc)

    use_case = IngestPropertyIntoReelUseCase(
        workspace_dir=tmp_path,
        property_url_template="",
        property_url_tracking_params=None,
        social_publishing_enabled=True,
    )
    context = use_case.execute(
        _build_job(publish_context=_build_publish_context()), uow=uow
    )

    assert context.publish_context is not None
    scheduled_at_iso = context.publish_context.scheduled_at
    assert scheduled_at_iso is not None and scheduled_at_iso, scheduled_at_iso

    # Decode the ISO string and verify it lands at the next 09:00 Dublin
    # (Wednesday 2026-05-13). Dublin is UTC+1 in May → 08:00 UTC.
    parsed = datetime.fromisoformat(scheduled_at_iso)
    assert parsed.tzinfo is not None
    parsed_utc = parsed.astimezone(timezone.utc)
    parsed_dublin = parsed.astimezone(ZoneInfo("Europe/Dublin"))
    assert parsed_dublin.date().isoformat() == "2026-05-13"
    assert parsed_dublin.hour == 9 and parsed_dublin.minute == 0
    assert parsed_utc > frozen_now_utc  # strictly in the future


def test_ingest_property_no_scheduled_at_when_all_toggles_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All three Automation toggles off → ``scheduled_at`` stays ``None``.

    Preserves the pre-feature-13 immediate-publish contract.
    """
    rules = _build_automation_rules(
        hold_window_seconds=0,
        quiet_hours_enabled=False,
        skip_weekends=False,
    )
    uow = _build_uow(automation_rules=rules, agency_timezone="Europe/Dublin")
    _freeze_now(monkeypatch, datetime(2026, 5, 12, 22, 0, tzinfo=timezone.utc))

    use_case = IngestPropertyIntoReelUseCase(
        workspace_dir=tmp_path,
        property_url_template="",
        property_url_tracking_params=None,
        social_publishing_enabled=True,
    )
    context = use_case.execute(
        _build_job(publish_context=_build_publish_context()), uow=uow
    )

    assert context.publish_context is not None
    assert context.publish_context.scheduled_at is None


def test_ingest_property_approval_required_true_does_not_block_scheduled_at(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``approval_required=True`` does NOT short-circuit slot computation.

    Design decision documented on :func:`_apply_scheduled_publish_slot`:
    the slot is always computed (the helper is pure and cheap) so the
    subsequent manual approve can inspect it. The downstream reel stays
    parked because the orchestrator/publisher looks at
    ``publish_context.approval_required``, not this field.
    """
    rules = _build_automation_rules(
        approval_required=True,
        quiet_hours_enabled=True,
        publish_window_start="09:00",
        publish_window_end="18:00",
    )
    uow = _build_uow(automation_rules=rules, agency_timezone="Europe/Dublin")
    _freeze_now(monkeypatch, datetime(2026, 5, 12, 22, 0, tzinfo=timezone.utc))

    use_case = IngestPropertyIntoReelUseCase(
        workspace_dir=tmp_path,
        property_url_template="",
        property_url_tracking_params=None,
        social_publishing_enabled=True,
    )
    context = use_case.execute(
        _build_job(publish_context=_build_publish_context()), uow=uow
    )

    assert context.publish_context is not None
    # The slot is still computed even though the reel will be parked.
    assert context.publish_context.scheduled_at is not None
    parsed = datetime.fromisoformat(context.publish_context.scheduled_at)
    assert parsed.tzinfo is not None
    # ``approval_required`` on the SocialPublishContext is set by the
    # job/webhook upstream, not by this helper — the field we just
    # checked is independent.


def test_ingest_property_no_publish_context_does_not_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``social_publishing_enabled=False`` → ``publish_context`` is ``None``.

    The helper must NOT attempt ``replace(None, scheduled_at=...)``; the
    ingest flow must complete cleanly so the reel state is still
    persisted with ``publish_status='skipped'``.
    """
    rules = _build_automation_rules(
        quiet_hours_enabled=True,
        publish_window_start="09:00",
        publish_window_end="18:00",
    )
    uow = _build_uow(automation_rules=rules, agency_timezone="Europe/Dublin")
    _freeze_now(monkeypatch, datetime(2026, 5, 12, 22, 0, tzinfo=timezone.utc))

    use_case = IngestPropertyIntoReelUseCase(
        workspace_dir=tmp_path,
        property_url_template="",
        property_url_tracking_params=None,
        social_publishing_enabled=False,  # → publish_context resolved to None.
    )
    # Even if the job carries a SocialPublishContext, the use case drops
    # it because ``social_publishing_enabled=False``. So pass None to
    # mirror the real webhook→worker flow when publishing is disabled.
    context = use_case.execute(_build_job(publish_context=None), uow=uow)

    assert context.publish_context is None
    # No crash, no save was skipped because of this, the use case keeps
    # behaving as it did before feature 15.
    assert isinstance(context.content_snapshot_json, str)
