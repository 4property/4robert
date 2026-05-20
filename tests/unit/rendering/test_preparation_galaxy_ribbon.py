"""Unit tests for the galaxy variant of ``_resolve_vertical_banner_layout``.

Century 21 polish v3 (2026-05-19): the galaxy vertical ribbon was
shortened back ~20% from polish v2 (0.360 -> 0.288, floor 450 ->
360 px) so the cinta is less dominant against the top photo crop.
The side_banner branch is untouched.

Pins:

1. Galaxy body height ratio set to 0.288 with absolute floor 360 px
   (v2 used 0.360 / 450 px; v1 used 0.268 / 330 px).
2. Galaxy banner still fits inside the frame (total height < frame
   height) at the canonical 1080x1920 resolution.
3. side_banner branch keeps the historical 0.325 body ratio so other
   templates are not affected by the polish pass.
"""

from __future__ import annotations

from modules.rendering.infrastructure.preparation import (
    _resolve_vertical_banner_layout,
)
from tests.unit.rendering.conftest import build_template


def test_resolve_vertical_banner_layout_galaxy_uses_polish_v3_body_height() -> None:
    settings = build_template(width=1080, height=1920)

    layout = _resolve_vertical_banner_layout(settings, layout_variant="galaxy")

    assert layout is not None
    notch_height = layout["notch_height"]
    body_height = layout["height"] - notch_height
    # 0.288 * 1920 = 553 px (max floor 360); polish v2 used 0.360 / 450.
    assert body_height == round(1920 * 0.288)
    assert body_height >= 360


def test_resolve_vertical_banner_layout_galaxy_fits_inside_frame() -> None:
    settings = build_template(width=1080, height=1920)

    layout = _resolve_vertical_banner_layout(settings, layout_variant="galaxy")

    assert layout is not None
    assert layout["height"] < settings.height
    assert layout["width"] < settings.width


def test_resolve_vertical_banner_layout_side_banner_unaffected_by_galaxy_polish() -> None:
    """side_banner keeps the historical 0.325 body ratio; the v2 polish
    does NOT touch it so legacy renders are byte-identical."""
    settings = build_template(width=1080, height=1920)

    layout = _resolve_vertical_banner_layout(settings, layout_variant="side_banner")

    assert layout is not None
    notch_height = layout["notch_height"]
    body_height = layout["height"] - notch_height
    assert body_height == round(1920 * 0.325)
