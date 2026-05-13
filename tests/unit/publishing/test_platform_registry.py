"""Unit tests for social platform registry metadata."""

from __future__ import annotations

from modules.publishing.infrastructure.adapters.gohighlevel.normalization import (
    SUPPORTED_GOHIGHLEVEL_PLATFORMS,
    normalise_platform_name,
)
from modules.publishing.infrastructure.adapters.gohighlevel.platform_policy import (
    resolve_platform_artifact_kind,
    resolve_platform_social_post_type,
    validate_platform_publish_request,
)
from modules.publishing.infrastructure.adapters.platforms import get_platform_config


def test_pinterest_is_registered_as_a_supported_gohighlevel_platform() -> None:
    config = get_platform_config("pin")

    assert config is not None
    assert config.platform == "pinterest"
    assert "pinterest" in SUPPORTED_GOHIGHLEVEL_PLATFORMS
    assert normalise_platform_name("Pins") == "pinterest"
    assert resolve_platform_social_post_type(
        platform="pinterest",
        requested_social_post_type="reel",
    ) == "post"
    assert resolve_platform_artifact_kind(
        platform="pinterest",
        requested_artifact_kind="poster_image",
    ) == "poster_image"


def test_pinterest_policy_enforces_caption_limit() -> None:
    warnings = validate_platform_publish_request(
        platform="pinterest",
        description="x" * 501,
        social_post_type="post",
        artifact_kind="reel_video",
        title="Sample property",
    )

    assert warnings == (
        "Caption exceeds the configured pinterest limit of 500 characters.",
    )


def test_pinterest_gohighlevel_payload_includes_title_and_link() -> None:
    config = get_platform_config("pinterest")
    assert config is not None

    payload = config.build_gohighlevel_payload(
        "https://ckp.ie/property/42",
        "A" * 120,
    )

    assert payload == {
        "pinterestPostDetails": {
            "title": "A" * 100,
            "link": "https://ckp.ie/property/42",
        }
    }
