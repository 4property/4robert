from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Any

from repositories.sqlite_connection import create_sqlite_connection

OUTBOX_EVENT_TABLE_NAME = "outbox_events"


@dataclass(frozen=True, slots=True)
class OutboxEventRecord:
    event_id: str
    aggregate_type: str
    aggregate_id: str
    site_id: str
    source_property_id: int | None
    event_type: str
    payload_json: str
    status: str
    created_at: str
    available_at: str
    published_at: str
    last_error: str

    @property
    def payload(self) -> dict[str, Any]:
        if not self.payload_json.strip():
            return {}
        try:
            parsed = json.loads(self.payload_json)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}


def _build_outbox_table_sql() -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {OUTBOX_EVENT_TABLE_NAME} (
            event_id TEXT PRIMARY KEY,
            aggregate_type TEXT NOT NULL,
            aggregate_id TEXT NOT NULL,
            site_id TEXT NOT NULL DEFAULT '',
            source_property_id INTEGER,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            available_at TEXT NOT NULL,
            published_at TEXT NOT NULL DEFAULT '',
            last_error TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_outbox_events_status_available_at
        ON {OUTBOX_EVENT_TABLE_NAME} (status, available_at, created_at);

        CREATE INDEX IF NOT EXISTS idx_outbox_events_site_property_created_at
        ON {OUTBOX_EVENT_TABLE_NAME} (site_id, source_property_id, created_at DESC);
    """


class OutboxEventRepository:
    def __init__(
        self,
        database_path: str | Path,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self._owns_connection = connection is None
        self.connection = connection or create_sqlite_connection(self.database_path)

    def __enter__(self) -> "OutboxEventRepository":
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
        self.connection.executescript(_build_outbox_table_sql())

    def add_event(
        self,
        *,
        event_id: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        site_id: str = "",
        source_property_id: int | None = None,
        status: str = "pending",
        created_at: str | None = None,
        available_at: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        self.connection.execute(
            f"""
            INSERT INTO {OUTBOX_EVENT_TABLE_NAME} (
                event_id,
                aggregate_type,
                aggregate_id,
                site_id,
                source_property_id,
                event_type,
                payload_json,
                status,
                created_at,
                available_at,
                published_at,
                last_error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '')
            """,
            (
                event_id,
                aggregate_type,
                aggregate_id,
                site_id,
                source_property_id,
                event_type,
                payload_json,
                status,
                created_at or now,
                available_at or created_at or now,
            ),
        )

    def mark_published(self, *, event_id: str, published_at: str | None = None) -> None:
        self.connection.execute(
            f"""
            UPDATE {OUTBOX_EVENT_TABLE_NAME}
            SET status = 'published',
                published_at = ?,
                last_error = ''
            WHERE event_id = ?
            """,
            (published_at or datetime.now(timezone.utc).isoformat(), event_id),
        )

    def list_events(
        self,
        *,
        site_id: str | None = None,
        source_property_id: int | None = None,
    ) -> tuple[OutboxEventRecord, ...]:
        if site_id is None:
            rows = self.connection.execute(
                f"""
                SELECT
                    event_id,
                    aggregate_type,
                    aggregate_id,
                    site_id,
                    source_property_id,
                    event_type,
                    payload_json,
                    status,
                    created_at,
                    available_at,
                    published_at,
                    last_error
                FROM {OUTBOX_EVENT_TABLE_NAME}
                ORDER BY created_at ASC, event_id ASC
                """
            ).fetchall()
        else:
            rows = self.connection.execute(
                f"""
                SELECT
                    event_id,
                    aggregate_type,
                    aggregate_id,
                    site_id,
                    source_property_id,
                    event_type,
                    payload_json,
                    status,
                    created_at,
                    available_at,
                    published_at,
                    last_error
                FROM {OUTBOX_EVENT_TABLE_NAME}
                WHERE site_id = ?
                AND source_property_id IS ?
                ORDER BY created_at ASC, event_id ASC
                """,
                (site_id, source_property_id),
            ).fetchall()
        return tuple(_row_to_outbox_event(row) for row in rows)


def _row_to_outbox_event(row: sqlite3.Row) -> OutboxEventRecord:
    return OutboxEventRecord(
        event_id=str(row["event_id"]),
        aggregate_type=str(row["aggregate_type"]),
        aggregate_id=str(row["aggregate_id"]),
        site_id=str(row["site_id"] or ""),
        source_property_id=None if row["source_property_id"] is None else int(row["source_property_id"]),
        event_type=str(row["event_type"]),
        payload_json=str(row["payload_json"] or ""),
        status=str(row["status"] or ""),
        created_at=str(row["created_at"] or ""),
        available_at=str(row["available_at"] or ""),
        published_at=str(row["published_at"] or ""),
        last_error=str(row["last_error"] or ""),
    )


__all__ = [
    "OUTBOX_EVENT_TABLE_NAME",
    "OutboxEventRecord",
    "OutboxEventRepository",
]
