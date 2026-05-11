from __future__ import annotations

from types import SimpleNamespace

from modules.tenancy.application.use_cases.reconfigure_agency import (
    ReconfigureAgencyInput,
    ReconfigureAgencyUseCase,
)
from modules.tenancy.domain import Agency


def test_reconfigure_agency_keeps_slug_when_only_timezone_changes() -> None:
    repo = _AgenciesRepo()

    updated = ReconfigureAgencyUseCase().execute(
        uow=_uow(repo),
        data=ReconfigureAgencyInput(
            agency_id="agency-1",
            timezone="UTC",
        ),
    )

    assert updated.slug == "agency-one"
    assert updated.timezone == "UTC"


def test_reconfigure_agency_derives_slug_from_new_name() -> None:
    repo = _AgenciesRepo()

    updated = ReconfigureAgencyUseCase().execute(
        uow=_uow(repo),
        data=ReconfigureAgencyInput(
            agency_id="agency-1",
            name="Agency One Dublin",
            status="PAUSED",
        ),
    )

    assert updated.name == "Agency One Dublin"
    assert updated.slug == "agency-one-dublin"
    assert updated.status == "paused"


def _uow(repo: _AgenciesRepo) -> SimpleNamespace:
    return SimpleNamespace(tenancy=SimpleNamespace(agencies=repo))


class _AgenciesRepo:
    def __init__(self) -> None:
        self.record = Agency(
            agency_id="agency-1",
            name="Agency One",
            slug="agency-one",
            timezone="Europe/Dublin",
            status="active",
            created_at=None,
            updated_at=None,
        )

    def get_by_id(self, agency_id: str) -> Agency | None:
        return self.record if agency_id == self.record.agency_id else None

    def update(
        self,
        *,
        agency_id: str,
        name: str,
        slug: str,
        timezone: str,
        status: str,
    ) -> None:
        self.record = Agency(
            agency_id=agency_id,
            name=name,
            slug=slug,
            timezone=timezone,
            status=status,
            created_at=self.record.created_at,
            updated_at=self.record.updated_at,
        )
