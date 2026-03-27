from __future__ import annotations

import subprocess
import shutil
import tempfile
from pathlib import Path

from config import LEGACY_SITE_ID
from core.errors import PropertyReelError
from services.reel_rendering.data import load_property_reel_data
from services.reel_rendering.filters import build_filter_complex
from services.reel_rendering.models import PropertyRenderData, PropertyReelTemplate
from services.reel_rendering.runtime import (
    compute_audio_fade,
    compute_slide_timing,
    prepare_agent_image,
    resolve_ber_icon_path,
    resolve_asset_path,
    resolve_ffmpeg_binary,
    resolve_reel_output_path,
    select_reel_slides,
)


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
    logo_path = resolve_asset_path(
        workspace_dir,
        settings,
        settings.cover_logo_filename,
    )
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

    output_dir = workspace_dir / settings.output_dirname
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
        audio_fade_duration, audio_fade_start = compute_audio_fade(total_duration)
        logo_input_index = len(slide_image_paths)
        agent_image_input_index = len(slide_image_paths) + 1
        ber_icon_input_index = len(slide_image_paths) + 2 if ber_icon_path else None

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
            ),
            encoding="utf-8",
        )

        command = [ffmpeg_binary, "-y"]
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
        audio_input_index = len(slide_image_paths) + (3 if ber_icon_path else 2)
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
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-shortest",
                str(final_output_path),
            ]
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
        raise PropertyReelError(f"ffmpeg failed to render the property reel.\n{stderr}")
    if not final_output_path.exists() or final_output_path.stat().st_size == 0:
        raise PropertyReelError("The reel output file was not created.")

    return final_output_path


def generate_property_reel(
    base_dir: str | Path,
    *,
    site_id: str = LEGACY_SITE_ID,
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


__all__ = ["generate_property_reel", "generate_property_reel_from_data"]

