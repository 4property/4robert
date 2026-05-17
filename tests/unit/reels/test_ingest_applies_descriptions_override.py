"""Unit tests for feature 21 — ``descriptions_override`` merge during ingest.

The worker's render+publish loop assembles a ``PropertyContext`` by
running :class:`IngestPropertyIntoReelUseCase` first. The override
stored on ``reels.descriptions_override`` must be merged on top of the
freshly-templated captions before the context flows to
:class:`PublishReelUseCase`. These tests pin that behaviour with the
existing DB-free UoW stub pattern from
``tests/unit/reels/test_ingest_property_into_reel.py``.

Coverage:

* helper :func:`_apply_descriptions_override` is a per-platform merge
  that ignores ``None``/empty values defensively;
* the worker pipeline (ingest) propagates the override into
  ``PropertyContext.publish_descriptions_by_platform`` AND into the
  persisted ``publish_target_snapshot.descriptions_by_platform`` so the
  downstream social adapter (``property_publisher.py``) picks it up
  without further wiring;
* a reel without an override falls back to the auto-generated
  captions verbatim (regression guard for the "no override" path).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from modules.reels.application.use_cases.ingest_property_into_reel import (
    IngestPropertyIntoReelUseCase,
    _apply_descriptions_override,
)
from modules.reels.domain import ReelState, build_empty_reel_state
from modules.reels.domain.types import PropertyMediaJob, SocialPublishContext
from modules.tenancy.domain.context import TenantContext


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
    def __init__(self, *, existing: ReelState | None = None) -> None:
        self.existing = existing
        self.saved: list[ReelState] = []

    def get(self, *, external_source_id: str, source_property_id: int) -> ReelState | None:
        del external_source_id, source_property_id
        return self.existing

    def save(self, state: ReelState) -> None:
        self.saved.append(state)


def _build_uow(
    *,
    states: _StubReelStates | None = None,
    properties: _StubProperties | None = None,
) -> Any:
    return SimpleNamespace(
        catalog=SimpleNamespace(properties=properties or _StubProperties()),
        reels=SimpleNamespace(states=states or _StubReelStates()),
        configuration=SimpleNamespace(
            defaults=SimpleNamespace(get=lambda _agency_id: None),
            render_templates=SimpleNamespace(get=lambda _template_id: None),
        ),
    )


def _build_job_with_publish_context() -> PropertyMediaJob:
    """A job carrying a SocialPublishContext so the planning step actually
    generates per-platform captions (otherwise the override has nothing
    to merge on top of)."""
    tenant = TenantContext(
        site_id="site-a",
        agency_id="agency-1",
        wordpress_source_id="ingestion-1",
    )
    publish_context = SocialPublishContext.from_dict(
        {
            "provider": "gohighlevel",
            "location_id": "loc-1",
            "platforms": ["instagram", "linkedin"],
            "social_templates": [],
        }
    )
    return PropertyMediaJob(
        event_id="event-1",
        tenant=tenant,
        property_id=7,
        received_at="2026-05-02T10:00:00+00:00",
        raw_payload_hash="hash-1",
        payload=_PAYLOAD,
        publish_context=publish_context,
        job_id="job-1",
    )


# ---------------------------------------------------------------------------
# Helper unit tests
# ---------------------------------------------------------------------------


def test_apply_descriptions_override_replaces_per_platform() -> None:
    descriptions = {
        "instagram": "Auto IG caption.",
        "linkedin": "Auto LI caption.",
    }
    _apply_descriptions_override(
        descriptions,
        override={"instagram": "Custom IG override."},
    )
    # Instagram is overridden, LinkedIn stays on the templated text.
    assert descriptions == {
        "instagram": "Custom IG override.",
        "linkedin": "Auto LI caption.",
    }


def test_apply_descriptions_override_ignores_none_and_blank_values() -> None:
    descriptions = {
        "instagram": "Auto IG caption.",
        "linkedin": "Auto LI caption.",
        "facebook": "Auto FB caption.",
    }
    _apply_descriptions_override(
        descriptions,
        override={"instagram": None, "linkedin": "   ", "facebook": ""},
    )
    # All three were defensive sentinels — nothing changes.
    assert descriptions == {
        "instagram": "Auto IG caption.",
        "linkedin": "Auto LI caption.",
        "facebook": "Auto FB caption.",
    }


def test_apply_descriptions_override_with_none_or_empty_is_noop() -> None:
    descriptions = {"instagram": "Auto"}
    _apply_descriptions_override(descriptions, override=None)
    assert descriptions == {"instagram": "Auto"}
    _apply_descriptions_override(descriptions, override={})
    assert descriptions == {"instagram": "Auto"}


# ---------------------------------------------------------------------------
# End-to-end ingest behaviour
# ---------------------------------------------------------------------------


def test_ingest_propagates_override_into_publish_context(tmp_path: Path) -> None:
    """Existing override on ``ReelState`` must reach ``PropertyContext``."""
    existing_state = build_empty_reel_state(
        external_source_id="site-a", source_property_id=7
    )
    existing_state = ReelState(
        agency_id="agency-1",
        ingestion_source_id="ingestion-1",
        external_source_id="site-a",
        source_property_id=7,
        content_fingerprint="",
        content_snapshot={},
        publish_target_fingerprint="",
        publish_target_snapshot={},
        selected_image_folder="",
        artifact_kind="",
        local_artifact_path="",
        local_metadata_path="",
        render_profile="",
        local_manifest_path="",
        local_video_path="",
        render_status="",
        publish_status="needs-approval",
        workflow_state="awaiting_review",
        publish_details={},
        current_revision_id="",
        last_published_provider_external_id="",
        created_at="",
        updated_at="",
        descriptions_override={"instagram": "Editor-overridden IG copy."},
    )
    states = _StubReelStates(existing=existing_state)
    uow = _build_uow(states=states)

    use_case = IngestPropertyIntoReelUseCase(
        workspace_dir=tmp_path,
        property_url_template="https://example.com/{slug}",
        property_url_tracking_params=None,
        social_publishing_enabled=True,
    )
    context = use_case.execute(_build_job_with_publish_context(), uow=uow)

    # PropertyContext mirrors the override (Instagram), keeps the auto
    # caption for LinkedIn.
    assert (
        context.publish_descriptions_by_platform["instagram"]
        == "Editor-overridden IG copy."
    )
    assert context.publish_descriptions_by_platform.get("linkedin")
    assert (
        context.publish_descriptions_by_platform["linkedin"]
        != "Editor-overridden IG copy."
    )

    # The publish_target_snapshot persisted on the reels row also
    # reflects the merge, so a worker restart re-reads consistent data.
    parsed_snapshot = json.loads(context.publish_target_snapshot_json)
    assert (
        parsed_snapshot["descriptions_by_platform"]["instagram"]
        == "Editor-overridden IG copy."
    )

    # The save call preserved the override so a future ingest pass
    # still sees it.
    assert len(states.saved) == 1
    saved = states.saved[0]
    assert saved.descriptions_override == {
        "instagram": "Editor-overridden IG copy."
    }


def test_ingest_without_override_uses_generated_captions(tmp_path: Path) -> None:
    """No override → ``publish_descriptions_by_platform`` is whatever the
    content generator produced. Regression guard for the default path."""
    states = _StubReelStates(existing=None)
    uow = _build_uow(states=states)

    use_case = IngestPropertyIntoReelUseCase(
        workspace_dir=tmp_path,
        property_url_template="https://example.com/{slug}",
        property_url_tracking_params=None,
        social_publishing_enabled=True,
    )
    context = use_case.execute(_build_job_with_publish_context(), uow=uow)

    assert "instagram" in context.publish_descriptions_by_platform
    # No override key escaped into the descriptions.
    for caption in context.publish_descriptions_by_platform.values():
        assert "Editor-overridden" not in caption

    # And the persisted state carries ``descriptions_override=None``.
    assert len(states.saved) == 1
    assert states.saved[0].descriptions_override is None
