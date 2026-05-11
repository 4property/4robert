"""Unit tests for ReadBrandSettingsUseCase."""

from __future__ import annotations

import pytest

from modules.configuration.application.use_cases.read_brand_settings import (
    ReadBrandSettingsUseCase,
)
from modules.configuration.domain import BrandSettings
from shared.errors import ResourceNotFoundError
from tests.unit.configuration._uow_stubs import StubBrand, build_uow


def test_read_brand_returns_existing_record() -> None:
    record = BrandSettings(
        agency_id="agency-1",
        primary_color="#0F172A",
        secondary_color="#FFFFFF",
        logo_position="top-right",
        logo_object_key="",
        intro_logo_object_key="",
        font_family="Inter",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )
    uow = build_uow(brand=StubBrand(existing=record))
    result = ReadBrandSettingsUseCase().execute(uow=uow, agency_id="agency-1")
    assert result is record


def test_read_brand_returns_none_when_no_record_yet() -> None:
    uow = build_uow(brand=StubBrand(existing=None))
    assert (
        ReadBrandSettingsUseCase().execute(uow=uow, agency_id="agency-1")
        is None
    )


def test_read_brand_raises_when_agency_missing() -> None:
    uow = build_uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        ReadBrandSettingsUseCase().execute(uow=uow, agency_id="missing")
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"
