"""Unit tests for accent / brand colour threading inside ``_build_render_data``
when ``layout_variant="galaxy"`` (feature 42).

Galaxy reuses the side_banner cascades VERBATIM:

- ``side_banner_panel_color`` (ingest-side stash from
  ``BrandSettings.primary_color``) → top + bottom rounded panels.
- ``side_banner_ribbon_background_color`` (ingest-side stash from
  ``BrandSettings.secondary_color``) → vertical ``FOR SALE`` ribbon.
- ``accent_text_color`` / ``accent_background_color`` are still
  intentionally left at ``None`` by ``_build_render_data`` (hotfix
  2026-05-15 contract).

The renderer guard ``layout_variant in {"side_banner", "galaxy"}``
inside ``filters.py`` / ``preparation.py`` / ``poster.py`` is what
makes the same data shape paint two different templates; this test
only covers the data-threading half of the contract.
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
    render_template_reel_settings: dict[str, object] | None = None,
) -> PropertyContext:
    site_id = "site-a"
    storage_paths = resolve_site_storage_layout(tmp_path, site_id)
    payload: dict[str, object] = {
        "id": 42,
        "slug": "galaxy-property",
        "title": {"rendered": "Galaxy Property"},
        "wppd_pics": ["https://example.com/img1.jpg"],
    }
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
        render_template_id="galaxy",
        render_template_layout_variant="galaxy",
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


def test_galaxy_render_data_threads_brand_panel_color_from_reel_settings(
    tmp_path: Path,
) -> None:
    """Galaxy reuses the ``side_banner_panel_color`` cascade verbatim."""
    context = _build_property_context(
        tmp_path,
        render_template_reel_settings={
            "side_banner_panel_color": "#0E2F59",
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

    assert isinstance(render_data, PropertyRenderData)
    assert render_data.side_banner_panel_color == "#0E2F59"
    # Brand panel colour does NOT leak into accent_* fields nor the
    # ribbon — they remain orthogonal cascades.
    assert render_data.accent_text_color is None
    assert render_data.accent_background_color is None
    assert render_data.side_banner_ribbon_background_color is None


def test_galaxy_render_data_threads_brand_secondary_color_from_reel_settings(
    tmp_path: Path,
) -> None:
    """Galaxy reuses the ``side_banner_ribbon_background_color`` cascade verbatim."""
    context = _build_property_context(
        tmp_path,
        render_template_reel_settings={
            "side_banner_ribbon_background_color": "#C9A24B",
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

    assert render_data.side_banner_ribbon_background_color == "#C9A24B"
    assert render_data.side_banner_panel_color is None
    assert render_data.accent_text_color is None
    assert render_data.accent_background_color is None


def test_galaxy_render_data_panel_and_ribbon_cascade_together(
    tmp_path: Path,
) -> None:
    """Both brand fields populate independent renderer fields for galaxy."""
    context = _build_property_context(
        tmp_path,
        render_template_reel_settings={
            "side_banner_panel_color": "#0E2F59",
            "side_banner_ribbon_background_color": "#C9A24B",
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

    assert render_data.side_banner_panel_color == "#0E2F59"
    assert render_data.side_banner_ribbon_background_color == "#C9A24B"
    # The legacy fallback channels stay inert.
    assert render_data.accent_text_color is None
    assert render_data.accent_background_color is None


def test_galaxy_render_data_panel_and_ribbon_default_to_none_when_absent(
    tmp_path: Path,
) -> None:
    """Without brand overrides, both fields stay ``None`` so consumers fall back.

    Galaxy consumers must fall back to the hardcoded greys
    (``_SIDE_BANNER_PANEL_DEFAULT`` in ``poster.py`` /
    ``render_reel.py`` and ``_SIDE_BANNER_RIBBON_BACKGROUND`` in
    ``preparation.py``) so the panels remain visible even on
    unconfigured agencies.
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
    assert render_data.side_banner_ribbon_background_color is None
    assert render_data.accent_text_color is None
    assert render_data.accent_background_color is None
