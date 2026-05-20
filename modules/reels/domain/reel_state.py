"""Reel pipeline state aggregate (was `property_pipeline_state`).

PK is `(external_source_id, source_property_id)`. Carries the latest workflow
state, render output paths, publish status and the pointer to the current
`media_revisions` row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(slots=True)
class ReelState:
    agency_id: str
    ingestion_source_id: str
    external_source_id: str
    source_property_id: int
    content_fingerprint: str
    content_snapshot: Mapping[str, Any]
    publish_target_fingerprint: str
    publish_target_snapshot: Mapping[str, Any]
    selected_image_folder: str
    artifact_kind: str
    local_artifact_path: str
    local_metadata_path: str
    render_profile: str
    local_manifest_path: str
    local_video_path: str
    render_status: str
    publish_status: str
    workflow_state: str
    publish_details: Mapping[str, Any]
    current_revision_id: str
    last_published_provider_external_id: str
    created_at: str
    updated_at: str
    render_template_id: str = "classic"
    # Feature 21: per-reel caption override. ``None`` means "no override —
    # fall back to ``publish_target_snapshot.descriptions_by_platform``";
    # an empty dict is treated the same way. Otherwise the keys are
    # platform names (matching the agency's ``agency_reel_defaults.platforms``)
    # and the values are the rendered caption text (no ``{{ variables }}``).
    descriptions_override: Mapping[str, Any] | None = field(default=None)
    # Feature 25: per-reel music override. ``None`` (and empty string)
    # means "no override — fall back to the agency pool resolver"
    # (features 23 / 24). Otherwise the value is the ``id`` of a row in
    # ``agency_music_tracks`` belonging to the same agency as the reel
    # (the use case validates cross-agency at PATCH time; the FK
    # guarantees referential integrity but not the same-agency
    # invariant).
    music_id: str | None = field(default=None)
    # Feature 35: per-reel photo override. ``None`` means "no override —
    # fall back to the default order from ``property_images`` /
    # ``media_revisions``". Otherwise an ordered list of
    # ``{"position": int, "selected": bool}`` entries whose ``position``
    # keys cover the range ``[0, N)`` exactly once each. Each entry's
    # ``position`` refers to the original photo index (0-based);
    # ``selected=false`` drops the photo from the rendered reel. The
    # array order is the render order, so a reversed list produces a
    # reel whose slides play in reverse.
    photos_override: list[dict[str, Any]] | None = field(default=None)
    # Feature 36: per-reel subtitle override. ``None`` means "no
    # override — keep the existing ``autoCaptions`` flow (subtitles
    # rendered when ``automation.autoCaptions`` is enabled, nothing
    # otherwise)". Otherwise an ordered list of
    # ``{"index": int, "text": str, "in_seconds": float,
    # "out_seconds": float}`` entries whose ``index`` keys are unique
    # and monotonically increasing, with non-overlapping timing windows
    # (``out_seconds > in_seconds`` and ``in_seconds >= 0``). The
    # ``text`` is 1-200 characters of literal caption text — no
    # ``{{ variables }}`` are interpolated. When present, the renderer
    # bypasses the autoCaptions composer entirely and burns the cues
    # via the same drawtext pipeline.
    subtitles_override: list[dict[str, Any]] | None = field(default=None)
    # Feature 37: per-reel slide manifest override. ``None`` means "no
    # override — fall back to the auto-generated manifest pipeline".
    # Otherwise an ordered list of
    # ``{"slide_id": str, "position": int, "duration_seconds": float,
    # "kind": str, ...kind-specific fields}`` entries. ``kind`` is one
    # of ``{"photo", "voiceover", "text", "intro_card", "outro_card"}``
    # and each kind carries its own required fields validated by the
    # PATCH layer (positions cover ``[0, N)`` exactly, slide_ids unique
    # non-empty strings, durations positive floats summing to at most
    # ``1.5 * target_duration_seconds``). The renderer reads this array
    # and drives the scene list directly instead of running the
    # auto-generation pipeline.
    manifest_override: list[dict[str, Any]] | None = field(default=None)
    # Feature 41: snapshot of the autoCaptions cues produced by the
    # renderer on the most recent render whose ``subtitles_override``
    # was ``None``. ``None`` means "no snapshot yet"; otherwise the
    # list has the same shape as ``subtitles_override`` (cues of
    # ``{"index": int, "text": str, "in_seconds": float,
    # "out_seconds": float}``) so the editor can pre-fill the cue
    # array from this column when no override has been set yet.
    # Refreshed on every render that runs the autoCaptions flow;
    # preserved untouched when the renderer consumes the override
    # (since the autoCaptions flow does not run in that branch).
    auto_subtitles_snapshot: list[dict[str, Any]] | None = field(default=None)


def build_empty_reel_state(
    *, external_source_id: str, source_property_id: int
) -> ReelState:
    return ReelState(
        agency_id="",
        ingestion_source_id="",
        external_source_id=external_source_id,
        source_property_id=source_property_id,
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
        publish_status="",
        workflow_state="",
        publish_details={},
        current_revision_id="",
        last_published_provider_external_id="",
        created_at="",
        updated_at="",
        render_template_id="classic",
    )


__all__ = ["ReelState", "build_empty_reel_state"]
