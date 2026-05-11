"""Unit tests for `IngestPropertyIntoReelUseCase` (no DB)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from modules.reels.domain.types import PropertyMediaJob
from modules.tenancy.domain.context import TenantContext
from modules.reels.application.use_cases.ingest_property_into_reel import (
    IngestPropertyIntoReelUseCase,
)
from modules.reels.domain import build_empty_reel_state


_PAYLOAD = {
    "id": 7,
    "slug": "casa-feliz",
    "title": {"rendered": "Casa Feliz"},
    "link": "https://example.com/casa-feliz",
    "property_status": "for sale",
    "price": "100000",
    "wppd_pics": ["https://example.com/img1.jpg"],
}


class _StubProperties:
    def __init__(self) -> None:
        self.upserts: list[dict[str, Any]] = []

    def upsert_property(self, record: dict[str, Any]) -> int:
        self.upserts.append(dict(record))
        return 1


class _StubReelStates:
    def __init__(self, *, existing: Any = None) -> None:
        self.existing = existing
        self.saved: list[Any] = []

    def get(self, *, external_source_id: str, source_property_id: int) -> Any:
        del external_source_id, source_property_id
        return self.existing

    def save(self, state: Any) -> None:
        self.saved.append(state)


def _build_uow(
    *,
    states: _StubReelStates | None = None,
    properties: _StubProperties | None = None,
) -> Any:
    return SimpleNamespace(
        catalog=SimpleNamespace(properties=properties or _StubProperties()),
        reels=SimpleNamespace(states=states or _StubReelStates()),
    )


def _build_job() -> PropertyMediaJob:
    tenant = TenantContext(
        site_id="site-a",
        agency_id="agency-1",
        wordpress_source_id="ingestion-1",
    )
    return PropertyMediaJob(
        event_id="event-1",
        tenant=tenant,
        property_id=7,
        received_at="2026-05-02T10:00:00+00:00",
        raw_payload_hash="hash-1",
        payload=_PAYLOAD,
        publish_context=None,
        job_id="job-1",
    )


def test_execute_persists_state_and_returns_context_for_fresh_property(tmp_path: Path) -> None:
    states = _StubReelStates(existing=None)
    properties = _StubProperties()
    uow = _build_uow(states=states, properties=properties)

    use_case = IngestPropertyIntoReelUseCase(
        workspace_dir=tmp_path,
        property_url_template="",
        property_url_tracking_params=None,
        social_publishing_enabled=False,
    )
    context = use_case.execute(_build_job(), uow=uow)

    # Catalog upsert ran with the canonical column names.
    assert len(properties.upserts) == 1
    record = properties.upserts[0]
    assert record["external_source_id"] == "site-a"
    assert record["ingestion_source_id"] == "ingestion-1"
    assert record["agency_id"] == "agency-1"
    assert record["source_property_id"] == 7
    assert "site_id" not in record  # legacy alias must be translated.
    assert "wordpress_source_id" not in record

    # ReelState was saved with workflow_state="ingested".
    assert len(states.saved) == 1
    saved_state = states.saved[0]
    assert saved_state.workflow_state == "ingested"
    assert saved_state.external_source_id == "site-a"
    assert saved_state.source_property_id == 7
    assert saved_state.publish_status == "skipped"  # publish_context is None
    assert saved_state.render_status == "pending"
    # Snapshots are dicts (JSONB-friendly), not strings.
    assert isinstance(saved_state.content_snapshot, dict)
    assert isinstance(saved_state.publish_target_snapshot, dict)
    assert saved_state.publish_target_snapshot == {}  # No publish context.

    # PropertyContext keeps the legacy string-based snapshots for steps 2-4.
    assert isinstance(context.content_snapshot_json, str)
    assert isinstance(context.publish_target_snapshot_json, str)
    parsed_snapshot = json.loads(context.content_snapshot_json)
    assert parsed_snapshot["delivery_plan"]["listing_lifecycle"] == "for_sale"
    assert context.requires_render is True
    assert context.requires_external_publish is False
    assert context.is_noop is False
    assert context.content_fingerprint  # non-empty hash.


def test_execute_is_noop_when_state_unchanged_and_artifacts_present(tmp_path: Path) -> None:
    # Run once to discover the fingerprints + snapshot the use case would produce.
    discovery_states = _StubReelStates(existing=None)
    discovery_properties = _StubProperties()
    discovery_uow = _build_uow(states=discovery_states, properties=discovery_properties)
    discovery = IngestPropertyIntoReelUseCase(
        workspace_dir=tmp_path,
        property_url_template="",
        property_url_tracking_params=None,
        social_publishing_enabled=False,
    ).execute(_build_job(), uow=discovery_uow)

    # Now seed an existing state that matches the snapshot/fingerprint and
    # has artifacts on disk so `_has_local_artifacts` returns True.
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    media_file = artifact_dir / "reel.mp4"
    media_file.write_bytes(b"video-bytes")
    metadata_file = artifact_dir / "reel.json"
    metadata_file.write_bytes(b"{}")
    poster_dir = tmp_path / "generated_media" / "site-a" / "posters"
    poster_dir.mkdir(parents=True)
    poster_file = poster_dir / "casa-feliz-poster.jpg"
    poster_file.write_bytes(b"poster")

    seeded_state = build_empty_reel_state(
        external_source_id="site-a", source_property_id=7
    )
    seeded_state = type(seeded_state)(
        agency_id="agency-1",
        ingestion_source_id="ingestion-1",
        external_source_id="site-a",
        source_property_id=7,
        content_fingerprint=discovery.content_fingerprint,
        content_snapshot=json.loads(discovery.content_snapshot_json),
        publish_target_fingerprint=discovery.publish_target_fingerprint,
        publish_target_snapshot=json.loads(discovery.publish_target_snapshot_json or "{}"),
        selected_image_folder="",
        artifact_kind="reel_video",
        local_artifact_path=str(media_file.relative_to(tmp_path)),
        local_metadata_path=str(metadata_file.relative_to(tmp_path)),
        render_profile="for_sale_reel",
        local_manifest_path=str(metadata_file.relative_to(tmp_path)),
        local_video_path=str(media_file.relative_to(tmp_path)),
        render_status="completed",
        publish_status="skipped",
        workflow_state="ingested",
        publish_details={},
        current_revision_id="rev-1",
        last_published_provider_external_id="",
        created_at="",
        updated_at="",
    )
    states = _StubReelStates(existing=seeded_state)
    uow = _build_uow(states=states)
    use_case = IngestPropertyIntoReelUseCase(
        workspace_dir=tmp_path,
        property_url_template="",
        property_url_tracking_params=None,
        social_publishing_enabled=False,
    )
    context = use_case.execute(_build_job(), uow=uow)

    assert context.is_noop is True
    assert context.requires_render is False
    # No save should fire on a noop run.
    assert states.saved == []


def test_execute_propagates_when_payload_is_not_a_mapping(tmp_path: Path) -> None:
    uow = _build_uow()
    use_case = IngestPropertyIntoReelUseCase(
        workspace_dir=tmp_path,
        property_url_template="",
        property_url_tracking_params=None,
        social_publishing_enabled=False,
    )
    bad_job = PropertyMediaJob(
        event_id="event-1",
        tenant=TenantContext(
            site_id="site-a",
            agency_id="agency-1",
            wordpress_source_id="ingestion-1",
        ),
        property_id=7,
        received_at="2026-05-02T10:00:00+00:00",
        raw_payload_hash="hash-1",
        payload="not-a-mapping",  # type: ignore[arg-type]
        publish_context=None,
        job_id="job-1",
    )

    with pytest.raises(TypeError, match="Property payload must be a mapping"):
        use_case.execute(bad_job, uow=uow)

    # Failure happens before any DB write.
    assert uow.catalog.properties.upserts == []
    assert uow.reels.states.saved == []
