from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from repositories.sqlite_connection import create_sqlite_connection

WEBHOOK_DELIVERY_TABLE_NAME = "webhook_events"


@dataclass(frozen=True, slots=True)
class WebhookDeliveryRecord:
    event_id: str
    site_id: str
    property_id: int | None
    received_at: str
    updated_at: str
    status: str
    raw_payload_hash: str
    error_message: str | None


class WebhookDeliveryRepository:
    def __init__(
        self,
        database_path: str | Path,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self._owns_connection = connection is None
        self.connection = connection or create_sqlite_connection(self.database_path)

    def __enter__(self) -> "WebhookDeliveryRepository":
        self.initialise()
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        if not self._owns_connection:
            return
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.connection.close()

    def initialise(self) -> None:
        self.connection.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS {WEBHOOK_DELIVERY_TABLE_NAME} (
                event_id TEXT PRIMARY KEY,
                site_id TEXT NOT NULL,
                property_id INTEGER,
                received_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                raw_payload_hash TEXT NOT NULL,
                error_message TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_webhook_events_site_received_at
            ON {WEBHOOK_DELIVERY_TABLE_NAME} (site_id, received_at DESC);

            CREATE INDEX IF NOT EXISTS idx_webhook_events_status_updated_at
            ON {WEBHOOK_DELIVERY_TABLE_NAME} (status, updated_at DESC);
            """
        )

    def create_event(
        self,
        *,
        event_id: str,
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
                site_id,
                property_id,
                received_at,
                updated_at,
                status,
                raw_payload_hash,
                error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                site_id,
                property_id,
                received_at,
                received_at,
                status,
                raw_payload_hash,
                error_message,
            ),
        )

    def update_event_status(
        self,
        event_id: str,
        *,
        status: str,
        error_message: str | None = None,
    ) -> None:
        updated_at = datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            f"""
            UPDATE {WEBHOOK_DELIVERY_TABLE_NAME}
            SET status = ?, updated_at = ?, error_message = ?
            WHERE event_id = ?
            """,
            (status, updated_at, error_message, event_id),
        )

    def get_event(self, event_id: str) -> WebhookDeliveryRecord | None:
        row = self.connection.execute(
            f"""
            SELECT event_id, site_id, property_id, received_at, updated_at, status, raw_payload_hash, error_message
            FROM {WEBHOOK_DELIVERY_TABLE_NAME}
            WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()
        if row is None:
            return None

        return WebhookDeliveryRecord(
            event_id=str(row["event_id"]),
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

