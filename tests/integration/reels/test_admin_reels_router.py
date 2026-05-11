"""Integration tests for the admin reels router."""

from __future__ import annotations

import json

from sqlalchemy import create_engine, text

from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.integration.reels._client import (
    ADMIN_BEARER,
    build_admin_reels_client,
    insert_legacy_queued_job,
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
            assert response.json() == {"items": [], "count": 0}


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


def test_approve_supersedes_previously_queued_job_for_same_property() -> None:
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
            finally:
                engine.dispose()
            assert old is not None
            assert old.status == "superseded"
            assert old.superseded_by_job_id == payload["job_id"]
            assert old_event is not None
            assert old_event.status == "superseded"


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
