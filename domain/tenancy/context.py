from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TenantContext:
    site_id: str
    agency_id: str
    wordpress_source_id: str
    auto_provisioned: bool = False


__all__ = ["TenantContext"]
