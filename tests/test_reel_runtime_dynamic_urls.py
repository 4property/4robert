from __future__ import annotations

import shutil
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from unittest.mock import patch
from uuid import uuid4

APPLICATION_ROOT = Path(__file__).resolve().parents[1]
if str(APPLICATION_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLICATION_ROOT))

from services.media.reel_rendering.models import PropertyRenderData, PropertyReelTemplate
from services.media.reel_rendering.runtime import (
    prepare_agent_image,
    prepare_cover_logo_image,
    should_reserve_agency_logo_space,
)


@contextmanager
def _workspace_temp_dir() -> Iterator[Path]:
    temp_root = APPLICATION_ROOT / ".tmp_test_cases"
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_dir = temp_root / f"dynamic_urls_{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _build_property_data(workspace_dir: Path) -> PropertyRenderData:
    selected_dir = workspace_dir / "selected_photos"
    selected_dir.mkdir(parents=True, exist_ok=True)
    return PropertyRenderData(
        site_id="4pm.ie",
        property_id=1,
        slug="sample-property",
        title="Sample Property",
        link="https://example.com/property/sample-property",
        property_status="For Sale",
        selected_image_dir=selected_dir,
        selected_image_paths=(),
        featured_image_url=None,
        bedrooms=3,
        bathrooms=2,
        ber_rating=None,
        agent_name="Jane Doe",
        agent_photo_url=None,
        agent_email="jane@example.com",
        agent_mobile=None,
        agent_number="+3531234567",
        price="500000",
        property_type_label="House",
        property_area_label="Dublin",
        property_county_label="Dublin",
        eircode="D01 TEST",
    )


class ReelRuntimeDynamicUrlTests(unittest.TestCase):
    def test_prepare_agent_image_accepts_thumbnail_aspx_url(self) -> None:
        with _workspace_temp_dir() as workspace_dir:
            property_data = _build_property_data(workspace_dir)
            property_data.agent_photo_url = (
                "https://old.4pm.ie/ShowThumbnail.aspx"
                "?img=4pm.ie__agentPhoto.png&h=400&w=400&crop=False&off=1455&neg=127795&t=photo"
            )
            template = PropertyReelTemplate()
            temp_dir = workspace_dir / "_prepared"

            def fake_download(image_url: str, destination: Path) -> Path:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"fake-image")
                return destination

            with patch(
                "services.media.reel_rendering.runtime.download_remote_image",
                side_effect=fake_download,
            ) as download_mock:
                downloaded_path = prepare_agent_image(
                    workspace_dir,
                    property_data,
                    template,
                    temp_dir,
                )

            self.assertEqual(downloaded_path.name, "agent_photo.png")
            self.assertEqual(download_mock.call_args.args[0], property_data.agent_photo_url)

    def test_prepare_cover_logo_image_accepts_thumbnail_aspx_url(self) -> None:
        with _workspace_temp_dir() as workspace_dir:
            property_data = _build_property_data(workspace_dir)
            property_data.agency_logo_url = (
                "https://old.4pm.ie/ShowThumbnail.aspx?img=4pm.ie__agencyLogo.png&w=400"
            )
            template = PropertyReelTemplate()

            def fake_download(image_url: str, destination: Path) -> Path:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"fake-image")
                return destination

            with patch(
                "services.media.reel_rendering.runtime.download_remote_image",
                side_effect=fake_download,
            ) as download_mock:
                downloaded_path = prepare_cover_logo_image(
                    workspace_dir,
                    property_data,
                    template,
                )

            self.assertIsNotNone(downloaded_path)
            assert downloaded_path is not None
            self.assertEqual(downloaded_path.suffix, ".png")
            self.assertEqual(download_mock.call_args.args[0], property_data.agency_logo_url)

    def test_dynamic_agent_photo_matches_static_logo_basename(self) -> None:
        with _workspace_temp_dir() as workspace_dir:
            property_data = _build_property_data(workspace_dir)
            property_data.agent_photo_url = (
                "https://old.4pm.ie/ShowThumbnail.aspx?img=4pm.ie__agentPhoto.png&w=400"
            )
            property_data.agency_logo_url = "https://cdn.example.com/branding/4pm.ie__agentphoto.png"

            self.assertTrue(should_reserve_agency_logo_space(property_data))


if __name__ == "__main__":
    unittest.main()
