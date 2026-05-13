"""Unit tests for `PersistLocalArtifactsUseCase` (no DB).

Filesystem operations are exercised against a real `tempfile.TemporaryDirectory`
so the atomic moves and staging cleanup are validated end-to-end. Persistence
calls hit inline UoW stubs that record kwargs for assertion.
"""

from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from modules.catalog.domain.wordpress_property import Property
from modules.reels.domain.types import (
    MediaDeliveryPlan,
    PropertyContext,
    PublishedMediaArtifact,
    RenderedMediaArtifact,
)
from modules.tenancy.domain.context import TenantContext
from shared.errors import ValidationError
from modules.reels.application.use_cases.persist_local_artifacts import (
    PersistLocalArtifactsUseCase,
)
from modules.reels.domain import MediaRevision
from shared.storage.site_layout import resolve_site_storage_layout


_PAYLOAD = {
    "id": 7,
    "slug": "casa-feliz",
    "title": {"rendered": "Casa Feliz"},
    "link": "https://example.com/casa-feliz",
    "property_status": "for sale",
    "price": "100000",
    "wppd_pics": ["https://example.com/img1.jpg"],
}


# ---------------------------------------------------------------------------
# UoW stubs
# ---------------------------------------------------------------------------


class _StubReelStates:
    def __init__(self) -> None:
        self.local_artifacts_calls: list[dict[str, Any]] = []

    def save_local_artifacts(self, **kwargs: Any) -> None:
        self.local_artifacts_calls.append(kwargs)


class _StubMediaRevisions:
    def __init__(self) -> None:
        self.save_calls: list[MediaRevision] = []

    def save_revision(self, record: MediaRevision) -> None:
        self.save_calls.append(record)


class _StubOutbox:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def add_event(self, **kwargs: Any) -> None:
        self.events.append(kwargs)


def _build_uow(
    *,
    states: _StubReelStates | None = None,
    revisions: _StubMediaRevisions | None = None,
    outbox: _StubOutbox | None = None,
) -> Any:
    return SimpleNamespace(
        reels=SimpleNamespace(
            states=states or _StubReelStates(),
            revisions=revisions or _StubMediaRevisions(),
        ),
        delivery=SimpleNamespace(
            outbox=outbox or _StubOutbox(),
        ),
    )


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _build_context(
    workspace_dir: Path,
    *,
    artifact_kind: str = "reel_video",
    requires_render: bool = True,
    existing_published_media: PublishedMediaArtifact | None = None,
    render_template_id: str = "classic",
) -> PropertyContext:
    site_id = "site-a"
    storage_paths = resolve_site_storage_layout(workspace_dir, site_id)
    property_item = Property.from_api_payload(_PAYLOAD)
    delivery_plan = MediaDeliveryPlan(
        listing_lifecycle="for_sale",
        artifact_kind=artifact_kind,
        render_profile=(
            "for_sale_reel" if artifact_kind == "reel_video" else "for_sale_poster"
        ),
        social_post_type="reel" if artifact_kind == "reel_video" else "image",
        asset_strategy=(
            "curated_selection" if artifact_kind == "reel_video" else "primary_only"
        ),
        banner_text="FOR SALE",
        price_display_text=None,
    )
    tenant = TenantContext(
        site_id=site_id,
        agency_id="agency-1",
        wordpress_source_id="ingestion-1",
    )
    context = PropertyContext(
        workspace_dir=workspace_dir,
        storage_paths=storage_paths,
        tenant=tenant,
        property=property_item,
        delivery_plan=delivery_plan,
        requires_asset_preparation=False,
        requires_render=requires_render,
        requires_external_publish=False,
        content_fingerprint="content-fp",
        publish_target_fingerprint="publish-fp",
        existing_published_media=existing_published_media,
    )
    return replace(context, render_template_id=render_template_id)


def _build_rendered_media(
    *,
    staging_dir: Path,
    slug: str,
    artifact_kind: str = "reel_video",
    write_poster: bool = True,
    write_manifest: bool = True,
    revision_id: str = "revision-1",
) -> RenderedMediaArtifact:
    staging_dir.mkdir(parents=True, exist_ok=True)
    media_filename = (
        f"{slug}-reel.mp4" if artifact_kind == "reel_video" else f"{slug}-poster.jpg"
    )
    media_path = staging_dir / media_filename
    media_path.write_bytes(b"media-bytes")
    metadata_path: Path | None = None
    if write_manifest:
        metadata_path = staging_dir / f"{slug}-reel.json"
        metadata_path.write_bytes(b"{}")
    if write_poster:
        poster_path = staging_dir / f"{slug}-poster.jpg"
        poster_path.write_bytes(b"poster-bytes")
    return RenderedMediaArtifact(
        staging_dir=staging_dir,
        artifact_kind=artifact_kind,
        media_path=media_path,
        metadata_path=metadata_path,
        revision_id=revision_id,
    )


