"""Integration tests for the autoCaptions snapshot side of the renderer (feature 41).

The renderer's ``_render_reel`` flow now records the autoCaptions cues
(per-slide caption text + slide timing) onto the returned
``RenderedMediaArtifact``. ``PersistLocalArtifactsUseCase`` then forwards
the cues into the ``reels.auto_subtitles_snapshot`` JSONB column. These
tests assert:

* When ``subtitles_override is None``, the renderer computes a snapshot
  from the slide captions a stubbed Gemini pipeline produces.
* When ``subtitles_override`` is set, the renderer leaves
  ``auto_subtitles_snapshot=None`` on the artifact (no autoCaptions
  pipeline ran).
* The cue ``text`` is the verbatim caption attached to each slide — no
  reformatting / uppercase / truncation leaks in.

The heavy ffmpeg primitives are stubbed (the snapshot logic does not
need a real video) so the tests stay fast.
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
from modules.rendering.infrastructure.models import PropertyReelSlide
from modules.tenancy.domain.context import TenantContext
from shared.storage.site_layout import resolve_site_storage_layout


# The captions the stubbed Gemini pipeline would emit for the slides
# in this test. ``build_local_selected_slides`` is replaced below so
# the renderer sees these captions verbatim.
_STUB_CAPTIONS = (
    "Welcome to this stunning property",
    "Spacious kitchen with marble worktops",
    "Bright master bedroom",
    "Landscaped back garden",
)


def _stub_render_primitives(
    monkeypatch: pytest.MonkeyPatch,
    *,
    captions: tuple[str | None, ...] = _STUB_CAPTIONS,
    seconds_per_slide: float = 3.0,
    include_intro: bool = False,
    intro_duration_seconds: float = 0.0,
) -> dict[str, list[Any]]:
    """Stub the heavy primitives and force a deterministic template.

    Returns a captured dict the tests inspect to assert what
    ``RenderedMediaArtifact`` carries.
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
        seconds_per_slide = 3.0
        include_intro = False
        intro_duration_seconds = 0.0
        subtitle_font_size = 28
        max_slide_count = 8
        total_duration_seconds = 30.0

        def __init__(self) -> None:
            # Pydantic-free dataclass-style attributes; the renderer
            # reads them by attribute access.
            self.seconds_per_slide = seconds_per_slide
            self.include_intro = include_intro
            self.intro_duration_seconds = intro_duration_seconds

    def _fake_template(profile: str, *, template=None):
        return _StubTemplate()

    def _fake_selected_slides(selected_dir, paths):
        return tuple(
            PropertyReelSlide(
                image_path=Path(path),
                caption=(
                    captions[index]
                    if index < len(captions)
                    else None
                ),
            )
            for index, path in enumerate(paths)
        )

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
                "selected_slides": tuple(render_data.selected_slides),
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
        captured["manifest"].append({"output_path": str(output_path)})
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
        captured["reel"].append({"output_path": str(output_path)})
        Path(output_path).write_bytes(b"mp4-stub")

    def _fake_poster(
        workspace,
        render_data,
        *,
        output_path,
        template,
        layout_variant="classic",
    ):
        captured["poster"].append({"output_path": str(output_path)})
        Path(output_path).write_bytes(b"jpg-stub")

    monkeypatch.setattr(
        fc_module, "build_reel_template_for_render_profile", _fake_template
    )
    monkeypatch.setattr(fc_module, "build_local_selected_slides", _fake_selected_slides)
    monkeypatch.setattr(fc_module, "prepare_reel_render_assets", _fake_prepare)
    monkeypatch.setattr(fc_module, "write_property_reel_manifest_from_data", _fake_manifest)
    monkeypatch.setattr(fc_module, "generate_property_reel_from_data", _fake_reel)
    monkeypatch.setattr(fc_module, "generate_property_poster_from_data", _fake_poster)
    return captured


