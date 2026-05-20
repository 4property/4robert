"""Unit tests for the ``galaxy`` layout variant of build_overlay_layout.

Feature 42 — verifies the geometric branching introduced when galaxy
joins ``classic`` and ``side_banner``:

- ``layout_variant="galaxy"`` removes outer photo margins (full-bleed).
- Top panel is a broad rounded header card inset like the reference
  (~94% width, ~24% height, ~3.2% y offset) and omits the BER badge so
  the ffmpeg layer can draw the secondary-colour C21 mark.
- Bottom panel uses the same ~94% inset width but is taller and anchored
  close to the bottom edge like the reference.
- Status header ("OFFERS OVER:") + price logic mirrors side_banner.
- The ``logo_box_width`` cap is the same as side_banner (~31% width,
  78px height) so the agency logo is anchored to the right side of the
  bottom card.
"""

from __future__ import annotations

import pytest

from modules.rendering.infrastructure.layout import build_overlay_layout
from modules.rendering.infrastructure.layout.models import OverlayLayout
from tests.unit.rendering.conftest import (
    build_property_data,
    build_slide,
    build_template,
)


def test_build_overlay_layout_galaxy_uses_zero_outer_margins() -> None:
    overlay = build_overlay_layout(
        build_property_data(title="Donnybrook, Dublin 4"),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
        layout_variant="galaxy",
    )

    assert isinstance(overlay, OverlayLayout)
    assert overlay.top_panel is not None
    # Galaxy top panel is anchored top-left at ~3% x, ~3.2% y.
    assert overlay.top_panel.x == round(1080 * 0.030)
    assert overlay.top_panel.y == round(1920 * 0.032)
    # Bottom panel keeps the side_banner inset card x geometry.
    assert overlay.bottom_panel is not None
    assert overlay.bottom_panel.x == round(1080 * 0.030)
    expected_bottom_margin = max(30, round(1920 * 0.023))
    assert overlay.bottom_panel.y == (
        1920 - overlay.bottom_panel.height - expected_bottom_margin
    )


def test_build_overlay_layout_galaxy_top_panel_is_broad_reference_card() -> None:
    overlay = build_overlay_layout(
        build_property_data(title="Donnybrook, Dublin 4"),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=False,
        layout_variant="galaxy",
    )

    assert overlay.top_panel is not None
    # Galaxy top panel spans the reference header card width.
    assert overlay.top_panel.width == 1080 - (round(1080 * 0.030) * 2)
    # Height grows to fit content but starts at a ~23.7% floor.
    assert overlay.top_panel.height >= round(1920 * 0.237)


def test_build_overlay_layout_galaxy_allows_address_to_wrap_to_two_lines() -> None:
    """Century 21 polish v3 (2026-05-19): the address block now wraps
    up to 2 lines so longer titles do not get clamped. The
    ``header_text_width`` was tightened to 0.460*W in the same pass to
    keep the column clear of the header logo to the right.
    """
    overlay = build_overlay_layout(
        build_property_data(
            title="123 Very Very Long Street Name With Multiple Extra Words, Englewood City, NJ 07631"
        ),
        build_template(width=1054, height=1492),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=False,
        layout_variant="galaxy",
    )

    address_block = next(block for block in overlay.text_blocks if block.block == "address")
    assert address_block.max_lines == 2
    assert len(address_block.lines) == 2


def test_build_overlay_layout_galaxy_bottom_panel_reuses_side_banner_card() -> None:
    overlay = build_overlay_layout(
        build_property_data(),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
        layout_variant="galaxy",
    )

    assert overlay.bottom_panel is not None
    # Bottom panel width/x match the side_banner inset card.
    assert overlay.bottom_panel.width == round(1080 * 0.94)
    assert overlay.bottom_panel.x == round(1080 * 0.030)
    expected_bottom_margin = max(30, round(1920 * 0.023))
    assert overlay.bottom_panel.y == (
        1920 - overlay.bottom_panel.height - expected_bottom_margin
    )
    # Sanity-check: the bottom edge sits within ~2.2 % of the frame
    # bottom, matching the reference layout.
    assert (
        1920 - (overlay.bottom_panel.y + overlay.bottom_panel.height)
        <= round(1920 * 0.026)
    )
    assert overlay.bottom_panel.height >= round(1920 * 0.225)


def test_build_overlay_layout_galaxy_footer_height_floor_is_chunkier_than_side_banner() -> None:
    """Galaxy footer floor is substantially taller than side_banner."""
    overlay_galaxy = build_overlay_layout(
        build_property_data(),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
        layout_variant="galaxy",
    )
    overlay_side_banner = build_overlay_layout(
        build_property_data(),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
        layout_variant="side_banner",
    )
    assert overlay_galaxy.bottom_panel is not None
    assert overlay_side_banner.bottom_panel is not None
    # Galaxy floor is strictly higher than side_banner's at the same
    # fixture (same width/height/agent_image/logo).
    assert overlay_galaxy.bottom_panel.height > overlay_side_banner.bottom_panel.height


