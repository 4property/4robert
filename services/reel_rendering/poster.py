from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from core.errors import PropertyReelError
from services.reel_rendering.filters import build_overlay_filter
from services.reel_rendering.formatting import resolve_agent_image_size, resolve_ber_icon_size
from services.reel_rendering.layout import BoxLayout, OverlayLayout, build_overlay_layout
from services.reel_rendering.models import PreparedReelSlide, PropertyRenderData, PropertyReelTemplate
from services.reel_rendering.preparation import prepare_reel_render_assets
from services.reel_rendering.runtime import resolve_ffmpeg_binary
from services.webhook_transport.site_storage import (
    GENERATED_MEDIA_POSTERS_DIRNAME,
    GENERATED_MEDIA_ROOT_DIRNAME,
    safe_site_dirname,
)
from settings.posters import (
    POSTER_BACKGROUND_BLUR_POWER,
    POSTER_BACKGROUND_BLUR_RADIUS,
    POSTER_HEIGHT,
    POSTER_WIDTH,
)


def generate_property_poster_from_data(
    base_dir: str | Path,
    property_data: PropertyRenderData,
    *,
    output_path: str | Path | None = None,
    template: PropertyReelTemplate | None = None,
) -> Path:
    workspace_dir = Path(base_dir).expanduser().resolve()
    settings = template or PropertyReelTemplate(
        width=POSTER_WIDTH,
        height=POSTER_HEIGHT,
        max_slide_count=1,
        include_intro=False,
        intro_duration_seconds=0.0,
    )
    ffmpeg_binary = resolve_ffmpeg_binary()
    final_output_path = _resolve_poster_output_path(
        workspace_dir,
        property_data,
        output_path=output_path,
    )
    temp_root = final_output_path.parent / "_staging"
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_dir = temp_root / f"poster_{uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        prepared_assets = prepare_reel_render_assets(
            workspace_dir,
            property_data,
            template=settings,
            working_dir=temp_dir / "prepared",
        )
        if not prepared_assets.slides:
            raise PropertyReelError("No primary image is available for poster generation.")

        background_image_path = _resolve_poster_source_path(prepared_assets.slides[0])
        agency_logo_input_index = 2 if prepared_assets.cover_logo_path is not None else None
        ber_icon_input_index = None
        next_input_index = 2
        if prepared_assets.cover_logo_path is not None:
            next_input_index += 1
        if prepared_assets.ber_icon_path is not None:
            ber_icon_input_index = next_input_index

        filter_script_path = temp_dir / "filter_complex.txt"
        filter_script_path.write_text(
            _build_poster_filter_script(
                property_data=property_data,
                settings=settings,
                include_agency_logo=(
                    prepared_assets.reserve_agency_logo_space
                    or prepared_assets.cover_logo_path is not None
                ),
                include_ber_icon=prepared_assets.ber_icon_path is not None,
                agent_input_index=1,
                agency_logo_input_index=agency_logo_input_index,
                ber_icon_input_index=ber_icon_input_index,
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
            str(prepared_assets.agent_image_path),
        ]
        if prepared_assets.cover_logo_path is not None:
            command.extend(
                [
                    "-loop",
                    "1",
                    "-i",
                    str(prepared_assets.cover_logo_path),
                ]
            )
        if prepared_assets.ber_icon_path is not None:
            command.extend(
                [
                    "-loop",
                    "1",
                    "-i",
                    str(prepared_assets.ber_icon_path),
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
        raise PropertyReelError(
            f"ffmpeg failed to render the property poster.\n{stderr}",
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
            "The poster output file was not created.",
            context={
                "site_id": property_data.site_id,
                "property_id": property_data.property_id,
                "output_path": str(final_output_path),
            },
            hint=(
                "Check the ffmpeg stderr above and verify the service user can write to the poster "
                "output directory on the deployed host."
            ),
        )

    return final_output_path


def resolve_property_poster_output_path(
    base_dir: str | Path,
    *,
    site_id: str,
    slug: str,
) -> Path:
    workspace_dir = Path(base_dir).expanduser().resolve()
    return _resolve_default_poster_dir(
        workspace_dir,
        site_id=site_id,
    ) / f"{slug}-poster.jpg"


def _resolve_poster_output_path(
    workspace_dir: Path,
    property_data: PropertyRenderData,
    *,
    output_path: str | Path | None,
) -> Path:
    output_dir = (
        Path(output_path).expanduser().resolve().parent
        if output_path is not None
        else _resolve_default_poster_dir(
            workspace_dir,
            site_id=property_data.site_id,
        )
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    return (
        Path(output_path).expanduser().resolve()
        if output_path is not None
        else resolve_property_poster_output_path(
            workspace_dir,
            site_id=property_data.site_id,
            slug=property_data.slug,
        )
    )


def _resolve_default_poster_dir(
    workspace_dir: Path,
    *,
    site_id: str,
) -> Path:
    return (
        workspace_dir
        / GENERATED_MEDIA_ROOT_DIRNAME
        / safe_site_dirname(site_id)
        / GENERATED_MEDIA_POSTERS_DIRNAME
    )


def _resolve_poster_source_path(prepared_slide: PreparedReelSlide) -> Path:
    original_path = prepared_slide.original_path
    if original_path.exists() and original_path.stat().st_size > 0:
        return original_path
    return prepared_slide.working_path


def _build_poster_filter_script(
    *,
    property_data: PropertyRenderData,
    settings: PropertyReelTemplate,
    include_agency_logo: bool,
    include_ber_icon: bool,
    agent_input_index: int,
    agency_logo_input_index: int | None,
    ber_icon_input_index: int | None,
) -> str:
    overlay_layout = build_overlay_layout(
        property_data,
        settings,
        slides=(),
        slide_duration=None,
        has_ber_badge=include_ber_icon,
        has_agency_logo=include_agency_logo,
        cover_caption=None,
    )
    photo_box = _resolve_poster_photo_box(settings, overlay_layout)
    agent_image_size = (
        overlay_layout.agent_image_box.width
        if overlay_layout.agent_image_box is not None and overlay_layout.agent_image_box.visible
        else resolve_agent_image_size(settings)
    )
    ber_icon_width, ber_icon_height = (
        (
            overlay_layout.ber_badge_box.width,
            overlay_layout.ber_badge_box.height,
        )
        if overlay_layout.ber_badge_box is not None and overlay_layout.ber_badge_box.visible
        else resolve_ber_icon_size(settings)
    )

    filter_parts = [
        (
            f"[0:v]scale=w={settings.width}:h={settings.height}:force_original_aspect_ratio=increase,"
            f"crop={settings.width}:{settings.height},boxblur={POSTER_BACKGROUND_BLUR_RADIUS}:{POSTER_BACKGROUND_BLUR_POWER},"
            "format=yuv420p,setsar=1[poster_blurred_background]"
        ),
        (
            f"[0:v]scale=w={photo_box.width}:h={photo_box.height}:force_original_aspect_ratio=decrease,"
            "format=rgba,setsar=1[poster_photo]"
        ),
        (
            "[poster_blurred_background][poster_photo]"
            f"overlay=x={photo_box.x}+floor(({photo_box.width}-w)/2):"
            f"y={photo_box.y}+floor(({photo_box.height}-h)/2)[poster_base]"
        ),
    ]
    if overlay_layout.agent_image_box is not None and overlay_layout.agent_image_box.visible:
        filter_parts.append(
            f"[{agent_input_index}:v]scale={agent_image_size}:{agent_image_size},format=rgba[agent_panel_image]"
        )
    if (
        agency_logo_input_index is not None
        and overlay_layout.agency_logo_box is not None
        and overlay_layout.agency_logo_box.visible
    ):
        filter_parts.append(
            (
                f"[{agency_logo_input_index}:v]"
                f"scale=w={overlay_layout.agency_logo_box.width}:h={overlay_layout.agency_logo_box.height}:force_original_aspect_ratio=decrease,"
                f"pad={overlay_layout.agency_logo_box.width}:{overlay_layout.agency_logo_box.height}:(ow-iw)/2:(oh-ih)/2:color=black@0.0,"
                "format=rgba[agency_logo]"
            )
        )
    if (
        include_ber_icon
        and ber_icon_input_index is not None
        and overlay_layout.ber_badge_box is not None
        and overlay_layout.ber_badge_box.visible
    ):
        filter_parts.append(
            f"[{ber_icon_input_index}:v]scale={ber_icon_width}:{ber_icon_height},format=rgba[ber_header_icon]"
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
            logo_image_label=(
                "agency_logo"
                if agency_logo_input_index is not None
                and overlay_layout.agency_logo_box is not None
                and overlay_layout.agency_logo_box.visible
                else None
            ),
            ber_icon_label=(
                "ber_header_icon"
                if include_ber_icon
                and ber_icon_input_index is not None
                and overlay_layout.ber_badge_box is not None
                and overlay_layout.ber_badge_box.visible
                else None
            ),
            output_label="vout",
            layout=overlay_layout,
        )
    )
    return ";".join(filter_parts)


def _resolve_poster_photo_box(
    settings: PropertyReelTemplate,
    _overlay_layout: OverlayLayout,
) -> BoxLayout:
    return BoxLayout(
        visible=True,
        x=0,
        y=0,
        width=max(2, settings.width),
        height=max(2, settings.height),
    )


def _build_ffmpeg_failure_hint(stderr: str) -> str:
    normalized_stderr = stderr.lower()
    if "cannot allocate memory" in normalized_stderr:
        return "The host ran out of memory while ffmpeg was rendering the poster."
    if "permission denied" in normalized_stderr:
        return "ffmpeg hit a filesystem permission error while writing or reading poster assets."
    if "no such file or directory" in normalized_stderr:
        return "ffmpeg could not read one of the poster inputs. Verify the selected photo and optional overlay assets exist."
    return "Inspect the ffmpeg stderr above and verify poster inputs and output permissions on the deployed host."


__all__ = ["generate_property_poster_from_data", "resolve_property_poster_output_path"]
