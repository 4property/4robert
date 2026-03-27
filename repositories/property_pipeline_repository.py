from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeAlias

from config import (
    DATABASE_FILENAME,
    LEGACY_PROPERTY_COLUMN_DEFINITIONS,
    LEGACY_SITE_ID,
    PROPERTY_COLUMN_DEFINITIONS,
    PROPERTY_UNIQUE_CONSTRAINTS,
)
from models.property import Property
from repositories.sqlite_connection import create_sqlite_connection

DownloadedImage: TypeAlias = tuple[int, str, Path | None]
PROPERTY_REEL_SELECT_FIELDS = (
    "site_id",
    "source_property_id",
    "slug",
    "title",
    "link",
    "featured_image_url",
    "bedrooms",
    "bathrooms",
    "ber_rating",
    "property_status",
    "agent_name",
    "agent_photo_url",
    "agent_email",
    "agent_mobile",
    "agent_number",
    "price",
    "property_type_label",
    "property_area_label",
    "property_county_label",
    "eircode",
    "pps.selected_image_folder",
    "pps.local_manifest_path",
    "pps.local_video_path",
)
LEGACY_PROPERTY_TABLE_NAME = "properties"
LEGACY_PROPERTY_IMAGES_TABLE_NAME = "property_images"
PIPELINE_STATE_TABLE_NAME = "property_pipeline_state"
MIGRATION_PROPERTY_TABLE_NAME = "properties__migration"
MIGRATION_PROPERTY_IMAGES_TABLE_NAME = "property_images__migration"


@dataclass(slots=True)
class PropertySyncState:
    modified_gmt: str | None
    raw_json: str
    image_folder: str
    social_publish_status: str


@dataclass(slots=True)
class PropertyPipelineState:
    site_id: str
    source_property_id: int
    content_fingerprint: str
    content_snapshot_json: str
    publish_target_fingerprint: str
    publish_target_snapshot_json: str
    selected_image_folder: str
    local_manifest_path: str
    local_video_path: str
    render_status: str
    publish_status: str
    publish_details_json: str
    last_published_location_id: str
    created_at: str
    updated_at: str


@dataclass(slots=True)
class PropertyReelRecord:
    site_id: str
    property_id: int
    slug: str
    title: str | None
    link: str | None
    selected_image_folder: str
    local_manifest_path: str
    local_video_path: str
    featured_image_url: str | None
    bedrooms: int | None
    bathrooms: int | None
    ber_rating: str | None
    property_status: str | None
    agent_name: str | None
    agent_photo_url: str | None
    agent_email: str | None
    agent_mobile: str | None
    agent_number: str | None
    price: str | None
    property_type_label: str | None
    property_area_label: str | None
    property_county_label: str | None
    eircode: str | None


def _relative_to_base(path: Path, base_dir: Path) -> str:
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return str(path)


def _build_property_reel_select_sql(where_clause: str) -> str:
    columns_sql = ",\n                    ".join(PROPERTY_REEL_SELECT_FIELDS)
    return (
        "SELECT\n"
        f"                    {columns_sql}\n"
        "                FROM properties\n"
        f"                LEFT JOIN {PIPELINE_STATE_TABLE_NAME} AS pps\n"
        "                    ON pps.site_id = properties.site_id\n"
        "                    AND pps.source_property_id = properties.source_property_id\n"
        f"                {where_clause}"
    )


def _build_table_sql(table_name: str) -> str:
    property_columns_sql = ",\n                ".join(
        f"{column} {definition}"
        for column, definition in PROPERTY_COLUMN_DEFINITIONS
    )
    constraint_sql = ",\n                ".join(PROPERTY_UNIQUE_CONSTRAINTS)
    return (
        f"CREATE TABLE IF NOT EXISTS {table_name} (\n"
        f"                {property_columns_sql},\n"
        f"                {constraint_sql}\n"
        "            );"
    )


def _build_property_images_table_sql(
    table_name: str,
    *,
    property_table_name: str,
) -> str:
    return (
        f"CREATE TABLE IF NOT EXISTS {table_name} (\n"
        "                record_id INTEGER NOT NULL,\n"
        "                position INTEGER NOT NULL,\n"
        "                image_url TEXT NOT NULL,\n"
        "                local_path TEXT,\n"
        "                PRIMARY KEY (record_id, position),\n"
        f"                FOREIGN KEY (record_id) REFERENCES {property_table_name}(record_id) ON DELETE CASCADE\n"
        "            );"
    )


