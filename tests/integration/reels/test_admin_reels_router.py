"""Integration tests for the admin reels router."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text

from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.integration.reels._client import (
    ADMIN_BEARER,
    build_admin_reels_client,
    insert_legacy_queued_job,
    seed_automation_rules,
    seed_property_image,
    seed_property_with_reel,
)
from tests.support.postgres import (
    seed_provider_connection,
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


def test_list_reels_returns_empty_for_a_fresh_agency() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            # Feature 32 added pagination metadata. The legacy "items + "
            # count" contract is preserved; the extra fields are additive.
            assert payload["items"] == []
            assert payload["count"] == 0
            assert payload["count_total"] == 0
            assert payload["has_more"] is False


def test_list_reels_returns_seeded_reel() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
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

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["count"] == 1
            assert payload["items"][0]["site_id"] == seeded.external_source_id
            assert payload["items"][0]["source_property_id"] == 42


def test_list_reels_returns_404_for_missing_agency() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.get(
                "/v1/admin/agencies/missing/reels", headers=ADMIN_BEARER
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_AGENCY_NOT_FOUND"


def test_inspect_reel_returns_detail_with_no_video() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
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

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            reel = response.json()["reel"]
            assert reel["source_property_id"] == 42
            assert reel["has_video"] is False
            assert reel["video_url"] is None


def test_inspect_reel_returns_404_when_reel_missing() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_REEL_NOT_FOUND"


def test_inspect_reel_returns_404_when_agency_missing() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.get(
                "/v1/admin/agencies/missing/reels/site/1", headers=ADMIN_BEARER
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_AGENCY_NOT_FOUND"


def test_inspect_reel_marks_video_available_when_file_exists() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            video_path = workspace_dir / "rendered" / "demo.mp4"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            video_path.write_bytes(b"FAKE-MP4")
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                revision_media_path="rendered/demo.mp4",
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            reel = response.json()["reel"]
            assert reel["has_video"] is True
            assert reel["video_url"] == (
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/video"
            )


def test_video_endpoint_streams_file() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            video_path = workspace_dir / "rendered" / "demo.mp4"
            video_path.parent.mkdir(parents=True, exist_ok=True)
            video_path.write_bytes(b"DATA")
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                revision_media_path="rendered/demo.mp4",
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/video",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            assert response.content == b"DATA"


def test_video_endpoint_returns_404_when_file_missing() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
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
            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/video",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_REEL_VIDEO_NOT_FOUND"


def test_images_endpoint_lists_images_with_local_flag() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            local_image = workspace_dir / "images" / "img-1.jpg"
            local_image.parent.mkdir(parents=True, exist_ok=True)
            local_image.write_bytes(b"img-bytes")
            seed_property_image(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                position=0,
                image_url="https://x/img-0.jpg",
                local_path=None,
            )
            seed_property_image(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                position=1,
                image_url="https://x/img-1.jpg",
                local_path="images/img-1.jpg",
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/images",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["count"] == 2
            assert payload["items"][0]["has_local_file"] is False
            assert payload["items"][1]["has_local_file"] is True


def test_image_file_endpoint_streams_local_image() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            local_image = workspace_dir / "images" / "img-1.jpg"
            local_image.parent.mkdir(parents=True, exist_ok=True)
            local_image.write_bytes(b"jpeg-bytes")
            seed_property_image(
                database.url,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                position=1,
                image_url="https://x/img.jpg",
                local_path="images/img-1.jpg",
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/images/1/file",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            assert response.content == b"jpeg-bytes"
            assert response.headers["content-type"].startswith("image/jpeg")


def test_manifest_endpoint_returns_json_when_file_exists() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            manifest_path = workspace_dir / "rendered" / "manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps({"scenes": [{"index": 0}]}), encoding="utf-8"
            )
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
                revision_metadata_path="rendered/manifest.json",
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/manifest",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            assert response.json()["manifest"] == {"scenes": [{"index": 0}]}


def test_manifest_endpoint_returns_404_when_file_missing() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
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
            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/manifest",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_REEL_MANIFEST_NOT_FOUND"


def test_approve_returns_publish_enqueued_false_without_prereqs() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
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
                f"{seeded.external_source_id}/42/approve",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["status"] == "approved"
            assert payload["publish_enqueued"] is False
            assert payload["reason"] == "PUBLISH_PREREQUISITES_MISSING"

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.reels is not None
                state = uow.reels.states.get(
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                )
            assert state is not None
            assert state.workflow_state == "approved"
            assert state.publish_status == "pending_publish"


def test_approve_enqueues_job_with_full_prereqs() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "tok-1"},
            )
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
                f"{seeded.external_source_id}/42/approve",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["publish_enqueued"] is True
            assert payload["event_id"]
            assert payload["job_id"]

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.delivery is not None
                job = uow.delivery.jobs.get_job(payload["job_id"])
            assert job is not None
            assert job.kind == "reel_publish"
            assert job.external_source_id == seeded.external_source_id
            assert job.property_id == 42
            bundle = json.loads(job.provider_secret_bundle)
            assert bundle == {"access_token": "tok-1", "provider": "gohighlevel"}


def test_approve_replays_existing_queued_job_for_same_property() -> None:
    """A queued job for the same property is treated as the active job.

    Before the idempotency change this scenario superseded the queued
    row and enqueued a fresh one. Now ``find_active_job_for_property``
    treats ``queued`` as still-active (the worker just hasn't claimed
    it yet), so a second Approve replays the same ``job_id`` /
    ``event_id`` with ``idempotent_replay=true`` and the queued row is
    left untouched.
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "tok-1"},
            )
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
            assert response.status_code == 200
            payload = response.json()
            assert payload["publish_enqueued"] is True
            assert payload.get("idempotent_replay") is True
            assert payload["job_id"] == old_job_id
            assert payload["event_id"] == old_event_id

            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    old = connection.execute(
                        text(
                            "SELECT status, superseded_by_job_id FROM jobs "
                            "WHERE job_id = :job_id"
                        ),
                        {"job_id": old_job_id},
                    ).first()
                    old_event = connection.execute(
                        text(
                            "SELECT status FROM webhook_events "
                            "WHERE event_id = :event_id"
                        ),
                        {"event_id": old_event_id},
                    ).first()
                    job_count = connection.execute(
                        text(
                            "SELECT COUNT(*) AS n FROM jobs "
                            "WHERE external_source_id = :site "
                            "AND property_id = :pid"
                        ),
                        {
                            "site": seeded.external_source_id,
                            "pid": 42,
                        },
                    ).first()
            finally:
                engine.dispose()
            assert old is not None
            # Pre-existing queued job stays exactly as it was.
            assert old.status == "queued"
            assert not old.superseded_by_job_id  # NULL or empty string
            assert old_event is not None
            assert old_event.status == "queued"
            assert job_count is not None
            assert int(job_count.n) == 1


