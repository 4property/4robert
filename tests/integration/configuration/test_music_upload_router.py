"""Integration tests for the agency music upload router (feature 22).

Covers ``POST /v1/admin/agencies/{id}/music/upload`` (multipart) and the
companion ``GET .../music/{music_id}/file/{filename}`` stream. The MP3
fixture in ``_fixtures/tiny.mp3`` is a 1-second silent MP3 (~4.4 KiB)
generated via ``ffmpeg -f lavfi anullsrc`` — small enough to live in
git, real enough for ``ffprobe`` to extract a duration.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from settings import DATABASE_URL
from shared.storage.site_layout import safe_site_dirname
from tests.integration.configuration._client import (
    ADMIN_BEARER,
    build_configuration_client,
)
from tests.support.postgres import (
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)

_FIXTURE_PATH = Path(__file__).parent / "_fixtures" / "tiny.mp3"


def _load_fixture() -> bytes:
    if not _FIXTURE_PATH.exists():
        pytest.skip(f"Missing fixture {_FIXTURE_PATH}")
    return _FIXTURE_PATH.read_bytes()


def _multipart(
    *,
    file_bytes: bytes,
    filename: str = "track.mp3",
    content_type: str = "audio/mpeg",
    display_name: str | None = "Sunset Drive",
    is_default: str | None = "false",
) -> tuple[dict, dict]:
    """Build the kwargs that ``TestClient.post`` accepts for multipart.

    Returns ``(files, data)``. ``data`` keys with ``None`` value are
    skipped so we can test the "missing display_name" path.
    """
    files = {"file": (filename, io.BytesIO(file_bytes), content_type)}
    data: dict[str, str] = {}
    if display_name is not None:
        data["display_name"] = display_name
    if is_default is not None:
        data["is_default"] = is_default
    return files, data


def test_music_upload_happy_path_returns_201_and_persists_blob() -> None:
    fixture = _load_fixture()
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            files, data = _multipart(
                file_bytes=fixture,
                filename="sunset drive!.mp3",
                display_name="Sunset Drive",
                is_default="true",
            )
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/music/upload",
                files=files,
                data=data,
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 201, response.text
            payload = response.json()
            assert payload["status"] == "created"
            assert payload["agency_id"] == seeded.agency_id

            track = payload["music_track"]
            assert set(track) == {
                "music_id",
                "agency_id",
                "display_name",
                "object_key",
                "duration_seconds",
                "is_default",
                "created_at",
            }
            assert track["display_name"] == "Sunset Drive"
            assert track["is_default"] is True
            safe_agency = safe_site_dirname(seeded.agency_id)
            assert track["object_key"].startswith(
                f"agencies/{safe_agency}/music/"
            )
            assert track["object_key"].endswith(".mp3")
            assert track["duration_seconds"] >= 1

            persisted_dir = (
                workspace_dir
                / "generated_media"
                / "_agency_music"
                / safe_agency
            )
            assert persisted_dir.exists()
            files_on_disk = list(persisted_dir.iterdir())
            assert len(files_on_disk) == 1
            assert files_on_disk[0].read_bytes() == fixture

            filename = Path(track["object_key"]).name
            download = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}"
                f"/music/{track['music_id']}/file/{filename}",
                headers=ADMIN_BEARER,
            )
            assert download.status_code == 200, download.text
            assert download.content == fixture
            assert download.headers["content-type"].startswith("audio/mpeg")


def test_music_upload_rejects_unsupported_mime_with_400() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            files, data = _multipart(
                file_bytes=b"not an audio file",
                filename="track.txt",
                content_type="text/plain",
            )
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/music/upload",
                files=files,
                data=data,
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 400, response.text
            assert response.json()["code"] == "MUSIC_TRACK_AUDIO_INVALID"


def test_music_upload_rejects_payload_over_20_mb() -> None:
    fixture_head = b"ID3\x03\x00\x00\x00"
    oversized = fixture_head + b"0" * (20 * 1024 * 1024 + 16)
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            files, data = _multipart(file_bytes=oversized)
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/music/upload",
                files=files,
                data=data,
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 413, response.text
            assert response.json()["code"] == "MUSIC_TRACK_UPLOAD_TOO_LARGE"


def test_music_upload_requires_display_name_with_422() -> None:
    fixture = _load_fixture()
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            files, data = _multipart(file_bytes=fixture, display_name=None)
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/music/upload",
                files=files,
                data=data,
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 422, response.text
            assert response.json()["code"] in {
                "MUSIC_TRACK_DISPLAY_NAME_REQUIRED",
                "MUSIC_TRACK_UPLOAD_MALFORMED",
            }


def test_music_upload_rejects_blank_display_name_with_422() -> None:
    fixture = _load_fixture()
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            files, data = _multipart(file_bytes=fixture, display_name="   ")
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/music/upload",
                files=files,
                data=data,
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 422, response.text
            assert response.json()["code"] == "MUSIC_TRACK_DISPLAY_NAME_REQUIRED"


def test_music_upload_rejects_magic_byte_mismatch_with_400() -> None:
    """Bytes that don't look like MP3 even though the MIME claims audio/mpeg."""
    bad_bytes = b"\x00\x00\x00\x00" + b"random data" * 8
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            files, data = _multipart(
                file_bytes=bad_bytes,
                content_type="audio/mpeg",
            )
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/music/upload",
                files=files,
                data=data,
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 400, response.text
            assert response.json()["code"] == "MUSIC_TRACK_AUDIO_INVALID"


