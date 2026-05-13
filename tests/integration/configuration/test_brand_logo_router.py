"""Integration tests for ``POST /v1/admin/agencies/{id}/brand/logo``.

Feature 10 (``agency_logo_upload``) adds the first multipart endpoint in
the project: admins upload a JPG/PNG, the back-end persists the binary
under ``workspace/generated_media/_agency_branding/<safe_agency>/`` and
returns an opaque ``object_key`` plus an admin URL that streams the
binary back. The companion GET handler is exercised here too because the
URL returned by POST must point to a working route.
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


_MINIMAL_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 128


def _multipart_files(
    *,
    name: str,
    content: bytes,
    content_type: str,
) -> dict[str, tuple[str, io.BytesIO, str]]:
    return {"file": (name, io.BytesIO(content), content_type)}


def test_brand_logo_upload_accepts_png() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/brand/logo",
                files=_multipart_files(
                    name="logo.png",
                    content=_MINIMAL_PNG,
                    content_type="image/png",
                ),
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 200, response.text
            payload = response.json()
            assert "object_key" in payload
            assert "url" in payload
            safe_agency = safe_site_dirname(seeded.agency_id)
            assert payload["object_key"].startswith(f"agencies/{safe_agency}/logo-")
            assert payload["object_key"].endswith(".png")
            assert payload["url"].startswith(
                f"/v1/admin/agencies/{seeded.agency_id}/brand/logo/file/"
            )

            persisted = (
                workspace_dir
                / "generated_media"
                / "_agency_branding"
                / safe_agency
            )
            assert persisted.exists()
            files = list(persisted.iterdir())
            assert len(files) == 1
            assert files[0].read_bytes() == _MINIMAL_PNG

            # The returned URL must stream the same bytes back.
            download = client.get(payload["url"], headers=ADMIN_BEARER)
            assert download.status_code == 200, download.text
            assert download.content == _MINIMAL_PNG
            assert download.headers["content-type"].startswith("image/png")


def test_brand_logo_upload_accepts_jpeg() -> None:
    jpeg_bytes = b"\xff\xd8\xff\xe0" + b"0" * 128
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/brand/logo",
                files=_multipart_files(
                    name="logo.jpg",
                    content=jpeg_bytes,
                    content_type="image/jpeg",
                ),
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["object_key"].endswith(".jpg")
            assert payload["url"].endswith(".jpg")

            download = client.get(payload["url"], headers=ADMIN_BEARER)
            assert download.status_code == 200, download.text
            assert download.content == jpeg_bytes
            assert download.headers["content-type"].startswith("image/jpeg")


def test_brand_logo_upload_rejects_unsupported_content_type() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/brand/logo",
                files=_multipart_files(
                    name="logo.txt",
                    content=b"not an image",
                    content_type="text/plain",
                ),
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 415, response.text
            assert (
                response.json()["code"]
                == "BRAND_LOGO_UPLOAD_UNSUPPORTED_TYPE"
            )


def test_brand_logo_upload_rejects_extension_mismatch() -> None:
    """A .gif filename with image/jpeg content-type → 422 mismatch."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/brand/logo",
                files=_multipart_files(
                    name="logo.gif",
                    content=_MINIMAL_PNG,
                    content_type="image/jpeg",
                ),
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 422, response.text
            assert (
                response.json()["code"]
                == "BRAND_LOGO_UPLOAD_UNSUPPORTED_EXTENSION"
            )


def test_brand_logo_upload_rejects_type_extension_mismatch() -> None:
    """A .jpg filename with image/png content-type → 422 cross-check."""
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/brand/logo",
                files=_multipart_files(
                    name="logo.jpg",
                    content=_MINIMAL_PNG,
                    content_type="image/png",
                ),
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 422, response.text
            assert (
                response.json()["code"]
                == "BRAND_LOGO_UPLOAD_TYPE_EXTENSION_MISMATCH"
            )


def test_brand_logo_upload_rejects_payload_over_5_mb() -> None:
    oversized = b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024 + 10)
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/brand/logo",
                files=_multipart_files(
                    name="logo.png",
                    content=oversized,
                    content_type="image/png",
                ),
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 413, response.text
            assert (
                response.json()["code"] == "BRAND_LOGO_UPLOAD_TOO_LARGE"
            )


def test_brand_logo_upload_rejects_empty_payload() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/brand/logo",
                files=_multipart_files(
                    name="logo.png",
                    content=b"",
                    content_type="image/png",
                ),
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 422, response.text
            assert response.json()["code"] == "BRAND_LOGO_UPLOAD_EMPTY"


def test_brand_logo_upload_requires_auth() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.post(
                f"/v1/admin/agencies/{seeded.agency_id}/brand/logo",
                files=_multipart_files(
                    name="logo.png",
                    content=_MINIMAL_PNG,
                    content_type="image/png",
                ),
            )

            assert response.status_code in {401, 403}, response.text


def test_brand_logo_upload_rejects_unknown_agency() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.post(
                "/v1/admin/agencies/does-not-exist/brand/logo",
                files=_multipart_files(
                    name="logo.png",
                    content=_MINIMAL_PNG,
                    content_type="image/png",
                ),
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 404, response.text
            assert response.json()["code"] == "ADMIN_AGENCY_NOT_FOUND"


def test_brand_logo_stream_returns_404_for_missing_file() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            client = build_configuration_client(
                database_url=database.url, workspace_dir=workspace_dir
            )

            response = client.get(
                f"/v1/admin/agencies/{seeded.agency_id}/brand/logo/file/missing.png",
                headers=ADMIN_BEARER,
            )

            assert response.status_code == 404, response.text
            assert response.json()["code"] == "BRAND_LOGO_FILE_NOT_FOUND"
