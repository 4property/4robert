from __future__ import annotations

import json
import shutil
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx

APPLICATION_ROOT = Path(__file__).resolve().parents[1]
if str(APPLICATION_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLICATION_ROOT))

from config import GEMINI_SELECTION_AUDIT_FILENAME
from core.errors import PhotoFilteringError
from models.property import Property
from services.ai_photo_selection.client import (
    GEMINI_BASE_URL,
    GeminiConfigurationError,
    GeminiPhotoSelectionClient,
    GeminiQuotaExhaustedError,
)
from services.ai_photo_selection.prompting import (
    build_prompt,
    build_property_context,
    normalize_caption,
)
from services.ai_photo_selection.selection import (
    GeminiImageRecord,
    choose_selected_rows,
    classify_property_images,
)
from services.property_media.naming import build_image_filename, build_selected_image_filename
from services.property_media.selection import download_and_filter_property_images

TEST_TEMP_ROOT = APPLICATION_ROOT / ".tmp_test_cases"
TEST_TEMP_ROOT.mkdir(parents=True, exist_ok=True)


@contextmanager
def workspace_temp_dir():
    temp_dir = TEST_TEMP_ROOT / uuid4().hex
    temp_dir.mkdir(parents=True, exist_ok=False)
    try:
        yield temp_dir
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def build_property() -> Property:
    return Property.from_api_payload(
        {
            "id": 170800,
            "importer_id": "2530",
            "slug": "sample-property",
            "title": {"rendered": "46 Example Street, Dublin 4"},
            "eircode": "D04 TEST",
            "property_type_label": "Apartment",
            "property_status": "Sale Agreed",
            "bedrooms": 3,
            "bathrooms": 2,
            "ber_rating": "B2",
            "excerpt": {"rendered": "Short excerpt."},
            "content": {"rendered": "Bright home with private patio."},
            "property_features": [
                "Own-door access|Private patio",
                "Turnkey condition",
            ],
            "wppd_primary_image": "https://example.com/01.jpg",
            "wppd_pics": [
                "https://example.com/01.jpg",
                "https://example.com/02.jpg",
                "https://example.com/03.jpg",
                "https://example.com/04.jpg",
                "https://example.com/05.jpg",
            ],
        }
    )


class PromptBuilderTests(unittest.TestCase):
    def test_build_prompt_formats_split_property_features_for_gemini(self) -> None:
        property_context = build_property_context(build_property())

        prompt = build_prompt(property_context)

        self.assertEqual(
            property_context["property_features"],
            ["Own-door access", "Private patio", "Turnkey condition"],
        )
        self.assertIn("Main features provided by the agent or listing:", prompt)
        self.assertIn("- Own-door access", prompt)
        self.assertIn("- Private patio", prompt)
        self.assertIn("- Turnkey condition", prompt)
        self.assertIn('"caption": "short estate-agent style fragment"', prompt)
        self.assertIn(
            'The caption must read like concise estate-agent feature copy, not like descriptive prose.',
            prompt,
        )
        self.assertIn(
            '- Do not start the caption with labels such as "Key features", "Features", or similar.',
            prompt,
        )
        self.assertIn('  - "Fully fitted bathroom"', prompt)
        self.assertNotIn('  - "Key features: Fully fitted bathroom"', prompt)
        self.assertNotIn("['Own-door access'", prompt)

    def test_build_property_context_splits_pipe_delimited_property_features(self) -> None:
        property_item = Property.from_api_payload(
            {
                "id": 170801,
                "slug": "sample-property-2",
                "title": {"rendered": "Sample Property"},
                "property_features": [
                    "Ground floor apartment with large private deck|"
                    "Well maintained gated and landscaped gardens|"
                    "Beautifully presented in turnkey condition|"
                    "Underfloor heating.|Secure underground parking|"
                    "10 minutes walk from UCD.|"
                    "Two double bedrooms. Two bathrooms.|"
                    "Open-plan kitchen/living/dining with hardwood flooring|"
                    "Not rent capped.|Service charge approx. â‚¬2870 per annum"
                ],
            }
        )

        property_context = build_property_context(property_item)

        self.assertIn(
            "Ground floor apartment with large private deck",
            property_context["property_features"],
        )
        self.assertIn(
            "Open-plan kitchen/living/dining with hardwood flooring",
            property_context["property_features"],
        )
        self.assertIn(
            "Service charge approx. â‚¬2870 per annum",
            property_context["property_features"],
        )
        self.assertEqual(len(property_context["property_features"]), 10)

    def test_normalize_caption_removes_key_features_prefix(self) -> None:
        self.assertEqual(
            normalize_caption("Key features: Bright open-plan kitchen/dining area"),
            "Bright open-plan kitchen/dining area.",
        )
        self.assertEqual(
            normalize_caption("FEATURES: Private rear garden"),
            "Private rear garden.",
        )


