"""Integration smoke test for the galaxy render template (Feature 42).

Same pattern as ``test_side_banner_render.py`` — exercise the
renderer end-to-end at the call-graph level (without running ffmpeg)
to verify that:

- ``DefaultMediaRenderer`` propagates
  ``context.render_template_layout_variant="galaxy"`` to the
  preparation, reel and poster primitives.
- The brand panel / ribbon colours on ``PropertyRenderData`` survive
  the trip.
- The vertical ribbon (``side_banner_ribbon_background_color``) is
  threaded to preparation for galaxy just like side_banner — galaxy
  reuses the helper verbatim.
"""

from __future__ import annotations

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
        music_tracks=None,
    ):
        captured["prepare"].append(
            {
                "layout_variant": layout_variant,
                "render_data_secondary_color": (
                    render_data.side_banner_ribbon_background_color
                ),
                "render_data_panel_color": render_data.side_banner_panel_color,
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
                "side_banner_panel_color": render_data.side_banner_panel_color,
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
                "side_banner_panel_color": render_data.side_banner_panel_color,
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
    side_banner_panel_color: str | None = None,
    side_banner_ribbon_background: str | None = None,
) -> PropertyContext:
    site_id = "site-a"
    storage_paths = resolve_site_storage_layout(workspace, site_id)
    payload: dict[str, Any] = {
        "id": 99,
        "slug": "galaxy-property",
        "title": {"rendered": "Galaxy Property"},
        "wppd_pics": ["https://example.com/img1.jpg"],
        "property_status": "For Sale",
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
    reel_settings: dict[str, object] = {}
    poster_settings: dict[str, object] = {}
    if side_banner_panel_color is not None:
        reel_settings["side_banner_panel_color"] = side_banner_panel_color
        poster_settings["side_banner_panel_color"] = side_banner_panel_color
    if side_banner_ribbon_background is not None:
        reel_settings["side_banner_ribbon_background_color"] = (
            side_banner_ribbon_background
        )
    return PropertyContext(
        workspace_dir=workspace,
        storage_paths=storage_paths,
        tenant=tenant,
        property=property_item,
        delivery_plan=delivery_plan,
        render_template_id="galaxy",
        render_template_layout_variant="galaxy",
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


def test_galaxy_render_propagates_layout_variant_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_primitives(monkeypatch)
    context = _build_context(tmp_path)
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared(selected_dir)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    artifact = renderer.render_media(context, prepared)

    assert artifact.artifact_kind == "reel_video"
    assert captured["prepare"][0]["layout_variant"] == "galaxy"
    assert captured["reel"][0]["layout_variant"] == "galaxy"
    assert captured["poster"][0]["layout_variant"] == "galaxy"


def test_galaxy_render_threads_brand_panel_color_to_reel_and_poster(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_primitives(monkeypatch)
    context = _build_context(tmp_path, side_banner_panel_color="#0E2F59")
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared(selected_dir)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, prepared)

    assert captured["reel"][0]["side_banner_panel_color"] == "#0E2F59"
    assert captured["poster"][0]["side_banner_panel_color"] == "#0E2F59"


def test_galaxy_render_threads_brand_ribbon_color_to_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_primitives(monkeypatch)
    context = _build_context(
        tmp_path, side_banner_ribbon_background="#C9A24B"
    )
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared(selected_dir)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, prepared)

    assert captured["prepare"][0]["render_data_secondary_color"] == "#C9A24B"
    assert captured["prepare"][0]["layout_variant"] == "galaxy"


def test_galaxy_render_panel_and_ribbon_default_to_none_without_brand(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_primitives(monkeypatch)
    context = _build_context(tmp_path)
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared(selected_dir)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, prepared)

    assert captured["prepare"][0]["render_data_secondary_color"] is None
    assert captured["prepare"][0]["render_data_panel_color"] is None
    assert captured["reel"][0]["side_banner_panel_color"] is None
    assert captured["poster"][0]["side_banner_panel_color"] is None
