"""Unit tests for `apply_alpha_to_hex` (Feature 16)."""

from __future__ import annotations

from modules.rendering.infrastructure.formatting import apply_alpha_to_hex


def test_apply_alpha_to_hex_with_hash_prefix() -> None:
    assert apply_alpha_to_hex("#e22f8c") == "0xe22f8c@0.85"


def test_apply_alpha_to_hex_without_hash_prefix() -> None:
    assert apply_alpha_to_hex("e22f8c") == "0xe22f8c@0.85"


def test_apply_alpha_to_hex_expands_shorthand() -> None:
    assert apply_alpha_to_hex("#fff") == "0xffffff@0.85"
    assert apply_alpha_to_hex("abc") == "0xaabbcc@0.85"


def test_apply_alpha_to_hex_lowercases_hex_digits() -> None:
    assert apply_alpha_to_hex("#FF00AA") == "0xff00aa@0.85"


def test_apply_alpha_to_hex_alpha_override() -> None:
    assert apply_alpha_to_hex("#000", alpha=0.5) == "0x000000@0.50"


def test_apply_alpha_to_hex_clamps_alpha() -> None:
    assert apply_alpha_to_hex("#fff", alpha=2.0).endswith("@1.00")
    assert apply_alpha_to_hex("#fff", alpha=-1.0).endswith("@0.00")


def test_apply_alpha_to_hex_none_returns_none() -> None:
    assert apply_alpha_to_hex(None) is None


def test_apply_alpha_to_hex_invalid_returns_none() -> None:
    assert apply_alpha_to_hex("") is None
    assert apply_alpha_to_hex("not-a-color") is None
    assert apply_alpha_to_hex("#xy00zz") is None
    assert apply_alpha_to_hex("#12345") is None
