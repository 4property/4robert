"""Unit tests for UpdateBrandSettingsUseCase."""

from __future__ import annotations

import pytest

from modules.configuration.application.use_cases.update_brand_settings import (
    UpdateBrandSettingsInput,
    UpdateBrandSettingsUseCase,
)
from modules.configuration.infrastructure.brand_repository import UNSET
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
    """Hotfix 2026-05-15: legacy callers (no ``fields_present``) translate
    ``None`` to ``UNSET`` so the repository keeps the existing column.
    The router path uses ``fields_present`` and lets ``None`` mean "clear".
    """
    brand = StubBrand()
    uow = build_uow(brand=brand)
    UpdateBrandSettingsUseCase().execute(
        uow=uow,
        data=UpdateBrandSettingsInput(agency_id="agency-1", primary_color="#111"),
    )
    call = brand.upsert_calls[0]
    # The supplied field travels verbatim.
    assert call["primary_color"] == "#111"
    # Every other ``None`` in the legacy input maps to ``UNSET`` so the
    # repository preserves the previous column value.
    assert call["secondary_color"] is UNSET
    assert call["logo_position"] is UNSET
    assert call["logo_object_key"] is UNSET
    assert call["intro_logo_object_key"] is UNSET
    assert call["font_family"] is UNSET


def test_update_brand_fields_present_clears_with_explicit_null() -> None:
    """When the router passes ``fields_present``, an explicit ``None`` in
    the input means "clear the override" and reaches the repository
    untouched (so the repo persists the empty string)."""
    brand = StubBrand()
    uow = build_uow(brand=brand)
    UpdateBrandSettingsUseCase().execute(
        uow=uow,
        data=UpdateBrandSettingsInput(
            agency_id="agency-1",
            primary_color=None,
            font_family="Manrope",
            fields_present=frozenset({"primary_color", "font_family"}),
        ),
    )
    call = brand.upsert_calls[0]
    # ``primary_color`` is present in the body as null → cleared.
    assert call["primary_color"] is None
    # ``font_family`` is present in the body with a real value → persisted.
    assert call["font_family"] == "Manrope"
    # Everything else was NOT in the body → preserved via ``UNSET``.
    assert call["secondary_color"] is UNSET
    assert call["logo_position"] is UNSET
    assert call["logo_object_key"] is UNSET
    assert call["intro_logo_object_key"] is UNSET


def test_update_brand_raises_when_agency_missing() -> None:
    uow = build_uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        UpdateBrandSettingsUseCase().execute(
            uow=uow,
            data=UpdateBrandSettingsInput(agency_id="missing"),
        )
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"
