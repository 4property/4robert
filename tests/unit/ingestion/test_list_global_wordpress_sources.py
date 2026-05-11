"""Unit tests for ListGlobalWordPressSourcesUseCase."""

from __future__ import annotations

from types import SimpleNamespace

from modules.ingestion.application.use_cases.list_global_wordpress_sources import (
    ListGlobalWordPressSourcesUseCase,
)
from modules.ingestion.domain import IngestionSource, IngestionSourceWithAgency


def test_list_global_wordpress_sources_filters_by_kind() -> None:
    wp_source = _make("agency-1", "wordpress", "ckp.ie")
    other_source = _make("agency-2", "shopify", "shop.example")
    repo = _SourcesRepo([wp_source, other_source])
    uow = _uow(repo)

    result = ListGlobalWordPressSourcesUseCase().execute(uow=uow)

    assert result == (wp_source,)


def _uow(repo) -> SimpleNamespace:
    return SimpleNamespace(ingestion=SimpleNamespace(sources=repo))


def _make(agency_id: str, kind: str, external_id: str) -> IngestionSourceWithAgency:
    return IngestionSourceWithAgency(
        source=IngestionSource(
            ingestion_source_id=f"src-{external_id}",
            agency_id=agency_id,
            kind=kind,
            external_id=external_id,
            name=f"Source {external_id}",
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
