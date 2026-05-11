"""Unit tests for UpdateReelDefaultsUseCase."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.configuration.application.use_cases.update_reel_defaults import (
    UpdateReelDefaultsInput,
    UpdateReelDefaultsUseCase,
)
from shared.errors import ResourceNotFoundError
from tests.unit.configuration._uow_stubs import StubDefaults, build_uow


def test_update_defaults_writes_platforms() -> None:
    defaults = StubDefaults()
    uow = build_uow(defaults=defaults)
    UpdateReelDefaultsUseCase().execute(
        uow=uow,
        data=UpdateReelDefaultsInput(
            agency_id="agency-1",
            platforms=["instagram", "tiktok"],
            duration_seconds=45,
        ),
    )
    call = defaults.upsert_calls[0]
    assert list(call["platforms"]) == ["instagram", "tiktok"]
    assert call["duration_seconds"] == 45


def test_update_defaults_merges_settings_with_existing() -> None:
    existing = SimpleNamespace(
        agency_id="agency-1",
        platforms=(),
        duration_seconds=30,
        music_id="",
        intro_enabled=True,
        caption_template="",
        settings={"currency": "EUR", "language": "en-IE"},
        created_at="",
        updated_at="",
    )
    defaults = StubDefaults(existing=existing)
    uow = build_uow(defaults=defaults)
    UpdateReelDefaultsUseCase().execute(
        uow=uow,
        data=UpdateReelDefaultsInput(
            agency_id="agency-1",
            settings={"language": "es-ES", "subFont": "Roboto"},
        ),
    )
    merged = defaults.upsert_calls[0]["settings"]
    assert merged == {
        "currency": "EUR",
        "language": "es-ES",
        "subFont": "Roboto",
    }


def test_update_defaults_raises_when_agency_missing() -> None:
    uow = build_uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        UpdateReelDefaultsUseCase().execute(
            uow=uow,
            data=UpdateReelDefaultsInput(agency_id="missing"),
        )
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"
