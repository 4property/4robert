"""Source-level guards for the side_banner panel-colour cascade.

Hotfix 2026-05-15: ``BrandSettings.primary_color`` (carried on
``PropertyRenderData.side_banner_panel_color``) drives the side_banner
top / bottom panels. The WordPress webhook accent feed is no longer
consulted at this layer. The cascade is therefore:

    side_banner_panel_color (brand primary)  →  _SIDE_BANNER_PANEL_DEFAULT
                                                (neutral grey hardcoded)

The two consumers are ``modules/rendering/infrastructure/poster.py``
(cover poster) and ``modules/rendering/infrastructure/ffmpeg/render_reel.py``
(segmented reel). A regression that drops the brand colour from the
fallback chain (e.g. reintroduces a bare
``apply_alpha_to_hex(property_data.accent_background_color, ...)``
without consulting ``side_banner_panel_color`` first) would silently
revert per-agency theming, so we inspect the source instead of running
ffmpeg.
"""

from __future__ import annotations

import inspect

from modules.rendering.infrastructure import poster
from modules.rendering.infrastructure.ffmpeg import render_reel


def test_poster_panel_color_prefers_side_banner_panel_color() -> None:
    """``poster.py`` reads ``side_banner_panel_color`` then falls to grey."""
    source = inspect.getsource(poster)
    # Brand-driven field must drive the panel colour.
    assert "property_data.side_banner_panel_color" in source
    # Hardcoded grey is the fallback when brand is absent.
    assert "_SIDE_BANNER_PANEL_DEFAULT" in source
    assert poster._SIDE_BANNER_PANEL_DEFAULT == "#374151"
    # The exact wiring uses ``or`` chaining to keep the grey as fallback.
    assert (
        "side_banner_panel_color\n            or _SIDE_BANNER_PANEL_DEFAULT"
        in source
        or "side_banner_panel_color or _SIDE_BANNER_PANEL_DEFAULT" in source
    )
    # Webhook accent must NOT be consulted in the cascade any more.
    assert "or property_data.accent_background_color" not in source


def test_render_reel_panel_color_prefers_side_banner_panel_color() -> None:
    """``render_reel.py`` (segment renderer) honours the brand cascade too."""
    source = inspect.getsource(render_reel)
    assert "property_data.side_banner_panel_color" in source
    assert "_SIDE_BANNER_PANEL_DEFAULT" in source
    assert render_reel._SIDE_BANNER_PANEL_DEFAULT == "#374151"
    assert (
        "side_banner_panel_color\n            or _SIDE_BANNER_PANEL_DEFAULT"
        in source
        or "side_banner_panel_color or _SIDE_BANNER_PANEL_DEFAULT" in source
    )
    # Webhook accent path must NOT be present any more.
    assert "or property_data.accent_background_color" not in source
