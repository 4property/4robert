"""List the most recent reels for an agency (admin "Reels" view)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from modules.reels.application.use_cases._admin_support import ensure_agency_exists
from shared.db import DatabaseUnitOfWork

if TYPE_CHECKING:
    from modules.reels.infrastructure.reel_query import AgencyReelSummary


DEFAULT_PAGE: int = 1
DEFAULT_PAGE_SIZE: int = 25
MAX_PAGE_SIZE: int = 100
MIN_PAGE_SIZE: int = 1


def clamp_page(page: int | None) -> int:
    """Clamp ``page`` to the inclusive range ``[1, +inf)``.

    The router calls this before invoking the use case so that out-of-range
    or missing values map to ``DEFAULT_PAGE`` deterministically.
    """
    try:
        value = int(page) if page is not None else DEFAULT_PAGE
    except (TypeError, ValueError):
        return DEFAULT_PAGE
    return value if value >= 1 else 1


def clamp_page_size(page_size: int | None) -> int:
    """Clamp ``page_size`` to ``[MIN_PAGE_SIZE, MAX_PAGE_SIZE]``."""
    try:
        value = (
            int(page_size) if page_size is not None else DEFAULT_PAGE_SIZE
        )
    except (TypeError, ValueError):
        return DEFAULT_PAGE_SIZE
    if value < MIN_PAGE_SIZE:
        return MIN_PAGE_SIZE
    if value > MAX_PAGE_SIZE:
        return MAX_PAGE_SIZE
    return value


def normalize_q(q: str | None) -> str | None:
    """Trim ``q`` and collapse empty/whitespace-only values to ``None``.

    The search field is optional. Callers should treat the return value
    as a presence flag — ``None`` means "no filter", non-``None`` means
    "ILIKE ``%value%`` over title/slug/list_reference".
    """
    if q is None:
        return None
    trimmed = str(q).strip()
    return trimmed or None


@dataclass(frozen=True, slots=True)
class ListReelsResult:
    """Paginated, filtered listing returned by :class:`ListReelsUseCase`.

    ``items`` is the slice the caller asked for; ``count_total`` is the
    total number of rows that satisfy the *same* filters (i.e. the value
    the UI uses to render the "N of M" status and the pager).
    """

    items: tuple[AgencyReelSummary, ...]
    count_total: int
    page: int
    page_size: int


class ListReelsUseCase:
    """Read-only use case that returns the agency's recent reels.

    The heavy lifting (cross-aggregate JOIN) lives in
    ``uow.reels.queries.list_recent_for_agency``. This use case adds
    tenant existence validation, server-side clamping of pagination, and
    the ``count_for_agency`` round-trip that backs ``has_more``.
    """

    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
        page: int | None = None,
        page_size: int | None = None,
        workflow_state: tuple[str, ...] | None = None,
        publish_status: tuple[str, ...] | None = None,
        q: str | None = None,
    ) -> ListReelsResult:
        if uow.reels is None:
            raise RuntimeError("The unit of work is not active.")
        ensure_agency_exists(uow, agency_id)
        normalized_agency_id = str(agency_id or "").strip()
        normalized_page = clamp_page(page)
        normalized_page_size = clamp_page_size(page_size)
        normalized_q = normalize_q(q)
        normalized_workflow_state = (
            tuple(workflow_state) if workflow_state else None
        )
        normalized_publish_status = (
            tuple(publish_status) if publish_status else None
        )
        offset = (normalized_page - 1) * normalized_page_size
        items = uow.reels.queries.list_recent_for_agency(
            agency_id=normalized_agency_id,
            limit=normalized_page_size,
            offset=offset,
            workflow_state=normalized_workflow_state,
            publish_status=normalized_publish_status,
            q=normalized_q,
        )
        count_total = uow.reels.queries.count_for_agency(
            agency_id=normalized_agency_id,
            workflow_state=normalized_workflow_state,
            publish_status=normalized_publish_status,
            q=normalized_q,
        )
        return ListReelsResult(
            items=tuple(items),
            count_total=int(count_total),
            page=normalized_page,
            page_size=normalized_page_size,
        )


__all__ = [
    "DEFAULT_PAGE",
    "DEFAULT_PAGE_SIZE",
    "ListReelsResult",
    "ListReelsUseCase",
    "MAX_PAGE_SIZE",
    "MIN_PAGE_SIZE",
    "clamp_page",
    "clamp_page_size",
    "normalize_q",
]
