from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from repositories.sqlite_connection import create_sqlite_connection

PROPERTY_JOB_TABLE_NAME = "job_queue"


@dataclass(frozen=True, slots=True)
class PropertyJobEnqueueRequest:
    job_id: str
    event_id: str
    site_id: str
    property_id: int | None
    received_at: str
    raw_payload_hash: str
    payload_json: str
    publish_context_json: str
    gohighlevel_access_token: str
    max_attempts: int
    available_at: str
    created_at: str


@dataclass(frozen=True, slots=True)
class QueuedPropertyJobRecord:
    job_id: str
    event_id: str
    site_id: str
    property_id: int | None
    received_at: str
    raw_payload_hash: str
    status: str
    payload_json: str
    publish_context_json: str
    gohighlevel_access_token: str
    attempt_count: int
    max_attempts: int
    available_at: str
    lease_expires_at: str
    worker_id: str
    last_error: str | None
    created_at: str
    updated_at: str
    finished_at: str
    superseded_by_job_id: str


def _build_job_queue_table_sql() -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {PROPERTY_JOB_TABLE_NAME} (
            job_id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            site_id TEXT NOT NULL,
            property_id INTEGER,
            received_at TEXT NOT NULL DEFAULT '',
            raw_payload_hash TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            publish_context_json TEXT NOT NULL DEFAULT '',
            gohighlevel_access_token TEXT NOT NULL DEFAULT '',
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 1,
            available_at TEXT NOT NULL,
            lease_expires_at TEXT NOT NULL DEFAULT '',
            worker_id TEXT NOT NULL DEFAULT '',
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            finished_at TEXT NOT NULL DEFAULT '',
            superseded_by_job_id TEXT NOT NULL DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_job_queue_status_available_at
        ON {PROPERTY_JOB_TABLE_NAME} (status, available_at, created_at);

        CREATE INDEX IF NOT EXISTS idx_job_queue_site_property_status
        ON {PROPERTY_JOB_TABLE_NAME} (site_id, property_id, status, created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_job_queue_processing_lease
        ON {PROPERTY_JOB_TABLE_NAME} (status, lease_expires_at);
    """


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PropertyJobRepository:
    def __init__(
        self,
        database_path: str | Path,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self._owns_connection = connection is None
        self.connection = connection or create_sqlite_connection(self.database_path)

    def __enter__(self) -> "PropertyJobRepository":
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
        self.connection.executescript(_build_job_queue_table_sql())
        self._ensure_job_queue_columns()

    def _get_table_columns(self) -> set[str]:
        return {
            str(row[1])
            for row in self.connection.execute(f"PRAGMA table_info({PROPERTY_JOB_TABLE_NAME})")
        }

    def _ensure_job_queue_columns(self) -> None:
        existing_columns = self._get_table_columns()
        required_columns = {
            "gohighlevel_access_token": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in required_columns.items():
            if column in existing_columns:
                continue
            self.connection.execute(
                f"ALTER TABLE {PROPERTY_JOB_TABLE_NAME} ADD COLUMN {column} {definition}"
            )

    def enqueue_job(self, request: PropertyJobEnqueueRequest) -> None:
        self.connection.execute(
            f"""
            INSERT INTO {PROPERTY_JOB_TABLE_NAME} (
                job_id,
                event_id,
                site_id,
                property_id,
                received_at,
                raw_payload_hash,
                status,
                payload_json,
                publish_context_json,
                gohighlevel_access_token,
                attempt_count,
                max_attempts,
                available_at,
                lease_expires_at,
                worker_id,
                last_error,
                created_at,
                updated_at,
                finished_at,
                superseded_by_job_id
            )
            VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, 0, ?, ?, '', '', NULL, ?, ?, '', '')
            """,
            (
                request.job_id,
                request.event_id,
                request.site_id,
                request.property_id,
                request.received_at,
                request.raw_payload_hash,
                request.payload_json,
                request.publish_context_json,
                request.gohighlevel_access_token,
                max(1, request.max_attempts),
                request.available_at,
                request.created_at,
                request.created_at,
            ),
        )

    def supersede_queued_jobs(
        self,
        *,
        site_id: str,
        property_id: int | None,
        superseded_by_job_id: str,
        finished_at: str | None = None,
    ) -> tuple[str, ...]:
        if property_id is None:
            return ()
        completed_at = finished_at or _now_iso()
        rows = self.connection.execute(
            f"""
            SELECT event_id
            FROM {PROPERTY_JOB_TABLE_NAME}
            WHERE site_id = ?
            AND property_id = ?
            AND status = 'queued'
            ORDER BY created_at DESC, job_id DESC
            """,
            (site_id, property_id),
        ).fetchall()
        if not rows:
            return ()
        self.connection.execute(
            f"""
            UPDATE {PROPERTY_JOB_TABLE_NAME}
            SET status = 'superseded',
                publish_context_json = '',
                gohighlevel_access_token = '',
                last_error = 'Superseded by a newer queued job.',
                updated_at = ?,
                finished_at = ?,
                superseded_by_job_id = ?
            WHERE site_id = ?
            AND property_id = ?
            AND status = 'queued'
            """,
            (completed_at, completed_at, superseded_by_job_id, site_id, property_id),
        )
        return tuple(str(row["event_id"]) for row in rows)

    def recover_expired_processing_jobs(self, *, now: str | None = None) -> int:
        active_now = now or _now_iso()
        cursor = self.connection.execute(
            f"""
            UPDATE {PROPERTY_JOB_TABLE_NAME}
            SET status = 'queued',
                worker_id = '',
                lease_expires_at = '',
                updated_at = ?,
                available_at = ?
            WHERE status = 'processing'
            AND lease_expires_at != ''
            AND lease_expires_at <= ?
            """,
            (active_now, active_now, active_now),
        )
        return int(cursor.rowcount or 0)

    def claim_next_ready_job(
        self,
        *,
        worker_id: str,
        lease_expires_at: str,
        now: str | None = None,
    ) -> QueuedPropertyJobRecord | None:
        active_now = now or _now_iso()
        row = self.connection.execute(
            f"""
            UPDATE {PROPERTY_JOB_TABLE_NAME}
            SET status = 'processing',
                attempt_count = attempt_count + 1,
                worker_id = ?,
                lease_expires_at = ?,
                updated_at = ?
            WHERE job_id = (
                SELECT candidate.job_id
                FROM {PROPERTY_JOB_TABLE_NAME} AS candidate
                WHERE candidate.status = 'queued'
                AND candidate.available_at <= ?
                AND NOT EXISTS (
                    SELECT 1
                    FROM {PROPERTY_JOB_TABLE_NAME} AS processing
                    WHERE processing.status = 'processing'
                    AND processing.site_id = candidate.site_id
                    AND processing.property_id IS NOT NULL
                    AND candidate.property_id IS NOT NULL
                    AND processing.property_id = candidate.property_id
                )
                ORDER BY candidate.created_at ASC, candidate.job_id ASC
                LIMIT 1
            )
            RETURNING
                job_id,
                event_id,
                site_id,
                property_id,
                received_at,
                raw_payload_hash,
                status,
                payload_json,
                publish_context_json,
                gohighlevel_access_token,
                attempt_count,
                max_attempts,
                available_at,
                lease_expires_at,
                worker_id,
                last_error,
                created_at,
                updated_at,
                finished_at,
                superseded_by_job_id
            """,
            (worker_id, lease_expires_at, active_now, active_now),
        ).fetchone()
        if row is None:
            return None
        return _row_to_queued_job(row)

    def renew_job_lease(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_expires_at: str,
        now: str | None = None,
    ) -> bool:
        active_now = now or _now_iso()
        cursor = self.connection.execute(
            f"""
            UPDATE {PROPERTY_JOB_TABLE_NAME}
            SET lease_expires_at = ?,
                updated_at = ?
            WHERE job_id = ?
            AND status = 'processing'
            AND worker_id = ?
            """,
            (lease_expires_at, active_now, job_id, worker_id),
        )
        return bool(cursor.rowcount)

    def mark_job_completed(self, *, job_id: str, finished_at: str | None = None) -> None:
        completed_at = finished_at or _now_iso()
        self.connection.execute(
            f"""
            UPDATE {PROPERTY_JOB_TABLE_NAME}
            SET status = 'completed',
                publish_context_json = '',
                gohighlevel_access_token = '',
                lease_expires_at = '',
                worker_id = '',
                last_error = NULL,
                updated_at = ?,
                finished_at = ?
            WHERE job_id = ?
            """,
            (completed_at, completed_at, job_id),
        )

    def mark_job_failed(
        self,
        *,
        job_id: str,
        error_message: str,
        finished_at: str | None = None,
    ) -> None:
        completed_at = finished_at or _now_iso()
        self.connection.execute(
            f"""
            UPDATE {PROPERTY_JOB_TABLE_NAME}
            SET status = 'failed',
                publish_context_json = '',
                gohighlevel_access_token = '',
                lease_expires_at = '',
                worker_id = '',
                last_error = ?,
                updated_at = ?,
                finished_at = ?
            WHERE job_id = ?
            """,
            (error_message, completed_at, completed_at, job_id),
        )

    def schedule_retry(
        self,
        *,
        job_id: str,
        error_message: str,
        available_at: str,
        now: str | None = None,
    ) -> None:
        active_now = now or _now_iso()
        self.connection.execute(
            f"""
            UPDATE {PROPERTY_JOB_TABLE_NAME}
            SET status = 'queued',
                lease_expires_at = '',
                worker_id = '',
                last_error = ?,
                updated_at = ?,
                available_at = ?,
                finished_at = ''
            WHERE job_id = ?
            """,
            (error_message, active_now, available_at, job_id),
        )

    def count_active_jobs(self) -> int:
        row = self.connection.execute(
            f"""
            SELECT COUNT(*)
            FROM {PROPERTY_JOB_TABLE_NAME}
            WHERE status IN ('queued', 'processing')
            """
        ).fetchone()
        return 0 if row is None else int(row[0])

    def get_job(self, job_id: str) -> QueuedPropertyJobRecord | None:
        row = self.connection.execute(
            f"""
            SELECT
                job_id,
                event_id,
                site_id,
                property_id,
                received_at,
                raw_payload_hash,
                status,
                payload_json,
                publish_context_json,
                gohighlevel_access_token,
                attempt_count,
                max_attempts,
                available_at,
                lease_expires_at,
                worker_id,
                last_error,
                created_at,
                updated_at,
                finished_at,
                superseded_by_job_id
            FROM {PROPERTY_JOB_TABLE_NAME}
            WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_queued_job(row)

    def list_jobs_for_property(
        self,
        *,
        site_id: str,
        property_id: int | None,
    ) -> tuple[QueuedPropertyJobRecord, ...]:
        rows = self.connection.execute(
            f"""
            SELECT
                job_id,
                event_id,
                site_id,
                property_id,
                received_at,
                raw_payload_hash,
                status,
                payload_json,
                publish_context_json,
                gohighlevel_access_token,
                attempt_count,
                max_attempts,
                available_at,
                lease_expires_at,
                worker_id,
                last_error,
                created_at,
                updated_at,
                finished_at,
                superseded_by_job_id
            FROM {PROPERTY_JOB_TABLE_NAME}
            WHERE site_id = ?
            AND property_id IS ?
            ORDER BY created_at ASC, job_id ASC
            """,
            (site_id, property_id),
        ).fetchall()
        return tuple(_row_to_queued_job(row) for row in rows)


def _row_to_queued_job(row: sqlite3.Row) -> QueuedPropertyJobRecord:
    return QueuedPropertyJobRecord(
        job_id=str(row["job_id"]),
        event_id=str(row["event_id"]),
        site_id=str(row["site_id"]),
        property_id=None if row["property_id"] is None else int(row["property_id"]),
        received_at=str(row["received_at"] or ""),
        raw_payload_hash=str(row["raw_payload_hash"] or ""),
        status=str(row["status"]),
        payload_json=str(row["payload_json"] or ""),
        publish_context_json=str(row["publish_context_json"] or ""),
        gohighlevel_access_token=str(row["gohighlevel_access_token"] or ""),
        attempt_count=int(row["attempt_count"] or 0),
        max_attempts=int(row["max_attempts"] or 1),
        available_at=str(row["available_at"] or ""),
        lease_expires_at=str(row["lease_expires_at"] or ""),
        worker_id=str(row["worker_id"] or ""),
        last_error=None if row["last_error"] is None else str(row["last_error"]),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
        finished_at=str(row["finished_at"] or ""),
        superseded_by_job_id=str(row["superseded_by_job_id"] or ""),
    )


__all__ = [
    "PROPERTY_JOB_TABLE_NAME",
    "PropertyJobRepository",
    "PropertyJobEnqueueRequest",
    "QueuedPropertyJobRecord",
]

