from __future__ import annotations

from sqlalchemy import (
    JSON,
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


class UserModel(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("auth_provider", "provider_user_id", name="uq_users_provider_identity"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    auth_provider: Mapped[str] = mapped_column(Text, nullable=False, default="gohighlevel")
    provider_user_id: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text)
    last_login_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class AgencyMembershipModel(Base):
    __tablename__ = "agency_memberships"
    __table_args__ = (
        UniqueConstraint("agency_id", "user_id", name="uq_agency_memberships_agency_user"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(String(36), ForeignKey("agencies.id"), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class GoHighLevelConnectionModel(Base):
    __tablename__ = "ghl_connections"
    __table_args__ = (
        UniqueConstraint("agency_id", "location_id", name="uq_ghl_connections_agency_location"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(String(36), ForeignKey("agencies.id"), nullable=False)
    location_id: Mapped[str] = mapped_column(Text, nullable=False)
    company_id: Mapped[str | None] = mapped_column(Text)
    access_token_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, default=b"")
    refresh_token_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, default=b"")
    token_expires_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    scopes_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="connected")
    connected_by_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
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


class ReelProfileModel(Base):
    __tablename__ = "reel_profiles"
    __table_args__ = (
        UniqueConstraint("agency_id", "name", "version", name="uq_reel_profiles_name_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(String(36), ForeignKey("agencies.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    render_profile_key: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_template: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    branding_settings: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    render_settings: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_by_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkflowPolicyModel(Base):
    __tablename__ = "workflow_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(String(36), ForeignKey("agencies.id"), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    delay_hours: Mapped[int | None] = mapped_column(Integer)
    send_review_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_email_to: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class AssetLibraryItemModel(Base):
    __tablename__ = "asset_library_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(String(36), ForeignKey("agencies.id"), nullable=False)
    asset_type: Mapped[str] = mapped_column(Text, nullable=False)
    usage_type: Mapped[str] = mapped_column(Text, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    checksum: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    uploaded_by_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    deleted_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))


class ReelProfileAssetModel(Base):
    __tablename__ = "reel_profile_assets"
    __table_args__ = (
        UniqueConstraint("profile_id", "slot", "sort_order", name="uq_reel_profile_assets_slot_order"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(36), ForeignKey("reel_profiles.id"), nullable=False)
    asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("asset_library_items.id"), nullable=False)
    slot: Mapped[str] = mapped_column(Text, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    config_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)


class PropertyModel(Base):
    __tablename__ = "properties"
    __table_args__ = (
        UniqueConstraint("site_id", "source_property_id", name="uq_properties_site_property"),
        Index("idx_properties_site_slug", "site_id", "slug"),
        Index("idx_properties_site_fetched_at", "site_id", "fetched_at"),
    )

    record_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agency_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agencies.id"))
    wordpress_source_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("wordpress_sources.id"))
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

    agency_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agencies.id"))
    wordpress_source_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("wordpress_sources.id"))
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
    agency_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agencies.id"))
    wordpress_source_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("wordpress_sources.id"))
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
    agency_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agencies.id"))
    wordpress_source_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("wordpress_sources.id"))
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
    agency_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agencies.id"))
    wordpress_source_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("wordpress_sources.id"))
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
    agency_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agencies.id"))
    wordpress_source_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("wordpress_sources.id"))
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
    agency_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("agencies.id"))
    wordpress_source_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("wordpress_sources.id"))
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


class PropertySnapshotModel(Base):
    __tablename__ = "property_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    site_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_property_id: Mapped[int] = mapped_column(Integer, nullable=False)
    source_event_id: Mapped[str | None] = mapped_column(Text)
    content_fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    normalized_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class ReelRenderModel(Base):
    __tablename__ = "reel_renders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(String(36), ForeignKey("agencies.id"), nullable=False)
    site_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_property_id: Mapped[int] = mapped_column(Integer, nullable=False)
    render_job_id: Mapped[str | None] = mapped_column(String(36))
    snapshot_id: Mapped[str | None] = mapped_column(String(36))
    profile_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("reel_profiles.id"))
    manifest_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    manifest_storage_key: Mapped[str | None] = mapped_column(Text)
    video_asset_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("asset_library_items.id"))
    poster_asset_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("asset_library_items.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class ReviewRequestModel(Base):
    __tablename__ = "review_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(String(36), ForeignKey("agencies.id"), nullable=False)
    reel_render_id: Mapped[str] = mapped_column(String(36), ForeignKey("reel_renders.id"), nullable=False)
    requested_by_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    assigned_to_user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    decision_note: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class PublicationJobModel(Base):
    __tablename__ = "publication_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(String(36), ForeignKey("agencies.id"), nullable=False)
    reel_render_id: Mapped[str] = mapped_column(String(36), ForeignKey("reel_renders.id"), nullable=False)
    ghl_connection_id: Mapped[str] = mapped_column(String(36), ForeignKey("ghl_connections.id"), nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_for: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    provider_post_id: Mapped[str | None] = mapped_column(Text)
    provider_response: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class NotificationRuleModel(Base):
    __tablename__ = "notification_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(String(36), ForeignKey("agencies.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    destination: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class NotificationDeliveryModel(Base):
    __tablename__ = "notification_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(String(36), ForeignKey("agencies.id"), nullable=False)
    rule_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("notification_rules.id"))
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    payload_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    scheduled_for: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = [
    "AgencyMembershipModel",
    "AgencyModel",
    "AssetLibraryItemModel",
    "GoHighLevelConnectionModel",
    "JobQueueModel",
    "MediaRevisionModel",
    "NotificationDeliveryModel",
    "NotificationRuleModel",
    "OutboxEventModel",
    "PropertyImageModel",
    "PropertyModel",
    "PropertyPipelineStateModel",
    "PropertySnapshotModel",
    "PublicationJobModel",
    "ReelProfileAssetModel",
    "ReelProfileModel",
    "ReelRenderModel",
    "ReviewRequestModel",
    "ScriptedVideoArtifactModel",
    "UserModel",
    "WebhookEventModel",
    "WordPressSourceModel",
    "WorkflowPolicyModel",
]
