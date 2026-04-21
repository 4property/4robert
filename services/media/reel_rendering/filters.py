from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from services.media.reel_rendering.formatting import (
    escape_drawtext_text,
    escape_filter_path,
    resolve_agent_image_size,
    resolve_ber_icon_size,
    resolve_text_color,
)
from services.media.reel_rendering.layout import OverlayLayout, build_overlay_layout
from services.media.reel_rendering.models import PropertyReelData, PropertyReelSlide, PropertyReelTemplate
from services.media.reel_rendering.runtime import resolve_font_path


def _build_drawtext_enable_expression(start_time: float, end_time: float) -> str:
    return f"enable='between(t\\,{start_time:.3f}\\,{end_time:.3f})'"


def build_overlay_filter(
    property_data: PropertyReelData,
    settings: PropertyReelTemplate,
    *,
    cover_caption: str | None = None,
    slide_captions: Sequence[str | None] = (),
    slide_duration: float | None = None,
    video_input_label: str = "video_base",
    agent_image_label: str = "agent_panel_image",
    logo_image_label: str | None = None,
    has_agency_logo: bool | None = None,
    ber_icon_label: str | None = None,
    output_label: str = "vout",
    layout: OverlayLayout | None = None,
) -> str:
    active_layout = layout or build_overlay_layout(
        property_data,
        settings,
        slides=tuple(
            PropertyReelSlide(image_path=Path(f"synthetic-slide-{index}.jpg"), caption=caption)
            for index, caption in enumerate(slide_captions, start=1)
        ),
        slide_duration=slide_duration,
        has_ber_badge=ber_icon_label is not None,
        has_agency_logo=(
            logo_image_label is not None if has_agency_logo is None else has_agency_logo
        ),
        cover_caption=cover_caption,
    )
    font_path = escape_filter_path(resolve_font_path(settings.font_path))
    bold_font_path = escape_filter_path(resolve_font_path(settings.bold_font_path))
    subtitle_font_path = escape_filter_path(resolve_font_path(settings.subtitle_font_path))

    text_filters: list[str] = []
    if active_layout.bottom_panel is not None and active_layout.bottom_panel.visible:
        text_filters.append(
            (
                f"drawbox=x={active_layout.bottom_panel.x}:y={active_layout.bottom_panel.y}:"
                f"w={active_layout.bottom_panel.width}:h={active_layout.bottom_panel.height}:"
                "color=black@0.46:t=fill"
            )
        )
    if active_layout.agent_image_box is not None and active_layout.agent_image_box.visible:
        text_filters.append(
            (
                f"drawbox=x={active_layout.agent_image_box.x - 6}:y={active_layout.agent_image_box.y - 6}:"
                f"w={active_layout.agent_image_box.width + 12}:h={active_layout.agent_image_box.height + 12}:"
                "color=white@0.14:t=fill"
            )
        )
    if active_layout.top_panel is not None and active_layout.top_panel.visible:
        text_filters.append(
            (
                f"drawbox=x={active_layout.top_panel.x}:y={active_layout.top_panel.y}:"
                f"w={active_layout.top_panel.width}:h={active_layout.top_panel.height}:"
                "color=black@0.38:t=fill"
            )
        )

    for block in active_layout.text_blocks:
        if not block.visible:
            continue
        font_file = bold_font_path if block.block in {"status", "price", "agent_name"} else font_path
        for index, line in enumerate(block.lines):
            text_filters.append(
                "drawtext="
                f"fontfile='{font_file}':"
                f"text='{escape_drawtext_text(line)}':"
                f"fontcolor={resolve_text_color(block.block)}:fontsize={block.font_size}:"
                f"x={block.x}:y={block.y + index * block.line_gap}:"
                "fix_bounds=1"
            )

    for segment in active_layout.subtitle_segments:
        enable = _build_drawtext_enable_expression(
            segment.start_time,
            segment.end_time,
        )
        for index, line in enumerate(segment.lines):
            text_filters.append(
                "drawtext="
                f"fontfile='{subtitle_font_path}':"
                f"text='{escape_drawtext_text(line)}':"
                f"fontcolor={resolve_text_color(segment.block)}:"
                f"fontsize={segment.font_size}:"
                f"x={segment.x}+max(({segment.max_width}-text_w)/2\\,0):"
                f"y={segment.y + index * segment.line_gap}:"
                f"borderw=2:bordercolor=black@0.80:"
                f"shadowx=0:shadowy=3:shadowcolor=black@0.75:"
                f"text_shaping=1:"
                f"fix_bounds=1:"
                f"{enable}"
            )

    overlay_base_label = "video_with_property_panels"
    if text_filters:
        filters = [f"[{video_input_label}]{','.join(text_filters)}[{overlay_base_label}]"]
    else:
        filters = [f"[{video_input_label}]null[{overlay_base_label}]"]

    current_video_label = overlay_base_label
    if (
        ber_icon_label is not None
        and active_layout.ber_badge_box is not None
        and active_layout.ber_badge_box.visible
    ):
        ber_overlay_label = "video_with_ber_panel"
        filters.append(
            (
                f"[{current_video_label}][{ber_icon_label}]"
                f"overlay=x={active_layout.ber_badge_box.x}:y={active_layout.ber_badge_box.y}"
                f"[{ber_overlay_label}]"
            )
        )
        current_video_label = ber_overlay_label

    if (
        active_layout.agent_image_box is not None
        and active_layout.agent_image_box.visible
    ):
        filters.append(
            (
                f"[{current_video_label}][{agent_image_label}]"
                f"overlay=x={active_layout.agent_image_box.x}:y={active_layout.agent_image_box.y}"
                "[video_with_agent_panel]"
            )
        )
        current_video_label = "video_with_agent_panel"

    if (
        logo_image_label is not None
        and active_layout.agency_logo_box is not None
        and active_layout.agency_logo_box.visible
    ):
        filters.append(
            (
                f"[{current_video_label}][{logo_image_label}]"
                f"overlay=x={active_layout.agency_logo_box.x}:y={active_layout.agency_logo_box.y}"
                "[video_with_agency_logo]"
            )
        )
        current_video_label = "video_with_agency_logo"

    filters.append(f"[{current_video_label}]null[{output_label}]")
    return ";".join(filters)


