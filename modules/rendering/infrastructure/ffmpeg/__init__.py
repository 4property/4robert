"""ffmpeg rendering infrastructure for property reels."""

from modules.rendering.infrastructure.ffmpeg.commands import (
    STATUS_REEL_RENDER_PROFILE_SUFFIX,
    build_audio_mux_command,
    build_concat_command,
    build_ffmpeg_reel_command,
    build_reel_template_for_render_profile,
    build_segment_render_command,
)
from modules.rendering.infrastructure.ffmpeg.filter_graph import (
    build_intro_segment_filter,
    build_motion_progress_expression,
    build_slide_crop_expressions,
    build_slide_segment_filter,
)
from modules.rendering.infrastructure.ffmpeg.render_reel import (
    build_ffmpeg_failure_hint,
    generate_property_reel,
    generate_property_reel_from_data,
    mux_audio_candidates,
    prepare_render_assets,
    render_silent_reel,
    run_ffmpeg_command,
    write_concat_list,
)

__all__ = [
    "STATUS_REEL_RENDER_PROFILE_SUFFIX",
    "build_audio_mux_command",
    "build_concat_command",
    "build_ffmpeg_failure_hint",
    "build_ffmpeg_reel_command",
    "build_intro_segment_filter",
    "build_motion_progress_expression",
    "build_reel_template_for_render_profile",
    "build_segment_render_command",
    "build_slide_crop_expressions",
    "build_slide_segment_filter",
    "generate_property_reel",
    "generate_property_reel_from_data",
    "mux_audio_candidates",
    "prepare_render_assets",
    "render_silent_reel",
    "run_ffmpeg_command",
    "write_concat_list",
]
