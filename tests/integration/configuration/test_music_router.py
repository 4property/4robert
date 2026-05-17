"""Integration tests for the configuration music router (CRUD per track).

Feature 22 retired the direct metadata POST in favour of the multipart
``POST /v1/admin/agencies/{id}/music/upload`` (see
``test_music_upload_router.py``). The tests here seed rows directly via
``DatabaseUnitOfWork`` so we still cover the GET / PUT / DELETE paths
without depending on ffprobe + multipart parsing.
"""

from __future__ import annotations

from pathlib import Path

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


def _seed_music_track(
    *,
    database_url: str,
    workspace_dir: Path,
    agency_id: str,
    music_id: str = "track-1",
    display_name: str = "Sunset Drive",
    object_key: str = "agencies/ckp/music/sunset.mp3",
    duration_seconds: int = 28,
    is_default: bool = False,
) -> None:
    with DatabaseUnitOfWork(database_url, workspace_dir) as uow:
        assert uow.configuration is not None
        uow.configuration.music.add_track(
            music_id=music_id,
            agency_id=agency_id,
            display_name=display_name,
            object_key=object_key,
            duration_seconds=duration_seconds,
            is_default=is_default,
        )


def test_music_direct_post_is_retired_with_405() -> None:
    """Feature 22 retired the direct metadata POST."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/music",
                json={
                    "display_name": "Sunset Drive",
                    "object_key": "agencies/ckp/sunset.mp3",
                    "duration_seconds": 28,
                    "is_default": True,
                },
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 405, response.text
            payload = response.json()
            assert payload["code"] == "METHOD_NOT_ALLOWED"
            assert "music/upload" in payload["details"]["use_endpoint"]


def test_music_list_returns_seeded_track() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url, site_id="ckp.ie", seed_default_music=False
            )
            _seed_music_track(
                database_url=database.url,
                workspace_dir=workspace_dir,
                agency_id=seeded.agency_id,
                display_name="Sunset Drive",
                object_key="agencies/ckp/music/sunset.mp3",
                duration_seconds=28,
                is_default=True,
            )
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            listing = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/music",
                headers=ADMIN_BEARER,
            )
            assert listing.status_code == 200, listing.text
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
            assert listed_track["agency_id"] == seeded.agency_id
            assert listed_track["display_name"] == "Sunset Drive"
            assert listed_track["object_key"] == "agencies/ckp/music/sunset.mp3"
            assert listed_track["duration_seconds"] == 28
            assert listed_track["is_default"] is True
            assert listed_track["created_at"]


def test_music_inspect_reconfigure_and_delete_round_trip() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_music_track(
                database_url=database.url,
                workspace_dir=workspace_dir,
                agency_id=seeded.agency_id,
                music_id="track-1",
                display_name="Old Track",
                object_key="agencies/ckp/music/old.mp3",
                duration_seconds=10,
            )
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            inspect = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/music/track-1",
                headers=ADMIN_BEARER,
            )
            assert inspect.status_code == 200, inspect.text
            assert inspect.json()["music_track"]["display_name"] == "Old Track"

            reconfigure = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/music/track-1",
                json={"display_name": "New Track", "is_default": True},
                headers=ADMIN_BEARER,
            )
            assert reconfigure.status_code == 200, reconfigure.text
            updated = reconfigure.json()["music_track"]
            assert updated["display_name"] == "New Track"
            assert updated["is_default"] is True
            # object_key and duration_seconds must NOT be touched by PUT
            assert updated["object_key"] == "agencies/ckp/music/old.mp3"
            assert updated["duration_seconds"] == 10

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                assert uow.configuration is not None
                saved = uow.configuration.music.get(music_id="track-1")
            assert saved is not None
            assert saved.display_name == "New Track"
            assert saved.is_default is True

            decommission = client.delete(
                f"/v1/admin/agencies/{seeded.agency_id}/music/track-1",
                headers=ADMIN_BEARER,
            )
            assert decommission.status_code == 200, decommission.text

            after = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/music/track-1",
                headers=ADMIN_BEARER,
            )
            assert after.status_code == 404
            assert after.json()["code"] == "MUSIC_TRACK_NOT_FOUND"


def test_music_put_rejects_object_key_with_422() -> None:
    """Feature 22: PUT must reject any attempt to rewrite ``object_key``.

    ``MusicTrackPatchPayload`` has ``extra='forbid'`` so unknown fields
    trigger a 422 from FastAPI's body validator before our handler runs.
    """
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_music_track(
                database_url=database.url,
                workspace_dir=workspace_dir,
                agency_id=seeded.agency_id,
                music_id="track-1",
            )
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/music/track-1",
                json={"object_key": "agencies/ckp/music/spoofed.mp3"},
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 422, response.text


def test_music_put_rejects_duration_seconds_with_422() -> None:
    """Feature 22: PUT must reject any attempt to rewrite ``duration_seconds``."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            _seed_music_track(
                database_url=database.url,
                workspace_dir=workspace_dir,
                agency_id=seeded.agency_id,
                music_id="track-1",
            )
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.put(
                f"/v1/admin/agencies/{seeded.agency_id}/music/track-1",
                json={"duration_seconds": 999},
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 422, response.text


def test_music_inspect_returns_404_for_other_agency_track() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            agency_a = seed_tenant(database.url, site_id="ckp.ie")
            agency_b = seed_tenant(database.url, site_id="other.ie")
            _seed_music_track(
                database_url=database.url,
                workspace_dir=workspace_dir,
                agency_id=agency_a.agency_id,
                music_id="track-a",
            )
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{agency_b.agency_id}/music/track-a",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 404
            assert response.json()["code"] == "MUSIC_TRACK_NOT_FOUND"
