"""ffmpeg filter graph builders for reel rendering."""

from __future__ import annotations

from dataclasses import replace

from modules.rendering.infrastructure.ffmpeg.filters import build_overlay_filter
from modules.rendering.infrastructure.formatting import build_fit_inside_rgba_filter
from modules.rendering.infrastructure.layout import build_overlay_layout
from modules.rendering.infrastructure.models import (
    PreparedReelAssets,
    PreparedReelSlide,
    PropertyRenderData,
    PropertyReelSlide,
    PropertyReelTemplate,
)


def build_intro_segment_filter(
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
        filter_parts.append(
            (
                f"[{next_input_index}:v]"
                f"{build_fit_inside_rgba_filter(intro_layout.agent_image_box.width, intro_layout.agent_image_box.height)}"
                "[agent_panel_image]"
            )
        )
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


def build_motion_progress_expression(slide_frames: int) -> str:
    if slide_frames <= 1:
        return "0"
    return f"(n/{slide_frames - 1})"


def build_slide_crop_expressions(
    *,
    slide: PreparedReelSlide,
    settings: PropertyReelTemplate,
    slide_frames: int,
) -> tuple[str, str]:
    travel_x = max(slide.working_width - settings.width, 0)
    travel_y = max(slide.working_height - settings.height, 0)
    progress = build_motion_progress_expression(slide_frames)
    center_x = str(travel_x // 2)
    center_y = str(travel_y // 2)
    crop_x = f"floor({travel_x}*{progress})" if travel_x > 0 else center_x
    return crop_x, center_y


def build_slide_segment_filter(
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
    crop_x, crop_y = build_slide_crop_expressions(
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
    filter_parts = ["[0:v]" + ",".join(slide_filters) + "[slide_base]"]
    next_input_index = 1
    if segment_layout.agent_image_box is not None and segment_layout.agent_image_box.visible:
        filter_parts.append(
            (
                f"[{next_input_index}:v]"
                f"{build_fit_inside_rgba_filter(segment_layout.agent_image_box.width, segment_layout.agent_image_box.height)}"
                "[agent_panel_image]"
            )
        )
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


__all__ = [
    "build_intro_segment_filter",
    "build_motion_progress_expression",
    "build_slide_crop_expressions",
    "build_slide_segment_filter",
]
