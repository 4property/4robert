"""Property reel asset preparation pipeline (slide normalization etc.).

Migrated from ``services/media/reel_rendering/preparation.py`` during
sub-feature 18c. Builds ``PreparedReelAssets`` from raw slide images by
running ffmpeg single-frame renders for slide normalization, agent image
fit, BER badge, and agency logo.
"""

from __future__ import annotations

import math
import re
import shutil
import subprocess
from pathlib import Path

from shared.errors import PropertyReelError
from modules.rendering.infrastructure.formatting import (
    apply_alpha_to_hex,
    build_fit_inside_rgba_filter,
    build_status_ribbon_text,
    escape_drawtext_text,
    escape_filter_path,
    resolve_agent_image_size,
    resolve_ber_icon_size,
)
from modules.rendering.infrastructure.layout import build_overlay_layout
from modules.rendering.infrastructure.models import (
    PreparedReelAssets,
    PreparedReelSlide,
    PropertyRenderData,
    PropertyReelTemplate,
)
from modules.rendering.infrastructure.runtime import (
    prepare_agent_image,
    prepare_cover_logo_image,
    resolve_background_audio_paths,
    resolve_ber_icon_path,
    resolve_ffmpeg_binary,
    resolve_font_path,
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
    layout_variant: str = "classic",
    music_tracks: tuple[Path, ...] | None = None,
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
        layout_variant=layout_variant,
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
            layout_variant=layout_variant,
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
        music_tracks=music_tracks,
    )

    vertical_banner_path: Path | None = None
    vertical_banner_x: int | None = None
    vertical_banner_y: int | None = None
    # Feature 42: galaxy reuses the side_banner vertical ribbon helper
    # verbatim. Same dimensions, same notch, same ``FOR SALE`` cascade
    # via ``build_status_ribbon_text``, same color cascade
    # (``side_banner_ribbon_background_color`` → hardcoded grey
    # fallback). No code duplication; only the conditional is widened.
    if layout_variant in {"side_banner", "galaxy"}:
        banner_layout = _resolve_vertical_banner_layout(
            settings,
            layout_variant=layout_variant,
        )
        banner_text = build_status_ribbon_text(property_data)
        if banner_text and banner_layout is not None:
            vertical_banner_path = overlays_dir / "vertical_status_banner.png"
            _render_vertical_status_banner(
                ffmpeg_binary=ffmpeg_binary,
                output_path=vertical_banner_path,
                width=banner_layout["width"],
                height=banner_layout["height"],
                notch_height=banner_layout["notch_height"],
                text=banner_text,
                background_hex=(
                    property_data.side_banner_ribbon_background_color
                    or _SIDE_BANNER_RIBBON_BACKGROUND
                ),
                text_hex=property_data.accent_text_color,
                font_path=resolve_font_path(settings.bold_font_path),
                property_data=property_data,
            )
            vertical_banner_x = banner_layout["x"]
            vertical_banner_y = banner_layout["y"]

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
        vertical_banner_path=vertical_banner_path,
        vertical_banner_x=vertical_banner_x,
        vertical_banner_y=vertical_banner_y,
    )


_VERTICAL_BANNER_DEFAULT_BACKGROUND = "#0F172A"
_VERTICAL_BANNER_DEFAULT_TEXT = "#FFFFFF"
# Hotfix 2026-05-15: the brand secondary colour drives the side_banner
# vertical ribbon. When the agency has not configured one yet,
# ``property_data.side_banner_ribbon_background_color`` is ``None`` and
# the renderer paints a neutral grey ribbon instead. The amber
# ``#FECF4D`` from feature 17 was a temporary visual probe; per the
# 2026-05-15 product call the default is now Tailwind's ``gray-400``
# (``#9CA3AF``) so the ribbon reads as "not configured" rather than as
# a deliberate yellow brand colour. The WordPress webhook accent feed
# is intentionally not consulted at this layer any more — colour comes
# from the agency brand row only.
_SIDE_BANNER_RIBBON_BACKGROUND = "#9CA3AF"


def _resolve_vertical_banner_layout(
    settings: PropertyReelTemplate,
    *,
    layout_variant: str = "side_banner",
) -> dict[str, int] | None:
    """Compute width/height/x/y for the rotated status banner.

    The banner follows the reference template: a wide vertical ribbon
    dropping from the top edge near the right side, with a triangular
    point at the bottom. ``height`` includes the transparent notch area.
    Returns ``None`` when the frame is too small to fit a meaningful
    banner so the renderer can skip the asset.
    """
    if layout_variant == "galaxy":
        banner_width = max(120, round(settings.width * 0.148))
        notch_height = max(38, round(settings.height * 0.032))
        # Century 21 polish v3 (2026-05-19): galaxy vertical ribbon
        # shortened ~20% from polish v2 (0.360 -> 0.288, floor 450 ->
        # 360) so the cinta is less dominant against the top photo
        # crop. The side_banner branch below keeps its previous
        # body_height untouched.
        body_height = max(360, round(settings.height * 0.288))
    else:
        banner_width = max(96, round(settings.width * 0.122))
        notch_height = max(28, round(settings.height * 0.025))
        body_height = max(420, round(settings.height * 0.325))
    banner_height = body_height + notch_height
    if banner_width >= settings.width or banner_height >= settings.height:
        return None
    return {
        "width": banner_width,
        "height": banner_height,
        "notch_height": notch_height,
        "x": min(
            settings.width - banner_width,
            max(
                0,
                round(settings.width * (0.787 if layout_variant == "galaxy" else 0.778)),
            ),
        ),
        "y": 0,
    }


