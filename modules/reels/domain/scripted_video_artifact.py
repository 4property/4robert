"""Scripted video artifact — output of the `scripted_render` job kind."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ScriptedVideoArtifact:
    render_id: str
    agency_id: str
    ingestion_source_id: str
    external_source_id: str
    source_property_id: int
    property_slug: str
    render_profile: str
    status: str
    request_manifest_json: str
    request_manifest_path: str
    resolved_manifest_path: str
    media_path: str
    error_message: str
    created_at: str
    updated_at: str


__all__ = ["ScriptedVideoArtifact"]
