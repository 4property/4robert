"""Unit tests for WordPress accent-color ingestion in Property.from_api_payload."""

from __future__ import annotations

from modules.catalog.domain.wordpress_property import Property


def test_property_from_api_payload_extracts_accent_colors() -> None:
    payload = {
        "id": 123,
        "slug": "sample",
        "wppd_accent_text_color": "#ffffff",
        "wppd_accent_background_color": "#e22f8c",
    }
    prop = Property.from_api_payload(payload)

    assert prop.wppd_accent_text_color == "#ffffff"
    assert prop.wppd_accent_background_color == "#e22f8c"


def test_property_from_api_payload_accent_colors_default_to_none() -> None:
    payload = {"id": 123, "slug": "sample"}
    prop = Property.from_api_payload(payload)

    assert prop.wppd_accent_text_color is None
    assert prop.wppd_accent_background_color is None


def test_property_from_api_payload_accent_colors_blank_strings_become_none() -> None:
    payload = {
        "id": 123,
        "slug": "sample",
        "wppd_accent_text_color": "   ",
        "wppd_accent_background_color": "",
    }
    prop = Property.from_api_payload(payload)

    assert prop.wppd_accent_text_color is None
    assert prop.wppd_accent_background_color is None


def test_property_to_db_record_includes_accent_colors() -> None:
    prop = Property.from_api_payload(
        {
            "id": 42,
            "slug": "sample",
            "wppd_accent_text_color": "#000",
            "wppd_accent_background_color": "#fff",
        }
    )
    record = prop.to_db_record(image_folder="", fetched_at="2026-05-13T00:00:00Z")
    assert record["wppd_accent_text_color"] == "#000"
    assert record["wppd_accent_background_color"] == "#fff"


def test_property_to_dict_includes_accent_colors() -> None:
    prop = Property.from_api_payload(
        {
            "id": 42,
            "slug": "sample",
            "wppd_accent_text_color": "#abc",
            "wppd_accent_background_color": "#def",
        }
    )
    data = prop.to_dict()
    assert data["wppd_accent_text_color"] == "#abc"
    assert data["wppd_accent_background_color"] == "#def"
