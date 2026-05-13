"""Unit tests for HTML entity decoding inside `GoHighLevelSocialService.create_social_post`.

Feature 12 `unescape_html_entities_everywhere` — the ``summary`` (and ``title``
when the platform config persists it) sent to ``POST /social-media-posting/
{locationId}/posts`` must be decoded so GoHighLevel never receives raw entities
like ``&#8217;``, ``&amp;``, ``&quot;``, ``&#x2019;``.

This file covers the six mandated cases (decimal numeric, hex numeric, named,
nested, idempotency, empty input) for the publishing integration point.
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


def _build_service(*, response_payload: dict[str, Any] | None = None) -> tuple[
    GoHighLevelSocialService, MagicMock
]:
    """Wire a GoHighLevelSocialService with a fully mocked client.

    Returns the service plus the ``request_json`` mock so individual tests can
    inspect the body that would have been posted.
    """
    client = MagicMock()
    payload = response_payload if response_payload is not None else {
        "results": {"id": "post-123", "status": "published"},
        "statusCode": 201,
        "message": "Post published",
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


def _captured_summary(request_json: MagicMock) -> str:
    """Pull the summary back out of the ``json_body`` kwarg of the captured call."""
    _, kwargs = request_json.call_args
    body = kwargs["json_body"]
    assert isinstance(body, dict)
    summary = body.get("summary")
    assert isinstance(summary, str)
    return summary


def test_create_social_post_decodes_decimal_numeric_entity_in_description() -> None:
    service, request_json = _build_service()

    service.create_social_post(
        location_id="loc-1",
        access_token="token",
        account_id="acct-1",
        user_id="user-1",
        uploaded_media=_make_uploaded_media(),
        platform="instagram",
        description="Dublin&#8217;s elegant home",
        title=None,
        social_post_type="reel",
    )

    assert _captured_summary(request_json) == "Dublin’s elegant home"


def test_create_social_post_decodes_hex_numeric_entity_in_description() -> None:
    service, request_json = _build_service()

    service.create_social_post(
        location_id="loc-1",
        access_token="token",
        account_id="acct-1",
        user_id="user-1",
        uploaded_media=_make_uploaded_media(),
        platform="instagram",
        description="Owner&#x2019;s private suite",
        title=None,
        social_post_type="reel",
    )

    assert _captured_summary(request_json) == "Owner’s private suite"


def test_create_social_post_decodes_named_entities_in_description() -> None:
    service, request_json = _build_service()

    service.create_social_post(
        location_id="loc-1",
        access_token="token",
        account_id="acct-1",
        user_id="user-1",
        uploaded_media=_make_uploaded_media(),
        platform="instagram",
        description="Smith &amp; Sons &quot;Premium&quot;",
        title=None,
        social_post_type="reel",
    )

    assert _captured_summary(request_json) == 'Smith & Sons "Premium"'


def test_create_social_post_decodes_nested_entities_one_level() -> None:
    """One-level decode: ``&amp;amp;`` → ``&amp;`` (not ``&``)."""
    service, request_json = _build_service()

    service.create_social_post(
        location_id="loc-1",
        access_token="token",
        account_id="acct-1",
        user_id="user-1",
        uploaded_media=_make_uploaded_media(),
        platform="instagram",
        description="A &amp;amp; B",
        title=None,
        social_post_type="reel",
    )

    assert _captured_summary(request_json) == "A &amp; B"


def test_create_social_post_is_idempotent_on_already_decoded_description() -> None:
    service, request_json = _build_service()

    service.create_social_post(
        location_id="loc-1",
        access_token="token",
        account_id="acct-1",
        user_id="user-1",
        uploaded_media=_make_uploaded_media(),
        platform="instagram",
        description="Dublin’s elegant home",
        title=None,
        social_post_type="reel",
    )

    assert _captured_summary(request_json) == "Dublin’s elegant home"


def test_create_social_post_accepts_empty_description() -> None:
    service, request_json = _build_service()

    service.create_social_post(
        location_id="loc-1",
        access_token="token",
        account_id="acct-1",
        user_id="user-1",
        uploaded_media=_make_uploaded_media(),
        platform="instagram",
        description="",
        title=None,
        social_post_type="reel",
    )

    assert _captured_summary(request_json) == ""


def test_create_social_post_decodes_title_used_by_platform_payload() -> None:
    """Title is also decoded so any platform that persists it sees clean text.

    YouTube is one of the registered platforms whose ``build_gohighlevel_payload``
    embeds the title under platform-specific keys (``youTubeTitle``); regardless
    of the destination key, the title we feed into the platform builder must be
    decoded.
    """
    service, request_json = _build_service()

    service.create_social_post(
        location_id="loc-1",
        access_token="token",
        account_id="acct-1",
        user_id="user-1",
        uploaded_media=_make_uploaded_media(),
        platform="youtube",
        description="Body unchanged",
        title="Owner&#x2019;s &amp; Family Suite",
        social_post_type="reel",
    )

    _, kwargs = request_json.call_args
    body = kwargs["json_body"]
    assert isinstance(body, dict)
    serialized = repr(body)
    assert "&#x2019;" not in serialized
    assert "&amp;" not in serialized
    assert "Owner’s & Family Suite" in serialized
