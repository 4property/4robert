"""Integration tests for the configuration music router (CRUD per track)."""

from __future__ import annotations

from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.integration.configuration._client import (
    ADMIN_BEARER,
    build_configuration_client,
)
from tests.support.postgres import (
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


def test_music_post_creates_track_and_get_lists_it() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            create = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/music",
                json={
                    "display_name": "Sunset Drive",
                    "object_key": "agencies/ckp/sunset.mp3",
                    "duration_seconds": 28,
                    "is_default": True,
                },
                headers=ADMIN_BEARER,
            )
            assert create.status_code == 201, create.text
            track = create.json()["music_track"]
            assert track["display_name"] == "Sunset Drive"
            assert track["is_default"] is True

            listing = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/music",
                headers=ADMIN_BEARER,
            )
            assert listing.status_code == 200
            payload = listing.json()
            assert set(payload) == {"agency_id", "items", "count"}
            assert payload["agency_id"] == seeded.agency_id
            assert payload["count"] == 1
            listed_track = payload["items"][0]
            assert set(listed_track) == {
                "music_id",
                "agency_id",
                "display_name",
                "object_key",
                "duration_seconds",
                "is_default",
                "created_at",
            }
            assert listed_track["music_id"] == track["music_id"]
            assert listed_track["agency_id"] == seeded.agency_id
            assert listed_track["display_name"] == "Sunset Drive"
            assert listed_track["object_key"] == "agencies/ckp/sunset.mp3"
            assert listed_track["duration_seconds"] == 28
            assert listed_track["is_default"] is True
            assert listed_track["created_at"]


def test_music_inspect_reconfigure_and_delete_round_trip() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            create = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/music",
                json={
                    "display_name": "Old Track",
                    "object_key": "agencies/ckp/old.mp3",
                    "duration_seconds": 10,
                },
                headers=ADMIN_BEARER,
            )
            music_id = create.json()["music_track"]["music_id"]

            inspect = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/music/{music_id}",
                headers=ADMIN_BEARER,
            )
            assert inspect.status_code == 200
            assert inspect.json()["music_track"]["display_name"] == "Old Track"

            reconfigure = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/music/{music_id}",
                json={"display_name": "New Track", "duration_seconds": 20},
                headers=ADMIN_BEARER,
            )
            assert reconfigure.status_code == 200
            assert reconfigure.json()["music_track"]["display_name"] == "New Track"
            assert reconfigure.json()["music_track"]["duration_seconds"] == 20

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                saved = uow.configuration.music.get(music_id=music_id)
            assert saved is not None
            assert saved.display_name == "New Track"

            decommission = client.delete(
                f"/v1/admin/agencies/{seeded.agency_id}/music/{music_id}",
                headers=ADMIN_BEARER,
            )
            assert decommission.status_code == 200

            after = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/music/{music_id}",
                headers=ADMIN_BEARER,
            )
            assert after.status_code == 404
            assert after.json()["code"] == "MUSIC_TRACK_NOT_FOUND"


def test_music_inspect_returns_404_for_other_agency_track() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            agency_a = seed_tenant(database.url, site_id="ckp.ie")
            agency_b = seed_tenant(database.url, site_id="other.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            create = client.post(
                f"/v1/admin/agencies/{agency_a.agency_id}/music",
                json={
                    "display_name": "A",
                    "object_key": "x.mp3",
                    "duration_seconds": 5,
                },
                headers=ADMIN_BEARER,
            )
            music_id = create.json()["music_track"]["music_id"]

            response = client.get(
                f"/v1/admin/agencies/{agency_b.agency_id}/music/{music_id}",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 404
            assert response.json()["code"] == "MUSIC_TRACK_NOT_FOUND"


def test_music_post_returns_404_for_unknown_agency() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )
            response = client.post(
                "/v1/admin/agencies/missing/music",
                json={
                    "display_name": "x",
                    "object_key": "y",
                    "duration_seconds": 5,
                },
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 404
            assert response.json()["code"] == "ADMIN_AGENCY_NOT_FOUND"
