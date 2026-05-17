"""Unit tests for `ListReelsUseCase` and the clamp helpers (feature 32)."""

from __future__ import annotations

import pytest

from modules.reels.application.use_cases.list_reels import (
    DEFAULT_PAGE,
    DEFAULT_PAGE_SIZE,
    ListReelsUseCase,
    MAX_PAGE_SIZE,
    clamp_page,
    clamp_page_size,
    normalize_q,
)
from shared.errors import ResourceNotFoundError
from tests.unit.reels._uow_stubs import StubReelQuery, build_uow, make_summary


def test_list_reels_returns_query_results_for_existing_agency() -> None:
    summary = make_summary(external_source_id="site-a", source_property_id=1)
    queries = StubReelQuery(items=(summary,), count_total=7)
    uow = build_uow(queries=queries)

    result = ListReelsUseCase().execute(
        uow=uow,
        agency_id="agency-1",
        page=1,
        page_size=10,
    )

    assert result.items == (summary,)
    assert result.count_total == 7
    assert result.page == 1
    assert result.page_size == 10
    assert queries.calls == [
        {
            "agency_id": "agency-1",
            "limit": 10,
            "offset": 0,
            "workflow_state": None,
            "publish_status": None,
            "q": None,
        }
    ]
    assert queries.count_calls == [
        {
            "agency_id": "agency-1",
            "workflow_state": None,
            "publish_status": None,
            "q": None,
        }
    ]


def test_list_reels_uses_defaults_when_pagination_is_omitted() -> None:
    summary = make_summary(external_source_id="site-a", source_property_id=1)
    queries = StubReelQuery(items=(summary,), count_total=1)
    uow = build_uow(queries=queries)

    result = ListReelsUseCase().execute(uow=uow, agency_id="agency-1")

    assert result.page == DEFAULT_PAGE
    assert result.page_size == DEFAULT_PAGE_SIZE
    assert queries.calls[0]["offset"] == 0
    assert queries.calls[0]["limit"] == DEFAULT_PAGE_SIZE


def test_list_reels_computes_offset_from_page_and_page_size() -> None:
    queries = StubReelQuery(items=(), count_total=120)
    uow = build_uow(queries=queries)

    ListReelsUseCase().execute(
        uow=uow,
        agency_id="agency-1",
        page=3,
        page_size=25,
    )

    assert queries.calls[0]["offset"] == 50
    assert queries.calls[0]["limit"] == 25


def test_list_reels_forwards_filters_to_query() -> None:
    queries = StubReelQuery(items=(), count_total=0)
    uow = build_uow(queries=queries)

    ListReelsUseCase().execute(
        uow=uow,
        agency_id="agency-1",
        page=1,
        page_size=25,
        workflow_state=("needs_approval", "approved"),
        publish_status=("pending_publish",),
        q="cranford",
    )

    assert queries.calls[0]["workflow_state"] == ("needs_approval", "approved")
    assert queries.calls[0]["publish_status"] == ("pending_publish",)
    assert queries.calls[0]["q"] == "cranford"
    # The count query receives the same filters so the totals stay aligned.
    assert queries.count_calls[0]["workflow_state"] == (
        "needs_approval",
        "approved",
    )
    assert queries.count_calls[0]["publish_status"] == ("pending_publish",)
    assert queries.count_calls[0]["q"] == "cranford"


def test_list_reels_raises_when_agency_does_not_exist() -> None:
    uow = build_uow(agency_present=False)

    with pytest.raises(ResourceNotFoundError) as exc_info:
        ListReelsUseCase().execute(uow=uow, agency_id="missing")

    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"


# ---------------------------------------------------------------------------
# Clamp helpers
# ---------------------------------------------------------------------------


def test_clamp_page_negatives_and_zero_collapse_to_one() -> None:
    assert clamp_page(0) == 1
    assert clamp_page(-3) == 1
    assert clamp_page(None) == DEFAULT_PAGE
    assert clamp_page(1) == 1
    assert clamp_page(99) == 99


def test_clamp_page_size_clamps_to_max_and_default() -> None:
    assert clamp_page_size(None) == DEFAULT_PAGE_SIZE
    assert clamp_page_size(0) == 1
    assert clamp_page_size(1) == 1
    assert clamp_page_size(25) == 25
    assert clamp_page_size(500) == MAX_PAGE_SIZE
    assert clamp_page_size(MAX_PAGE_SIZE) == MAX_PAGE_SIZE


def test_clamp_page_size_handles_garbage_input() -> None:
    assert clamp_page_size("not-a-number") == DEFAULT_PAGE_SIZE  # type: ignore[arg-type]
    assert clamp_page("not-a-number") == DEFAULT_PAGE  # type: ignore[arg-type]


def test_normalize_q_collapses_blank_strings_to_none() -> None:
    assert normalize_q(None) is None
    assert normalize_q("") is None
    assert normalize_q("   ") is None
    assert normalize_q("\t \n") is None
    assert normalize_q("  cranford  ") == "cranford"
    assert normalize_q("cranford") == "cranford"
