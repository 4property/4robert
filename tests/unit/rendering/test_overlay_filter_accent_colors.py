"""Unit tests for the parametrizable panel colors in `build_overlay_filter`.

Verifies Feature 16 wiring:

- ``top_panel_color`` / ``bottom_panel_color`` override the ``drawbox``
  ``color=`` argument when provided; defaults remain the classic
  ``black@0.38`` / ``black@0.46`` so old renders are byte-identical.
- ``vertical_banner_label`` adds an overlay step with the provided x/y.
- ``layout_variant="side_banner"`` produces zero outer margins.
- ``text_override_color`` substitutes the per-block ``fontcolor`` for the
  text drawn inside the colored panels.
"""

from __future__ import annotations

from modules.rendering.infrastructure.ffmpeg.filters import build_filter_complex, build_overlay_filter
from modules.rendering.infrastructure.poster import _build_poster_filter_script
from tests.unit.rendering.conftest import build_property_data, build_slide, build_template


def test_overlay_filter_defaults_preserve_classic_panel_colors() -> None:
    script = build_overlay_filter(
        build_property_data(),
        build_template(width=1080, height=1920),
        slide_captions=("Caption",),
        slide_duration=2.5,
    )
    assert "color=black@0.38" in script
    assert "color=black@0.46" in script


def test_overlay_filter_supports_top_and_bottom_panel_color_overrides() -> None:
    script = build_overlay_filter(
        build_property_data(),
        build_template(width=1080, height=1920),
        slide_captions=("Caption",),
        slide_duration=2.5,
        top_panel_color="0xe22f8c@0.85",
        bottom_panel_color="0xe22f8c@0.85",
    )
    assert "color=0xe22f8c@0.85" in script
    # Classic defaults must NOT leak through when an override is supplied.
    assert "color=black@0.38" not in script
    assert "color=black@0.46" not in script


def test_overlay_filter_side_banner_uses_reference_panel_positions() -> None:
    script_classic = build_overlay_filter(
        build_property_data(),
        build_template(width=1080, height=1920),
        slide_captions=("Caption",),
        slide_duration=2.5,
        layout_variant="classic",
    )
    script_side = build_overlay_filter(
        build_property_data(title="Donnybrook, Dublin 4"),
        build_template(width=1080, height=1920),
        slide_captions=("Caption",),
        slide_duration=2.5,
        layout_variant="side_banner",
    )
    # The classic script has non-zero panel x/y coordinates from outer
    # margins; side_banner uses the reference top band and inset footer card.
    assert "drawbox=x=0:y=111:w=1080:h=405" in script_side
    assert "color=c=black:s=1015x217" in script_side
    assert "overlay=x=32:y=1500[video_with_side_banner_footer_panel]" in script_side
    assert "drawbox=x=32:y=1500:w=1015:h=217" not in script_side
    assert "drawbox=x=0:y=111:w=1080:h=405" not in script_classic


def test_overlay_filter_side_banner_footer_panel_has_rounded_alpha_mask() -> None:
    script = build_overlay_filter(
        build_property_data(title="Donnybrook, Dublin 4"),
        build_template(width=1080, height=1920),
        slide_captions=("Caption",),
        slide_duration=2.5,
        layout_variant="side_banner",
    )

    assert "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)'" in script
    assert "max(max(24-X\\,X-990)\\,0)" in script
    assert "max(max(24-Y\\,Y-192)\\,0)" in script
    assert "\\,576)\\,117\\,0)'[side_banner_footer_panel]" in script


def test_overlay_filter_includes_vertical_banner_overlay() -> None:
    script = build_overlay_filter(
        build_property_data(),
        build_template(width=1080, height=1920),
        slide_captions=("Caption",),
        slide_duration=2.5,
        layout_variant="side_banner",
        vertical_banner_label="vertical_banner",
        vertical_banner_x=900,
        vertical_banner_y=200,
    )
    assert "[vertical_banner]overlay=x=900:y=200" in script


def test_overlay_filter_text_override_color_applied_to_text_blocks() -> None:
    script = build_overlay_filter(
        build_property_data(),
        build_template(width=1080, height=1920),
        slide_captions=("Caption",),
        slide_duration=2.5,
        text_override_color="#e22f8c",
    )
    # All drawtext layers for the colored panels use the override (in
    # ffmpeg's 0xRRGGBB notation).
    assert "fontcolor=0xe22f8c" in script


