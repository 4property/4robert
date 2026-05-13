"""Unit tests for the agency-logo override in ``prepare_cover_logo_image``.

Feature 10 (``agency_logo_upload``) wires the rendering pipeline to
prefer an admin-uploaded logo over the legacy ``property.agency_logo_url``
that comes from the WordPress webhook. The two paths under test are:

* **Override** — ``PropertyRenderData.agency_logo_local_path`` points to
  a real file on disk; ``prepare_cover_logo_image`` must return that
  path without ever touching ``property.agency_logo_url`` (the remote
  fetch is patched to fail the test if it runs).
* **Fallback** — the override is ``None`` (or the file is missing on
  disk); ``prepare_cover_logo_image`` must fall back to the webhook
  URL via ``download_remote_image`` as before.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from modules.rendering.infrastructure.models import (
    PropertyReelTemplate,
    PropertyRenderData,
)
from modules.rendering.infrastructure.runtime.branding import (
    prepare_cover_logo_image,
)


def _build_property_data(
    *,
    agency_logo_url: str | None = None,
    agency_logo_local_path: Path | None = None,
) -> PropertyRenderData:
    return PropertyRenderData(
        site_id="ckp.ie",
        property_id=12345,
        slug="sample-property",
        title="Sample property",
        link="https://ckp.ie/property/sample-property",
        property_status="For Sale",
        selected_image_dir=Path("selected_photos"),
        selected_image_paths=(Path("selected_photos/primary_image.png"),),
        featured_image_url=None,
        bedrooms=3,
        bathrooms=2,
        ber_rating=None,
        agent_name="Jane Doe",
        agent_photo_url=None,
        agent_email=None,
        agent_mobile=None,
        agent_number=None,
        price="500000",
        property_type_label="Apartment",
        property_area_label="Dublin 14",
        property_county_label="Dublin",
        eircode="D14 TEST",
        agency_logo_url=agency_logo_url,
        agency_logo_local_path=agency_logo_local_path,
    )


def test_prepare_cover_logo_prefers_local_override_over_webhook_url(
    tmp_path: Path,
) -> None:
    """Agency-uploaded path wins, webhook URL is never fetched."""

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    uploaded_logo = tmp_path / "uploaded_logo.png"
    uploaded_logo.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)

    property_data = _build_property_data(
        agency_logo_url="https://wordpress.example.com/wp-content/uploads/webhook_logo.png",
        agency_logo_local_path=uploaded_logo,
    )
    template = PropertyReelTemplate()

    with patch(
        "modules.rendering.infrastructure.runtime.branding.download_remote_image"
    ) as download_mock:
        cover_path = prepare_cover_logo_image(
            workspace_dir, property_data, template
        )

    assert cover_path == uploaded_logo
    assert download_mock.call_count == 0


def test_prepare_cover_logo_falls_back_to_webhook_when_override_unset(
    tmp_path: Path,
) -> None:
    """Empty ``logo_object_key`` → local path is None → webhook URL is used."""

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    property_data = _build_property_data(
        agency_logo_url="https://wordpress.example.com/wp-content/uploads/webhook_logo.png",
        agency_logo_local_path=None,
    )
    template = PropertyReelTemplate()

    def fake_download(image_url: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fake-webhook-bytes")
        return destination

    with patch(
        "modules.rendering.infrastructure.runtime.branding.download_remote_image",
        side_effect=fake_download,
    ) as download_mock:
        cover_path = prepare_cover_logo_image(
            workspace_dir, property_data, template
        )

    assert cover_path is not None
    assert cover_path.read_bytes() == b"fake-webhook-bytes"
    assert download_mock.call_count == 1
    assert (
        download_mock.call_args.args[0]
        == "https://wordpress.example.com/wp-content/uploads/webhook_logo.png"
    )


def test_prepare_cover_logo_falls_back_when_override_path_missing_on_disk(
    tmp_path: Path,
) -> None:
    """If the uploaded path is stale (file deleted), we fall back."""

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()
    missing_override = tmp_path / "stale_logo.png"
    # File deliberately not written.

    property_data = _build_property_data(
        agency_logo_url="https://wordpress.example.com/wp-content/uploads/webhook_logo.png",
        agency_logo_local_path=missing_override,
    )
    template = PropertyReelTemplate()

    def fake_download(image_url: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fake-webhook-bytes")
        return destination

    with patch(
        "modules.rendering.infrastructure.runtime.branding.download_remote_image",
        side_effect=fake_download,
    ) as download_mock:
        cover_path = prepare_cover_logo_image(
            workspace_dir, property_data, template
        )

    assert cover_path is not None
    assert cover_path.read_bytes() == b"fake-webhook-bytes"
    assert download_mock.call_count == 1


def test_prepare_cover_logo_returns_none_when_neither_override_nor_url(
    tmp_path: Path,
) -> None:
    """No upload and no webhook URL → no agency logo on the reel."""

    workspace_dir = tmp_path / "workspace"
    workspace_dir.mkdir()

    property_data = _build_property_data(
        agency_logo_url=None,
        agency_logo_local_path=None,
    )
    template = PropertyReelTemplate()

    with patch(
        "modules.rendering.infrastructure.runtime.branding.download_remote_image"
    ) as download_mock:
        cover_path = prepare_cover_logo_image(
            workspace_dir, property_data, template
        )

    assert cover_path is None
    assert download_mock.call_count == 0
