"""Property reel render template + slide/asset dataclasses.

Migrated from ``services/media/reel_rendering/models.py`` during
sub-feature 18c. The models describe the runtime template fed to ffmpeg
plus the prepared slide/asset envelopes consumed by the rendering
pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from settings.reels import (
    ASSETS_DIRNAME,
    REEL_AUDIO_VOLUME,
    REEL_AGENCY_LOGO_SCALE,
    REEL_BACKGROUND_AUDIO_FILENAME,
    REEL_BER_ICON_SCALE,
    REEL_BER_ICONS_DIRNAME,
    REEL_COVER_LOGO_FILENAME,
    REEL_FFMPEG_ENCODER_THREADS,
    REEL_FFMPEG_FILTER_THREADS,
    REEL_FPS,
    REEL_HEIGHT,
    REEL_INTRO_DURATION_SECONDS,
    REEL_MAX_SLIDE_COUNT,
    REEL_SECONDS_PER_SLIDE,
    REEL_SUBTITLE_FONT_PATH,
    REEL_SUBTITLE_FONT_SIZE,
    REEL_TOTAL_DURATION_SECONDS,
    REEL_WIDTH,
)

PRIMARY_IMAGE_NAME = "primary_image"
DEFAULT_REEL_FONT_PATH = Path("assets/fonts/Inter/static/Inter_28pt-Regular.ttf")
DEFAULT_REEL_FONT_BOLD_PATH = Path("assets/fonts/Inter/static/Inter_28pt-Bold.ttf")


@dataclass(frozen=True, slots=True)
class SubtitleStyle:
    """Per-agency subtitle styling resolved from ``agency_reel_defaults.settings``.

    Feature 31: the frontend ``/defaults > Subtitles`` panel persists ten
    ``sub*`` fields plus ``automation.autoCaptions`` under
    ``agency_reel_defaults.settings`` (JSONB). The ingest use case maps
    those into renderer-internal keys on
    ``render_template_reel_settings``; ``frame_composition._build_render_data``
    then materialises them into this dataclass which travels with
    ``PropertyRenderData`` to the ffmpeg filter graph.

    Defaults mirror the frontend defaults so a freshly-onboarded agency
    that never opened the panel renders the same look the codebase had
    before feature 31 cabled the wires (outline-only subtitle, bottom
    position, centered, no uppercase, 36-char wrap).
    """

    enabled: bool = True
    font_family: str | None = None
    weight: str = "700"
    color: str = "#ffffff"
    bg_style: str = "outline"
    bg_color: str = "#0f1729"
    bg_opacity: int = 82
    position: str = "bottom"
    alignment: str = "center"
    uppercase: bool = False
    max_chars: int = 36


@dataclass(slots=True)
class PropertyReelTemplate:
    width: int = REEL_WIDTH
    height: int = REEL_HEIGHT
    fps: int = REEL_FPS
    total_duration_seconds: float = REEL_TOTAL_DURATION_SECONDS
    seconds_per_slide: float = REEL_SECONDS_PER_SLIDE
    max_slide_count: int = REEL_MAX_SLIDE_COUNT
    intro_duration_seconds: float = REEL_INTRO_DURATION_SECONDS
    assets_dirname: str = ASSETS_DIRNAME
    ber_icons_dirname: str = REEL_BER_ICONS_DIRNAME
    cover_logo_filename: str = REEL_COVER_LOGO_FILENAME
    background_audio_filename: str = REEL_BACKGROUND_AUDIO_FILENAME
    audio_volume: float = REEL_AUDIO_VOLUME
    ffmpeg_filter_threads: int = REEL_FFMPEG_FILTER_THREADS
    ffmpeg_encoder_threads: int = REEL_FFMPEG_ENCODER_THREADS
    font_path: Path = DEFAULT_REEL_FONT_PATH
    bold_font_path: Path = DEFAULT_REEL_FONT_BOLD_PATH
    subtitle_font_path: Path = REEL_SUBTITLE_FONT_PATH
    subtitle_font_size: int = REEL_SUBTITLE_FONT_SIZE
    ber_icon_scale: float = REEL_BER_ICON_SCALE
    agency_logo_scale: float = REEL_AGENCY_LOGO_SCALE
    include_intro: bool = False
    footer_bottom_offset_px: int = 0


def property_reel_template_to_dict(template: PropertyReelTemplate) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for field_definition in fields(template):
        value = getattr(template, field_definition.name)
        serialized[field_definition.name] = str(value) if isinstance(value, Path) else value
    return serialized


@dataclass(slots=True)
class PropertyReelSlide:
    image_path: Path
    caption: str | None = None


@dataclass(slots=True)
class PreparedReelSlide:
    original_path: Path
    working_path: Path
    caption: str | None = None
    working_width: int = 0
    working_height: int = 0
    motion_mode: str = "diagonal"
    source_width: int | None = None
    source_height: int | None = None


@dataclass(slots=True)
class PreparedReelAssets:
    working_dir: Path
    slides: tuple[PreparedReelSlide, ...]
    cover_background_path: Path
    cover_logo_path: Path | None
    agent_image_path: Path
    ber_icon_path: Path | None
    background_audio_path: Path
    background_audio_candidates: tuple[Path, ...] = field(default_factory=tuple)
    reserve_agency_logo_space: bool = False
    vertical_banner_path: Path | None = None
    vertical_banner_x: int | None = None
    vertical_banner_y: int | None = None


@dataclass(slots=True)
class PropertyRenderData:
    site_id: str
    property_id: int
    slug: str
    title: str
    link: str | None
    property_status: str | None
    selected_image_dir: Path
    selected_image_paths: tuple[Path, ...]
    featured_image_url: str | None
    bedrooms: int | None
    bathrooms: int | None
    ber_rating: str | None
    agent_name: str | None
    agent_photo_url: str | None
    agent_email: str | None
    agent_mobile: str | None
    agent_number: str | None
    price: str | None
    property_type_label: str | None
    property_area_label: str | None
    property_county_label: str | None
    eircode: str | None
    selected_slides: tuple[PropertyReelSlide, ...] = ()
    property_size: str | None = None
    agency_psra: str | None = None
    agency_logo_url: str | None = None
    agency_logo_local_path: Path | None = None
    listing_lifecycle: str | None = None
    banner_text: str | None = None
    price_display_text: str | None = None
    viewing_times: tuple[str, ...] = ()
    accent_text_color: str | None = None
    accent_background_color: str | None = None
    # Feature 29: BrandSettings.secondary_color cascades down to the
    # side_banner vertical ribbon. ``None`` signals "use the hardcoded
    # global fallback" (``preparation._SIDE_BANNER_RIBBON_BACKGROUND``
    # = ``#FECF4D``). The accent_* fields above keep driving the top /
    # bottom panels (reel + poster); the secondary color is only
    # consumed by the rotated ribbon asset.
    side_banner_ribbon_background_color: str | None = None
    # Hotfix 2026-05-15: ``BrandSettings.primary_color`` cascades down to
    # the side_banner top / bottom panels (the "header" and "footer" the
    # user sees over the reel and the poster). ``None`` means "no agency
    # override" — the renderer then falls back to
    # ``accent_background_color`` (the per-property colour from the
    # WordPress webhook), and finally to the hardcoded
    # ``black@0.38`` / ``black@0.46`` defaults inside
    # ``build_overlay_filter`` if neither value is present. Classic
    # layout does NOT use this field; only ``side_banner`` consumes it.
    side_banner_panel_color: str | None = None
    # Feature 31: per-agency subtitle styling resolved from
    # ``agency_reel_defaults.settings`` (JSONB). ``frame_composition._build_render_data``
    # materialises the renderer-internal ``subtitle_*`` keys (set in the
    # ingest use case from the front-end persisted ``sub*`` camelCase
    # values) into this dataclass. ``enabled=False`` skips every subtitle
    # ``drawtext`` in the ffmpeg filter graph.
    subtitle_style: SubtitleStyle = field(default_factory=SubtitleStyle)
    # Feature 36: per-reel subtitle override forwarded from
    # ``reels.subtitles_override``. ``None`` means "no override — let
    # ``compose_subtitle_segments`` build the captions from the slide
    # text as usual". Otherwise an ordered tuple of
    # ``(index, text, in_seconds, out_seconds)`` cues that bypass the
    # autoCaptions composer entirely; the layout still goes through
    # ``compose_subtitle_segments`` (so geometry / styling stays
    # consistent with feature 31) but the input changes from the
    # auto-generated captions to the override cues.
    subtitles_override: (
        tuple[tuple[int, str, float, float], ...] | None
    ) = None


PropertyReelData = PropertyRenderData


__all__ = [
    "DEFAULT_REEL_FONT_BOLD_PATH",
    "DEFAULT_REEL_FONT_PATH",
    "PRIMARY_IMAGE_NAME",
    "PreparedReelAssets",
    "PreparedReelSlide",
    "PropertyReelData",
    "PropertyRenderData",
    "PropertyReelSlide",
    "PropertyReelTemplate",
    "SubtitleStyle",
    "property_reel_template_to_dict",
]