class ImageNamingTests(unittest.TestCase):
    def test_long_local_image_filenames_are_shortened_for_windows_paths(self) -> None:
        image_url = (
            "https://example.com/"
            "apartment-64-fitzwilliam-point-fitzwilliam-quay-ringsend-dublin-4-"
            "85115b71_6da0dc7f_7446972e_cdc16577.jpg"
        )

        raw_filename = build_image_filename(1, image_url)
        selected_filename = build_selected_image_filename(1, raw_filename)

        self.assertLessEqual(len(Path(raw_filename).name), 76)
        self.assertLessEqual(len(Path(selected_filename).name), 75)
        self.assertTrue(raw_filename.endswith(".jpg"))
        self.assertTrue(selected_filename.endswith(".jpg"))


class GeminiClientTests(unittest.TestCase):
    def test_classify_image_posts_json_payload_and_parses_response(self) -> None:
        with workspace_temp_dir() as temp_dir:
            image_path = temp_dir / "room.jpg"
            image_path.write_bytes(b"image-bytes")
            captured_request: dict[str, object] = {}

            def handler(request: httpx.Request) -> httpx.Response:
                captured_request["url"] = str(request.url)
                captured_request["payload"] = json.loads(request.content.decode("utf-8"))
                return httpx.Response(
                    200,
                    json={
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {
                                            "text": json.dumps(
                                                {
                                                    "area": "living_room",
                                                    "confidence": 98,
                                                    "showcase_score": 85,
                                                    "space_id": "main_living_space",
                                                    "highlights": [
                                                        "feature fireplace",
                                                        "timber flooring",
                                                    ],
                                                    "caption": "Living room with feature fireplace",
                                                }
                                            )
                                        }
                                    ]
                                }
                            }
                        ]
                    },
                )

            client = GeminiPhotoSelectionClient(
                api_key="test-key",
                model="gemini-2.5-flash",
                retry_attempts=1,
                client=httpx.Client(
                    transport=httpx.MockTransport(handler),
                    base_url=GEMINI_BASE_URL,
                ),
            )
            result = client.classify_image(image_path, "prompt text")
            client.close()

        self.assertTrue(
            str(captured_request["url"]).endswith(
                "/v1beta/models/gemini-2.5-flash:generateContent?key=test-key"
            )
        )
        payload = captured_request["payload"]
        assert isinstance(payload, dict)
        self.assertEqual(payload["generationConfig"]["temperature"], 0)
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(payload["generationConfig"]["thinkingConfig"]["thinkingBudget"], 0)
        self.assertEqual(payload["contents"][0]["parts"][0]["text"], "prompt text")
        self.assertEqual(result["area"], "living_room")
        self.assertEqual(result["space_id"], "main_living_space")
        self.assertEqual(result["caption"], "Living room with feature fireplace.")

    def test_classify_image_raises_daily_quota_error_on_daily_limit(self) -> None:
        with workspace_temp_dir() as temp_dir:
            image_path = temp_dir / "room.jpg"
            image_path.write_bytes(b"image-bytes")

            def handler(request: httpx.Request) -> httpx.Response:
                return httpx.Response(
                    429,
                    json={
                        "error": {
                            "details": [
                                {
                                    "violations": [
                                        {
                                            "quotaId": "GenerateContentRequestsPerDayPerProjectPerModel-FreeTier"
                                        }
                                    ],
                                    "retryDelay": "35s",
                                }
                            ]
                        }
                    },
                )

            client = GeminiPhotoSelectionClient(
                api_key="test-key",
                model="gemini-2.5-flash",
                retry_attempts=1,
                client=httpx.Client(
                    transport=httpx.MockTransport(handler),
                    base_url=GEMINI_BASE_URL,
                ),
            )
            with self.assertRaises(GeminiQuotaExhaustedError):
                client.classify_image(image_path, "prompt text")
            client.close()


