"""Unit tests for ReadAggregatedReelProfileUseCase."""

from __future__ import annotations

import pytest

from modules.configuration.application.use_cases.read_aggregated_reel_profile import (
    ReadAggregatedReelProfileUseCase,
)
from modules.configuration.domain import (
    AutomationRules,
    BrandSettings,
    ReelDefaults,
)
from shared.errors import ResourceNotFoundError
from tests.unit.configuration._uow_stubs import (
    StubAutomation,
    StubBrand,
    StubDefaults,
    build_uow,
)


def test_read_aggregated_reel_profile_returns_none_when_no_section_rows() -> None:
    uow = build_uow()
    result = ReadAggregatedReelProfileUseCase().execute(
        uow=uow, agency_id="agency-1"
    )
    assert result is None


def test_read_aggregated_reel_profile_composes_legacy_shape() -> None:
    brand = BrandSettings(
        agency_id="agency-1",
        primary_color="#FF0000",
        secondary_color="#0000FF",
        logo_position="bottom-left",
        logo_object_key="",
        intro_logo_object_key="",
        font_family="Inter",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-02T00:00:00Z",
    )
    defaults = ReelDefaults(
        agency_id="agency-1",
        platforms=("instagram", "tiktok"),
        duration_seconds=45,
        music_id="track-1",
        intro_enabled=False,
        caption_template="{{title}}",
        settings={"watermark": True},
        created_at="2026-01-03T00:00:00Z",
        updated_at="2026-01-04T00:00:00Z",
    )
    automation = AutomationRules(
        agency_id="agency-1",
        approval_required=True,
        publish_window_start="09:00",
        publish_window_end="18:00",
        publish_days=("mon",),
        trigger_on_status=("for_sale",),
        created_at="2026-01-05T00:00:00Z",
        updated_at="2026-01-06T00:00:00Z",
    )
    uow = build_uow(
        brand=StubBrand(existing=brand),
        defaults=StubDefaults(existing=defaults),
        automation=StubAutomation(existing=automation),
    )

    result = ReadAggregatedReelProfileUseCase().execute(
        uow=uow, agency_id="agency-1"
    )
    assert result is not None
    payload = result.to_public_dict()
    assert payload["profile_id"] == "agency-1"
    assert payload["agency_id"] == "agency-1"
    assert payload["platforms"] == ["instagram", "tiktok"]
    assert payload["duration_seconds"] == 45
    assert payload["music_id"] == "track-1"
    assert payload["intro_enabled"] is False
    assert payload["logo_position"] == "bottom-left"
    assert payload["brand_primary_color"] == "#FF0000"
    assert payload["brand_secondary_color"] == "#0000FF"
    assert payload["caption_template"] == "{{title}}"
    assert payload["approval_required"] is True
    assert payload["extra_settings"]["watermark"] is True
    # Defaults timestamp wins (legacy precedence).
    assert payload["created_at"] == "2026-01-03T00:00:00Z"
    assert payload["updated_at"] == "2026-01-04T00:00:00Z"


def test_read_aggregated_reel_profile_raises_for_unknown_agency() -> None:
    uow = build_uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        ReadAggregatedReelProfileUseCase().execute(
            uow=uow, agency_id="missing"
        )
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"
