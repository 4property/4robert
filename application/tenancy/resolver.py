from __future__ import annotations

from collections.abc import Callable

from application.persistence import UnitOfWork
from core.errors import ResourceNotFoundError
from domain.tenancy.context import TenantContext


class TenantResolver:
    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork]) -> None:
        self.unit_of_work_factory = unit_of_work_factory

    def resolve(self, *, site_id: str) -> TenantContext:
        normalized_site_id = str(site_id or "").strip().lower()
        with self.unit_of_work_factory() as unit_of_work:
            source = unit_of_work.wordpress_source_store.get_by_site_id(normalized_site_id)
        if source is None or source.status != "active":
            raise ResourceNotFoundError(
                "The webhook site is not provisioned.",
                code="UNKNOWN_WORDPRESS_SITE",
                context={"site_id": normalized_site_id},
                hint="Provision an active wordpress_sources row for this site_id before sending webhooks.",
            )
        return TenantContext(
            site_id=source.site_id,
            agency_id=source.agency_id,
            wordpress_source_id=source.wordpress_source_id,
        )


__all__ = ["TenantResolver"]
