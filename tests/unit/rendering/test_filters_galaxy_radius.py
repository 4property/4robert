"""Unit tests for ``_resolve_galaxy_panel_radius``.

The Galaxy reference uses broad panels with subtle rounded corners, so
the helper keeps the same top/bottom radius and a low ``max(12,
round(frame_h * 0.010))`` floor.
"""

from __future__ import annotations

from modules.rendering.infrastructure.ffmpeg.filters import (
    _resolve_galaxy_panel_radius,
    _resolve_side_banner_footer_radius,
)


def test_galaxy_panel_radius_typical_1080x1920_is_subtle() -> None:
    """At the canonical 1080x1920 frame Galaxy keeps a subtle radius."""
    galaxy_radius = _resolve_galaxy_panel_radius(
        frame_height=1920, panel_width=1015, panel_height=217
    )
    side_banner_radius = _resolve_side_banner_footer_radius(
        frame_height=1920, panel_width=1015, panel_height=217
    )
    assert galaxy_radius == max(12, round(1920 * 0.010))
    assert galaxy_radius < side_banner_radius


def test_galaxy_panel_radius_floor_at_short_frame() -> None:
    """At a short frame the helper hits the 12 px floor."""
    galaxy_radius = _resolve_galaxy_panel_radius(
        frame_height=600, panel_width=500, panel_height=200
    )
    assert galaxy_radius == 12


def test_galaxy_panel_radius_capped_by_panel_dimensions() -> None:
    """The radius can never exceed half of the panel's shortest side."""
    # frame_height=2000 -> would suggest round(2000*0.010) = 20 px, but
    # panel_height=20 caps the radius at 10 px.
    galaxy_radius = _resolve_galaxy_panel_radius(
        frame_height=2000, panel_width=400, panel_height=20
    )
    assert galaxy_radius == 10
