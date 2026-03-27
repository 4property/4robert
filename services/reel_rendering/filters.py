from __future__ import annotations

from collections.abc import Sequence

from services.ai_photo_selection.prompting import normalize_caption
from services.reel_rendering.formatting import (
    build_agent_lines,
    build_status_ribbon_text,
    clean_text,
    escape_drawtext_text,
    escape_filter_path,
    format_price,
    wrap_lines,
)
from services.reel_rendering.models import PropertyReelData, PropertyReelSlide, PropertyReelTemplate
from services.reel_rendering.runtime import resolve_font_path

_BER_ICON_ASPECT_RATIO = 1800 / 582


def _resolve_top_panel_height(settings: PropertyReelTemplate) -> int:
    return max(340, round(settings.height * 0.245))


def _resolve_bottom_panel_height(settings: PropertyReelTemplate) -> int:
    return max(220, round(settings.height * 0.16))


def _resolve_agent_image_size(settings: PropertyReelTemplate) -> int:
    panel_padding_y = max(22, round(settings.height * 0.018))
    bottom_panel_height = _resolve_bottom_panel_height(settings)
    return bottom_panel_height - (panel_padding_y * 2)


def _resolve_ber_icon_size(settings: PropertyReelTemplate) -> tuple[int, int]:
    top_panel_height = _resolve_top_panel_height(settings)
    panel_padding_y = max(22, round(settings.height * 0.018))
    max_height = max(60, top_panel_height - (panel_padding_y * 2))
    icon_height = min(max_height, max(60, round(top_panel_height * 0.18)))
    icon_width = max(1, round(icon_height * _BER_ICON_ASPECT_RATIO))
    return icon_width, icon_height


def _wrap_width_from_pixels(*, usable_width: int, font_size: int, min_chars: int) -> int:
    usable_width = max(120, usable_width)
    average_character_width = max(14.0, font_size * 0.62)
    return max(min_chars, round(usable_width / average_character_width))


