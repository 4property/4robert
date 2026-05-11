"""Unit tests for `PrepareReelAssetsUseCase` (no DB).

The HTTP client is stubbed via `monkeypatch` of `download_image` and
`download_and_filter_property_images` (the legacy entrypoints the use case
imports), so no traffic leaves the process.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from modules.catalog.domain.wordpress_property import Property
from modules.reels.domain.types import (
    MediaDeliveryPlan,
    PreparedMediaAssets,
    PropertyContext,
)
from modules.tenancy.domain.context import TenantContext
from shared.errors import PhotoFilteringError
from modules.reels.application.use_cases.prepare_reel_assets import (
    LocalPhotoSelectionEngine,
    PrepareReelAssetsUseCase,
)
from shared.storage.site_layout import resolve_site_storage_layout


_PAYLOAD = {
    "id": 7,
    "slug": "casa-feliz",
    "title": {"rendered": "Casa Feliz"},
    "link": "https://example.com/casa-feliz",
    "property_status": "for sale",
    "price": "100000",
    "wppd_pics": ["https://example.com/img1.jpg"],
    "wppd_primary_image": "https://example.com/featured.jpg",
}


# ---------------------------------------------------------------------------
# UoW stubs
# ---------------------------------------------------------------------------


class _StubProperties:
    def __init__(self, *, record_id: int = 11) -> None:
        self.record_id = record_id
        self.upserts: list[dict[str, Any]] = []

    def upsert_property(self, record: dict[str, Any]) -> int:
        self.upserts.append(dict(record))
        return self.record_id


class _StubImages:
    def __init__(self) -> None:
        self.replace_calls: list[tuple[int, list[tuple[int, str, Any]]]] = []

    def replace_images(
        self,
        record_id: int,
        downloaded_images: Any,
    ) -> None:
        self.replace_calls.append((record_id, list(downloaded_images)))


class _StubReelStates:
    def __init__(self) -> None:
        self.workflow_calls: list[dict[str, Any]] = []

    def update_workflow_state(self, **kwargs: Any) -> None:
        self.workflow_calls.append(kwargs)


def _build_uow(
    *,
    properties: _StubProperties | None = None,
    images: _StubImages | None = None,
    states: _StubReelStates | None = None,
) -> Any:
    return SimpleNamespace(
        catalog=SimpleNamespace(
            properties=properties or _StubProperties(),
            images=images or _StubImages(),
        ),
        reels=SimpleNamespace(
            states=states or _StubReelStates(),
        ),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_context(
    workspace_dir: Path,
    *,
    asset_strategy: str = "curated_selection",
    requires_asset_preparation: bool = True,
    payload: dict[str, Any] | None = None,
) -> PropertyContext:
    site_id = "site-a"
    storage_paths = resolve_site_storage_layout(workspace_dir, site_id)
    property_item = Property.from_api_payload(payload if payload is not None else _PAYLOAD)
    delivery_plan = MediaDeliveryPlan(
        listing_lifecycle="for_sale",
        artifact_kind="reel_video" if asset_strategy != "primary_only" else "poster_image",
        render_profile="for_sale_reel",
        social_post_type="reel",
        asset_strategy=asset_strategy,
        banner_text="FOR SALE",
        price_display_text=None,
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
        requires_asset_preparation=requires_asset_preparation,
        requires_render=True,
        requires_external_publish=False,
    )


# ---------------------------------------------------------------------------
# Tests — curated path
# ---------------------------------------------------------------------------


def test_execute_curated_path_persists_property_images_and_workflow_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _build_context(tmp_path)
    selected_dir = (
        context.storage_paths.filtered_images_root
        / context.property.folder_name
        / "selected_photos"
    )
    selected_dir.mkdir(parents=True, exist_ok=True)
    fake_image = selected_dir / "01_house.jpg"
    fake_image.write_bytes(b"fake-jpg-bytes")
    primary_image = selected_dir / "primary_image.jpg"
    primary_image.write_bytes(b"fake-primary-bytes")
    captured_calls: dict[str, Any] = {}

    def _fake_select_photos(self, *, property_item, raw_images_root, filtered_images_root):  # type: ignore[no-untyped-def]
        captured_calls["raw"] = raw_images_root
        captured_calls["filtered"] = filtered_images_root
        return selected_dir, [
            (1, "https://example.com/img1.jpg", fake_image),
        ]

    monkeypatch.setattr(LocalPhotoSelectionEngine, "select_photos", _fake_select_photos)

    properties = _StubProperties(record_id=42)
    images = _StubImages()
    states = _StubReelStates()
    uow = _build_uow(properties=properties, images=images, states=states)

    use_case = PrepareReelAssetsUseCase(workspace_dir=tmp_path)
    result = use_case.execute(context, uow=uow)

    # Engine was wired with the right roots.
    assert captured_calls["raw"] == context.storage_paths.raw_images_root
    assert captured_calls["filtered"] == context.storage_paths.filtered_images_root

    # Catalog upsert used the canonical column names.
    assert len(properties.upserts) == 1
    record = properties.upserts[0]
    assert record["external_source_id"] == "site-a"
    assert record["ingestion_source_id"] == "ingestion-1"
    assert record["agency_id"] == "agency-1"
    assert record["source_property_id"] == 7
    assert "site_id" not in record
    assert "wordpress_source_id" not in record

    # Image replacement keyed on the upserted record_id.
    assert len(images.replace_calls) == 1
    record_id, downloaded = images.replace_calls[0]
    assert record_id == 42
    assert downloaded == [(1, "https://example.com/img1.jpg", fake_image)]

    # Workflow bumped to assets_prepared with modern parameter names.
    assert len(states.workflow_calls) == 1
    workflow = states.workflow_calls[0]
    assert workflow["workflow_state"] == "assets_prepared"
    assert workflow["external_source_id"] == "site-a"
    assert workflow["ingestion_source_id"] == "ingestion-1"
    assert workflow["agency_id"] == "agency-1"
    assert workflow["source_property_id"] == 7
    assert workflow["current_revision_id"] is None

    # Returned PreparedMediaAssets reflects the on-disk state.
    assert isinstance(result, PreparedMediaAssets)
    assert result.selected_dir == selected_dir
    assert result.primary_image_path == primary_image
    assert fake_image in result.selected_photo_paths


# ---------------------------------------------------------------------------
# Tests — primary-only path
# ---------------------------------------------------------------------------


def test_execute_primary_only_path_downloads_featured_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _build_context(tmp_path, asset_strategy="primary_only")

    download_calls: list[tuple[str, Path]] = []

    def _fake_download_image(image_url: str, destination: Path) -> None:
        download_calls.append((image_url, destination))
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"fake-primary-bytes")

    monkeypatch.setattr(
        "modules.reels.application.use_cases.prepare_reel_assets.download_image",
        _fake_download_image,
    )

    properties = _StubProperties(record_id=99)
    images = _StubImages()
    states = _StubReelStates()
    uow = _build_uow(properties=properties, images=images, states=states)

    use_case = PrepareReelAssetsUseCase(workspace_dir=tmp_path)
    result = use_case.execute(context, uow=uow)

    # The featured URL was the source for the primary download.
    assert download_calls
    download_url, _ = download_calls[0]
    assert download_url == "https://example.com/featured.jpg"

    # Primary file was placed in the selected_photos directory.
    assert result.primary_image_path is not None
    assert result.primary_image_path.exists()
    assert result.primary_image_path.parent.name == "selected_photos"
    assert result.primary_image_path.read_bytes() == b"fake-primary-bytes"

    # Persistence ran for the primary-only path too.
    assert len(properties.upserts) == 1
    assert images.replace_calls and images.replace_calls[0][0] == 99
    assert states.workflow_calls
    assert states.workflow_calls[0]["workflow_state"] == "assets_prepared"


# ---------------------------------------------------------------------------
# Tests — already-prepared short-circuit
# ---------------------------------------------------------------------------


def test_execute_returns_existing_assets_without_persisting_when_not_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _build_context(tmp_path, requires_asset_preparation=False)
    selected_dir = (
        context.storage_paths.filtered_images_root
        / context.property.folder_name
        / "selected_photos"
    )
    selected_dir.mkdir(parents=True, exist_ok=True)
    existing_image = selected_dir / "01_existing.jpg"
    existing_image.write_bytes(b"existing")

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Engine should NOT be called when assets exist already.")

    monkeypatch.setattr(LocalPhotoSelectionEngine, "select_photos", _explode)
    monkeypatch.setattr(
        "modules.reels.application.use_cases.prepare_reel_assets.download_image",
        _explode,
    )

    properties = _StubProperties()
    images = _StubImages()
    states = _StubReelStates()
    uow = _build_uow(properties=properties, images=images, states=states)

    use_case = PrepareReelAssetsUseCase(workspace_dir=tmp_path)
    result = use_case.execute(context, uow=uow)

    assert existing_image in result.selected_photo_paths
    # No persistence calls — the use case short-circuited before opening the UoW path.
    assert properties.upserts == []
    assert images.replace_calls == []
    assert states.workflow_calls == []


# ---------------------------------------------------------------------------
# Tests — error paths
# ---------------------------------------------------------------------------


def test_execute_curated_path_wraps_unexpected_engine_error_as_photo_filtering_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _build_context(tmp_path)

    def _boom(self, *, property_item, raw_images_root, filtered_images_root):  # type: ignore[no-untyped-def]
        raise RuntimeError("network down")

    monkeypatch.setattr(LocalPhotoSelectionEngine, "select_photos", _boom)

    use_case = PrepareReelAssetsUseCase(workspace_dir=tmp_path)
    uow = _build_uow()

    with pytest.raises(PhotoFilteringError) as excinfo:
        use_case.execute(context, uow=uow)
    assert excinfo.value.code == "CURATED_ASSET_PREPARATION_FAILED"


def test_execute_primary_only_path_raises_when_no_image_url_is_available(
    tmp_path: Path,
) -> None:
    payload_without_images = {
        "id": 11,
        "slug": "blank-house",
        "title": {"rendered": "Blank House"},
        "link": "https://example.com/blank-house",
        "property_status": "for sale",
        "price": "0",
    }
    context = _build_context(
        tmp_path,
        asset_strategy="primary_only",
        payload=payload_without_images,
    )

    use_case = PrepareReelAssetsUseCase(workspace_dir=tmp_path)
    uow = _build_uow()

    with pytest.raises(PhotoFilteringError) as excinfo:
        use_case.execute(context, uow=uow)
    assert excinfo.value.code == "PRIMARY_IMAGE_MISSING"


# ---------------------------------------------------------------------------
# Tests — cleanup
# ---------------------------------------------------------------------------


def test_cleanup_removes_selected_dir_when_cleanup_selected_photos_is_true(
    tmp_path: Path,
) -> None:
    context = _build_context(tmp_path)
    selected_dir = tmp_path / "to_cleanup"
    selected_dir.mkdir()
    (selected_dir / "image.jpg").write_bytes(b"x")
    prepared = PreparedMediaAssets(
        selected_dir=selected_dir,
        selected_photo_paths=tuple(selected_dir.iterdir()),
        downloaded_images=(),
        primary_image_path=None,
    )

    use_case = PrepareReelAssetsUseCase(
        workspace_dir=tmp_path,
        cleanup_selected_photos=True,
    )
    use_case.cleanup(context, prepared)
    assert not selected_dir.exists()


def test_cleanup_keeps_selected_dir_when_cleanup_selected_photos_is_false(
    tmp_path: Path,
) -> None:
    context = _build_context(tmp_path)
    selected_dir = tmp_path / "keep"
    selected_dir.mkdir()
    (selected_dir / "image.jpg").write_bytes(b"x")
    prepared = PreparedMediaAssets(
        selected_dir=selected_dir,
        selected_photo_paths=tuple(selected_dir.iterdir()),
        downloaded_images=(),
        primary_image_path=None,
    )

    use_case = PrepareReelAssetsUseCase(
        workspace_dir=tmp_path,
        cleanup_selected_photos=False,
    )
    use_case.cleanup(context, prepared)
    assert selected_dir.exists()
