from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260416_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
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

    op.create_table(
        "wordpress_sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("agency_id", sa.String(length=36), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("site_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("site_url", sa.Text()),
        sa.Column("normalized_host", sa.Text(), nullable=False),
        sa.Column("webhook_secret_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("last_event_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("site_id", name="uq_wordpress_sources_site_id"),
        sa.UniqueConstraint("agency_id", "normalized_host", name="uq_wordpress_sources_host"),
    )

    op.create_table(
        "properties",
        sa.Column("record_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agency_id", sa.String(length=36), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("wordpress_source_id", sa.String(length=36), sa.ForeignKey("wordpress_sources.id"), nullable=False),
        sa.Column("site_id", sa.Text(), nullable=False),
        sa.Column("source_property_id", sa.Integer(), nullable=False),
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
        sa.Column("image_folder", sa.Text(), nullable=False),
        sa.Column("image_count", sa.Integer(), nullable=False),
        sa.Column("social_publish_status", sa.Text(), nullable=False),
        sa.Column("social_publish_details_json", sa.Text(), nullable=False),
        sa.Column("raw_json", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("site_id", "source_property_id", name="uq_properties_site_property"),
    )
    op.create_index("idx_properties_site_slug", "properties", ["site_id", "slug"])
    op.create_index("idx_properties_site_fetched_at", "properties", ["site_id", "fetched_at"])

    op.create_table(
        "property_images",
        sa.Column("record_id", sa.Integer(), sa.ForeignKey("properties.record_id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("local_path", sa.Text()),
        sa.PrimaryKeyConstraint("record_id", "position", name="pk_property_images"),
    )

    op.create_table(
        "property_pipeline_state",
        sa.Column("agency_id", sa.String(length=36), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("wordpress_source_id", sa.String(length=36), sa.ForeignKey("wordpress_sources.id"), nullable=False),
        sa.Column("site_id", sa.Text(), nullable=False),
        sa.Column("source_property_id", sa.Integer(), nullable=False),
        sa.Column("content_fingerprint", sa.Text(), nullable=False),
        sa.Column("content_snapshot_json", sa.Text(), nullable=False),
        sa.Column("publish_target_fingerprint", sa.Text(), nullable=False),
        sa.Column("publish_target_snapshot_json", sa.Text(), nullable=False),
        sa.Column("selected_image_folder", sa.Text(), nullable=False),
        sa.Column("artifact_kind", sa.Text(), nullable=False),
        sa.Column("local_artifact_path", sa.Text(), nullable=False),
        sa.Column("local_metadata_path", sa.Text(), nullable=False),
        sa.Column("render_profile", sa.Text(), nullable=False),
        sa.Column("local_manifest_path", sa.Text(), nullable=False),
        sa.Column("local_video_path", sa.Text(), nullable=False),
        sa.Column("render_status", sa.Text(), nullable=False),
        sa.Column("publish_status", sa.Text(), nullable=False),
        sa.Column("workflow_state", sa.Text(), nullable=False),
        sa.Column("publish_details_json", sa.Text(), nullable=False),
        sa.Column("current_revision_id", sa.Text(), nullable=False),
        sa.Column("last_published_location_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("site_id", "source_property_id", name="pk_property_pipeline_state"),
    )
    op.create_index("idx_pipeline_state_site_publish_status", "property_pipeline_state", ["site_id", "publish_status", "updated_at"])

    op.create_table(
        "webhook_events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("agency_id", sa.String(length=36), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("wordpress_source_id", sa.String(length=36), sa.ForeignKey("wordpress_sources.id"), nullable=False),
        sa.Column("site_id", sa.Text(), nullable=False),
        sa.Column("property_id", sa.Integer()),
        sa.Column("received_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("raw_payload_hash", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text()),
    )
    op.create_index("idx_webhook_events_site_received_at", "webhook_events", ["site_id", "received_at"])
    op.create_index("idx_webhook_events_status_updated_at", "webhook_events", ["status", "updated_at"])

    op.create_table(
        "job_queue",
        sa.Column("job_id", sa.Text(), primary_key=True),
        sa.Column("agency_id", sa.String(length=36), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("wordpress_source_id", sa.String(length=36), sa.ForeignKey("wordpress_sources.id"), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("site_id", sa.Text(), nullable=False),
        sa.Column("property_id", sa.Integer()),
        sa.Column("received_at", sa.Text(), nullable=False),
        sa.Column("raw_payload_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("publish_context_json", sa.Text(), nullable=False),
        sa.Column("gohighlevel_access_token_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.Text(), nullable=False),
        sa.Column("lease_expires_at", sa.Text(), nullable=False),
        sa.Column("worker_id", sa.Text(), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("finished_at", sa.Text(), nullable=False),
        sa.Column("superseded_by_job_id", sa.Text(), nullable=False),
    )
    op.create_index("idx_job_queue_status_available_at", "job_queue", ["status", "available_at", "created_at"])
    op.create_index("idx_job_queue_site_property_status", "job_queue", ["site_id", "property_id", "status", "created_at"])
    op.create_index("idx_job_queue_processing_lease", "job_queue", ["status", "lease_expires_at"])

    op.create_table(
        "media_revisions",
        sa.Column("revision_id", sa.Text(), primary_key=True),
        sa.Column("agency_id", sa.String(length=36), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("wordpress_source_id", sa.String(length=36), sa.ForeignKey("wordpress_sources.id"), nullable=False),
        sa.Column("site_id", sa.Text(), nullable=False),
        sa.Column("source_property_id", sa.Integer(), nullable=False),
        sa.Column("artifact_kind", sa.Text(), nullable=False),
        sa.Column("render_profile", sa.Text(), nullable=False),
        sa.Column("media_path", sa.Text(), nullable=False),
        sa.Column("metadata_path", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("content_fingerprint", sa.Text(), nullable=False),
        sa.Column("publish_target_fingerprint", sa.Text(), nullable=False),
        sa.Column("workflow_state", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_media_revisions_site_property_created_at", "media_revisions", ["site_id", "source_property_id", "created_at"])

    op.create_table(
        "outbox_events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("aggregate_type", sa.Text(), nullable=False),
        sa.Column("aggregate_id", sa.Text(), nullable=False),
        sa.Column("agency_id", sa.String(length=36), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("wordpress_source_id", sa.String(length=36), sa.ForeignKey("wordpress_sources.id"), nullable=False),
        sa.Column("site_id", sa.Text(), nullable=False),
        sa.Column("source_property_id", sa.Integer()),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("available_at", sa.Text(), nullable=False),
        sa.Column("published_at", sa.Text(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=False),
    )
    op.create_index("idx_outbox_events_status_available_at", "outbox_events", ["status", "available_at", "created_at"])
    op.create_index("idx_outbox_events_site_property_created_at", "outbox_events", ["site_id", "source_property_id", "created_at"])

    op.create_table(
        "scripted_video_artifacts",
        sa.Column("render_id", sa.Text(), primary_key=True),
        sa.Column("agency_id", sa.String(length=36), sa.ForeignKey("agencies.id"), nullable=False),
        sa.Column("wordpress_source_id", sa.String(length=36), sa.ForeignKey("wordpress_sources.id"), nullable=False),
        sa.Column("site_id", sa.Text(), nullable=False),
        sa.Column("source_property_id", sa.Integer(), nullable=False),
        sa.Column("property_slug", sa.Text(), nullable=False),
        sa.Column("render_profile", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("request_manifest_json", sa.Text(), nullable=False),
        sa.Column("request_manifest_path", sa.Text(), nullable=False),
        sa.Column("resolved_manifest_path", sa.Text(), nullable=False),
        sa.Column("media_path", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index("idx_scripted_video_artifacts_site_property_created_at", "scripted_video_artifacts", ["site_id", "source_property_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_scripted_video_artifacts_site_property_created_at", table_name="scripted_video_artifacts")
    op.drop_table("scripted_video_artifacts")
    op.drop_index("idx_outbox_events_site_property_created_at", table_name="outbox_events")
    op.drop_index("idx_outbox_events_status_available_at", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("idx_media_revisions_site_property_created_at", table_name="media_revisions")
    op.drop_table("media_revisions")
    op.drop_index("idx_job_queue_processing_lease", table_name="job_queue")
    op.drop_index("idx_job_queue_site_property_status", table_name="job_queue")
    op.drop_index("idx_job_queue_status_available_at", table_name="job_queue")
    op.drop_table("job_queue")
    op.drop_index("idx_webhook_events_status_updated_at", table_name="webhook_events")
    op.drop_index("idx_webhook_events_site_received_at", table_name="webhook_events")
    op.drop_table("webhook_events")
    op.drop_index("idx_pipeline_state_site_publish_status", table_name="property_pipeline_state")
    op.drop_table("property_pipeline_state")
    op.drop_table("property_images")
    op.drop_index("idx_properties_site_fetched_at", table_name="properties")
    op.drop_index("idx_properties_site_slug", table_name="properties")
    op.drop_table("properties")
    op.drop_table("wordpress_sources")
    op.drop_table("agencies")
