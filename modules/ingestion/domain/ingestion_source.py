"""Ingestion source aggregate.

A tenant's connection to one external system that pushes property data into
the platform. The `kind` discriminator picks the adapter (`wordpress` today;
new `kind`s require only an adapter under
`modules/ingestion/application/adapters/`, no schema change).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class IngestionSource:
    ingestion_source_id: str
    agency_id: str
    kind: str
    external_id: str
    name: str
    config: Mapping[str, Any] = field(default_factory=dict)
    status: str = "active"
    has_secret: bool = False
    last_event_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class IngestionSourceWithAgency:
    """Read model used by admin endpoints — joins source + agency in one shape."""

    source: IngestionSource
    agency_name: str
    agency_slug: str
    agency_timezone: str
    agency_status: str


__all__ = ["IngestionSource", "IngestionSourceWithAgency"]
