"""Webhook event aggregate — transport audit row, one per inbound call."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WebhookEvent:
    event_id: str
    agency_id: str
    ingestion_source_id: str
    external_source_id: str
    property_id: int | None
    received_at: str
    updated_at: str
    status: str
    raw_payload_hash: str
    error_message: str | None


__all__ = ["WebhookEvent"]