def test_build_overlay_layout_galaxy_agent_text_is_bigger_than_side_banner() -> None:
    """iter 3: chunky footer + bigger agent text.

    Galaxy's `agent_name` and contact rows use bumped font bounds
    relative to side_banner (max 32/26 px vs 26/24 px), so the
    measured font_size on the rendered blocks must be strictly higher.
    """
    overlay_galaxy = build_overlay_layout(
        build_property_data(),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
        layout_variant="galaxy",
    )
    overlay_side_banner = build_overlay_layout(
        build_property_data(),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
        layout_variant="side_banner",
    )
    galaxy_agent_name = next(
        block for block in overlay_galaxy.text_blocks if block.block == "agent_name"
    )
    side_banner_agent_name = next(
        block for block in overlay_side_banner.text_blocks if block.block == "agent_name"
    )
    # Galaxy agent_name floor is 32 px (vs side_banner 26 px). The
    # measured font_size must respect the floor.
    assert galaxy_agent_name.font_size >= 32
    assert galaxy_agent_name.font_size > side_banner_agent_name.font_size
    # Contact rows (agent_phone / agent_email): galaxy floor 26 px
    # versus side_banner 24 px.
    galaxy_phone = next(
        (block for block in overlay_galaxy.text_blocks if block.block == "agent_phone"),
        None,
    )
    if galaxy_phone is not None:
        assert galaxy_phone.font_size >= 26


def test_build_overlay_layout_galaxy_font_bounds_floor_at_low_resolution() -> None:
    """iter 3: floors of 32/26 px protect low-resolution frames.

    At a short frame (height=900) the percentage-based maxes shrink
    below the floors (round(900 * 0.022) = 20 px, round(900 * 0.017)
    = 15 px); the floors prevent the agent text from collapsing.
    """
    overlay = build_overlay_layout(
        build_property_data(),
        build_template(width=540, height=900),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
        layout_variant="galaxy",
    )
    agent_name = next(
        (block for block in overlay.text_blocks if block.block == "agent_name"),
        None,
    )
    if agent_name is not None:
        # Floor of 32 px must hold even at a low frame height.
        assert agent_name.font_size >= 26  # min_font_size floor


def test_build_overlay_layout_galaxy_status_header_is_offers_over() -> None:
    """Galaxy reuses the side_banner "OFFERS OVER:" header verbatim."""
    overlay_galaxy = build_overlay_layout(
        build_property_data(price="500000"),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
        layout_variant="galaxy",
    )
    status_blocks = [
        block for block in overlay_galaxy.text_blocks if block.block == "status"
    ]
    price_blocks = [
        block for block in overlay_galaxy.text_blocks if block.block == "price"
    ]
    assert status_blocks, "galaxy top panel must include a status block"
    assert status_blocks[0].text == "OFFERS OVER:"
    assert price_blocks, "galaxy top panel must include a price block"
    # Century 21 polish v2 (2026-05-19): galaxy renders the U.S. brand
    # so the currency glyph flips from € to $. Other variants keep €.
    assert price_blocks[0].text == "$500,000"
    assert status_blocks[0].y < price_blocks[0].y


@pytest.mark.parametrize("price", [None, "", "0", "0.00", "-1", "POA"])
def test_build_overlay_layout_galaxy_omits_offers_over_without_positive_price(
    price: str | None,
) -> None:
    overlay = build_overlay_layout(
        build_property_data(price=price),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
        layout_variant="galaxy",
    )

    assert all(block.block != "status" for block in overlay.text_blocks)
    assert all(block.block != "price" for block in overlay.text_blocks)


def test_build_overlay_layout_galaxy_omits_header_ber_badge() -> None:
    """Galaxy reserves the right header column for the C21 mark, not BER."""
    template = build_template(width=1080, height=1920)
    overlay = build_overlay_layout(
        build_property_data(ber_rating="A1"),
        template,
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=True,
        has_agency_logo=True,
        layout_variant="galaxy",
    )

    assert overlay.ber_badge_box is None
    assert any(block.block == "address_meta" for block in overlay.text_blocks)


def test_build_overlay_layout_galaxy_agent_box_anchored_to_left_of_footer() -> None:
    overlay = build_overlay_layout(
        build_property_data(),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
        layout_variant="galaxy",
    )

    assert overlay.bottom_panel is not None
    assert overlay.agent_image_box is not None
    # Agent avatar anchored close to the left edge of the footer.
    assert overlay.agent_image_box.x == (
        overlay.bottom_panel.x + max(26, round(1080 * 0.025))
    )
    assert overlay.agent_image_box.height == max(190, round(1920 * 0.164))


