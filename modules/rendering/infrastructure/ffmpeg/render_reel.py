"""Render property reels with ffmpeg."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from modules.rendering.infrastructure.data import load_property_reel_data
from modules.rendering.infrastructure.ffmpeg.commands import (
    build_audio_mux_command,
    build_concat_command,
    build_segment_render_command,
)
from modules.rendering.infrastructure.ffmpeg.filter_graph import build_slide_segment_filter
from modules.rendering.infrastructure.layout import build_overlay_layout
from modules.rendering.infrastructure.models import (
    PreparedReelAssets,
    PropertyRenderData,
    PropertyReelSlide,
    PropertyReelTemplate,
)
from modules.rendering.infrastructure.preparation import prepare_reel_render_assets
from modules.rendering.infrastructure.runtime import (
    compute_audio_fade,
    compute_segment_timing,
    compute_slide_timing,
    resolve_ffmpeg_binary,
    resolve_reel_output_path,
)
from shared.storage.site_layout import resolve_site_storage_layout
from shared.errors import PropertyReelError


# Hotfix 2026-05-15: neutral grey fallback for the side_banner top /
# bottom panels when the agency has not configured a brand primary
# colour. Mirrors the ``_SIDE_BANNER_PANEL_DEFAULT`` in ``poster.py``
# so the cover image and the reel segments paint the same grey. Same
# Tailwind ``gray-700`` shade — the goal is a neutral panel that
# reads as "unconfigured" rather than as a deliberate brand colour.
_SIDE_BANNER_PANEL_DEFAULT = "#374151"
from shared.observability import format_console_block, format_detail_line

logger = logging.getLogger(__name__)


def write_concat_list(segment_paths: list[Path], concat_list_path: Path) -> None:
    concat_list_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for segment_path in segment_paths:
        escaped_path = segment_path.resolve().as_posix().replace("'", "'\\''")
        lines.append(f"file '{escaped_path}'")
    concat_list_path.write_text("\n".join(lines), encoding="utf-8")


def run_ffmpeg_command(
    command: list[str],
    *,
    property_data: PropertyRenderData,
    ffmpeg_binary: str,
    output_path: Path,
    failure_message: str,
    hint: str,
) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise PropertyReelError(
            f"{failure_message}\n{stderr}",
            context={
                "site_id": property_data.site_id,
                "property_id": property_data.property_id,
                "output_path": str(output_path),
                "ffmpeg_binary": ffmpeg_binary,
            },
            hint=hint,
        )
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise PropertyReelError(
            f"The ffmpeg output file was not created: {output_path.name}.",
            context={
                "site_id": property_data.site_id,
                "property_id": property_data.property_id,
                "output_path": str(output_path),
            },
            hint=hint,
        )


def prepare_render_assets(
    *,
    workspace_dir: Path,
    property_data: PropertyRenderData,
    settings: PropertyReelTemplate,
    working_dir: Path,
    prepared_assets: PreparedReelAssets | None,
    layout_variant: str = "classic",
) -> PreparedReelAssets:
    if prepared_assets is not None:
        property_data.selected_slides = tuple(
            PropertyReelSlide(image_path=slide.original_path, caption=slide.caption)
            for slide in prepared_assets.slides
        )
        return prepared_assets

    return prepare_reel_render_assets(
        workspace_dir,
        property_data,
        template=settings,
        working_dir=working_dir,
        layout_variant=layout_variant,
    )


def generate_property_reel_from_data(
    base_dir: str | Path,
    property_data: PropertyRenderData,
    *,
    output_path: str | Path | None = None,
    template: PropertyReelTemplate | None = None,
    prepared_assets: PreparedReelAssets | None = None,
    working_dir: str | Path | None = None,
    layout_variant: str = "classic",
) -> Path:
    workspace_dir = Path(base_dir).expanduser().resolve()
    settings = template or PropertyReelTemplate()
    ffmpeg_binary = resolve_ffmpeg_binary()
    final_output_path = resolve_reel_output_path(
        workspace_dir,
        property_data,
        settings,
        output_path,
    )

    output_dir = resolve_site_storage_layout(
        workspace_dir,
        property_data.site_id,
    ).generated_reels_root
    output_dir.mkdir(parents=True, exist_ok=True)
    created_temp_dir = working_dir is None
    temp_dir = (
        Path(working_dir).expanduser().resolve()
        if working_dir is not None
        else Path(tempfile.mkdtemp(prefix="reel_", dir=output_dir))
    )
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        prepared_assets = prepare_render_assets(
            workspace_dir=workspace_dir,
            property_data=property_data,
            settings=settings,
            working_dir=temp_dir,
            prepared_assets=prepared_assets,
            layout_variant=layout_variant,
        )
        original_slides = tuple(
            PropertyReelSlide(image_path=slide.original_path, caption=slide.caption)
            for slide in prepared_assets.slides
        )
        property_data.selected_slides = original_slides
        segment_frame_counts, segment_durations, total_duration = compute_segment_timing(
            settings,
            len(prepared_assets.slides),
        )
        slide_frames, slide_duration, _ = compute_slide_timing(
            settings,
            len(prepared_assets.slides),
        )
        reserve_agency_logo_space = (
            prepared_assets.reserve_agency_logo_space
            or prepared_assets.cover_logo_path is not None
        )
        overlay_layout = build_overlay_layout(
            property_data,
            settings,
            slides=original_slides,
            slide_duration=slide_duration,
            has_ber_badge=prepared_assets.ber_icon_path is not None,
            has_agency_logo=reserve_agency_logo_space,
            cover_caption=None,
            layout_variant=layout_variant,
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

        silent_reel_path, total_duration = render_silent_reel(
            ffmpeg_binary=ffmpeg_binary,
            property_data=property_data,
            settings=settings,
            prepared_assets=prepared_assets,
            segment_frame_counts=segment_frame_counts,
            segment_durations=segment_durations,
            reserve_agency_logo_space=reserve_agency_logo_space,
            temp_dir=temp_dir,
            layout_variant=layout_variant,
        )
        mux_audio_candidates(
            ffmpeg_binary=ffmpeg_binary,
            property_data=property_data,
            settings=settings,
            prepared_assets=prepared_assets,
            silent_reel_path=silent_reel_path,
            total_duration=total_duration,
            final_output_path=final_output_path,
        )
    finally:
        if created_temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)

    if not final_output_path.exists() or final_output_path.stat().st_size == 0:
        raise PropertyReelError(
            "The reel output file was not created.",
            context={
                "site_id": property_data.site_id,
                "property_id": property_data.property_id,
                "output_path": str(final_output_path),
            },
            hint=(
                "Check the ffmpeg stderr above and verify the service user can write "
                "to generated_media on the deployed host."
            ),
        )
    return final_output_path


def render_silent_reel(
    *,
    ffmpeg_binary: str,
    property_data: PropertyRenderData,
    settings: PropertyReelTemplate,
    prepared_assets: PreparedReelAssets,
    segment_frame_counts: list[int],
    segment_durations: list[float],
    reserve_agency_logo_space: bool,
    temp_dir: Path,
    layout_variant: str = "classic",
) -> tuple[Path, float]:
    # Hotfix 2026-05-15: side_banner panels are painted with the brand
    # primary colour exclusively, falling back to a neutral grey when
    # the agency has not configured one. The WordPress webhook accent
    # feed used to participate here (feature 16) but is no longer
    # consulted — the colour comes from the agency brand row only.
    # Classic layout keeps the historical ``black@0.38`` /
    # ``black@0.46`` defaults from ``build_overlay_filter``.
    # Feature 42: galaxy reuses the same panel-colour cascade as
    # side_banner (brand primary → grey fallback → 0.55 alpha) so the
    # rounded top and bottom cards stay consistent across the two
    # full-bleed variants. Classic keeps the historical black overlay.
    from modules.rendering.infrastructure.formatting import apply_alpha_to_hex
    panel_color = (
        apply_alpha_to_hex(
            property_data.side_banner_panel_color
            or _SIDE_BANNER_PANEL_DEFAULT,
            alpha=0.55,
        )
        if layout_variant in {"side_banner", "galaxy"}
        else None
    )
    text_override = (
        property_data.accent_text_color
        if layout_variant in {"side_banner", "galaxy"}
        else None
    )

    segments_dir = temp_dir / "segments"
    segments_dir.mkdir(parents=True, exist_ok=True)
    segment_paths: list[Path] = []

    for index, (slide, segment_frame_count, segment_duration) in enumerate(
        zip(prepared_assets.slides, segment_frame_counts, segment_durations, strict=True),
        start=1,
    ):
        segment_path = segments_dir / f"segment_{index:02d}.mp4"
        slide_input_paths = [slide.working_path, prepared_assets.agent_image_path]
        if prepared_assets.cover_logo_path is not None:
            slide_input_paths.append(prepared_assets.cover_logo_path)
        if prepared_assets.ber_icon_path is not None:
            slide_input_paths.append(prepared_assets.ber_icon_path)
        vertical_banner_input_index: int | None = None
        if (
            layout_variant in {"side_banner", "galaxy"}
            and prepared_assets.vertical_banner_path is not None
        ):
            vertical_banner_input_index = len(slide_input_paths)
            slide_input_paths.append(prepared_assets.vertical_banner_path)
        run_ffmpeg_command(
            build_segment_render_command(
                ffmpeg_binary=ffmpeg_binary,
                input_paths=slide_input_paths,
                duration_seconds=segment_duration,
                frame_count=segment_frame_count,
                settings=settings,
                filter_text=build_slide_segment_filter(
                    property_data=property_data,
                    settings=settings,
                    slide=slide,
                    slide_frames=segment_frame_count,
                    slide_duration=segment_duration,
                    include_agency_logo=reserve_agency_logo_space,
                    include_ber_icon=prepared_assets.ber_icon_path is not None,
                    render_agency_logo=prepared_assets.cover_logo_path is not None,
                    apply_fade_in=index != 1,
                    layout_variant=layout_variant,
                    top_panel_color=panel_color,
                    bottom_panel_color=panel_color,
                    text_override_color=text_override,
                    vertical_banner_input_index=vertical_banner_input_index,
                    vertical_banner_x=prepared_assets.vertical_banner_x,
                    vertical_banner_y=prepared_assets.vertical_banner_y,
                ),
                output_path=segment_path,
            ),
            property_data=property_data,
            ffmpeg_binary=ffmpeg_binary,
            output_path=segment_path,
            failure_message=(
                "ffmpeg failed while rendering one of the reel slide segments."
            ),
            hint=(
                "A prepared slide segment could not be rendered. Verify the "
                "normalized slide assets exist in the working directory and that "
                "the host can write segment files."
            ),
        )
        segment_paths.append(segment_path)

    concat_list_path = temp_dir / "segments.txt"
    silent_reel_path = temp_dir / "reel_silent.mp4"
    write_concat_list(segment_paths, concat_list_path)
    run_ffmpeg_command(
        build_concat_command(
            ffmpeg_binary=ffmpeg_binary,
            concat_list_path=concat_list_path,
            settings=settings,
            output_path=silent_reel_path,
        ),
        property_data=property_data,
        ffmpeg_binary=ffmpeg_binary,
        output_path=silent_reel_path,
        failure_message="ffmpeg failed while concatenating the prepared reel segments.",
        hint=(
            "One or more staged reel segments could not be concatenated. Verify "
            "the staged segment files are present and readable in the working "
            "directory."
        ),
    )
    return silent_reel_path, sum(segment_durations)


def mux_audio_candidates(
    *,
    ffmpeg_binary: str,
    property_data: PropertyRenderData,
    settings: PropertyReelTemplate,
    prepared_assets: PreparedReelAssets,
    silent_reel_path: Path,
    total_duration: float,
    final_output_path: Path,
) -> None:
    audio_fade_duration, audio_fade_start = compute_audio_fade(total_duration)
    audio_candidates = (
        prepared_assets.background_audio_candidates
        if prepared_assets.background_audio_candidates
        else (prepared_assets.background_audio_path,)
    )
    last_audio_error: PropertyReelError | None = None
    for audio_index, background_audio_path in enumerate(audio_candidates, start=1):
        try:
            run_ffmpeg_command(
                build_audio_mux_command(
                    ffmpeg_binary=ffmpeg_binary,
                    video_path=silent_reel_path,
                    background_audio_path=background_audio_path,
                    settings=settings,
                    audio_fade_start=audio_fade_start,
                    audio_fade_duration=audio_fade_duration,
                    output_path=final_output_path,
                ),
                property_data=property_data,
                ffmpeg_binary=ffmpeg_binary,
                output_path=final_output_path,
                failure_message="ffmpeg failed to render the property reel.",
                hint=(
                    "The staged reel video could not be muxed with background "
                    "audio. Verify the staged silent reel and background music "
                    "assets are both readable."
                ),
            )
            prepared_assets.background_audio_path = background_audio_path
            break
        except PropertyReelError as exc:
            last_audio_error = exc
            if audio_index >= len(audio_candidates):
                raise
            logger.warning(
                "Background audio mux failed for property %s (%s) with %s. "
                "Trying the next track.",
                property_data.property_id,
                property_data.slug,
                background_audio_path.name,
            )
            final_output_path.unlink(missing_ok=True)
    if last_audio_error is not None and not final_output_path.exists():
        raise last_audio_error


def generate_property_reel(
    base_dir: str | Path,
    *,
    site_id: str,
    property_id: int | None = None,
    slug: str | None = None,
    output_path: str | Path | None = None,
    template: PropertyReelTemplate | None = None,
    working_dir: str | Path | None = None,
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
        working_dir=working_dir,
    )


def build_ffmpeg_failure_hint(stderr: str) -> str:
    normalized_stderr = stderr.lower()
    if "no such filter" in normalized_stderr or "filter not found" in normalized_stderr:
        return (
            "ffmpeg could not parse the generated filter_complex graph. Inspect "
            "the generated filter script for unescaped commas or malformed "
            "drawtext / overlay expressions."
        )
    if "concat" in normalized_stderr and "impossible to open" in normalized_stderr:
        return (
            "ffmpeg could not open one of the staged reel segments during "
            "concatenation. Inspect the working directory and verify all segment "
            "files were written before the concat pass."
        )
    if "cannot allocate memory" in normalized_stderr:
        return (
            "The host ran out of memory while ffmpeg was filtering the reel. "
            "Reduce REEL_FFMPEG_FILTER_THREADS / REEL_FFMPEG_ENCODER_THREADS "
            "or allocate more memory."
        )
    if "permission denied" in normalized_stderr:
        return (
            "ffmpeg hit a filesystem permission error. Ensure the deployed "
            "service user can read assets and property_media, and write to "
            "generated_media."
        )
    if "no such file or directory" in normalized_stderr:
        return (
            "ffmpeg could not read one of the referenced inputs. Verify selected "
            "photos, background audio, fonts, and generated staging files exist "
            "on the deployed host."
        )
    return (
        "Inspect the ffmpeg stderr above and verify that all reel assets, fonts, "
        "and writable output directories are present in the deployment."
    )


__all__ = [
    "build_ffmpeg_failure_hint",
    "generate_property_reel",
    "generate_property_reel_from_data",
    "mux_audio_candidates",
    "prepare_render_assets",
    "render_silent_reel",
    "run_ffmpeg_command",
    "write_concat_list",
]
