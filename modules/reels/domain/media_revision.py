"""Media revision aggregate — immutable render history."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MediaRevision:
    revision_id: str
    agency_id: str
    ingestion_source_id: str
    external_source_id: str
    source_property_id: int
    artifact_kind: str
    render_profile: str
    media_path: str
    metadata_path: str
    mime_type: str
    content_fingerprint: str
    publish_target_fingerprint: str
    workflow_state: str
    created_at: str
    render_template_id: str = "classic"


__all__ = ["MediaRevision"]
