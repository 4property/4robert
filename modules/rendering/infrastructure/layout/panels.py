"""Top and bottom panel composition for the property-reel overlay.

Extracted verbatim (with kwarg-only signatures) from
`services.media.reel_rendering.layout.build_overlay_layout` as part of
feature 15 (`rendering_layout_split`). The phase A (top panel) and phase B
(bottom panel) bodies are preserved byte-for-byte; what previously were
locals in `build_overlay_layout` (`outer_margin_x`, `panel_padding_x`,
`panel_width`, ...) become explicit keyword arguments.

Note: imports from `services.media.reel_rendering.formatting` and
`services.media.reel_rendering.models` are a transitional cross-frontier
dependency removed by feature 18 when `services/` is retired.
"""

from __future__ import annotations

from modules.rendering.infrastructure.layout.models import (
    BoxLayout,
    LayoutWarning,
    TextBlockLayout,
)
from modules.rendering.infrastructure.layout.text_measurement import (
    MeasuredTextBlock,
    _measure_text_block_with_single_line_preference,
    measure_address_blocks,
    measure_text_block,
)
from modules.rendering.infrastructure.formatting import (
    build_agent_lines,
    build_display_price,
    build_property_header_details_line,
    build_property_header_viewing_times_line,
    build_status_ribbon_text,
    has_positive_price,
    resolve_agency_logo_box_size,
    resolve_agent_image_size,
    resolve_ber_icon_size,
    resolve_font_size_bounds,
)
from modules.rendering.infrastructure.models import PropertyReelData, PropertyReelTemplate

_SINGLE_LINE_TEXT_BLOCKS = frozenset({"price", "agent_phone", "agent_email", "agency_psra"})


def _resolve_top_panel_height_range(settings: PropertyReelTemplate) -> tuple[int, int]:
    return max(160, round(settings.height * 0.13)), max(340, round(settings.height * 0.34))


def _resolve_bottom_panel_height_range(settings: PropertyReelTemplate) -> tuple[int, int]:
    return max(208, round(settings.height * 0.145)), max(500, round(settings.height * 0.34))


def _resolve_bottom_panel_y(
    *,
    frame_height: int,
    outer_margin_y: int,
    panel_height: int,
    footer_bottom_offset_px: int,
    top_panel: BoxLayout | None,
    vertical_gap: int,
) -> int:
    minimum_y = outer_margin_y
    if top_panel is not None:
        minimum_y = top_panel.y + top_panel.height + vertical_gap
    return max(
        minimum_y,
        frame_height - outer_margin_y - footer_bottom_offset_px - panel_height,
    )


def _build_galaxy_header_details_line(property_data: PropertyReelData) -> str | None:
    facts: list[str] = []
    if property_data.bedrooms is not None and property_data.bedrooms > 0:
        facts.append(f"{property_data.bedrooms} BR")
    if property_data.bathrooms is not None and property_data.bathrooms > 0:
        facts.append(f"{property_data.bathrooms} BA")
    if not facts:
        return None
    return " | ".join(facts)


