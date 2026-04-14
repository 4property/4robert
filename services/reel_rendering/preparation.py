from __future__ import annotations

import math
import re
import shutil
import subprocess
from pathlib import Path

from core.errors import PropertyReelError
from services.reel_rendering.formatting import resolve_agent_image_size, resolve_ber_icon_size
from services.reel_rendering.layout import build_overlay_layout
from services.reel_rendering.models import (
    PreparedReelAssets,
    PreparedReelSlide,
    PropertyRenderData,
    PropertyReelTemplate,
)
from services.reel_rendering.runtime import (
    prepare_agent_image,
    prepare_cover_logo_image,
    resolve_background_audio_paths,
    resolve_ber_icon_path,
    resolve_ffmpeg_binary,
    select_reel_slides,
    should_reserve_agency_logo_space,
)

_PNG_IMAGE_CODEC = "png"
_SLIDE_WORKING_BASE_SCALE = 1.24
_SLIDE_MOTION_MIN_PIXELS_PER_FRAME = 2.0


def prepare_reel_render_assets(
    base_dir: str | Path,
    property_data: PropertyRenderData,
    *,
    template: PropertyReelTemplate | None = None,
    working_dir: str | Path,
) -> PreparedReelAssets:
    workspace_dir = Path(base_dir).expanduser().resolve()
    settings = template or PropertyReelTemplate()
    ffmpeg_binary = resolve_ffmpeg_binary()
    prepared_root = Path(working_dir).expanduser().resolve()
    slides_dir = prepared_root / "slides"
    overlays_dir = prepared_root / "overlays"
    slides_dir.mkdir(parents=True, exist_ok=True)
    overlays_dir.mkdir(parents=True, exist_ok=True)

    slides = select_reel_slides(
        property_data,
        max_slide_count=settings.max_slide_count,
        temp_dir=prepared_root,
    )
    property_data.selected_slides = tuple(slides)
    slide_working_width, slide_working_height = _resolve_slide_working_size(settings)

    prepared_slides: list[PreparedReelSlide] = []
    for index, slide in enumerate(slides, start=1):
        working_path = slides_dir / f"slide_{index:02d}.png"
        source_width, source_height = _probe_image_dimensions(
            ffmpeg_binary=ffmpeg_binary,
            input_path=slide.image_path,
        )
        _normalize_slide_image(
            ffmpeg_binary=ffmpeg_binary,
            input_path=slide.image_path,
            output_path=working_path,
            working_width=slide_working_width,
            working_height=slide_working_height,
            property_data=property_data,
        )
        prepared_slides.append(
            PreparedReelSlide(
                original_path=slide.image_path,
                working_path=working_path,
                caption=slide.caption,
                working_width=slide_working_width,
                working_height=slide_working_height,
                motion_mode=_resolve_motion_mode(
                    source_width=source_width,
                    source_height=source_height,
                    settings=settings,
                ),
                source_width=source_width,
                source_height=source_height,
            )
        )

    if not prepared_slides:
        raise PropertyReelError(
            "No prepared slide assets were generated for the reel.",
            stage="prepare",
            context={
                "site_id": property_data.site_id,
                "property_id": property_data.property_id,
                "working_dir": str(prepared_root),
            },
            hint=(
                "Verify the selected_photos directory contains at least one readable image before "
                "starting the render."
            ),
        )

    agent_source_path = prepare_agent_image(
        workspace_dir,
        property_data,
        settings,
        prepared_root,
    )
    prepared_agent_path = overlays_dir / "agent_panel.png"
    _normalize_agent_image(
        ffmpeg_binary=ffmpeg_binary,
        input_path=agent_source_path,
        output_path=prepared_agent_path,
        settings=settings,
        property_data=property_data,
    )

    prepared_ber_icon_path: Path | None = None
    ber_icon_path = resolve_ber_icon_path(
        workspace_dir,
        settings,
        property_data.ber_rating,
    )
    if ber_icon_path is not None:
        prepared_ber_icon_path = overlays_dir / "ber_badge.png"
        _normalize_ber_icon(
            ffmpeg_binary=ffmpeg_binary,
            input_path=ber_icon_path,
            output_path=prepared_ber_icon_path,
            settings=settings,
            property_data=property_data,
        )

    prepared_cover_logo_path: Path | None = None
    cover_logo_path = prepare_cover_logo_image(workspace_dir, property_data, settings)
    reserve_agency_logo_space = should_reserve_agency_logo_space(
        property_data,
        cover_logo_path=cover_logo_path,
    )
    if reserve_agency_logo_space:
        overlay_layout = build_overlay_layout(
            property_data,
            settings,
            slides=property_data.selected_slides,
            slide_duration=settings.seconds_per_slide,
            has_ber_badge=prepared_ber_icon_path is not None,
            has_agency_logo=reserve_agency_logo_space,
            cover_caption=None,
        )
        if (
            cover_logo_path is not None
            and overlay_layout.agency_logo_box is not None
            and overlay_layout.agency_logo_box.visible
        ):
            prepared_cover_logo_path = overlays_dir / "agency_logo.png"
            _normalize_agency_logo(
                ffmpeg_binary=ffmpeg_binary,
                input_path=cover_logo_path,
                output_path=prepared_cover_logo_path,
                logo_width=overlay_layout.agency_logo_box.width,
                logo_height=overlay_layout.agency_logo_box.height,
                property_data=property_data,
            )

    background_audio_candidates = resolve_background_audio_paths(
        workspace_dir,
        settings,
        shuffle_candidates=True,
    )

    return PreparedReelAssets(
        working_dir=prepared_root,
        slides=tuple(prepared_slides),
        cover_background_path=prepared_slides[0].working_path,
        cover_logo_path=prepared_cover_logo_path,
        agent_image_path=prepared_agent_path,
        ber_icon_path=prepared_ber_icon_path,
        background_audio_path=background_audio_candidates[0],
        background_audio_candidates=background_audio_candidates,
        reserve_agency_logo_space=reserve_agency_logo_space,
    )


