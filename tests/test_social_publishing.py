from __future__ import annotations

import json
import shutil
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import httpx

APPLICATION_ROOT = Path(__file__).resolve().parents[1]
if str(APPLICATION_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLICATION_ROOT))

from application.types import PropertyContext, PublishedVideoArtifact, SocialPublishContext
from core.errors import SocialPublishingError, TransientSocialPublishingError
from models.property import Property
from services.social_delivery.description import build_property_public_url, build_tiktok_description
from services.social_delivery.gohighlevel_client import GoHighLevelApiError, GoHighLevelClient
from services.social_delivery.gohighlevel_media_service import GoHighLevelMediaService
from services.social_delivery.gohighlevel_publisher import GoHighLevelPublisher
from services.social_delivery.gohighlevel_social_service import GoHighLevelSocialService
from services.social_delivery.models import PublishVideoRequest, PublishVideoResult
from services.social_delivery.property_publisher import GoHighLevelPropertyPublisher
from services.webhook_transport.site_storage import resolve_site_storage_layout

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


def build_client_with_transport(handler) -> GoHighLevelClient:
    transport = httpx.MockTransport(handler)
    client = httpx.Client(
        base_url="https://services.leadconnectorhq.com",
        transport=transport,
    )
    return GoHighLevelClient(
        base_url="https://services.leadconnectorhq.com",
        api_version="2021-07-28",
        timeout_seconds=30,
        client=client,
    )


def build_property_payload(*, property_status: str = "Sale Agreed") -> dict[str, object]:
    return {
        "id": 170800,
        "slug": "sample-property",
        "title": {"rendered": "46 Example Street, Dublin 4"},
        "modified_gmt": "2026-03-24T10:43:19",
        "price": "650000",
        "bedrooms": 3,
        "bathrooms": 2,
        "ber_rating": "B2",
        "property_status": property_status,
        "link": "https://ckp.ie/property/sample-property",
        "agent_name": "Jane Doe",
        "agent_email": "jane@example.com",
        "agent_number": "+353 1 234 5678",
    }


class DescriptionBuilderTests(unittest.TestCase):
    def test_build_tiktok_description_prioritizes_property_url_and_status(self) -> None:
        description = build_tiktok_description(
            site_id="ckp.ie",
            slug="sample-property",
            title="46 Example Street, Dublin 4",
            price="650000",
            bedrooms=3,
            bathrooms=2,
            ber_rating="B2",
            property_status="Sale Agreed",
            agent_name="Jane Doe",
            agent_email="jane@example.com",
            agent_number="+353 1 234 5678",
            property_link="https://ckp.ie/property/sample-property",
            property_url_template="https://{site_id}/property/{slug}",
        )

        self.assertIn("View property:", description)
        self.assertIn("https://ckp.ie/property/sample-property", description)
        self.assertIn("SALE AGREED", description)
        self.assertNotIn("tel:+35312345678", description)
        self.assertNotIn("mailto:jane@example.com", description)
        self.assertLessEqual(len(description), 150)

    def test_build_property_public_url_appends_tracking_params(self) -> None:
        property_url = build_property_public_url(
            site_id="ckp.ie",
            slug="sample-property",
            property_link="https://ckp.ie/property/sample-property?ref=organic",
            property_url_template="https://{site_id}/property/{slug}",
            tracking_query_params={
                "utm_source": "tiktok",
                "utm_medium": "social",
                "utm_campaign": "{site_id}-{slug}",
            },
        )

        self.assertEqual(
            property_url,
            (
                "https://ckp.ie/property/sample-property"
                "?ref=organic&utm_source=tiktok&utm_medium=social"
                "&utm_campaign=ckp.ie-sample-property"
            ),
        )


