from __future__ import annotations

from dataclasses import replace
import shutil
import subprocess
import tempfile
from pathlib import Path

from core.errors import PropertyReelError
from core.logging import format_console_block, format_detail_line
from services.reel_rendering.data import load_property_reel_data
from services.reel_rendering.filters import build_filter_complex
from services.reel_rendering.layout import build_overlay_layout
from services.reel_rendering.models import PropertyRenderData, PropertyReelTemplate
from services.reel_rendering.runtime import (
    compute_audio_fade,
    compute_slide_timing,
    prepare_agent_image,
    prepare_cover_logo_image,
    resolve_ber_icon_path,
    resolve_ffmpeg_binary,
    resolve_reel_output_path,
    resolve_asset_path,
    select_reel_slides,
)
from services.webhook_transport.site_storage import resolve_site_storage_layout

_STATUS_REEL_RENDER_PROFILE_SUFFIX = "_status_reel"
import logging

logger = logging.getLogger(__name__)


def _build_ffmpeg_reel_command(
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
        command.extend(
            [
                "-filter_complex_threads",
                str(settings.ffmpeg_filter_threads),
            ]
        )

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
    command.extend(
        [
            "-stream_loop",
            "-1",
            "-i",
            str(background_audio_path),
        ]
    )

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
        command.extend(
            [
                "-threads:v",
                str(settings.ffmpeg_encoder_threads),
            ]
        )
    command.extend(
        [
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "-shortest",
            str(output_path),
        ]
    )
    return command


def build_reel_template_for_render_profile(
    render_profile: str,
    *,
    template: PropertyReelTemplate | None = None,
) -> PropertyReelTemplate:
    base_template = template or PropertyReelTemplate()
    if render_profile.endswith(_STATUS_REEL_RENDER_PROFILE_SUFFIX):
        return replace(
            base_template,
            max_slide_count=1,
            intro_duration_seconds=0.0,
            total_duration_seconds=base_template.seconds_per_slide,
            include_intro=False,
        )
    return base_template


def generate_property_reel_from_data(
    base_dir: str | Path,
    property_data: PropertyRenderData,
    *,
    output_path: str | Path | None = None,
    template: PropertyReelTemplate | None = None,
) -> Path:
    workspace_dir = Path(base_dir).expanduser().resolve()
    settings = template or PropertyReelTemplate()
    ffmpeg_binary = resolve_ffmpeg_binary()
    logo_path = prepare_cover_logo_image(workspace_dir, property_data, settings)
    background_audio_path = resolve_asset_path(
        workspace_dir,
        settings,
        settings.background_audio_filename,
    )
    ber_icon_path = resolve_ber_icon_path(
        workspace_dir,
        settings,
        property_data.ber_rating,
    )
    final_output_path = resolve_reel_output_path(
        workspace_dir,
        property_data,
        settings,
        output_path,
    )

    output_dir = resolve_site_storage_layout(workspace_dir, property_data.site_id).generated_reels_root
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="reel_", dir=output_dir))
    try:
        slides = select_reel_slides(
            property_data,
            max_slide_count=settings.max_slide_count,
            temp_dir=temp_dir,
        )
        property_data.selected_slides = tuple(slides)
        slide_image_paths = [slide.image_path for slide in slides]
        agent_image_path = prepare_agent_image(
            workspace_dir,
            property_data,
            settings,
            temp_dir,
        )
        slide_frames, slide_duration, total_duration = compute_slide_timing(
            settings,
            len(slide_image_paths),
        )
        overlay_layout = build_overlay_layout(
            property_data,
            settings,
            slides=tuple(slides),
            slide_duration=slide_duration,
            has_ber_badge=ber_icon_path is not None,
            cover_caption=slides[0].caption if settings.include_intro and slides else None,
        )
        for warning in overlay_layout.warnings:
            logger.warning(
                format_console_block(
                    "Reel Layout Warning",
                    format_detail_line("Property ID", property_data.property_id),
                    format_detail_line("Slug", property_data.slug),
                    format_detail_line("Block", warning.block),
                    format_detail_line("Code", warning.code),
                    format_detail_line("Reason", warning.message),
                    format_detail_line("Original text", warning.original_text or "<empty>"),
                )
            )
        audio_fade_duration, audio_fade_start = compute_audio_fade(total_duration)
        has_logo_input = settings.include_intro and logo_path is not None
        logo_input_index = len(slide_image_paths) if has_logo_input else None
        agent_image_input_index = len(slide_image_paths) + (1 if has_logo_input else 0)
        ber_icon_input_index = (
            agent_image_input_index + 1
            if ber_icon_path is not None
            else None
        )

        filter_script_path = temp_dir / "filter_complex.txt"
        filter_script_path.write_text(
            build_filter_complex(
                property_data,
                settings,
                slides=slides,
                slide_frames=slide_frames,
                slide_duration=slide_duration,
                logo_input_index=logo_input_index,
                agent_image_input_index=agent_image_input_index,
                ber_icon_input_index=ber_icon_input_index,
                layout=overlay_layout,
            ),
            encoding="utf-8",
        )

        command = _build_ffmpeg_reel_command(
            ffmpeg_binary=ffmpeg_binary,
            slide_image_paths=slide_image_paths,
            slide_duration=slide_duration,
            total_duration=total_duration,
            settings=settings,
            logo_path=logo_path if has_logo_input else None,
            agent_image_path=agent_image_path,
            ber_icon_path=ber_icon_path,
            background_audio_path=background_audio_path,
            filter_script_path=filter_script_path,
            output_path=final_output_path,
            audio_fade_start=audio_fade_start,
            audio_fade_duration=audio_fade_duration,
        )

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise PropertyReelError(
            f"ffmpeg failed to render the property reel.\n{stderr}",
            context={
                "site_id": property_data.site_id,
                "property_id": property_data.property_id,
                "output_path": str(final_output_path),
                "ffmpeg_binary": ffmpeg_binary,
            },
            hint=_build_ffmpeg_failure_hint(stderr),
        )
    if not final_output_path.exists() or final_output_path.stat().st_size == 0:
        raise PropertyReelError(
            "The reel output file was not created.",
            context={
                "site_id": property_data.site_id,
                "property_id": property_data.property_id,
                "output_path": str(final_output_path),
            },
            hint=(
                "Check the ffmpeg stderr above and verify the service user can write to generated_media "
                "on the deployed host."
            ),
        )

    return final_output_path


