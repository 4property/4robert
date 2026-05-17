"""Unit tests for :func:`shared.email.url_builder.build_reel_editor_url`."""

from __future__ import annotations

from shared.email.url_builder import build_reel_editor_url


def test_builds_url_with_site_id_and_property_id() -> None:
    url = build_reel_editor_url(
        "https://admin.example.com",
        site_id="ckp.ie",
        property_id=42,
    )
    assert url == "https://admin.example.com/reels?site_id=ckp.ie&property_id=42"


def test_strips_trailing_slash_from_base_url() -> None:
    url = build_reel_editor_url(
        "https://admin.example.com/",
        site_id="ckp.ie",
        property_id=42,
    )
    assert url == "https://admin.example.com/reels?site_id=ckp.ie&property_id=42"


def test_strips_multiple_trailing_slashes() -> None:
    url = build_reel_editor_url(
        "https://admin.example.com///",
        site_id="ckp.ie",
        property_id=42,
    )
    assert url == "https://admin.example.com/reels?site_id=ckp.ie&property_id=42"


def test_escapes_site_id_with_special_characters() -> None:
    url = build_reel_editor_url(
        "https://admin.example.com",
        site_id="some/site with spaces",
        property_id=7,
    )
    assert (
        url
        == "https://admin.example.com/reels?site_id=some%2Fsite%20with%20spaces&property_id=7"
    )


def test_coerces_property_id_to_int_in_string_form() -> None:
    url = build_reel_editor_url(
        "https://admin.example.com",
        site_id="site",
        property_id=7,
    )
    assert "property_id=7" in url


def test_handles_empty_base_url_gracefully() -> None:
    url = build_reel_editor_url("", site_id="site", property_id=1)
    assert url == "/reels?site_id=site&property_id=1"
