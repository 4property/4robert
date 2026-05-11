from __future__ import annotations

from types import SimpleNamespace

from modules.tenancy.application.use_cases.list_agencies import ListAgenciesUseCase
from modules.tenancy.domain import Agency


def test_list_agencies_returns_all_agencies_from_repository() -> None:
    agencies = (
        Agency(
            agency_id="agency-1",
            name="Agency One",
            slug="agency-one",
            timezone="Europe/Dublin",
            status="active",
            created_at=None,
            updated_at=None,
        ),
        Agency(
            agency_id="agency-2",
            name="Agency Two",
            slug="agency-two",
            timezone="UTC",
            status="paused",
            created_at=None,
            updated_at=None,
        ),
    )

    result = ListAgenciesUseCase().execute(uow=_uow(agencies))

    assert result == agencies


def _uow(agencies: tuple[Agency, ...]) -> SimpleNamespace:
    return SimpleNamespace(
        tenancy=SimpleNamespace(
            agencies=SimpleNamespace(list_all=lambda: agencies),
        )
    )
