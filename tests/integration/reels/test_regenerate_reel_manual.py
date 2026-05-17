"""Integration tests for the manual regenerate endpoint (feature 40).

Coverage:

* happy path — ``POST .../regenerate`` returns 200 with
  ``{render_status:"pending", job_id, queued_at}``; a fresh
  ``reel_publish`` job lands in ``status='queued'``; ``workflow_state``
  and ``publish_status`` are **not** mutated.
* 404 path — unknown ``(site_id, source_property_id)``.
* 409 ``REGENERATE_PUBLISHED_FORBIDDEN`` — reel already published.
* 409 ``REGENERATE_ALREADY_IN_FLIGHT`` — there is already a
  ``reel_publish`` job in ``queued`` / ``processing`` status for the
  same property.
* override survives — when the reel carries a ``photos_override``,
  the newly enqueued job sits next to that override (the renderer
  reads ``reels.photos_override`` directly at render time via the
  ingest pipeline; this test asserts the override was not cleared).
* regression guard — the legacy approve handler keeps replaying the
  same active job with ``idempotent_replay=True`` (feature 25
  contract) even after the use case grew the ``mode`` parameter.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.integration.reels._client import (
    ADMIN_BEARER,
    build_admin_reels_client,
    insert_legacy_queued_job,
    seed_property_with_reel,
)
from tests.support.postgres import (
    seed_provider_connection,
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


def _seed_reel_defaults(database_url: str, *, agency_id: str) -> None:
    timestamp = datetime.now(timezone.utc)
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO agency_reel_defaults ("
                    "agency_id, platforms, duration_seconds, music_id, "
                    "intro_enabled, caption_template, render_template_id, "
                    "settings, created_at, updated_at"
                    ") VALUES ("
                    ":agency_id, :platforms, 30, '', TRUE, '', 'classic', "
                    "CAST('{}' AS jsonb), :created_at, :updated_at"
                    ")"
                ),
                {
                    "agency_id": agency_id,
                    "platforms": ["instagram"],
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )
    finally:
        engine.dispose()


def _read_reel_state(
    database_url: str,
    *,
    external_source_id: str,
    source_property_id: int,
):
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT workflow_state, publish_status, render_status, "
                    "photos_override "
                    "FROM reels WHERE external_source_id = :site "
                    "AND source_property_id = :pid"
                ),
                {"site": external_source_id, "pid": source_property_id},
            ).first()
    finally:
        engine.dispose()
    return row


def _read_job(database_url: str, *, job_id: str):
    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as connection:
            row = connection.execute(
                text(
                    "SELECT job_id, status, kind, property_id, "
                    "external_source_id, publish_context_json "
                    "FROM jobs WHERE job_id = :job_id"
                ),
                {"job_id": job_id},
            ).first()
    finally:
        engine.dispose()
    return row


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_regenerate_manual_enqueues_job_without_touching_workflow_state() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "tok-1"},
            )
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                workflow_state="rendered",
                publish_status="needs-approval",
            )

            before = _read_reel_state(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            assert before is not None
            assert before.workflow_state == "rendered"
            assert before.publish_status == "needs-approval"

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/regenerate",
                headers=ADMIN_BEARER,
                json={"reason": "Frontend manual button"},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["render_status"] == "pending"
            assert body["job_id"]
            assert body["queued_at"]

            # workflow_state + publish_status invariants
            after = _read_reel_state(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            assert after is not None
            assert after.workflow_state == "rendered"
            assert after.publish_status == "needs-approval"

            job = _read_job(database.url, job_id=body["job_id"])
            assert job is not None
            assert job.status == "queued"
            assert job.kind == "reel_publish"
            assert job.property_id == 42
            assert job.external_source_id == seeded.external_source_id
            # The optional ``reason`` and the manual-mode discriminator
            # ride along on the publish_context_json so the audit log
            # can distinguish manual re-renders.
            context = job.publish_context_json or {}
            assert context.get("regenerate_mode") == "manual_only"
            assert context.get("manual_reason") == "Frontend manual button"


def test_regenerate_manual_accepts_empty_body() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "tok-1"},
            )
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/regenerate",
                headers=ADMIN_BEARER,
                json={},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["render_status"] == "pending"
            assert body["job_id"]


# ---------------------------------------------------------------------------
# 404
# ---------------------------------------------------------------------------


def test_regenerate_manual_returns_404_for_unknown_reel() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/9999/regenerate",
                headers=ADMIN_BEARER,
                json={},
            )
            assert response.status_code == 404, response.text


# ---------------------------------------------------------------------------
# 409 REGENERATE_PUBLISHED_FORBIDDEN
# ---------------------------------------------------------------------------


def test_regenerate_manual_returns_409_when_already_published() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "tok-1"},
            )
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                workflow_state="published",
                publish_status="published",
            )

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/regenerate",
                headers=ADMIN_BEARER,
                json={},
            )
            assert response.status_code == 409, response.text
            body = response.json()
            assert body == {
                "error": "REGENERATE_PUBLISHED_FORBIDDEN",
                "detail": (
                    "Cannot re-render a reel that has already been "
                    "published."
                ),
            }


# ---------------------------------------------------------------------------
# 409 REGENERATE_ALREADY_IN_FLIGHT
# ---------------------------------------------------------------------------


def test_regenerate_manual_returns_409_when_active_job_already_exists() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "tok-1"},
            )
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            # Seed an existing job in ``processing`` status for the same
            # (external_source_id, property_id, kind) tuple. The use
            # case must raise ``RegenerateAlreadyInFlight`` and the
            # router must surface it as 409.
            old_event_id, old_job_id = insert_legacy_queued_job(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                property_id=42,
            )
            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE jobs SET status = 'processing' "
                            "WHERE job_id = :job_id"
                        ),
                        {"job_id": old_job_id},
                    )
            finally:
                engine.dispose()

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/regenerate",
                headers=ADMIN_BEARER,
                json={},
            )
            assert response.status_code == 409, response.text
            body = response.json()
            assert body == {
                "error": "REGENERATE_ALREADY_IN_FLIGHT",
                "detail": (
                    "A render is already in progress for this reel. "
                    "Wait for it to finish."
                ),
            }
            # Sanity: the pre-existing processing job is still around
            # and untouched.
            job = _read_job(database.url, job_id=old_job_id)
            assert job is not None
            assert job.status == "processing"


def test_regenerate_manual_returns_409_when_queued_job_already_exists() -> None:
    """``queued`` is also treated as ``in flight`` (mirror of approve idempotence)."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "tok-1"},
            )
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            insert_legacy_queued_job(  # leaves status='queued' by default
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                property_id=42,
            )

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/regenerate",
                headers=ADMIN_BEARER,
                json={},
            )
            assert response.status_code == 409, response.text
            assert (
                response.json()["error"] == "REGENERATE_ALREADY_IN_FLIGHT"
            )


