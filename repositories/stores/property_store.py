from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from domain.media.types import DownloadedImage
from domain.properties.model import Property
from repositories.postgres.repository import PostgresRepositoryBase

PIPELINE_STATE_TABLE_NAME = "property_pipeline_state"
PROPERTY_IMAGES_TABLE_NAME = "property_images"
PROPERTY_TABLE_NAME = "properties"

PROPERTY_REEL_SELECT_FIELDS = (
    "properties.site_id AS site_id",
    "properties.source_property_id AS source_property_id",
    "properties.slug AS slug",
    "properties.title AS title",
    "properties.link AS link",
    "properties.featured_image_url AS featured_image_url",
    "properties.bedrooms AS bedrooms",
    "properties.bathrooms AS bathrooms",
    "properties.ber_rating AS ber_rating",
    "properties.property_status AS property_status",
    "properties.agent_name AS agent_name",
    "properties.agent_photo_url AS agent_photo_url",
    "properties.agent_email AS agent_email",
    "properties.agent_mobile AS agent_mobile",
    "properties.agent_number AS agent_number",
    "properties.agency_psra AS agency_psra",
    "properties.agency_logo_url AS agency_logo_url",
    "properties.price AS price",
    "properties.price_term AS price_term",
    "properties.property_type_label AS property_type_label",
    "properties.property_area_label AS property_area_label",
    "properties.property_county_label AS property_county_label",
    "properties.property_size AS property_size",
    "properties.eircode AS eircode",
    "properties.viewing_times AS viewing_times",
    "pps.selected_image_folder AS selected_image_folder",
    "pps.artifact_kind AS artifact_kind",
    "pps.local_artifact_path AS local_artifact_path",
    "pps.local_metadata_path AS local_metadata_path",
    "pps.render_profile AS render_profile",
    "pps.local_manifest_path AS local_manifest_path",
    "pps.local_video_path AS local_video_path",
)


@dataclass(slots=True)
class PropertySyncState:
    modified_gmt: str | None
    raw_json: str
    image_folder: str
    social_publish_status: str


@dataclass(slots=True)
class AgencyReelSummary:
    site_id: str
    source_property_id: int
    slug: str
    title: str | None
    link: str | None
    price: str | None
    property_status: str | None
    property_type_label: str | None
    property_area_label: str | None
    property_county_label: str | None
    bedrooms: int | None
    bathrooms: int | None
    featured_image_url: str | None
    agent_name: str | None
    workflow_state: str
    publish_status: str
    render_status: str
    last_published_location_id: str
    pipeline_updated_at: str
    pipeline_created_at: str
    fetched_at: str
    current_revision_id: str
    revision_media_path: str
    revision_metadata_path: str
    revision_artifact_kind: str
    revision_created_at: str


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
    agency_psra: str | None
    agency_logo_url: str | None
    price: str | None
    price_term: str | None
    property_type_label: str | None
    property_area_label: str | None
    property_county_label: str | None
    property_size: str | None
    eircode: str | None
    viewing_times: tuple[str, ...]
    artifact_kind: str
    local_artifact_path: str
    local_metadata_path: str
    render_profile: str


