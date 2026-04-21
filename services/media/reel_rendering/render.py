from __future__ import annotations

from dataclasses import replace
import shutil
import subprocess
import tempfile
import logging
from pathlib import Path

from core.errors import PropertyReelError
from core.logging import format_console_block, format_detail_line
from services.media.reel_rendering.data import load_property_reel_data
from services.media.reel_rendering.filters import build_overlay_filter
from services.media.reel_rendering.layout import build_overlay_layout
from services.media.reel_rendering.models import (
    PreparedReelAssets,
    PreparedReelSlide,
    PropertyRenderData,
    PropertyReelSlide,
    PropertyReelTemplate,
)
from services.media.reel_rendering.preparation import prepare_reel_render_assets
from services.media.reel_rendering.runtime import (
    compute_audio_fade,
    compute_segment_timing,
    compute_slide_timing,
    resolve_ffmpeg_binary,
    resolve_reel_output_path,
)
from services.media.site_storage import resolve_site_storage_layout

_STATUS_REEL_RENDER_PROFILE_SUFFIX = "_status_reel"

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


def _build_segment_render_command(
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
        command.extend(
            [
                "-filter_complex_threads",
                str(settings.ffmpeg_filter_threads),
            ]
        )
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
            str(output_path),
        ]
    )
    return command


def _build_concat_command(
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
        (
            f"fps={settings.fps},"
            f"setpts=N/({settings.fps}*TB),"
            "format=yuv420p"
        ),
        "-r",
        str(settings.fps),
        "-c:v",
        "libx264",
    ]
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
            str(output_path),
        ]
    )
    return command


