"""ffmpeg filter graph helpers for property reels.

Migrated from ``services/media/reel_rendering/filters.py`` during
sub-feature 18c. Builds the ``filter_complex`` script consumed by the
ffmpeg reel render pipeline.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from modules.rendering.infrastructure.formatting import (
    escape_drawtext_text,
    escape_filter_path,
    resolve_agent_image_size,
    resolve_ber_icon_size,
    resolve_text_color,
)
from modules.rendering.infrastructure.layout import (
    OverlayLayout,
    build_overlay_layout,
)
from modules.rendering.infrastructure.models import (
    PropertyReelData,
    PropertyReelSlide,
    PropertyReelTemplate,
)
from modules.rendering.infrastructure.runtime import resolve_font_path

_APPLICATION_ROOT = Path(__file__).resolve().parents[4]
_CENTURY21_ASSET_DIR = _APPLICATION_ROOT / "assets" / "render-templates" / "century21"
_CENTURY21_HEADER_LOGO_PATH = _CENTURY21_ASSET_DIR / "header-logo.png"
_CENTURY21_PHONE_ICON_PATH = _CENTURY21_ASSET_DIR / "phone.png"
_CENTURY21_MAIL_ICON_PATH = _CENTURY21_ASSET_DIR / "mail.png"


def _split_ffmpeg_color_alpha(color: str) -> tuple[str, int]:
    base_color, separator, alpha_text = color.strip().rpartition("@")
    if not separator or not base_color:
        return color, 255
    try:
        alpha = float(alpha_text)
    except ValueError:
        return color, 255
    return base_color, round(max(0.0, min(1.0, alpha)) * 255)


def _build_rounded_panel_source(
    *,
    label: str,
    color: str,
    width: int,
    height: int,
    radius: int,
) -> str:
    color_source, alpha = _split_ffmpeg_color_alpha(color)
    safe_radius = max(1, min(radius, width // 2, height // 2))
    right = width - safe_radius - 1
    bottom = height - safe_radius - 1
    radius_squared = safe_radius * safe_radius
    dx = f"max(max({safe_radius}-X\\,X-{right})\\,0)"
    dy = f"max(max({safe_radius}-Y\\,Y-{bottom})\\,0)"
    alpha_expr = (
        f"if(lte(({dx})*({dx})+({dy})*({dy})\\,{radius_squared})\\,{alpha}\\,0)"
    )
    return (
        f"color=c={color_source}:s={width}x{height},format=rgba,"
        "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
        f"a='{alpha_expr}'[{label}]"
    )


def _resolve_side_banner_footer_radius(
    *,
    frame_height: int,
    panel_width: int,
    panel_height: int,
) -> int:
    return min(
        panel_width // 2,
        panel_height // 2,
        max(12, round(frame_height * 0.0125)),
    )


def _resolve_galaxy_panel_radius(
    *,
    frame_height: int,
    panel_width: int,
    panel_height: int,
) -> int:
    """Resolve the shared Galaxy card radius for top and bottom panels."""
    return min(
        panel_width // 2,
        panel_height // 2,
        max(12, round(frame_height * 0.010)),
    )


def _normalize_hex_draw_color(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = value.strip()
    if not candidate:
        return None
    candidate = candidate.split("@", 1)[0].strip()
    if candidate.lower().startswith("0x"):
        candidate = candidate[2:]
    candidate = candidate.lstrip("#")
    if len(candidate) == 3 and all(
        ch in "0123456789abcdefABCDEF" for ch in candidate
    ):
        candidate = "".join(ch * 2 for ch in candidate)
    if len(candidate) != 6 or any(
        ch not in "0123456789abcdefABCDEF" for ch in candidate
    ):
        return None
    return f"0x{candidate.lower()}"


def _normalize_hex_box_color(value: str | None, *, alpha: float) -> str | None:
    draw_color = _normalize_hex_draw_color(value)
    if draw_color is None:
        return None
    return f"{draw_color}@{max(0.0, min(1.0, alpha)):.2f}"


def _resolve_galaxy_secondary_text_color(
    property_data: PropertyReelData,
    text_override_color: str | None,
) -> str:
    secondary_color = _normalize_hex_draw_color(
        property_data.side_banner_ribbon_background_color
    )
    if secondary_color is not None:
        return secondary_color
    return resolve_text_color("agent_name", text_override_color)


def _resolve_galaxy_secondary_box_color(
    property_data: PropertyReelData,
    text_override_color: str | None,
) -> str:
    secondary_color = _normalize_hex_box_color(
        property_data.side_banner_ribbon_background_color,
        alpha=0.95,
    )
    if secondary_color is not None:
        return secondary_color
    fallback_color = _normalize_hex_box_color(text_override_color, alpha=0.95)
    return fallback_color or "white@0.90"


def _append_galaxy_footer_graphics(
    text_filters: list[str],
    *,
    layout: OverlayLayout,
    property_data: PropertyReelData,
    text_override_color: str | None,
) -> None:
    if layout.bottom_panel is None or not layout.bottom_panel.visible:
        return
    accent_color = _resolve_galaxy_secondary_text_color(
        property_data,
        text_override_color,
    )
    if layout.agent_image_box is not None and layout.agent_image_box.visible:
        separator_width = max(2, round(layout.frame_width * 0.0025))
        separator_height = max(96, round(layout.agent_image_box.height * 0.72))
        separator_x = (
            layout.agent_image_box.x
            + layout.agent_image_box.width
            + max(14, round(layout.frame_width * 0.014))
        )
        separator_y = layout.agent_image_box.y + round(
            (layout.agent_image_box.height - separator_height) / 2
        )
        text_filters.append(
            "drawbox="
            f"x={separator_x}:y={separator_y}:"
            f"w={separator_width}:h={separator_height}:"
            f"color={accent_color}:t=fill"
        )


def _append_static_png_overlay(
    filters: list[str],
    *,
    base_label: str,
    image_path: Path,
    label_prefix: str,
    x: int,
    y: int,
    width: int,
    height: int,
) -> str:
    image_source_label = f"{label_prefix}_source"
    image_overlay_label = f"video_with_{label_prefix}"
    image_path_escaped = escape_filter_path(image_path)
    filters.append(
        f"movie=filename='{image_path_escaped}',format=rgba,"
        f"scale=w={width}:h={height}"
        f"[{image_source_label}]"
    )
    filters.append(
        f"[{base_label}][{image_source_label}]"
        f"overlay=x={x}:y={y}"
        f"[{image_overlay_label}]"
    )
    return image_overlay_label


def _append_galaxy_header_logo_overlay(
    filters: list[str],
    *,
    base_label: str,
    layout: OverlayLayout,
) -> str:
    if layout.top_panel is None or not layout.top_panel.visible:
        return base_label
    # Century 21 polish v2 (2026-05-19): logo header bumped +50% so the
    # seal reads from the thumbnail. With the previous 0.073 vertical
    # anchor and a panel min height of ~0.237*H, the new 0.174*H logo
    # height overflows the bottom edge of the top panel at 1492 px frame
    # (e.g. 157+260=417 > panel_bottom=402). We therefore center the
    # logo vertically inside the top panel so it cannot escape, while
    # keeping the horizontal anchor at 0.558*W. The result is a logo
    # ~1.5x bigger that stays inside the card on every supported frame
    # size.
    # Century 21 polish v3 (2026-05-19): horizontal anchor shifted
    # slightly to the left (0.558 -> 0.520) so the seal moves ~3.5% of
    # the frame width closer to the header text column. Vertical anchor
    # logic unchanged. The header_text_width factor in
    # ``compose_top_panel`` was tightened in tandem to 0.460 to keep the
    # address column clear of the seal.
    logo_width = max(192, round(layout.frame_width * 0.225))
    logo_height = max(210, round(layout.frame_height * 0.174))
    logo_x = layout.top_panel.x + round(layout.frame_width * 0.520)
    logo_y = layout.top_panel.y + max(0, (layout.top_panel.height - logo_height) // 2)
    return _append_static_png_overlay(
        filters,
        base_label=base_label,
        image_path=_CENTURY21_HEADER_LOGO_PATH,
        label_prefix="galaxy_header_logo",
        x=logo_x,
        y=logo_y,
        width=logo_width,
        height=logo_height,
    )


def _append_galaxy_contact_icon_overlays(
    filters: list[str],
    *,
    base_label: str,
    layout: OverlayLayout,
) -> str:
    current_label = base_label
    contact_blocks = {
        block.block: block
        for block in layout.text_blocks
        if block.block in {"agent_phone", "agent_email"} and block.visible
    }
    for block_name, image_path, label_prefix in (
        ("agent_phone", _CENTURY21_PHONE_ICON_PATH, "galaxy_phone_icon"),
        ("agent_email", _CENTURY21_MAIL_ICON_PATH, "galaxy_mail_icon"),
    ):
        block = contact_blocks.get(block_name)
        if block is None:
            continue
        icon_slot = max(34, round(layout.frame_width * 0.040))
        icon_size = max(22, round(block.font_size * 1.04))
        icon_x = max(0, block.x - icon_slot)
        icon_y = block.y + max(0, round((block.box_height - icon_size) / 2))
        current_label = _append_static_png_overlay(
            filters,
            base_label=current_label,
            image_path=image_path,
            label_prefix=label_prefix,
            x=icon_x,
            y=icon_y,
            width=icon_size,
            height=icon_size,
        )
    return current_label


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
    layout_variant: str = "classic",
    top_panel_color: str | None = None,
    bottom_panel_color: str | None = None,
    text_override_color: str | None = None,
    vertical_banner_label: str | None = None,
    vertical_banner_x: int | None = None,
    vertical_banner_y: int | None = None,
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
        layout_variant=layout_variant,
    )
    font_path = escape_filter_path(resolve_font_path(settings.font_path))
    bold_font_path = escape_filter_path(resolve_font_path(settings.bold_font_path))
    subtitle_font_path = escape_filter_path(resolve_font_path(settings.subtitle_font_path))

    # Feature 16: side_banner can override the panel fill colors with a
    # transparent per-property accent. Defaults preserve the classic
    # black overlays byte-for-byte.
    resolved_top_panel_color = top_panel_color or "black@0.38"
    resolved_bottom_panel_color = bottom_panel_color or "black@0.46"

    filters: list[str] = []
    current_base_label = video_input_label
    text_filters: list[str] = []
    if active_layout.bottom_panel is not None and active_layout.bottom_panel.visible:
        if layout_variant in {"side_banner", "galaxy"}:
            # Feature 16 (side_banner) introduced the rounded footer
            # card; feature 42 (galaxy) reuses the same helper and the
            # same radius cascade so the bottom panel keeps a soft
            # corner profile against the full-bleed photo. The top
            # panel is rounded in a separate block below (galaxy only).
            footer_panel_label = (
                "side_banner_footer_panel"
                if layout_variant == "side_banner"
                else "galaxy_footer_panel"
            )
            footer_base_label = (
                "video_with_side_banner_footer_panel"
                if layout_variant == "side_banner"
                else "video_with_galaxy_footer_panel"
            )
            footer_radius_resolver = (
                _resolve_galaxy_panel_radius
                if layout_variant == "galaxy"
                else _resolve_side_banner_footer_radius
            )
            filters.append(
                _build_rounded_panel_source(
                    label=footer_panel_label,
                    color=resolved_bottom_panel_color,
                    width=active_layout.bottom_panel.width,
                    height=active_layout.bottom_panel.height,
                    radius=footer_radius_resolver(
                        frame_height=settings.height,
                        panel_width=active_layout.bottom_panel.width,
                        panel_height=active_layout.bottom_panel.height,
                    ),
                )
            )
            filters.append(
                (
                    f"[{current_base_label}][{footer_panel_label}]"
                    f"overlay=x={active_layout.bottom_panel.x}:y={active_layout.bottom_panel.y}"
                    f"[{footer_base_label}]"
                )
            )
            current_base_label = footer_base_label
        else:
            text_filters.append(
                (
                    f"drawbox=x={active_layout.bottom_panel.x}:y={active_layout.bottom_panel.y}:"
                    f"w={active_layout.bottom_panel.width}:h={active_layout.bottom_panel.height}:"
                    f"color={resolved_bottom_panel_color}:t=fill"
                )
            )
    if active_layout.top_panel is not None and active_layout.top_panel.visible:
        if layout_variant == "galaxy":
            # Feature 42: galaxy rounds BOTH the top and bottom panels
            # (side_banner only rounds the bottom). Same radius helper
            # as the footer so the card has a consistent corner
            # profile, drawn as a separate overlay so the rounded
            # corners blend with the underlying photo alpha.
            top_panel_label = "galaxy_top_panel"
            top_base_label = "video_with_galaxy_top_panel"
            filters.append(
                _build_rounded_panel_source(
                    label=top_panel_label,
                    color=resolved_top_panel_color,
                    width=active_layout.top_panel.width,
                    height=active_layout.top_panel.height,
                    radius=_resolve_galaxy_panel_radius(
                        frame_height=settings.height,
                        panel_width=active_layout.top_panel.width,
                        panel_height=active_layout.top_panel.height,
                    ),
                )
            )
            filters.append(
                (
                    f"[{current_base_label}][{top_panel_label}]"
                    f"overlay=x={active_layout.top_panel.x}:y={active_layout.top_panel.y}"
                    f"[{top_base_label}]"
                )
            )
            current_base_label = top_base_label
        else:
            text_filters.append(
                (
                    f"drawbox=x={active_layout.top_panel.x}:y={active_layout.top_panel.y}:"
                    f"w={active_layout.top_panel.width}:h={active_layout.top_panel.height}:"
                    f"color={resolved_top_panel_color}:t=fill"
                )
            )

    galaxy_secondary_text_color = (
        _resolve_galaxy_secondary_text_color(property_data, text_override_color)
        if layout_variant == "galaxy"
        else None
    )
    if layout_variant == "galaxy":
        current_base_label = _append_galaxy_header_logo_overlay(
            filters,
            base_label=current_base_label,
            layout=active_layout,
        )
        current_base_label = _append_galaxy_contact_icon_overlays(
            filters,
            base_label=current_base_label,
            layout=active_layout,
        )
        _append_galaxy_footer_graphics(
            text_filters,
            layout=active_layout,
            property_data=property_data,
            text_override_color=text_override_color,
        )

    # Century 21 polish v2 (2026-05-19): galaxy renders the "OFFERS
    # OVER:" status block in the regular weight so the price below it
    # reads as the heavier element. Classic and side_banner keep the
    # historical bold cascade for status/price/agent_name.
    galaxy_bold_blocks = {"price", "agent_name"}
    default_bold_blocks = {"status", "price", "agent_name"}
    bold_blocks = (
        galaxy_bold_blocks if layout_variant == "galaxy" else default_bold_blocks
    )
    for block in active_layout.text_blocks:
        if not block.visible:
            continue
        font_file = bold_font_path if block.block in bold_blocks else font_path
        font_color = (
            galaxy_secondary_text_color
            if block.block == "agent_name" and galaxy_secondary_text_color is not None
            else resolve_text_color(block.block, text_override_color)
        )
        for index, line in enumerate(block.lines):
            text_filters.append(
                "drawtext="
                f"fontfile='{font_file}':"
                f"text='{escape_drawtext_text(line)}':"
                f"fontcolor={font_color}:fontsize={block.font_size}:"
                f"x={block.x}:y={block.y + index * block.line_gap}:"
                "fix_bounds=1"
            )

    # Feature 31: per-agency subtitle styling cascades from
    # ``PropertyRenderData.subtitle_style``. ``enabled=False`` skips
    # every subtitle drawtext entirely (the agency toggled
    # ``automation.autoCaptions`` off via ``/defaults``); the rest of
    # the overlay (top/bottom panels, agent panel, etc.) is unaffected.
    # Feature 36: when the reel carries a per-reel subtitles override
    # the override always renders, even if the agency-level
    # ``autoCaptions`` toggle is disabled — the editorial intent on
    # the override row is the source of truth.
    subtitle_style = getattr(property_data, "subtitle_style", None)
    subtitle_enabled = bool(subtitle_style.enabled) if subtitle_style is not None else True
    subtitles_override = getattr(property_data, "subtitles_override", None)
    if subtitles_override:
        subtitle_enabled = True
    if subtitle_enabled:
        # Resolve the per-render font path via the catalogue helper. When
        # the agency picked a family from the brand catalogue we honour
        # the chosen weight; otherwise we fall back to the template's
        # historical ``subtitle_font_path``. Unknown families surface as
        # ``ValueError`` from ``font_catalog.resolve_weighted`` — we fall
        # back to the legacy path with no crash so a stale persisted
        # family cannot break a render.
        resolved_subtitle_font_path = subtitle_font_path
        if subtitle_style is not None and subtitle_style.font_family:
            try:
                from modules.configuration.domain.font_catalog import (
                    resolve_weighted,
                )

                primary_path, _bold = resolve_weighted(
                    subtitle_style.font_family,
                    subtitle_style.weight,
                )
                resolved_subtitle_font_path = escape_filter_path(
                    resolve_font_path(primary_path)
                )
            except ValueError:
                resolved_subtitle_font_path = subtitle_font_path

        fontcolor_hex = (
            subtitle_style.color.replace("#", "0x")
            if subtitle_style is not None and subtitle_style.color
            else "0xffffff"
        )
        bg_color_hex = (
            subtitle_style.bg_color.replace("#", "0x")
            if subtitle_style is not None and subtitle_style.bg_color
            else "0x0f1729"
        )
        bg_opacity_raw = (
            subtitle_style.bg_opacity if subtitle_style is not None else 82
        )
        bg_alpha = max(0.0, min(1.0, float(bg_opacity_raw or 0) / 100.0))
        bg_style = (
            (subtitle_style.bg_style or "outline").lower()
            if subtitle_style is not None
            else "outline"
        )

        def _subtitle_x_expr(seg) -> str:
            align = (seg.alignment or "center").lower()
            if align == "left":
                return f"{seg.x}"
            if align == "right":
                return f"{seg.x}+max({seg.max_width}-text_w\\,0)"
            return f"{seg.x}+max(({seg.max_width}-text_w)/2\\,0)"

        for segment in active_layout.subtitle_segments:
            enable = _build_drawtext_enable_expression(
                segment.start_time,
                segment.end_time,
            )
            for index, line in enumerate(segment.lines):
                drawtext_bits = [
                    "drawtext=",
                    f"fontfile='{resolved_subtitle_font_path}':",
                    f"text='{escape_drawtext_text(line)}':",
                    f"fontcolor={fontcolor_hex}:",
                    f"fontsize={segment.font_size}:",
                    f"x={_subtitle_x_expr(segment)}:",
                    f"y={segment.y + index * segment.line_gap}:",
                ]
                # Feature 31: bg_style cascade.
                # * "outline" → keep the legacy stroke-on-glyph look.
                # * "block" / "pill" → ffmpeg box (pill collapses to a
                #   rectangular box at MVP — true rounded background
                #   would require a second filter pass).
                # * "none" → no border, no box. The subtitle still
                #   carries a soft drop shadow so it stays readable on
                #   pale photos.
                if bg_style == "outline":
                    drawtext_bits.append("borderw=2:bordercolor=black@0.80:")
                elif bg_style in {"block", "pill"}:
                    drawtext_bits.append(
                        f"box=1:boxcolor={bg_color_hex}@{bg_alpha:.2f}:boxborderw=8:"
                    )
                # ``none`` adds neither outline nor box.
                drawtext_bits.append(
                    "shadowx=0:shadowy=3:shadowcolor=black@0.75:"
                )
                drawtext_bits.append("text_shaping=1:")
                drawtext_bits.append("fix_bounds=1:")
                drawtext_bits.append(enable)
                text_filters.append("".join(drawtext_bits))

    overlay_base_label = "video_with_property_panels"
    if text_filters:
        filters.append(f"[{current_base_label}]{','.join(text_filters)}[{overlay_base_label}]")
    else:
        filters.append(f"[{current_base_label}]null[{overlay_base_label}]")

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

    # Feature 16: pre-rendered vertical status banner overlay
    # (side_banner template). The banner is generated as a PNG by
    # ``preparation._render_vertical_status_banner`` and exposed as an
    # extra ffmpeg input; classic renders skip this stage entirely
    # (``vertical_banner_label is None``).
    if (
        vertical_banner_label is not None
        and vertical_banner_x is not None
        and vertical_banner_y is not None
    ):
        filters.append(
            (
                f"[{current_video_label}][{vertical_banner_label}]"
                f"overlay=x={vertical_banner_x}:y={vertical_banner_y}"
                "[video_with_vertical_banner]"
            )
        )
        current_video_label = "video_with_vertical_banner"

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
    layout_variant: str = "classic",
    top_panel_color: str | None = None,
    bottom_panel_color: str | None = None,
    text_override_color: str | None = None,
    vertical_banner_input_index: int | None = None,
    vertical_banner_x: int | None = None,
    vertical_banner_y: int | None = None,
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
        layout_variant=layout_variant,
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
    render_ber_icon = (
        ber_icon_input_index is not None
        and overlay_layout.ber_badge_box is not None
        and overlay_layout.ber_badge_box.visible
    )
    if render_ber_icon:
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
    vertical_banner_label: str | None = None
    if vertical_banner_input_index is not None:
        filter_parts.append(
            f"[{vertical_banner_input_index}:v]format=rgba[vertical_banner]"
        )
        vertical_banner_label = "vertical_banner"
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
            ber_icon_label="ber_header_icon" if render_ber_icon else None,
            output_label="vout",
            layout=overlay_layout,
            layout_variant=layout_variant,
            top_panel_color=top_panel_color,
            bottom_panel_color=bottom_panel_color,
            text_override_color=text_override_color,
            vertical_banner_label=vertical_banner_label,
            vertical_banner_x=vertical_banner_x,
            vertical_banner_y=vertical_banner_y,
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
