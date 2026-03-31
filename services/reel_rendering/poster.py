from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from core.errors import PropertyReelError
from services.reel_rendering.filters import (
    build_overlay_filter,
    resolve_agent_image_size,
    resolve_ber_icon_size,
)
from services.reel_rendering.models import PropertyRenderData, PropertyReelTemplate
from services.reel_rendering.runtime import (
    prepare_agent_image,
    resolve_ber_icon_path,
    resolve_ffmpeg_binary,
    select_reel_slides,
)
from services.webhook_transport.site_storage import GENERATED_MEDIA_POSTERS_DIRNAME, GENERATED_MEDIA_ROOT_DIRNAME, safe_site_dirname


def generate_property_poster_from_data(
    base_dir: str | Path,
    property_data: PropertyRenderData,
    *,
    output_path: str | Path | None = None,
    template: PropertyReelTemplate | None = None,
) -> Path:
    workspace_dir = Path(base_dir).expanduser().resolve()
    settings = template or PropertyReelTemplate(width=1080, height=1920)
    ffmpeg_binary = resolve_ffmpeg_binary()
    final_output_path = _resolve_poster_output_path(
        workspace_dir,
        property_data,
        output_path=output_path,
    )
    temp_root = final_output_path.parent / "_staging"
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix="poster_", dir=temp_root))

    try:
        slides = select_reel_slides(
            property_data,
            max_slide_count=1,
            temp_dir=temp_dir,
        )
        if not slides:
            raise PropertyReelError("No primary image is available for poster generation.")

        background_image_path = slides[0].image_path
        agent_image_path = prepare_agent_image(
            workspace_dir,
            property_data,
            settings,
            temp_dir,
        )
        ber_icon_path = resolve_ber_icon_path(
            workspace_dir,
            settings,
            property_data.ber_rating,
        )
        filter_script_path = temp_dir / "filter_complex.txt"
        filter_script_path.write_text(
            _build_poster_filter_script(
                property_data=property_data,
                settings=settings,
                include_ber_icon=ber_icon_path is not None,
            ),
            encoding="utf-8",
        )

        command = [
            ffmpeg_binary,
            "-y",
            "-loop",
            "1",
            "-i",
            str(background_image_path),
            "-loop",
            "1",
            "-i",
            str(agent_image_path),
        ]
        if ber_icon_path is not None:
            command.extend(
                [
                    "-loop",
                    "1",
                    "-i",
                    str(ber_icon_path),
                ]
            )
        command.extend(
            [
                "-filter_complex_script",
                str(filter_script_path),
                "-map",
                "[vout]",
                "-frames:v",
                "1",
                "-q:v",
                "2",
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
        raise PropertyReelError(f"ffmpeg failed to render the property poster.\n{stderr}")
    if not final_output_path.exists() or final_output_path.stat().st_size == 0:
        raise PropertyReelError("The poster output file was not created.")

    return final_output_path


def _resolve_poster_output_path(
    workspace_dir: Path,
    property_data: PropertyRenderData,
    *,
    output_path: str | Path | None,
) -> Path:
    output_dir = (
        Path(output_path).expanduser().resolve().parent
        if output_path is not None
        else workspace_dir
        / GENERATED_MEDIA_ROOT_DIRNAME
        / safe_site_dirname(property_data.site_id)
        / GENERATED_MEDIA_POSTERS_DIRNAME
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    return (
        Path(output_path).expanduser().resolve()
        if output_path is not None
        else output_dir / f"{property_data.slug}-poster.jpg"
    )


def _build_poster_filter_script(
    *,
    property_data: PropertyRenderData,
    settings: PropertyReelTemplate,
    include_ber_icon: bool,
) -> str:
    agent_image_size = resolve_agent_image_size(settings)
    ber_icon_width, ber_icon_height = resolve_ber_icon_size(settings)
    poster_photo_width, poster_photo_height = _resolve_poster_photo_frame(settings)
    filter_parts = [
        (
            f"[0:v]scale=w={settings.width}:h={settings.height}:force_original_aspect_ratio=increase,"
            f"crop={settings.width}:{settings.height},boxblur=36:12,format=yuv420p,setsar=1"
            "[poster_blurred_background]"
        ),
        (
            f"[0:v]scale=w={poster_photo_width}:h={poster_photo_height}:force_original_aspect_ratio=decrease,"
            "format=rgba,setsar=1[poster_photo]"
        ),
        "[poster_blurred_background][poster_photo]overlay=x=(W-w)/2:y=(H-h)/2[poster_base]",
        f"[1:v]scale={agent_image_size}:{agent_image_size},format=rgba[agent_panel_image]",
    ]
    if include_ber_icon:
        filter_parts.append(
            f"[2:v]scale={ber_icon_width}:{ber_icon_height},format=rgba[ber_header_icon]"
        )
    filter_parts.append(
        build_overlay_filter(
            property_data,
            settings,
            cover_caption=None,
            slide_captions=(),
            slide_duration=None,
            video_input_label="poster_base",
            agent_image_label="agent_panel_image",
            ber_icon_label="ber_header_icon" if include_ber_icon else None,
            output_label="vout",
        )
    )
    return ";".join(filter_parts)


def _resolve_poster_photo_frame(settings: PropertyReelTemplate) -> tuple[int, int]:
    horizontal_margin = max(96, round(settings.width * 0.09))
    vertical_margin = max(320, round(settings.height * 0.17))
    return (
        max(320, settings.width - horizontal_margin),
        max(480, settings.height - vertical_margin),
    )


__all__ = ["generate_property_poster_from_data"]