class GeminiSelectionRuleTests(unittest.TestCase):
    def test_choose_selected_rows_respects_reserved_file_and_area_limits(self) -> None:
        results = [
            {
                "file": "primary_image.jpg",
                "area": "exterior_front",
                "confidence": 80,
                "showcase_score": 70,
                "space_id": "front",
                "highlights": [],
                "caption": "Primary",
                "reserved": True,
            },
            {
                "file": "living-1.jpg",
                "area": "living_room",
                "confidence": 90,
                "showcase_score": 95,
                "space_id": "living_main",
                "highlights": [],
                "caption": "Living",
            },
            {
                "file": "living-2.jpg",
                "area": "living_room",
                "confidence": 88,
                "showcase_score": 92,
                "space_id": "living_main",
                "highlights": [],
                "caption": "Duplicate living",
            },
            {
                "file": "bed-1.jpg",
                "area": "bedroom",
                "confidence": 80,
                "showcase_score": 88,
                "space_id": "bed_1",
                "highlights": [],
                "caption": "Bed 1",
            },
            {
                "file": "bed-2.jpg",
                "area": "bedroom",
                "confidence": 81,
                "showcase_score": 87,
                "space_id": "bed_2",
                "highlights": [],
                "caption": "Bed 2",
            },
            {
                "file": "bed-3.jpg",
                "area": "bedroom",
                "confidence": 82,
                "showcase_score": 86,
                "space_id": "bed_3",
                "highlights": [],
                "caption": "Bed 3",
            },
            {
                "file": "bed-4.jpg",
                "area": "bedroom",
                "confidence": 83,
                "showcase_score": 85,
                "space_id": "bed_4",
                "highlights": [],
                "caption": "Bed 4",
            },
            {
                "file": "bath-1.jpg",
                "area": "bathroom",
                "confidence": 75,
                "showcase_score": 85,
                "space_id": "bath_1",
                "highlights": [],
                "caption": "Bath 1",
            },
            {
                "file": "bath-2.jpg",
                "area": "bathroom",
                "confidence": 76,
                "showcase_score": 84,
                "space_id": "bath_2",
                "highlights": [],
                "caption": "Bath 2",
            },
            {
                "file": "bath-3.jpg",
                "area": "bathroom",
                "confidence": 77,
                "showcase_score": 83,
                "space_id": "bath_3",
                "highlights": [],
                "caption": "Bath 3",
            },
            {
                "file": "hall-1.jpg",
                "area": "hallway",
                "confidence": 70,
                "showcase_score": 82,
                "space_id": "hall_1",
                "highlights": [],
                "caption": "Hall 1",
            },
            {
                "file": "stairs-1.jpg",
                "area": "stairs",
                "confidence": 69,
                "showcase_score": 81,
                "space_id": "stairs_1",
                "highlights": [],
                "caption": "Stairs 1",
            },
        ]

        selected_rows = choose_selected_rows(
            results,
            max_images=8,
            reserved_file="primary_image.jpg",
        )

        self.assertEqual(selected_rows[0]["file"], "primary_image.jpg")
        self.assertEqual(
            sum(1 for row in selected_rows if row["area"] == "bedroom"),
            3,
        )
        self.assertEqual(
            sum(1 for row in selected_rows if row["area"] == "bathroom"),
            2,
        )
        self.assertEqual(
            sum(1 for row in selected_rows if row["area"] in {"hallway", "stairs"}),
            1,
        )
        self.assertEqual(
            len({row["space_id"] for row in selected_rows}),
            len(selected_rows),
        )


