"""Orchestrator for the property-reel overlay layout.

Thin wrapper introduced in feature 15 (`rendering_layout_split`). Computes
the shared geometry constants previously locals of
`services.media.reel_rendering.layout.build_overlay_layout` and delegates
the three phases (top panel, bottom panel, subtitle segments) to dedicated
submodules. Output preserved byte-for-byte versus the legacy
implementation.
"""

from __future__ import annotations

from modules.rendering.infrastructure.layout.models import LayoutWarning, OverlayLayout
from modules.rendering.infrastructure.layout.panels import (
    compose_bottom_panel,
    compose_top_panel,
)
from modules.rendering.infrastructure.layout.subtitles import compose_subtitle_segments
from modules.rendering.infrastructure.models import (
    PropertyReelData,
    PropertyReelSlide,
    PropertyReelTemplate,
)


def build_overlay_layout(
    property_data: PropertyReelData,
    settings: PropertyReelTemplate,
    *,
    slides: tuple[PropertyReelSlide, ...] | list[PropertyReelSlide],
    slide_duration: float | None,
    has_ber_badge: bool,
    has_agency_logo: bool = False,
    cover_caption: str | None = None,
    single_line_contact_email: bool = False,
    layout_variant: str = "classic",
) -> OverlayLayout:
    width = settings.width
    height = settings.height
    # Feature 16: the side_banner variant ditches the outer photo
    # margins entirely so the property photo runs edge to edge
    # (full-bleed). The top panel becomes a full-width band and the
    # vertical status ribbon floats near the right side.
    if layout_variant == "side_banner":
        outer_margin_x = 0
        outer_margin_y = 0
    else:
        outer_margin_x = max(36, round(width * 0.04))
        outer_margin_y = max(36, round(height * 0.03))
    panel_padding_x = max(26, round(width * 0.024))
    panel_padding_y = max(22, round(height * 0.018))
    panel_width = width - (outer_margin_x * 2)

    if layout_variant == "side_banner":
        # The reference side_banner has a full-width translucent top
        # band; text and BER are constrained inside that band while the
        # vertical ribbon floats above it.
        top_panel_width = panel_width
    else:
        top_panel_width = panel_width

    warnings: list[LayoutWarning] = []

    top_panel, top_text_blocks, ber_badge_box, top_warnings = compose_top_panel(
        property_data,
        settings,
        has_ber_badge=has_ber_badge,
        outer_margin_x=outer_margin_x,
        outer_margin_y=outer_margin_y,
        panel_padding_x=panel_padding_x,
        panel_padding_y=panel_padding_y,
        panel_width=top_panel_width,
        layout_variant=layout_variant,
    )
    warnings.extend(top_warnings)

    (
        bottom_panel,
        bottom_text_blocks,
        agent_image_box,
        agency_logo_box,
        bottom_warnings,
    ) = compose_bottom_panel(
        property_data,
        settings,
        top_panel=top_panel,
        has_agency_logo=has_agency_logo,
        single_line_contact_email=single_line_contact_email,
        outer_margin_x=outer_margin_x,
        outer_margin_y=outer_margin_y,
        panel_padding_x=panel_padding_x,
        panel_padding_y=panel_padding_y,
        panel_width=panel_width,
        layout_variant=layout_variant,
    )
    warnings.extend(bottom_warnings)

    subtitle_segments, subtitle_warnings = compose_subtitle_segments(
        property_data,
        settings,
        slides=slides,
        slide_duration=slide_duration,
        cover_caption=cover_caption,
        bottom_panel=bottom_panel,
        panel_width=panel_width,
        outer_margin_x=outer_margin_x,
        outer_margin_y=outer_margin_y,
        panel_padding_x=panel_padding_x,
    )
    warnings.extend(subtitle_warnings)

    return OverlayLayout(
        frame_width=width,
        frame_height=height,
        top_panel=top_panel,
        bottom_panel=bottom_panel,
        agent_image_box=agent_image_box,
        agency_logo_box=agency_logo_box,
        ber_badge_box=ber_badge_box,
        text_blocks=tuple(top_text_blocks) + tuple(bottom_text_blocks),
        subtitle_segments=subtitle_segments,
        warnings=tuple(warnings),
    )


__all__ = ["build_overlay_layout"]