def generate_property_reel(
    base_dir: str | Path,
    *,
    site_id: str,
    property_id: int | None = None,
    slug: str | None = None,
    output_path: str | Path | None = None,
    template: PropertyReelTemplate | None = None,
) -> Path:
    workspace_dir = Path(base_dir).expanduser().resolve()
    property_data = load_property_reel_data(
        workspace_dir,
        site_id=site_id,
        property_id=property_id,
        slug=slug,
    )
    return generate_property_reel_from_data(
        workspace_dir,
        property_data,
        output_path=output_path,
        template=template,
    )


def _build_ffmpeg_failure_hint(stderr: str) -> str:
    normalized_stderr = stderr.lower()
    if "cannot allocate memory" in normalized_stderr:
        return (
            "The host ran out of memory while ffmpeg was filtering the reel. Reduce "
            "REEL_FFMPEG_FILTER_THREADS / REEL_FFMPEG_ENCODER_THREADS or allocate more memory."
        )
    if "permission denied" in normalized_stderr:
        return (
            "ffmpeg hit a filesystem permission error. Ensure the deployed service user can read assets "
            "and property_media, and write to generated_media."
        )
    if "no such file or directory" in normalized_stderr:
        return (
            "ffmpeg could not read one of the referenced inputs. Verify selected photos, background audio, "
            "fonts, and generated staging files exist on the deployed host."
        )
    return (
        "Inspect the ffmpeg stderr above and verify that all reel assets, fonts, and writable output "
        "directories are present in the deployment."
    )


__all__ = [
    "_build_ffmpeg_reel_command",
    "build_reel_template_for_render_profile",
    "generate_property_reel",
    "generate_property_reel_from_data",
]
