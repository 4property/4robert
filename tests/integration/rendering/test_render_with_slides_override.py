"""Integration test for the slides override branch of the renderer (feature 37).

The renderer wraps the photo-array driver so when ``context.manifest_override``
is present, the ordered ``photo``-kind entries (sorted by ``position``) drive
the rendered slides. Non-photo kinds (voiceover, text, intro_card, outro_card)
are persisted for the FE editor but do not change the photo array — same
contract documented in the implementer report.

The heavy primitives (``prepare_reel_render_assets``,
``generate_property_reel_from_data``, ffmpeg, poster) are stubbed because we
only care about the manifest contract — the rest of the pipeline already has
its own coverage in ``test_render_with_photos_override.py``.
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
    manifest_override: tuple[dict, ...] | None = None,
) -> PropertyContext:
    site_id = "site-feature-37"
    storage_paths = resolve_site_storage_layout(workspace, site_id)
    property_item = Property.from_api_payload(
        {
            "id": 77,
            "slug": "slides-override-property",
            "title": {"rendered": "Slides Override Property"},
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
        agency_id="agency-feature-37",
        wordpress_source_id="ingestion-1",
    )
    return PropertyContext(
        workspace_dir=workspace,
        storage_paths=storage_paths,
        tenant=tenant,
        property=property_item,
        delivery_plan=delivery_plan,
        manifest_override=manifest_override,
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


def _photo_slide(position: int, photo_position: int, duration: float = 3.0) -> dict:
    return {
        "slide_id": f"slide-{position}",
        "position": position,
        "duration_seconds": duration,
        "kind": "photo",
        "photo_position": photo_position,
    }


def test_renderer_uses_manifest_override_photo_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Override with reversed photo order → manifest receives reversed photos."""
    captured = _stub_render_primitives(monkeypatch)
    prepared = _build_prepared_assets(tmp_path, photo_count=5)
    override = tuple(
        _photo_slide(position=index, photo_position=photo_position)
        for index, photo_position in enumerate((4, 3, 2, 1, 0))
    )
    context = _build_context(tmp_path, manifest_override=override)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, prepared)

    assert captured["manifest"], "manifest was not invoked"
    rendered_paths = captured["manifest"][0]["selected_image_paths"]
    expected_paths = tuple(prepared.selected_photo_paths[idx] for idx in (4, 3, 2, 1, 0))
    assert rendered_paths == expected_paths


def test_renderer_falls_back_when_manifest_override_is_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``manifest_override=None`` → renderer keeps the prepared photo order."""
    captured = _stub_render_primitives(monkeypatch)
    prepared = _build_prepared_assets(tmp_path, photo_count=5)
    context = _build_context(tmp_path, manifest_override=None)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, prepared)

    rendered_paths = captured["manifest"][0]["selected_image_paths"]
    assert rendered_paths == tuple(prepared.selected_photo_paths)


def test_renderer_handles_mixed_kinds_in_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mixed kinds → only ``photo`` kinds drive the slide array.

    Voiceover / text / intro_card / outro_card are persisted but do not
    contribute to the photo array fed to ffmpeg today. The photo entries
    are sorted by ``position`` and mapped through ``photo_position`` to
    the underlying source images.
    """
    captured = _stub_render_primitives(monkeypatch)
    prepared = _build_prepared_assets(tmp_path, photo_count=5)
    override = (
        {
            "slide_id": "intro",
            "position": 0,
            "duration_seconds": 2.0,
            "kind": "intro_card",
            "title": "Welcome",
        },
        _photo_slide(position=1, photo_position=2),
        _photo_slide(position=2, photo_position=0),
        {
            "slide_id": "vo",
            "position": 3,
            "duration_seconds": 1.5,
            "kind": "voiceover",
            "audio_url": "https://example.com/voiceover.mp3",
        },
        _photo_slide(position=4, photo_position=4),
        {
            "slide_id": "outro",
            "position": 5,
            "duration_seconds": 2.0,
            "kind": "outro_card",
            "title": "Thanks",
        },
    )
    context = _build_context(tmp_path, manifest_override=override)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, prepared)

    rendered_paths = captured["manifest"][0]["selected_image_paths"]
    # Photo slides at positions 1, 2, 4 → photo_positions 2, 0, 4 (sorted
    # by ``position`` already).
    expected_paths = tuple(prepared.selected_photo_paths[idx] for idx in (2, 0, 4))
    assert rendered_paths == expected_paths


def test_renderer_falls_back_when_override_has_no_photo_kinds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An override with zero ``photo``-kind entries must not produce an empty reel."""
    captured = _stub_render_primitives(monkeypatch)
    prepared = _build_prepared_assets(tmp_path, photo_count=3)
    override = (
        {
            "slide_id": "intro",
            "position": 0,
            "duration_seconds": 2.0,
            "kind": "intro_card",
        },
        {
            "slide_id": "text",
            "position": 1,
            "duration_seconds": 2.0,
            "kind": "text",
            "text": "Welcome",
        },
    )
    context = _build_context(tmp_path, manifest_override=override)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, prepared)

    rendered_paths = captured["manifest"][0]["selected_image_paths"]
    # Fallback to the default prepared order — no photo kinds present.
    assert rendered_paths == tuple(prepared.selected_photo_paths)


def test_renderer_falls_back_when_override_photo_positions_out_of_range(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale override (``photo_position`` beyond the prepared set) falls back."""
    captured = _stub_render_primitives(monkeypatch)
    prepared = _build_prepared_assets(tmp_path, photo_count=2)
    override = (
        _photo_slide(position=0, photo_position=99),
        _photo_slide(position=1, photo_position=100),
    )
    context = _build_context(tmp_path, manifest_override=override)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    renderer.render_media(context, prepared)

    rendered_paths = captured["manifest"][0]["selected_image_paths"]
    assert rendered_paths == tuple(prepared.selected_photo_paths)
