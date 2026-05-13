"""Unit tests for :func:`shared.types.colors.is_valid_hex_color`.

Feature 16 (pass-2): ingestion now validates the per-property HEX
fields up front so we can emit a ``logger.warning`` when a webhook
delivers a malformed value (e.g. CSS keywords like ``"red"``) instead
of silently swallowing it deep inside the ffmpeg filter chain.
"""

from __future__ import annotations

import pytest

from shared.errors.validation import is_valid_hex_color


@pytest.mark.parametrize(
    "value",
    [
        "#ffffff",
        "#FFFFFF",
        "ffffff",
        "FFFFFF",
        "#e22f8c",
        "e22f8c",
    ],
)
def test_six_digit_hex_is_valid(value: str) -> None:
    assert is_valid_hex_color(value) is True


@pytest.mark.parametrize("value", ["#fff", "fff", "#FFF", "abc"])
def test_three_digit_hex_shorthand_is_valid(value: str) -> None:
    assert is_valid_hex_color(value) is True


@pytest.mark.parametrize("value", ["#abcd", "abcd", "#ffffffff", "ffffffff"])
def test_alpha_aware_forms_are_valid(value: str) -> None:
    assert is_valid_hex_color(value) is True


def test_none_is_valid() -> None:
    # `None` means the field was not provided and the renderer falls
    # back to BrandSettings.primary_color — that path is intentional.
    assert is_valid_hex_color(None) is True


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "red",
        "white",
        "#xyz",
        "#xyzxyz",
        "#12",
        "#12345",
        "#1234567",
        "rgb(255,0,0)",
        "0xffffff",
    ],
)
def test_invalid_inputs_are_rejected(value: str) -> None:
    assert is_valid_hex_color(value) is False


@pytest.mark.parametrize("value", [123, 0xFFFFFF, 1.5, [], {}, b"#fff"])
def test_non_string_inputs_are_rejected(value: object) -> None:
    assert is_valid_hex_color(value) is False  # type: ignore[arg-type]


def test_leading_and_trailing_whitespace_is_tolerated() -> None:
    assert is_valid_hex_color("  #fff  ") is True
    assert is_valid_hex_color(" ffffff ") is True