def test_approve_is_idempotent_when_active_job_already_exists() -> None:
    """A double-click on Approve must not enqueue a second job.

    Scenario:
    1. First POST /approve enqueues a fresh `reel_publish` job in
       ``queued`` state.
    2. We flip that job to ``processing`` to simulate the worker picking
       it up between the two clicks.
    3. Second POST /approve sees the active job and replays the same
       ``job_id``/``event_id`` with ``idempotent_replay=true`` — no
       duplicate row in the queue.
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "tok-1"},
            )
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

            first = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/approve",
                headers=ADMIN_BEARER,
            )
            assert first.status_code == 200
            first_payload = first.json()
            assert first_payload["publish_enqueued"] is True
            assert first_payload.get("idempotent_replay") is None
            first_job_id = first_payload["job_id"]
            first_event_id = first_payload["event_id"]

            # Simulate the worker claiming the job: status flips from
            # ``queued`` to ``processing``.
            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "UPDATE jobs SET status = 'processing' "
                            "WHERE job_id = :job_id"
                        ),
                        {"job_id": first_job_id},
                    )
            finally:
                engine.dispose()

            second = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/approve",
                headers=ADMIN_BEARER,
            )
            assert second.status_code == 200
            second_payload = second.json()
            assert second_payload["publish_enqueued"] is True
            assert second_payload.get("idempotent_replay") is True
            assert second_payload["job_id"] == first_job_id
            assert second_payload["event_id"] == first_event_id

            # Confirm only one job exists for this property.
            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    rows = connection.execute(
                        text(
                            "SELECT job_id, status FROM jobs "
                            "WHERE external_source_id = :site "
                            "AND property_id = :pid"
                        ),
                        {
                            "site": seeded.external_source_id,
                            "pid": 42,
                        },
                    ).all()
            finally:
                engine.dispose()
            assert len(rows) == 1
            assert rows[0].job_id == first_job_id
            assert rows[0].status == "processing"


def test_approve_returns_404_for_missing_agency() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.post(
                "/v1/admin/agencies/missing/reels/site/1/approve",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_AGENCY_NOT_FOUND"


def test_approve_returns_404_when_reel_missing() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/99/approve",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_REEL_NOT_FOUND"


def test_reject_marks_workflow_and_publish_as_rejected() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
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
                f"{seeded.external_source_id}/42/reject",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["status"] == "rejected"
            assert payload["reel"]["workflow_state"] == "rejected"

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.reels is not None
                state = uow.reels.states.get(
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                )
            assert state is not None
            assert state.workflow_state == "rejected"
            assert state.publish_status == "rejected"


def test_reject_returns_404_when_reel_missing() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/99/reject",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_REEL_NOT_FOUND"


# ---------------------------------------------------------------------------
# Feature 11 — scheduled_at in approve response and persisted publish_context
# ---------------------------------------------------------------------------


def test_approve_includes_scheduled_at_in_response_body() -> None:
    """The fresh approve path must echo the computed slot back to the front.

    The exact slot value is non-deterministic (it depends on ``datetime.now``)
    so we only assert structural invariants: the key exists, and the
    persisted ``jobs.publish_context_json`` row carries the same string
    (or ``null``) as the response.
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "tok-1"},
            )
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            seed_automation_rules(
                database.url,
                agency_id=seeded.agency_id,
                publish_window_start="09:00",
                publish_window_end="17:00",
                publish_days=("mon", "tue", "wed", "thu", "fri"),
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/approve",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["publish_enqueued"] is True
            # The key must be present (frontend contract). The value
            # is ``str | None`` depending on the current weekday/time.
            assert "scheduled_at" in payload
            response_scheduled_at = payload["scheduled_at"]
            assert response_scheduled_at is None or isinstance(
                response_scheduled_at, str
            )

            # Persisted publish_context_json carries the same value as
            # the response so the worker honours the same slot.
            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    row = connection.execute(
                        text(
                            "SELECT publish_context_json FROM jobs "
                            "WHERE job_id = :job_id"
                        ),
                        {"job_id": payload["job_id"]},
                    ).first()
            finally:
                engine.dispose()
            assert row is not None
            persisted = row.publish_context_json
            assert isinstance(persisted, dict)
            assert persisted.get("scheduled_at") == response_scheduled_at


def test_approve_replay_recovers_scheduled_at_from_active_job() -> None:
    """An idempotent replay must surface the original ``scheduled_at``.

    Seeds a queued job whose ``publish_context_json`` carries a known
    ``scheduled_at``; a follow-up approve must return that same value
    rather than recomputing.
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "tok-1"},
            )
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            persisted_slot = "2026-05-18T09:00:00+00:00"
            old_event_id, old_job_id = insert_legacy_queued_job(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                property_id=42,
                publish_context={"scheduled_at": persisted_slot},
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/approve",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["publish_enqueued"] is True
            assert payload.get("idempotent_replay") is True
            assert payload["job_id"] == old_job_id
            assert payload["event_id"] == old_event_id
            assert payload["scheduled_at"] == persisted_slot


def test_approve_replay_legacy_job_surfaces_null_scheduled_at() -> None:
    """A pre-feature-11 replay (empty publish_context_json) must still respond cleanly."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "tok-1"},
            )
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
                publish_context=None,
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                f"{seeded.external_source_id}/42/approve",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload.get("idempotent_replay") is True
            assert payload["job_id"] == old_job_id
            assert payload["event_id"] == old_event_id
            assert payload["scheduled_at"] is None


