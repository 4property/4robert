"""Unit tests for ReadReelDefaultsUseCase."""

from __future__ import annotations

import pytest

from modules.configuration.application.use_cases.read_reel_defaults import (
    ReadReelDefaultsUseCase,
)
from modules.configuration.domain import ReelDefaults
from shared.errors import ResourceNotFoundError
from tests.unit.configuration._uow_stubs import StubDefaults, build_uow


def test_read_defaults_returns_existing_record() -> None:
    record = ReelDefaults(
        agency_id="agency-1",
        platforms=("instagram", "tiktok"),
        duration_seconds=30,
        music_id="default",
        intro_enabled=True,
        caption_template="",
        settings={"currency": "EUR"},
        created_at="",
        updated_at="",
    )
    uow = build_uow(defaults=StubDefaults(existing=record))
    assert (
        ReadReelDefaultsUseCase().execute(uow=uow, agency_id="agency-1") is record
    )


def test_read_defaults_returns_none_when_no_record() -> None:
    uow = build_uow(defaults=StubDefaults(existing=None))
    assert ReadReelDefaultsUseCase().execute(uow=uow, agency_id="agency-1") is None


def test_read_defaults_raises_when_agency_missing() -> None:
    uow = build_uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        ReadReelDefaultsUseCase().execute(uow=uow, agency_id="missing")
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"
