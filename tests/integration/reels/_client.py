"""Shared test client builder + DB seed helpers for admin reels tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from apps.api.admin_auth import AdminAccessPolicy
from apps.api.error_handlers import register_error_handlers
from modules.reels.transport.http.admin_reels_router import (
    create_admin_reels_router,
)
from shared.db import DatabaseUnitOfWork

ADMIN_BEARER = {"Authorization": "Bearer test-admin-token"}


def build_admin_reels_client(
    *,
    database_url: str,
    workspace_dir: Path,
    job_max_attempts: int = 3,
    default_platforms: tuple[str, ...] = ("instagram",),
) -> TestClient:
    policy = AdminAccessPolicy(
        enabled=True,
        base_path="/v1/admin",
        bearer_token="test-admin-token",
        disable_auth_for_testing=False,
    )
    app = FastAPI()
    factory = lambda: DatabaseUnitOfWork(database_url, workspace_dir)  # noqa: E731
    app.include_router(
        create_admin_reels_router(
            unit_of_work_factory=factory,
            admin_access_policy=policy,
            workspace_dir=workspace_dir,
            job_max_attempts=job_max_attempts,
            default_platforms=default_platforms,
        )
    )
    register_error_handlers(app)
    return TestClient(app)


def seed_property_with_reel(
    database_url: str,
    *,
    agency_id: str,
    ingestion_source_id: str,
    external_source_id: str,
    source_property_id: int = 42,
    raw_json: dict | None = None,
    workflow_state: str = "rendered",
    publish_status: str = "ready_to_publish",
    revision_media_path: str = "",
    revision_metadata_path: str = "",
) -> str:
    """Insert a property + reel row + media revision. Returns the revision id."""
    timestamp = datetime.now(timezone.utc)
    revision_id = str(uuid4())
    raw_payload = raw_json if raw_json is not None else {
        "id": source_property_id,
        "title": "Sample",
        "rest_domain": external_source_id,
    }
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO properties ("
                    "agency_id, ingestion_source_id, external_source_id, "
                    "source_property_id, slug, title, raw_json, fetched_at"
                    ") VALUES ("
                    ":agency_id, :ingestion_source_id, :external_source_id, "
                    ":source_property_id, :slug, :title, "
                    "CAST(:raw_json AS jsonb), :fetched_at"
                    ")"
                ),
                {
                    "agency_id": agency_id,
                    "ingestion_source_id": ingestion_source_id,
                    "external_source_id": external_source_id,
                    "source_property_id": source_property_id,
                    "slug": "sample",
                    "title": "Sample",
                    "raw_json": json.dumps(raw_payload),
                    "fetched_at": timestamp,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO reels ("
                    "agency_id, ingestion_source_id, external_source_id, "
                    "source_property_id, workflow_state, publish_status, "
                    "render_status, current_revision_id, created_at, updated_at"
                    ") VALUES ("
                    ":agency_id, :ingestion_source_id, :external_source_id, "
                    ":source_property_id, :workflow_state, :publish_status, "
                    "'completed', :revision_id, :created_at, :updated_at"
                    ")"
                ),
                {
                    "agency_id": agency_id,
                    "ingestion_source_id": ingestion_source_id,
                    "external_source_id": external_source_id,
                    "source_property_id": source_property_id,
                    "workflow_state": workflow_state,
                    "publish_status": publish_status,
                    "revision_id": revision_id,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO media_revisions ("
                    "revision_id, agency_id, ingestion_source_id, "
                    "external_source_id, source_property_id, artifact_kind, "
                    "media_path, metadata_path, created_at"
                    ") VALUES ("
                    ":revision_id, :agency_id, :ingestion_source_id, "
                    ":external_source_id, :source_property_id, 'reel_video', "
                    ":media_path, :metadata_path, :created_at"
                    ")"
                ),
                {
                    "revision_id": revision_id,
                    "agency_id": agency_id,
                    "ingestion_source_id": ingestion_source_id,
                    "external_source_id": external_source_id,
                    "source_property_id": source_property_id,
                    "media_path": revision_media_path,
                    "metadata_path": revision_metadata_path,
                    "created_at": timestamp,
                },
            )
    finally:
        engine.dispose()
    return revision_id


def seed_property_image(
    database_url: str,
    *,
    external_source_id: str,
    source_property_id: int,
    position: int,
    image_url: str,
    local_path: str | None = None,
) -> None:
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT record_id FROM properties WHERE "
                    "external_source_id = :id AND source_property_id = :pid"
                ),
                {"id": external_source_id, "pid": source_property_id},
            ).first()
            assert row is not None
            connection.execute(
                text(
                    "INSERT INTO property_images ("
                    "record_id, position, image_url, local_path"
                    ") VALUES (:record_id, :position, :image_url, :local_path)"
                ),
                {
                    "record_id": int(row.record_id),
                    "position": position,
                    "image_url": image_url,
                    "local_path": local_path,
                },
            )
    finally:
        engine.dispose()


def insert_legacy_queued_job(
    database_url: str,
    *,
    agency_id: str,
    ingestion_source_id: str,
    external_source_id: str,
    property_id: int,
) -> tuple[str, str]:
    """Pre-seed an event + queued job so the regenerate flow can supersede it.

    Returns the `(event_id, job_id)` of the seeded row.
    """
    timestamp = datetime.now(timezone.utc).isoformat()
    event_id = str(uuid4())
    job_id = str(uuid4())
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO webhook_events ("
                    "event_id, agency_id, ingestion_source_id, "
                    "external_source_id, source_kind, property_id, "
                    "received_at, updated_at, status, raw_payload_hash"
                    ") VALUES ("
                    ":event_id, :agency_id, :ingestion_source_id, "
                    ":external_source_id, 'wordpress', :property_id, "
                    ":received_at, :received_at, 'queued', 'hash-old'"
                    ")"
                ),
                {
                    "event_id": event_id,
                    "agency_id": agency_id,
                    "ingestion_source_id": ingestion_source_id,
                    "external_source_id": external_source_id,
                    "property_id": property_id,
                    "received_at": timestamp,
                },
            )
            from shared.db.security import encrypt_text
            connection.execute(
                text(
                    "INSERT INTO jobs ("
                    "job_id, event_id, agency_id, ingestion_source_id, kind, "
                    "external_source_id, property_id, received_at, "
                    "raw_payload_hash, status, payload_json, "
                    "publish_context_json, provider_secrets_encrypted, "
                    "attempt_count, max_attempts, available_at, worker_id, "
                    "created_at, updated_at"
                    ") VALUES ("
                    ":job_id, :event_id, :agency_id, :ingestion_source_id, "
                    "'reel_publish', :external_source_id, :property_id, "
                    ":received_at, 'hash-old', 'queued', "
                    "CAST('{}' AS jsonb), CAST('{}' AS jsonb), "
                    ":empty_token, 0, 3, :received_at, '', "
                    ":received_at, :received_at"
                    ")"
                ),
                {
                    "job_id": job_id,
                    "event_id": event_id,
                    "agency_id": agency_id,
                    "ingestion_source_id": ingestion_source_id,
                    "external_source_id": external_source_id,
                    "property_id": property_id,
                    "received_at": timestamp,
                    "empty_token": encrypt_text(""),
                },
            )
    finally:
        engine.dispose()
    return event_id, job_id


__all__ = [
    "ADMIN_BEARER",
    "build_admin_reels_client",
    "insert_legacy_queued_job",
    "seed_property_image",
    "seed_property_with_reel",
]
