from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.ingestion.application.use_cases.decommission_ingestion_source import (
    DecommissionIngestionSourceUseCase,
)
from modules.ingestion.domain import IngestionSource
from modules.tenancy.domain import Agency
from shared.errors import ResourceNotFoundError, ValidationError


def test_decommission_ingestion_source_deletes_record() -> None:
    sources = _SourcesRepo()
    sources.records["src-1"] = IngestionSource(
        ingestion_source_id="src-1",
        agency_id="agency-1",
        kind="wordpress",
        external_id="ckp.ie",
        name="Old",
    )
    agencies = _AgenciesRepo({"agency-1": _agency("agency-1")})

    DecommissionIngestionSourceUseCase().execute(
        uow=_uow(sources=sources, agencies=agencies),
        agency_id="agency-1",
        ingestion_source_id="src-1",
    )

    assert "src-1" not in sources.records


def test_decommission_ingestion_source_raises_when_id_missing() -> None:
    sources = _SourcesRepo()
    agencies = _AgenciesRepo({"agency-1": _agency("agency-1")})

    with pytest.raises(ResourceNotFoundError) as exc_info:
        DecommissionIngestionSourceUseCase().execute(
            uow=_uow(sources=sources, agencies=agencies),
            agency_id="agency-1",
            ingestion_source_id="missing",
        )
    assert exc_info.value.code == "ADMIN_SOURCE_NOT_FOUND"


def test_decommission_ingestion_source_rejects_agency_mismatch() -> None:
    sources = _SourcesRepo()
    sources.records["src-1"] = IngestionSource(
        ingestion_source_id="src-1",
        agency_id="agency-other",
        kind="wordpress",
        external_id="ckp.ie",
        name="Foreign",
    )
    agencies = _AgenciesRepo({"agency-1": _agency("agency-1")})

    with pytest.raises(ValidationError) as exc_info:
        DecommissionIngestionSourceUseCase().execute(
            uow=_uow(sources=sources, agencies=agencies),
            agency_id="agency-1",
            ingestion_source_id="src-1",
        )
    assert exc_info.value.code == "ADMIN_SOURCE_AGENCY_MISMATCH"


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


class _AgenciesRepo:
    def __init__(self, records: dict[str, Agency]) -> None:
        self.records = records

    def get_by_id(self, agency_id: str) -> Agency | None:
        return self.records.get(agency_id)


class _SourcesRepo:
    def __init__(self) -> None:
        self.records: dict[str, IngestionSource] = {}

    def get_by_id(self, ingestion_source_id: str) -> IngestionSource | None:
        return self.records.get(ingestion_source_id)

    def delete(self, ingestion_source_id: str) -> bool:
        if ingestion_source_id in self.records:
            del self.records[ingestion_source_id]
            return True
        return False