def _build_context(
    workspace: Path,
    *,
    subtitles_override: tuple[tuple[int, str, float, float], ...] | None = None,
) -> PropertyContext:
    site_id = "site-feature-41"
    storage_paths = resolve_site_storage_layout(workspace, site_id)
    property_item = Property.from_api_payload(
        {
            "id": 99,
            "slug": "auto-subtitles-snapshot-property",
            "title": {"rendered": "Auto Subtitles Snapshot Property"},
            "wppd_pics": [
                f"https://example.com/img-{idx}.jpg"
                for idx in range(len(_STUB_CAPTIONS))
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
        agency_id="agency-feature-41",
        wordpress_source_id="ingestion-1",
    )
    return PropertyContext(
        workspace_dir=workspace,
        storage_paths=storage_paths,
        tenant=tenant,
        property=property_item,
        delivery_plan=delivery_plan,
        subtitles_override=subtitles_override,
    )


def _build_prepared_assets(tmp_path: Path) -> PreparedMediaAssets:
    selected_dir = tmp_path / "selected"
    selected_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index in range(len(_STUB_CAPTIONS)):
        path = selected_dir / f"{index + 1:02d}_photo_{index}.jpg"
        path.write_bytes(f"stub-photo-{index}".encode())
        paths.append(path)
    return PreparedMediaAssets(
        selected_dir=selected_dir,
        selected_photo_paths=tuple(paths),
        downloaded_images=tuple(
            (index + 1, f"https://example.com/img-{index}.jpg", paths[index])
            for index in range(len(paths))
        ),
        primary_image_path=paths[0] if paths else None,
    )


def _expected_caption(raw: str) -> str:
    """Mirror the renderer's caption normalisation.

    ``normalize_caption`` appends a sentence terminator when the input
    does not already end with one (so subtitles always read as complete
    sentences). The snapshot stores the normalised text — the same
    text the renderer paints onscreen — so the editor sees exactly the
    cue that would be rendered.
    """
    from modules.rendering.infrastructure.ai_photo_selection.prompting import (
        normalize_caption,
    )

    return normalize_caption(raw, "")


def test_renderer_emits_auto_subtitles_snapshot_when_no_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No override → artifact carries the captions verbatim with the
    canonical timing window per slide.
    """
    _stub_render_primitives(monkeypatch)
    prepared = _build_prepared_assets(tmp_path)
    context = _build_context(tmp_path, subtitles_override=None)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    artifact = renderer.render_media(context, prepared)

    snapshot = artifact.auto_subtitles_snapshot
    assert snapshot is not None
    assert len(snapshot) == len(_STUB_CAPTIONS)
    for index, raw_text in enumerate(_STUB_CAPTIONS):
        cue = snapshot[index]
        assert cue["index"] == index
        assert cue["text"] == _expected_caption(raw_text)
        assert cue["in_seconds"] == pytest.approx(index * 3.0)
        assert cue["out_seconds"] == pytest.approx((index + 1) * 3.0)


def test_renderer_emits_no_snapshot_when_override_is_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With ``subtitles_override`` set, the autoCaptions composer is
    bypassed and the artifact must NOT carry a fresh snapshot — the
    previously-persisted column stays authoritative (preserved by the
    ``save_local_artifacts`` sentinel default).
    """
    _stub_render_primitives(monkeypatch)
    prepared = _build_prepared_assets(tmp_path)
    override = (
        (0, "Custom intro caption", 0.0, 2.5),
        (1, "Custom middle caption", 2.5, 5.0),
    )
    context = _build_context(tmp_path, subtitles_override=override)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    artifact = renderer.render_media(context, prepared)

    assert artifact.auto_subtitles_snapshot is None


def test_renderer_snapshot_skips_slides_without_caption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Slides whose Gemini caption is empty / ``None`` are dropped from
    the snapshot. The remaining cues keep monotonic indices.
    """
    captions = (
        _STUB_CAPTIONS[0],
        None,
        _STUB_CAPTIONS[2],
        "",
    )
    _stub_render_primitives(monkeypatch, captions=captions)
    prepared = _build_prepared_assets(tmp_path)
    context = _build_context(tmp_path, subtitles_override=None)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    artifact = renderer.render_media(context, prepared)

    snapshot = artifact.auto_subtitles_snapshot
    assert snapshot is not None
    assert len(snapshot) == 2
    assert snapshot[0]["text"] == _expected_caption(_STUB_CAPTIONS[0])
    assert snapshot[1]["text"] == _expected_caption(_STUB_CAPTIONS[2])
    # ``index`` is monotonic in cue order (the column is consumed by the
    # editor as ``ReelSubtitleCue`` payloads, which require monotone
    # indices).
    assert snapshot[0]["index"] == 0
    assert snapshot[1]["index"] == 1
    # The cue timing window matches the slide that produced it — slide
    # index 2 still spans ``[2 * 3.0, 3 * 3.0)`` because the autoCaptions
    # composer keys timing off the slide position, not the cue index.
    assert snapshot[1]["in_seconds"] == pytest.approx(2 * 3.0)
    assert snapshot[1]["out_seconds"] == pytest.approx(3 * 3.0)


def test_renderer_snapshot_includes_intro_when_template_has_intro(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An intro segment produces an extra cue at the start of the array
    spanning ``[0, intro_duration_seconds)``.
    """
    _stub_render_primitives(
        monkeypatch,
        include_intro=True,
        intro_duration_seconds=1.5,
    )
    prepared = _build_prepared_assets(tmp_path)
    context = _build_context(tmp_path, subtitles_override=None)

    renderer = DefaultMediaRenderer(workspace_dir=tmp_path)
    artifact = renderer.render_media(context, prepared)

    snapshot = artifact.auto_subtitles_snapshot
    assert snapshot is not None
    # 4 slides + 1 intro cue = 5 entries.
    assert len(snapshot) == 1 + len(_STUB_CAPTIONS)
    # The intro cue uses the first slide caption as its text (matches
    # the autoCaptions loop).
    intro_cue = snapshot[0]
    assert intro_cue["index"] == 0
    assert intro_cue["text"] == _expected_caption(_STUB_CAPTIONS[0])
    assert intro_cue["in_seconds"] == pytest.approx(0.0)
    assert intro_cue["out_seconds"] == pytest.approx(1.5)
    # The first slide cue starts at the end of the intro.
    first_slide_cue = snapshot[1]
    assert first_slide_cue["in_seconds"] == pytest.approx(1.5)
    assert first_slide_cue["out_seconds"] == pytest.approx(1.5 + 3.0)


# ---------------------------------------------------------------------------
# End-to-end: renderer artifact + PersistLocalArtifactsUseCase persistence
# ---------------------------------------------------------------------------


def test_persist_local_artifacts_writes_snapshot_when_artifact_carries_one(
    tmp_path: Path,
) -> None:
    """The renderer's ``RenderedMediaArtifact.auto_subtitles_snapshot``
    travels through ``PersistLocalArtifactsUseCase`` and lands on the
    ``reels.auto_subtitles_snapshot`` column.
    """
    from datetime import datetime, timezone

    from settings import DATABASE_URL
    from modules.reels.application.use_cases.persist_local_artifacts import (
        PersistLocalArtifactsUseCase,
    )
    from modules.reels.domain.types import RenderedMediaArtifact
    from shared.db import DatabaseUnitOfWork
    from tests.support.postgres import (
        seed_tenant,
        temporary_postgres_schema,
        temporary_workspace,
    )
    from tests.integration.reels._client import seed_property_with_reel

    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )

            # Build a context + a fake rendered artifact carrying a
            # snapshot. The persist use case writes to the row in place
            # and does not need a real video.
            storage_paths = resolve_site_storage_layout(
                workspace_dir, seeded.external_source_id
            )
            storage_paths.generated_reels_root.mkdir(parents=True, exist_ok=True)
            storage_paths.generated_posters_root.mkdir(parents=True, exist_ok=True)
            staging_dir = workspace_dir / "_staging"
            staging_dir.mkdir(parents=True, exist_ok=True)
            media_path = staging_dir / "sample-reel.mp4"
            metadata_path = staging_dir / "sample-reel.json"
            poster_path = staging_dir / "sample-poster.jpg"
            media_path.write_bytes(b"mp4-stub")
            metadata_path.write_text("{}", encoding="utf-8")
            poster_path.write_bytes(b"jpg-stub")

            property_item = Property.from_api_payload(
                {
                    "id": 42,
                    "slug": "sample",
                    "title": {"rendered": "Sample"},
                }
            )
            tenant = TenantContext(
                site_id=seeded.external_source_id,
                agency_id=seeded.agency_id,
                wordpress_source_id=seeded.ingestion_source_id,
            )
            delivery_plan = MediaDeliveryPlan(
                listing_lifecycle="for_sale",
                artifact_kind="reel_video",
                render_profile="for_sale_reel",
                social_post_type="reel",
                asset_strategy="curated_selection",
                banner_text="FOR SALE",
            )
            context = PropertyContext(
                workspace_dir=workspace_dir,
                storage_paths=storage_paths,
                tenant=tenant,
                property=property_item,
                delivery_plan=delivery_plan,
            )
            snapshot = [
                {
                    "index": 0,
                    "text": "First cue",
                    "in_seconds": 0.0,
                    "out_seconds": 3.0,
                },
                {
                    "index": 1,
                    "text": "Second cue",
                    "in_seconds": 3.0,
                    "out_seconds": 6.0,
                },
            ]
            rendered = RenderedMediaArtifact(
                staging_dir=staging_dir,
                artifact_kind="reel_video",
                media_path=media_path,
                metadata_path=metadata_path,
                revision_id="rev-1",
                auto_subtitles_snapshot=snapshot,
            )
            persist = PersistLocalArtifactsUseCase(
                workspace_dir=workspace_dir,
                database_locator=database.url,
            )
            persist.execute(context, rendered)

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                state = uow.reels.states.get(  # type: ignore[union-attr]
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                )
            assert state is not None
            assert state.auto_subtitles_snapshot == snapshot


def test_persist_local_artifacts_preserves_existing_snapshot_when_artifact_has_none(
    tmp_path: Path,
) -> None:
    """An artifact with ``auto_subtitles_snapshot=None`` must not clobber
    the previously-persisted column. This guards the
    "override-set render keeps the previous snapshot" contract.
    """
    import json

    from settings import DATABASE_URL
    from modules.reels.application.use_cases.persist_local_artifacts import (
        PersistLocalArtifactsUseCase,
    )
    from modules.reels.domain.types import RenderedMediaArtifact
    from shared.db import DatabaseUnitOfWork
    from sqlalchemy import create_engine, text as sa_text
    from tests.support.postgres import (
        seed_tenant,
        temporary_postgres_schema,
        temporary_workspace,
    )
    from tests.integration.reels._client import seed_property_with_reel

    existing_snapshot = [
        {
            "index": 0,
            "text": "Pre-existing cue",
            "in_seconds": 0.0,
            "out_seconds": 4.0,
        },
    ]
    serialised = json.dumps(existing_snapshot, separators=(",", ":"))

    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(
                database.url,
                site_id="ckp.ie",
                workspace_dir=workspace_dir,
            )
            seed_property_with_reel(
                database.url,
                agency_id=seeded.agency_id,
                ingestion_source_id=seeded.ingestion_source_id,
                external_source_id=seeded.external_source_id,
                source_property_id=42,
            )
            # Pre-seed the snapshot column.
            engine = create_engine(database.url, future=True)
            try:
                with engine.begin() as connection:
                    connection.execute(
                        sa_text(
                            "UPDATE reels SET auto_subtitles_snapshot = "
                            "CAST(:snapshot AS jsonb) "
                            "WHERE external_source_id = :site "
                            "AND source_property_id = :pid"
                        ),
                        {
                            "snapshot": serialised,
                            "site": seeded.external_source_id,
                            "pid": 42,
                        },
                    )
            finally:
                engine.dispose()

            storage_paths = resolve_site_storage_layout(
                workspace_dir, seeded.external_source_id
            )
            storage_paths.generated_reels_root.mkdir(parents=True, exist_ok=True)
            storage_paths.generated_posters_root.mkdir(parents=True, exist_ok=True)
            staging_dir = workspace_dir / "_staging"
            staging_dir.mkdir(parents=True, exist_ok=True)
            media_path = staging_dir / "sample-reel.mp4"
            metadata_path = staging_dir / "sample-reel.json"
            poster_path = staging_dir / "sample-poster.jpg"
            media_path.write_bytes(b"mp4-stub")
            metadata_path.write_text("{}", encoding="utf-8")
            poster_path.write_bytes(b"jpg-stub")

            property_item = Property.from_api_payload(
                {
                    "id": 42,
                    "slug": "sample",
                    "title": {"rendered": "Sample"},
                }
            )
            tenant = TenantContext(
                site_id=seeded.external_source_id,
                agency_id=seeded.agency_id,
                wordpress_source_id=seeded.ingestion_source_id,
            )
            delivery_plan = MediaDeliveryPlan(
                listing_lifecycle="for_sale",
                artifact_kind="reel_video",
                render_profile="for_sale_reel",
                social_post_type="reel",
                asset_strategy="curated_selection",
                banner_text="FOR SALE",
            )
            context = PropertyContext(
                workspace_dir=workspace_dir,
                storage_paths=storage_paths,
                tenant=tenant,
                property=property_item,
                delivery_plan=delivery_plan,
            )
            rendered = RenderedMediaArtifact(
                staging_dir=staging_dir,
                artifact_kind="reel_video",
                media_path=media_path,
                metadata_path=metadata_path,
                revision_id="rev-1",
                auto_subtitles_snapshot=None,
            )
            persist = PersistLocalArtifactsUseCase(
                workspace_dir=workspace_dir,
                database_locator=database.url,
            )
            persist.execute(context, rendered)

            with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                state = uow.reels.states.get(  # type: ignore[union-attr]
                    external_source_id=seeded.external_source_id,
                    source_property_id=42,
                )
            assert state is not None
            assert state.auto_subtitles_snapshot == existing_snapshot
