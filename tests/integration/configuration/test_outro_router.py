"""Integration tests for the agency outro router (feature 33).

Covers ``POST .../outro/upload`` (multipart), ``GET .../outro/file``
(byte stream), ``DELETE .../outro`` and the impact on ``GET .../defaults``.
The MP4 fixtures in ``_fixtures/`` are tiny (5s @ 320x240, ~7 KiB) but
real enough for ffprobe to extract a duration so the use case round-trip
matches production.

Size (50 MB) and duration ([1, 10] s) restrictions were removed: the
SaaS admin is trusted to upload outros of any length and weight, so
the only HTTP-level validations left are MIME and "body not empty".
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.admin_auth import AdminAccessPolicy
from apps.api.error_handlers import register_error_handlers
from modules.configuration.application.use_cases.upload_outro_video import (
    UploadOutroVideoUseCase,
)
from modules.configuration.transport.http.outro_router import create_outro_router
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
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

_FIXTURE_DIR = Path(__file__).parent / "_fixtures"
_OUTRO_OK_PATH = _FIXTURE_DIR / "tiny_outro_5s.mp4"
_OUTRO_LONG_PATH = _FIXTURE_DIR / "long_outro_15s.mp4"


def _load_fixture(path: Path) -> bytes:
    if not path.exists():
        pytest.skip(f"Missing fixture {path}")
    return path.read_bytes()


def _multipart(
    *,
    file_bytes: bytes,
    filename: str = "outro.mp4",
    content_type: str = "video/mp4",
) -> dict:
    return {"file": (filename, io.BytesIO(file_bytes), content_type)}


def test_outro_upload_happy_path_returns_metadata_and_persists_blob() -> None:
    fixture = _load_fixture(_OUTRO_OK_PATH)
    sha = hashlib.sha1(fixture).hexdigest()[:16]
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            files = _multipart(file_bytes=fixture)
            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/outro/upload",
                files=files,
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert set(payload) == {
                "outro_object_key",
                "outro_duration_seconds",
                "outro_source",
            }
            assert payload["outro_source"] == "uploaded"
            safe_agency = safe_site_dirname(seeded.agency_id)
            expected_filename = f"outro-{sha}.mp4"
            expected_object_key = (
                f"agencies/{safe_agency}/outro/{expected_filename}"
            )
            assert payload["outro_object_key"] == expected_object_key
            # The fixture is 5 seconds; ffprobe rounds to nearest int.
            assert payload["outro_duration_seconds"] == 5

            persisted_path = (
                workspace_dir
                / "generated_media"
                / "_agency_outro"
                / safe_agency
                / expected_filename
            )
            assert persisted_path.exists()
            assert persisted_path.read_bytes() == fixture

            # GET /defaults must surface the outro_* fields without
            # requiring a second roundtrip — the leader's mandatory
            # contract.
            defaults_response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/defaults",
                headers=ADMIN_BEARER,
            )
            assert defaults_response.status_code == 200, defaults_response.text
            defaults_body = defaults_response.json()["defaults"]
            assert defaults_body["outro_object_key"] == expected_object_key
            assert defaults_body["outro_duration_seconds"] == 5
            assert defaults_body["outro_source"] == "uploaded"
            assert defaults_body["outro_enabled"] is False


def test_outro_get_file_returns_bytes_and_correct_content_type() -> None:
    fixture = _load_fixture(_OUTRO_OK_PATH)
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            upload_response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/outro/upload",
                files=_multipart(file_bytes=fixture),
                headers=ADMIN_BEARER,
            )
            assert upload_response.status_code == 200, upload_response.text

            file_response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/outro/file",
                headers=ADMIN_BEARER,
            )
            assert file_response.status_code == 200, file_response.text
            assert file_response.content == fixture
            assert (
                hashlib.sha1(file_response.content).hexdigest()
                == hashlib.sha1(fixture).hexdigest()
            )
            assert file_response.headers["content-type"].startswith("video/mp4")
            assert file_response.headers["content-disposition"] == "inline"


def test_outro_delete_clears_metadata_and_removes_blob() -> None:
    fixture = _load_fixture(_OUTRO_OK_PATH)
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            upload_response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/outro/upload",
                files=_multipart(file_bytes=fixture),
                headers=ADMIN_BEARER,
            )
            assert upload_response.status_code == 200, upload_response.text
            object_key = upload_response.json()["outro_object_key"]

            delete_response = client.delete(
                f"/v1/admin/agencies/{seeded.agency_id}/outro",
                headers=ADMIN_BEARER,
            )
            assert delete_response.status_code == 200, delete_response.text
            body = delete_response.json()
            assert body["outro_source"] == "none"
            assert body["outro_object_key"] is None
            assert body["outro_duration_seconds"] is None

            # The on-disk blob is gone.
            safe_agency = safe_site_dirname(seeded.agency_id)
            expected_filename = Path(object_key).name
            persisted_path = (
                workspace_dir
                / "generated_media"
                / "_agency_outro"
                / safe_agency
                / expected_filename
            )
            assert not persisted_path.exists()

            # And so are the outro_* fields on /defaults.
            defaults_response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/defaults",
                headers=ADMIN_BEARER,
            )
            assert defaults_response.status_code == 200
            defaults_body = defaults_response.json()["defaults"]
            assert defaults_body["outro_source"] == "none"
            assert defaults_body["outro_object_key"] is None
            assert defaults_body["outro_duration_seconds"] is None


def test_outro_upload_rejects_unsupported_mime_with_422() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/outro/upload",
                files=_multipart(
                    file_bytes=b"not a video file",
                    filename="outro.txt",
                    content_type="text/plain",
                ),
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 422, response.text
            assert response.json()["code"] == "OUTRO_INVALID_MIME"


def test_outro_upload_accepts_duration_above_10_seconds() -> None:
    """The [1, 10] s duration window was removed: 15s outros are accepted."""
    fixture = _load_fixture(_OUTRO_LONG_PATH)
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/outro/upload",
                files=_multipart(file_bytes=fixture),
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["outro_source"] == "uploaded"
            # The fixture is 15 seconds; ffprobe rounds to nearest int.
            assert payload["outro_duration_seconds"] == 15

            # The blob is persisted (no orphan cleanup since no rejection).
            safe_agency = safe_site_dirname(seeded.agency_id)
            persisted_dir = (
                workspace_dir
                / "generated_media"
                / "_agency_outro"
                / safe_agency
            )
            assert persisted_dir.exists()
            assert len(list(persisted_dir.iterdir())) == 1


def test_outro_upload_accepts_payload_over_50mb() -> None:
    """The 50 MB cap was removed: a >50MB upload must succeed (200).

    We inject a stubbed ``ffprobe_runner`` so the test doesn't depend
    on ffprobe being able to parse the synthetic bytes — the contract
    we care about here is that the size guard no longer fires.
    """
    oversized = b"\x00\x00\x00\x20ftypisom" + b"0" * (50 * 1024 * 1024 + 16)
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")

            policy = AdminAccessPolicy(
                enabled=True,
                base_path="/v1/admin",
                bearer_token="test-admin-token",
                disable_auth_for_testing=False,
            )
            factory = lambda: DatabaseUnitOfWork(  # noqa: E731
                database.url, workspace_dir
            )
            use_case = UploadOutroVideoUseCase(
                workspace_dir=workspace_dir,
                ffprobe_runner=lambda _path: 60,  # 60s outro, well over 10s
            )
            app = FastAPI()
            app.include_router(
                create_outro_router(
                    unit_of_work_factory=factory,
                    admin_access_policy=policy,
                    workspace_dir=workspace_dir,
                    upload_outro_video=use_case,
                )
            )
            register_error_handlers(app)
            client = TestClient(app)

            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/outro/upload",
                files=_multipart(file_bytes=oversized),
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["outro_source"] == "uploaded"
            assert payload["outro_duration_seconds"] == 60
            assert payload["outro_object_key"]


def test_outro_upload_replaces_previous_blob() -> None:
    fixture = _load_fixture(_OUTRO_OK_PATH)
    second_payload = fixture + b"\x00"  # different sha — same content_type
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            first = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/outro/upload",
                files=_multipart(file_bytes=fixture),
                headers=ADMIN_BEARER,
            )
            assert first.status_code == 200, first.text
            first_key = first.json()["outro_object_key"]

            second = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/outro/upload",
                files=_multipart(file_bytes=second_payload),
                headers=ADMIN_BEARER,
            )
            assert second.status_code == 200, second.text
            second_key = second.json()["outro_object_key"]
            assert first_key != second_key

            safe_agency = safe_site_dirname(seeded.agency_id)
            persisted_dir = (
                workspace_dir
                / "generated_media"
                / "_agency_outro"
                / safe_agency
            )
            files_on_disk = sorted(p.name for p in persisted_dir.iterdir())
            # The previous blob is gone; only the new one remains.
            assert files_on_disk == [Path(second_key).name]


def test_outro_endpoints_require_auth() -> None:
    fixture = _load_fixture(_OUTRO_OK_PATH)
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/outro/upload",
                files=_multipart(file_bytes=fixture),
            )
            assert response.status_code in {401, 403}, response.text

            response = client.delete(
                f"/v1/admin/agencies/{seeded.agency_id}/outro",
            )
            assert response.status_code in {401, 403}, response.text


def test_outro_file_returns_404_when_nothing_uploaded() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/outro/file",
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 404, response.text
            assert response.json()["code"] == "OUTRO_FILE_NOT_FOUND"


def test_outro_upload_returns_404_for_unknown_agency() -> None:
    fixture = _load_fixture(_OUTRO_OK_PATH)
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.post(
                "/v1/admin/agencies/does-not-exist/outro/upload",
                files=_multipart(file_bytes=fixture),
                headers=ADMIN_BEARER,
            )
            assert response.status_code == 404, response.text
            assert response.json()["code"] == "ADMIN_AGENCY_NOT_FOUND"
