"""Unit tests for `modules.rendering.infrastructure.layout.panels`."""

from __future__ import annotations

from modules.rendering.infrastructure.layout.panels import (
    compose_bottom_panel,
    compose_top_panel,
)
from tests.unit.rendering.conftest import build_property_data, build_template


def _layout_kwargs(template) -> dict[str, int]:
    width = template.width
    height = template.height
    outer_margin_x = max(36, round(width * 0.04))
    outer_margin_y = max(36, round(height * 0.03))
    panel_padding_x = max(26, round(width * 0.024))
    panel_padding_y = max(22, round(height * 0.018))
    panel_width = width - (outer_margin_x * 2)
    return {
        "outer_margin_x": outer_margin_x,
        "outer_margin_y": outer_margin_y,
        "panel_padding_x": panel_padding_x,
        "panel_padding_y": panel_padding_y,
        "panel_width": panel_width,
    }


def test_compose_top_panel_returns_none_when_no_text_blocks() -> None:
    property_data = build_property_data(
        title="",
        price=None,
        property_status=None,
        bedrooms=None,
        bathrooms=None,
        ber_rating=None,
        viewing_times=(),
    )
    template = build_template()
    top_panel, text_blocks, ber_badge_box, warnings = compose_top_panel(
        property_data,
        template,
        has_ber_badge=False,
        **_layout_kwargs(template),
    )
    assert top_panel is None
    assert text_blocks == ()
    assert ber_badge_box is None
    assert warnings == ()


def test_compose_top_panel_includes_status_price_address() -> None:
    property_data = build_property_data()
    template = build_template()
    top_panel, text_blocks, ber_badge_box, _warnings = compose_top_panel(
        property_data,
        template,
        has_ber_badge=False,
        **_layout_kwargs(template),
    )
    assert top_panel is not None
    assert ber_badge_box is None
    block_names = [block.block for block in text_blocks]
    assert "status" in block_names
    assert "price" in block_names
    assert "address" in block_names
    assert all(block.x >= top_panel.x for block in text_blocks)


def test_compose_top_panel_places_ber_badge_when_flag_true() -> None:
    property_data = build_property_data(ber_rating="A1")
    template = build_template()
    kwargs = _layout_kwargs(template)
    top_panel, _text_blocks, ber_badge_box, _warnings = compose_top_panel(
        property_data,
        template,
        has_ber_badge=True,
        **kwargs,
    )
    assert top_panel is not None
    assert ber_badge_box is not None
    assert ber_badge_box.x + ber_badge_box.width <= top_panel.x + top_panel.width
    assert ber_badge_box.y >= top_panel.y
    assert ber_badge_box.y + ber_badge_box.height <= top_panel.y + top_panel.height


def test_compose_bottom_panel_keeps_agent_image_logo_within_bounds() -> None:
    property_data = build_property_data()
    template = build_template()
    kwargs = _layout_kwargs(template)
    (
        bottom_panel,
        text_blocks,
        agent_image_box,
        agency_logo_box,
        _warnings,
    ) = compose_bottom_panel(
        property_data,
        template,
        top_panel=None,
        has_agency_logo=True,
        single_line_contact_email=False,
        **kwargs,
    )
    assert bottom_panel is not None
    assert agency_logo_box is not None
    assert agency_logo_box.x + agency_logo_box.width <= bottom_panel.x + bottom_panel.width
    assert agency_logo_box.y >= bottom_panel.y
    assert agency_logo_box.y + agency_logo_box.height <= bottom_panel.y + bottom_panel.height
    if agent_image_box is not None:
        assert agent_image_box.x >= bottom_panel.x
        assert agent_image_box.y >= bottom_panel.y
    for block in text_blocks:
        assert block.x >= bottom_panel.x
        assert block.x + block.max_width <= bottom_panel.x + bottom_panel.width


def test_compose_bottom_panel_returns_blocks_in_agent_block_order() -> None:
    property_data = build_property_data(
        agent_name="Jane Doe",
        agent_number="+353 1 234 5678",
        agent_email="jane@example.com",
        agency_psra="PSRA 1234",
    )
    template = build_template()
    kwargs = _layout_kwargs(template)
    (_bp, text_blocks, _img, _logo, _w) = compose_bottom_panel(
        property_data,
        template,
        top_panel=None,
        has_agency_logo=False,
        single_line_contact_email=False,
        **kwargs,
    )
    block_names = [block.block for block in text_blocks]
    expected_known = ["agent_name", "agent_phone", "agent_email"]
    filtered = [name for name in block_names if name in expected_known]
    assert filtered == expected_known


def test_compose_bottom_panel_y_shifts_with_footer_offset() -> None:
    property_data = build_property_data()
    default_template = build_template(width=360, height=640, footer_bottom_offset_px=0)
    shifted_template = build_template(width=360, height=640, footer_bottom_offset_px=48)

    default_panel, *_ = compose_bottom_panel(
        property_data,
        default_template,
        top_panel=None,
        has_agency_logo=True,
        single_line_contact_email=False,
        **_layout_kwargs(default_template),
    )
    shifted_panel, *_ = compose_bottom_panel(
        property_data,
        shifted_template,
        top_panel=None,
        has_agency_logo=True,
        single_line_contact_email=False,
        **_layout_kwargs(shifted_template),
    )
    assert default_panel is not None
    assert shifted_panel is not None
    assert default_panel.y - shifted_panel.y == 48
