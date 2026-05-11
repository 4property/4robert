"""Overlay layout composition for property reels.

Extracted from `services.media.reel_rendering.layout` in feature 15
(`rendering_layout_split`). The legacy module is preserved as a thin
facade until feature 18 retires `services/`.
"""

from __future__ import annotations

from modules.rendering.infrastructure.layout.composition import build_overlay_layout
from modules.rendering.infrastructure.layout.models import (
    BoxLayout,
    LayoutWarning,
    OverlayLayout,
    TextBlockLayout,
    TimedTextSegmentLayout,
)

__all__ = [
    "BoxLayout",
    "LayoutWarning",
    "OverlayLayout",
    "TextBlockLayout",
    "TimedTextSegmentLayout",
    "build_overlay_layout",
]
