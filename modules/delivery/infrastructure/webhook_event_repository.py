"""Persistence for the WebhookEvent aggregate.

One row per inbound webhook (audit). Status transitions: `received` →
`accepted` / `rejected`. The job queue picks it up afterwards by `event_id`.
"""

from __future__ import annotations

from sqlalchemy import text

from modules.delivery.domain import WebhookEvent
from shared.db.repository_base import ModuleRepository


def _isoformat(value: object | None) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def _row_to_event(row) -> WebhookEvent:
    return WebhookEvent(
        event_id=str(row.event_id),
        agency_id=str(row.agency_id or ""),
        ingestion_source_id=str(row.ingestion_source_id or ""),
        external_source_id=str(row.external_source_id or ""),
        property_id=None if row.property_id is None else int(row.property_id),
        received_at=_isoformat(row.received_at) or "",
        updated_at=_isoformat(row.updated_at) or "",
        status=str(row.status or ""),
        raw_payload_hash=str(row.raw_payload_hash or ""),
        error_message=None if row.error_message is None else str(row.error_message),
    )


class WebhookEventRepository(ModuleRepository):
    def create_event(
        self,
        *,
        event_id: str,
        agency_id: str,
        ingestion_source_id: str,
        external_source_id: str,
        property_id: int | None,
        received_at: str,
        raw_payload_hash: str,
        status: str,
        source_kind: str = "wordpress",
        error_message: str | None = None,
    ) -> None:
        self.session.execute(
            text(
                "INSERT INTO webhook_events ("
                "event_id, agency_id, ingestion_source_id, external_source_id, "
                "source_kind, property_id, received_at, updated_at, status, "
                "raw_payload_hash, error_message"
                ") VALUES ("
                ":event_id, :agency_id, :ingestion_source_id, :external_source_id, "
                ":source_kind, :property_id, :received_at, :updated_at, :status, "
                ":raw_payload_hash, :error_message"
                ")"
            ),
            {
                "event_id": event_id,
                "agency_id": agency_id,
                "ingestion_source_id": ingestion_source_id,
                "external_source_id": external_source_id,
                "source_kind": source_kind,
                "property_id": property_id,
                "received_at": received_at,
                "updated_at": received_at,
                "status": status,
                "raw_payload_hash": raw_payload_hash,
                "error_message": error_message,
            },
        )

    def update_event_status(
        self,
        event_id: str,
        *,
        status: str,
        error_message: str | None = None,
    ) -> None:
        self.session.execute(
            text(
                "UPDATE webhook_events SET status = :status, "
                "updated_at = CURRENT_TIMESTAMP, error_message = :error_message "
                "WHERE event_id = :event_id"
            ),
            {
                "status": status,
                "error_message": error_message,
                "event_id": event_id,
            },
        )

    def get_event(self, event_id: str) -> WebhookEvent | None:
        row = self.session.execute(
            text(
                "SELECT event_id, agency_id, ingestion_source_id, external_source_id, "
                "property_id, received_at, updated_at, status, raw_payload_hash, "
                "error_message FROM webhook_events WHERE event_id = :event_id"
            ),
            {"event_id": event_id},
        ).first()
        return _row_to_event(row) if row is not None else None


__all__ = ["WebhookEventRepository"]
