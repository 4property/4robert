"""Persistence for the Job aggregate.

Backs the worker queue. `claim_next_ready_job` uses `FOR UPDATE SKIP LOCKED`
so multiple workers can run concurrently. Property-level serialization is
encoded in the SQL: a `(external_source_id, property_id)` already in
`processing` blocks new claims for the same property.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from sqlalchemy import bindparam, text

from modules.delivery.domain import Job, JobEnqueueRequest
from shared.db.repository_base import ModuleRepository, utcnow
from shared.db.security import decrypt_text, encrypt_text


def _isoformat(value: object | None) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def _json_to_mapping(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(bytes(raw).decode("utf-8"))
    if isinstance(raw, str):
        return json.loads(raw) if raw.strip() else {}
    return dict(raw)


def _row_to_job(row) -> Job:
    secrets_value = row.provider_secrets_encrypted
    secret_bundle = decrypt_text(secrets_value) if secrets_value else ""
    return Job(
        job_id=str(row.job_id),
        event_id=str(row.event_id or ""),
        agency_id=str(row.agency_id or ""),
        ingestion_source_id=str(row.ingestion_source_id or ""),
        kind=str(row.kind or "reel_publish"),
        external_source_id=str(row.external_source_id or ""),
        property_id=None if row.property_id is None else int(row.property_id),
        received_at=_isoformat(row.received_at) or "",
        raw_payload_hash=str(row.raw_payload_hash or ""),
        status=str(row.status or ""),
        payload=_json_to_mapping(row.payload_json),
        publish_context=_json_to_mapping(row.publish_context_json),
        provider_secret_bundle=secret_bundle,
        attempt_count=int(row.attempt_count or 0),
        max_attempts=int(row.max_attempts or 1),
        available_at=_isoformat(row.available_at) or "",
        lease_expires_at=_isoformat(row.lease_expires_at),
        worker_id=str(row.worker_id or ""),
        last_error=None if row.last_error is None else str(row.last_error),
        created_at=_isoformat(row.created_at) or "",
        updated_at=_isoformat(row.updated_at) or "",
        finished_at=_isoformat(row.finished_at),
        superseded_by_job_id=str(row.superseded_by_job_id or ""),
    )


_SELECT_JOB_COLUMNS = (
    "job_id, event_id, agency_id, ingestion_source_id, kind, "
    "external_source_id, property_id, received_at, raw_payload_hash, status, "
    "payload_json, publish_context_json, provider_secrets_encrypted, "
    "attempt_count, max_attempts, available_at, lease_expires_at, worker_id, "
    "last_error, created_at, updated_at, finished_at, superseded_by_job_id"
)


class JobRepository(ModuleRepository):
    """The durable work queue. Multi-worker safe via `FOR UPDATE SKIP LOCKED`."""

    def enqueue_job(self, request: JobEnqueueRequest) -> None:
        self.session.execute(
            text(
                "INSERT INTO jobs ("
                "job_id, event_id, agency_id, ingestion_source_id, kind, "
                "external_source_id, property_id, received_at, raw_payload_hash, "
                "status, payload_json, publish_context_json, "
                "provider_secrets_encrypted, attempt_count, max_attempts, "
                "available_at, worker_id, created_at, updated_at"
                ") VALUES ("
                ":job_id, :event_id, :agency_id, :ingestion_source_id, :kind, "
                ":external_source_id, :property_id, :received_at, :raw_payload_hash, "
                "'queued', CAST(:payload_json AS jsonb), "
                "CAST(:publish_context_json AS jsonb), "
                ":provider_secrets_encrypted, 0, :max_attempts, "
                ":available_at, '', :created_at, :updated_at"
                ")"
            ),
            {
                "job_id": request.job_id,
                "event_id": request.event_id,
                "agency_id": request.agency_id,
                "ingestion_source_id": request.ingestion_source_id,
                "kind": str(request.kind or "reel_publish").strip().lower(),
                "external_source_id": request.external_source_id,
                "property_id": request.property_id,
                "received_at": request.received_at,
                "raw_payload_hash": request.raw_payload_hash,
                "payload_json": json.dumps(dict(request.payload), separators=(",", ":")),
                "publish_context_json": json.dumps(
                    dict(request.publish_context), separators=(",", ":")
                ),
                "provider_secrets_encrypted": encrypt_text(request.provider_secret_bundle),
                "max_attempts": max(1, request.max_attempts),
                "available_at": request.available_at,
                "created_at": request.created_at,
                "updated_at": request.created_at,
            },
        )

    def supersede_queued_jobs(
        self,
        *,
        external_source_id: str,
        property_id: int | None,
        superseded_by_job_id: str,
        finished_at: str | None = None,
    ) -> tuple[str, ...]:
        if property_id is None:
            return ()
        completed_at = finished_at or utcnow().isoformat()
        rows = self.session.execute(
            text(
                "SELECT event_id FROM jobs "
                "WHERE external_source_id = :external_source_id "
                "AND property_id = :property_id AND status = 'queued' "
                "ORDER BY created_at DESC, job_id DESC"
            ),
            {"external_source_id": external_source_id, "property_id": property_id},
        ).all()
        if not rows:
            return ()
        self.session.execute(
            text(
                "UPDATE jobs SET status = 'superseded', "
                "publish_context_json = '{}'::jsonb, "
                "provider_secrets_encrypted = :empty_token, "
                "last_error = 'Superseded by a newer queued job.', "
                "updated_at = :updated_at, finished_at = :finished_at, "
                "superseded_by_job_id = :superseded_by_job_id "
                "WHERE external_source_id = :external_source_id "
                "AND property_id = :property_id AND status = 'queued'"
            ),
            {
                "empty_token": encrypt_text(""),
                "updated_at": completed_at,
                "finished_at": completed_at,
                "superseded_by_job_id": superseded_by_job_id,
                "external_source_id": external_source_id,
                "property_id": property_id,
            },
        )
        return tuple(str(row.event_id) for row in rows)

    def recover_expired_processing_jobs(self, *, now: str | None = None) -> int:
        active_now = now or utcnow().isoformat()
        cursor = self.session.execute(
            text(
                "UPDATE jobs SET status = 'queued', worker_id = '', "
                "lease_expires_at = NULL, updated_at = :updated_at, "
                "available_at = :available_at "
                "WHERE status = 'processing' AND lease_expires_at IS NOT NULL "
                "AND lease_expires_at <= :active_now"
            ),
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
        kinds: tuple[str, ...] | None = None,
        now: str | None = None,
    ) -> Job | None:
        active_now = now or utcnow().isoformat()
        params: dict[str, Any] = {
            "worker_id": worker_id,
            "lease_expires_at": lease_expires_at,
            "updated_at": active_now,
            "active_now": active_now,
        }
        kind_filter_sql = ""
        if kinds:
            kind_filter_sql = " AND candidate.kind IN :kinds"
            params["kinds"] = tuple(str(k).strip().lower() for k in kinds)
        statement = text(
            "WITH candidate AS ("
            "SELECT candidate.job_id FROM jobs AS candidate "
            "WHERE candidate.status = 'queued' "
            "AND candidate.available_at <= :active_now"
            f"{kind_filter_sql} "
            "AND NOT EXISTS ("
            "SELECT 1 FROM jobs AS processing "
            "WHERE processing.status = 'processing' "
            "AND processing.external_source_id = candidate.external_source_id "
            "AND processing.property_id IS NOT NULL "
            "AND candidate.property_id IS NOT NULL "
            "AND processing.property_id = candidate.property_id"
            ") "
            "ORDER BY candidate.created_at ASC, candidate.job_id ASC "
            "FOR UPDATE SKIP LOCKED LIMIT 1"
            ") "
            "UPDATE jobs AS queue SET status = 'processing', "
            "attempt_count = queue.attempt_count + 1, "
            "worker_id = :worker_id, "
            "lease_expires_at = :lease_expires_at, "
            "updated_at = :updated_at "
            "FROM candidate WHERE queue.job_id = candidate.job_id "
            f"RETURNING {_SELECT_JOB_COLUMNS.replace('job_id', 'queue.job_id', 1)}"
        )
        if kinds:
            statement = statement.bindparams(bindparam("kinds", expanding=True))
        row = self.session.execute(statement, params).first()
        return _row_to_job(row) if row is not None else None

    def renew_job_lease(
        self,
        *,
        job_id: str,
        worker_id: str,
        lease_expires_at: str,
        now: str | None = None,
    ) -> bool:
        active_now = now or utcnow().isoformat()
        cursor = self.session.execute(
            text(
                "UPDATE jobs SET lease_expires_at = :lease_expires_at, "
                "updated_at = :updated_at "
                "WHERE job_id = :job_id AND status = 'processing' "
                "AND worker_id = :worker_id"
            ),
            {
                "lease_expires_at": lease_expires_at,
                "updated_at": active_now,
                "job_id": job_id,
                "worker_id": worker_id,
            },
        )
        return bool(cursor.rowcount)

    def mark_job_completed(self, *, job_id: str, finished_at: str | None = None) -> None:
        completed_at = finished_at or utcnow().isoformat()
        self.session.execute(
            text(
                "UPDATE jobs SET status = 'completed', "
                "publish_context_json = '{}'::jsonb, "
                "provider_secrets_encrypted = :empty_token, "
                "lease_expires_at = NULL, worker_id = '', last_error = NULL, "
                "updated_at = :updated_at, finished_at = :finished_at "
                "WHERE job_id = :job_id"
            ),
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
        completed_at = finished_at or utcnow().isoformat()
        self.session.execute(
            text(
                "UPDATE jobs SET status = 'failed', "
                "publish_context_json = '{}'::jsonb, "
                "provider_secrets_encrypted = :empty_token, "
                "lease_expires_at = NULL, worker_id = '', "
                "last_error = :last_error, "
                "updated_at = :updated_at, finished_at = :finished_at "
                "WHERE job_id = :job_id"
            ),
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
        active_now = now or utcnow().isoformat()
        self.session.execute(
            text(
                "UPDATE jobs SET status = 'queued', lease_expires_at = NULL, "
                "worker_id = '', last_error = :last_error, "
                "updated_at = :updated_at, available_at = :available_at, "
                "finished_at = NULL "
                "WHERE job_id = :job_id"
            ),
            {
                "last_error": error_message,
                "updated_at": active_now,
                "available_at": available_at,
                "job_id": job_id,
            },
        )

    def count_active_jobs(self) -> int:
        row = self.session.execute(
            text(
                "SELECT COUNT(*) AS count FROM jobs "
                "WHERE status IN ('queued', 'processing')"
            )
        ).first()
        return 0 if row is None else int(row.count)

    def get_job(self, job_id: str) -> Job | None:
        row = self.session.execute(
            text(f"SELECT {_SELECT_JOB_COLUMNS} FROM jobs WHERE job_id = :job_id"),
            {"job_id": job_id},
        ).first()
        return _row_to_job(row) if row is not None else None

    def list_jobs_for_property(
        self,
        *,
        external_source_id: str,
        property_id: int | None,
    ) -> tuple[Job, ...]:
        rows = self.session.execute(
            text(
                f"SELECT {_SELECT_JOB_COLUMNS} FROM jobs "
                "WHERE external_source_id = :external_source_id "
                "AND property_id IS NOT DISTINCT FROM :property_id "
                "ORDER BY created_at ASC, job_id ASC"
            ),
            {"external_source_id": external_source_id, "property_id": property_id},
        ).all()
        return tuple(_row_to_job(row) for row in rows)


__all__ = ["JobRepository"]
