"""Job aggregate.

Backs `apps/worker/`. The `kind` discriminator routes to the right handler
(`reel_publish` → ReelPipeline, `scripted_render` → RenderScriptedVideo).
Adding a new job kind: register a handler in `apps/worker/runtime.py` and
enqueue with the new kind. No schema change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class JobEnqueueRequest:
    job_id: str
    event_id: str
    agency_id: str
    ingestion_source_id: str
    kind: str
    external_source_id: str
    property_id: int | None
    received_at: str
    raw_payload_hash: str
    payload: Mapping[str, Any]
    publish_context: Mapping[str, Any]
    provider_secret_bundle: str
    max_attempts: int
    available_at: str
    created_at: str


@dataclass(frozen=True, slots=True)
class Job:
    job_id: str
    event_id: str
    agency_id: str
    ingestion_source_id: str
    kind: str
    external_source_id: str
    property_id: int | None
    received_at: str
    raw_payload_hash: str
    status: str
    payload: Mapping[str, Any]
    publish_context: Mapping[str, Any]
    provider_secret_bundle: str
    attempt_count: int
    max_attempts: int
    available_at: str
    lease_expires_at: str | None
    worker_id: str
    last_error: str | None
    created_at: str
    updated_at: str
    finished_at: str | None
    superseded_by_job_id: str


__all__ = ["Job", "JobEnqueueRequest"]