def _normalize_slide_image(
    *,
    ffmpeg_binary: str,
    input_path: Path,
    output_path: Path,
    working_width: int,
    working_height: int,
    property_data: PropertyRenderData,
) -> None:
    target_aspect_ratio = working_width / working_height
    filter_text = (
        f"scale=w='if(gte(iw/ih,{target_aspect_ratio:.8f}),-2,{working_width})':"
        f"h='if(gte(iw/ih,{target_aspect_ratio:.8f}),{working_height},-2)':"
        "eval=init:flags=lanczos,"
        f"crop={working_width}:{working_height},setsar=1,format=rgb24"
    )
    _render_single_frame(
        ffmpeg_binary=ffmpeg_binary,
        input_path=input_path,
        output_path=output_path,
        filter_text=filter_text,
        property_data=property_data,
        stage="prepare",
        hint=(
            "A selected property image could not be normalized for rendering. Verify the file is a "
            "readable image and not a partial download."
        ),
    )


def _resolve_slide_working_size(settings: PropertyReelTemplate) -> tuple[int, int]:
    slide_frames = max(1, round(settings.seconds_per_slide * settings.fps))
    minimum_scale = max(
        _SLIDE_WORKING_BASE_SCALE,
        (settings.width + (slide_frames * _SLIDE_MOTION_MIN_PIXELS_PER_FRAME)) / settings.width,
        (settings.height + (slide_frames * _SLIDE_MOTION_MIN_PIXELS_PER_FRAME)) / settings.height,
    )
    return (
        _round_even(settings.width * minimum_scale),
        _round_even(settings.height * minimum_scale),
    )


def _resolve_motion_mode(
    *,
    source_width: int | None,
    source_height: int | None,
    settings: PropertyReelTemplate,
) -> str:
    return "horizontal"