def build_motion_crop_expressions(*, slide_frames: int) -> tuple[str, str]:
    frame_progress = "0"
    if slide_frames > 1:
        frame_progress = f"(n/{slide_frames - 1})"

    center_y = "floor((in_h-out_h)/2)"
    crop_x = f"if(gt(in_w,out_w),floor((in_w-out_w)*{frame_progress}),0)"
    return crop_x, center_y


def build_filter_complex(
    property_data: PropertyReelData,
    settings: PropertyReelTemplate,
    *,
    slides: Sequence[PropertyReelSlide],
    slide_frames: int,
    slide_duration: float,
    logo_input_index: int | None,
    agent_image_input_index: int,
    ber_icon_input_index: int | None = None,
    include_agency_logo: bool | None = None,
    layout: OverlayLayout | None = None,
) -> str:
    slide_count = len(slides)
    filter_parts: list[str] = []
    fade_duration = min(0.35, slide_duration / 4.0)
    target_aspect_ratio = settings.width / settings.height
    overlay_layout = layout or build_overlay_layout(
        property_data,
        settings,
        slides=tuple(slides),
        slide_duration=slide_duration,
        has_ber_badge=ber_icon_input_index is not None,
        has_agency_logo=(
            logo_input_index is not None
            if include_agency_logo is None
            else include_agency_logo
        ),
        cover_caption=slides[0].caption if settings.include_intro and slides else None,
    )

    agent_box = overlay_layout.agent_image_box
    agent_image_size = (
        agent_box.width
        if agent_box is not None and agent_box.visible
        else resolve_agent_image_size(settings)
    )
    filter_parts.append(
        f"[{agent_image_input_index}:v]"
        f"scale=w={agent_image_size}:h={agent_image_size}:force_original_aspect_ratio=increase,"
        f"crop={agent_image_size}:{agent_image_size},"
        "format=rgba"
        "[agent_panel_image]"
    )
    if ber_icon_input_index is not None:
        ber_height = (
            overlay_layout.ber_badge_box.height
            if overlay_layout.ber_badge_box is not None and overlay_layout.ber_badge_box.visible
            else resolve_ber_icon_size(settings)[1]
        )
        filter_parts.append(
            f"[{ber_icon_input_index}:v]"
            f"scale=w=-1:h={ber_height},"
            "format=rgba"
            "[ber_header_icon]"
        )
    if (
        logo_input_index is not None
        and overlay_layout.agency_logo_box is not None
        and overlay_layout.agency_logo_box.visible
    ):
        filter_parts.append(
            f"[{logo_input_index}:v]"
            f"scale=w={overlay_layout.agency_logo_box.width}:h={overlay_layout.agency_logo_box.height}:force_original_aspect_ratio=decrease,"
            f"pad={overlay_layout.agency_logo_box.width}:{overlay_layout.agency_logo_box.height}:(ow-iw)/2:(oh-ih)/2:color=black@0.0,"
            "format=rgba"
            "[agency_logo]"
        )
    if settings.include_intro:
        filter_parts.append(
            f"[0:v]"
            f"scale=w={settings.width}:h={settings.height}:force_original_aspect_ratio=increase,"
            f"crop={settings.width}:{settings.height},"
            "boxblur=22:4,"
            "eq=saturation=0.92:contrast=1.02:brightness=-0.02,"
            "format=yuv420p,"
            "setsar=1,"
            f"trim=duration={settings.intro_duration_seconds:.6f},"
            "setpts=PTS-STARTPTS"
            "[coverbg]"
        )
        if logo_input_index is not None:
            filter_parts.append(
                f"[{logo_input_index}:v]"
                f"scale=w='min(iw,{settings.width - 260})':h=-1,"
                "format=rgba"
                "[logo]"
            )
            filter_parts.append(
                "[coverbg][logo]"
                "overlay=x=(W-w)/2:y=(H-h)/2-110"
                "[cover]"
            )
        else:
            filter_parts.append("[coverbg]null[cover]")

    for index in range(slide_count):
        crop_x, crop_y = build_motion_crop_expressions(slide_frames=slide_frames)
        slide_filters = [
            f"scale=w='if(gte(iw/ih,{target_aspect_ratio:.8f}),-2,{settings.width})':"
            f"h='if(gte(iw/ih,{target_aspect_ratio:.8f}),{settings.height},-2)':"
            "eval=init",
            f"crop={settings.width}:{settings.height}:x='{crop_x}':y='{crop_y}'",
            "eq=saturation=1.03:contrast=1.02:brightness=0.01",
            "format=yuv420p",
            "setsar=1",
            f"trim=duration={slide_duration:.6f}",
            "setpts=PTS-STARTPTS",
        ]
        if index != 0:
            slide_filters.append(f"fade=t=in:st=0:d={fade_duration:.3f}")
        slide_filters.append(
            f"fade=t=out:st={max(slide_duration - fade_duration, 0.0):.3f}:d={fade_duration:.3f}"
        )
        filter_parts.append(
            f"[{index}:v]{','.join(slide_filters)}[v{index}]"
        )

    if slide_count == 1:
        filter_parts.append("[v0]null[slideshow]")
    else:
        concat_inputs = "".join(f"[v{index}]" for index in range(slide_count))
        filter_parts.append(f"{concat_inputs}concat=n={slide_count}:v=1:a=0[slideshow]")
    if settings.include_intro:
        filter_parts.append("[cover][slideshow]concat=n=2:v=1:a=0[video_base]")
    else:
        filter_parts.append("[slideshow]null[video_base]")
    filter_parts.append(
        build_overlay_filter(
            property_data,
            settings,
            cover_caption=slides[0].caption if settings.include_intro and slides else None,
            slide_captions=[slide.caption for slide in slides],
            slide_duration=slide_duration,
            video_input_label="video_base",
            agent_image_label="agent_panel_image",
            logo_image_label=(
                "agency_logo"
                if logo_input_index is not None
                and overlay_layout.agency_logo_box is not None
                and overlay_layout.agency_logo_box.visible
                else None
            ),
            ber_icon_label="ber_header_icon" if ber_icon_input_index is not None else None,
            output_label="vout",
            layout=overlay_layout,
        )
    )
    return ";".join(filter_parts)


__all__ = [
    "_build_drawtext_enable_expression",
    "build_filter_complex",
    "build_motion_crop_expressions",
    "build_overlay_filter",
    "resolve_agent_image_size",
    "resolve_ber_icon_size",
]
