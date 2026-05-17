"""Rendering runtime helpers."""

from .assets import (
    download_primary_image,
    download_remote_image,
    normalize_ber_icon_code,
    resolve_agency_music_local_paths,
    resolve_asset_path,
    resolve_background_audio_paths,
    resolve_ber_icon_path,
    resolve_ffmpeg_binary,
    resolve_font_path,
)
from .branding import (
    prepare_agent_image,
    prepare_cover_logo_image,
    should_reserve_agency_logo_space,
)
from .slides import (
    build_local_selected_slides,
    compute_audio_fade,
    compute_segment_timing,
    compute_slide_timing,
    resolve_manifest_output_path,
    resolve_reel_output_path,
    select_reel_images,
    select_reel_slides,
    sorted_image_paths,
)

__all__ = [
    "build_local_selected_slides",
    "compute_audio_fade",
    "compute_segment_timing",
    "compute_slide_timing",
    "download_primary_image",
    "download_remote_image",
    "normalize_ber_icon_code",
    "prepare_agent_image",
    "prepare_cover_logo_image",
    "resolve_agency_music_local_paths",
    "resolve_asset_path",
    "resolve_background_audio_paths",
    "resolve_ber_icon_path",
    "resolve_ffmpeg_binary",
    "resolve_font_path",
    "resolve_manifest_output_path",
    "resolve_reel_output_path",
    "select_reel_images",
    "select_reel_slides",
    "should_reserve_agency_logo_space",
    "sorted_image_paths",
]
