"""Unit tests for accent / brand colour threading inside ``_build_render_data``.

Hotfix 2026-05-15: side_banner colours are now driven exclusively by
the agency brand row. The renderer no longer consults the WordPress
webhook accents (``wppd_accent_*``) nor the ``fallback_accent_*`` keys
that the ingestion use case used to stash in
``render_template_reel_settings``. ``PropertyRenderData.accent_*`` are
left at ``None`` and the top/bottom panels + the vertical ribbon are
painted from ``side_banner_panel_color`` (brand primary) and
``side_banner_ribbon_background_color`` (brand secondary). When either
is absent, ``poster.py`` / ``render_reel.py`` / ``preparation.py``
fall back to hardcoded neutral greys.
"""

from __future__ import annotations

from pathlib import Path

from modules.catalog.domain.wordpress_property import Property
from modules.reels.domain.types import (
    MediaDeliveryPlan,
    PreparedMediaAssets,
    PropertyContext,
)
from modules.rendering.application.frame_composition import DefaultMediaRenderer
from modules.rendering.infrastructure.models import PropertyRenderData
from modules.tenancy.domain.context import TenantContext
from shared.storage.site_layout import resolve_site_storage_layout


def _build_property_context(
    tmp_path: Path,
    *,
    wppd_accent_text_color: str | None = None,
    wppd_accent_background_color: str | None = None,
    render_template_reel_settings: dict[str, object] | None = None,
) -> PropertyContext:
    site_id = "site-a"
    storage_paths = resolve_site_storage_layout(tmp_path, site_id)
    payload: dict[str, object] = {
        "id": 42,
        "slug": "accent-property",
        "title": {"rendered": "Accent Property"},
        "wppd_pics": ["https://example.com/img1.jpg"],
    }
    if wppd_accent_text_color is not None:
        payload["wppd_accent_text_color"] = wppd_accent_text_color
    if wppd_accent_background_color is not None:
        payload["wppd_accent_background_color"] = wppd_accent_background_color
    property_item = Property.from_api_payload(payload)
    delivery_plan = MediaDeliveryPlan(
        listing_lifecycle="for_sale",
        artifact_kind="reel_video",
        render_profile="for_sale_reel",
        social_post_type="reel",
        asset_strategy="curated_selection",
        banner_text="FOR SALE",
        price_display_text=None,
    )
    tenant = TenantContext(
        site_id=site_id,
        agency_id="agency-1",
        wordpress_source_id="ingestion-1",
    )
    return PropertyContext(
        workspace_dir=tmp_path,
        storage_paths=storage_paths,
        tenant=tenant,
        property=property_item,
        delivery_plan=delivery_plan,
        render_template_reel_settings=render_template_reel_settings or {},
    )


def _build_prepared_assets(selected_dir: Path) -> PreparedMediaAssets:
    photo_path = selected_dir / "01_house.jpg"
    return PreparedMediaAssets(
        selected_dir=selected_dir,
        selected_photo_paths=(photo_path,),
        downloaded_images=((1, "https://example.com/img1.jpg", photo_path),),
        primary_image_path=selected_dir / "primary_image.jpg",
    )


def test_build_render_data_ignores_wppd_accent_colors(tmp_path: Path) -> None:
    """Hotfix 2026-05-15: webhook accent colours are no longer threaded.

    The previous behaviour copied ``wppd_accent_*`` into
    ``PropertyRenderData.accent_*`` so the side_banner panels could use
    them. The new contract drops that threading — colour comes from
    the brand row exclusively, so ``accent_*`` stay ``None`` even when
    the WordPress payload supplies them.
    """
    context = _build_property_context(
        tmp_path,
        wppd_accent_text_color="#ffffff",
        wppd_accent_background_color="#e22f8c",
    )
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared_assets(selected_dir)

    render_data = DefaultMediaRenderer._build_render_data(
        context=context,
        prepared_assets=prepared,
        selected_slides=(),
    )

    assert isinstance(render_data, PropertyRenderData)
    assert render_data.accent_text_color is None
    assert render_data.accent_background_color is None


def test_build_render_data_ignores_fallback_accent_keys(tmp_path: Path) -> None:
    """Hotfix 2026-05-15: the legacy ``fallback_accent_*_color`` keys are
    ignored.

    They were the channel used by feature 16 to thread the brand
    primary colour as a fallback for the webhook accents. The new
    cascade uses ``side_banner_panel_color`` / ``side_banner_ribbon_background_color``
    directly, so the fallback keys are inert even when ingestion sends
    them.
    """
    context = _build_property_context(
        tmp_path,
        render_template_reel_settings={
            "fallback_accent_text_color": "#0F172A",
            "fallback_accent_background_color": "#0F172A",
        },
    )
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared_assets(selected_dir)

    render_data = DefaultMediaRenderer._build_render_data(
        context=context,
        prepared_assets=prepared,
        selected_slides=(),
    )

    assert render_data.accent_text_color is None
    assert render_data.accent_background_color is None


