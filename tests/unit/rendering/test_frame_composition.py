"""Unit tests for `DefaultMediaRenderer` (pure frame composition).

The renderer orchestrates 4 top-level primitives from
`services.media.reel_rendering.*`:

- `prepare_reel_render_assets`
- `write_property_reel_manifest_from_data`
- `generate_property_reel_from_data`
- `generate_property_poster_from_data`

We patch each of them on the renderer module (so we never need ffmpeg).
The renderer is pure compute + filesystem writes, so no DB stubs are
required.
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
    RenderedMediaArtifact,
)
from modules.tenancy.domain.context import TenantContext
from modules.rendering.application import frame_composition as fc_module
from modules.rendering.application.frame_composition import DefaultMediaRenderer
from modules.rendering.infrastructure.models import PropertyRenderData
from shared.storage.site_layout import resolve_site_storage_layout


_PAYLOAD = {
    "id": 11,
    "slug": "casa-feliz",
    "title": {"rendered": "Casa Feliz"},
    "link": "https://example.com/casa-feliz",
    "property_status": "for sale",
    "price": "350000",
    "wppd_pics": ["https://example.com/img1.jpg"],
    "wppd_primary_image": "https://example.com/featured.jpg",
}


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _build_context(workspace_dir: Path) -> PropertyContext:
    site_id = "site-a"
    storage_paths = resolve_site_storage_layout(workspace_dir, site_id)
    property_item = Property.from_api_payload(_PAYLOAD)
    delivery_plan = MediaDeliveryPlan(
        listing_lifecycle="for_sale",
        artifact_kind="reel_video",
        render_profile="for_sale_reel",
        social_post_type="reel",
        asset_strategy="curated_selection",
        banner_text="FOR SALE",
        price_display_text="EUR 350,000",
    )
    tenant = TenantContext(
        site_id=site_id,
        agency_id="agency-1",
        wordpress_source_id="ingestion-1",
    )
    return PropertyContext(
        workspace_dir=workspace_dir,
        storage_paths=storage_paths,
        tenant=tenant,
        property=property_item,
        delivery_plan=delivery_plan,
    )


def _build_prepared_assets(selected_dir: Path) -> PreparedMediaAssets:
    photo_path = selected_dir / "01_house.jpg"
    return PreparedMediaAssets(
        selected_dir=selected_dir,
        selected_photo_paths=(photo_path,),
        downloaded_images=((1, "https://example.com/img1.jpg", photo_path),),
        primary_image_path=selected_dir / "primary_image.jpg",
    )


def _patch_primitives(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[dict[str, Any]]]:
    """Patches the 4 primitives + `build_reel_template_for_render_profile` and
    `build_local_selected_slides` on the renderer module. Returns a dict of
    captured invocations keyed by primitive name."""

    captured: dict[str, list[dict[str, Any]]] = {
        "prepare": [],
        "manifest": [],
        "reel": [],
        "poster": [],
        "template": [],
        "selected_slides": [],
    }

    def _fake_template(profile: str) -> object:
        captured["template"].append({"render_profile": profile})
        return object()  # opaque template token

    def _fake_selected_slides(selected_dir: Path, paths: tuple[Path, ...]):
        captured["selected_slides"].append(
            {"selected_dir": selected_dir, "paths": paths}
        )
        return [{"stub_slide_for": str(p)} for p in paths]

    def _fake_prepare(workspace, render_data, *, template, working_dir):
        captured["prepare"].append(
            {
                "workspace": workspace,
                "render_data": render_data,
                "template": template,
                "working_dir": working_dir,
            }
        )
        working_dir.mkdir(parents=True, exist_ok=True)
        return object()

    def _fake_manifest(
        workspace,
        render_data,
        *,
        output_path,
        template,
        render_profile,
        prepared_assets,
        working_dir,
    ):
        captured["manifest"].append(
            {
                "workspace": workspace,
                "render_data": render_data,
                "output_path": output_path,
                "template": template,
                "render_profile": render_profile,
                "prepared_assets": prepared_assets,
                "working_dir": working_dir,
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
    ):
        captured["reel"].append(
            {
                "workspace": workspace,
                "render_data": render_data,
                "output_path": output_path,
                "template": template,
                "prepared_assets": prepared_assets,
                "working_dir": working_dir,
            }
        )
        Path(output_path).write_bytes(b"fake-mp4")

    def _fake_poster(workspace, render_data, *, output_path):
        captured["poster"].append(
            {
                "workspace": workspace,
                "render_data": render_data,
                "output_path": output_path,
            }
        )
        Path(output_path).write_bytes(b"fake-jpg")

    monkeypatch.setattr(fc_module, "build_reel_template_for_render_profile", _fake_template)
    monkeypatch.setattr(fc_module, "build_local_selected_slides", _fake_selected_slides)
    monkeypatch.setattr(fc_module, "prepare_reel_render_assets", _fake_prepare)
    monkeypatch.setattr(fc_module, "write_property_reel_manifest_from_data", _fake_manifest)
    monkeypatch.setattr(fc_module, "generate_property_reel_from_data", _fake_reel)
    monkeypatch.setattr(fc_module, "generate_property_poster_from_data", _fake_poster)
    return captured


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_render_media_returns_rendered_artifact_with_uuid_revision_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_primitives(monkeypatch)
    context = _build_context(tmp_path)
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared_assets(selected_dir)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    artifact = renderer.render_media(context, prepared)

    assert isinstance(artifact, RenderedMediaArtifact)
    assert artifact.artifact_kind == "reel_video"
    # uuid4().hex => 32 chars hex
    assert len(artifact.revision_id) == 32
    assert all(ch in "0123456789abcdef" for ch in artifact.revision_id)
    assert artifact.media_path.name == f"{context.property.slug}-reel.mp4"
    assert artifact.metadata_path is not None
    assert artifact.metadata_path.name == f"{context.property.slug}-reel.json"
    # 4 primitives invoked exactly once each.
    assert len(captured["prepare"]) == 1
    assert len(captured["manifest"]) == 1
    assert len(captured["reel"]) == 1
    assert len(captured["poster"]) == 1


def test_render_media_creates_staging_dir_under_generated_reels_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_primitives(monkeypatch)
    context = _build_context(tmp_path)
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared_assets(selected_dir)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    artifact = renderer.render_media(context, prepared)

    expected_staging_root = context.storage_paths.generated_reels_root / "_staging"
    assert artifact.staging_dir.parent == expected_staging_root
    assert artifact.staging_dir.exists()
    assert artifact.staging_dir.is_dir()
    # Prefix-based naming: tempfile.mkdtemp(prefix=f"{slug}-", dir=staging_root).
    assert artifact.staging_dir.name.startswith(f"{context.property.slug}-")


def test_render_media_invokes_prepare_reel_render_assets_with_workspace_and_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_primitives(monkeypatch)
    context = _build_context(tmp_path)
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared_assets(selected_dir)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    artifact = renderer.render_media(context, prepared)

    assert len(captured["prepare"]) == 1
    prepare_call = captured["prepare"][0]
    assert prepare_call["workspace"] == renderer.workspace_dir
    assert isinstance(prepare_call["render_data"], PropertyRenderData)
    assert prepare_call["working_dir"] == artifact.staging_dir / "_prepared"
    # Template was the one returned by `build_reel_template_for_render_profile`.
    assert len(captured["template"]) == 1
    assert captured["template"][0]["render_profile"] == context.delivery_plan.render_profile
    assert prepare_call["template"] is not None


def test_render_media_invokes_write_manifest_with_correct_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_primitives(monkeypatch)
    context = _build_context(tmp_path)
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared_assets(selected_dir)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    artifact = renderer.render_media(context, prepared)

    manifest_call = captured["manifest"][0]
    assert manifest_call["output_path"] == (
        artifact.staging_dir / f"{context.property.slug}-reel.json"
    )
    assert manifest_call["render_profile"] == context.delivery_plan.render_profile
    assert manifest_call["working_dir"] == artifact.staging_dir / "_prepared"


def test_render_media_invokes_generate_reel_with_correct_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_primitives(monkeypatch)
    context = _build_context(tmp_path)
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared_assets(selected_dir)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    artifact = renderer.render_media(context, prepared)

    reel_call = captured["reel"][0]
    assert reel_call["output_path"] == (
        artifact.staging_dir / f"{context.property.slug}-reel.mp4"
    )
    assert reel_call["working_dir"] == artifact.staging_dir / "_prepared"
    assert artifact.media_path == reel_call["output_path"]


def test_render_media_invokes_generate_poster_with_correct_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_primitives(monkeypatch)
    context = _build_context(tmp_path)
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared_assets(selected_dir)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    artifact = renderer.render_media(context, prepared)

    poster_call = captured["poster"][0]
    expected_poster_path = artifact.staging_dir / f"{context.property.slug}-poster.jpg"
    assert poster_call["output_path"] == expected_poster_path
    assert expected_poster_path.exists()


def test_render_video_alias_delegates_to_render_media(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _patch_primitives(monkeypatch)
    context = _build_context(tmp_path)
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared_assets(selected_dir)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    artifact = renderer.render_video(context, prepared)

    # Same primitive call counts as `render_media` — render_video is a 1:1 alias.
    assert len(captured["prepare"]) == 1
    assert len(captured["manifest"]) == 1
    assert len(captured["reel"]) == 1
    assert len(captured["poster"]) == 1
    assert isinstance(artifact, RenderedMediaArtifact)
    assert artifact.artifact_kind == "reel_video"


def test_build_render_data_maps_property_fields(tmp_path: Path) -> None:
    context = _build_context(tmp_path)
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    prepared = _build_prepared_assets(selected_dir)

    selected_slides = [{"slide": 1}, {"slide": 2}]
    render_data = DefaultMediaRenderer._build_render_data(
        context=context,
        prepared_assets=prepared,
        selected_slides=selected_slides,
    )

    assert isinstance(render_data, PropertyRenderData)
    assert render_data.site_id == context.site_id
    assert render_data.property_id == context.property.id
    assert render_data.slug == context.property.slug
    assert render_data.title == context.property.title
    assert render_data.link == context.property.link
    assert render_data.listing_lifecycle == context.delivery_plan.listing_lifecycle
    assert render_data.banner_text == context.delivery_plan.banner_text
    assert render_data.selected_image_dir == prepared.selected_dir
    assert render_data.selected_image_paths == prepared.selected_photo_paths
    assert render_data.featured_image_url == context.property.featured_image_url
    assert render_data.bedrooms == context.property.bedrooms
    assert render_data.agent_name == context.property.agent_name
    assert render_data.agency_logo_url == context.property.agency_logo_url
    assert render_data.price == context.property.price
    assert render_data.price_display_text == context.delivery_plan.price_display_text
    # selected_slides must be a tuple (not a list).
    assert isinstance(render_data.selected_slides, tuple)
    assert render_data.selected_slides == tuple(selected_slides)
