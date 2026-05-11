"""Unit tests for `InspectReelUseCase`."""

from __future__ import annotations

import pytest

from modules.reels.application.use_cases.inspect_reel import InspectReelUseCase
from shared.errors import ResourceNotFoundError
from tests.unit.reels._uow_stubs import StubReelQuery, build_uow, make_summary


def test_inspect_reel_returns_matching_summary() -> None:
    target = make_summary(external_source_id="ckp.ie", source_property_id=42)
    other = make_summary(external_source_id="ckp.ie", source_property_id=99)
    uow = build_uow(queries=StubReelQuery(items=(other, target)))

    result = InspectReelUseCase().execute(
        uow=uow,
        agency_id="agency-1",
        site_id="CKP.IE",
        source_property_id=42,
    )

    assert result is target


def test_inspect_reel_raises_when_agency_missing() -> None:
    uow = build_uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        InspectReelUseCase().execute(
            uow=uow, agency_id="x", site_id="y", source_property_id=1
        )
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"


def test_inspect_reel_raises_when_reel_missing() -> None:
    uow = build_uow(queries=StubReelQuery(items=()))
    with pytest.raises(ResourceNotFoundError) as exc_info:
        InspectReelUseCase().execute(
            uow=uow,
            agency_id="agency-1",
            site_id="ckp.ie",
            source_property_id=42,
        )
    assert exc_info.value.code == "ADMIN_REEL_NOT_FOUND"