def test_build_render_data_brand_keys_drive_side_banner_only(tmp_path: Path) -> None:
    """The two brand-driven keys populate dedicated fields, not ``accent_*``."""
    context = _build_property_context(
        tmp_path,
        wppd_accent_text_color="#aabbcc",
        wppd_accent_background_color="#112233",
        render_template_reel_settings={
            "side_banner_panel_color": "#FF0000",
            "side_banner_ribbon_background_color": "#00FF00",
            # These two are present but inert under the new contract.
            "fallback_accent_text_color": "#000000",
            "fallback_accent_background_color": "#ffffff",
        },
    )
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared_assets(selected_dir)

    render_data = DefaultMediaRenderer._build_render_data(
        context=context,
        prepared_assets=prepared,
        selected_slides=(),
    )

    # Brand-driven side_banner fields populated.
    assert render_data.side_banner_panel_color == "#FF0000"
    assert render_data.side_banner_ribbon_background_color == "#00FF00"
    # Accent fields stay None — the webhook accents are no longer
    # threaded, and the inert fallback keys are not consulted either.
    assert render_data.accent_text_color is None
    assert render_data.accent_background_color is None


def test_build_render_data_returns_none_when_no_property_and_no_fallback(
    tmp_path: Path,
) -> None:
    context = _build_property_context(tmp_path)
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared_assets(selected_dir)

    render_data = DefaultMediaRenderer._build_render_data(
        context=context,
        prepared_assets=prepared,
        selected_slides=(),
    )

    assert render_data.accent_text_color is None
    assert render_data.accent_background_color is None
    # Feature 29: no brand override means the renderer uses its hardcoded
    # ``#FECF4D`` ribbon background; the render data carries ``None`` to
    # signal that.
    assert render_data.side_banner_ribbon_background_color is None


def test_build_render_data_threads_brand_secondary_color_from_reel_settings(
    tmp_path: Path,
) -> None:
    """Feature 29: the renderer lifts the brand secondary HEX from reel settings.

    ``IngestPropertyIntoReelUseCase`` stashes the brand secondary colour
    as ``side_banner_ribbon_background_color`` inside the reel settings
    dict. The renderer must propagate the value onto
    ``PropertyRenderData`` so ``preparation.prepare_reel_render_assets``
    can render the rotated ribbon with the brand colour instead of the
    hardcoded ``#FECF4D``.
    """
    context = _build_property_context(
        tmp_path,
        render_template_reel_settings={
            "side_banner_ribbon_background_color": "#FF00FF",
        },
    )
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared_assets(selected_dir)

    render_data = DefaultMediaRenderer._build_render_data(
        context=context,
        prepared_assets=prepared,
        selected_slides=(),
    )

    assert render_data.side_banner_ribbon_background_color == "#FF00FF"
    # The accent fields stay independent — the brand secondary colour
    # does NOT leak into the top / bottom panel colours.
    assert render_data.accent_text_color is None
    assert render_data.accent_background_color is None


def test_build_render_data_threads_brand_panel_color_from_reel_settings(
    tmp_path: Path,
) -> None:
    """Hotfix 2026-05-15: the renderer lifts the brand primary panel HEX from settings.

    ``IngestPropertyIntoReelUseCase`` stashes the brand
    ``primary_color`` as ``side_banner_panel_color`` inside both the
    reel and poster settings dicts. The renderer must propagate the
    value onto ``PropertyRenderData`` so ``poster.py`` and
    ``render_reel.py`` can paint the side_banner top / bottom panels
    with the brand colour instead of the per-property
    ``accent_background_color``.
    """
    context = _build_property_context(
        tmp_path,
        render_template_reel_settings={
            "side_banner_panel_color": "#FF0000",
        },
    )
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared_assets(selected_dir)

    render_data = DefaultMediaRenderer._build_render_data(
        context=context,
        prepared_assets=prepared,
        selected_slides=(),
    )

    assert render_data.side_banner_panel_color == "#FF0000"
    # Brand panel colour does NOT leak into accent_* fields nor the
    # ribbon — they remain orthogonal cascades.
    assert render_data.accent_text_color is None
    assert render_data.accent_background_color is None
    assert render_data.side_banner_ribbon_background_color is None


def test_build_render_data_panel_color_defaults_to_none_when_absent(
    tmp_path: Path,
) -> None:
    """Without the key in reel settings, ``side_banner_panel_color`` stays ``None``.

    A ``None`` here means the cascade in ``poster.py`` /
    ``render_reel.py`` falls back to ``accent_background_color`` (which
    in turn may carry the ``fallback_accent_background_color`` from the
    brand row, per feature 16).
    """
    context = _build_property_context(tmp_path, render_template_reel_settings={})
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared_assets(selected_dir)

    render_data = DefaultMediaRenderer._build_render_data(
        context=context,
        prepared_assets=prepared,
        selected_slides=(),
    )

    assert render_data.side_banner_panel_color is None
