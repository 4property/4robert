from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repositories.postgres.repository import PostgresRepositoryBase

WEBHOOK_DELIVERY_TABLE_NAME = "webhook_events"


@dataclass(frozen=True, slots=True)
class WebhookDeliveryRecord:
    event_id: str
    agency_id: str
    wordpress_source_id: str
    site_id: str
    property_id: int | None
    received_at: str
    updated_at: str
    status: str
    raw_payload_hash: str
    error_message: str | None


class WebhookDeliveryRepository(PostgresRepositoryBase):
    def __init__(
        self,
        database_path: str | Path | None,
        *,
        connection=None,
    ) -> None:
        super().__init__(database_path, connection=connection)

    def create_event(
        self,
        *,
        event_id: str,
        agency_id: str,
        wordpress_source_id: str,
        site_id: str,
        property_id: int | None,
        received_at: str,
        raw_payload_hash: str,
        status: str,
        error_message: str | None = None,
    ) -> None:
        self.connection.execute(
            f"""
            INSERT INTO {WEBHOOK_DELIVERY_TABLE_NAME} (
                event_id,
                agency_id,
                wordpress_source_id,
                site_id,
                property_id,
                received_at,
                updated_at,
                status,
                raw_payload_hash,
                error_message
            )
            VALUES (
                :event_id,
                :agency_id,
                :wordpress_source_id,
                :site_id,
                :property_id,
                :received_at,
                :updated_at,
                :status,
                :raw_payload_hash,
                :error_message
            )
            """,
            {
                "event_id": event_id,
                "agency_id": agency_id,
                "wordpress_source_id": wordpress_source_id,
                "site_id": site_id,
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
        self.connection.execute(
            f"""
            UPDATE {WEBHOOK_DELIVERY_TABLE_NAME}
            SET status = :status,
                updated_at = CURRENT_TIMESTAMP,
                error_message = :error_message
            WHERE event_id = :event_id
            """,
            {
                "status": status,
                "error_message": error_message,
                "event_id": event_id,
            },
        )

    def get_event(self, event_id: str) -> WebhookDeliveryRecord | None:
        row = self.connection.execute(
            f"""
            SELECT
                event_id,
                agency_id,
                wordpress_source_id,
                site_id,
                property_id,
                received_at,
                updated_at,
                status,
                raw_payload_hash,
                error_message
            FROM {WEBHOOK_DELIVERY_TABLE_NAME}
            WHERE event_id = :event_id
            """,
            {"event_id": event_id},
        ).fetchone()
        if row is None:
            return None
        return WebhookDeliveryRecord(
            event_id=str(row["event_id"]),
            agency_id=str(row["agency_id"]),
            wordpress_source_id=str(row["wordpress_source_id"]),
            site_id=str(row["site_id"]),
            property_id=None if row["property_id"] is None else int(row["property_id"]),
            received_at=str(row["received_at"]),
            updated_at=str(row["updated_at"]),
            status=str(row["status"]),
            raw_payload_hash=str(row["raw_payload_hash"]),
            error_message=None if row["error_message"] is None else str(row["error_message"]),
        )


__all__ = [
    "WEBHOOK_DELIVERY_TABLE_NAME",
    "WebhookDeliveryRecord",
    "WebhookDeliveryRepository",
]