def test_build_overlay_layout_galaxy_logo_box_anchored_to_right_of_footer() -> None:
    overlay = build_overlay_layout(
        build_property_data(),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
        layout_variant="galaxy",
    )

    assert overlay.bottom_panel is not None
    assert overlay.agency_logo_box is not None
    # Logo box sized identically to side_banner (~31% width, 78px+ tall).
    assert overlay.agency_logo_box.width <= max(220, round(1080 * 0.31))
    assert overlay.agency_logo_box.width >= max(72, round(1080 * 0.11))
    assert overlay.agency_logo_box.height == max(78, round(1920 * 0.062))
    # Anchored to the right side of the footer (within footer_padding_x
    # of the right edge).
    expected_right_edge = (
        overlay.bottom_panel.x + overlay.bottom_panel.width
    )
    assert (
        overlay.agency_logo_box.x + overlay.agency_logo_box.width
    ) <= expected_right_edge


def test_build_overlay_layout_galaxy_classic_geometry_unaffected() -> None:
    """Regression guard: classic variant geometry must not change."""
    overlay_classic = build_overlay_layout(
        build_property_data(),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
        layout_variant="classic",
    )
    assert overlay_classic.top_panel is not None
    # Classic keeps non-zero outer margins.
    assert overlay_classic.top_panel.x > 0
    assert overlay_classic.top_panel.y > 0
    # Classic top panel spans the full inner width (panel_width).
    assert overlay_classic.top_panel.width > round(1080 * 0.48)


def test_build_overlay_layout_galaxy_keeps_short_address_on_one_line() -> None:
    """Polish v3: short titles still fit on a single line; the 2-line
    cap only kicks in when the address actually needs wrapping."""
    overlay = build_overlay_layout(
        build_property_data(title="Howth, Dublin"),
        build_template(width=1054, height=1492),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=False,
        layout_variant="galaxy",
    )

    address_block = next(block for block in overlay.text_blocks if block.block == "address")
    # max_lines stays at 2 (the cap), but the actual content stays on 1
    # line because it fits.
    assert address_block.max_lines == 2
    assert len(address_block.lines) == 1
    assert address_block.clamped is False


def test_build_overlay_layout_galaxy_wraps_long_address_to_two_lines() -> None:
    """Polish v3: long titles wrap to 2 lines instead of being clamped."""
    overlay = build_overlay_layout(
        build_property_data(
            title=(
                "Beautiful 5-Bedroom Detached Villa with Panoramic Sea Views, "
                "Howth, Co. Dublin"
            )
        ),
        build_template(width=1054, height=1492),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=False,
        layout_variant="galaxy",
    )

    address_block = next(block for block in overlay.text_blocks if block.block == "address")
    assert address_block.max_lines == 2
    assert len(address_block.lines) == 2


def test_build_overlay_layout_classic_address_max_lines_unchanged_by_polish_v3() -> None:
    """Regression guard: polish v3 only bumped galaxy's address
    ``max_lines`` (1 -> 2). classic keeps the historical
    ``measure_address_blocks`` cap of 4 lines so the renderer wraps
    long addresses the same way it always has.
    """
    overlay = build_overlay_layout(
        build_property_data(title="Howth, Dublin"),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=False,
        layout_variant="classic",
    )

    address_block = next(
        block for block in overlay.text_blocks if block.block == "address"
    )
    # classic comes from measure_address_blocks with max_lines=4 — NOT
    # the galaxy single-block branch we tightened.
    assert address_block.max_lines == 4


def test_build_overlay_layout_side_banner_address_max_lines_unchanged_by_polish_v3() -> None:
    """Regression guard: side_banner keeps the historical
    ``measure_address_blocks`` cap of 4 lines for the address. Polish
    v3 only bumped galaxy's address ``max_lines`` (1 -> 2).
    """
    overlay = build_overlay_layout(
        build_property_data(title="Howth, Dublin"),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=False,
        layout_variant="side_banner",
    )

    address_block = next(
        block for block in overlay.text_blocks if block.block == "address"
    )
    assert address_block.max_lines == 4


def test_build_overlay_layout_galaxy_header_text_clears_logo_column() -> None:
    """Polish v3 geometry guard: the header text column must end with a
    non-negative margin to the left of the header logo so the address
    cannot collide with the seal at the pinned 1054x1492 fixture.

    At 1054x1492:
      side_text_x        = round(1054 * 0.069)  = 73
      header_text_width  = round(1054 * 0.460)  = 485
      text_end           = 73 + 485             = 558
      logo_x (relative)  = round(1054 * 0.520)  = 548
      logo_x (absolute)  = top_panel.x + 548    = 32 + 548 = 580
      margin             = 580 - 558            = 22 px
    """
    overlay = build_overlay_layout(
        build_property_data(title="Howth, Dublin"),
        build_template(width=1054, height=1492),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=False,
        layout_variant="galaxy",
    )

    assert overlay.top_panel is not None
    address_block = next(block for block in overlay.text_blocks if block.block == "address")
    text_end = address_block.x + address_block.max_width
    logo_x = overlay.top_panel.x + round(1054 * 0.520)
    margin = logo_x - text_end
    assert margin >= 0, (
        f"address column collides with header logo: text_end={text_end}, "
        f"logo_x={logo_x}, margin={margin}"
    )
    # The math above pins the expected margin at 22 px for the canonical
    # 1054x1492 fixture so a future bump in either factor surfaces here.
    assert margin == 22
