from __future__ import annotations

from collections.abc import Callable
import logging

from application.persistence import UnitOfWork
from core.errors import ResourceNotFoundError
from domain.tenancy.context import TenantContext

logger = logging.getLogger(__name__)


class TenantResolver:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        allow_unknown_sites_for_testing: bool = False,
        unsafe_test_source_provisioner: Callable[..., object] | None = None,
    ) -> None:
        self.unit_of_work_factory = unit_of_work_factory
        self.allow_unknown_sites_for_testing = allow_unknown_sites_for_testing
        self.unsafe_test_source_provisioner = unsafe_test_source_provisioner

    def resolve(self, *, site_id: str) -> TenantContext:
        normalized_site_id = str(site_id or "").strip().lower()
        with self.unit_of_work_factory() as unit_of_work:
            source = unit_of_work.wordpress_source_store.get_by_site_id(normalized_site_id)
        if (
            (source is None or source.status != "active")
            and self.allow_unknown_sites_for_testing
            and self.unsafe_test_source_provisioner is not None
        ):
            provisioned_result = self.unsafe_test_source_provisioner(site_id=normalized_site_id)
            provisioned_source = getattr(provisioned_result, "source", None)
            if provisioned_source is not None:
                logger.warning(
                    "Auto-provisioned wordpress source for testing: site_id=%s",
                    normalized_site_id,
                )
                return TenantContext(
                    site_id=str(getattr(provisioned_source, "site_id")),
                    agency_id=str(getattr(provisioned_source, "agency_id")),
                    wordpress_source_id=str(getattr(provisioned_source, "wordpress_source_id")),
                    auto_provisioned=True,
                )
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