def _probe_image_dimensions(
    *,
    ffmpeg_binary: str,
    input_path: Path,
) -> tuple[int | None, int | None]:
    ffprobe_binary = _resolve_ffprobe_binary(ffmpeg_binary)
    if ffprobe_binary is not None:
        completed = subprocess.run(
            [
                ffprobe_binary,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=p=0:s=x",
                str(input_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            match = re.search(r"^\s*(\d+)x(\d+)\s*$", completed.stdout)
            if match is not None:
                return int(match.group(1)), int(match.group(2))

    completed = subprocess.run(
        [ffmpeg_binary, "-hide_banner", "-i", str(input_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    match = re.search(r"Video:.*?,.*?,\s*(\d+)x(\d+)\b", completed.stderr)
    if match is None:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _resolve_ffprobe_binary(ffmpeg_binary: str) -> str | None:
    ffmpeg_path = Path(ffmpeg_binary)
    candidate_names = ["ffprobe.exe", "ffprobe"] if ffmpeg_path.suffix.lower() == ".exe" else ["ffprobe"]
    for candidate_name in candidate_names:
        candidate_path = ffmpeg_path.with_name(candidate_name)
        if candidate_path.exists():
            return str(candidate_path)
    ffprobe_binary = shutil.which("ffprobe")
    if ffprobe_binary:
        return ffprobe_binary
    return None


def _round_even(value: float) -> int:
    rounded = max(2, int(math.ceil(value)))
    if rounded % 2 == 1:
        rounded += 1
    return rounded


def _normalize_agency_logo(
    *,
    ffmpeg_binary: str,
    input_path: Path,
    output_path: Path,
    logo_width: int,
    logo_height: int,
    property_data: PropertyRenderData,
) -> None:
    filter_text = (
        f"scale=w={logo_width}:h={logo_height}:force_original_aspect_ratio=decrease,"
        f"pad={logo_width}:{logo_height}:(ow-iw)/2:(oh-ih)/2:color=black@0.0,"
        "setsar=1,format=rgba"
    )
    _render_single_frame(
        ffmpeg_binary=ffmpeg_binary,
        input_path=input_path,
        output_path=output_path,
        filter_text=filter_text,
        property_data=property_data,
        stage="prepare",
        hint=(
            "The agency logo could not be normalized for the footer panel. Verify the remote logo is "
            "a valid PNG/JPG image."
        ),
    )


def _normalize_agent_image(
    *,
    ffmpeg_binary: str,
    input_path: Path,
    output_path: Path,
    settings: PropertyReelTemplate,
    property_data: PropertyRenderData,
) -> None:
    agent_image_size = resolve_agent_image_size(settings)
    filter_text = (
        f"scale=w={agent_image_size}:h={agent_image_size}:force_original_aspect_ratio=increase,"
        f"crop={agent_image_size}:{agent_image_size},setsar=1,format=rgba"
    )
    _render_single_frame(
        ffmpeg_binary=ffmpeg_binary,
        input_path=input_path,
        output_path=output_path,
        filter_text=filter_text,
        property_data=property_data,
        stage="prepare",
        hint=(
            "The agent image fallback could not be normalized. Verify the agent photo or agency logo "
            "is readable on the deployed host."
        ),
    )


def _normalize_ber_icon(
    *,
    ffmpeg_binary: str,
    input_path: Path,
    output_path: Path,
    settings: PropertyReelTemplate,
    property_data: PropertyRenderData,
) -> None:
    icon_width, icon_height = resolve_ber_icon_size(settings)
    filter_text = (
        f"scale=w={icon_width}:h={icon_height}:force_original_aspect_ratio=decrease,"
        f"pad={icon_width}:{icon_height}:(ow-iw)/2:(oh-ih)/2:color=black@0.0,"
        "setsar=1,format=rgba"
    )
    _render_single_frame(
        ffmpeg_binary=ffmpeg_binary,
        input_path=input_path,
        output_path=output_path,
        filter_text=filter_text,
        property_data=property_data,
        stage="prepare",
        hint=(
            "The BER badge could not be normalized. Verify the BER icon exists in assets/ber-icons "
            "and is readable."
        ),
    )


def _render_single_frame(
    *,
    ffmpeg_binary: str,
    input_path: Path,
    output_path: Path,
    filter_text: str,
    property_data: PropertyRenderData,
    stage: str,
    hint: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.stat().st_size > 0:
        return

    command = [
        ffmpeg_binary,
        "-y",
        "-i",
        str(input_path),
        "-vf",
        filter_text,
        "-frames:v",
        "1",
        "-c:v",
        _PNG_IMAGE_CODEC,
        str(output_path),
    ]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise PropertyReelError(
            f"ffmpeg failed while preparing a reel asset.\n{stderr}",
            stage=stage,
            context={
                "site_id": property_data.site_id,
                "property_id": property_data.property_id,
                "input_path": str(input_path),
                "output_path": str(output_path),
                "ffmpeg_binary": ffmpeg_binary,
            },
            hint=hint,
        )
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise PropertyReelError(
            "A prepared reel asset was not written to disk.",
            stage=stage,
            context={
                "site_id": property_data.site_id,
                "property_id": property_data.property_id,
                "input_path": str(input_path),
                "output_path": str(output_path),
            },
            hint=(
                "Verify the render working directory is writable and that ffmpeg can decode the "
                "source image."
            ),
        )


__all__ = ["prepare_reel_render_assets"]
