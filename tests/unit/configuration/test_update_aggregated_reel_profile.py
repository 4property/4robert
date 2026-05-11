"""Unit tests for UpdateAggregatedReelProfileUseCase."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from modules.configuration.application.use_cases.update_aggregated_reel_profile import (
    UpdateAggregatedReelProfileInput,
    UpdateAggregatedReelProfileUseCase,
)
from modules.configuration.domain import ReelDefaults
from shared.errors import ResourceNotFoundError
from tests.unit.configuration._uow_stubs import (
    StubAutomation,
    StubBrand,
    StubDefaults,
    build_uow,
)


class _PersistentDefaults(StubDefaults):
    """StubDefaults whose ``upsert`` materialises a real ``ReelDefaults`` row.

    The aggregated update use case reloads via the read use case after
    fanning the writes out, so the stub must reflect the upsert in
    ``get`` for the reload to succeed. This stub is shared between both
    aggregated update tests.
    """

    def upsert(self, **kwargs: Any) -> Any:
        self.upsert_calls.append(kwargs)
        record = ReelDefaults(
            agency_id=str(kwargs.get("agency_id")),
            platforms=tuple(kwargs.get("platforms") or ()),
            duration_seconds=int(kwargs.get("duration_seconds") or 30),
            music_id=str(kwargs.get("music_id") or ""),
            intro_enabled=bool(
                kwargs.get("intro_enabled")
                if kwargs.get("intro_enabled") is not None
                else True
            ),
            caption_template=str(kwargs.get("caption_template") or ""),
            settings=dict(kwargs.get("settings") or {}),
            created_at="now",
            updated_at="now",
        )
        self.existing = record
        return record


def test_update_aggregated_reel_profile_fans_out_to_each_section() -> None:
    brand = StubBrand()
    defaults = _PersistentDefaults()
    automation = StubAutomation()
    uow = build_uow(brand=brand, defaults=defaults, automation=automation)

    UpdateAggregatedReelProfileUseCase().execute(
        uow=uow,
        data=UpdateAggregatedReelProfileInput(
            agency_id="agency-1",
            platforms=["instagram"],
            duration_seconds=20,
            music_id="m1",
            intro_enabled=True,
            logo_position="top-left",
            brand_primary_color="#123456",
            brand_secondary_color="#654321",
            caption_template="hello",
            approval_required=True,
            extra_settings={"watermark": True},
        ),
    )

    assert brand.upsert_calls == [
        {
            "agency_id": "agency-1",
            "primary_color": "#123456",
            "secondary_color": "#654321",
            "logo_position": "top-left",
        }
    ]
    assert defaults.upsert_calls == [
        {
            "agency_id": "agency-1",
            "platforms": ["instagram"],
            "duration_seconds": 20,
            "music_id": "m1",
            "intro_enabled": True,
            "caption_template": "hello",
            "settings": {"watermark": True},
        }
    ]
    assert automation.upsert_calls == [
        {"agency_id": "agency-1", "approval_required": True}
    ]


def test_update_aggregated_reel_profile_skips_brand_when_no_brand_fields() -> None:
    brand = StubBrand()
    defaults = _PersistentDefaults()
    automation = StubAutomation()
    uow = build_uow(brand=brand, defaults=defaults, automation=automation)

    UpdateAggregatedReelProfileUseCase().execute(
        uow=uow,
        data=UpdateAggregatedReelProfileInput(
            agency_id="agency-1",
            platforms=["instagram"],
        ),
    )

    assert brand.upsert_calls == []
    assert len(defaults.upsert_calls) == 1
    assert automation.upsert_calls == []
    # Persisted defaults exposed via ``existing`` so the reload-step works.
    assert defaults.existing is not None
    _ = SimpleNamespace  # imported but only used in some test variants


def test_update_aggregated_reel_profile_raises_for_unknown_agency() -> None:
    uow = build_uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        UpdateAggregatedReelProfileUseCase().execute(
            uow=uow,
            data=UpdateAggregatedReelProfileInput(
                agency_id="missing", approval_required=True
            ),
        )
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"
