"""Repository for the ``email_notifications`` audit table (feature 26).

Reads and writes only — the dispatch use case (feature 27) owns the
session boundary. The repository never commits; the unit of work that
owns the session does.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import text

from modules.notifications.domain import EmailRecord, STATUS_QUEUED
from modules.configuration.infrastructure.repository_helpers import isoformat
from shared.db.repository_base import ModuleRepository, utcnow


_SELECT_COLUMNS = (
    "id, agency_id, event_kind, site_id, source_property_id, "
    "recipient_email, status, provider_message_id, error_message, "
    "sent_at, created_at, updated_at"
)


def _row_to_record(row: object) -> EmailRecord:
    return EmailRecord(
        id=str(row.id),  # type: ignore[attr-defined]
        agency_id=str(row.agency_id),  # type: ignore[attr-defined]
        event_kind=str(row.event_kind),  # type: ignore[attr-defined]
        site_id=str(row.site_id),  # type: ignore[attr-defined]
        source_property_id=int(row.source_property_id),  # type: ignore[attr-defined]
        recipient_email=str(row.recipient_email),  # type: ignore[attr-defined]
        status=str(row.status),  # type: ignore[attr-defined]
        provider_message_id=(
            str(row.provider_message_id)  # type: ignore[attr-defined]
            if row.provider_message_id is not None  # type: ignore[attr-defined]
            else None
        ),
        error_message=(
            str(row.error_message)  # type: ignore[attr-defined]
            if row.error_message is not None  # type: ignore[attr-defined]
            else None
        ),
        sent_at=isoformat(row.sent_at),  # type: ignore[attr-defined]
        created_at=isoformat(row.created_at) or "",  # type: ignore[attr-defined]
        updated_at=isoformat(row.updated_at) or "",  # type: ignore[attr-defined]
    )


class EmailNotificationRepository(ModuleRepository):
    def insert_pending(
        self,
        *,
        agency_id: str,
        event_kind: str,
        site_id: str,
        source_property_id: int,
        recipient_email: str,
    ) -> EmailRecord:
        """Idempotent insert of a queued row.

        Uses ``ON CONFLICT (uq_email_notifications_dedup) DO UPDATE SET
        updated_at = EXCLUDED.updated_at`` so the statement always
        returns the row (whether newly created or pre-existing) without
        duplicating it. The trade-off vs ``DO NOTHING`` is that this
        bumps ``updated_at`` on conflict; the dispatch use case in
        feature 27 relies on that to know the latest activity on a
        slot.
        """

        timestamp = utcnow()
        row = self.session.execute(
            text(
                "INSERT INTO email_notifications ("
                "id, agency_id, event_kind, site_id, source_property_id, "
                "recipient_email, status, provider_message_id, error_message, "
                "sent_at, created_at, updated_at"
                ") VALUES ("
                ":id, :agency_id, :event_kind, :site_id, :source_property_id, "
                ":recipient_email, :status, NULL, NULL, "
                "NULL, :created_at, :updated_at"
                ") ON CONFLICT ON CONSTRAINT uq_email_notifications_dedup "
                "DO UPDATE SET updated_at = EXCLUDED.updated_at "
                f"RETURNING {_SELECT_COLUMNS}"
            ),
            {
                "id": str(uuid4()),
                "agency_id": agency_id,
                "event_kind": event_kind,
                "site_id": site_id,
                "source_property_id": source_property_id,
                "recipient_email": recipient_email,
                "status": STATUS_QUEUED,
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        ).first()
        assert row is not None
        return _row_to_record(row)

    def get(self, *, email_id: str) -> EmailRecord | None:
        row = self.session.execute(
            text(
                f"SELECT {_SELECT_COLUMNS} FROM email_notifications "
                "WHERE id = :email_id"
            ),
            {"email_id": email_id},
        ).first()
        if row is None:
            return None
        return _row_to_record(row)

    def list_by_agency(
        self, *, agency_id: str, limit: int = 100
    ) -> tuple[EmailRecord, ...]:
        rows = self.session.execute(
            text(
                f"SELECT {_SELECT_COLUMNS} FROM email_notifications "
                "WHERE agency_id = :agency_id "
                "ORDER BY created_at DESC LIMIT :limit"
            ),
            {"agency_id": agency_id, "limit": limit},
        ).all()
        return tuple(_row_to_record(row) for row in rows)

    def list_by_status(
        self, *, status: str, limit: int = 100
    ) -> tuple[EmailRecord, ...]:
        rows = self.session.execute(
            text(
                f"SELECT {_SELECT_COLUMNS} FROM email_notifications "
                "WHERE status = :status "
                "ORDER BY created_at ASC LIMIT :limit"
            ),
            {"status": status, "limit": limit},
        ).all()
        return tuple(_row_to_record(row) for row in rows)

    def mark_sent(
        self,
        *,
        email_id: str,
        provider_message_id: str | None,
        sent_at: datetime,
    ) -> EmailRecord:
        timestamp = utcnow()
        row = self.session.execute(
            text(
                "UPDATE email_notifications SET "
                "status = :status, "
                "provider_message_id = :provider_message_id, "
                "error_message = NULL, "
                "sent_at = :sent_at, "
                "updated_at = :updated_at "
                "WHERE id = :email_id "
                f"RETURNING {_SELECT_COLUMNS}"
            ),
            {
                "email_id": email_id,
                "status": "sent",
                "provider_message_id": provider_message_id,
                "sent_at": sent_at,
                "updated_at": timestamp,
            },
        ).first()
        assert row is not None
        return _row_to_record(row)

    def mark_failed(
        self,
        *,
        email_id: str,
        error_message: str,
    ) -> EmailRecord:
        timestamp = utcnow()
        row = self.session.execute(
            text(
                "UPDATE email_notifications SET "
                "status = :status, "
                "error_message = :error_message, "
                "updated_at = :updated_at "
                "WHERE id = :email_id "
                f"RETURNING {_SELECT_COLUMNS}"
            ),
            {
                "email_id": email_id,
                "status": "failed",
                "error_message": error_message,
                "updated_at": timestamp,
            },
        ).first()
        assert row is not None
        return _row_to_record(row)

    def find_recent_sent(
        self,
        *,
        agency_id: str,
        recipient_email: str,
        since: datetime,
    ) -> EmailRecord | None:
        """Return the most recent ``status='sent'`` row for the
        (agency, recipient) pair whose ``sent_at >= since``.

        Used by the feature-27 throttle (max 1 send per minute per
        agency+recipient). ``since`` is the lower bound of the throttle
        window (e.g. ``utcnow() - timedelta(seconds=60)``).
        """

        row = self.session.execute(
            text(
                f"SELECT {_SELECT_COLUMNS} FROM email_notifications "
                "WHERE agency_id = :agency_id "
                "AND recipient_email = :recipient_email "
                "AND status = 'sent' "
                "AND sent_at IS NOT NULL "
                "AND sent_at >= :since "
                "ORDER BY sent_at DESC LIMIT 1"
            ),
            {
                "agency_id": agency_id,
                "recipient_email": recipient_email,
                "since": since,
            },
        ).first()
        if row is None:
            return None
        return _row_to_record(row)


__all__ = ["EmailNotificationRepository"]
