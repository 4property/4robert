from __future__ import annotations

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from repositories.postgres.base import Base


class AgencyModel(Base):
    __tablename__ = "agencies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="UTC")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class WordPressSourceModel(Base):
    __tablename__ = "wordpress_sources"
    __table_args__ = (
        UniqueConstraint("site_id", name="uq_wordpress_sources_site_id"),
        UniqueConstraint("agency_id", "normalized_host", name="uq_wordpress_sources_host"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(String(36), ForeignKey("agencies.id"), nullable=False)
    site_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    site_url: Mapped[str | None] = mapped_column(Text)
    normalized_host: Mapped[str] = mapped_column(Text, nullable=False)
    webhook_secret_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, default=b"")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    last_event_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class PropertyModel(Base):
    __tablename__ = "properties"
    __table_args__ = (
        UniqueConstraint("site_id", "source_property_id", name="uq_properties_site_property"),
        Index("idx_properties_site_slug", "site_id", "slug"),
        Index("idx_properties_site_fetched_at", "site_id", "fetched_at"),
    )

    record_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agency_id: Mapped[str] = mapped_column(String(36), ForeignKey("agencies.id"), nullable=False)
    wordpress_source_id: Mapped[str] = mapped_column(String(36), ForeignKey("wordpress_sources.id"), nullable=False)
    site_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_property_id: Mapped[int] = mapped_column(Integer, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    guid: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    resource_type: Mapped[str | None] = mapped_column(Text)
    author_id: Mapped[int | None] = mapped_column(Integer)
    importer_id: Mapped[str | None] = mapped_column(Text)
    list_reference: Mapped[str | None] = mapped_column(Text)
    date: Mapped[str | None] = mapped_column(Text)
    date_gmt: Mapped[str | None] = mapped_column(Text)
    modified: Mapped[str | None] = mapped_column(Text)
    modified_gmt: Mapped[str | None] = mapped_column(Text)
    excerpt_html: Mapped[str | None] = mapped_column(Text)
    content_html: Mapped[str | None] = mapped_column(Text)
    price: Mapped[str | None] = mapped_column(Text)
    price_sold: Mapped[str | None] = mapped_column(Text)
    price_term: Mapped[str | None] = mapped_column(Text)
    property_status: Mapped[str | None] = mapped_column(Text)
    property_market: Mapped[str | None] = mapped_column(Text)
    property_type_label: Mapped[str | None] = mapped_column(Text)
    property_county_label: Mapped[str | None] = mapped_column(Text)
    property_area_label: Mapped[str | None] = mapped_column(Text)
    property_size: Mapped[str | None] = mapped_column(Text)
    property_land_size: Mapped[str | None] = mapped_column(Text)
    property_accommodation: Mapped[str | None] = mapped_column(Text)
    property_disclaimer: Mapped[str | None] = mapped_column(Text)
    bedrooms: Mapped[int | None] = mapped_column(Integer)
    bathrooms: Mapped[int | None] = mapped_column(Integer)
    ber_rating: Mapped[str | None] = mapped_column(Text)
    ber_number: Mapped[str | None] = mapped_column(Text)
    energy_details: Mapped[str | None] = mapped_column(Text)
    bidding_method: Mapped[str | None] = mapped_column(Text)
    living_type: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    eircode: Mapped[str | None] = mapped_column(Text)
    directions: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    agent_name: Mapped[str | None] = mapped_column(Text)
    agent_photo_url: Mapped[str | None] = mapped_column(Text)
    agent_email: Mapped[str | None] = mapped_column(Text)
    agent_mobile: Mapped[str | None] = mapped_column(Text)
    agent_number: Mapped[str | None] = mapped_column(Text)
    agent_qualification: Mapped[str | None] = mapped_column(Text)
    agency_psra: Mapped[str | None] = mapped_column(Text)
    agency_logo_url: Mapped[str | None] = mapped_column(Text)
    featured_media_id: Mapped[int | None] = mapped_column(Integer)
    featured_image_url: Mapped[str | None] = mapped_column(Text)
    amenities: Mapped[str | None] = mapped_column(Text)
    property_order: Mapped[int | None] = mapped_column(Integer)
    wppd_parent_id: Mapped[str | None] = mapped_column(Text)
    property_type_ids: Mapped[str | None] = mapped_column(Text)
    property_county_ids: Mapped[str | None] = mapped_column(Text)
    property_area_ids: Mapped[str | None] = mapped_column(Text)
    property_features: Mapped[str | None] = mapped_column(Text)
    media_attachments_json: Mapped[str | None] = mapped_column(Text)
    brochure_urls: Mapped[str | None] = mapped_column(Text)
    floorplan_urls: Mapped[str | None] = mapped_column(Text)
    tour_urls: Mapped[str | None] = mapped_column(Text)
    viewing_times: Mapped[str | None] = mapped_column(Text)
    image_folder: Mapped[str] = mapped_column(Text, nullable=False, default="")
    image_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    social_publish_status: Mapped[str] = mapped_column(Text, nullable=False, default="")
    social_publish_details_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    fetched_at: Mapped[str] = mapped_column(Text, nullable=False, default="")


class PropertyImageModel(Base):
    __tablename__ = "property_images"
    __table_args__ = (
        PrimaryKeyConstraint("record_id", "position", name="pk_property_images"),
    )

    record_id: Mapped[int] = mapped_column(Integer, ForeignKey("properties.record_id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    local_path: Mapped[str | None] = mapped_column(Text)


class PropertyPipelineStateModel(Base):
    __tablename__ = "property_pipeline_state"
    __table_args__ = (
        PrimaryKeyConstraint("site_id", "source_property_id", name="pk_property_pipeline_state"),
        Index("idx_pipeline_state_site_publish_status", "site_id", "publish_status", "updated_at"),
    )

    agency_id: Mapped[str] = mapped_column(String(36), ForeignKey("agencies.id"), nullable=False)
    wordpress_source_id: Mapped[str] = mapped_column(String(36), ForeignKey("wordpress_sources.id"), nullable=False)
    site_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_property_id: Mapped[int] = mapped_column(Integer, nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    publish_target_fingerprint: Mapped[str] = mapped_column(Text, nullable=False, default="")
    publish_target_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    selected_image_folder: Mapped[str] = mapped_column(Text, nullable=False, default="")
    artifact_kind: Mapped[str] = mapped_column(Text, nullable=False, default="")
    local_artifact_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    local_metadata_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    render_profile: Mapped[str] = mapped_column(Text, nullable=False, default="")
    local_manifest_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    local_video_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    render_status: Mapped[str] = mapped_column(Text, nullable=False, default="")
    publish_status: Mapped[str] = mapped_column(Text, nullable=False, default="")
    workflow_state: Mapped[str] = mapped_column(Text, nullable=False, default="")
    publish_details_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    current_revision_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_published_location_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[str] = mapped_column(Text, nullable=False, default="")


class WebhookEventModel(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        Index("idx_webhook_events_site_received_at", "site_id", "received_at"),
        Index("idx_webhook_events_status_updated_at", "status", "updated_at"),
    )

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    agency_id: Mapped[str] = mapped_column(String(36), ForeignKey("agencies.id"), nullable=False)
    wordpress_source_id: Mapped[str] = mapped_column(String(36), ForeignKey("wordpress_sources.id"), nullable=False)
    site_id: Mapped[str] = mapped_column(Text, nullable=False)
    property_id: Mapped[int | None] = mapped_column(Integer)
    received_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)


class JobQueueModel(Base):
    __tablename__ = "job_queue"
    __table_args__ = (
        Index("idx_job_queue_status_available_at", "status", "available_at", "created_at"),
        Index("idx_job_queue_site_property_status", "site_id", "property_id", "status", "created_at"),
        Index("idx_job_queue_processing_lease", "status", "lease_expires_at"),
    )

    job_id: Mapped[str] = mapped_column(Text, primary_key=True)
    agency_id: Mapped[str] = mapped_column(String(36), ForeignKey("agencies.id"), nullable=False)
    wordpress_source_id: Mapped[str] = mapped_column(String(36), ForeignKey("wordpress_sources.id"), nullable=False)
    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    site_id: Mapped[str] = mapped_column(Text, nullable=False)
    property_id: Mapped[int | None] = mapped_column(Integer)
    received_at: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw_payload_hash: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    publish_context_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    gohighlevel_access_token_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, default=b"")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    available_at: Mapped[str] = mapped_column(Text, nullable=False)
    lease_expires_at: Mapped[str] = mapped_column(Text, nullable=False, default="")
    worker_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    finished_at: Mapped[str] = mapped_column(Text, nullable=False, default="")
    superseded_by_job_id: Mapped[str] = mapped_column(Text, nullable=False, default="")


class MediaRevisionModel(Base):
    __tablename__ = "media_revisions"
    __table_args__ = (
        Index("idx_media_revisions_site_property_created_at", "site_id", "source_property_id", "created_at"),
    )

    revision_id: Mapped[str] = mapped_column(Text, primary_key=True)
    agency_id: Mapped[str] = mapped_column(String(36), ForeignKey("agencies.id"), nullable=False)
    wordpress_source_id: Mapped[str] = mapped_column(String(36), ForeignKey("wordpress_sources.id"), nullable=False)
    site_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_property_id: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_kind: Mapped[str] = mapped_column(Text, nullable=False, default="")
    render_profile: Mapped[str] = mapped_column(Text, nullable=False, default="")
    media_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    mime_type: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_fingerprint: Mapped[str] = mapped_column(Text, nullable=False, default="")
    publish_target_fingerprint: Mapped[str] = mapped_column(Text, nullable=False, default="")
    workflow_state: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class OutboxEventModel(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("idx_outbox_events_status_available_at", "status", "available_at", "created_at"),
        Index("idx_outbox_events_site_property_created_at", "site_id", "source_property_id", "created_at"),
    )

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[str] = mapped_column(Text, nullable=False)
    agency_id: Mapped[str] = mapped_column(String(36), ForeignKey("agencies.id"), nullable=False)
    wordpress_source_id: Mapped[str] = mapped_column(String(36), ForeignKey("wordpress_sources.id"), nullable=False)
    site_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_property_id: Mapped[int | None] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    available_at: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ScriptedVideoArtifactModel(Base):
    __tablename__ = "scripted_video_artifacts"
    __table_args__ = (
        Index("idx_scripted_video_artifacts_site_property_created_at", "site_id", "source_property_id", "created_at"),
    )

    render_id: Mapped[str] = mapped_column(Text, primary_key=True)
    agency_id: Mapped[str] = mapped_column(String(36), ForeignKey("agencies.id"), nullable=False)
    wordpress_source_id: Mapped[str] = mapped_column(String(36), ForeignKey("wordpress_sources.id"), nullable=False)
    site_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_property_id: Mapped[int] = mapped_column(Integer, nullable=False)
    property_slug: Mapped[str] = mapped_column(Text, nullable=False, default="")
    render_profile: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="")
    request_manifest_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    request_manifest_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resolved_manifest_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    media_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class GoHighLevelConnectionModel(Base):
    __tablename__ = "ghl_connections"
    __table_args__ = (
        UniqueConstraint("agency_id", name="uq_ghl_connections_agency_id"),
        Index("idx_ghl_connections_location_id", "location_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    location_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    user_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    access_token: Mapped[str] = mapped_column(Text, nullable=False, default="")
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expires_at: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class ReelProfileModel(Base):
    __tablename__ = "reel_profiles"
    __table_args__ = (
        UniqueConstraint("agency_id", name="uq_reel_profiles_agency_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, default="Default")
    platforms_json: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default='["tiktok","instagram","linkedin","youtube","facebook","gbp"]',
    )
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    music_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    intro_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    logo_position: Mapped[str] = mapped_column(Text, nullable=False, default="top-right")
    brand_primary_color: Mapped[str] = mapped_column(Text, nullable=False, default="#0F172A")
    brand_secondary_color: Mapped[str] = mapped_column(Text, nullable=False, default="#FFFFFF")
    caption_template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    extra_settings_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


__all__ = [
    "AgencyModel",
    "GoHighLevelConnectionModel",
    "JobQueueModel",
    "MediaRevisionModel",
    "OutboxEventModel",
    "PropertyImageModel",
    "PropertyModel",
    "PropertyPipelineStateModel",
    "ReelProfileModel",
    "ScriptedVideoArtifactModel",
    "WebhookEventModel",
    "WordPressSourceModel",
]