def _render_vertical_status_banner(
    *,
    ffmpeg_binary: str,
    output_path: Path,
    width: int,
    height: int,
    notch_height: int,
    text: str,
    background_hex: str | None,
    text_hex: str | None,
    font_path: Path,
    property_data: PropertyRenderData,
) -> None:
    """Render the rotated status banner as a PNG via ffmpeg.

    Creates a horizontal strip (``height x width``) filled with the
    accent background color, draws the status text centered inside the
    rectangular body, masks a triangular notch into the future bottom
    edge, and rotates the image 90° clockwise with ``transpose=1`` so
    the final asset is ``width x height`` with the text reading like
    the reference vertical ribbon.

    Falls back to the brand-style default colors (dark navy background,
    white text) when ``property_data`` does not provide accent colors
    and no fallback was injected upstream.
    """
    background_drawbox = apply_alpha_to_hex(background_hex, alpha=1.0) or apply_alpha_to_hex(
        _VERTICAL_BANNER_DEFAULT_BACKGROUND, alpha=1.0
    )
    text_color = _normalize_drawtext_color(text_hex) or "white"
    font_path_escaped = escape_filter_path(font_path)
    horizontal_width = max(2, height)
    horizontal_height = max(2, width)
    normalized_notch_height = max(0, min(notch_height, height - 2))
    body_width = max(2, horizontal_width - normalized_notch_height)
    center_y = (horizontal_height - 1) / 2
    half_height = horizontal_height / 2
    font_size = max(20, round(horizontal_height * 0.40))
    text_down_shift = max(10, round(width * 0.18))
    escaped_text = escape_drawtext_text(text)
    if normalized_notch_height > 0:
        alpha_mask = (
            "geq="
            "r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
            "a='if(lte(X\\,"
            f"{body_width})+lte(abs(Y-{center_y:.1f})\\,"
            f"{half_height:.1f}*(1-(X-{body_width})/{normalized_notch_height}))"
            "\\,255\\,0)'"
        )
    else:
        alpha_mask = "null"
    horizontal_filter = (
        "format=rgba,"
        f"drawbox=x=0:y=0:w={horizontal_width}:h={horizontal_height}:"
        f"color={background_drawbox}:t=fill,"
        f"drawtext=fontfile='{font_path_escaped}':text='{escaped_text}':"
        f"fontcolor={text_color}:fontsize={font_size}:"
        f"x=({body_width}-text_w)/2+{text_down_shift}:y=(h-text_h)/2:"
        "fix_bounds=1,"
        f"{alpha_mask},"
        "transpose=1,format=rgba"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.stat().st_size > 0:
        return
    command = [
        ffmpeg_binary,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black@0.0:s={horizontal_width}x{horizontal_height}:d=1",
        "-vf",
        horizontal_filter,
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
            f"ffmpeg failed while preparing the side_banner status overlay.\n{stderr}",
            stage="prepare",
            context={
                "site_id": property_data.site_id,
                "property_id": property_data.property_id,
                "output_path": str(output_path),
                "ffmpeg_binary": ffmpeg_binary,
            },
            hint=(
                "Verify ffmpeg is available and the bold reel font is readable on the deployed host."
            ),
        )
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise PropertyReelError(
            "The side_banner status overlay was not written to disk.",
            stage="prepare",
            context={
                "site_id": property_data.site_id,
                "property_id": property_data.property_id,
                "output_path": str(output_path),
            },
            hint=(
                "Check ffmpeg permissions on the working directory and the reel font path."
            ),
        )


def _normalize_drawtext_color(value: str | None) -> str | None:
    """Convert a HEX color into ffmpeg ``drawtext`` notation.

    ``drawtext`` accepts ``0xRRGGBB`` (no alpha) or named colors. Empty
    inputs and unrecognized formats return ``None`` so the caller can
    fall back to a default.
    """
    if value is None:
        return None
    cleaned = value.strip().lstrip("#")
    if not cleaned:
        return None
    if len(cleaned) == 3 and all(ch in "0123456789abcdefABCDEF" for ch in cleaned):
        cleaned = "".join(ch * 2 for ch in cleaned)
    if len(cleaned) != 6 or any(
        ch not in "0123456789abcdefABCDEF" for ch in cleaned
    ):
        return None
    return f"0x{cleaned.lower()}"


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
    layout_variant: str = "classic",
    property_data: PropertyRenderData,
) -> None:
    agent_image_size = resolve_agent_image_size(settings)
    # Feature 42: galaxy reuses the side_banner agent-image preparation
    # (circular crop + fill) so the agent photo reads as a circular
    # avatar inside the rounded footer card.
    use_side_banner_avatar = layout_variant in {"side_banner", "galaxy"}
    filter_text = build_fit_inside_rgba_filter(
        agent_image_size,
        agent_image_size,
        include_setsar=True,
        fill=use_side_banner_avatar,
        circular_mask=use_side_banner_avatar,
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
