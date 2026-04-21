from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TenantContext:
    site_id: str
    agency_id: str
    wordpress_source_id: str


__all__ = ["TenantContext"]