def build_overlay_filter(
    property_data: PropertyReelData,
    settings: PropertyReelTemplate,
    *,
    cover_caption: str | None = None,
    slide_captions: Sequence[str | None] = (),
    slide_duration: float | None = None,
    video_input_label: str = "video_base",
    agent_image_label: str = "agent_panel_image",
    ber_icon_label: str | None = None,
    output_label: str = "vout",
) -> str:
    width = settings.width
    height = settings.height
    font_path = escape_filter_path(resolve_font_path(settings.font_path))
    bold_font_path = escape_filter_path(resolve_font_path(settings.bold_font_path))
    subtitle_font_path = escape_filter_path(resolve_font_path(settings.subtitle_font_path))
    outer_margin_x = max(36, round(width * 0.04))
    outer_margin_y = max(36, round(height * 0.03))
    panel_padding_x = max(26, round(width * 0.024))
    panel_padding_y = max(22, round(height * 0.018))
    top_panel_height = _resolve_top_panel_height(settings)
    bottom_panel_height = _resolve_bottom_panel_height(settings)
    top_panel_y = outer_margin_y
    bottom_panel_y = height - outer_margin_y - bottom_panel_height
    panel_width = width - (outer_margin_x * 2)
    top_text_x = outer_margin_x + panel_padding_x
    agent_lines = build_agent_lines(property_data)
    ber_icon_width, ber_icon_height = _resolve_ber_icon_size(settings)
    ber_icon_gap = max(24, round(width * 0.018))
    header_text_width = panel_width - (panel_padding_x * 2)
    if ber_icon_label is not None:
        header_text_width = max(
            280,
            header_text_width - ber_icon_width - ber_icon_gap,
        )

    status_lines = wrap_lines(
        build_status_ribbon_text(property_data),
        width=_wrap_width_from_pixels(
            usable_width=header_text_width,
            font_size=max(60, round(height * 0.05)),
            min_chars=8,
        ),
        max_lines=1,
    )
    price_text = format_price(property_data.price)
    price_lines = wrap_lines(
        price_text,
        width=_wrap_width_from_pixels(
            usable_width=header_text_width,
            font_size=max(60, round(height * 0.05)),
            min_chars=8,
        ),
        max_lines=1,
    )
    address_lines = wrap_lines(
        clean_text(property_data.title),
        width=_wrap_width_from_pixels(
            usable_width=header_text_width,
            font_size=max(28, round(height * 0.024)),
            min_chars=18,
        ),
        max_lines=2,
    )
    show_top_panel = bool(status_lines or price_lines or address_lines)

    price_font_size = max(60, round(height * 0.05))
    address_font_size = max(28, round(height * 0.024))
    caption_font_size = settings.subtitle_font_size
    agent_name_font_size = max(28, round(height * 0.024))
    agent_contact_font_size = max(22, round(height * 0.019))
    status_font_size = price_font_size

    agent_image_size = _resolve_agent_image_size(settings)
    agent_image_x = outer_margin_x + panel_padding_x
    agent_image_y = bottom_panel_y + panel_padding_y
    agent_text_x = agent_image_x + agent_image_size + panel_padding_x
    bottom_text_width_chars = max(22, round((panel_width - agent_image_size - (panel_padding_x * 3)) / 17))
    wrapped_agent_name = wrap_lines(agent_lines[0], width=bottom_text_width_chars, max_lines=2)
    wrapped_agent_contact = wrap_lines(
        agent_lines[1] if len(agent_lines) > 1 else "",
        width=bottom_text_width_chars,
        max_lines=2,
    )
    agent_name_y = bottom_panel_y + panel_padding_y + 8
    agent_name_line_gap = agent_name_font_size + 8
    agent_contact_y = agent_name_y + (len(wrapped_agent_name[:2]) * agent_name_line_gap) + 14
    agent_contact_line_gap = agent_contact_font_size + 8
    subtitle_gap_y = max(20, round(height * 0.018))
    subtitle_text_safe_x = outer_margin_x + panel_padding_x
    subtitle_max_width = panel_width - (panel_padding_x * 2)
    subtitle_width_chars = _wrap_width_from_pixels(
        usable_width=subtitle_max_width,
        font_size=caption_font_size,
        min_chars=18,
    )
    subtitle_line_gap = caption_font_size + max(8, round(caption_font_size * 0.22))
    ber_icon_x = outer_margin_x + panel_width - panel_padding_x - ber_icon_width
    ber_icon_y = top_panel_y + max(0, round((top_panel_height - ber_icon_height) / 2))

    text_filters = [
        (
            f"drawbox=x={outer_margin_x}:y={bottom_panel_y}:"
            f"w={panel_width}:h={bottom_panel_height}:"
            "color=black@0.46:t=fill"
        ),
        (
            f"drawbox=x={agent_image_x - 6}:y={agent_image_y - 6}:"
            f"w={agent_image_size + 12}:h={agent_image_size + 12}:"
            "color=white@0.14:t=fill"
        ),
    ]

    if show_top_panel:
        text_filters.append(
            (
                f"drawbox=x={outer_margin_x}:y={top_panel_y}:"
                f"w={panel_width}:h={top_panel_height}:"
                "color=black@0.38:t=fill"
            )
        )
        top_cursor_y = top_panel_y + panel_padding_y - 4
        for index, line in enumerate(status_lines):
            text_filters.append(
                "drawtext="
                f"fontfile='{bold_font_path}':"
                f"text='{escape_drawtext_text(line)}':"
                f"fontcolor=white:fontsize={status_font_size}:"
                f"x={top_text_x}:y={top_cursor_y + index * (status_font_size + 8)}"
            )

        if status_lines:
            top_cursor_y += (len(status_lines) * (status_font_size + 8)) + 10

        for index, line in enumerate(price_lines):
            text_filters.append(
                "drawtext="
                f"fontfile='{bold_font_path}':"
                f"text='{escape_drawtext_text(line)}':"
                f"fontcolor=white:fontsize={price_font_size}:"
                f"x={top_text_x}:y={top_cursor_y + index * (price_font_size + 8)}"
            )

        address_start_y = (
            top_cursor_y + (len(price_lines) * (price_font_size + 8)) + 4
            if price_lines
            else top_cursor_y + 6
        )
        for index, line in enumerate(address_lines):
            text_filters.append(
                "drawtext="
                f"fontfile='{font_path}':"
                f"text='{escape_drawtext_text(line)}':"
                f"fontcolor=white:fontsize={address_font_size}:"
                f"x={top_text_x}:y={address_start_y + index * (address_font_size + 8)}"
            )

    for index, line in enumerate(wrapped_agent_name[:2]):
        text_filters.append(
            "drawtext="
            f"fontfile='{bold_font_path}':"
            f"text='{escape_drawtext_text(line)}':"
            f"fontcolor=white:fontsize={agent_name_font_size}:"
            f"x={agent_text_x}:y={agent_name_y + index * agent_name_line_gap}"
        )

    for index, line in enumerate(wrapped_agent_contact[:2]):
        text_filters.append(
            "drawtext="
            f"fontfile='{font_path}':"
            f"text='{escape_drawtext_text(line)}':"
            f"fontcolor=white:fontsize={agent_contact_font_size}:"
            f"x={agent_text_x}:y={agent_contact_y + index * agent_contact_line_gap}"
        )

    if slide_duration is not None:
        segment_captions = [
            (0.0, settings.intro_duration_seconds, normalize_caption(cover_caption, ""))
        ]
        segment_captions.extend(
            (
                settings.intro_duration_seconds + (index * slide_duration),
                settings.intro_duration_seconds + ((index + 1) * slide_duration),
                normalize_caption(caption, ""),
            )
            for index, caption in enumerate(slide_captions)
        )

        for start_time, end_time, caption in segment_captions:
            if not caption:
                continue

            subtitle_lines = wrap_lines(
                caption,
                width=subtitle_width_chars,
                max_lines=2,
            )
            if not subtitle_lines:
                continue

            subtitle_text_height = ((len(subtitle_lines) - 1) * subtitle_line_gap) + caption_font_size
            subtitle_text_y = bottom_panel_y - subtitle_gap_y - subtitle_text_height
            enable = f"enable='between(t,{start_time:.3f},{end_time:.3f})'"
            for index, line in enumerate(subtitle_lines):
                text_filters.append(
                    "drawtext="
                    f"fontfile='{subtitle_font_path}':"
                    f"text='{escape_drawtext_text(line)}':"
                    "fontcolor=0xF4D03F:"
                    f"fontsize={caption_font_size}:"
                    f"x={subtitle_text_safe_x}+max(({subtitle_max_width}-text_w)/2\\,0):"
                    f"y={subtitle_text_y + index * subtitle_line_gap}:"
                    f"borderw=2:bordercolor=black@0.80:"
                    f"shadowx=0:shadowy=3:shadowcolor=black@0.75:"
                    f"text_shaping=1:"
                    f"fix_bounds=1:"
                    f"{enable}"
                )

    overlay_base_label = "video_with_property_panels"
    filters = [f"[{video_input_label}]{','.join(text_filters)}[{overlay_base_label}]"]
    current_video_label = overlay_base_label
    if ber_icon_label is not None:
        ber_overlay_label = "video_with_ber_panel"
        filters.append(
            (
                f"[{current_video_label}][{ber_icon_label}]"
                f"overlay=x={ber_icon_x}:y={ber_icon_y}"
                f"[{ber_overlay_label}]"
            )
        )
        current_video_label = ber_overlay_label
    filters.append(
        (
            f"[{current_video_label}][{agent_image_label}]"
            f"overlay=x={agent_image_x}:y={agent_image_y}"
            "[video_with_agent_panel]"
        )
    )
    filters.append(f"[video_with_agent_panel]null[{output_label}]")
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
    logo_input_index: int,
    agent_image_input_index: int,
    ber_icon_input_index: int | None = None,
) -> str:
    slide_count = len(slides)
    filter_parts: list[str] = []
    fade_duration = min(0.35, slide_duration / 4.0)
    target_aspect_ratio = settings.width / settings.height
    agent_image_size = _resolve_agent_image_size(settings)
    ber_icon_width, ber_icon_height = _resolve_ber_icon_size(settings)

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
    filter_parts.append(
        f"[{logo_input_index}:v]"
        f"scale=w='min(iw,{settings.width - 260})':h=-1,"
        "format=rgba"
        "[logo]"
    )
    filter_parts.append(
        f"[{agent_image_input_index}:v]"
        f"scale=w={agent_image_size}:h={agent_image_size}:force_original_aspect_ratio=increase,"
        f"crop={agent_image_size}:{agent_image_size},"
        "format=rgba"
        "[agent_panel_image]"
    )
    if ber_icon_input_index is not None:
        filter_parts.append(
            f"[{ber_icon_input_index}:v]"
            f"scale=w=-1:h={ber_icon_height},"
            "format=rgba"
            "[ber_header_icon]"
        )
    filter_parts.append(
        "[coverbg][logo]"
        "overlay=x=(W-w)/2:y=(H-h)/2-110"
        "[cover]"
    )

    for index in range(slide_count):
        crop_x, crop_y = build_motion_crop_expressions(slide_frames=slide_frames)
        filter_parts.append(
            f"[{index}:v]"
            f"scale=w='if(gte(iw/ih,{target_aspect_ratio:.8f}),-2,{settings.width})':"
            f"h='if(gte(iw/ih,{target_aspect_ratio:.8f}),{settings.height},-2)':"
            "eval=init,"
            f"crop={settings.width}:{settings.height}:x='{crop_x}':y='{crop_y}',"
            "eq=saturation=1.03:contrast=1.02:brightness=0.01,"
            "format=yuv420p,"
            "setsar=1,"
            f"trim=duration={slide_duration:.6f},"
            "setpts=PTS-STARTPTS,"
            f"fade=t=in:st=0:d={fade_duration:.3f},"
            f"fade=t=out:st={max(slide_duration - fade_duration, 0.0):.3f}:d={fade_duration:.3f}"
            f"[v{index}]"
        )

    concat_inputs = "".join(f"[v{index}]" for index in range(slide_count))
    filter_parts.append(f"{concat_inputs}concat=n={slide_count}:v=1:a=0[slideshow]")
    filter_parts.append("[cover][slideshow]concat=n=2:v=1:a=0[video_base]")
    filter_parts.append(
        build_overlay_filter(
            property_data,
            settings,
            cover_caption=slides[0].caption if slides else None,
            slide_captions=[slide.caption for slide in slides],
            slide_duration=slide_duration,
            video_input_label="video_base",
            agent_image_label="agent_panel_image",
            ber_icon_label="ber_header_icon" if ber_icon_input_index is not None else None,
            output_label="vout",
        )
    )
    return ";".join(filter_parts)


__all__ = ["build_filter_complex", "build_motion_crop_expressions", "build_overlay_filter"]