def compose_top_panel(
    property_data: PropertyReelData,
    settings: PropertyReelTemplate,
    *,
    has_ber_badge: bool,
    outer_margin_x: int,
    outer_margin_y: int,
    panel_padding_x: int,
    panel_padding_y: int,
    panel_width: int,
    layout_variant: str = "classic",
) -> tuple[
    BoxLayout | None,
    tuple[TextBlockLayout, ...],
    BoxLayout | None,
    tuple[LayoutWarning, ...],
]:
    width = settings.width
    height = settings.height
    is_side_banner = layout_variant == "side_banner"
    # Galaxy keeps the side_banner sale/price contract but uses its own
    # reference geometry: a broad header card, larger type, and a
    # secondary-colour C21 mark in the right half of the panel.
    is_galaxy = layout_variant == "galaxy"
    is_side_banner_like = is_side_banner or is_galaxy
    effective_has_ber_badge = has_ber_badge and not is_galaxy
    warnings: list[LayoutWarning] = []
    ber_badge_box: BoxLayout | None = None
    ber_icon_gap = max(24, round(width * 0.018))
    ber_icon_width, ber_icon_height = resolve_ber_icon_size(settings)
    if is_side_banner_like:
        side_text_x = (
            max(panel_padding_x, round(width * 0.069))
            if is_galaxy
            else max(panel_padding_x, round(width * 0.086))
        )
        # side_banner keeps its historical 0.36 BER column. Galaxy no
        # longer renders BER in the header; the value below is retained
        # only so the shared arithmetic stays simple.
        side_ber_x = (
            round(width * 0.36)
            if is_side_banner
            else round(width * 0.61)
        )
        # Century 21 polish v3 (2026-05-19): galaxy tightens the
        # ``header_text_width`` from polish v2's 0.54*W to 0.460*W so the
        # address column ends safely to the left of the header logo
        # (now anchored at ``top_panel.x + round(W*0.520)``, see
        # ``_append_galaxy_header_logo_overlay``). At 1054 the column
        # ends at 73+round(1054*0.460)=558 vs logo_x=580 -> 22 px of
        # safety. side_banner keeps the historical 0.54 / floor 300
        # cascade so its layout is byte-for-byte identical.
        if is_galaxy:
            header_text_width = round(width * 0.460)
        else:
            header_text_width = max(
                300,
                (
                    side_ber_x - side_text_x - ber_icon_gap
                    if effective_has_ber_badge
                    else round(width * 0.54)
                ),
            )
        if is_galaxy:
            status_max_font_size = max(34, round(height * 0.023))
            status_min_font_size = max(28, round(height * 0.018))
            price_max_font_size = max(72, round(height * 0.050))
            price_min_font_size = max(56, round(height * 0.038))
            address_max_font_size = max(40, round(height * 0.027))
            address_min_font_size = max(30, round(height * 0.020))
        else:
            status_max_font_size = max(24, round(height * 0.014))
            status_min_font_size = max(20, round(height * 0.010))
            price_max_font_size = max(48, round(height * 0.033))
            price_min_font_size = max(32, round(height * 0.023))
            address_max_font_size = max(34, round(height * 0.021))
            address_min_font_size = max(24, round(height * 0.014))
    else:
        header_text_width = panel_width - (panel_padding_x * 2)
        if effective_has_ber_badge:
            header_text_width = max(260, header_text_width - ber_icon_width - ber_icon_gap)
        status_max_font_size, status_min_font_size = resolve_font_size_bounds(
            "status",
            frame_height=height,
            subtitle_font_size=settings.subtitle_font_size,
        )
        price_max_font_size, price_min_font_size = resolve_font_size_bounds(
            "price",
            frame_height=height,
            subtitle_font_size=settings.subtitle_font_size,
        )
        address_max_font_size, address_min_font_size = resolve_font_size_bounds(
            "address",
            frame_height=height,
            subtitle_font_size=settings.subtitle_font_size,
        )

    # Century 21 polish v2 (2026-05-19): galaxy renders prices with "$"
    # instead of "€"; classic and side_banner keep the historical euro
    # glyph byte-for-byte by passing the default symbol.
    resolved_price_text = build_display_price(
        property_data,
        currency_symbol="$" if is_galaxy else "€",
    )
    side_banner_has_price = (
        is_side_banner_like
        and has_positive_price(property_data)
        and bool(resolved_price_text)
    )

    # Feature 16b — gap #1: the side_banner variant replaces the status
    # ribbon text with a hardcoded "OFFERS OVER:" label when a positive
    # numeric price exists, so the top panel does not duplicate the
    # vertical banner. The classic variant keeps the dynamic
    # `build_status_ribbon_text(...)` value (e.g. "FOR SALE") untouched.
    # Feature 42: galaxy reuses the side_banner contract verbatim — the
    # vertical ribbon (preparation.py) already draws "FOR SALE", so the
    # top panel shows "OFFERS OVER:" + price and skips the dynamic
    # ribbon label.
    if side_banner_has_price:
        status_text: str | None = "OFFERS OVER:"
    else:
        status_text = (
            None
            if is_side_banner_like
            else build_status_ribbon_text(property_data)
        )
    price_text = (
        resolved_price_text
        if not is_side_banner_like or side_banner_has_price
        else None
    )

    top_blocks: list[MeasuredTextBlock] = []
    for measured_block in (
        _measure_text_block_with_single_line_preference(
            block="status",
            text=status_text,
            usable_width=header_text_width,
            preferred_min_chars=6,
            fallback_max_lines=2,
            max_font_size=status_max_font_size,
            min_font_size=status_min_font_size,
            fallback_min_chars=8,
        ),
        measure_text_block(
            block="price",
            text=price_text,
            usable_width=header_text_width,
            max_lines=1,
            max_font_size=price_max_font_size,
            min_font_size=price_min_font_size,
            min_chars=8,
        ),
    ):
        if measured_block is None:
            continue
        top_blocks.append(measured_block)
        if measured_block.warning is not None:
            warnings.append(measured_block.warning)

    if is_galaxy:
        # Century 21 polish v3 (2026-05-19): allow the address to wrap
        # up to 2 lines (``header_text_width`` was tightened to 0.460*W
        # in tandem to keep the column clear of the header logo to the
        # right). ``viewing_times`` and ``address_meta`` still wrap to
        # at most 1 line so the header keeps a 3-block rhythm.
        address_candidates = (
            measure_text_block(
                block="address",
                text=property_data.title,
                usable_width=header_text_width,
                max_lines=2,
                max_font_size=address_max_font_size,
                min_font_size=address_min_font_size,
                min_chars=18,
            ),
            measure_text_block(
                block="viewing_times",
                text=build_property_header_viewing_times_line(property_data),
                usable_width=header_text_width,
                max_lines=1,
                max_font_size=address_max_font_size,
                min_font_size=address_min_font_size,
                min_chars=18,
            ),
            measure_text_block(
                block="address_meta",
                text=_build_galaxy_header_details_line(property_data),
                usable_width=header_text_width,
                max_lines=1,
                max_font_size=address_max_font_size,
                min_font_size=address_min_font_size,
                min_chars=10,
            ),
        )
        for measured_block in address_candidates:
            if measured_block is None:
                continue
            top_blocks.append(measured_block)
            if measured_block.warning is not None:
                warnings.append(measured_block.warning)
    else:
        for measured_block in measure_address_blocks(
            address=property_data.title,
            viewing_times=build_property_header_viewing_times_line(property_data),
            details=build_property_header_details_line(
                property_data,
                compact_room_labels=is_side_banner,
            ),
            usable_width=header_text_width,
            max_lines=4,
            max_font_size=address_max_font_size,
            min_font_size=address_min_font_size,
            min_chars=18,
        ):
            top_blocks.append(measured_block)
            if measured_block.warning is not None:
                warnings.append(measured_block.warning)

    top_panel: BoxLayout | None = None
    text_blocks: list[TextBlockLayout] = []
    if top_blocks:
        top_gap = max(
            10 if is_galaxy else 8,
            round(height * (0.009 if is_galaxy else 0.007 if is_side_banner_like else 0.006)),
        )
        top_content_height = sum(block.box_height for block in top_blocks) + (top_gap * (len(top_blocks) - 1))
        top_content_offset_y = (
            max(panel_padding_y, round(height * (0.035 if is_galaxy else 0.081)))
            if is_side_banner_like
            else panel_padding_y
        )
        if is_galaxy:
            # Galaxy matches the reference card: a broad translucent
            # header inset from both sides with the ribbon floating on
            # top. Height grows to fit content with a floor near 24% of
            # the frame height.
            top_panel_height = max(
                round(height * 0.237),
                top_content_offset_y + top_content_height + panel_padding_y,
            )
            top_panel_y = round(height * 0.032)
            top_panel_x = round(width * 0.030)
            top_panel_visible_width = width - (top_panel_x * 2)
        elif is_side_banner:
            top_panel_height = max(
                round(height * 0.211),
                top_content_offset_y + top_content_height + panel_padding_y,
            )
            top_panel_y = round(height * 0.058)
            top_panel_x = outer_margin_x
            top_panel_visible_width = panel_width
        else:
            top_min_height, top_max_height = _resolve_top_panel_height_range(settings)
            top_panel_height = min(top_max_height, max(top_min_height, top_content_height + (panel_padding_y * 2)))
            top_panel_y = outer_margin_y
            top_panel_x = outer_margin_x
            top_panel_visible_width = panel_width
        top_panel = BoxLayout(
            visible=True,
            x=top_panel_x,
            y=top_panel_y,
            width=top_panel_visible_width,
            height=top_panel_height,
        )
        cursor_y = top_panel.y + top_content_offset_y
        if is_galaxy:
            text_x = side_text_x
        elif is_side_banner:
            text_x = side_text_x
        else:
            text_x = top_panel.x + panel_padding_x
        for block in top_blocks:
            text_blocks.append(
                TextBlockLayout(
                    block=block.block,
                    visible=True,
                    text=block.text,
                    lines=block.lines,
                    font_size=block.font_size,
                    x=text_x,
                    y=cursor_y,
                    max_width=block.max_width,
                    line_gap=block.line_gap,
                    box_height=block.box_height,
                    max_lines=block.max_lines,
                    clamped=block.clamped,
                )
            )
            cursor_y += block.box_height + top_gap
        if effective_has_ber_badge:
            # Feature 16b — gap #3: in `side_banner` the BER badge moves
            # from the vertical center of the top panel to inline with
            # the property specs row (the `address_meta` block, e.g.
            # "108m² | 3 beds | 2 baths" rendered below the address),
            # matching the reference layout. `classic` keeps the
            # original vertical-centered position.
            # Galaxy and side_banner both align BER to the details row;
            # only the x column differs.
            details_block = next(
                (block for block in text_blocks if block.block == "address_meta"),
                None,
            )
            if is_side_banner_like and details_block is not None:
                ber_y = details_block.y + round(
                    (details_block.box_height - ber_icon_height) / 2
                )
                ber_x = side_ber_x
            else:
                ber_y = top_panel.y + max(
                    0,
                    round((top_panel.height - ber_icon_height) / 2),
                )
                ber_x = top_panel.x + top_panel.width - panel_padding_x - ber_icon_width
            ber_badge_box = BoxLayout(
                visible=True,
                x=ber_x,
                y=ber_y,
                width=ber_icon_width,
                height=ber_icon_height,
            )

    return top_panel, tuple(text_blocks), ber_badge_box, tuple(warnings)