def test_music_upload_rejects_ffprobe_failure_with_400() -> None:
    """Magic bytes look like MP3, but the body is too short for ffprobe."""
    truncated = b"ID3\x03\x00\x00\x00\x00\x00\x00" + b"garbage" * 4
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            files, data = _multipart(file_bytes=truncated)
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/music/upload",
                files=files,
                data=data,
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 400, response.text
            body = response.json()
            assert body["code"] == "MUSIC_TRACK_AUDIO_INVALID"
            # Cleanup must remove the orphan blob.
            safe_agency = safe_site_dirname(seeded.agency_id)
            persisted_dir = (
                workspace_dir
                / "generated_media"
                / "_agency_music"
                / safe_agency
            )
            if persisted_dir.exists():
                assert list(persisted_dir.iterdir()) == []


def test_music_upload_returns_404_for_unknown_agency() -> None:
    fixture = _load_fixture()
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            files, data = _multipart(file_bytes=fixture)
            response = client.post(
                "/v1/admin/agencies/does-not-exist/music/upload",
                files=files,
                data=data,
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 404, response.text
            assert response.json()["code"] == "ADMIN_AGENCY_NOT_FOUND"


def test_music_upload_requires_auth() -> None:
    fixture = _load_fixture()
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            files, data = _multipart(file_bytes=fixture)
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/music/upload",
                files=files,
                data=data,
            )
            assert response.status_code in {401, 403}, response.text


def test_music_file_stream_404_for_unknown_track() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}"
                f"/music/missing-id/file/track.mp3",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 404, response.text
            assert response.json()["code"] == "MUSIC_TRACK_NOT_FOUND"


def test_music_file_stream_cross_agency_returns_404() -> None:
    fixture = _load_fixture()
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            agency_a = seed_tenant(database.url, site_id="ckp.ie")
            agency_b = seed_tenant(database.url, site_id="other.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            files, data = _multipart(file_bytes=fixture)
            create = client.post(
                f"/v1/admin/agencies/{agency_a.agency_id}/music/upload",
                files=files,
                data=data,
                headers=ADMIN_BEARER,
            )
            assert create.status_code == 201
            track = create.json()["music_track"]
            filename = Path(track["object_key"]).name

            cross = client.get(
                f"/v1/admin/agencies/{agency_b.agency_id}"
                f"/music/{track['music_id']}/file/{filename}",
                headers=ADMIN_BEARER,
            )
            assert cross.status_code == 404, cross.text
            assert cross.json()["code"] == "MUSIC_TRACK_NOT_FOUND"


def test_music_file_stream_rejects_filename_mismatch_with_404() -> None:
    fixture = _load_fixture()
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            files, data = _multipart(file_bytes=fixture)
            create = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/music/upload",
                files=files,
                data=data,
                headers=ADMIN_BEARER,
            )
            assert create.status_code == 201
            track = create.json()["music_track"]

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}"
                f"/music/{track['music_id']}/file/spoofed.mp3",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 404, response.text
            assert response.json()["code"] == "MUSIC_TRACK_FILE_NOT_FOUND"
