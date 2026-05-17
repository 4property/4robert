"""Persistence for the OutboxEvent aggregate.

Inserts run inside the same transaction that mutates an aggregate (in
`apps/worker/`). The outbox relay polls `status='pending'` rows and dispatches
them to consumers. Consumers acknowledge by status, never by deletion.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from sqlalchemy import text

from modules.delivery.domain import OutboxEvent
from shared.db.repository_base import ModuleRepository


def _isoformat(value: object | None) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def _payload_to_jsonb(payload: Mapping[str, Any] | None) -> str:
    return json.dumps(dict(payload or {}), ensure_ascii=False, sort_keys=True)


def _jsonb_to_payload(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(bytes(raw).decode("utf-8"))
    if isinstance(raw, str):
        return json.loads(raw) if raw.strip() else {}
    return dict(raw)


def _row_to_event(row) -> OutboxEvent:
    return OutboxEvent(
        event_id=str(row.event_id),
        aggregate_type=str(row.aggregate_type),
        aggregate_id=str(row.aggregate_id),
        agency_id=str(row.agency_id or ""),
        ingestion_source_id=str(row.ingestion_source_id or ""),
        external_source_id=str(row.external_source_id or ""),
        source_property_id=(
            None if row.source_property_id is None else int(row.source_property_id)
        ),
        event_type=str(row.event_type),
        payload=_jsonb_to_payload(row.payload),
        status=str(row.status or ""),
        created_at=_isoformat(row.created_at) or "",
        available_at=_isoformat(row.available_at) or "",
        published_at=_isoformat(row.published_at),
        last_error=str(row.last_error or ""),
    )


class OutboxRepository(ModuleRepository):
    """Append-only emit + relay of outbound events."""

    def add_event(
        self,
        *,
        event_id: str,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        agency_id: str = "",
        ingestion_source_id: str = "",
        external_source_id: str = "",
        source_property_id: int | None = None,
        status: str = "pending",
        created_at: str | None = None,
        available_at: str | None = None,
    ) -> None:
        resolved_created_at = created_at or ""
        resolved_available_at = available_at or created_at or ""
        self.session.execute(
            text(
                "INSERT INTO outbox_events ("
                "event_id, aggregate_type, aggregate_id, agency_id, "
                "ingestion_source_id, external_source_id, source_property_id, "
                "event_type, payload, status, created_at, available_at"
                ") VALUES ("
                ":event_id, :aggregate_type, :aggregate_id, :agency_id, "
                ":ingestion_source_id, :external_source_id, :source_property_id, "
                ":event_type, CAST(:payload AS jsonb), :status, "
                ":created_at, :available_at"
                ")"
            ),
            {
                "event_id": event_id,
                "aggregate_type": aggregate_type,
                "aggregate_id": aggregate_id,
                "agency_id": agency_id,
                "ingestion_source_id": ingestion_source_id,
                "external_source_id": external_source_id,
                "source_property_id": source_property_id,
                "event_type": event_type,
                "payload": _payload_to_jsonb(payload),
                "status": status,
                "created_at": resolved_created_at,
                "available_at": resolved_available_at,
            },
        )

    def mark_published(self, *, event_id: str, published_at: str | None = None) -> None:
        self.session.execute(
            text(
                "UPDATE outbox_events SET status = 'published', "
                "published_at = :published_at, last_error = '' "
                "WHERE event_id = :event_id"
            ),
            {"published_at": published_at, "event_id": event_id},
        )

    def mark_status(
        self,
        *,
        event_id: str,
        status: str,
        last_error: str | None = None,
        published_at: str | None = None,
    ) -> None:
        """Generic status transition used by the notifications subscriber
        (feature 27) — moves an outbox row to e.g. ``'dispatched'`` or
        ``'failed'`` while preserving the existing ``last_error`` /
        ``published_at`` semantics of :meth:`mark_published`.
        """

        self.session.execute(
            text(
                "UPDATE outbox_events SET status = :status, "
                "published_at = :published_at, "
                "last_error = COALESCE(:last_error, '') "
                "WHERE event_id = :event_id"
            ),
            {
                "status": status,
                "published_at": published_at,
                "last_error": last_error,
                "event_id": event_id,
            },
        )

    def claim_pending_event(self, *, event_type: str) -> OutboxEvent | None:
        """Lock and return the oldest ``status='pending'`` row of the
        given ``event_type`` using ``FOR UPDATE SKIP LOCKED`` semantics.

        Multi-process safe: any other worker calling this concurrently
        will receive the next row (or ``None`` if the queue is empty).
        The caller is responsible for transitioning the row to its
        terminal status (``dispatched``, ``failed``) via
        :meth:`mark_status` inside the same UoW transaction.
        """

        row = self.session.execute(
            text(
                "SELECT event_id, aggregate_type, aggregate_id, agency_id, "
                "ingestion_source_id, external_source_id, source_property_id, "
                "event_type, payload, status, created_at, available_at, "
                "published_at, last_error FROM outbox_events "
                "WHERE status = 'pending' AND event_type = :event_type "
                "ORDER BY created_at ASC, event_id ASC "
                "FOR UPDATE SKIP LOCKED LIMIT 1"
            ),
            {"event_type": event_type},
        ).first()
        return None if row is None else _row_to_event(row)

    def list_events(
        self,
        *,
        external_source_id: str | None = None,
        source_property_id: int | None = None,
    ) -> tuple[OutboxEvent, ...]:
        if external_source_id is None:
            rows = self.session.execute(
                text(
                    "SELECT event_id, aggregate_type, aggregate_id, agency_id, "
                    "ingestion_source_id, external_source_id, source_property_id, "
                    "event_type, payload, status, created_at, available_at, "
                    "published_at, last_error FROM outbox_events "
                    "ORDER BY created_at ASC, event_id ASC"
                )
            ).all()
        else:
            rows = self.session.execute(
                text(
                    "SELECT event_id, aggregate_type, aggregate_id, agency_id, "
                    "ingestion_source_id, external_source_id, source_property_id, "
                    "event_type, payload, status, created_at, available_at, "
                    "published_at, last_error FROM outbox_events "
                    "WHERE external_source_id = :external_source_id "
                    "AND source_property_id IS NOT DISTINCT FROM :source_property_id "
                    "ORDER BY created_at ASC, event_id ASC"
                ),
                {
                    "external_source_id": external_source_id,
                    "source_property_id": source_property_id,
                },
            ).all()
        return tuple(_row_to_event(row) for row in rows)


__all__ = ["OutboxRepository"]
