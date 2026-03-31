from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from settings.reels import (
    ASSETS_DIRNAME,
    REEL_AUDIO_VOLUME,
    REEL_BACKGROUND_AUDIO_FILENAME,
    REEL_BER_ICONS_DIRNAME,
    REEL_COVER_LOGO_FILENAME,
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
    font_path: Path = DEFAULT_REEL_FONT_PATH
    bold_font_path: Path = DEFAULT_REEL_FONT_BOLD_PATH
    subtitle_font_path: Path = REEL_SUBTITLE_FONT_PATH
    subtitle_font_size: int = REEL_SUBTITLE_FONT_SIZE
    include_intro: bool = True


@dataclass(slots=True)
class PropertyReelSlide:
    image_path: Path
    caption: str | None = None


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
    agency_psra: str | None = None
    agency_logo_url: str | None = None
    listing_lifecycle: str | None = None
    banner_text: str | None = None
    price_display_text: str | None = None


PropertyReelData = PropertyRenderData


__all__ = [
    "DEFAULT_REEL_FONT_BOLD_PATH",
    "DEFAULT_REEL_FONT_PATH",
    "PRIMARY_IMAGE_NAME",
    "PropertyReelData",
    "PropertyRenderData",
    "PropertyReelSlide",
    "PropertyReelTemplate",
]
