"""Integration test for Feature 23 — the agency music pool reaches the render.

Goal: verify that the ``DefaultMediaRenderer`` forwards the
``background_audio_candidates`` resolved by the ingest use case all the
way down to ``prepare_reel_render_assets``, and that the resulting
``music_tracks`` tuple references paths under
``workspace/generated_media/_agency_music/...`` (the canonical agency
music destination) instead of the legacy ``assets/music/`` folder.
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
from shared.storage.site_layout import (
    resolve_agency_music_destination,
    resolve_site_storage_layout,
)


def _stub_primitives(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    captured: dict[str, list[Any]] = {"prepare_music": []}

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
        captured["prepare_music"].append(music_tracks)
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
        Path(output_path).write_bytes(b"mp4")

    def _fake_poster(
        workspace,
        render_data,
        *,
        output_path,
        template,
        layout_variant="classic",
    ):
        Path(output_path).write_bytes(b"jpg")

    monkeypatch.setattr(fc_module, "build_reel_template_for_render_profile", _fake_template)
    monkeypatch.setattr(fc_module, "build_local_selected_slides", _fake_selected_slides)
    monkeypatch.setattr(fc_module, "prepare_reel_render_assets", _fake_prepare)
    monkeypatch.setattr(fc_module, "write_property_reel_manifest_from_data", _fake_manifest)
    monkeypatch.setattr(fc_module, "generate_property_reel_from_data", _fake_reel)
    monkeypatch.setattr(fc_module, "generate_property_poster_from_data", _fake_poster)
    return captured


def _build_context_with_music(
    workspace: Path,
    music_paths: tuple[Path, ...],
) -> PropertyContext:
    site_id = "site-a"
    storage_paths = resolve_site_storage_layout(workspace, site_id)
    property_item = Property.from_api_payload(
        {
            "id": 99,
            "slug": "music-pool-property",
            "title": {"rendered": "Music Pool Property"},
            "wppd_pics": ["https://example.com/img1.jpg"],
        }
    )
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
        agency_id="agency-feature-23",
        wordpress_source_id="ingestion-1",
    )
    return PropertyContext(
        workspace_dir=workspace,
        storage_paths=storage_paths,
        tenant=tenant,
        property=property_item,
        delivery_plan=delivery_plan,
        background_audio_candidates=music_paths,
    )


def _build_prepared(selected_dir: Path) -> PreparedMediaAssets:
    return PreparedMediaAssets(
        selected_dir=selected_dir,
        selected_photo_paths=(selected_dir / "01.jpg",),
        downloaded_images=((1, "https://example.com/img1.jpg", selected_dir / "01.jpg"),),
        primary_image_path=selected_dir / "primary_image.jpg",
    )


def test_renderer_forwards_agency_music_paths_to_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    object_key_a, local_path_a = resolve_agency_music_destination(
        workspace_dir=tmp_path,
        agency_id="agency-feature-23",
        filename="_seed_ncs_apart.mp3",
    )
    object_key_b, local_path_b = resolve_agency_music_destination(
        workspace_dir=tmp_path,
        agency_id="agency-feature-23",
        filename="_seed_ncs_silence.mp3",
    )
    local_path_a.write_bytes(b"a")
    local_path_b.write_bytes(b"b")
    music_paths = (local_path_a, local_path_b)
    # Sanity: both paths sit under the canonical agency-music subtree.
    assert "_agency_music" in str(local_path_a)
    assert "_agency_music" in str(local_path_b)
    assert object_key_a.startswith("agencies/")
    assert object_key_b.startswith("agencies/")

    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    context = _build_context_with_music(tmp_path, music_paths)
    captured = _stub_primitives(monkeypatch)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, _build_prepared(selected_dir))

    assert captured["prepare_music"], "prepare_reel_render_assets was not invoked"
    forwarded = captured["prepare_music"][0]
    assert forwarded is not None
    assert set(forwarded) == set(music_paths)
    for path in forwarded:
        assert "_agency_music" in str(path)
        assert "assets/music" not in str(path)


def test_renderer_falls_back_to_legacy_path_when_pool_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    context = _build_context_with_music(tmp_path, music_paths=())
    captured = _stub_primitives(monkeypatch)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, _build_prepared(selected_dir))

    assert captured["prepare_music"][0] is None
