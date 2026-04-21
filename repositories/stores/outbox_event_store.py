from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from repositories.postgres.repository import PostgresRepositoryBase

OUTBOX_EVENT_TABLE_NAME = "outbox_events"


@dataclass(frozen=True, slots=True)
class OutboxEventRecord:
    event_id: str
    aggregate_type: str
    aggregate_id: str
    agency_id: str
    wordpress_source_id: str
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


class OutboxEventRepository(PostgresRepositoryBase):
    def __init__(
        self,
        database_path: str | Path | None,
        *,
        connection=None,
    ) -> None:
        super().__init__(database_path, connection=connection)

    def add_event(
        self,
        *,
        event_id: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        agency_id: str = "",
        wordpress_source_id: str = "",
        site_id: str = "",
        source_property_id: int | None = None,
        status: str = "pending",
        created_at: str | None = None,
        available_at: str | None = None,
    ) -> None:
        resolved_created_at = created_at or ""
        resolved_available_at = available_at or created_at or ""
        payload_json = json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)
        self.connection.execute(
            f"""
            INSERT INTO {OUTBOX_EVENT_TABLE_NAME} (
                event_id,
                aggregate_type,
                aggregate_id,
                agency_id,
                wordpress_source_id,
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
            VALUES (
                :event_id,
                :aggregate_type,
                :aggregate_id,
                :agency_id,
                :wordpress_source_id,
                :site_id,
                :source_property_id,
                :event_type,
                :payload_json,
                :status,
                :created_at,
                :available_at,
                '',
                ''
            )
            """,
            {
                "event_id": event_id,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "agency_id": agency_id,
                "wordpress_source_id": wordpress_source_id,
                "site_id": site_id,
                "source_property_id": source_property_id,
                "event_type": event_type,
                "payload_json": payload_json,
                "status": status,
                "created_at": resolved_created_at,
                "available_at": resolved_available_at,
            },
        )

    def mark_published(self, *, event_id: str, published_at: str | None = None) -> None:
        self.connection.execute(
            f"""
            UPDATE {OUTBOX_EVENT_TABLE_NAME}
            SET status = 'published',
                published_at = :published_at,
                last_error = ''
            WHERE event_id = :event_id
            """,
            {
                "published_at": published_at or "",
                "event_id": event_id,
            },
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
                    agency_id,
                    wordpress_source_id,
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
                    agency_id,
                    wordpress_source_id,
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
                WHERE site_id = :site_id
                AND source_property_id IS NOT DISTINCT FROM :source_property_id
                ORDER BY created_at ASC, event_id ASC
                """,
                {
                    "site_id": site_id,
                    "source_property_id": source_property_id,
                },
            ).fetchall()
        return tuple(_row_to_outbox_event(row) for row in rows)


def _row_to_outbox_event(row) -> OutboxEventRecord:
    return OutboxEventRecord(
        event_id=str(row["event_id"]),
        aggregate_type=str(row["aggregate_type"]),
        aggregate_id=str(row["aggregate_id"]),
        agency_id=str(row["agency_id"] or ""),
        wordpress_source_id=str(row["wordpress_source_id"] or ""),
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
