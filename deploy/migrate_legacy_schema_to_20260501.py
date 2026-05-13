"""One-off legacy database bridge to the clean 20260501 schema.

Use only for databases left at the removed Alembic revision ``20260429_0003``.
It preserves existing rows, renames the legacy Phase 1/2 tables and columns to
the Phase 3/4 names, creates newly introduced tables, then stamps Alembic head.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from settings import DATABASE_URL
from shared.db.base import Base
from shared.db.security import encrypt_text
import shared.db.orm  # noqa: F401  # register ORM metadata


HEAD_REVISION = "20260501_0001"


def main() -> int:
    engine = create_engine(DATABASE_URL, future=True)
    with engine.begin() as connection:
        migrate_legacy_tables(connection)
        Base.metadata.create_all(bind=connection)
        migrate_provider_connections(connection)
        migrate_reel_profiles(connection)
        stamp_head(connection)
    print(f"Database schema migrated/stamped to {HEAD_REVISION}.")
    return 0


def migrate_legacy_tables(connection) -> None:
    rename_table(connection, "wordpress_sources", "ingestion_sources")
    rename_column(connection, "ingestion_sources", "site_id", "external_id")
    rename_column(
        connection,
        "ingestion_sources",
        "webhook_secret_encrypted",
        "secrets_encrypted",
    )
    execute(
        connection,
        """
        ALTER TABLE ingestion_sources
            ADD COLUMN IF NOT EXISTS kind text,
            ADD COLUMN IF NOT EXISTS config_json jsonb
        """,
        table="ingestion_sources",
    )
    execute(
        connection,
        """
        UPDATE ingestion_sources
        SET
            kind = COALESCE(NULLIF(kind, ''), 'wordpress'),
            config_json = COALESCE(
                config_json,
                jsonb_build_object(
                    'site_url', COALESCE(site_url, ''),
                    'normalized_host', COALESCE(normalized_host, '')
                )
            )
        """,
        table="ingestion_sources",
    )
    execute(
        connection,
        """
        ALTER TABLE ingestion_sources
            ALTER COLUMN kind SET NOT NULL,
            ALTER COLUMN config_json SET DEFAULT '{}'::jsonb,
            ALTER COLUMN config_json SET NOT NULL
        """,
        table="ingestion_sources",
    )

    rename_column(connection, "properties", "wordpress_source_id", "ingestion_source_id")
    rename_column(connection, "properties", "site_id", "external_source_id")
    alter_jsonb(connection, "properties", "social_publish_details_json")
    alter_jsonb(connection, "properties", "raw_json")
    alter_timestamptz(connection, "properties", "fetched_at", nullable=False)

    rename_table(connection, "property_pipeline_state", "reels")
    rename_column(connection, "reels", "wordpress_source_id", "ingestion_source_id")
    rename_column(connection, "reels", "site_id", "external_source_id")
    rename_column(connection, "reels", "content_snapshot_json", "content_snapshot")
    rename_column(
        connection,
        "reels",
        "publish_target_snapshot_json",
        "publish_target_snapshot",
    )
    rename_column(connection, "reels", "publish_details_json", "publish_details")
    rename_column(
        connection,
        "reels",
        "last_published_location_id",
        "last_published_provider_external_id",
    )
    alter_jsonb(connection, "reels", "content_snapshot")
    alter_jsonb(connection, "reels", "publish_target_snapshot")
    alter_jsonb(connection, "reels", "publish_details")
    alter_timestamptz(connection, "reels", "created_at", nullable=False)
    alter_timestamptz(connection, "reels", "updated_at", nullable=False)

    rename_column(connection, "media_revisions", "wordpress_source_id", "ingestion_source_id")
    rename_column(connection, "media_revisions", "site_id", "external_source_id")
    alter_timestamptz(connection, "media_revisions", "created_at", nullable=False)

    rename_column(connection, "webhook_events", "wordpress_source_id", "ingestion_source_id")
    rename_column(connection, "webhook_events", "site_id", "external_source_id")
    execute(
        connection,
        "ALTER TABLE webhook_events ADD COLUMN IF NOT EXISTS source_kind text",
        table="webhook_events",
    )
    execute(
        connection,
        "UPDATE webhook_events SET source_kind = COALESCE(NULLIF(source_kind, ''), 'wordpress')",
        table="webhook_events",
    )
    execute(
        connection,
        "ALTER TABLE webhook_events ALTER COLUMN source_kind SET NOT NULL",
        table="webhook_events",
    )
    alter_timestamptz(connection, "webhook_events", "received_at", nullable=False)
    alter_timestamptz(connection, "webhook_events", "updated_at", nullable=False)

    rename_table(connection, "job_queue", "jobs")
    rename_column(connection, "jobs", "wordpress_source_id", "ingestion_source_id")
    rename_column(connection, "jobs", "site_id", "external_source_id")
    rename_column(
        connection,
        "jobs",
        "gohighlevel_access_token_encrypted",
        "provider_secrets_encrypted",
    )
    execute(
        connection,
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS kind text DEFAULT 'reel_publish'",
        table="jobs",
    )
    execute(
        connection,
        "UPDATE jobs SET kind = COALESCE(NULLIF(kind, ''), 'reel_publish')",
        table="jobs",
    )
    alter_jsonb(connection, "jobs", "payload_json")
    alter_jsonb(connection, "jobs", "publish_context_json")
    alter_timestamptz(connection, "jobs", "received_at", nullable=False)
    alter_timestamptz(connection, "jobs", "available_at", nullable=False)
    alter_timestamptz(connection, "jobs", "lease_expires_at")
    alter_timestamptz(connection, "jobs", "created_at", nullable=False)
    alter_timestamptz(connection, "jobs", "updated_at", nullable=False)
    alter_timestamptz(connection, "jobs", "finished_at")

    rename_column(connection, "outbox_events", "wordpress_source_id", "ingestion_source_id")
    rename_column(connection, "outbox_events", "site_id", "external_source_id")
    rename_column(connection, "outbox_events", "payload_json", "payload")
    alter_jsonb(connection, "outbox_events", "payload")
    alter_timestamptz(connection, "outbox_events", "created_at", nullable=False)
    alter_timestamptz(connection, "outbox_events", "available_at", nullable=False)
    alter_timestamptz(connection, "outbox_events", "published_at")

    rename_column(
        connection,
        "scripted_video_artifacts",
        "wordpress_source_id",
        "ingestion_source_id",
    )
    rename_column(connection, "scripted_video_artifacts", "site_id", "external_source_id")
    rename_column(
        connection,
        "scripted_video_artifacts",
        "request_manifest_json",
        "request_manifest",
    )
    alter_jsonb(connection, "scripted_video_artifacts", "request_manifest")
    alter_timestamptz(connection, "scripted_video_artifacts", "created_at", nullable=False)
    alter_timestamptz(connection, "scripted_video_artifacts", "updated_at", nullable=False)


def migrate_provider_connections(connection) -> None:
    if not table_exists(connection, "ghl_connections"):
        return
    rows = connection.execute(
        text(
            """
            SELECT id, agency_id, location_id, user_id, access_token, refresh_token,
                   expires_at, status, created_at, updated_at
            FROM ghl_connections
            """
        )
    ).mappings()
    for row in rows:
        secrets = {
            "access_token": str(row["access_token"] or ""),
            "refresh_token": str(row["refresh_token"] or ""),
            "expires_at": str(row["expires_at"] or ""),
        }
        config = {
            "user_id": str(row["user_id"] or ""),
            "expires_at": str(row["expires_at"] or ""),
        }
        connection.execute(
            text(
                """
                INSERT INTO provider_connections (
                    id, agency_id, provider, external_id, config_json,
                    secrets_encrypted, status, created_at, updated_at
                )
                VALUES (
                    :id, :agency_id, 'gohighlevel', :external_id,
                    CAST(:config_json AS jsonb), :secrets_encrypted,
                    :status, CAST(:created_at AS timestamptz),
                    CAST(:updated_at AS timestamptz)
                )
                ON CONFLICT (agency_id, provider) DO NOTHING
                """
            ),
            {
                "id": row["id"],
                "agency_id": row["agency_id"],
                "external_id": row["location_id"],
                "config_json": json.dumps(config, separators=(",", ":")),
                "secrets_encrypted": encrypt_text(json.dumps(secrets, separators=(",", ":"))),
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )


def migrate_reel_profiles(connection) -> None:
    if not table_exists(connection, "reel_profiles"):
        return
    rows = connection.execute(text("SELECT * FROM reel_profiles ORDER BY updated_at DESC")).mappings()
    seen_agencies: set[str] = set()
    for row in rows:
        agency_id = str(row["agency_id"])
        if agency_id in seen_agencies:
            continue
        seen_agencies.add(agency_id)
        platforms = parse_json(row["platforms_json"], [])
        settings = parse_json(row["extra_settings_json"], {})
        created_at = row["created_at"]
        updated_at = row["updated_at"]
        connection.execute(
            text(
                """
                INSERT INTO agency_brand_settings (
                    agency_id, primary_color, secondary_color, logo_position,
                    logo_object_key, intro_logo_object_key, font_family,
                    created_at, updated_at
                )
                VALUES (
                    :agency_id, :primary_color, :secondary_color, :logo_position,
                    '', '', '', CAST(:created_at AS timestamptz),
                    CAST(:updated_at AS timestamptz)
                )
                ON CONFLICT (agency_id) DO NOTHING
                """
            ),
            {
                "agency_id": agency_id,
                "primary_color": row["brand_primary_color"],
                "secondary_color": row["brand_secondary_color"],
                "logo_position": row["logo_position"],
                "created_at": created_at,
                "updated_at": updated_at,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO agency_reel_defaults (
                    agency_id, platforms, duration_seconds, music_id,
                    intro_enabled, caption_template, settings, created_at, updated_at
                )
                VALUES (
                    :agency_id, :platforms, :duration_seconds, :music_id,
                    :intro_enabled, :caption_template, CAST(:settings AS jsonb),
                    CAST(:created_at AS timestamptz), CAST(:updated_at AS timestamptz)
                )
                ON CONFLICT (agency_id) DO NOTHING
                """
            ),
            {
                "agency_id": agency_id,
                "platforms": list(platforms) if isinstance(platforms, list) else [],
                "duration_seconds": row["duration_seconds"],
                "music_id": row["music_id"],
                "intro_enabled": row["intro_enabled"],
                "caption_template": row["caption_template"],
                "settings": json.dumps(settings, separators=(",", ":")),
                "created_at": created_at,
                "updated_at": updated_at,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO agency_automation_rules (
                    agency_id, approval_required, publish_window_start,
                    publish_window_end, publish_days, trigger_on_status,
                    created_at, updated_at
                )
                VALUES (
                    :agency_id, :approval_required, '', '', ARRAY[]::text[],
                    ARRAY['published']::text[], CAST(:created_at AS timestamptz),
                    CAST(:updated_at AS timestamptz)
                )
                ON CONFLICT (agency_id) DO NOTHING
                """
            ),
            {
                "agency_id": agency_id,
                "approval_required": row["approval_required"],
                "created_at": created_at,
                "updated_at": updated_at,
            },
        )
        social_templates = settings.get("social_templates") if isinstance(settings, dict) else None
        if isinstance(social_templates, dict):
            for platform, template in social_templates.items():
                connection.execute(
                    text(
                        """
                        INSERT INTO agency_social_templates (
                            agency_id, platform, description_template, title_template,
                            hashtags, created_at, updated_at
                        )
                        VALUES (
                            :agency_id, :platform, :description_template, '',
                            ARRAY[]::text[], CAST(:created_at AS timestamptz),
                            CAST(:updated_at AS timestamptz)
                        )
                        ON CONFLICT (agency_id, platform) DO NOTHING
                        """
                    ),
                    {
                        "agency_id": agency_id,
                        "platform": str(platform),
                        "description_template": str(template or ""),
                        "created_at": created_at,
                        "updated_at": updated_at,
                    },
                )


def stamp_head(connection) -> None:
    connection.execute(text("DELETE FROM alembic_version"))
    connection.execute(
        text("INSERT INTO alembic_version (version_num) VALUES (:version)"),
        {"version": HEAD_REVISION},
    )


def rename_table(connection, old: str, new: str) -> None:
    if table_exists(connection, old) and not table_exists(connection, new):
        connection.execute(text(f'ALTER TABLE "{old}" RENAME TO "{new}"'))


def rename_column(connection, table: str, old: str, new: str) -> None:
    if column_exists(connection, table, old) and not column_exists(connection, table, new):
        connection.execute(text(f'ALTER TABLE "{table}" RENAME COLUMN "{old}" TO "{new}"'))


def alter_jsonb(connection, table: str, column: str) -> None:
    if not column_exists(connection, table, column):
        return
    if column_type(connection, table, column) == "jsonb":
        return
    connection.execute(
        text(
            f"""
            ALTER TABLE "{table}"
            ALTER COLUMN "{column}" TYPE jsonb
            USING COALESCE(NULLIF("{column}", '')::jsonb, '{{}}'::jsonb)
            """
        )
    )


def alter_timestamptz(
    connection,
    table: str,
    column: str,
    *,
    nullable: bool = True,
) -> None:
    if not column_exists(connection, table, column):
        return
    if column_type(connection, table, column) == "timestamp with time zone":
        return
    fallback = "NULL" if nullable else "now()"
    if nullable:
        connection.execute(
            text(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" DROP NOT NULL')
        )
    connection.execute(
        text(
            f"""
            ALTER TABLE "{table}"
            ALTER COLUMN "{column}" TYPE timestamptz
            USING COALESCE(NULLIF("{column}", '')::timestamptz, {fallback})
            """
        )
    )


def execute(connection, sql: str, *, table: str) -> None:
    if table_exists(connection, table):
        connection.execute(text(sql))


def parse_json(raw: Any, default: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if raw is None:
        return default
    try:
        return json.loads(str(raw)) if str(raw).strip() else default
    except json.JSONDecodeError:
        return default


def table_exists(connection, table: str) -> bool:
    return inspect(connection).has_table(table)


def column_exists(connection, table: str, column: str) -> bool:
    if not table_exists(connection, table):
        return False
    return any(item["name"] == column for item in inspect(connection).get_columns(table))


def column_type(connection, table: str, column: str) -> str:
    for item in inspect(connection).get_columns(table):
        if item["name"] == column:
            return str(item["type"]).lower()
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