def test_galaxy_footer_uses_secondary_for_agent_name_icons_and_separator() -> None:
    script = build_overlay_filter(
        build_property_data(side_banner_ribbon_background_color="#C9A24B"),
        build_template(width=1054, height=1492),
        slide_captions=("Caption",),
        slide_duration=2.5,
        layout_variant="galaxy",
    )

    assert "text='Jane Doe':fontcolor=0xc9a24b" in script
    assert "drawbox=x=318:y=1202:w=3:h=176:color=0xc9a24b:t=fill" in script
    assert "assets/render-templates/century21/phone.png" in script
    assert "assets/render-templates/century21/mail.png" in script
    # The old hand-drawn icon strokes were visibly distorted; Century 21
    # uses rasterized icon assets instead.
    assert script.count("color=0xc9a24b:t=fill") == 1
    assert "color=0xc9a24b@0.95:t=fill" not in script
    assert "text='+353 1 234 5678':fontcolor=white:fontsize=26:x=383" in script
    assert "text='jane@example.com':fontcolor=white:fontsize=26:x=383" in script


def test_galaxy_header_uses_century21_logo_asset_instead_of_ber() -> None:
    script = build_overlay_filter(
        build_property_data(
            ber_rating="A1",
            side_banner_ribbon_background_color="#C9A24B",
        ),
        build_template(width=1054, height=1492),
        slide_captions=("Caption",),
        slide_duration=2.5,
        layout_variant="galaxy",
        ber_icon_label="ber_header_icon",
    )

    assert "assets/render-templates/century21/header-logo.png" in script
    # Century 21 polish v2: logo bumped +50% (0.225*W x 0.174*H, with
    # floors 192/210) and re-anchored to the vertical center of the
    # top panel so the larger asset cannot overflow the card bottom.
    # At 1054x1492 the top_panel is y=48 h=354, so the centered logo
    # sits at y = 48 + (354-260)//2 = 95.
    # Century 21 polish v3: horizontal anchor shifted 0.558*W -> 0.520*W
    # so at 1054 the logo_x = 32 + round(1054*0.520) = 32 + 548 = 580.
    assert "scale=w=237:h=260[galaxy_header_logo_source]" in script
    assert "overlay=x=580:y=95[video_with_galaxy_header_logo]" in script
    assert "text='C':fontcolor=0xc9a24b" not in script
    assert "ber_header_icon" not in script


def test_galaxy_filter_complex_does_not_create_unused_ber_stream() -> None:
    script = build_filter_complex(
        build_property_data(
            ber_rating="A1",
            side_banner_ribbon_background_color="#C9A24B",
        ),
        build_template(width=1054, height=1492),
        slides=(build_slide(),),
        slide_frames=1,
        slide_duration=2.5,
        logo_input_index=None,
        agent_image_input_index=1,
        ber_icon_input_index=2,
        layout_variant="galaxy",
    )

    assert "ber_header_icon" not in script
    assert "assets/render-templates/century21/header-logo.png" in script


def test_galaxy_poster_uses_full_bleed_photo_crop() -> None:
    script = _build_poster_filter_script(
        property_data=build_property_data(),
        settings=build_template(width=1054, height=1492),
        include_agency_logo=False,
        include_ber_icon=False,
        agent_input_index=1,
        agency_logo_input_index=None,
        ber_icon_input_index=None,
        layout_variant="galaxy",
    )

    assert "crop=1054:1492,format=yuv420p,setsar=1[poster_base]" in script
    assert "poster_blurred_background" not in script
    assert "[poster_photo]" not in script


def test_side_banner_poster_panels_use_brand_primary_panel_color() -> None:
    """Hotfix 2026-05-15: ``side_banner_panel_color`` (brand primary)
    paints the panels with the 0.55 alpha overlay. The previous wiring
    pulled from ``accent_background_color`` (webhook); the new wiring
    ignores the webhook accent feed entirely.
    """
    script = _build_poster_filter_script(
        property_data=build_property_data(
            # Brand primary is set on the dedicated side_banner field.
            side_banner_panel_color="#e22f8c",
            # Webhook accent (present but no longer consulted).
            accent_background_color="#123456",
        ),
        settings=build_template(width=1080, height=1920),
        include_agency_logo=False,
        include_ber_icon=False,
        agent_input_index=1,
        agency_logo_input_index=None,
        ber_icon_input_index=None,
        layout_variant="side_banner",
    )

    assert "color=0xe22f8c@0.55" in script
    # Webhook accent must NOT appear in the filter graph.
    assert "0x123456" not in script


def test_side_banner_poster_panels_fall_back_to_grey_when_no_brand() -> None:
    """Without a brand primary colour, the panels render with the
    Tailwind ``gray-700`` (``#374151``) fallback at 0.55 alpha."""
    script = _build_poster_filter_script(
        property_data=build_property_data(
            # No brand override.
            side_banner_panel_color=None,
            # Webhook accent ignored — would have leaked in the legacy
            # cascade.
            accent_background_color="#e22f8c",
        ),
        settings=build_template(width=1080, height=1920),
        include_agency_logo=False,
        include_ber_icon=False,
        agent_input_index=1,
        agency_logo_input_index=None,
        ber_icon_input_index=None,
        layout_variant="side_banner",
    )

    assert "color=0x374151@0.55" in script
    # Webhook accent must NOT participate.
    assert "0xe22f8c" not in script