# ---------------------------------------------------------------------------
# Feature 14 — agency.timezone + skip_weekends + quiet_hours_enabled cross
# timezone boundary
# ---------------------------------------------------------------------------


def test_approve_skip_weekends_quiet_hours_dublin_lands_on_monday_utc() -> None:
    """A Saturday approve from a Dublin agency lands on Monday at 09:00 local.

    Seeds:
      * Agency with ``timezone='Europe/Dublin'`` (via the default
        ``seed_tenant``).
      * Automation rules with ``skip_weekends=True`` and
        ``quiet_hours_enabled=True``; window 09:00–18:00 Mon–Fri.

    Patches ``datetime.now`` inside ``regenerate_reel`` so the wall-clock
    is Saturday 2026-05-16 10:00 Dublin BST (= 09:00 UTC).

    Expected ``scheduled_at`` in the response and persisted in
    ``jobs.publish_context_json``: Monday 2026-05-18 09:00 Dublin
    converted to UTC (08:00 UTC during BST).
    """
    fixed_now_utc = datetime(2026, 5, 16, 9, 0, tzinfo=timezone.utc)
    expected_local = datetime(
        2026, 5, 18, 9, 0, tzinfo=ZoneInfo("Europe/Dublin")
    )
    expected_iso = expected_local.astimezone(timezone.utc).isoformat()

    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "tok-1"},
            )
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            seed_automation_rules(
                database.url,
                agency_id=seeded.agency_id,
                publish_window_start="09:00",
                publish_window_end="18:00",
                publish_days=("mon", "tue", "wed", "thu", "fri"),
                quiet_hours_enabled=True,
                skip_weekends=True,
            )
            client = build_admin_reels_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            with patch(
                "modules.reels.application.use_cases.regenerate_reel.datetime"
            ) as datetime_mock:
                datetime_mock.now.return_value = fixed_now_utc
                response = client.post(
                    f"/v1/admin/agencies/{seeded.agency_id}/reels/"
                    f"{seeded.external_source_id}/42/approve",
                    headers=ADMIN_BEARER,
                )
            assert response.status_code == 200
            payload = response.json()
            assert payload["publish_enqueued"] is True
            assert payload["scheduled_at"] == expected_iso

            # Persisted publish_context_json mirrors the response.
            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    row = connection.execute(
                        text(
                            "SELECT publish_context_json FROM jobs "
                            "WHERE job_id = :job_id"
                        ),
                        {"job_id": payload["job_id"]},
                    ).first()
            finally:
                engine.dispose()
            assert row is not None
            persisted = row.publish_context_json
            assert isinstance(persisted, dict)
            assert persisted.get("scheduled_at") == expected_iso
