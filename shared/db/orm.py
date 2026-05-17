"""SQLAlchemy ORM mappings — one class per table, mirroring the schema in
`alembic/versions/20260501_0001_initial_schema.py`.

The mappings live here (cross-cutting `shared/db/`) rather than per-module
because Alembic needs a single `target_metadata` to introspect every table
in one pass. Modules read from these mappings indirectly through their own
`infrastructure/<aggregate>_repository.py`.

Naming follows the schema renames captured in the refactor plan:
`external_source_id` (was `site_id`), `ingestion_source_id` (was
`wordpress_source_id`), `provider_secrets_encrypted` (was
`gohighlevel_access_token_encrypted`), `last_published_provider_external_id`
(was `last_published_location_id`).
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from modules.catalog.infrastructure.orm import PropertyImageORM, PropertyORM
from modules.configuration.infrastructure.orm import (
    AgencyAutomationRulesORM,
    AgencyBrandSettingsORM,
    AgencyMusicTrackORM,
    AgencyReelDefaultsORM,
    AgencySocialTemplateORM,
    RenderTemplateORM,
)
from shared.db.base import Base


# ── Tenancy ─────────────────────────────────────────────────────────────


class AgencyORM(Base):
    __tablename__ = "agencies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    timezone: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


# ── Ingestion ───────────────────────────────────────────────────────────


class IngestionSourceORM(Base):
    __tablename__ = "ingestion_sources"
    __table_args__ = (
        UniqueConstraint("kind", "external_id", name="uq_ingestion_sources_kind_external_id"),
        UniqueConstraint(
            "agency_id",
            "kind",
            "external_id",
            name="uq_ingestion_sources_agency_kind_external",
        ),
        Index("idx_ingestion_sources_agency_kind", "agency_id", "kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    config_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    secrets_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    last_event_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


# ── Publishing ──────────────────────────────────────────────────────────


class ProviderConnectionORM(Base):
    __tablename__ = "provider_connections"
    __table_args__ = (
        UniqueConstraint(
            "agency_id", "provider", name="uq_provider_connections_agency_provider"
        ),
        Index(
            "idx_provider_connections_provider_external",
            "provider",
            "external_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agencies.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    config_json: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    secrets_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


# ── Configuration ──────────────────────────────────────────────────────


# ── Catalog ─────────────────────────────────────────────────────────────


# ── Reels ───────────────────────────────────────────────────────────────


class ReelORM(Base):
    __tablename__ = "reels"
    __table_args__ = (
        PrimaryKeyConstraint("external_source_id", "source_property_id", name="pk_reels"),
        Index(
            "idx_reels_agency_publish_status",
            "agency_id",
            "publish_status",
            text("updated_at DESC"),
        ),
        Index(
            "idx_reels_agency_workflow_state",
            "agency_id",
            "workflow_state",
            text("updated_at DESC"),
        ),
    )

    agency_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agencies.id"), nullable=False
    )
    ingestion_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_sources.id"), nullable=False
    )
    external_source_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_property_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_fingerprint: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    content_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    publish_target_fingerprint: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )
    publish_target_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    descriptions_override: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, server_default=None
    )
    # Feature 25: per-reel background music override. ``NULL`` means
    # "fall back to the agency pool resolver" (features 23 / 24);
    # otherwise the value must reference an ``agency_music_tracks.id``
    # row belonging to the same agency. ``ON DELETE SET NULL`` keeps the
    # reel renderable if the agency later deletes the picked track.
    music_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("agency_music_tracks.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Feature 36: per-reel subtitle override. ``NULL`` means "no
    # override — fall back to the historical autoCaptions flow (if the
    # agency keeps ``automation.autoCaptions`` enabled) or render no
    # subtitles at all". Otherwise an ordered JSON array of
    # ``{"index": int, "text": str, "in_seconds": float,
    # "out_seconds": float}`` entries whose ``index`` keys are unique
    # and monotonically increasing, and whose timing windows are
    # non-overlapping with ``out_seconds > in_seconds`` and
    # ``in_seconds >= 0``.
    subtitles_override: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, server_default=None
    )
    # Feature 35 (retro-fix, closed by feature 37): per-reel photo
    # override. ``NULL`` means "no override — render in the default
    # property_images order". Otherwise an ordered JSON array of
    # ``{"position": int, "selected": bool}`` entries whose ``position``
    # keys cover the range ``[0, N)`` exactly once each. The column was
    # added by migration ``20260515_0003_reels_photos_override`` but the
    # ORM declaration was missed in feature 35; declared here so
    # ``alembic revision --autogenerate`` does not propose a spurious
    # ``drop_column``.
    photos_override: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, server_default=None
    )
    # Feature 37: per-reel slide manifest override. ``NULL`` means "no
    # override — fall back to the auto-generated manifest pipeline".
    # Otherwise an ordered JSON array of
    # ``{"slide_id": str, "position": int, "duration_seconds": float,
    # "kind": str, ...kind-specific fields}`` entries whose ``position``
    # keys cover the range ``[0, N)`` exactly once, whose ``slide_id``
    # values are unique non-empty strings, whose ``duration_seconds``
    # are positive floats summing to at most ``1.5 *
    # target_duration_seconds``, and whose ``kind`` discriminator is one
    # of ``{"photo", "voiceover", "text", "intro_card", "outro_card"}``.
    manifest_override: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, server_default=None
    )
    render_template_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("render_templates.template_id"),
        nullable=False,
        server_default="classic",
    )
    selected_image_folder: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    artifact_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    local_artifact_path: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    local_metadata_path: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    render_profile: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    local_manifest_path: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    local_video_path: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    render_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    publish_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    workflow_state: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    publish_details: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    current_revision_id: Mapped[str | None] = mapped_column(String(36))
    last_published_provider_external_id: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class MediaRevisionORM(Base):
    __tablename__ = "media_revisions"
    __table_args__ = (
        Index(
            "idx_media_revisions_external_source_property",
            "external_source_id",
            "source_property_id",
            text("created_at DESC"),
        ),
    )

    revision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agencies.id"), nullable=False
    )
    ingestion_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_sources.id"), nullable=False
    )
    external_source_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_property_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    artifact_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    render_profile: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    render_template_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("render_templates.template_id"),
        nullable=False,
        server_default="classic",
    )
    media_path: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    metadata_path: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    mime_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    content_fingerprint: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    publish_target_fingerprint: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=""
    )
    workflow_state: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


# ── Webhook events / jobs / outbox / scripted ──────────────────────────


class WebhookEventORM(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        Index(
            "idx_webhook_events_external_received_at",
            "external_source_id",
            text("received_at DESC"),
        ),
        Index("idx_webhook_events_status_updated_at", "status", "updated_at"),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agencies.id"), nullable=False
    )
    ingestion_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_sources.id"), nullable=False
    )
    external_source_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_kind: Mapped[str] = mapped_column(Text, nullable=False)
    property_id: Mapped[int | None] = mapped_column(BigInteger)
    received_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    raw_payload_hash: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)


class JobORM(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("idx_jobs_status_available_at", "status", "available_at", "created_at"),
        Index(
            "idx_jobs_external_source_property_status",
            "external_source_id",
            "property_id",
            "status",
            "created_at",
        ),
        Index("idx_jobs_status_lease", "status", "lease_expires_at"),
    )

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agencies.id"), nullable=False
    )
    ingestion_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_sources.id"), nullable=False
    )
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="reel_publish")
    external_source_id: Mapped[str] = mapped_column(Text, nullable=False)
    property_id: Mapped[int | None] = mapped_column(BigInteger)
    received_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_payload_hash: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(Text, nullable=False)
    payload_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    publish_context_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    provider_secrets_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    available_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    lease_expires_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    superseded_by_job_id: Mapped[str | None] = mapped_column(String(36))


class OutboxEventORM(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "idx_outbox_events_status_available_at",
            "status",
            "available_at",
            "created_at",
        ),
        Index(
            "idx_outbox_events_external_source_property",
            "external_source_id",
            "source_property_id",
            text("created_at DESC"),
        ),
    )

    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(Text, nullable=False)
    aggregate_id: Mapped[str] = mapped_column(Text, nullable=False)
    agency_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agencies.id"), nullable=False
    )
    ingestion_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_sources.id"), nullable=False
    )
    external_source_id: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    source_property_id: Mapped[int | None] = mapped_column(BigInteger)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    published_at: Mapped[object | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str] = mapped_column(Text, nullable=False, server_default="")


class ScriptedVideoArtifactORM(Base):
    __tablename__ = "scripted_video_artifacts"
    __table_args__ = (
        Index(
            "idx_scripted_video_external_source_property",
            "external_source_id",
            "source_property_id",
            text("created_at DESC"),
        ),
    )

    render_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agency_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agencies.id"), nullable=False
    )
    ingestion_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ingestion_sources.id"), nullable=False
    )
    external_source_id: Mapped[str] = mapped_column(Text, nullable=False)
    source_property_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    property_slug: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    render_profile: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    request_manifest: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    request_manifest_path: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    resolved_manifest_path: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    media_path: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = [
    "AgencyAutomationRulesORM",
    "AgencyBrandSettingsORM",
    "AgencyMusicTrackORM",
    "AgencyORM",
    "AgencyReelDefaultsORM",
    "AgencySocialTemplateORM",
    "IngestionSourceORM",
    "JobORM",
    "MediaRevisionORM",
    "OutboxEventORM",
    "PropertyImageORM",
    "PropertyORM",
    "ProviderConnectionORM",
    "RenderTemplateORM",
    "ReelORM",
    "ScriptedVideoArtifactORM",
    "WebhookEventORM",
]
