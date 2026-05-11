from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.ingestion.application.use_cases.reconfigure_ingestion_source import (
    ReconfigureIngestionSourceInput,
    ReconfigureIngestionSourceUseCase,
)
from modules.ingestion.domain import IngestionSource
from modules.tenancy.domain import Agency
from shared.errors import ResourceNotFoundError, ValidationError


def test_reconfigure_ingestion_source_updates_only_provided_fields() -> None:
    sources = _SourcesRepo()
    sources.records["src-1"] = IngestionSource(
        ingestion_source_id="src-1",
        agency_id="agency-1",
        kind="wordpress",
        external_id="ckp.ie",
        name="Old",
        status="active",
        config={"site_url": "https://ckp.ie", "normalized_host": "ckp.ie"},
    )
    agencies = _AgenciesRepo({"agency-1": _agency("agency-1")})

    updated = ReconfigureIngestionSourceUseCase().execute(
        uow=_uow(sources=sources, agencies=agencies),
        data=ReconfigureIngestionSourceInput(
            agency_id="agency-1",
            ingestion_source_id="src-1",
            name="New Name",
        ),
    )

    assert updated.name == "New Name"
    assert updated.status == "active"
    assert sources.last_secret is None  # secret untouched


def test_reconfigure_ingestion_source_raises_when_id_missing() -> None:
    sources = _SourcesRepo()
    agencies = _AgenciesRepo({"agency-1": _agency("agency-1")})

    with pytest.raises(ResourceNotFoundError) as exc_info:
        ReconfigureIngestionSourceUseCase().execute(
            uow=_uow(sources=sources, agencies=agencies),
            data=ReconfigureIngestionSourceInput(
                agency_id="agency-1",
                ingestion_source_id="missing",
                name="X",
            ),
        )
    assert exc_info.value.code == "ADMIN_SOURCE_NOT_FOUND"


def test_reconfigure_ingestion_source_rejects_agency_mismatch() -> None:
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
        ReconfigureIngestionSourceUseCase().execute(
            uow=_uow(sources=sources, agencies=agencies),
            data=ReconfigureIngestionSourceInput(
                agency_id="agency-1",
                ingestion_source_id="src-1",
                name="X",
            ),
        )
    assert exc_info.value.code == "ADMIN_SOURCE_AGENCY_MISMATCH"


def test_reconfigure_ingestion_source_rotates_secret_when_requested() -> None:
    sources = _SourcesRepo()
    sources.records["src-1"] = IngestionSource(
        ingestion_source_id="src-1",
        agency_id="agency-1",
        kind="wordpress",
        external_id="ckp.ie",
        name="Old",
    )
    agencies = _AgenciesRepo({"agency-1": _agency("agency-1")})

    ReconfigureIngestionSourceUseCase().execute(
        uow=_uow(sources=sources, agencies=agencies),
        data=ReconfigureIngestionSourceInput(
            agency_id="agency-1",
            ingestion_source_id="src-1",
            secret="new-secret",
            update_secret=True,
        ),
    )

    assert sources.last_secret == "new-secret"


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
        self.last_secret: str | None = None

    def get_by_id(self, ingestion_source_id: str) -> IngestionSource | None:
        return self.records.get(ingestion_source_id)

    def update(
        self,
        *,
        ingestion_source_id: str,
        name: str,
        config,
        status: str,
        secret=None,
    ) -> None:
        existing = self.records[ingestion_source_id]
        self.records[ingestion_source_id] = IngestionSource(
            ingestion_source_id=ingestion_source_id,
            agency_id=existing.agency_id,
            kind=existing.kind,
            external_id=existing.external_id,
            name=name,
            config=dict(config or {}),
            status=status,
            has_secret=secret is not None and secret != "",
        )
        self.last_secret = secret
