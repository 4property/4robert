"""Unit tests for the `side_banner` layout variant of build_overlay_layout.

Verifies the geometric branching introduced in Feature 16:

- ``layout_variant="side_banner"`` removes outer margins (full-bleed photo).
- Top panel is a full-width band offset from the top like the reference image.
- Bottom panel is an inset contact card.
- Default (``layout_variant="classic"``) is unchanged — see
  ``test_layout_composition.py`` for the regression coverage.

Feature 16b refinements:

- The top panel status block becomes the literal ``"OFFERS OVER:"`` for
  ``side_banner`` and stays as ``build_status_ribbon_text(...)`` for
  ``classic``.
- When ``has_ber_badge=True`` and the ``side_banner`` variant produces a
  ``details`` text block, the BER badge is aligned inline with that
  details row; ``classic`` keeps the original vertical-center against
  the top panel.
"""

from __future__ import annotations

import pytest

from modules.rendering.infrastructure.formatting import (
    build_status_ribbon_text,
    resolve_ber_icon_size,
)
from modules.rendering.infrastructure.layout import build_overlay_layout
from modules.rendering.infrastructure.layout.models import OverlayLayout
from tests.unit.rendering.conftest import (
    build_property_data,
    build_slide,
    build_template,
)


def test_build_overlay_layout_side_banner_uses_zero_outer_margins() -> None:
    overlay = build_overlay_layout(
        build_property_data(title="Donnybrook, Dublin 4"),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
        layout_variant="side_banner",
    )

    assert isinstance(overlay, OverlayLayout)
    assert overlay.top_panel is not None
    assert overlay.top_panel.x == 0
    assert overlay.top_panel.y == round(1920 * 0.058)
    assert overlay.bottom_panel is not None
    assert overlay.bottom_panel.x == round(1080 * 0.030)


def test_build_overlay_layout_side_banner_uses_reference_top_band_geometry() -> None:
    overlay = build_overlay_layout(
        build_property_data(title="Donnybrook, Dublin 4"),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=False,
        layout_variant="side_banner",
    )

    assert overlay.top_panel is not None
    assert overlay.bottom_panel is not None
    assert overlay.top_panel.width == 1080
    assert overlay.top_panel.height == round(1920 * 0.211)
    assert overlay.bottom_panel.width == round(1080 * 0.94)


def test_build_overlay_layout_classic_outer_margins_preserved() -> None:
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
    overlay_default = build_overlay_layout(
        build_property_data(),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
    )

    assert overlay_classic.top_panel is not None
    assert overlay_default.top_panel is not None
    # The default and explicit-classic must match byte-for-byte.
    assert overlay_classic.top_panel.x == overlay_default.top_panel.x
    assert overlay_classic.top_panel.y == overlay_default.top_panel.y
    assert overlay_classic.top_panel.width == overlay_default.top_panel.width
    # Classic keeps non-zero outer margins.
    assert overlay_classic.top_panel.x > 0
    assert overlay_classic.top_panel.y > 0


def test_build_overlay_layout_side_banner_bottom_panel_is_inset_contact_card() -> None:
    overlay = build_overlay_layout(
        build_property_data(),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
        layout_variant="side_banner",
    )

    assert overlay.bottom_panel is not None
    assert overlay.bottom_panel.x == round(1080 * 0.030)
    assert overlay.bottom_panel.y == round(1920 * 0.781)
    assert overlay.bottom_panel.width == round(1080 * 0.94)


def test_build_overlay_layout_side_banner_status_header_is_offers_over() -> None:
    """Feature 16b — gap #1: side_banner shows the literal above the price."""
    overlay_side = build_overlay_layout(
        build_property_data(price="500000"),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
        layout_variant="side_banner",
    )
    status_blocks_side = [
        block for block in overlay_side.text_blocks if block.block == "status"
    ]
    assert status_blocks_side, "side_banner top panel must include a status block"
    assert status_blocks_side[0].text == "OFFERS OVER:"
    price_blocks_side = [
        block for block in overlay_side.text_blocks if block.block == "price"
    ]
    assert price_blocks_side, "side_banner top panel must include a price block"
    assert price_blocks_side[0].text == "€500,000"
    assert status_blocks_side[0].y < price_blocks_side[0].y


