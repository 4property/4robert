from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from modules.tenancy.application.use_cases.register_agency import (
    RegisterAgencyInput,
    RegisterAgencyUseCase,
)
from modules.tenancy.domain import Agency
from shared.errors import ValidationError


def test_register_agency_creates_agency_with_slug_and_defaults() -> None:
    repo = _AgenciesRepo()

    agency = RegisterAgencyUseCase().execute(
        uow=_uow(repo),
        data=RegisterAgencyInput(name="CKP Estate Agents"),
    )

    assert agency.name == "CKP Estate Agents"
    assert agency.slug == "ckp-estate-agents"
    assert agency.timezone == "Europe/Dublin"
    assert agency.status == "active"
    assert repo.get_by_id(agency.agency_id) == agency


def test_register_agency_raises_validation_error_when_slug_is_taken() -> None:
    repo = _AgenciesRepo()
    repo.records["existing"] = Agency(
        agency_id="existing",
        name="Existing",
        slug="ckp",
        timezone="Europe/Dublin",
        status="active",
        created_at=None,
        updated_at=None,
    )

    with pytest.raises(ValidationError) as exc_info:
        RegisterAgencyUseCase().execute(
            uow=_uow(repo),
            data=RegisterAgencyInput(name="Another Agency", slug="ckp"),
        )

    assert exc_info.value.code == "ADMIN_AGENCY_SLUG_TAKEN"


def _uow(repo: _AgenciesRepo) -> SimpleNamespace:
    return SimpleNamespace(tenancy=SimpleNamespace(agencies=repo))


class _AgenciesRepo:
    def __init__(self) -> None:
        self.records: dict[str, Agency] = {}

    def get_by_id(self, agency_id: str) -> Agency | None:
        return self.records.get(agency_id)

    def create(
        self,
        *,
        agency_id: str,
        name: str,
        slug: str,
        timezone: str,
        status: str,
    ) -> None:
        for record in self.records.values():
            if record.slug == slug:
                raise IntegrityError(
                    "INSERT INTO agencies ...",
                    {},
                    Exception('duplicate key value violates unique constraint "agencies_slug_key"'),
                )
        self.records[agency_id] = Agency(
            agency_id=agency_id,
            name=name,
            slug=slug,
            timezone=timezone,
            status=status,
            created_at=None,
            updated_at=None,
        )
