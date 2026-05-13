"""Integration smoke test for the side_banner render template (Feature 16).

We exercise the renderer end-to-end at the call-graph level (without
running ffmpeg). The goal is to verify that:

- ``DefaultMediaRenderer`` propagates
  ``context.render_template_layout_variant="side_banner"`` to the
  preparation, reel, and poster primitives.
- The accent colors on ``PropertyRenderData`` survive the trip.

The actual ffmpeg filter graph produced for the side_banner is covered
in detail by ``tests/unit/rendering/test_overlay_filter_accent_colors.py``
and ``tests/unit/rendering/test_layout_composition_side_banner.py``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from modules.catalog.domain.wordpress_property import Property
from modules.reels.domain.types import (
    MediaDeliveryPlan,
    PreparedMediaAssets,
    PropertyContext,
)
from modules.rendering.application import frame_composition as fc_module
from modules.rendering.application.frame_composition import DefaultMediaRenderer
from modules.tenancy.domain.context import TenantContext
from shared.storage.site_layout import resolve_site_storage_layout


def _patch_primitives(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, Any]]]:
    captured: dict[str, list[dict[str, Any]]] = {
        "prepare": [],
        "manifest": [],
        "reel": [],
        "poster": [],
    }

    def _fake_template(profile: str, *, template=None) -> object:
        return template or object()

    def _fake_selected_slides(selected_dir, paths):
        return [{"stub": str(p)} for p in paths]

    def _fake_prepare(
        workspace,
        render_data,
        *,
        template,
        working_dir,
        layout_variant="classic",
    ):
        captured["prepare"].append(
            {
                "layout_variant": layout_variant,
                "render_data_accent_text": render_data.accent_text_color,
                "render_data_accent_background": render_data.accent_background_color,
            }
        )
        Path(working_dir).mkdir(parents=True, exist_ok=True)
        return object()

    def _fake_manifest(
        workspace,
        render_data,
        *,
        output_path,
        template,
        render_profile,
        render_template_id,
        render_template_settings_hash,
        poster_template,
        prepared_assets,
        working_dir,
    ):
        captured["manifest"].append(
            {"render_template_id": render_template_id}
        )
        Path(output_path).write_text("{}", encoding="utf-8")

    def _fake_reel(
        workspace,
        render_data,
        *,
        output_path,
        template,
        prepared_assets,
        working_dir,
        layout_variant="classic",
    ):
        captured["reel"].append(
            {
                "layout_variant": layout_variant,
                "accent_text": render_data.accent_text_color,
                "accent_background": render_data.accent_background_color,
            }
        )
        Path(output_path).write_bytes(b"mp4")

    def _fake_poster(
        workspace,
        render_data,
        *,
        output_path,
        template,
        layout_variant="classic",
    ):
        captured["poster"].append(
            {
                "layout_variant": layout_variant,
                "accent_text": render_data.accent_text_color,
                "accent_background": render_data.accent_background_color,
            }
        )
        Path(output_path).write_bytes(b"jpg")

    monkeypatch.setattr(fc_module, "build_reel_template_for_render_profile", _fake_template)
    monkeypatch.setattr(fc_module, "build_local_selected_slides", _fake_selected_slides)
    monkeypatch.setattr(fc_module, "prepare_reel_render_assets", _fake_prepare)
    monkeypatch.setattr(fc_module, "write_property_reel_manifest_from_data", _fake_manifest)
    monkeypatch.setattr(fc_module, "generate_property_reel_from_data", _fake_reel)
    monkeypatch.setattr(fc_module, "generate_property_poster_from_data", _fake_poster)
    return captured


def _build_context(
    workspace: Path,
    *,
    layout_variant: str,
    accent_text: str | None = None,
    accent_background: str | None = None,
    fallback_text: str | None = None,
    fallback_background: str | None = None,
) -> PropertyContext:
    site_id = "site-a"
    storage_paths = resolve_site_storage_layout(workspace, site_id)
    payload: dict[str, Any] = {
        "id": 99,
        "slug": "side-banner-property",
        "title": {"rendered": "Side Banner Property"},
        "wppd_pics": ["https://example.com/img1.jpg"],
        "property_status": "For Sale",
    }
    if accent_text is not None:
        payload["wppd_accent_text_color"] = accent_text
    if accent_background is not None:
        payload["wppd_accent_background_color"] = accent_background
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
    reel_settings: dict[str, object] = {}
    poster_settings: dict[str, object] = {}
    if fallback_text:
        reel_settings["fallback_accent_text_color"] = fallback_text
        poster_settings["fallback_accent_text_color"] = fallback_text
    if fallback_background:
        reel_settings["fallback_accent_background_color"] = fallback_background
        poster_settings["fallback_accent_background_color"] = fallback_background
    return PropertyContext(
        workspace_dir=workspace,
        storage_paths=storage_paths,
        tenant=tenant,
        property=property_item,
        delivery_plan=delivery_plan,
        render_template_id="side_banner",
        render_template_layout_variant=layout_variant,
        render_template_reel_settings=reel_settings,
        render_template_poster_settings=poster_settings,
    )


def _build_prepared(selected_dir: Path) -> PreparedMediaAssets:
    photo_path = selected_dir / "01.jpg"
    return PreparedMediaAssets(
        selected_dir=selected_dir,
        selected_photo_paths=(photo_path,),
        downloaded_images=((1, "https://example.com/img1.jpg", photo_path),),
        primary_image_path=selected_dir / "primary_image.jpg",
    )


def test_side_banner_render_threads_layout_variant_and_accent_colors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_primitives(monkeypatch)
    context = _build_context(
        tmp_path,
        layout_variant="side_banner",
        accent_text="#ffffff",
        accent_background="#e22f8c",
    )
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared(selected_dir)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    artifact = renderer.render_media(context, prepared)

    assert artifact.artifact_kind == "reel_video"
    assert captured["prepare"][0]["layout_variant"] == "side_banner"
    assert captured["reel"][0]["layout_variant"] == "side_banner"
    assert captured["poster"][0]["layout_variant"] == "side_banner"
    # Per-property accent colors win.
    assert captured["reel"][0]["accent_text"] == "#ffffff"
    assert captured["reel"][0]["accent_background"] == "#e22f8c"
    assert captured["poster"][0]["accent_text"] == "#ffffff"
    assert captured["poster"][0]["accent_background"] == "#e22f8c"


def test_side_banner_render_falls_back_to_brand_color_when_property_misses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_primitives(monkeypatch)
    context = _build_context(
        tmp_path,
        layout_variant="side_banner",
        accent_text=None,
        accent_background=None,
        fallback_text="#0F172A",
        fallback_background="#0F172A",
    )
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared(selected_dir)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, prepared)

    assert captured["reel"][0]["accent_text"] == "#0F172A"
    assert captured["reel"][0]["accent_background"] == "#0F172A"


def test_classic_render_default_layout_variant_unaffected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_primitives(monkeypatch)
    context = _build_context(tmp_path, layout_variant="classic")
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared(selected_dir)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, prepared)

    assert captured["prepare"][0]["layout_variant"] == "classic"
    assert captured["reel"][0]["layout_variant"] == "classic"
    assert captured["poster"][0]["layout_variant"] == "classic"
    # Without per-property colors or fallbacks, accent fields are None.
    assert captured["reel"][0]["accent_text"] is None
    assert captured["reel"][0]["accent_background"] is None
