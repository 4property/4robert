from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.ingestion.application.use_cases.register_ingestion_source import (
    RegisterIngestionSourceInput,
    RegisterIngestionSourceUseCase,
)
from modules.ingestion.domain import IngestionSource
from modules.tenancy.domain import Agency
from shared.errors import ResourceNotFoundError, ValidationError


def test_register_ingestion_source_creates_row_for_existing_agency() -> None:
    sources = _SourcesRepo()
    agencies = _AgenciesRepo({"agency-1": _agency("agency-1")})

    source = RegisterIngestionSourceUseCase().execute(
        uow=_uow(sources=sources, agencies=agencies),
        data=RegisterIngestionSourceInput(
            agency_id="agency-1",
            name="CKP",
            external_id="CKP.IE",
        ),
    )

    assert source.agency_id == "agency-1"
    assert source.kind == "wordpress"
    assert source.external_id == "ckp.ie"
    assert source.name == "CKP"
    assert source.config["site_url"] == "https://ckp.ie"
    assert source.config["normalized_host"] == "ckp.ie"


def test_register_ingestion_source_raises_when_agency_missing() -> None:
    with pytest.raises(ResourceNotFoundError) as exc_info:
        RegisterIngestionSourceUseCase().execute(
            uow=_uow(sources=_SourcesRepo(), agencies=_AgenciesRepo({})),
            data=RegisterIngestionSourceInput(
                agency_id="ghost", name="X", external_id="x.example"
            ),
        )
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"


def test_register_ingestion_source_rejects_duplicate_external_id() -> None:
    sources = _SourcesRepo()
    sources.records["existing"] = IngestionSource(
        ingestion_source_id="existing",
        agency_id="agency-1",
        kind="wordpress",
        external_id="ckp.ie",
        name="Existing",
        config={"site_url": "https://ckp.ie", "normalized_host": "ckp.ie"},
    )

    with pytest.raises(ValidationError) as exc_info:
        RegisterIngestionSourceUseCase().execute(
            uow=_uow(
                sources=sources,
                agencies=_AgenciesRepo({"agency-1": _agency("agency-1")}),
            ),
            data=RegisterIngestionSourceInput(
                agency_id="agency-1", name="Dup", external_id="ckp.ie"
            ),
        )
    assert exc_info.value.code == "INGESTION_SOURCE_DUPLICATE"


def _uow(*, sources: _SourcesRepo, agencies: _AgenciesRepo) -> SimpleNamespace:
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

    def get_by_kind_external_id(
        self, *, kind: str, external_id: str
    ) -> IngestionSource | None:
        for record in self.records.values():
            if record.kind == kind and record.external_id == external_id:
                return record
        return None

    def create(
        self,
        *,
        ingestion_source_id: str,
        agency_id: str,
        kind: str,
        external_id: str,
        name: str,
        config: dict | None = None,
        secret: str = "",
        status: str = "active",
    ) -> None:
        self.records[ingestion_source_id] = IngestionSource(
            ingestion_source_id=ingestion_source_id,
            agency_id=agency_id,
            kind=kind,
            external_id=external_id,
            name=name,
            config=dict(config or {}),
            status=status,
            has_secret=bool(secret),
        )