def _build_pipeline_state_table_sql(table_name: str = PIPELINE_STATE_TABLE_NAME) -> str:
    return (
        f"CREATE TABLE IF NOT EXISTS {table_name} (\n"
        "                site_id TEXT NOT NULL,\n"
        "                source_property_id INTEGER NOT NULL,\n"
        "                content_fingerprint TEXT NOT NULL DEFAULT '',\n"
        "                content_snapshot_json TEXT NOT NULL DEFAULT '',\n"
        "                publish_target_fingerprint TEXT NOT NULL DEFAULT '',\n"
        "                publish_target_snapshot_json TEXT NOT NULL DEFAULT '',\n"
        "                selected_image_folder TEXT NOT NULL DEFAULT '',\n"
        "                local_manifest_path TEXT NOT NULL DEFAULT '',\n"
        "                local_video_path TEXT NOT NULL DEFAULT '',\n"
        "                render_status TEXT NOT NULL DEFAULT '',\n"
        "                publish_status TEXT NOT NULL DEFAULT '',\n"
        "                publish_details_json TEXT NOT NULL DEFAULT '',\n"
        "                last_published_location_id TEXT NOT NULL DEFAULT '',\n"
        "                created_at TEXT NOT NULL,\n"
        "                updated_at TEXT NOT NULL,\n"
        "                PRIMARY KEY (site_id, source_property_id)\n"
        "            );"
    )


