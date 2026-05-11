from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.tenancy.application.use_cases.decommission_agency import (
    DecommissionAgencyUseCase,
)
from shared.errors import ResourceNotFoundError


def test_decommission_agency_deletes_existing_agency() -> None:
    repo = _AgenciesRepo(deleted=True)

    DecommissionAgencyUseCase().execute(uow=_uow(repo), agency_id="agency-1")

    assert repo.deleted_ids == ["agency-1"]


def test_decommission_agency_raises_not_found_when_agency_is_missing() -> None:
    repo = _AgenciesRepo(deleted=False)

    with pytest.raises(ResourceNotFoundError) as exc_info:
        DecommissionAgencyUseCase().execute(uow=_uow(repo), agency_id="missing")

    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"


def _uow(repo: _AgenciesRepo) -> SimpleNamespace:
    return SimpleNamespace(tenancy=SimpleNamespace(agencies=repo))


class _AgenciesRepo:
    def __init__(self, *, deleted: bool) -> None:
        self.deleted = deleted
        self.deleted_ids: list[str] = []

    def delete(self, agency_id: str) -> bool:
        self.deleted_ids.append(agency_id)
        return self.deleted
