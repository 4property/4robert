"""Unit tests pinning the font-weight used for the status text block.

Century 21 polish v2 (2026-05-19): the galaxy layout variant renders
the "OFFERS OVER:" status block in the regular weight so the price
underneath reads as the heavier element. Classic and side_banner keep
the historical bold cascade for ``{status, price, agent_name}``.

We verify this by extracting the drawtext entry whose ``text=``
matches the status block and checking the ``fontfile=`` path: it must
point to the Bold TTF for classic / side_banner and to the Regular TTF
for galaxy.
"""

from __future__ import annotations

import re

from modules.rendering.infrastructure.ffmpeg.filters import build_overlay_filter
from tests.unit.rendering.conftest import build_property_data, build_template


_DRAWTEXT_FONTFILE_PATTERN = re.compile(
    r"drawtext=fontfile='([^']*)':text='([^']*)':",
)


def _font_path_for_text(script: str, text_fragment: str) -> str | None:
    for match in _DRAWTEXT_FONTFILE_PATTERN.finditer(script):
        font_path, text = match.group(1), match.group(2)
        if text_fragment in text:
            return font_path
    return None


def test_galaxy_status_block_uses_regular_weight_not_bold() -> None:
    script = build_overlay_filter(
        build_property_data(),
        build_template(width=1054, height=1492),
        slide_captions=("Caption",),
        slide_duration=2.5,
        layout_variant="galaxy",
    )

    status_font = _font_path_for_text(script, "OFFERS OVER")
    price_font = _font_path_for_text(script, "$500")
    agent_name_font = _font_path_for_text(script, "Jane Doe")

    assert status_font is not None, "status drawtext block missing"
    assert price_font is not None, "price drawtext block missing"
    assert agent_name_font is not None, "agent_name drawtext block missing"
    # Galaxy: status MUST be regular weight (not Bold).
    assert "Bold" not in status_font
    # Galaxy: price and agent_name MUST still be bold.
    assert "Bold" in price_font
    assert "Bold" in agent_name_font


def test_classic_status_block_keeps_bold_weight() -> None:
    """Regression: classic must NOT lose bold on the status block."""
    script = build_overlay_filter(
        build_property_data(property_status="For Sale"),
        build_template(width=1080, height=1920),
        slide_captions=("Caption",),
        slide_duration=2.5,
        layout_variant="classic",
    )

    status_font = _font_path_for_text(script, "FOR SALE")
    price_font = _font_path_for_text(script, "€500")

    assert status_font is not None
    assert price_font is not None
    assert "Bold" in status_font
    assert "Bold" in price_font


def test_side_banner_status_block_keeps_bold_weight() -> None:
    """Regression: side_banner must NOT lose bold on the status block."""
    script = build_overlay_filter(
        build_property_data(),
        build_template(width=1080, height=1920),
        slide_captions=("Caption",),
        slide_duration=2.5,
        layout_variant="side_banner",
    )

    status_font = _font_path_for_text(script, "OFFERS OVER")
    price_font = _font_path_for_text(script, "€500")

    assert status_font is not None
    assert price_font is not None
    assert "Bold" in status_font
    assert "Bold" in price_font