class PropertyPipelineRepository:
    def __init__(
        self,
        database_path: str | Path,
        base_dir: str | Path,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.base_dir = Path(base_dir).expanduser().resolve()
        self._owns_connection = connection is None
        self.connection = connection or create_sqlite_connection(self.database_path)

    def __enter__(self) -> "PropertyPipelineRepository":
        self.initialise()
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        if not self._owns_connection:
            return
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.connection.close()

    def _table_exists(self, table_name: str) -> bool:
        row = self.connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    def _get_table_columns(self, table_name: str) -> list[str]:
        if not self._table_exists(table_name):
            return []
        return [
            str(row[1])
            for row in self.connection.execute(f"PRAGMA table_info({table_name})")
        ]

    def _create_properties_table(self, table_name: str = "properties") -> None:
        self.connection.executescript(_build_table_sql(table_name))

    def _create_property_images_table(
        self,
        table_name: str = "property_images",
        *,
        property_table_name: str = "properties",
    ) -> None:
        self.connection.executescript(
            _build_property_images_table_sql(
                table_name,
                property_table_name=property_table_name,
            )
        )

    def _create_pipeline_state_table(self, table_name: str = PIPELINE_STATE_TABLE_NAME) -> None:
        self.connection.executescript(_build_pipeline_state_table_sql(table_name))

    def _create_indexes(self) -> None:
        self.connection.executescript(
            f"""
            CREATE INDEX IF NOT EXISTS idx_properties_site_slug
            ON properties (site_id, slug);

            CREATE INDEX IF NOT EXISTS idx_properties_site_fetched_at
            ON properties (site_id, fetched_at DESC);

            CREATE INDEX IF NOT EXISTS idx_pipeline_state_site_publish_status
            ON {PIPELINE_STATE_TABLE_NAME} (site_id, publish_status, updated_at DESC);
            """
        )

    def _ensure_property_columns(self) -> None:
        existing_columns = set(self._get_table_columns("properties"))
        if not existing_columns:
            return

        for column, definition in PROPERTY_COLUMN_DEFINITIONS:
            if column == "record_id" or column in existing_columns:
                continue
            self.connection.execute(
                f"ALTER TABLE properties ADD COLUMN {column} {definition}"
            )

    def _ensure_pipeline_state_columns(self) -> None:
        existing_columns = set(self._get_table_columns(PIPELINE_STATE_TABLE_NAME))
        if not existing_columns:
            return

        pipeline_columns = {
            "site_id": "TEXT NOT NULL",
            "source_property_id": "INTEGER NOT NULL",
            "content_fingerprint": "TEXT NOT NULL DEFAULT ''",
            "content_snapshot_json": "TEXT NOT NULL DEFAULT ''",
            "publish_target_fingerprint": "TEXT NOT NULL DEFAULT ''",
            "publish_target_snapshot_json": "TEXT NOT NULL DEFAULT ''",
            "selected_image_folder": "TEXT NOT NULL DEFAULT ''",
            "local_manifest_path": "TEXT NOT NULL DEFAULT ''",
            "local_video_path": "TEXT NOT NULL DEFAULT ''",
            "render_status": "TEXT NOT NULL DEFAULT ''",
            "publish_status": "TEXT NOT NULL DEFAULT ''",
            "publish_details_json": "TEXT NOT NULL DEFAULT ''",
            "last_published_location_id": "TEXT NOT NULL DEFAULT ''",
            "created_at": "TEXT NOT NULL DEFAULT ''",
            "updated_at": "TEXT NOT NULL DEFAULT ''",
        }
        for column, definition in pipeline_columns.items():
            if column in existing_columns:
                continue
            self.connection.execute(
                f"ALTER TABLE {PIPELINE_STATE_TABLE_NAME} ADD COLUMN {column} {definition}"
            )

    def _is_legacy_schema(self) -> bool:
        existing_columns = set(self._get_table_columns("properties"))
        return (
            bool(existing_columns)
            and "record_id" not in existing_columns
            and "source_property_id" not in existing_columns
            and "id" in existing_columns
        )

    def _migrate_legacy_schema(self) -> None:
        legacy_columns = set(self._get_table_columns(LEGACY_PROPERTY_TABLE_NAME))
        if not legacy_columns:
            return

        self.connection.executescript(
            f"""
            DROP TABLE IF EXISTS {MIGRATION_PROPERTY_IMAGES_TABLE_NAME};
            DROP TABLE IF EXISTS {MIGRATION_PROPERTY_TABLE_NAME};
            """
        )
        self._create_properties_table(MIGRATION_PROPERTY_TABLE_NAME)
        self._create_property_images_table(
            MIGRATION_PROPERTY_IMAGES_TABLE_NAME,
            property_table_name=MIGRATION_PROPERTY_TABLE_NAME,
        )

        copied_columns = [
            column
            for column, _ in LEGACY_PROPERTY_COLUMN_DEFINITIONS
            if column in legacy_columns and column != "id"
        ]
        insert_columns = ["site_id", "source_property_id", *copied_columns]
        select_columns = ["?", "id", *copied_columns]
        self.connection.execute(
            f"""
            INSERT INTO {MIGRATION_PROPERTY_TABLE_NAME} (
                {", ".join(insert_columns)}
            )
            SELECT
                {", ".join(select_columns)}
            FROM {LEGACY_PROPERTY_TABLE_NAME}
            """,
            (LEGACY_SITE_ID,),
        )

        if self._table_exists(LEGACY_PROPERTY_IMAGES_TABLE_NAME):
            self.connection.execute(
                f"""
                INSERT INTO {MIGRATION_PROPERTY_IMAGES_TABLE_NAME} (
                    record_id,
                    position,
                    image_url,
                    local_path
                )
                SELECT
                    migrated.record_id,
                    legacy.position,
                    legacy.image_url,
                    legacy.local_path
                FROM {LEGACY_PROPERTY_IMAGES_TABLE_NAME} AS legacy
                INNER JOIN {MIGRATION_PROPERTY_TABLE_NAME} AS migrated
                    ON migrated.site_id = ?
                    AND migrated.source_property_id = legacy.property_id
                """,
                (LEGACY_SITE_ID,),
            )

        self.connection.executescript(
            f"""
            DROP TABLE IF EXISTS {LEGACY_PROPERTY_IMAGES_TABLE_NAME};
            DROP TABLE IF EXISTS {LEGACY_PROPERTY_TABLE_NAME};
            ALTER TABLE {MIGRATION_PROPERTY_TABLE_NAME} RENAME TO {LEGACY_PROPERTY_TABLE_NAME};
            ALTER TABLE {MIGRATION_PROPERTY_IMAGES_TABLE_NAME} RENAME TO {LEGACY_PROPERTY_IMAGES_TABLE_NAME};
            """
        )
        self._create_indexes()

    def initialise(self) -> None:
        if self._is_legacy_schema():
            self._migrate_legacy_schema()

        self._create_properties_table()
        self._create_property_images_table()
        self._create_pipeline_state_table()
        self._ensure_property_columns()
        self._ensure_pipeline_state_columns()
        self._create_indexes()

    def _upsert_property_record(self, record: dict[str, Any]) -> int:
        columns = list(record.keys())
        placeholders = ", ".join("?" for _ in columns)
        update_clause = ",\n                ".join(
            f"{column} = excluded.{column}"
            for column in columns
        )

        self.connection.execute(
            f"""
            INSERT INTO properties (
                {", ".join(columns)}
            )
            VALUES ({placeholders})
            ON CONFLICT(site_id, source_property_id) DO UPDATE SET
                {update_clause}
            """,
            tuple(record[column] for column in columns),
        )

        row = self.connection.execute(
            """
            SELECT record_id
            FROM properties
            WHERE site_id = ?
            AND source_property_id = ?
            """,
            (record["site_id"], record["source_property_id"]),
        ).fetchone()
        if row is None:
            raise RuntimeError("Failed to resolve the stored property record id.")
        return int(row["record_id"])

    def _replace_property_images(
        self,
        record_id: int,
        downloaded_images: list[DownloadedImage],
    ) -> None:
        self.connection.execute(
            "DELETE FROM property_images WHERE record_id = ?",
            (record_id,),
        )
        self.connection.executemany(
            """
            INSERT INTO property_images (
                record_id,
                position,
                image_url,
                local_path
            )
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    record_id,
                    position,
                    image_url,
                    None if local_path is None else _relative_to_base(local_path, self.base_dir),
                )
                for position, image_url, local_path in downloaded_images
            ],
        )

    def get_property_ids(self, *, site_id: str | None = LEGACY_SITE_ID) -> set[int]:
        if site_id is None:
            rows = self.connection.execute("SELECT DISTINCT source_property_id FROM properties")
        else:
            rows = self.connection.execute(
                "SELECT source_property_id FROM properties WHERE site_id = ?",
                (site_id,),
            )
        return {int(row[0]) for row in rows}

    def get_property_sync_state(
        self,
        *,
        site_id: str = LEGACY_SITE_ID,
        source_property_id: int,
    ) -> PropertySyncState | None:
        row = self.connection.execute(
            f"""
            SELECT
                properties.modified_gmt,
                properties.raw_json,
                COALESCE(pps.selected_image_folder, '') AS selected_image_folder,
                COALESCE(pps.publish_status, '') AS publish_status
            FROM properties
            LEFT JOIN {PIPELINE_STATE_TABLE_NAME} AS pps
                ON pps.site_id = properties.site_id
                AND pps.source_property_id = properties.source_property_id
            WHERE properties.site_id = ?
            AND properties.source_property_id = ?
            """,
            (site_id, source_property_id),
        ).fetchone()
        if row is None:
            return None

        return PropertySyncState(
            modified_gmt=None if row["modified_gmt"] is None else str(row["modified_gmt"]),
            raw_json=str(row["raw_json"]),
            image_folder="" if row["selected_image_folder"] is None else str(row["selected_image_folder"]),
            social_publish_status="" if row["publish_status"] is None else str(row["publish_status"]),
        )

    def _get_property_reel_row(
        self,
        *,
        site_id: str = LEGACY_SITE_ID,
        property_id: int | None = None,
        slug: str | None = None,
    ) -> sqlite3.Row | None:
        if property_id is not None:
            return self.connection.execute(
                _build_property_reel_select_sql(
                    "WHERE properties.site_id = ? AND properties.source_property_id = ?"
                ),
                (site_id, property_id),
            ).fetchone()

        if slug is not None:
            return self.connection.execute(
                _build_property_reel_select_sql("WHERE properties.site_id = ? AND properties.slug = ?"),
                (site_id, slug),
            ).fetchone()

        return self.connection.execute(
            _build_property_reel_select_sql(
                "WHERE properties.site_id = ? "
                "AND COALESCE(pps.selected_image_folder, '') != '' "
                "ORDER BY properties.fetched_at DESC LIMIT 1"
            ),
            (site_id,),
        ).fetchone()

    def get_property_reel_record(
        self,
        *,
        site_id: str = LEGACY_SITE_ID,
        property_id: int | None = None,
        slug: str | None = None,
    ) -> PropertyReelRecord | None:
        row = self._get_property_reel_row(
            site_id=site_id,
            property_id=property_id,
            slug=slug,
        )
        if row is None:
            return None

        return PropertyReelRecord(
            site_id=str(row["site_id"]),
            property_id=int(row["source_property_id"]),
            slug=str(row["slug"]),
            title=None if row["title"] is None else str(row["title"]),
            link=None if row["link"] is None else str(row["link"]),
            selected_image_folder="" if row["selected_image_folder"] is None else str(row["selected_image_folder"]),
            local_manifest_path="" if row["local_manifest_path"] is None else str(row["local_manifest_path"]),
            local_video_path="" if row["local_video_path"] is None else str(row["local_video_path"]),
            featured_image_url=None if row["featured_image_url"] is None else str(row["featured_image_url"]),
            bedrooms=row["bedrooms"],
            bathrooms=row["bathrooms"],
            ber_rating=None if row["ber_rating"] is None else str(row["ber_rating"]),
            property_status=None if row["property_status"] is None else str(row["property_status"]),
            agent_name=None if row["agent_name"] is None else str(row["agent_name"]),
            agent_photo_url=None if row["agent_photo_url"] is None else str(row["agent_photo_url"]),
            agent_email=None if row["agent_email"] is None else str(row["agent_email"]),
            agent_mobile=None if row["agent_mobile"] is None else str(row["agent_mobile"]),
            agent_number=None if row["agent_number"] is None else str(row["agent_number"]),
            price=None if row["price"] is None else str(row["price"]),
            property_type_label=None if row["property_type_label"] is None else str(row["property_type_label"]),
            property_area_label=None if row["property_area_label"] is None else str(row["property_area_label"]),
            property_county_label=None if row["property_county_label"] is None else str(row["property_county_label"]),
            eircode=None if row["eircode"] is None else str(row["eircode"]),
        )

    def _save_property_record(
        self,
        property_item: Property,
        *,
        site_id: str,
        downloaded_images: list[DownloadedImage],
    ) -> None:
        fetched_at = datetime.now(timezone.utc).isoformat()
        record = property_item.to_db_record(
            image_folder="",
            fetched_at=fetched_at,
        )
        record["site_id"] = site_id
        record["image_folder"] = ""
        record["social_publish_status"] = ""
        record["social_publish_details_json"] = ""
        record_id = self._upsert_property_record(record)
        self._replace_property_images(record_id, downloaded_images)

    def get_property_pipeline_state(
        self,
        *,
        site_id: str = LEGACY_SITE_ID,
        source_property_id: int,
    ) -> PropertyPipelineState | None:
        row = self.connection.execute(
            f"""
            SELECT
                site_id,
                source_property_id,
                content_fingerprint,
                content_snapshot_json,
                publish_target_fingerprint,
                publish_target_snapshot_json,
                selected_image_folder,
                local_manifest_path,
                local_video_path,
                render_status,
                publish_status,
                publish_details_json,
                last_published_location_id,
                created_at,
                updated_at
            FROM {PIPELINE_STATE_TABLE_NAME}
            WHERE site_id = ?
            AND source_property_id = ?
            """,
            (site_id, source_property_id),
        ).fetchone()
        if row is None:
            return None

        return PropertyPipelineState(
            site_id=str(row["site_id"]),
            source_property_id=int(row["source_property_id"]),
            content_fingerprint=str(row["content_fingerprint"] or ""),
            content_snapshot_json=str(row["content_snapshot_json"] or ""),
            publish_target_fingerprint=str(row["publish_target_fingerprint"] or ""),
            publish_target_snapshot_json=str(row["publish_target_snapshot_json"] or ""),
            selected_image_folder=str(row["selected_image_folder"] or ""),
            local_manifest_path=str(row["local_manifest_path"] or ""),
            local_video_path=str(row["local_video_path"] or ""),
            render_status=str(row["render_status"] or ""),
            publish_status=str(row["publish_status"] or ""),
            publish_details_json=str(row["publish_details_json"] or ""),
            last_published_location_id=str(row["last_published_location_id"] or ""),
            created_at=str(row["created_at"] or ""),
            updated_at=str(row["updated_at"] or ""),
        )

    def save_property_pipeline_state(self, state: PropertyPipelineState) -> None:
        now = datetime.now(timezone.utc).isoformat()
        created_at = state.created_at or now
        updated_at = now
        self.connection.execute(
            f"""
            INSERT INTO {PIPELINE_STATE_TABLE_NAME} (
                site_id,
                source_property_id,
                content_fingerprint,
                content_snapshot_json,
                publish_target_fingerprint,
                publish_target_snapshot_json,
                selected_image_folder,
                local_manifest_path,
                local_video_path,
                render_status,
                publish_status,
                publish_details_json,
                last_published_location_id,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(site_id, source_property_id) DO UPDATE SET
                content_fingerprint = excluded.content_fingerprint,
                content_snapshot_json = excluded.content_snapshot_json,
                publish_target_fingerprint = excluded.publish_target_fingerprint,
                publish_target_snapshot_json = excluded.publish_target_snapshot_json,
                selected_image_folder = excluded.selected_image_folder,
                local_manifest_path = excluded.local_manifest_path,
                local_video_path = excluded.local_video_path,
                render_status = excluded.render_status,
                publish_status = excluded.publish_status,
                publish_details_json = excluded.publish_details_json,
                last_published_location_id = excluded.last_published_location_id,
                updated_at = excluded.updated_at
            """,
            (
                state.site_id,
                state.source_property_id,
                state.content_fingerprint,
                state.content_snapshot_json,
                state.publish_target_fingerprint,
                state.publish_target_snapshot_json,
                state.selected_image_folder,
                state.local_manifest_path,
                state.local_video_path,
                state.render_status,
                state.publish_status,
                state.publish_details_json,
                state.last_published_location_id,
                created_at,
                updated_at,
            ),
        )

    def save_property_data(
        self,
        property_item: Property,
        *,
        site_id: str = LEGACY_SITE_ID,
        image_folder: str = "",
        social_publish_status: str | None = None,
        social_publish_details_json: str | None = None,
    ) -> None:
        self._save_property_record(
            property_item,
            site_id=site_id,
            downloaded_images=[
                (position, image_url, None)
                for position, image_url in enumerate(property_item.image_urls, start=1)
            ],
        )
        if image_folder or social_publish_status or social_publish_details_json:
            state = self.get_property_pipeline_state(
                site_id=site_id,
                source_property_id=property_item.id,
            ) or PropertyPipelineState(
                site_id=site_id,
                source_property_id=property_item.id,
                content_fingerprint="",
                content_snapshot_json="",
                publish_target_fingerprint="",
                publish_target_snapshot_json="",
                selected_image_folder="",
                local_manifest_path="",
                local_video_path="",
                render_status="",
                publish_status="",
                publish_details_json="",
                last_published_location_id="",
                created_at="",
                updated_at="",
            )
            details_json = state.publish_details_json
            if social_publish_details_json is not None:
                details_json = social_publish_details_json
            self.save_property_pipeline_state(
                PropertyPipelineState(
                    site_id=state.site_id,
                    source_property_id=state.source_property_id,
                    content_fingerprint=state.content_fingerprint,
                    content_snapshot_json=state.content_snapshot_json,
                    publish_target_fingerprint=state.publish_target_fingerprint,
                    publish_target_snapshot_json=state.publish_target_snapshot_json,
                    selected_image_folder=image_folder or state.selected_image_folder,
                    local_manifest_path=state.local_manifest_path,
                    local_video_path=state.local_video_path,
                    render_status=state.render_status,
                    publish_status=social_publish_status or state.publish_status,
                    publish_details_json=details_json,
                    last_published_location_id=state.last_published_location_id,
                    created_at=state.created_at,
                    updated_at=state.updated_at,
                )
            )

    def save_property_images(
        self,
        property_item: Property,
        property_dir: Path,
        downloaded_images: list[DownloadedImage],
        *,
        site_id: str = LEGACY_SITE_ID,
        social_publish_status: str | None = None,
        social_publish_details_json: str | None = None,
    ) -> None:
        self._save_property_record(
            property_item,
            site_id=site_id,
            downloaded_images=downloaded_images,
        )
        state = self.get_property_pipeline_state(
            site_id=site_id,
            source_property_id=property_item.id,
        ) or PropertyPipelineState(
            site_id=site_id,
            source_property_id=property_item.id,
            content_fingerprint="",
            content_snapshot_json="",
            publish_target_fingerprint="",
            publish_target_snapshot_json="",
            selected_image_folder="",
            local_manifest_path="",
            local_video_path="",
            render_status="",
            publish_status="",
            publish_details_json="",
            last_published_location_id="",
            created_at="",
            updated_at="",
        )
        self.save_property_pipeline_state(
            PropertyPipelineState(
                site_id=state.site_id,
                source_property_id=state.source_property_id,
                content_fingerprint=state.content_fingerprint,
                content_snapshot_json=state.content_snapshot_json,
                publish_target_fingerprint=state.publish_target_fingerprint,
                publish_target_snapshot_json=state.publish_target_snapshot_json,
                selected_image_folder=_relative_to_base(property_dir, self.base_dir),
                local_manifest_path=state.local_manifest_path,
                local_video_path=state.local_video_path,
                render_status=state.render_status,
                publish_status=social_publish_status or state.publish_status,
                publish_details_json=social_publish_details_json or state.publish_details_json,
                last_published_location_id=state.last_published_location_id,
                created_at=state.created_at,
                updated_at=state.updated_at,
            )
        )

    def save_downloaded_images(
        self,
        property_item: Property,
        property_dir: Path,
        downloaded_images: list[DownloadedImage],
        *,
        site_id: str = LEGACY_SITE_ID,
    ) -> None:
        self.save_property_images(
            property_item,
            property_dir,
            downloaded_images,
            site_id=site_id,
        )

    def update_social_publish_status(
        self,
        *,
        site_id: str = LEGACY_SITE_ID,
        source_property_id: int,
        status: str,
        details: dict[str, Any] | None = None,
        last_published_location_id: str = "",
    ) -> None:
        details_json = ""
        if details:
            details_json = json.dumps(details, ensure_ascii=False, sort_keys=True)
        state = self.get_property_pipeline_state(
            site_id=site_id,
            source_property_id=source_property_id,
        ) or PropertyPipelineState(
            site_id=site_id,
            source_property_id=source_property_id,
            content_fingerprint="",
            content_snapshot_json="",
            publish_target_fingerprint="",
            publish_target_snapshot_json="",
            selected_image_folder="",
            local_manifest_path="",
            local_video_path="",
            render_status="",
            publish_status="",
            publish_details_json="",
            last_published_location_id="",
            created_at="",
            updated_at="",
        )
        self.save_property_pipeline_state(
            PropertyPipelineState(
                site_id=state.site_id,
                source_property_id=state.source_property_id,
                content_fingerprint=state.content_fingerprint,
                content_snapshot_json=state.content_snapshot_json,
                publish_target_fingerprint=state.publish_target_fingerprint,
                publish_target_snapshot_json=state.publish_target_snapshot_json,
                selected_image_folder=state.selected_image_folder,
                local_manifest_path=state.local_manifest_path,
                local_video_path=state.local_video_path,
                render_status=state.render_status,
                publish_status=status,
                publish_details_json=details_json,
                last_published_location_id=last_published_location_id or state.last_published_location_id,
                created_at=state.created_at,
                updated_at=state.updated_at,
            )
        )

    def save_local_artifacts(
        self,
        *,
        site_id: str = LEGACY_SITE_ID,
        source_property_id: int,
        manifest_path: Path,
        video_path: Path,
    ) -> None:
        state = self.get_property_pipeline_state(
            site_id=site_id,
            source_property_id=source_property_id,
        ) or PropertyPipelineState(
            site_id=site_id,
            source_property_id=source_property_id,
            content_fingerprint="",
            content_snapshot_json="",
            publish_target_fingerprint="",
            publish_target_snapshot_json="",
            selected_image_folder="",
            local_manifest_path="",
            local_video_path="",
            render_status="",
            publish_status="",
            publish_details_json="",
            last_published_location_id="",
            created_at="",
            updated_at="",
        )
        self.save_property_pipeline_state(
            PropertyPipelineState(
                site_id=state.site_id,
                source_property_id=state.source_property_id,
                content_fingerprint=state.content_fingerprint,
                content_snapshot_json=state.content_snapshot_json,
                publish_target_fingerprint=state.publish_target_fingerprint,
                publish_target_snapshot_json=state.publish_target_snapshot_json,
                selected_image_folder=state.selected_image_folder,
                local_manifest_path=_relative_to_base(manifest_path, self.base_dir),
                local_video_path=_relative_to_base(video_path, self.base_dir),
                render_status="completed",
                publish_status=state.publish_status,
                publish_details_json=state.publish_details_json,
                last_published_location_id=state.last_published_location_id,
                created_at=state.created_at,
                updated_at=state.updated_at,
            )
        )


__all__ = [
    "DATABASE_FILENAME",
    "DownloadedImage",
    "PropertyPipelineState",
    "PropertyReelRecord",
    "PropertySyncState",
    "PropertyPipelineRepository",
]

