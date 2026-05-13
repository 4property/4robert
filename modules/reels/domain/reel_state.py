"""Reel pipeline state aggregate (was `property_pipeline_state`).

PK is `(external_source_id, source_property_id)`. Carries the latest workflow
state, render output paths, publish status and the pointer to the current
`media_revisions` row.
"""

from __future__ import annotations

from dataclasses import dataclass
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
