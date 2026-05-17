"""Integration test for the photos override branch of the renderer (feature 35).

The renderer's reel composition step reorders / filters
``prepared_assets.selected_photo_paths`` from ``context.photos_override``
before constructing the manifest. These tests assert that the manifest
fed to ffmpeg sees the photos in the override-driven order (or the
default order when the override is ``None``).

The heavy primitives (``prepare_reel_render_assets``,
``generate_property_reel_from_data``, the actual ffmpeg invocation) are
stubbed because we only care about the manifest contract — the rest of
the pipeline already has its own coverage.
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


def _stub_render_primitives(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, list[Any]]:
    """Stub out the heavy render primitives so we can inspect the inputs.

    ``captured['prepare']`` collects the ``property_render_data`` that
    would be forwarded to ``prepare_reel_render_assets`` — the manifest
    is built from the same data so the ordered slide image paths are
    the canonical fingerprint of the override outcome.
    """

    captured: dict[str, list[Any]] = {
        "prepare": [],
        "manifest": [],
        "reel": [],
        "poster": [],
    }

    class _StubTemplate:
        width = 320
        height = 240
        fps = 15

    def _fake_template(profile: str, *, template=None):
        return _StubTemplate()

    def _fake_selected_slides(selected_dir, paths):
        return tuple({"image_path": str(p)} for p in paths)

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
                "render_data": render_data,
                "selected_image_paths": tuple(render_data.selected_image_paths),
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
            {
                "selected_image_paths": tuple(render_data.selected_image_paths),
            }
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
                "output_path": str(output_path),
                "selected_image_paths": tuple(render_data.selected_image_paths),
            }
        )
        Path(output_path).write_bytes(b"mp4-stub")

    def _fake_poster(
        workspace,
        render_data,
        *,
        output_path,
        template,
        layout_variant="classic",
    ):
        captured["poster"].append({"layout_variant": layout_variant})
        Path(output_path).write_bytes(b"jpg-stub")

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
    photos_override: tuple[tuple[int, bool], ...] | None = None,
) -> PropertyContext:
    site_id = "site-feature-35"
    storage_paths = resolve_site_storage_layout(workspace, site_id)
    property_item = Property.from_api_payload(
        {
            "id": 77,
            "slug": "photos-override-property",
            "title": {"rendered": "Photos Override Property"},
            "wppd_pics": [
                f"https://example.com/img-{idx}.jpg" for idx in range(5)
            ],
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
        agency_id="agency-feature-35",
        wordpress_source_id="ingestion-1",
    )
    return PropertyContext(
        workspace_dir=workspace,
        storage_paths=storage_paths,
        tenant=tenant,
        property=property_item,
        delivery_plan=delivery_plan,
        photos_override=photos_override,
    )


def _build_prepared_assets(tmp_path: Path, *, photo_count: int) -> PreparedMediaAssets:
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    selected_paths: list[Path] = []
    for index in range(photo_count):
        path = selected_dir / f"{index + 1:02d}_photo_{index}.jpg"
        path.write_bytes(f"stub-photo-{index}".encode())
        selected_paths.append(path)
    return PreparedMediaAssets(
        selected_dir=selected_dir,
        selected_photo_paths=tuple(selected_paths),
        downloaded_images=tuple(
            (index + 1, f"https://example.com/img-{index}.jpg", selected_paths[index])
            for index in range(photo_count)
        ),
        primary_image_path=selected_paths[0] if selected_paths else None,
    )


def test_renderer_applies_photos_override_reversed_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reversed override → manifest receives the photos reversed."""
    captured = _stub_render_primitives(monkeypatch)
    prepared = _build_prepared_assets(tmp_path, photo_count=5)
    override = tuple((position, True) for position in (4, 3, 2, 1, 0))
    context = _build_context(tmp_path, photos_override=override)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, prepared)

    assert captured["manifest"], "manifest was not invoked"
    invocation = captured["manifest"][0]
    rendered_paths = invocation["selected_image_paths"]
    expected_paths = tuple(prepared.selected_photo_paths[index] for index in (4, 3, 2, 1, 0))
    assert rendered_paths == expected_paths


def test_renderer_skips_unselected_photos_from_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``selected=false`` entries are dropped from the manifest."""
    captured = _stub_render_primitives(monkeypatch)
    prepared = _build_prepared_assets(tmp_path, photo_count=5)
    # Keep positions 0, 2, 4 and drop 1, 3.
    override = (
        (0, True),
        (1, False),
        (2, True),
        (3, False),
        (4, True),
    )
    context = _build_context(tmp_path, photos_override=override)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, prepared)

    invocation = captured["manifest"][0]
    rendered_paths = invocation["selected_image_paths"]
    expected_paths = tuple(prepared.selected_photo_paths[index] for index in (0, 2, 4))
    assert rendered_paths == expected_paths


def test_renderer_preserves_default_order_when_override_is_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``photos_override=None`` → renderer keeps the prepared photo order."""
    captured = _stub_render_primitives(monkeypatch)
    prepared = _build_prepared_assets(tmp_path, photo_count=5)
    context = _build_context(tmp_path, photos_override=None)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, prepared)

    invocation = captured["manifest"][0]
    rendered_paths = invocation["selected_image_paths"]
    assert rendered_paths == tuple(prepared.selected_photo_paths)


def test_renderer_falls_back_to_default_when_override_all_unselected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An override that excludes every slot must not produce an empty reel."""
    captured = _stub_render_primitives(monkeypatch)
    prepared = _build_prepared_assets(tmp_path, photo_count=3)
    override = tuple((position, False) for position in (0, 1, 2))
    context = _build_context(tmp_path, photos_override=override)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, prepared)

    invocation = captured["manifest"][0]
    rendered_paths = invocation["selected_image_paths"]
    assert rendered_paths == tuple(prepared.selected_photo_paths)