# ---------------------------------------------------------------------------
# Override survives
# ---------------------------------------------------------------------------


def test_regenerate_manual_preserves_photos_override_on_reel() -> None:
    """A reel with ``photos_override`` set keeps the override after a manual regenerate.

    The renderer reads ``reels.photos_override`` straight from the
    persisted row at render time (via
    ``_build_ingested_reel_state``) — the override does **not** travel
    on the job's ``publish_context``. This test guards against the
    use case accidentally clearing the column when re-enqueueing.
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "tok-1"},
            )
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )

            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE reels SET photos_override = "
                            "CAST(:override AS jsonb) "
                            "WHERE external_source_id = :site "
                            "AND source_property_id = :pid"
                        ),
                        {
                            "override": (
                                '[{"position":0,"selected":true},'
                                '{"position":1,"selected":false}]'
                            ),
                            "site": seeded.external_source_id,
                            "pid": 42,
                        },
                    )
            finally:
                engine.dispose()

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/regenerate",
                headers=ADMIN_BEARER,
                json={},
            )
            assert response.status_code == 200, response.text

            after = _read_reel_state(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            assert after is not None
            assert after.photos_override == [
                {"position": 0, "selected": True},
                {"position": 1, "selected": False},
            ]

            # Cross-check that the use case can still see the override
            # through the proper read path (``uow.reels.states.get``):
            # this is the data the ingest use case feeds into the
            # ``PropertyContext`` at render time.
            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                state = uow.reels.states.get(  # type: ignore[union-attr]
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                )
            assert state is not None
            assert state.photos_override == [
                {"position": 0, "selected": True},
                {"position": 1, "selected": False},
            ]


# ---------------------------------------------------------------------------
# Regression guard: the approve handler keeps replaying active jobs.
# ---------------------------------------------------------------------------


def test_approve_handler_still_replays_queued_job_after_mode_extension() -> None:
    """Feature 25 contract guard.

    The approve handler invokes ``RegenerateReelUseCase.execute`` with
    the default ``mode='approve_and_regenerate'``. Even with a queued
    job already in place — the same trigger feature 40's manual path
    rejects with 409 — approve must short-circuit with
    ``idempotent_replay=True`` and reuse the existing ``job_id`` /
    ``event_id``.
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "tok-1"},
            )
            _seed_reel_defaults(database.url, agency_id=seeded.agency_id)
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            old_event_id, old_job_id = insert_legacy_queued_job(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                property_id=42,
            )

            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/approve",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["publish_enqueued"] is True
            assert body.get("idempotent_replay") is True
            assert body["job_id"] == old_job_id
            assert body["event_id"] == old_event_id