def _build_audio_mux_command(
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


def _build_intro_segment_filter(
    *,
    property_data: PropertyRenderData,
    settings: PropertyReelTemplate,
    prepared_assets: PreparedReelAssets,
) -> str:
    reserve_agency_logo_space = (
        prepared_assets.reserve_agency_logo_space
        or prepared_assets.cover_logo_path is not None
    )
    cover_caption = prepared_assets.slides[0].caption if prepared_assets.slides else None
    intro_layout = build_overlay_layout(
        property_data,
        settings,
        slides=(),
        slide_duration=settings.intro_duration_seconds,
        has_ber_badge=prepared_assets.ber_icon_path is not None,
        has_agency_logo=reserve_agency_logo_space,
        cover_caption=cover_caption,
    )
    filter_parts = [
        (
            "[0:v]"
            f"crop={settings.width}:{settings.height}:"
            f"x='floor((in_w-{settings.width})/2)':"
            f"y='floor((in_h-{settings.height})/2)',"
            "boxblur=22:4,eq=saturation=0.92:contrast=1.02:brightness=-0.02,"
            "format=yuv420p,setsar=1[intro_background]"
        )
    ]
    current_label = "intro_background"
    next_input_index = 1
    if prepared_assets.cover_logo_path is not None:
        filter_parts.append(f"[{next_input_index}:v]format=rgba[cover_logo]")
        filter_parts.append(
            f"[{current_label}][cover_logo]overlay=x=(W-w)/2:y=(H-h)/2-110[intro_base]"
        )
        current_label = "intro_base"
        next_input_index += 1
    else:
        filter_parts.append(f"[{current_label}]null[intro_base]")
        current_label = "intro_base"

    if intro_layout.agent_image_box is not None and intro_layout.agent_image_box.visible:
        filter_parts.append(f"[{next_input_index}:v]format=rgba[agent_panel_image]")
        next_input_index += 1
    ber_icon_label: str | None = None
    if (
        prepared_assets.ber_icon_path is not None
        and intro_layout.ber_badge_box is not None
        and intro_layout.ber_badge_box.visible
    ):
        ber_icon_label = "ber_header_icon"
        filter_parts.append(f"[{next_input_index}:v]format=rgba[{ber_icon_label}]")

    filter_parts.append(
        build_overlay_filter(
            property_data,
            settings,
            cover_caption=cover_caption,
            slide_captions=(),
            slide_duration=settings.intro_duration_seconds,
            video_input_label=current_label,
            agent_image_label="agent_panel_image",
            ber_icon_label=ber_icon_label,
            output_label="vout",
            layout=intro_layout,
        )
    )
    return ";".join(filter_parts)


def _build_motion_progress_expression(slide_frames: int) -> str:
    if slide_frames <= 1:
        return "0"
    return f"(n/{slide_frames - 1})"


def _build_slide_crop_expressions(
    *,
    slide: PreparedReelSlide,
    settings: PropertyReelTemplate,
    slide_frames: int,
) -> tuple[str, str]:
    travel_x = max(slide.working_width - settings.width, 0)
    travel_y = max(slide.working_height - settings.height, 0)
    progress = _build_motion_progress_expression(slide_frames)
    center_x = str(travel_x // 2)
    center_y = str(travel_y // 2)
    crop_x = f"floor({travel_x}*{progress})" if travel_x > 0 else center_x
    crop_y = center_y
    return crop_x, crop_y


def _build_slide_segment_filter(
    *,
    property_data: PropertyRenderData,
    settings: PropertyReelTemplate,
    slide: PreparedReelSlide,
    slide_frames: int,
    slide_duration: float,
    include_agency_logo: bool,
    include_ber_icon: bool,
    render_agency_logo: bool | None = None,
    apply_fade_in: bool = True,
) -> str:
    if render_agency_logo is None:
        render_agency_logo = include_agency_logo
    segment_settings = replace(
        settings,
        include_intro=False,
        intro_duration_seconds=0.0,
        total_duration_seconds=slide_duration,
    )
    segment_layout = build_overlay_layout(
        property_data,
        segment_settings,
        slides=(PropertyReelSlide(image_path=slide.working_path, caption=slide.caption),),
        slide_duration=slide_duration,
        has_ber_badge=include_ber_icon,
        has_agency_logo=include_agency_logo,
        cover_caption=None,
    )
    crop_x, crop_y = _build_slide_crop_expressions(
        slide=slide,
        settings=settings,
        slide_frames=slide_frames,
    )
    fade_duration = min(0.35, slide_duration / 4.0)
    slide_filters = [
        f"crop={settings.width}:{settings.height}:x='{crop_x}':y='{crop_y}'",
        "eq=saturation=1.03:contrast=1.02:brightness=0.01",
        "format=yuv420p",
        "setsar=1",
        f"trim=duration={slide_duration:.6f}",
        "setpts=PTS-STARTPTS",
    ]
    if apply_fade_in:
        slide_filters.append(f"fade=t=in:st=0:d={fade_duration:.3f}")
    slide_filters.append(
        f"fade=t=out:st={max(slide_duration - fade_duration, 0.0):.3f}:d={fade_duration:.3f}"
    )
    filter_parts = [
        (
            "[0:v]" + ",".join(slide_filters) + "[slide_base]"
        ),
    ]
    next_input_index = 1
    if segment_layout.agent_image_box is not None and segment_layout.agent_image_box.visible:
        filter_parts.append(f"[{next_input_index}:v]format=rgba[agent_panel_image]")
        next_input_index += 1
    logo_image_label: str | None = None
    if (
        render_agency_logo
        and segment_layout.agency_logo_box is not None
        and segment_layout.agency_logo_box.visible
    ):
        logo_image_label = "agency_logo"
        filter_parts.append(f"[{next_input_index}:v]format=rgba[{logo_image_label}]")
        next_input_index += 1
    ber_icon_label: str | None = None
    if (
        include_ber_icon
        and segment_layout.ber_badge_box is not None
        and segment_layout.ber_badge_box.visible
    ):
        ber_icon_label = "ber_header_icon"
        filter_parts.append(f"[{next_input_index}:v]format=rgba[ber_header_icon]")

    filter_parts.append(
        build_overlay_filter(
            property_data,
            segment_settings,
            cover_caption=None,
            slide_captions=(slide.caption,),
            slide_duration=slide_duration,
            video_input_label="slide_base",
            agent_image_label="agent_panel_image",
            logo_image_label=logo_image_label,
            ber_icon_label=ber_icon_label,
            output_label="vout",
            layout=segment_layout,
        )
    )
    return ";".join(filter_parts)


def _write_concat_list(segment_paths: list[Path], concat_list_path: Path) -> None:
    concat_list_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for segment_path in segment_paths:
        escaped_path = segment_path.resolve().as_posix().replace("'", "'\\''")
        lines.append(f"file '{escaped_path}'")
    concat_list_path.write_text("\n".join(lines), encoding="utf-8")


def _run_ffmpeg_command(
    command: list[str],
    *,
    property_data: PropertyRenderData,
    ffmpeg_binary: str,
    output_path: Path,
    failure_message: str,
    hint: str,
) -> None:
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
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


def _prepare_render_assets(
    *,
    workspace_dir: Path,
    property_data: PropertyRenderData,
    settings: PropertyReelTemplate,
    working_dir: Path,
    prepared_assets: PreparedReelAssets | None,
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
    )


def generate_property_reel_from_data(
    base_dir: str | Path,
    property_data: PropertyRenderData,
    *,
    output_path: str | Path | None = None,
    template: PropertyReelTemplate | None = None,
    prepared_assets: PreparedReelAssets | None = None,
    working_dir: str | Path | None = None,
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

    output_dir = resolve_site_storage_layout(workspace_dir, property_data.site_id).generated_reels_root
    output_dir.mkdir(parents=True, exist_ok=True)
    created_temp_dir = working_dir is None
    temp_dir = (
        Path(working_dir).expanduser().resolve()
        if working_dir is not None
        else Path(tempfile.mkdtemp(prefix="reel_", dir=output_dir))
    )
    temp_dir.mkdir(parents=True, exist_ok=True)
    try:
        prepared_assets = _prepare_render_assets(
            workspace_dir=workspace_dir,
            property_data=property_data,
            settings=settings,
            working_dir=temp_dir,
            prepared_assets=prepared_assets,
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

        segments_dir = temp_dir / "segments"
        segments_dir.mkdir(parents=True, exist_ok=True)
        segment_paths: list[Path] = []

        for index, (slide, segment_frame_count, segment_duration) in enumerate(
            zip(prepared_assets.slides, segment_frame_counts, segment_durations, strict=True),
            start=1,
        ):
            segment_path = segments_dir / f"segment_{index:02d}.mp4"
            slide_input_paths = [
                slide.working_path,
                prepared_assets.agent_image_path,
            ]
            if prepared_assets.cover_logo_path is not None:
                slide_input_paths.append(prepared_assets.cover_logo_path)
            if prepared_assets.ber_icon_path is not None:
                slide_input_paths.append(prepared_assets.ber_icon_path)
            _run_ffmpeg_command(
                _build_segment_render_command(
                    ffmpeg_binary=ffmpeg_binary,
                    input_paths=slide_input_paths,
                    duration_seconds=segment_duration,
                    frame_count=segment_frame_count,
                    settings=settings,
                    filter_text=_build_slide_segment_filter(
                        property_data=property_data,
                        settings=settings,
                        slide=slide,
                        slide_frames=segment_frame_count,
                        slide_duration=segment_duration,
                        include_agency_logo=reserve_agency_logo_space,
                        include_ber_icon=prepared_assets.ber_icon_path is not None,
                        render_agency_logo=prepared_assets.cover_logo_path is not None,
                        apply_fade_in=index != 1,
                    ),
                    output_path=segment_path,
                ),
                property_data=property_data,
                ffmpeg_binary=ffmpeg_binary,
                output_path=segment_path,
                failure_message="ffmpeg failed while rendering one of the reel slide segments.",
                hint=(
                    "A prepared slide segment could not be rendered. Verify the normalized slide assets "
                    "exist in the working directory and that the host can write segment files."
                ),
            )
            segment_paths.append(segment_path)

        concat_list_path = temp_dir / "segments.txt"
        silent_reel_path = temp_dir / "reel_silent.mp4"
        _write_concat_list(segment_paths, concat_list_path)
        _run_ffmpeg_command(
            _build_concat_command(
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
                "One or more staged reel segments could not be concatenated. Verify the staged segment "
                "files are present and readable in the working directory."
            ),
        )

        audio_fade_duration, audio_fade_start = compute_audio_fade(total_duration)
        audio_candidates = (
            prepared_assets.background_audio_candidates
            if prepared_assets.background_audio_candidates
            else (prepared_assets.background_audio_path,)
        )
        last_audio_error: PropertyReelError | None = None
        for audio_index, background_audio_path in enumerate(audio_candidates, start=1):
            try:
                _run_ffmpeg_command(
                    _build_audio_mux_command(
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
                        "The staged reel video could not be muxed with background audio. Verify the staged "
                        "silent reel and background music assets are both readable."
                    ),
                )
                prepared_assets.background_audio_path = background_audio_path
                break
            except PropertyReelError as exc:
                last_audio_error = exc
                if audio_index >= len(audio_candidates):
                    raise
                logger.warning(
                    "Background audio mux failed for property %s (%s) with %s. Trying the next track.",
                    property_data.property_id,
                    property_data.slug,
                    background_audio_path.name,
                )
                final_output_path.unlink(missing_ok=True)
        if last_audio_error is not None and not final_output_path.exists():
            raise last_audio_error
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


def _build_ffmpeg_failure_hint(stderr: str) -> str:
    normalized_stderr = stderr.lower()
    if "no such filter" in normalized_stderr or "filter not found" in normalized_stderr:
        return (
            "ffmpeg could not parse the generated filter_complex graph. Inspect the generated filter "
            "script for unescaped commas or malformed drawtext / overlay expressions."
        )
    if "concat" in normalized_stderr and "impossible to open" in normalized_stderr:
        return (
            "ffmpeg could not open one of the staged reel segments during concatenation. Inspect the "
            "working directory and verify all segment files were written before the concat pass."
        )
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
    "_build_audio_mux_command",
    "_build_concat_command",
    "_build_segment_render_command",
    "_build_ffmpeg_reel_command",
    "build_reel_template_for_render_profile",
    "generate_property_reel",
    "generate_property_reel_from_data",
]