class GeminiSelectionWorkflowTests(unittest.TestCase):
    def test_classify_property_images_writes_audit_and_keeps_reserved_image_first(self) -> None:
        property_item = build_property()

        class FakeGeminiClient:
            def __init__(self, *args, **kwargs) -> None:
                self.model = "gemini-fake"

            def classify_image(self, image_path: Path, prompt_text: str) -> dict[str, object]:
                if image_path.name == "primary-source.jpg":
                    return {
                        "area": "exterior_front",
                        "confidence": 90,
                        "showcase_score": 88,
                        "space_id": "front",
                        "highlights": ["own-door access", "brick facade"],
                        "caption": "Exterior view",
                    }
                if image_path.name == "002_living.jpg":
                    return {
                        "area": "living_room",
                        "confidence": 95,
                        "showcase_score": 91,
                        "space_id": "living_main",
                        "highlights": ["timber flooring", "feature fireplace"],
                        "caption": "Living room",
                    }
                return {
                    "area": "kitchen",
                    "confidence": 89,
                    "showcase_score": 84,
                    "space_id": "kitchen_main",
                    "highlights": ["shaker units", "breakfast counter"],
                    "caption": "Kitchen",
                }

            def close(self) -> None:
                return None

        with workspace_temp_dir() as temp_dir:
            primary_path = temp_dir / "primary-source.jpg"
            living_path = temp_dir / "002_living.jpg"
            kitchen_path = temp_dir / "003_kitchen.jpg"
            for path in (primary_path, living_path, kitchen_path):
                path.write_bytes(b"image")

            output_path = temp_dir / GEMINI_SELECTION_AUDIT_FILENAME
            outcome = classify_property_images(
                property_item,
                [
                    GeminiImageRecord(
                        file="primary_image.jpg",
                        source_url="https://example.com/01.jpg",
                        source_index=1,
                        local_path=primary_path,
                        relative_path="raw/primary-source.jpg",
                        reserved=True,
                    ),
                    GeminiImageRecord(
                        file="002_living.jpg",
                        source_url="https://example.com/02.jpg",
                        source_index=2,
                        local_path=living_path,
                        relative_path="raw/002_living.jpg",
                    ),
                    GeminiImageRecord(
                        file="003_kitchen.jpg",
                        source_url="https://example.com/03.jpg",
                        source_index=3,
                        local_path=kitchen_path,
                        relative_path="raw/003_kitchen.jpg",
                    ),
                ],
                output_path=output_path,
                downloads_dir="raw",
                photos_to_select=3,
                client=FakeGeminiClient(),
            )

            payload = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["selected_images"][0]["file"], "primary_image.jpg")
        self.assertEqual(payload["selected_images"][0]["caption"], "Exterior view.")
        self.assertEqual(payload["selected_images"][1]["caption"], "Living room.")
        self.assertEqual(payload["selected_images"][2]["caption"], "Kitchen.")
        self.assertEqual(
            tuple(path.name for path in outcome.selected_photo_paths),
            ("002_living.jpg", "003_kitchen.jpg"),
        )


