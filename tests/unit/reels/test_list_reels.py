"""Unit tests for `ListReelsUseCase`."""

from __future__ import annotations

import pytest

from modules.reels.application.use_cases.list_reels import ListReelsUseCase
from shared.errors import ResourceNotFoundError
from tests.unit.reels._uow_stubs import StubReelQuery, build_uow, make_summary


def test_list_reels_returns_query_results_for_existing_agency() -> None:
    summary = make_summary(external_source_id="site-a", source_property_id=1)
    queries = StubReelQuery(items=(summary,))
    uow = build_uow(queries=queries)

    result = ListReelsUseCase().execute(
        uow=uow, agency_id="agency-1", limit=20
    )

    assert result == (summary,)
    assert queries.calls == [{"agency_id": "agency-1", "limit": 20}]


def test_list_reels_raises_when_agency_does_not_exist() -> None:
    uow = build_uow(agency_present=False)

    with pytest.raises(ResourceNotFoundError) as exc_info:
        ListReelsUseCase().execute(uow=uow, agency_id="missing")

    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"
