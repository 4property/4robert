"""Pydantic payloads for the admin reels router.

The admin "Reels" view exposes a flat record per reel that joins the
`properties` row, the latest `reels` row, and the most recent
`media_revisions` snapshot. The payloads below mirror the legacy
serializer shape so the frontend can switch transport without changes.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AgencyReelItemPayload(BaseModel):
    """Flat shape for one reel in the admin "Reels" view."""

    model_config = ConfigDict(extra="forbid")

    site_id: str
    source_property_id: int
    slug: str
    title: str | None = None
    link: str | None = None
    price: str | None = None
    property_status: str | None = None
    property_type_label: str | None = None
    property_area_label: str | None = None
    property_county_label: str | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    featured_image_url: str | None = None
    agent_name: str | None = None
    workflow_state: str = ""
    publish_status: str = ""
    render_status: str = ""
    last_published_location_id: str = ""
    current_revision_id: str = ""
    pipeline_updated_at: str = ""
    pipeline_created_at: str = ""
    fetched_at: str = ""
    revision_media_path: str = ""
    revision_metadata_path: str = ""
    revision_artifact_kind: str = ""
    revision_created_at: str = ""


class ListReelsResponse(BaseModel):
    """Body for `GET /v1/admin/agencies/{agency_id}/reels`."""

    model_config = ConfigDict(extra="forbid")

    items: list[AgencyReelItemPayload]
    count: int


class InspectReelResponseItem(AgencyReelItemPayload):
    """Detail item adds a flag and resolved video URL."""

    model_config = ConfigDict(extra="forbid")

    has_video: bool = False
    video_url: str | None = None


class InspectReelResponse(BaseModel):
    """Body for `GET /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}`."""

    model_config = ConfigDict(extra="forbid")

    reel: InspectReelResponseItem


class RegenerateReelResponse(BaseModel):
    """Body for `POST .../approve` (use case `regenerate_reel`).

    Mirrors the legacy contract: 200 with `publish_enqueued=True/False`
    so the frontend can render the success-without-publish state when
    prerequisites are missing (no raw payload, no GHL connection).
    """

    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="approved")
    publish_enqueued: bool
    event_id: str | None = None
    job_id: str | None = None
    reason: str | None = None
    hint: str | None = None
    reel: AgencyReelItemPayload


class RejectReelResponse(BaseModel):
    """Body for `POST .../reject`."""

    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="rejected")
    reel: AgencyReelItemPayload


__all__ = [
    "AgencyReelItemPayload",
    "InspectReelResponse",
    "InspectReelResponseItem",
    "ListReelsResponse",
    "RegenerateReelResponse",
    "RejectReelResponse",
]
