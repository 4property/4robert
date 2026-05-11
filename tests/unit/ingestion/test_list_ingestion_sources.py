from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.ingestion.application.use_cases.list_ingestion_sources import (
    ListIngestionSourcesUseCase,
)
from modules.ingestion.domain import IngestionSource, IngestionSourceWithAgency
from modules.tenancy.domain import Agency
from shared.errors import ResourceNotFoundError


def test_list_ingestion_sources_returns_records_for_agency() -> None:
    record = _make_record("agency-1", "ckp.ie")
    sources = _SourcesRepo({"agency-1": (record,)})
    agencies = _AgenciesRepo({"agency-1": _agency("agency-1")})

    result = ListIngestionSourcesUseCase().execute(
        uow=_uow(sources=sources, agencies=agencies),
        agency_id="agency-1",
    )

    assert result == (record,)


def test_list_ingestion_sources_raises_when_agency_missing() -> None:
    with pytest.raises(ResourceNotFoundError) as exc_info:
        ListIngestionSourcesUseCase().execute(
            uow=_uow(sources=_SourcesRepo({}), agencies=_AgenciesRepo({})),
            agency_id="ghost",
        )
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"


def _uow(*, sources, agencies) -> SimpleNamespace:
    return SimpleNamespace(
        ingestion=SimpleNamespace(sources=sources),
        tenancy=SimpleNamespace(agencies=agencies),
    )


def _agency(agency_id: str) -> Agency:
    return Agency(
        agency_id=agency_id,
        name="Test",
        slug="test",
        timezone="Europe/Dublin",
        status="active",
        created_at=None,
        updated_at=None,
    )


def _make_record(agency_id: str, external_id: str) -> IngestionSourceWithAgency:
    return IngestionSourceWithAgency(
        source=IngestionSource(
            ingestion_source_id="src-1",
            agency_id=agency_id,
            kind="wordpress",
            external_id=external_id,
            name="Test Source",
        ),
        agency_name="Test",
        agency_slug="test",
        agency_timezone="Europe/Dublin",
        agency_status="active",
    )


class _AgenciesRepo:
    def __init__(self, records: dict[str, Agency]) -> None:
        self.records = records

    def get_by_id(self, agency_id: str) -> Agency | None:
        return self.records.get(agency_id)


class _SourcesRepo:
    def __init__(self, records: dict[str, tuple]) -> None:
        self.records = records

    def list_for_agency(self, agency_id: str) -> tuple:
        return self.records.get(agency_id, ())
