"""ffmpeg command builders for reel rendering."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from modules.rendering.infrastructure.models import PropertyReelTemplate

STATUS_REEL_RENDER_PROFILE_SUFFIX = "_status_reel"


def build_ffmpeg_reel_command(
    *,
    ffmpeg_binary: str,
    slide_image_paths: list[Path],
    slide_duration: float,
    total_duration: float,
    settings: PropertyReelTemplate,
    logo_path: Path | None,
    agent_image_path: Path,
    ber_icon_path: Path | None,
    background_audio_path: Path,
    filter_script_path: Path,
    output_path: Path,
    audio_fade_start: float,
    audio_fade_duration: float,
) -> list[str]:
    command = [ffmpeg_binary, "-y"]
    if settings.ffmpeg_filter_threads > 0:
        command.extend(["-filter_complex_threads", str(settings.ffmpeg_filter_threads)])

    has_logo_input = settings.include_intro and logo_path is not None
    for slide_image_path in slide_image_paths:
        command.extend(
            [
                "-loop",
                "1",
                "-framerate",
                str(settings.fps),
                "-t",
                f"{slide_duration:.6f}",
                "-i",
                str(slide_image_path),
            ]
        )
    if has_logo_input and logo_path is not None:
        command.extend(
            [
                "-loop",
                "1",
                "-framerate",
                str(settings.fps),
                "-t",
                f"{settings.intro_duration_seconds:.6f}",
                "-i",
                str(logo_path),
            ]
        )
    command.extend(
        [
            "-loop",
            "1",
            "-framerate",
            str(settings.fps),
            "-t",
            f"{total_duration:.6f}",
            "-i",
            str(agent_image_path),
        ]
    )
    if ber_icon_path is not None:
        command.extend(
            [
                "-loop",
                "1",
                "-framerate",
                str(settings.fps),
                "-t",
                f"{total_duration:.6f}",
                "-i",
                str(ber_icon_path),
            ]
        )
    command.extend(["-stream_loop", "-1", "-i", str(background_audio_path)])

    audio_input_index = len(slide_image_paths) + (1 if has_logo_input else 0) + 1
    if ber_icon_path is not None:
        audio_input_index += 1

    command.extend(
        [
            "-filter_complex_script",
            str(filter_script_path),
            "-map",
            "[vout]",
            "-map",
            f"{audio_input_index}:a:0",
            "-r",
            str(settings.fps),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-af",
            (
                f"volume={settings.audio_volume:.3f},"
                f"afade=t=out:st={audio_fade_start:.3f}:d={audio_fade_duration:.3f}"
            ),
            "-c:v",
            "libx264",
        ]
    )
    if settings.ffmpeg_encoder_threads > 0:
        command.extend(["-threads:v", str(settings.ffmpeg_encoder_threads)])
    command.extend(
        ["-pix_fmt", "yuv420p", "-movflags", "+faststart", "-shortest", str(output_path)]
    )
    return command


def build_reel_template_for_render_profile(
    render_profile: str,
    *,
    template: PropertyReelTemplate | None = None,
) -> PropertyReelTemplate:
    base_template = template or PropertyReelTemplate()
    if render_profile.endswith(STATUS_REEL_RENDER_PROFILE_SUFFIX):
        return replace(
            base_template,
            max_slide_count=1,
            intro_duration_seconds=0.0,
            total_duration_seconds=base_template.seconds_per_slide,
            include_intro=False,
        )
    return base_template


def build_segment_render_command(
    *,
    ffmpeg_binary: str,
    input_paths: list[Path],
    duration_seconds: float,
    frame_count: int,
    settings: PropertyReelTemplate,
    filter_text: str,
    output_path: Path,
) -> list[str]:
    command = [ffmpeg_binary, "-y"]
    if settings.ffmpeg_filter_threads > 0:
        command.extend(["-filter_complex_threads", str(settings.ffmpeg_filter_threads)])
    for input_path in input_paths:
        command.extend(
            [
                "-loop",
                "1",
                "-framerate",
                str(settings.fps),
                "-t",
                f"{duration_seconds:.6f}",
                "-i",
                str(input_path),
            ]
        )
    command.extend(
        [
            "-filter_complex",
            filter_text,
            "-map",
            "[vout]",
            "-r",
            str(settings.fps),
            "-frames:v",
            str(frame_count),
            "-an",
            "-c:v",
            "libx264",
        ]
    )
    if settings.ffmpeg_encoder_threads > 0:
        command.extend(["-threads:v", str(settings.ffmpeg_encoder_threads)])
    command.extend(["-pix_fmt", "yuv420p", str(output_path)])
    return command


def build_concat_command(
    *,
    ffmpeg_binary: str,
    concat_list_path: Path,
    settings: PropertyReelTemplate,
    output_path: Path,
) -> list[str]:
    command = [
        ffmpeg_binary,
        "-y",
        "-fflags",
        "+genpts",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list_path),
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        f"fps={settings.fps},setpts=N/({settings.fps}*TB),format=yuv420p",
        "-r",
        str(settings.fps),
        "-c:v",
        "libx264",
    ]
    if settings.ffmpeg_encoder_threads > 0:
        command.extend(["-threads:v", str(settings.ffmpeg_encoder_threads)])
    command.extend(["-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output_path)])
    return command


def build_audio_mux_command(
    *,
    ffmpeg_binary: str,
    video_path: Path,
    background_audio_path: Path,
    settings: PropertyReelTemplate,
    audio_fade_start: float,
    audio_fade_duration: float,
    output_path: Path,
) -> list[str]:
    return [
        ffmpeg_binary,
        "-y",
        "-i",
        str(video_path),
        "-stream_loop",
        "-1",
        "-i",
        str(background_audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-af",
        (
            f"volume={settings.audio_volume:.3f},"
            f"afade=t=out:st={audio_fade_start:.3f}:d={audio_fade_duration:.3f}"
        ),
        "-movflags",
        "+faststart",
        "-shortest",
        str(output_path),
    ]


__all__ = [
    "build_audio_mux_command",
    "build_concat_command",
    "build_ffmpeg_reel_command",
    "build_reel_template_for_render_profile",
    "build_segment_render_command",
]