def _deserialize_text_tuple(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if parsed is not None:
                return _deserialize_text_tuple(parsed)
        return (text,)

    if isinstance(value, (list, tuple, set)):
        items: list[str] = []
        for item in value:
            items.extend(_deserialize_text_tuple(item))
        return tuple(items)

    text = str(value).strip()
    return (text,) if text else ()


def _relative_to_base(path: Path, base_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(base_dir))
    except ValueError:
        return str(path.resolve())


def _build_property_reel_select_sql(where_clause: str) -> str:
    columns_sql = ",\n                ".join(PROPERTY_REEL_SELECT_FIELDS)
    return (
        "SELECT\n"
        f"                {columns_sql}\n"
        f"FROM {PROPERTY_TABLE_NAME} AS properties\n"
        f"LEFT JOIN {PIPELINE_STATE_TABLE_NAME} AS pps\n"
        "    ON pps.site_id = properties.site_id\n"
        "    AND pps.source_property_id = properties.source_property_id\n"
        f"{where_clause}"
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PropertyStore(PostgresRepositoryBase):
    def __init__(
        self,
        database_locator: str | Path | None,
        base_dir: str | Path,
        *,
        connection=None,
    ) -> None:
        super().__init__(database_locator, connection=connection)
        self.base_dir = Path(base_dir).expanduser().resolve()

    def list_recent_for_agency(
        self,
        *,
        agency_id: str,
        limit: int = 50,
    ) -> tuple["AgencyReelSummary", ...]:
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            return ()
        rows = self.connection.execute(
            f"""
            SELECT
                p.site_id,
                p.source_property_id,
                p.slug,
                p.title,
                p.link,
                p.price,
                p.property_status,
                p.property_type_label,
                p.property_area_label,
                p.property_county_label,
                p.bedrooms,
                p.bathrooms,
                p.featured_image_url,
                p.agent_name,
                p.fetched_at,
                pps.workflow_state,
                pps.publish_status,
                pps.render_status,
                pps.last_published_location_id,
                pps.current_revision_id,
                pps.created_at AS pipeline_created_at,
                pps.updated_at AS pipeline_updated_at,
                mr.media_path AS revision_media_path,
                mr.metadata_path AS revision_metadata_path,
                mr.artifact_kind AS revision_artifact_kind,
                mr.created_at AS revision_created_at
            FROM {PROPERTY_TABLE_NAME} AS p
            LEFT JOIN {PIPELINE_STATE_TABLE_NAME} AS pps
                ON pps.site_id = p.site_id
                AND pps.source_property_id = p.source_property_id
            LEFT JOIN LATERAL (
                SELECT *
                FROM media_revisions m
                WHERE m.site_id = p.site_id
                AND m.source_property_id = p.source_property_id
                ORDER BY m.created_at DESC
                LIMIT 1
            ) AS mr ON TRUE
            WHERE p.agency_id = :agency_id
            ORDER BY pps.updated_at DESC NULLS LAST, p.fetched_at DESC NULLS LAST
            LIMIT :limit
            """,
            {
                "agency_id": normalized_agency_id,
                "limit": int(max(1, min(limit, 500))),
            },
        ).fetchall()
        return tuple(
            AgencyReelSummary(
                site_id=str(row["site_id"] or ""),
                source_property_id=int(row["source_property_id"] or 0),
                slug=str(row["slug"] or ""),
                title=row["title"],
                link=row["link"],
                price=row["price"],
                property_status=row["property_status"],
                property_type_label=row["property_type_label"],
                property_area_label=row["property_area_label"],
                property_county_label=row["property_county_label"],
                bedrooms=row["bedrooms"],
                bathrooms=row["bathrooms"],
                featured_image_url=row["featured_image_url"],
                agent_name=row["agent_name"],
                workflow_state=str(row["workflow_state"] or ""),
                publish_status=str(row["publish_status"] or ""),
                render_status=str(row["render_status"] or ""),
                last_published_location_id=str(row["last_published_location_id"] or ""),
                pipeline_updated_at=str(row["pipeline_updated_at"] or ""),
                pipeline_created_at=str(row["pipeline_created_at"] or ""),
                fetched_at=str(row["fetched_at"] or ""),
                current_revision_id=str(row["current_revision_id"] or ""),
                revision_media_path=str(row["revision_media_path"] or ""),
                revision_metadata_path=str(row["revision_metadata_path"] or ""),
                revision_artifact_kind=str(row["revision_artifact_kind"] or ""),
                revision_created_at=str(row["revision_created_at"] or ""),
            )
            for row in rows
        )

    def _upsert_property_record(self, record: dict[str, Any]) -> int:
        columns = list(record.keys())
        insert_columns = ", ".join(columns)
        insert_values = ", ".join(f":{column}" for column in columns)
        update_clause = ",\n                ".join(
            f"{column} = EXCLUDED.{column}"
            for column in columns
            if column not in {"site_id", "source_property_id"}
        )
        self.connection.execute(
            f"""
            INSERT INTO {PROPERTY_TABLE_NAME} (
                {insert_columns}
            )
            VALUES (
                {insert_values}
            )
            ON CONFLICT (site_id, source_property_id) DO UPDATE SET
                {update_clause}
            """,
            record,
        )
        row = self.connection.execute(
            f"""
            SELECT record_id
            FROM {PROPERTY_TABLE_NAME}
            WHERE site_id = :site_id
            AND source_property_id = :source_property_id
            """,
            {
                "site_id": record["site_id"],
                "source_property_id": record["source_property_id"],
            },
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
            f"DELETE FROM {PROPERTY_IMAGES_TABLE_NAME} WHERE record_id = :record_id",
            {"record_id": record_id},
        )
        for position, image_url, local_path in downloaded_images:
            self.connection.execute(
                f"""
                INSERT INTO {PROPERTY_IMAGES_TABLE_NAME} (
                    record_id,
                    position,
                    image_url,
                    local_path
                )
                VALUES (
                    :record_id,
                    :position,
                    :image_url,
                    :local_path
                )
                """,
                {
                    "record_id": record_id,
                    "position": position,
                    "image_url": image_url,
                    "local_path": (
                        None
                        if local_path is None
                        else _relative_to_base(local_path, self.base_dir)
                    ),
                },
            )

    def _save_property_record(
        self,
        property_item: Property,
        *,
        agency_id: str,
        wordpress_source_id: str,
        site_id: str,
        downloaded_images: list[DownloadedImage],
        social_publish_status: str = "",
        social_publish_details_json: str = "",
    ) -> None:
        fetched_at = _now_iso()
        record = property_item.to_db_record(
            image_folder="",
            fetched_at=fetched_at,
        )
        record["agency_id"] = agency_id
        record["wordpress_source_id"] = wordpress_source_id
        record["site_id"] = site_id
        record["image_folder"] = ""
        record["social_publish_status"] = social_publish_status
        record["social_publish_details_json"] = social_publish_details_json
        record_id = self._upsert_property_record(record)
        self._replace_property_images(record_id, downloaded_images)

    def get_property_ids(self, *, site_id: str | None = None) -> set[int]:
        if site_id is None:
            rows = self.connection.execute(
                f"SELECT DISTINCT source_property_id FROM {PROPERTY_TABLE_NAME}"
            ).fetchall()
        else:
            rows = self.connection.execute(
                f"SELECT source_property_id FROM {PROPERTY_TABLE_NAME} WHERE site_id = :site_id",
                {"site_id": site_id},
            ).fetchall()
        return {int(row[0]) for row in rows}

    def get_property_sync_state(
        self,
        *,
        site_id: str,
        source_property_id: int,
    ) -> PropertySyncState | None:
        row = self.connection.execute(
            f"""
            SELECT
                properties.modified_gmt,
                properties.raw_json,
                COALESCE(pps.selected_image_folder, '') AS selected_image_folder,
                COALESCE(pps.publish_status, '') AS publish_status
            FROM {PROPERTY_TABLE_NAME} AS properties
            LEFT JOIN {PIPELINE_STATE_TABLE_NAME} AS pps
                ON pps.site_id = properties.site_id
                AND pps.source_property_id = properties.source_property_id
            WHERE properties.site_id = :site_id
            AND properties.source_property_id = :source_property_id
            """,
            {
                "site_id": site_id,
                "source_property_id": source_property_id,
            },
        ).fetchone()
        if row is None:
            return None
        return PropertySyncState(
            modified_gmt=None if row["modified_gmt"] is None else str(row["modified_gmt"]),
            raw_json=str(row["raw_json"] or ""),
            image_folder=str(row["selected_image_folder"] or ""),
            social_publish_status=str(row["publish_status"] or ""),
        )

    def _get_property_reel_row(
        self,
        *,
        site_id: str,
        property_id: int | None = None,
        slug: str | None = None,
    ):
        if property_id is not None:
            return self.connection.execute(
                _build_property_reel_select_sql(
                    "\nWHERE properties.site_id = :site_id AND properties.source_property_id = :property_id"
                ),
                {
                    "site_id": site_id,
                    "property_id": property_id,
                },
            ).fetchone()

        if slug is not None:
            return self.connection.execute(
                _build_property_reel_select_sql(
                    "\nWHERE properties.site_id = :site_id AND properties.slug = :slug"
                ),
                {
                    "site_id": site_id,
                    "slug": slug,
                },
            ).fetchone()

        return self.connection.execute(
            _build_property_reel_select_sql(
                "\nWHERE properties.site_id = :site_id "
                "AND COALESCE(pps.selected_image_folder, '') != '' "
                "ORDER BY properties.fetched_at DESC LIMIT 1"
            ),
            {"site_id": site_id},
        ).fetchone()

    def get_property_reel_record(
        self,
        *,
        site_id: str,
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
            selected_image_folder=str(row["selected_image_folder"] or ""),
            local_manifest_path=str(row["local_manifest_path"] or ""),
            local_video_path=str(row["local_video_path"] or ""),
            featured_image_url=(
                None if row["featured_image_url"] is None else str(row["featured_image_url"])
            ),
            bedrooms=None if row["bedrooms"] is None else int(row["bedrooms"]),
            bathrooms=None if row["bathrooms"] is None else int(row["bathrooms"]),
            ber_rating=None if row["ber_rating"] is None else str(row["ber_rating"]),
            property_status=(
                None if row["property_status"] is None else str(row["property_status"])
            ),
            agent_name=None if row["agent_name"] is None else str(row["agent_name"]),
            agent_photo_url=(
                None if row["agent_photo_url"] is None else str(row["agent_photo_url"])
            ),
            agent_email=None if row["agent_email"] is None else str(row["agent_email"]),
            agent_mobile=None if row["agent_mobile"] is None else str(row["agent_mobile"]),
            agent_number=None if row["agent_number"] is None else str(row["agent_number"]),
            agency_psra=None if row["agency_psra"] is None else str(row["agency_psra"]),
            agency_logo_url=(
                None if row["agency_logo_url"] is None else str(row["agency_logo_url"])
            ),
            price=None if row["price"] is None else str(row["price"]),
            price_term=None if row["price_term"] is None else str(row["price_term"]),
            property_type_label=(
                None if row["property_type_label"] is None else str(row["property_type_label"])
            ),
            property_area_label=(
                None if row["property_area_label"] is None else str(row["property_area_label"])
            ),
            property_county_label=(
                None if row["property_county_label"] is None else str(row["property_county_label"])
            ),
            property_size=None if row["property_size"] is None else str(row["property_size"]),
            eircode=None if row["eircode"] is None else str(row["eircode"]),
            viewing_times=_deserialize_text_tuple(row["viewing_times"]),
            artifact_kind=str(row["artifact_kind"] or ""),
            local_artifact_path=str(row["local_artifact_path"] or ""),
            local_metadata_path=str(row["local_metadata_path"] or ""),
            render_profile=str(row["render_profile"] or ""),
        )

    def save_property_data(
        self,
        property_item: Property,
        *,
        agency_id: str,
        wordpress_source_id: str,
        site_id: str,
        image_folder: str = "",
        social_publish_status: str | None = None,
        social_publish_details_json: str | None = None,
    ) -> None:
        del image_folder
        self._save_property_record(
            property_item,
            agency_id=agency_id,
            wordpress_source_id=wordpress_source_id,
            site_id=site_id,
            downloaded_images=[
                (position, image_url, None)
                for position, image_url in enumerate(property_item.image_urls, start=1)
            ],
            social_publish_status=social_publish_status or "",
            social_publish_details_json=social_publish_details_json or "",
        )

    def save_property_images(
        self,
        property_item: Property,
        property_dir: Path,
        downloaded_images: list[DownloadedImage],
        *,
        agency_id: str,
        wordpress_source_id: str,
        site_id: str,
        social_publish_status: str | None = None,
        social_publish_details_json: str | None = None,
    ) -> None:
        del property_dir
        self._save_property_record(
            property_item,
            agency_id=agency_id,
            wordpress_source_id=wordpress_source_id,
            site_id=site_id,
            downloaded_images=downloaded_images,
            social_publish_status=social_publish_status or "",
            social_publish_details_json=social_publish_details_json or "",
        )

    def save_downloaded_images(
        self,
        property_item: Property,
        property_dir: Path,
        downloaded_images: list[DownloadedImage],
        *,
        agency_id: str,
        wordpress_source_id: str,
        site_id: str,
    ) -> None:
        self.save_property_images(
            property_item,
            property_dir,
            downloaded_images,
            agency_id=agency_id,
            wordpress_source_id=wordpress_source_id,
            site_id=site_id,
        )


__all__ = [
    "AgencyReelSummary",
    "PIPELINE_STATE_TABLE_NAME",
    "PROPERTY_IMAGES_TABLE_NAME",
    "PROPERTY_TABLE_NAME",
    "PropertyReelRecord",
    "PropertyStore",
    "PropertySyncState",
]
