"""Unit tests for the optional ``currency_symbol`` argument on
``format_price`` and ``build_display_price``.

Century 21 polish v2 (2026-05-19): the galaxy layout variant renders
prices with a ``$`` glyph instead of the historical ``€`` so the
overlay matches the U.S. Century 21 brand. The signatures stay
backward-compatible — the default symbol is the euro, so classic and
side_banner renders are byte-identical to the pre-v2 baseline.

These tests pin three behaviours:

1. ``format_price`` honours ``currency_symbol`` for numeric values.
2. ``build_display_price`` formats from ``property_data.price`` with
   the requested currency.
3. ``build_display_price`` rewrites the ``€`` glyph baked into
   ``property_data.price_display_text`` to the requested currency
   *only* when a non-euro symbol is requested. Otherwise the upstream
   text passes through untouched (no regression for classic /
   side_banner).
"""

from __future__ import annotations

from modules.rendering.infrastructure.formatting import (
    build_display_price,
    format_price,
)
from tests.unit.rendering.conftest import build_property_data


def test_format_price_defaults_to_euro_for_backwards_compat() -> None:
    assert format_price("1234567") == "€1,234,567"


def test_format_price_supports_dollar_for_galaxy() -> None:
    assert format_price("1234567", currency_symbol="$") == "$1,234,567"


def test_build_display_price_defaults_to_euro_for_classic_and_side_banner() -> None:
    property_data = build_property_data(price="1234567", price_display_text=None)
    assert build_display_price(property_data) == "€1,234,567"


def test_build_display_price_uses_dollar_when_galaxy_passes_currency_symbol() -> None:
    property_data = build_property_data(price="1234567", price_display_text=None)
    assert (
        build_display_price(property_data, currency_symbol="$")
        == "$1,234,567"
    )


def test_build_display_price_rewrites_euro_marker_in_display_text_for_galaxy() -> None:
    property_data = build_property_data(
        price="500000",
        price_display_text="€500,000",
    )
    assert (
        build_display_price(property_data, currency_symbol="$")
        == "$500,000"
    )


def test_build_display_price_preserves_display_text_for_default_currency() -> None:
    property_data = build_property_data(
        price="500000",
        price_display_text="€500,000",
    )
    # Classic / side_banner pass no override (or pass "€"): the
    # upstream text is returned untouched so existing renders stay
    # byte-identical.
    assert build_display_price(property_data) == "€500,000"
    assert (
        build_display_price(property_data, currency_symbol="€")
        == "€500,000"
    )