class WordPressImageIntegrationTests(unittest.TestCase):
    @staticmethod
    def _fake_download_image(image_url: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(f"downloaded:{image_url}".encode("utf-8"))

    def test_download_and_filter_property_images_uses_gemini_and_writes_ordered_selection(self) -> None:
        property_item = build_property()

        class FakeGeminiClient:
            def __init__(self, *args, **kwargs) -> None:
                self.model = "gemini-fake"

            def classify_image(self, image_path: Path, prompt_text: str) -> dict[str, object]:
                if image_path.name.startswith("_tmp_primary_image"):
                    return {
                        "area": "exterior_front",
                        "confidence": 92,
                        "showcase_score": 87,
                        "space_id": "front",
                        "highlights": ["own-door access", "brick facade"],
                        "caption": "Exterior",
                    }
                if image_path.name == "002_02.jpg":
                    return {
                        "area": "living_room",
                        "confidence": 96,
                        "showcase_score": 94,
                        "space_id": "living_main",
                        "highlights": ["feature fireplace", "timber flooring"],
                        "caption": "Living room",
                    }
                if image_path.name == "003_03.jpg":
                    return {
                        "area": "kitchen",
                        "confidence": 93,
                        "showcase_score": 90,
                        "space_id": "kitchen_main",
                        "highlights": ["breakfast counter", "appliances"],
                        "caption": "Kitchen",
                    }
                return {
                    "area": "bedroom",
                    "confidence": 85,
                    "showcase_score": 80,
                    "space_id": f"space_{image_path.stem}",
                    "highlights": ["wardrobes", "window"],
                    "caption": "Bedroom",
                }

            def close(self) -> None:
                return None

        with workspace_temp_dir() as workspace_dir:
            raw_images_root = workspace_dir / "property_media_raw" / "site-a"
            filtered_images_root = workspace_dir / "property_media" / "site-a"

            with (
                patch(
                    "services.property_media.downloads.download_image",
                    side_effect=self._fake_download_image,
                ),
                patch(
                    "services.ai_photo_selection.selection.GeminiPhotoSelectionClient",
                    FakeGeminiClient,
                ),
            ):
                selected_dir, downloaded_images = download_and_filter_property_images(
                    property_item,
                    raw_images_root,
                    filtered_images_root,
                    photos_to_select=4,
                )

            selected_files = sorted(path.name for path in selected_dir.iterdir())
            audit_path = selected_dir.parent / GEMINI_SELECTION_AUDIT_FILENAME
            payload = json.loads(audit_path.read_text(encoding="utf-8"))

        self.assertTrue(any(name.startswith("01_") for name in selected_files))
        self.assertIn("primary_image.jpg", selected_files)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["selected_images"][0]["file"], "primary_image.jpg")
        self.assertEqual(payload["selected_images"][0]["caption"], "Exterior.")
        self.assertEqual(payload["selected_images"][1]["caption"], "Living room.")
        self.assertTrue(any(local_path is not None for _, _, local_path in downloaded_images))

    def test_download_and_filter_property_images_fails_without_gemini_and_writes_partial_audit(self) -> None:
        property_item = build_property()

        class FailingGeminiClient:
            def __init__(self, *args, **kwargs) -> None:
                raise GeminiConfigurationError("Gemini is not configured")

        with workspace_temp_dir() as workspace_dir:
            raw_images_root = workspace_dir / "property_media_raw" / "site-a"
            filtered_images_root = workspace_dir / "property_media" / "site-a"

            with (
                patch(
                    "services.property_media.downloads.download_image",
                    side_effect=self._fake_download_image,
                ),
                patch(
                    "services.ai_photo_selection.selection.GeminiPhotoSelectionClient",
                    FailingGeminiClient,
                ),
            ):
                with self.assertRaises(PhotoFilteringError):
                    download_and_filter_property_images(
                        property_item,
                        raw_images_root,
                        filtered_images_root,
                        photos_to_select=4,
                    )

            audit_path = (
                filtered_images_root
                / property_item.folder_name
                / GEMINI_SELECTION_AUDIT_FILENAME
            )
            payload = json.loads(audit_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["results"], [])
        self.assertIn("Gemini is not configured", payload["processing_error"])


if __name__ == "__main__":
    unittest.main()

