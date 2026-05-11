"""Unit tests for InspectWordPressSourceBySiteIdUseCase."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.ingestion.application.use_cases.inspect_wordpress_source_by_site_id import (
    InspectWordPressSourceBySiteIdUseCase,
)
from modules.ingestion.domain import IngestionSource, IngestionSourceWithAgency
from shared.errors import ValidationError


def test_inspect_returns_record_when_present() -> None:
    record = _make("agency-1", "ckp.ie")
    repo = _SourcesRepo([record])
    uow = _uow(repo)

    result = InspectWordPressSourceBySiteIdUseCase().execute(
        uow=uow, site_id="ckp.ie"
    )
    assert result is record


def test_inspect_lowercases_url_before_lookup() -> None:
    record = _make("agency-1", "ckp.ie")
    repo = _SourcesRepo([record])
    uow = _uow(repo)

    result = InspectWordPressSourceBySiteIdUseCase().execute(
        uow=uow, site_id="https://CKP.IE/"
    )
    assert result is record


def test_inspect_returns_none_for_unknown_site() -> None:
    record = _make("agency-1", "ckp.ie")
    repo = _SourcesRepo([record])
    uow = _uow(repo)

    result = InspectWordPressSourceBySiteIdUseCase().execute(
        uow=uow, site_id="unknown.example"
    )
    assert result is None


def test_inspect_raises_when_site_id_blank() -> None:
    with pytest.raises(ValidationError) as exc_info:
        InspectWordPressSourceBySiteIdUseCase().execute(
            uow=_uow(_SourcesRepo([])),
            site_id="",
        )
    assert exc_info.value.code == "ADMIN_SITE_ID_REQUIRED"


def _uow(repo) -> SimpleNamespace:
    return SimpleNamespace(ingestion=SimpleNamespace(sources=repo))


def _make(agency_id: str, external_id: str) -> IngestionSourceWithAgency:
    return IngestionSourceWithAgency(
        source=IngestionSource(
            ingestion_source_id=f"src-{external_id}",
            agency_id=agency_id,
            kind="wordpress",
            external_id=external_id,
            name="Site",
        ),
        agency_name="A",
        agency_slug="a",
        agency_timezone="Europe/Dublin",
        agency_status="active",
    )


class _SourcesRepo:
    def __init__(self, records: list[IngestionSourceWithAgency]) -> None:
        self.records = tuple(records)

    def list_all(self) -> tuple[IngestionSourceWithAgency, ...]:
        return self.records
