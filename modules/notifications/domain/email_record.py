"""Persisted shape of one row in ``email_notifications``."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EmailRecord:
    id: str
    agency_id: str
    event_kind: str
    site_id: str
    source_property_id: int
    recipient_email: str
    status: str
    provider_message_id: str | None
    error_message: str | None
    sent_at: str | None
    created_at: str
    updated_at: str


__all__ = ["EmailRecord"]
