"""Initial schema for the modular monolith refactor.

The previous three migrations are replaced by this single clean upgrade:

* `wordpress_sources` becomes `ingestion_sources(kind, config_json)` so future
  ingestion sources slot in without a schema change.
* `gohighlevel_tokens` / `ghl_connections` become `provider_connections(
  provider, config_json)` so future publishers slot in without a schema
  change.
* `reel_profiles.extra_settings_json` is dissolved into per-section typed
  tables (`agency_brand_settings`, `agency_reel_defaults`,
  `agency_automation_rules`, `agency_social_templates`) plus a small
  catch-all `agency_reel_defaults.settings JSONB` for the genuinely
  free-form Defaults form fields.
* `property_pipeline_state` becomes `reels`.
* `job_queue` becomes `jobs(kind)` so future job kinds slot in without a
  schema change.
* `site_id` is renamed `external_source_id` throughout. `wordpress_source_id`
  becomes `ingestion_source_id`. `last_published_location_id` becomes
  `last_published_provider_external_id`. JSON-in-TEXT columns become JSONB.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg


revision = "20260501_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Tenancy ─────────────────────────────────────────────────────────
    op.create_table(
        "agencies",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── Ingestion ───────────────────────────────────────────────────────
    op.create_table(
        "ingestion_sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "agency_id",
            sa.String(length=36),
            sa.ForeignKey("agencies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "config_json",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("secrets_encrypted", sa.LargeBinary()),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("last_event_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kind", "external_id", name="uq_ingestion_sources_kind_external_id"),
        sa.UniqueConstraint(
            "agency_id",
            "kind",
            "external_id",
            name="uq_ingestion_sources_agency_kind_external",
        ),
    )
    op.create_index(
        "idx_ingestion_sources_agency_kind",
        "ingestion_sources",
        ["agency_id", "kind"],
    )

    # ── Publishing ──────────────────────────────────────────────────────
    op.create_table(
        "provider_connections",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "agency_id",
            sa.String(length=36),
            sa.ForeignKey("agencies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "config_json",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("secrets_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("agency_id", "provider", name="uq_provider_connections_agency_provider"),
    )
    op.create_index(
        "idx_provider_connections_provider_external",
        "provider_connections",
        ["provider", "external_id"],
    )

    # ── Configuration: brand / defaults / automation / social / music ──
    op.create_table(
        "agency_brand_settings",
        sa.Column(
            "agency_id",
            sa.String(length=36),
            sa.ForeignKey("agencies.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("primary_color", sa.Text(), nullable=False, server_default="#0F172A"),
        sa.Column("secondary_color", sa.Text(), nullable=False, server_default="#FFFFFF"),
        sa.Column("logo_position", sa.Text(), nullable=False, server_default="top-right"),
        sa.Column("logo_object_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("intro_logo_object_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("font_family", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "agency_reel_defaults",
        sa.Column(
            "agency_id",
            sa.String(length=36),
            sa.ForeignKey("agencies.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "platforms",
            pg.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text(
                "ARRAY['tiktok','instagram','linkedin','youtube','facebook','gbp']::text[]"
            ),
        ),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("music_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("intro_enabled", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("caption_template", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "settings",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "agency_automation_rules",
        sa.Column(
            "agency_id",
            sa.String(length=36),
            sa.ForeignKey("agencies.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "approval_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
        sa.Column("publish_window_start", sa.Text(), nullable=False, server_default=""),
        sa.Column("publish_window_end", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "publish_days",
            pg.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column(
            "trigger_on_status",
            pg.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY['published']::text[]"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "agency_social_templates",
        sa.Column(
            "agency_id",
            sa.String(length=36),
            sa.ForeignKey("agencies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("description_template", sa.Text(), nullable=False),
        sa.Column("title_template", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "hashtags",
            pg.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("ARRAY[]::text[]"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("agency_id", "platform", name="pk_agency_social_templates"),
    )

    op.create_table(
        "agency_music_tracks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "agency_id",
            sa.String(length=36),
            sa.ForeignKey("agencies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_agency_music_tracks_agency",
        "agency_music_tracks",
        ["agency_id"],
    )

    # ── Catalog: properties + images ───────────────────────────────────
    op.create_table(
        "properties",
        sa.Column("record_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "agency_id",
            sa.String(length=36),
            sa.ForeignKey("agencies.id"),
            nullable=False,
        ),
        sa.Column(
            "ingestion_source_id",
            sa.String(length=36),
            sa.ForeignKey("ingestion_sources.id"),
            nullable=False,
        ),
        sa.Column("external_source_id", sa.Text(), nullable=False),
        sa.Column("source_property_id", sa.BigInteger(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("link", sa.Text()),
        sa.Column("guid", sa.Text()),
        sa.Column("status", sa.Text()),
        sa.Column("resource_type", sa.Text()),
        sa.Column("author_id", sa.Integer()),
        sa.Column("importer_id", sa.Text()),
        sa.Column("list_reference", sa.Text()),
        sa.Column("date", sa.Text()),
        sa.Column("date_gmt", sa.Text()),
        sa.Column("modified", sa.Text()),
        sa.Column("modified_gmt", sa.Text()),
        sa.Column("excerpt_html", sa.Text()),
        sa.Column("content_html", sa.Text()),
        sa.Column("price", sa.Text()),
        sa.Column("price_sold", sa.Text()),
        sa.Column("price_term", sa.Text()),
        sa.Column("property_status", sa.Text()),
        sa.Column("property_market", sa.Text()),
        sa.Column("property_type_label", sa.Text()),
        sa.Column("property_county_label", sa.Text()),
        sa.Column("property_area_label", sa.Text()),
        sa.Column("property_size", sa.Text()),
        sa.Column("property_land_size", sa.Text()),
        sa.Column("property_accommodation", sa.Text()),
        sa.Column("property_disclaimer", sa.Text()),
        sa.Column("bedrooms", sa.Integer()),
        sa.Column("bathrooms", sa.Integer()),
        sa.Column("ber_rating", sa.Text()),
        sa.Column("ber_number", sa.Text()),
        sa.Column("energy_details", sa.Text()),
        sa.Column("bidding_method", sa.Text()),
        sa.Column("living_type", sa.Text()),
        sa.Column("country", sa.Text()),
        sa.Column("eircode", sa.Text()),
        sa.Column("directions", sa.Text()),
        sa.Column("latitude", sa.Float()),
        sa.Column("longitude", sa.Float()),
        sa.Column("agent_name", sa.Text()),
        sa.Column("agent_photo_url", sa.Text()),
        sa.Column("agent_email", sa.Text()),
        sa.Column("agent_mobile", sa.Text()),
        sa.Column("agent_number", sa.Text()),
        sa.Column("agent_qualification", sa.Text()),
        sa.Column("agency_psra", sa.Text()),
        sa.Column("agency_logo_url", sa.Text()),
        sa.Column("featured_media_id", sa.Integer()),
        sa.Column("featured_image_url", sa.Text()),
        sa.Column("amenities", sa.Text()),
        sa.Column("property_order", sa.Integer()),
        sa.Column("wppd_parent_id", sa.Text()),
        sa.Column("property_type_ids", sa.Text()),
        sa.Column("property_county_ids", sa.Text()),
        sa.Column("property_area_ids", sa.Text()),
        sa.Column("property_features", sa.Text()),
        sa.Column("media_attachments_json", sa.Text()),
        sa.Column("brochure_urls", sa.Text()),
        sa.Column("floorplan_urls", sa.Text()),
        sa.Column("tour_urls", sa.Text()),
        sa.Column("viewing_times", sa.Text()),
        sa.Column("image_folder", sa.Text(), nullable=False, server_default=""),
        sa.Column("image_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("social_publish_status", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "social_publish_details_json",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "raw_json",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "external_source_id",
            "source_property_id",
            name="uq_properties_external_source_property",
        ),
    )
    op.create_index(
        "idx_properties_external_source_slug",
        "properties",
        ["external_source_id", "slug"],
    )
    op.create_index(
        "idx_properties_agency_fetched_at",
        "properties",
        ["agency_id", sa.text("fetched_at DESC")],
    )

    op.create_table(
        "property_images",
        sa.Column(
            "record_id",
            sa.BigInteger(),
            sa.ForeignKey("properties.record_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("local_path", sa.Text()),
        sa.PrimaryKeyConstraint("record_id", "position", name="pk_property_images"),
    )

    # ── Reels (was property_pipeline_state) ─────────────────────────────
    op.create_table(
        "reels",
        sa.Column(
            "agency_id",
            sa.String(length=36),
            sa.ForeignKey("agencies.id"),
            nullable=False,
        ),
        sa.Column(
            "ingestion_source_id",
            sa.String(length=36),
            sa.ForeignKey("ingestion_sources.id"),
            nullable=False,
        ),
        sa.Column("external_source_id", sa.Text(), nullable=False),
        sa.Column("source_property_id", sa.BigInteger(), nullable=False),
        sa.Column("content_fingerprint", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "content_snapshot",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("publish_target_fingerprint", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "publish_target_snapshot",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("selected_image_folder", sa.Text(), nullable=False, server_default=""),
        sa.Column("artifact_kind", sa.Text(), nullable=False, server_default=""),
        sa.Column("local_artifact_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("local_metadata_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("render_profile", sa.Text(), nullable=False, server_default=""),
        sa.Column("local_manifest_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("local_video_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("render_status", sa.Text(), nullable=False, server_default=""),
        sa.Column("publish_status", sa.Text(), nullable=False, server_default=""),
        sa.Column("workflow_state", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "publish_details",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("current_revision_id", sa.String(length=36)),
        sa.Column(
            "last_published_provider_external_id",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("external_source_id", "source_property_id", name="pk_reels"),
    )
    op.create_index(
        "idx_reels_agency_publish_status",
        "reels",
        ["agency_id", "publish_status", sa.text("updated_at DESC")],
    )
    op.create_index(
        "idx_reels_agency_workflow_state",
        "reels",
        ["agency_id", "workflow_state", sa.text("updated_at DESC")],
    )

    op.create_table(
        "media_revisions",
        sa.Column("revision_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "agency_id",
            sa.String(length=36),
            sa.ForeignKey("agencies.id"),
            nullable=False,
        ),
        sa.Column(
            "ingestion_source_id",
            sa.String(length=36),
            sa.ForeignKey("ingestion_sources.id"),
            nullable=False,
        ),
        sa.Column("external_source_id", sa.Text(), nullable=False),
        sa.Column("source_property_id", sa.BigInteger(), nullable=False),
        sa.Column("artifact_kind", sa.Text(), nullable=False, server_default=""),
        sa.Column("render_profile", sa.Text(), nullable=False, server_default=""),
        sa.Column("media_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("mime_type", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_fingerprint", sa.Text(), nullable=False, server_default=""),
        sa.Column("publish_target_fingerprint", sa.Text(), nullable=False, server_default=""),
        sa.Column("workflow_state", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_media_revisions_external_source_property",
        "media_revisions",
        ["external_source_id", "source_property_id", sa.text("created_at DESC")],
    )

    # ── Webhook events (any source kind) ────────────────────────────────
    op.create_table(
        "webhook_events",
        sa.Column("event_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "agency_id",
            sa.String(length=36),
            sa.ForeignKey("agencies.id"),
            nullable=False,
        ),
        sa.Column(
            "ingestion_source_id",
            sa.String(length=36),
            sa.ForeignKey("ingestion_sources.id"),
            nullable=False,
        ),
        sa.Column("external_source_id", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("property_id", sa.BigInteger()),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("raw_payload_hash", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index(
        "idx_webhook_events_external_received_at",
        "webhook_events",
        ["external_source_id", sa.text("received_at DESC")],
    )
    op.create_index(
        "idx_webhook_events_status_updated_at",
        "webhook_events",
        ["status", "updated_at"],
    )

    # ── Job queue (worker contract) ─────────────────────────────────────
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "agency_id",
            sa.String(length=36),
            sa.ForeignKey("agencies.id"),
            nullable=False,
        ),
        sa.Column(
            "ingestion_source_id",
            sa.String(length=36),
            sa.ForeignKey("ingestion_sources.id"),
            nullable=False,
        ),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False, server_default="reel_publish"),
        sa.Column("external_source_id", sa.Text(), nullable=False),
        sa.Column("property_id", sa.BigInteger()),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload_hash", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "payload_json",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "publish_context_json",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("provider_secrets_encrypted", sa.LargeBinary()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("worker_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_by_job_id", sa.String(length=36)),
    )
    op.create_index(
        "idx_jobs_status_available_at",
        "jobs",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "idx_jobs_external_source_property_status",
        "jobs",
        ["external_source_id", "property_id", "status", "created_at"],
    )
    op.create_index(
        "idx_jobs_status_lease",
        "jobs",
        ["status", "lease_expires_at"],
    )

    # ── Outbox events ───────────────────────────────────────────────────
    op.create_table(
        "outbox_events",
        sa.Column("event_id", sa.String(length=36), primary_key=True),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Text(), nullable=False),
        sa.Column(
            "agency_id",
            sa.String(length=36),
            sa.ForeignKey("agencies.id"),
            nullable=False,
        ),
        sa.Column(
            "ingestion_source_id",
            sa.String(length=36),
            sa.ForeignKey("ingestion_sources.id"),
            nullable=False,
        ),
        sa.Column("external_source_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_property_id", sa.BigInteger()),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text(), nullable=False, server_default=""),
    )
    op.create_index(
        "idx_outbox_events_status_available_at",
        "outbox_events",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "idx_outbox_events_external_source_property",
        "outbox_events",
        ["external_source_id", "source_property_id", sa.text("created_at DESC")],
    )

    # ── Scripted video artifacts ────────────────────────────────────────
    op.create_table(
        "scripted_video_artifacts",
        sa.Column("render_id", sa.String(length=36), primary_key=True),
        sa.Column(
            "agency_id",
            sa.String(length=36),
            sa.ForeignKey("agencies.id"),
            nullable=False,
        ),
        sa.Column(
            "ingestion_source_id",
            sa.String(length=36),
            sa.ForeignKey("ingestion_sources.id"),
            nullable=False,
        ),
        sa.Column("external_source_id", sa.Text(), nullable=False),
        sa.Column("source_property_id", sa.BigInteger(), nullable=False),
        sa.Column("property_slug", sa.Text(), nullable=False, server_default=""),
        sa.Column("render_profile", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "request_manifest",
            pg.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("request_manifest_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("resolved_manifest_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("media_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "idx_scripted_video_external_source_property",
        "scripted_video_artifacts",
        ["external_source_id", "source_property_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_table("scripted_video_artifacts")
    op.drop_table("outbox_events")
    op.drop_table("jobs")
    op.drop_table("webhook_events")
    op.drop_table("media_revisions")
    op.drop_table("reels")
    op.drop_table("property_images")
    op.drop_table("properties")
    op.drop_table("agency_music_tracks")
    op.drop_table("agency_social_templates")
    op.drop_table("agency_automation_rules")
    op.drop_table("agency_reel_defaults")
    op.drop_table("agency_brand_settings")
    op.drop_table("provider_connections")
    op.drop_table("ingestion_sources")
    op.drop_table("agencies")
