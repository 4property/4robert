from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repositories.postgres.repository import PostgresRepositoryBase, now_iso
from repositories.postgres.security import decrypt_text, encrypt_text

PROPERTY_JOB_TABLE_NAME = "job_queue"


@dataclass(frozen=True, slots=True)
class PropertyJobEnqueueRequest:
    job_id: str
    event_id: str
    agency_id: str
    wordpress_source_id: str
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
    agency_id: str
    wordpress_source_id: str
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


class PropertyJobRepository(PostgresRepositoryBase):
    def __init__(
        self,
        database_path: str | Path | None,
        *,
        connection=None,
    ) -> None:
        super().__init__(database_path, connection=connection)

    def initialise(self) -> None:
        return None

    def enqueue_job(self, request: PropertyJobEnqueueRequest) -> None:
        self.connection.execute(
            f"""
            INSERT INTO {PROPERTY_JOB_TABLE_NAME} (
                job_id,
                event_id,
                agency_id,
                wordpress_source_id,
                site_id,
                property_id,
                received_at,
                raw_payload_hash,
                status,
                payload_json,
                publish_context_json,
                gohighlevel_access_token_encrypted,
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
            VALUES (
                :job_id,
                :event_id,
                :agency_id,
                :wordpress_source_id,
                :site_id,
                :property_id,
                :received_at,
                :raw_payload_hash,
                'queued',
                :payload_json,
                :publish_context_json,
                :gohighlevel_access_token_encrypted,
                0,
                :max_attempts,
                :available_at,
                '',
                '',
                NULL,
                :created_at,
                :updated_at,
                '',
                ''
            )
            """,
            {
                "job_id": request.job_id,
                "event_id": request.event_id,
                "agency_id": request.agency_id,
                "wordpress_source_id": request.wordpress_source_id,
                "site_id": request.site_id,
                "property_id": request.property_id,
                "received_at": request.received_at,
                "raw_payload_hash": request.raw_payload_hash,
                "payload_json": request.payload_json,
                "publish_context_json": request.publish_context_json,
                "gohighlevel_access_token_encrypted": encrypt_text(request.gohighlevel_access_token),
                "max_attempts": max(1, request.max_attempts),
                "available_at": request.available_at,
                "created_at": request.created_at,
                "updated_at": request.created_at,
            },
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
        completed_at = finished_at or now_iso()
        rows = self.connection.execute(
            f"""
            SELECT event_id
            FROM {PROPERTY_JOB_TABLE_NAME}
            WHERE site_id = :site_id
            AND property_id = :property_id
            AND status = 'queued'
            ORDER BY created_at DESC, job_id DESC
            """,
            {
                "site_id": site_id,
                "property_id": property_id,
            },
        ).fetchall()
        if not rows:
            return ()
        self.connection.execute(
            f"""
            UPDATE {PROPERTY_JOB_TABLE_NAME}
            SET status = 'superseded',
                publish_context_json = '',
                gohighlevel_access_token_encrypted = :empty_token,
                last_error = 'Superseded by a newer queued job.',
                updated_at = :updated_at,
                finished_at = :finished_at,
                superseded_by_job_id = :superseded_by_job_id
            WHERE site_id = :site_id
            AND property_id = :property_id
            AND status = 'queued'
            """,
            {
                "empty_token": encrypt_text(""),
                "updated_at": completed_at,
                "finished_at": completed_at,
                "superseded_by_job_id": superseded_by_job_id,
                "site_id": site_id,
                "property_id": property_id,
            },
        )
        return tuple(str(row["event_id"]) for row in rows)

    def recover_expired_processing_jobs(self, *, now: str | None = None) -> int:
        active_now = now or now_iso()
        cursor = self.connection.execute(
            f"""
            UPDATE {PROPERTY_JOB_TABLE_NAME}
            SET status = 'queued',
                worker_id = '',
                lease_expires_at = '',
                updated_at = :updated_at,
                available_at = :available_at
            WHERE status = 'processing'
            AND lease_expires_at != ''
            AND lease_expires_at <= :active_now
            """,
            {
                "updated_at": active_now,
                "available_at": active_now,
                "active_now": active_now,
            },
        )
        return int(cursor.rowcount or 0)

    def claim_next_ready_job(
        self,
        *,
        worker_id: str,
        lease_expires_at: str,
        now: str | None = None,
    ) -> QueuedPropertyJobRecord | None:
        active_now = now or now_iso()
        row = self.connection.execute(
            f"""
            WITH candidate AS (
                SELECT candidate.job_id
                FROM {PROPERTY_JOB_TABLE_NAME} AS candidate
                WHERE candidate.status = 'queued'
                AND candidate.available_at <= :active_now
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
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE {PROPERTY_JOB_TABLE_NAME} AS queue
            SET status = 'processing',
                attempt_count = queue.attempt_count + 1,
                worker_id = :worker_id,
                lease_expires_at = :lease_expires_at,
                updated_at = :updated_at
            FROM candidate
            WHERE queue.job_id = candidate.job_id
            RETURNING
                queue.job_id,
                queue.event_id,
                queue.agency_id,
                queue.wordpress_source_id,
                queue.site_id,
                queue.property_id,
                queue.received_at,
                queue.raw_payload_hash,
                queue.status,
                queue.payload_json,
                queue.publish_context_json,
                queue.gohighlevel_access_token_encrypted,
                queue.attempt_count,
                queue.max_attempts,
                queue.available_at,
                queue.lease_expires_at,
                queue.worker_id,
                queue.last_error,
                queue.created_at,
                queue.updated_at,
                queue.finished_at,
                queue.superseded_by_job_id
            """,
            {
                "worker_id": worker_id,
                "lease_expires_at": lease_expires_at,
                "updated_at": active_now,
                "active_now": active_now,
            },
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
        active_now = now or now_iso()
        cursor = self.connection.execute(
            f"""
            UPDATE {PROPERTY_JOB_TABLE_NAME}
            SET lease_expires_at = :lease_expires_at,
                updated_at = :updated_at
            WHERE job_id = :job_id
            AND status = 'processing'
            AND worker_id = :worker_id
            """,
            {
                "lease_expires_at": lease_expires_at,
                "updated_at": active_now,
                "job_id": job_id,
                "worker_id": worker_id,
            },
        )
        return bool(cursor.rowcount)

    def mark_job_completed(self, *, job_id: str, finished_at: str | None = None) -> None:
        completed_at = finished_at or now_iso()
        self.connection.execute(
            f"""
            UPDATE {PROPERTY_JOB_TABLE_NAME}
            SET status = 'completed',
                publish_context_json = '',
                gohighlevel_access_token_encrypted = :empty_token,
                lease_expires_at = '',
                worker_id = '',
                last_error = NULL,
                updated_at = :updated_at,
                finished_at = :finished_at
            WHERE job_id = :job_id
            """,
            {
                "empty_token": encrypt_text(""),
                "updated_at": completed_at,
                "finished_at": completed_at,
                "job_id": job_id,
            },
        )

    def mark_job_failed(
        self,
        *,
        job_id: str,
        error_message: str,
        finished_at: str | None = None,
    ) -> None:
        completed_at = finished_at or now_iso()
        self.connection.execute(
            f"""
            UPDATE {PROPERTY_JOB_TABLE_NAME}
            SET status = 'failed',
                publish_context_json = '',
                gohighlevel_access_token_encrypted = :empty_token,
                lease_expires_at = '',
                worker_id = '',
                last_error = :last_error,
                updated_at = :updated_at,
                finished_at = :finished_at
            WHERE job_id = :job_id
            """,
            {
                "empty_token": encrypt_text(""),
                "last_error": error_message,
                "updated_at": completed_at,
                "finished_at": completed_at,
                "job_id": job_id,
            },
        )

    def schedule_retry(
        self,
        *,
        job_id: str,
        error_message: str,
        available_at: str,
        now: str | None = None,
    ) -> None:
        active_now = now or now_iso()
        self.connection.execute(
            f"""
            UPDATE {PROPERTY_JOB_TABLE_NAME}
            SET status = 'queued',
                lease_expires_at = '',
                worker_id = '',
                last_error = :last_error,
                updated_at = :updated_at,
                available_at = :available_at,
                finished_at = ''
            WHERE job_id = :job_id
            """,
            {
                "last_error": error_message,
                "updated_at": active_now,
                "available_at": available_at,
                "job_id": job_id,
            },
        )

    def count_active_jobs(self) -> int:
        row = self.connection.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM {PROPERTY_JOB_TABLE_NAME}
            WHERE status IN ('queued', 'processing')
            """
        ).fetchone()
        return 0 if row is None else int(row["count"])

    def get_job(self, job_id: str) -> QueuedPropertyJobRecord | None:
        row = self.connection.execute(
            f"""
            SELECT
                job_id,
                event_id,
                agency_id,
                wordpress_source_id,
                site_id,
                property_id,
                received_at,
                raw_payload_hash,
                status,
                payload_json,
                publish_context_json,
                gohighlevel_access_token_encrypted,
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
            WHERE job_id = :job_id
            """,
            {"job_id": job_id},
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
                agency_id,
                wordpress_source_id,
                site_id,
                property_id,
                received_at,
                raw_payload_hash,
                status,
                payload_json,
                publish_context_json,
                gohighlevel_access_token_encrypted,
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
            WHERE site_id = :site_id
            AND property_id IS NOT DISTINCT FROM :property_id
            ORDER BY created_at ASC, job_id ASC
            """,
            {
                "site_id": site_id,
                "property_id": property_id,
            },
        ).fetchall()
        return tuple(_row_to_queued_job(row) for row in rows)


def _row_to_queued_job(row) -> QueuedPropertyJobRecord:
    return QueuedPropertyJobRecord(
        job_id=str(row["job_id"]),
        event_id=str(row["event_id"]),
        agency_id=str(row["agency_id"]),
        wordpress_source_id=str(row["wordpress_source_id"]),
        site_id=str(row["site_id"]),
        property_id=None if row["property_id"] is None else int(row["property_id"]),
        received_at=str(row["received_at"] or ""),
        raw_payload_hash=str(row["raw_payload_hash"] or ""),
        status=str(row["status"]),
        payload_json=str(row["payload_json"] or ""),
        publish_context_json=str(row["publish_context_json"] or ""),
        gohighlevel_access_token=decrypt_text(row["gohighlevel_access_token_encrypted"]),
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
