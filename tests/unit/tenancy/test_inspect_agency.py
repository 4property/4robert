from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.tenancy.application.use_cases.inspect_agency import InspectAgencyUseCase
from modules.tenancy.domain import Agency
from shared.errors import ResourceNotFoundError


def test_inspect_agency_returns_matching_agency() -> None:
    agency = Agency(
        agency_id="agency-1",
        name="Agency One",
        slug="agency-one",
        timezone="Europe/Dublin",
        status="active",
        created_at=None,
        updated_at=None,
    )

    result = InspectAgencyUseCase().execute(uow=_uow(agency), agency_id="agency-1")

    assert result == agency


def test_inspect_agency_raises_not_found_for_unknown_id() -> None:
    with pytest.raises(ResourceNotFoundError) as exc_info:
        InspectAgencyUseCase().execute(uow=_uow(None), agency_id="missing")

    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"
    assert exc_info.value.context == {"agency_id": "missing"}


def _uow(agency: Agency | None) -> SimpleNamespace:
    return SimpleNamespace(
        tenancy=SimpleNamespace(
            agencies=SimpleNamespace(get_by_id=lambda agency_id: agency if agency_id == "agency-1" else None),
        )
    )