# ---------------------------------------------------------------------------
# Tests — happy path (reel_video)
# ---------------------------------------------------------------------------


def test_execute_reel_video_promotes_artifacts_and_writes_db(tmp_path: Path) -> None:
    context = _build_context(tmp_path, render_template_id="modern")
    with tempfile.TemporaryDirectory(dir=str(tmp_path)) as staging_root:
        staging_dir = Path(staging_root) / "staging"
        rendered = _build_rendered_media(
            staging_dir=staging_dir,
            slug=context.property.slug,
        )
        states = _StubReelStates()
        revisions = _StubMediaRevisions()
        outbox = _StubOutbox()
        uow = _build_uow(states=states, revisions=revisions, outbox=outbox)

        use_case = PersistLocalArtifactsUseCase(
            workspace_dir=tmp_path,
            cleanup_temporary_files=False,
        )
        result = use_case.execute(context, rendered, uow=uow)

    # Artifacts moved to canonical output directories.
    final_reels_dir = context.storage_paths.generated_reels_root
    final_posters_dir = context.storage_paths.generated_posters_root
    assert (final_reels_dir / f"{context.property.slug}-reel.mp4").exists()
    assert (final_reels_dir / f"{context.property.slug}-reel.json").exists()
    assert (final_posters_dir / f"{context.property.slug}-poster.jpg").exists()

    # The returned PublishedMediaArtifact points at the final paths.
    assert isinstance(result, PublishedMediaArtifact)
    assert result.artifact_kind == "reel_video"
    assert result.media_path == final_reels_dir / f"{context.property.slug}-reel.mp4"
    assert result.metadata_path == final_reels_dir / f"{context.property.slug}-reel.json"
    assert result.revision_id == "revision-1"

    # save_local_artifacts called once with modern column names.
    assert len(states.local_artifacts_calls) == 1
    call = states.local_artifacts_calls[0]
    assert call["agency_id"] == "agency-1"
    assert call["ingestion_source_id"] == "ingestion-1"
    assert call["external_source_id"] == "site-a"
    assert call["source_property_id"] == 7
    assert call["artifact_kind"] == "reel_video"
    assert call["render_profile"] == "for_sale_reel"
    assert call["current_revision_id"] == "revision-1"
    assert call["artifact_path"] == result.media_path
    assert call["metadata_path"] == result.metadata_path

    # save_revision once with the modern dataclass.
    assert len(revisions.save_calls) == 1
    record = revisions.save_calls[0]
    assert isinstance(record, MediaRevision)
    assert record.revision_id == "revision-1"
    assert record.agency_id == "agency-1"
    assert record.ingestion_source_id == "ingestion-1"
    assert record.external_source_id == "site-a"
    assert record.source_property_id == 7
    assert record.artifact_kind == "reel_video"
    assert record.render_profile == "for_sale_reel"
    assert record.render_template_id == "modern"
    assert record.workflow_state == "rendered"
    assert record.media_path  # non-empty relative path text
    assert record.metadata_path  # non-empty relative path text
    assert record.content_fingerprint == "content-fp"
    assert record.publish_target_fingerprint == "publish-fp"

    # outbox.add_event called once with media_rendered + payload extras.
    assert len(outbox.events) == 1
    event = outbox.events[0]
    assert event["event_type"] == "media_rendered"
    assert event["aggregate_type"] == "property_media"
    assert event["aggregate_id"] == "site-a:7"
    assert event["agency_id"] == "agency-1"
    assert event["ingestion_source_id"] == "ingestion-1"
    assert event["external_source_id"] == "site-a"
    assert event["source_property_id"] == 7
    assert event["event_id"]  # non-empty (uuid4 hex)
    payload = event["payload"]
    assert payload["workflow_state"] == "rendered"
    assert payload["revision_id"] == "revision-1"
    assert payload["render_template_id"] == "modern"
    assert payload["mime_type"] == record.mime_type
    assert payload["media_path"]
    assert payload["metadata_path"]


# ---------------------------------------------------------------------------
# Tests — poster_image path (no manifest)
# ---------------------------------------------------------------------------


