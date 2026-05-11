"""Unit tests for UpdateBrandSettingsUseCase."""

from __future__ import annotations

import pytest

from modules.configuration.application.use_cases.update_brand_settings import (
    UpdateBrandSettingsInput,
    UpdateBrandSettingsUseCase,
)
from shared.errors import ResourceNotFoundError
from tests.unit.configuration._uow_stubs import StubBrand, build_uow


def test_update_brand_forwards_payload_to_repository() -> None:
    brand = StubBrand()
    uow = build_uow(brand=brand)
    UpdateBrandSettingsUseCase().execute(
        uow=uow,
        data=UpdateBrandSettingsInput(
            agency_id="agency-1",
            primary_color="#000000",
            secondary_color="#FFFFFF",
            logo_position="top-left",
            font_family="Inter",
        ),
    )
    assert len(brand.upsert_calls) == 1
    call = brand.upsert_calls[0]
    assert call["agency_id"] == "agency-1"
    assert call["primary_color"] == "#000000"
    assert call["secondary_color"] == "#FFFFFF"
    assert call["logo_position"] == "top-left"
    assert call["font_family"] == "Inter"


def test_update_brand_preserves_unset_fields() -> None:
    brand = StubBrand()
    uow = build_uow(brand=brand)
    UpdateBrandSettingsUseCase().execute(
        uow=uow,
        data=UpdateBrandSettingsInput(agency_id="agency-1", primary_color="#111"),
    )
    call = brand.upsert_calls[0]
    assert call["primary_color"] == "#111"
    assert call["font_family"] is None


def test_update_brand_raises_when_agency_missing() -> None:
    uow = build_uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        UpdateBrandSettingsUseCase().execute(
            uow=uow,
            data=UpdateBrandSettingsInput(agency_id="missing"),
        )
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"