class GoHighLevelPublisherRetryTests(unittest.TestCase):
    def test_publish_video_retries_transient_failures_and_succeeds(self) -> None:
        call_counts = {"accounts": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/accounts"):
                call_counts["accounts"] += 1
                if call_counts["accounts"] < 3:
                    raise httpx.ReadTimeout("temporary timeout")
                return httpx.Response(
                    200,
                    json={
                        "results": {
                            "accounts": [
                                {
                                    "id": "account-1",
                                    "name": "TikTok Business",
                                    "platform": "tiktok",
                                    "type": "profile",
                                    "isExpired": False,
                                }
                            ]
                        }
                    },
                )
            if request.url.path == "/users/":
                return httpx.Response(
                    200,
                    json={
                        "users": [
                            {
                                "id": "user-1",
                                "firstName": "Jane",
                                "lastName": "Doe",
                                "email": "jane@example.com",
                            }
                        ]
                    },
                )
            if request.url.path == "/medias/upload-file":
                return httpx.Response(
                    200,
                    json={"fileId": "file-1", "url": "https://storage.googleapis.com/example/reel.mp4"},
                )
            if request.url.path.endswith("/posts"):
                return httpx.Response(
                    201,
                    json={"results": {"id": "post-1", "status": "published"}},
                )
            raise AssertionError(f"Unexpected path: {request.url.path}")

        with workspace_temp_dir() as temp_dir:
            video_path = temp_dir / "sample-reel.mp4"
            video_path.write_bytes(b"video-bytes")
            client = build_client_with_transport(handler)
            publisher = GoHighLevelPublisher(
                media_service=GoHighLevelMediaService(client=client),
                social_service=GoHighLevelSocialService(client=client),
                retry_attempts=3,
                retry_backoff_seconds=0.0,
            )

            result = publisher.publish_video(
                PublishVideoRequest(
                    video_path=video_path,
                    description="https://ckp.ie/property/sample-property",
                    location_id="location-1",
                    access_token="token-1",
                    platform="tiktok",
                    source_site_id="ckp.ie",
                )
            )

        self.assertEqual(result.created_post.post_id, "post-1")
        self.assertEqual(call_counts["accounts"], 3)

    def test_publish_video_uses_injected_fallback_user_selector(self) -> None:
        captured_user_ids: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/accounts"):
                return httpx.Response(
                    200,
                    json={
                        "results": {
                            "accounts": [
                                {
                                    "id": "account-1",
                                    "name": "TikTok Business",
                                    "platform": "tiktok",
                                    "type": "profile",
                                    "isExpired": False,
                                }
                            ]
                        }
                    },
                )
            if request.url.path == "/users/":
                return httpx.Response(
                    200,
                    json={
                        "users": [
                            {
                                "id": "user-1",
                                "firstName": "Alice",
                                "lastName": "Example",
                                "email": "alice@example.com",
                            },
                            {
                                "id": "user-2",
                                "firstName": "Bob",
                                "lastName": "Example",
                                "email": "bob@example.com",
                            },
                        ]
                    },
                )
            if request.url.path == "/medias/upload-file":
                return httpx.Response(
                    200,
                    json={"fileId": "file-1", "url": "https://storage.googleapis.com/example/reel.mp4"},
                )
            if request.url.path.endswith("/posts"):
                captured_user_ids.append(json.loads(request.content.decode("utf-8"))["userId"])
                return httpx.Response(
                    201,
                    json={"results": {"id": "post-1", "status": "published"}},
                )
            raise AssertionError(f"Unexpected path: {request.url.path}")

        def pick_second_user(location_users):
            return location_users[1]

        with workspace_temp_dir() as temp_dir:
            video_path = temp_dir / "sample-reel.mp4"
            video_path.write_bytes(b"video-bytes")
            client = build_client_with_transport(handler)
            publisher = GoHighLevelPublisher(
                media_service=GoHighLevelMediaService(client=client),
                social_service=GoHighLevelSocialService(client=client),
                fallback_user_selector=pick_second_user,
                retry_attempts=1,
                retry_backoff_seconds=0.0,
            )

            publisher.publish_video(
                PublishVideoRequest(
                    video_path=video_path,
                    description="https://ckp.ie/property/sample-property",
                    location_id="location-1",
                    access_token="token-1",
                    platform="tiktok",
                    source_site_id="ckp.ie",
                )
            )

        self.assertEqual(captured_user_ids, ["user-2"])

    def test_publish_video_prefers_requested_user_over_fallback_selector(self) -> None:
        captured_user_ids: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/accounts"):
                return httpx.Response(
                    200,
                    json={
                        "results": {
                            "accounts": [
                                {
                                    "id": "account-1",
                                    "name": "TikTok Business",
                                    "platform": "tiktok",
                                    "type": "profile",
                                    "isExpired": False,
                                }
                            ]
                        }
                    },
                )
            if request.url.path == "/users/":
                return httpx.Response(
                    200,
                    json={
                        "users": [
                            {
                                "id": "user-1",
                                "firstName": "Alice",
                                "lastName": "Example",
                                "email": "alice@example.com",
                            },
                            {
                                "id": "user-2",
                                "firstName": "Bob",
                                "lastName": "Example",
                                "email": "bob@example.com",
                            },
                        ]
                    },
                )
            if request.url.path == "/medias/upload-file":
                return httpx.Response(
                    200,
                    json={"fileId": "file-1", "url": "https://storage.googleapis.com/example/reel.mp4"},
                )
            if request.url.path.endswith("/posts"):
                captured_user_ids.append(json.loads(request.content.decode("utf-8"))["userId"])
                return httpx.Response(
                    201,
                    json={"results": {"id": "post-1", "status": "published"}},
                )
            raise AssertionError(f"Unexpected path: {request.url.path}")

        def pick_second_user(location_users):
            return location_users[1]

        with workspace_temp_dir() as temp_dir:
            video_path = temp_dir / "sample-reel.mp4"
            video_path.write_bytes(b"video-bytes")
            client = build_client_with_transport(handler)
            publisher = GoHighLevelPublisher(
                media_service=GoHighLevelMediaService(client=client),
                social_service=GoHighLevelSocialService(client=client),
                fallback_user_selector=pick_second_user,
                retry_attempts=1,
                retry_backoff_seconds=0.0,
            )

            publisher.publish_video(
                PublishVideoRequest(
                    video_path=video_path,
                    description="https://ckp.ie/property/sample-property",
                    location_id="location-1",
                    access_token="token-1",
                    platform="tiktok",
                    user_id="user-1",
                    source_site_id="ckp.ie",
                )
            )

        self.assertEqual(captured_user_ids, ["user-1"])

    def test_publish_video_raises_when_create_post_response_cannot_confirm_post(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/accounts"):
                return httpx.Response(
                    200,
                    json={
                        "results": {
                            "accounts": [
                                {
                                    "id": "account-1",
                                    "name": "TikTok Business",
                                    "platform": "tiktok",
                                    "type": "profile",
                                    "isExpired": False,
                                }
                            ]
                        }
                    },
                )
            if request.url.path == "/users/":
                return httpx.Response(
                    200,
                    json={
                        "users": [
                            {
                                "id": "user-1",
                                "firstName": "Jane",
                                "lastName": "Doe",
                                "email": "jane@example.com",
                            }
                        ]
                    },
                )
            if request.url.path == "/medias/upload-file":
                return httpx.Response(
                    200,
                    json={"fileId": "file-1", "url": "https://storage.googleapis.com/example/reel.mp4"},
                )
            if request.url.path.endswith("/posts"):
                return httpx.Response(
                    201,
                    json={"message": "Created Post", "results": {}},
                )
            raise AssertionError(f"Unexpected path: {request.url.path}")

        with workspace_temp_dir() as temp_dir:
            video_path = temp_dir / "sample-reel.mp4"
            video_path.write_bytes(b"video-bytes")
            client = build_client_with_transport(handler)
            publisher = GoHighLevelPublisher(
                media_service=GoHighLevelMediaService(client=client),
                social_service=GoHighLevelSocialService(client=client),
                retry_attempts=1,
                retry_backoff_seconds=0.0,
            )

            with self.assertRaises(SocialPublishingError) as raised:
                publisher.publish_video(
                    PublishVideoRequest(
                        video_path=video_path,
                        description="https://ckp.ie/property/sample-property",
                        location_id="location-1",
                        access_token="token-1",
                        platform="tiktok",
                        source_site_id="ckp.ie",
                    )
                )

        self.assertIn("did not return a post_id or post_status", str(raised.exception))

    def test_publish_video_does_not_retry_client_errors(self) -> None:
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            if request.url.path.endswith("/accounts"):
                call_count += 1
                return httpx.Response(
                    401,
                    json={"message": "Unauthorized"},
                )
            raise AssertionError(f"Unexpected path: {request.url.path}")

        with workspace_temp_dir() as temp_dir:
            video_path = temp_dir / "sample-reel.mp4"
            video_path.write_bytes(b"video-bytes")
            client = build_client_with_transport(handler)
            publisher = GoHighLevelPublisher(
                media_service=GoHighLevelMediaService(client=client),
                social_service=GoHighLevelSocialService(client=client),
                retry_attempts=3,
                retry_backoff_seconds=0.0,
            )

            with self.assertRaises(GoHighLevelApiError):
                publisher.publish_video(
                    PublishVideoRequest(
                        video_path=video_path,
                        description="",
                        location_id="location-1",
                        access_token="token-1",
                        platform="tiktok",
                    )
                )

        self.assertEqual(call_count, 1)


class PropertyPublisherTests(unittest.TestCase):
    def test_property_publisher_uses_request_scoped_publish_context(self) -> None:
        class FakePublisher:
            def __init__(self) -> None:
                self.last_request: PublishVideoRequest | None = None

            def publish_video(self, request: PublishVideoRequest) -> PublishVideoResult:
                self.last_request = request
                raise TransientSocialPublishingError("stop after capture")

        publisher = FakePublisher()
        property_item = Property.from_api_payload(build_property_payload())
        with workspace_temp_dir() as workspace_dir:
            storage_paths = resolve_site_storage_layout(workspace_dir, "ckp.ie")
            context = PropertyContext(
                workspace_dir=workspace_dir,
                storage_paths=storage_paths,
                site_id="ckp.ie",
                property=property_item,
                publish_context=SocialPublishContext(
                    provider="gohighlevel",
                    location_id="location-1",
                    access_token="token-1",
                    platform="tiktok",
                ),
                publish_description="SALE AGREED\nView property:\nhttps://ckp.ie/property/sample-property",
                publish_target_url="https://ckp.ie/property/sample-property",
            )
            published_video = PublishedVideoArtifact(
                manifest_path=workspace_dir / "sample.json",
                video_path=workspace_dir / "sample.mp4",
            )

            with self.assertRaises(TransientSocialPublishingError):
                GoHighLevelPropertyPublisher(publisher=publisher).publish_property_reel(
                    context,
                    published_video,
                )

        self.assertIsNotNone(publisher.last_request)
        assert publisher.last_request is not None
        self.assertEqual(publisher.last_request.location_id, "location-1")
        self.assertEqual(publisher.last_request.access_token, "token-1")
        self.assertEqual(publisher.last_request.platform, "tiktok")
        self.assertEqual(
            publisher.last_request.description,
            "SALE AGREED\nView property:\nhttps://ckp.ie/property/sample-property",
        )
        self.assertEqual(
            publisher.last_request.target_url,
            "https://ckp.ie/property/sample-property",
        )


if __name__ == "__main__":
    unittest.main()

