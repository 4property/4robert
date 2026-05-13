"""Unit tests for accent color threading inside `_build_render_data`.

Feature 16: when the WordPress payload provides ``wppd_accent_text_color``
and ``wppd_accent_background_color``, those flow verbatim onto the
``PropertyRenderData`` consumed by the ffmpeg layer. When the payload
omits them, the renderer falls back to the brand-scoped colors that
``ingest_property_into_reel.py`` stuffs into
``context.render_template_reel_settings["fallback_accent_*"]``.
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


def test_build_render_data_uses_property_accent_colors(tmp_path: Path) -> None:
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
    assert render_data.accent_text_color == "#ffffff"
    assert render_data.accent_background_color == "#e22f8c"


def test_build_render_data_falls_back_to_brand_primary_when_missing(
    tmp_path: Path,
) -> None:
    context = _build_property_context(
        tmp_path,
        wppd_accent_text_color=None,
        wppd_accent_background_color=None,
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

    assert render_data.accent_text_color == "#0F172A"
    assert render_data.accent_background_color == "#0F172A"


def test_build_render_data_property_overrides_fallback(tmp_path: Path) -> None:
    context = _build_property_context(
        tmp_path,
        wppd_accent_text_color="#aabbcc",
        wppd_accent_background_color=None,
        render_template_reel_settings={
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

    # Property override wins for text; fallback is used for background.
    assert render_data.accent_text_color == "#aabbcc"
    assert render_data.accent_background_color == "#ffffff"


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
