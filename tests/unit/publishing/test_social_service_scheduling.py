"""Unit tests for `scheduleDate` propagation inside `GoHighLevelSocialService`.

Feature 11 `wire_automation_publish_window_to_ghl_schedule` — when the
approve flow computes a future publish slot from the agency's automation
rules, that ISO8601 UTC timestamp must reach the GoHighLevel POST body
under the canonical key ``scheduleDate``, with ``status='scheduled'``.
When no slot is provided, the existing immediate-publish behaviour
(``status='published'``, no ``scheduleDate``) must be preserved exactly.

The tests use the same ``MagicMock(client.request_json)`` pattern as
``test_social_service_unescape.py`` so they can inspect the ``json_body``
that would have been posted without spinning up an HTTP server.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

APPLICATION_ROOT = Path(__file__).resolve().parents[3]
if str(APPLICATION_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLICATION_ROOT))

from modules.publishing.infrastructure.adapters.gohighlevel.models import UploadedMedia
from modules.publishing.infrastructure.adapters.gohighlevel.social_service import (
    GoHighLevelSocialService,
)


def _build_service(
    *, response_payload: dict[str, Any] | None = None
) -> tuple[GoHighLevelSocialService, MagicMock]:
    client = MagicMock()
    payload = response_payload if response_payload is not None else {
        "results": {"id": "post-123", "status": "scheduled"},
        "statusCode": 201,
        "message": "Post scheduled",
    }
    client.request_json.return_value = payload
    return GoHighLevelSocialService(client=client), client.request_json


def _make_uploaded_media() -> UploadedMedia:
    return UploadedMedia(
        file_id="file-1",
        url="https://cdn.example.com/media/file-1.mp4",
        mime_type="video/mp4",
        file_name="reel.mp4",
        raw_response={},
    )


def _captured_body(request_json: MagicMock) -> dict[str, Any]:
    _, kwargs = request_json.call_args
    body = kwargs["json_body"]
    assert isinstance(body, dict)
    return body


def test_create_social_post_emits_schedule_date_when_scheduled_at_provided() -> None:
    """With a future ``scheduled_at`` we send ``scheduleDate`` and ``status='scheduled'``."""
    service, request_json = _build_service()
    scheduled_at = "2026-05-18T09:00:00+00:00"

    service.create_social_post(
        location_id="loc-1",
        access_token="token",
        account_id="acct-1",
        user_id="user-1",
        uploaded_media=_make_uploaded_media(),
        platform="instagram",
        description="A future scheduled post",
        title=None,
        social_post_type="reel",
        scheduled_at=scheduled_at,
    )

    body = _captured_body(request_json)
    assert body["scheduleDate"] == scheduled_at
    assert body["status"] == "scheduled"


def test_create_social_post_keeps_published_status_when_scheduled_at_none() -> None:
    """Without ``scheduled_at`` the contract stays at ``status='published'``."""
    service, request_json = _build_service(
        response_payload={
            "results": {"id": "post-456", "status": "published"},
            "statusCode": 201,
            "message": "Post published",
        }
    )

    service.create_social_post(
        location_id="loc-1",
        access_token="token",
        account_id="acct-1",
        user_id="user-1",
        uploaded_media=_make_uploaded_media(),
        platform="instagram",
        description="Immediate publish",
        title=None,
        social_post_type="reel",
        scheduled_at=None,
    )

    body = _captured_body(request_json)
    assert "scheduleDate" not in body
    assert body["status"] == "published"


def test_create_social_post_treats_empty_scheduled_at_as_immediate() -> None:
    """Empty / whitespace-only ``scheduled_at`` collapses to immediate publish."""
    service, request_json = _build_service(
        response_payload={
            "results": {"id": "post-789", "status": "published"},
            "statusCode": 201,
            "message": "Post published",
        }
    )

    service.create_social_post(
        location_id="loc-1",
        access_token="token",
        account_id="acct-1",
        user_id="user-1",
        uploaded_media=_make_uploaded_media(),
        platform="instagram",
        description="Whitespace scheduled_at",
        title=None,
        social_post_type="reel",
        scheduled_at="   ",
    )

    body = _captured_body(request_json)
    assert "scheduleDate" not in body
    assert body["status"] == "published"


def test_create_social_post_default_scheduled_at_omitted() -> None:
    """When callers omit ``scheduled_at`` entirely (legacy code paths) the body matches the pre-feature-11 shape."""
    service, request_json = _build_service(
        response_payload={
            "results": {"id": "post-default", "status": "published"},
            "statusCode": 201,
            "message": "Post published",
        }
    )

    service.create_social_post(
        location_id="loc-1",
        access_token="token",
        account_id="acct-1",
        user_id="user-1",
        uploaded_media=_make_uploaded_media(),
        platform="instagram",
        description="No kwarg at all",
        title=None,
        social_post_type="reel",
    )

    body = _captured_body(request_json)
    assert "scheduleDate" not in body
    assert body["status"] == "published"


def test_create_reel_post_forwards_scheduled_at() -> None:
    """``create_reel_post`` is the public wrapper used by other tooling; it must forward the kwarg."""
    service, request_json = _build_service()
    scheduled_at = "2026-06-01T08:30:00+00:00"

    service.create_reel_post(
        location_id="loc-1",
        access_token="token",
        account_id="acct-1",
        user_id="user-1",
        uploaded_media=_make_uploaded_media(),
        platform="instagram",
        description="Forwarded scheduling",
        title=None,
        scheduled_at=scheduled_at,
    )

    body = _captured_body(request_json)
    assert body["scheduleDate"] == scheduled_at
    assert body["status"] == "scheduled"