def compose_bottom_panel(
    property_data: PropertyReelData,
    settings: PropertyReelTemplate,
    *,
    top_panel: BoxLayout | None,
    has_agency_logo: bool,
    single_line_contact_email: bool,
    outer_margin_x: int,
    outer_margin_y: int,
    panel_padding_x: int,
    panel_padding_y: int,
    panel_width: int,
    layout_variant: str = "classic",
) -> tuple[
    BoxLayout | None,
    tuple[TextBlockLayout, ...],
    BoxLayout | None,
    BoxLayout | None,
    tuple[LayoutWarning, ...],
]:
    width = settings.width
    height = settings.height
    is_side_banner = layout_variant == "side_banner"
    # Galaxy shares the side_banner full-bleed footer family, but the
    # reference needs a larger avatar, tighter left padding, and a much
    # taller card.
    is_galaxy = layout_variant == "galaxy"
    is_side_banner_like = is_side_banner or is_galaxy
    warnings: list[LayoutWarning] = []

    agent_image_size = resolve_agent_image_size(settings)
    if is_galaxy:
        agent_image_size = max(190, round(height * 0.164))
    elif is_side_banner:
        agent_image_size = min(agent_image_size, max(128, round(height * 0.089)))
    agent_lines = build_agent_lines(property_data)
    if has_agency_logo:
        logo_box_width, logo_box_height = resolve_agency_logo_box_size(settings)
        if is_side_banner_like:
            logo_box_width = max(220, round(width * 0.31))
            logo_box_height = max(78, round(height * 0.062))
    else:
        logo_box_width, logo_box_height = (0, 0)
    effective_panel_width = (
        round(width * 0.94) if is_side_banner_like else panel_width
    )
    footer_padding_x = (
        max(panel_padding_x, round(width * 0.025))
        if is_galaxy
        else max(panel_padding_x, round(width * 0.082))
        if is_side_banner
        else panel_padding_x
    )
    footer_padding_y = (
        max(18, round(height * 0.012))
        if is_side_banner_like
        else panel_padding_y
    )
    content_width = effective_panel_width - (footer_padding_x * 2)
    minimum_text_width = max(220, round(width * 0.24))
    agent_gap = (
        max(24, round(width * 0.027))
        if is_side_banner_like and agent_image_size > 0
        else panel_padding_x if agent_image_size > 0 else 0
    )
    logo_gap = (
        max(32, round(width * 0.04))
        if is_side_banner_like and has_agency_logo
        else panel_padding_x if has_agency_logo else 0
    )
    text_width = content_width - agent_image_size - agent_gap - logo_box_width - logo_gap

    logo_min_width = max(72, round(width * 0.11)) if has_agency_logo else 0
    if has_agency_logo and text_width < minimum_text_width:
        reducible_logo_width = max(0, logo_box_width - logo_min_width)
        reduction = min(reducible_logo_width, minimum_text_width - text_width)
        logo_box_width -= reduction
        text_width += reduction

    agent_min_size = max(92, round(height * 0.07))
    if agent_image_size > 0 and text_width < minimum_text_width:
        reducible_agent_width = max(0, agent_image_size - agent_min_size)
        reduction = min(reducible_agent_width, minimum_text_width - text_width)
        agent_image_size -= reduction
        text_width += reduction

    if text_width < minimum_text_width and agent_image_size > 0:
        text_width += agent_image_size + agent_gap
        agent_image_size = 0
        agent_gap = 0

    if has_agency_logo and text_width < minimum_text_width:
        text_width += max(0, logo_box_width - logo_min_width)
        logo_box_width = logo_min_width

    text_width = max(180, text_width)

    def bottom_font_bounds(block_name: str) -> tuple[int, int]:
        if is_galaxy:
            # Feature 42 iter 3: the reference shows the agent name
            # noticeably larger / bolder than the contact rows; the
            # side_banner bounds (max 26, max 24) felt cramped at 1492
            # px tall. Galaxy bumps agent_name to a max ≈ round(h *
            # 0.022) (≈ 33 px @ 1492) with a 32 px floor — and the
            # contact rows (phone, email, agency psra) to a max ≈
            # round(h * 0.017) (≈ 25-26 px @ 1492) with a 26 px floor.
            # Floors of 32/26 px protect low-resolution frames.
            if block_name == "agent_name":
                return (
                    max(32, round(height * 0.022)),
                    max(26, round(height * 0.016)),
                )
            return (
                max(26, round(height * 0.017)),
                max(22, round(height * 0.013)),
            )
        if is_side_banner:
            if block_name == "agent_name":
                return (
                    max(26, round(height * 0.016)),
                    max(20, round(height * 0.012)),
                )
            return (
                max(24, round(height * 0.015)),
                max(18, round(height * 0.011)),
            )
        return resolve_font_size_bounds(
            block_name,
            frame_height=height,
            subtitle_font_size=settings.subtitle_font_size,
        )

    bottom_blocks: list[MeasuredTextBlock] = []
    agent_name_text = agent_lines[0] if agent_lines else None
    for measured_block in (
        measure_text_block(
            block="agent_name",
            text=agent_name_text,
            usable_width=text_width,
            max_lines=2,
            max_font_size=bottom_font_bounds("agent_name")[0],
            min_font_size=bottom_font_bounds("agent_name")[1],
            min_chars=14,
        ),
        *(
            measure_text_block(
                block=block_name,
                text=block_text,
                usable_width=text_width,
                max_lines=1 if block_name in _SINGLE_LINE_TEXT_BLOCKS else 2,
                max_font_size=bottom_font_bounds(block_name)[0],
                min_font_size=(
                    min(
                        bottom_font_bounds(block_name)[0],
                        14,
                    )
                    if block_name == "agent_email" and single_line_contact_email
                    else bottom_font_bounds(block_name)[1]
                ),
                min_chars=16,
                char_width_floor=(
                    8.0
                    if block_name == "agent_email" and single_line_contact_email
                    else 12.0
                ),
            )
            for block_name, block_text in zip(
                ("agent_phone", "agent_email", "agency_psra"),
                agent_lines[1:4],
                strict=False,
            )
        ),
    ):
        if measured_block is None:
            continue
        bottom_blocks.append(measured_block)
        if measured_block.warning is not None:
            warnings.append(measured_block.warning)

    show_agent_panel = bool(bottom_blocks or agent_image_size > 0 or has_agency_logo)
    bottom_panel: BoxLayout | None = None
    agent_image_box: BoxLayout | None = None
    agency_logo_box: BoxLayout | None = None
    text_blocks: list[TextBlockLayout] = []
    if show_agent_panel:
        bottom_gap = (
            max(26, round(height * 0.023))
            if is_galaxy
            else max(6, round(height * 0.004))
        )
        text_height = (
            sum(block.box_height for block in bottom_blocks)
            + (bottom_gap * (len(bottom_blocks) - 1 if bottom_blocks else 0))
        )
        bottom_min_height, bottom_max_height = _resolve_bottom_panel_height_range(settings)
        if is_galaxy:
            # Galaxy footer matches the reference's chunky lower card:
            # roughly 22.5% of the frame height with a large avatar
            # and generous brand/logo area.
            bottom_panel_height = max(
                round(height * 0.225),
                max(text_height, agent_image_size, logo_box_height) + (footer_padding_y * 2),
            )
        elif is_side_banner:
            # Feature 42: side_banner footer card geometry (94% width
            # inset, ~11.3 % min height anchored at 78.1% from the top).
            bottom_panel_height = max(
                round(height * 0.113),
                max(text_height, agent_image_size, logo_box_height) + (footer_padding_y * 2),
            )
        else:
            bottom_panel_height = min(
                bottom_max_height,
                max(bottom_min_height, max(text_height, agent_image_size, logo_box_height) + (footer_padding_y * 2)),
            )
        if is_galaxy:
            galaxy_bottom_margin = max(30, round(height * 0.023))
            bottom_panel_y = height - bottom_panel_height - galaxy_bottom_margin
        elif is_side_banner:
            bottom_panel_y = round(height * 0.781)
        else:
            bottom_panel_y = _resolve_bottom_panel_y(
                frame_height=height,
                outer_margin_y=outer_margin_y,
                panel_height=bottom_panel_height,
                footer_bottom_offset_px=max(0, settings.footer_bottom_offset_px),
                top_panel=top_panel,
                vertical_gap=max(panel_padding_y, round(height * 0.02)),
            )
        bottom_panel = BoxLayout(
            visible=True,
            x=(
                round(width * 0.030)
                if is_side_banner_like
                else outer_margin_x
            ),
            y=bottom_panel_y,
            width=effective_panel_width,
            height=bottom_panel_height,
        )
        if agent_image_size > 0:
            agent_image_box = BoxLayout(
                visible=True,
                x=(
                    bottom_panel.x + footer_padding_x
                    if is_side_banner_like
                    else bottom_panel.x + panel_padding_x
                ),
                y=bottom_panel.y + max(footer_padding_y, round((bottom_panel.height - agent_image_size) / 2)),
                width=agent_image_size,
                height=agent_image_size,
            )
        if has_agency_logo and logo_box_width > 0 and logo_box_height > 0:
            agency_logo_box = BoxLayout(
                visible=True,
                x=(
                    bottom_panel.x
                    + bottom_panel.width
                    - max(footer_padding_x, round(width * 0.061))
                    - logo_box_width
                    if is_side_banner_like
                    else bottom_panel.x + bottom_panel.width - panel_padding_x - logo_box_width
                ),
                y=bottom_panel.y + max(footer_padding_y, round((bottom_panel.height - logo_box_height) / 2)),
                width=logo_box_width,
                height=logo_box_height,
            )
        if agent_image_box is None:
            text_x = bottom_panel.x + footer_padding_x
        elif is_galaxy:
            separator_x = (
                agent_image_box.x
                + agent_image_box.width
                + max(14, round(width * 0.014))
            )
            text_x = separator_x + max(22, round(width * 0.022))
        elif is_side_banner:
            text_x = bottom_panel.x + round(width * 0.267)
        else:
            text_x = agent_image_box.x + agent_image_box.width + panel_padding_x
        cursor_y = (
            bottom_panel.y + max(footer_padding_y, round(height * (0.063 if is_galaxy else 0.030)))
            if is_side_banner_like
            else bottom_panel.y + footer_padding_y
        )
        contact_icon_slot = max(34, round(width * 0.040)) if is_galaxy else 0
        for block in bottom_blocks:
            block_x = (
                text_x + contact_icon_slot
                if is_galaxy and block.block in {"agent_phone", "agent_email"}
                else text_x
            )
            text_blocks.append(
                TextBlockLayout(
                    block=block.block,
                    visible=True,
                    text=block.text,
                    lines=block.lines,
                    font_size=block.font_size,
                    x=block_x,
                    y=cursor_y,
                    max_width=block.max_width,
                    line_gap=block.line_gap,
                    box_height=block.box_height,
                    max_lines=block.max_lines,
                    clamped=block.clamped,
                )
            )
            cursor_y += block.box_height + bottom_gap

    return (
        bottom_panel,
        tuple(text_blocks),
        agent_image_box,
        agency_logo_box,
        tuple(warnings),
    )


__all__ = ["compose_bottom_panel", "compose_top_panel"]
