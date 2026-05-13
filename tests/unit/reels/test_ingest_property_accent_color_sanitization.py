"""Feature 16 (pass-2): ingestion-time HEX color sanitization.

Verifies that ``IngestPropertyIntoReelUseCase._sanitize_property_accent_colors``
nullifies malformed ``wppd_accent_*`` values on the ingested
``Property`` and emits a ``logger.warning`` line so operators can spot
the offending payload. Valid HEX values and ``None`` round-trip
untouched.
"""

from __future__ import annotations

import logging

from modules.catalog.domain.wordpress_property import Property
from modules.reels.application.use_cases.ingest_property_into_reel import (
    IngestPropertyIntoReelUseCase,
)


def _make_property(
    *,
    text_color: str | None,
    background_color: str | None,
) -> Property:
    return Property(
        id=1234,
        slug="sample-property",
        wppd_accent_text_color=text_color,
        wppd_accent_background_color=background_color,
    )


def test_valid_hex_values_round_trip_untouched(caplog) -> None:
    caplog.set_level(logging.WARNING)
    property_item = _make_property(text_color="#e22f8c", background_color="ffffff")
    IngestPropertyIntoReelUseCase._sanitize_property_accent_colors(property_item)
    assert property_item.wppd_accent_text_color == "#e22f8c"
    assert property_item.wppd_accent_background_color == "ffffff"
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_none_values_pass_through_without_warning(caplog) -> None:
    caplog.set_level(logging.WARNING)
    property_item = _make_property(text_color=None, background_color=None)
    IngestPropertyIntoReelUseCase._sanitize_property_accent_colors(property_item)
    assert property_item.wppd_accent_text_color is None
    assert property_item.wppd_accent_background_color is None
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_invalid_text_color_is_nulled_and_warning_logged(caplog) -> None:
    caplog.set_level(logging.WARNING)
    property_item = _make_property(text_color="red", background_color="#e22f8c")
    IngestPropertyIntoReelUseCase._sanitize_property_accent_colors(property_item)
    assert property_item.wppd_accent_text_color is None
    # Valid background must survive the sanitization of the text field.
    assert property_item.wppd_accent_background_color == "#e22f8c"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "wppd_accent_text_color" in warnings[0].getMessage()
    assert "red" in warnings[0].getMessage()


def test_invalid_background_color_is_nulled_and_warning_logged(caplog) -> None:
    caplog.set_level(logging.WARNING)
    property_item = _make_property(text_color=None, background_color="#xyz")
    IngestPropertyIntoReelUseCase._sanitize_property_accent_colors(property_item)
    assert property_item.wppd_accent_background_color is None
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "wppd_accent_background_color" in warnings[0].getMessage()


def test_both_fields_invalid_emit_two_warnings(caplog) -> None:
    caplog.set_level(logging.WARNING)
    property_item = _make_property(text_color="red", background_color="blue")
    IngestPropertyIntoReelUseCase._sanitize_property_accent_colors(property_item)
    assert property_item.wppd_accent_text_color is None
    assert property_item.wppd_accent_background_color is None
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 2


def test_empty_string_is_treated_as_invalid_and_nulled(caplog) -> None:
    caplog.set_level(logging.WARNING)
    property_item = _make_property(text_color="   ", background_color="")
    IngestPropertyIntoReelUseCase._sanitize_property_accent_colors(property_item)
    # Empty / whitespace-only is malformed (use `None` to signal absence).
    assert property_item.wppd_accent_text_color is None
    assert property_item.wppd_accent_background_color is None
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 2
