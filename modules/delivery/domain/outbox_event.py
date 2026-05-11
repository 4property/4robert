"""Outbox event aggregate.

Decouples writers (use cases inside the worker) from external consumers
(notifications, analytics, downstream services). The relay polls
`status='pending'` rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    event_id: str
    aggregate_type: str
    aggregate_id: str
    agency_id: str
    ingestion_source_id: str
    external_source_id: str
    source_property_id: int | None
    event_type: str
    payload: Mapping[str, Any]
    status: str
    created_at: str
    available_at: str
    published_at: str | None
    last_error: str


__all__ = ["OutboxEvent"]