@pytest.mark.parametrize("price", [None, "", "0", "0.00", "-1", "POA"])
def test_build_overlay_layout_side_banner_omits_offers_over_without_positive_price(
    price: str | None,
) -> None:
    overlay_side = build_overlay_layout(
        build_property_data(price=price),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
        layout_variant="side_banner",
    )

    assert all(block.block != "status" for block in overlay_side.text_blocks)
    assert all(block.block != "price" for block in overlay_side.text_blocks)


def test_side_banner_omits_offers_over_without_display_price() -> None:
    overlay_side = build_overlay_layout(
        build_property_data(price="500000", price_display_text=""),
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
        layout_variant="side_banner",
    )

    assert all(block.block != "status" for block in overlay_side.text_blocks)
    assert all(block.block != "price" for block in overlay_side.text_blocks)


def test_build_overlay_layout_classic_status_header_preserved() -> None:
    """Feature 16b — gap #1 regression: classic keeps the dynamic ribbon text."""
    property_data = build_property_data()
    overlay_classic = build_overlay_layout(
        property_data,
        build_template(width=1080, height=1920),
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=False,
        has_agency_logo=True,
        layout_variant="classic",
    )
    status_blocks_classic = [
        block for block in overlay_classic.text_blocks if block.block == "status"
    ]
    assert status_blocks_classic, "classic top panel must include a status block"
    assert status_blocks_classic[0].text == build_status_ribbon_text(property_data)
    # Sanity-check: the dynamic ribbon for our fixture must not collide
    # with the side_banner literal — otherwise the previous assertion is
    # vacuous.
    assert status_blocks_classic[0].text != "OFFERS OVER:"


def test_build_overlay_layout_side_banner_ber_badge_inline_with_details_row() -> None:
    """Feature 16b — gap #3: side_banner aligns BER badge with the specs row.

    The specs row (e.g. "3 beds | 2 baths") is emitted by
    ``measure_address_blocks`` as the ``address_meta`` block.
    """
    template = build_template(width=1080, height=1920)
    overlay = build_overlay_layout(
        build_property_data(ber_rating="A1"),
        template,
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=True,
        has_agency_logo=True,
        layout_variant="side_banner",
    )

    assert overlay.ber_badge_box is not None
    details_blocks = [
        block for block in overlay.text_blocks if block.block == "address_meta"
    ]
    assert details_blocks, "side_banner fixture must produce an address_meta block"
    details_block = details_blocks[0]
    _, ber_icon_height = resolve_ber_icon_size(template)
    expected_ber_y = details_block.y + round(
        (details_block.box_height - ber_icon_height) / 2
    )
    assert overlay.ber_badge_box.y == expected_ber_y
    assert overlay.ber_badge_box.x == round(1080 * 0.36)
    # Belt-and-braces: ensure the badge actually moved down from the
    # top-panel vertical center, which would be the classic position.
    assert overlay.top_panel is not None
    classic_y = overlay.top_panel.y + max(
        0, round((overlay.top_panel.height - ber_icon_height) / 2)
    )
    assert overlay.ber_badge_box.y != classic_y


def test_build_overlay_layout_classic_ber_badge_centered_on_top_panel() -> None:
    """Feature 16b — gap #3 regression: classic keeps the vertical-centered BER."""
    template = build_template(width=1080, height=1920)
    overlay = build_overlay_layout(
        build_property_data(ber_rating="A1"),
        template,
        slides=(build_slide(),),
        slide_duration=2.5,
        has_ber_badge=True,
        has_agency_logo=True,
        layout_variant="classic",
    )

    assert overlay.ber_badge_box is not None
    assert overlay.top_panel is not None
    _, ber_icon_height = resolve_ber_icon_size(template)
    expected_ber_y = overlay.top_panel.y + max(
        0, round((overlay.top_panel.height - ber_icon_height) / 2)
    )
    assert overlay.ber_badge_box.y == expected_ber_y