def test_execute_poster_image_targets_posters_root_without_manifest(
    tmp_path: Path,
) -> None:
    context = _build_context(tmp_path, artifact_kind="poster_image")
    with tempfile.TemporaryDirectory(dir=str(tmp_path)) as staging_root:
        staging_dir = Path(staging_root) / "staging"
        rendered = _build_rendered_media(
            staging_dir=staging_dir,
            slug=context.property.slug,
            artifact_kind="poster_image",
            write_poster=False,
            write_manifest=False,
        )
        uow = _build_uow()

        use_case = PersistLocalArtifactsUseCase(
            workspace_dir=tmp_path,
            cleanup_temporary_files=False,
        )
        result = use_case.execute(context, rendered, uow=uow)

    final_posters_dir = context.storage_paths.generated_posters_root
    assert (final_posters_dir / f"{context.property.slug}-poster.jpg").exists()
    assert result.artifact_kind == "poster_image"
    assert result.metadata_path is None
    assert result.media_path == final_posters_dir / f"{context.property.slug}-poster.jpg"


# ---------------------------------------------------------------------------
# Tests — staging cleanup honours cleanup_temporary_files
# ---------------------------------------------------------------------------


def test_execute_cleans_staging_when_cleanup_temporary_files_is_true(
    tmp_path: Path,
) -> None:
    context = _build_context(tmp_path)
    staging_dir = tmp_path / "staging-cleaned"
    rendered = _build_rendered_media(
        staging_dir=staging_dir, slug=context.property.slug
    )
    uow = _build_uow()
    use_case = PersistLocalArtifactsUseCase(
        workspace_dir=tmp_path,
        cleanup_temporary_files=True,
    )
    use_case.execute(context, rendered, uow=uow)
    assert not staging_dir.exists()


def test_execute_keeps_staging_when_cleanup_temporary_files_is_false(
    tmp_path: Path,
) -> None:
    context = _build_context(tmp_path)
    staging_dir = tmp_path / "staging-kept"
    rendered = _build_rendered_media(
        staging_dir=staging_dir, slug=context.property.slug
    )
    uow = _build_uow()
    use_case = PersistLocalArtifactsUseCase(
        workspace_dir=tmp_path,
        cleanup_temporary_files=False,
    )
    use_case.execute(context, rendered, uow=uow)
    assert staging_dir.exists()


# ---------------------------------------------------------------------------
# Tests — POSTER_REQUIRED validation for reel_video
# ---------------------------------------------------------------------------


def test_execute_raises_poster_required_when_reel_video_has_no_poster(
    tmp_path: Path,
) -> None:
    context = _build_context(tmp_path)
    staging_dir = tmp_path / "staging-no-poster"
    rendered = _build_rendered_media(
        staging_dir=staging_dir,
        slug=context.property.slug,
        write_poster=False,
    )
    uow = _build_uow()
    use_case = PersistLocalArtifactsUseCase(workspace_dir=tmp_path)
    with pytest.raises(ValidationError) as excinfo:
        use_case.execute(context, rendered, uow=uow)
    assert excinfo.value.code == "POSTER_REQUIRED"


# ---------------------------------------------------------------------------
# Tests — execute_existing
# ---------------------------------------------------------------------------


def test_execute_existing_raises_when_no_existing_artifact(tmp_path: Path) -> None:
    context = _build_context(tmp_path, requires_render=False)
    use_case = PersistLocalArtifactsUseCase(workspace_dir=tmp_path)
    with pytest.raises(ValidationError) as excinfo:
        use_case.execute_existing(context)
    assert excinfo.value.code == "EXISTING_MEDIA_REQUIRED"


def test_execute_existing_returns_existing_artifact_without_db(tmp_path: Path) -> None:
    existing = PublishedMediaArtifact(
        artifact_kind="reel_video",
        media_path=tmp_path / "previous-reel.mp4",
        metadata_path=tmp_path / "previous-reel.json",
        mime_type="video/mp4",
        revision_id="prior-revision",
    )
    context = _build_context(
        tmp_path,
        requires_render=False,
        existing_published_media=existing,
    )
    states = _StubReelStates()
    revisions = _StubMediaRevisions()
    outbox = _StubOutbox()
    uow = _build_uow(states=states, revisions=revisions, outbox=outbox)

    use_case = PersistLocalArtifactsUseCase(workspace_dir=tmp_path)
    result = use_case.execute_existing(context, uow=uow)

    assert result is existing
    # No DB writes from the publish-only retry path.
    assert states.local_artifacts_calls == []
    assert revisions.save_calls == []
    assert outbox.events == []
