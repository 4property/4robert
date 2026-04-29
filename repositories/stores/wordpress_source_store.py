from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repositories.postgres.repository import PostgresRepositoryBase, now_iso
from repositories.postgres.security import encrypt_text


def _timestamp_to_text(value: object | None) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


@dataclass(frozen=True, slots=True)
class WordPressSourceRecord:
    wordpress_source_id: str
    agency_id: str
    site_id: str
    name: str
    site_url: str | None
    normalized_host: str
    status: str


@dataclass(frozen=True, slots=True)
class WordPressSourceDetailsRecord:
    wordpress_source_id: str
    agency_id: str
    agency_name: str
    agency_slug: str
    agency_timezone: str
    agency_status: str
    site_id: str
    name: str
    site_url: str | None
    normalized_host: str
    status: str
    has_webhook_secret: bool
    last_event_at: str | None
    created_at: str | None
    updated_at: str | None


class WordPressSourceStore(PostgresRepositoryBase):
    def __init__(
        self,
        database_locator: str | Path | None,
        *,
        connection=None,
    ) -> None:
        super().__init__(database_locator, connection=connection)

    def get_by_site_id(self, site_id: str) -> WordPressSourceRecord | None:
        normalized_site_id = str(site_id or "").strip().lower()
        if not normalized_site_id:
            return None
        row = self.connection.execute(
            """
            SELECT
                id,
                agency_id,
                site_id,
                name,
                site_url,
                normalized_host,
                status
            FROM wordpress_sources
            WHERE site_id = :site_id
            """,
            {"site_id": normalized_site_id},
        ).fetchone()
        if row is None:
            return None
        return WordPressSourceRecord(
            wordpress_source_id=str(row["id"]),
            agency_id=str(row["agency_id"]),
            site_id=str(row["site_id"]),
            name=str(row["name"] or ""),
            site_url=None if row["site_url"] is None else str(row["site_url"]),
            normalized_host=str(row["normalized_host"] or ""),
            status=str(row["status"] or ""),
        )

    def create_source(
        self,
        *,
        wordpress_source_id: str,
        agency_id: str,
        site_id: str,
        name: str,
        site_url: str | None = None,
        normalized_host: str | None = None,
        status: str = "active",
        webhook_secret: str = "",
    ) -> None:
        timestamp = now_iso()
        normalized_site_id = str(site_id or "").strip().lower()
        self.connection.execute(
            """
            INSERT INTO wordpress_sources (
                id,
                agency_id,
                site_id,
                name,
                site_url,
                normalized_host,
                webhook_secret_encrypted,
                status,
                last_event_at,
                created_at,
                updated_at
            )
            VALUES (
                :id,
                :agency_id,
                :site_id,
                :name,
                :site_url,
                :normalized_host,
                :webhook_secret_encrypted,
                :status,
                NULL,
                :created_at,
                :updated_at
            )
            """,
            {
                "id": wordpress_source_id,
                "agency_id": agency_id,
                "site_id": normalized_site_id,
                "name": name,
                "site_url": site_url,
                "normalized_host": normalized_host or normalized_site_id,
                "webhook_secret_encrypted": encrypt_text(webhook_secret),
                "status": status,
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )

    def update_source(
        self,
        *,
        wordpress_source_id: str,
        name: str,
        site_url: str | None = None,
        normalized_host: str | None = None,
        status: str = "active",
        webhook_secret: str = "",
        update_webhook_secret: bool = False,
    ) -> None:
        assignments = [
            "name = :name",
            "site_url = :site_url",
            "normalized_host = :normalized_host",
            "status = :status",
            "updated_at = :updated_at",
        ]
        parameters = {
            "wordpress_source_id": str(wordpress_source_id).strip(),
            "name": str(name or "").strip(),
            "site_url": site_url,
            "normalized_host": str(normalized_host or "").strip(),
            "status": str(status or "active").strip().lower() or "active",
            "updated_at": now_iso(),
        }
        if update_webhook_secret:
            assignments.append("webhook_secret_encrypted = :webhook_secret_encrypted")
            parameters["webhook_secret_encrypted"] = encrypt_text(webhook_secret)

        self.connection.execute(
            f"""
            UPDATE wordpress_sources
            SET
                {", ".join(assignments)}
            WHERE id = :wordpress_source_id
            """,
            parameters,
        )

    def get_details_by_site_id(self, site_id: str) -> WordPressSourceDetailsRecord | None:
        normalized_site_id = str(site_id or "").strip().lower()
        if not normalized_site_id:
            return None
        row = self.connection.execute(
            """
            SELECT
                source.id,
                source.agency_id,
                source.site_id,
                source.name,
                source.site_url,
                source.normalized_host,
                source.status,
                source.last_event_at,
                source.created_at,
                source.updated_at,
                agency.name AS agency_name,
                agency.slug AS agency_slug,
                agency.timezone AS agency_timezone,
                agency.status AS agency_status,
                CASE
                    WHEN source.webhook_secret_encrypted IS NULL
                        OR octet_length(source.webhook_secret_encrypted) = 0
                    THEN FALSE
                    ELSE TRUE
                END AS has_webhook_secret
            FROM wordpress_sources AS source
            INNER JOIN agencies AS agency
                ON agency.id = source.agency_id
            WHERE source.site_id = :site_id
            """,
            {"site_id": normalized_site_id},
        ).fetchone()
        if row is None:
            return None
        return WordPressSourceDetailsRecord(
            wordpress_source_id=str(row["id"]),
            agency_id=str(row["agency_id"]),
            agency_name=str(row["agency_name"] or ""),
            agency_slug=str(row["agency_slug"] or ""),
            agency_timezone=str(row["agency_timezone"] or ""),
            agency_status=str(row["agency_status"] or ""),
            site_id=str(row["site_id"] or ""),
            name=str(row["name"] or ""),
            site_url=None if row["site_url"] is None else str(row["site_url"]),
            normalized_host=str(row["normalized_host"] or ""),
            status=str(row["status"] or ""),
            has_webhook_secret=bool(row["has_webhook_secret"]),
            last_event_at=_timestamp_to_text(row["last_event_at"]),
            created_at=_timestamp_to_text(row["created_at"]),
            updated_at=_timestamp_to_text(row["updated_at"]),
        )

    def list_sources_for_agency(
        self, agency_id: str
    ) -> tuple[WordPressSourceDetailsRecord, ...]:
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            return ()
        rows = self.connection.execute(
            """
            SELECT
                source.id,
                source.agency_id,
                source.site_id,
                source.name,
                source.site_url,
                source.normalized_host,
                source.status,
                source.last_event_at,
                source.created_at,
                source.updated_at,
                agency.name AS agency_name,
                agency.slug AS agency_slug,
                agency.timezone AS agency_timezone,
                agency.status AS agency_status,
                CASE
                    WHEN source.webhook_secret_encrypted IS NULL
                        OR octet_length(source.webhook_secret_encrypted) = 0
                    THEN FALSE
                    ELSE TRUE
                END AS has_webhook_secret
            FROM wordpress_sources AS source
            INNER JOIN agencies AS agency
                ON agency.id = source.agency_id
            WHERE source.agency_id = :agency_id
            ORDER BY source.site_id ASC
            """,
            {"agency_id": normalized_agency_id},
        ).fetchall()
        return tuple(
            WordPressSourceDetailsRecord(
                wordpress_source_id=str(row["id"]),
                agency_id=str(row["agency_id"]),
                agency_name=str(row["agency_name"] or ""),
                agency_slug=str(row["agency_slug"] or ""),
                agency_timezone=str(row["agency_timezone"] or ""),
                agency_status=str(row["agency_status"] or ""),
                site_id=str(row["site_id"] or ""),
                name=str(row["name"] or ""),
                site_url=None if row["site_url"] is None else str(row["site_url"]),
                normalized_host=str(row["normalized_host"] or ""),
                status=str(row["status"] or ""),
                has_webhook_secret=bool(row["has_webhook_secret"]),
                last_event_at=_timestamp_to_text(row["last_event_at"]),
                created_at=_timestamp_to_text(row["created_at"]),
                updated_at=_timestamp_to_text(row["updated_at"]),
            )
            for row in rows
        )

    def delete_source(self, wordpress_source_id: str) -> bool:
        normalized_id = str(wordpress_source_id or "").strip()
        if not normalized_id:
            return False
        row = self.connection.execute(
            """
            DELETE FROM wordpress_sources
            WHERE id = :wordpress_source_id
            RETURNING id
            """,
            {"wordpress_source_id": normalized_id},
        ).fetchone()
        return row is not None

    def list_sources(self) -> tuple[WordPressSourceDetailsRecord, ...]:
        rows = self.connection.execute(
            """
            SELECT
                source.id,
                source.agency_id,
                source.site_id,
                source.name,
                source.site_url,
                source.normalized_host,
                source.status,
                source.last_event_at,
                source.created_at,
                source.updated_at,
                agency.name AS agency_name,
                agency.slug AS agency_slug,
                agency.timezone AS agency_timezone,
                agency.status AS agency_status,
                CASE
                    WHEN source.webhook_secret_encrypted IS NULL
                        OR octet_length(source.webhook_secret_encrypted) = 0
                    THEN FALSE
                    ELSE TRUE
                END AS has_webhook_secret
            FROM wordpress_sources AS source
            INNER JOIN agencies AS agency
                ON agency.id = source.agency_id
            ORDER BY source.site_id ASC
            """
        ).fetchall()
        return tuple(
            WordPressSourceDetailsRecord(
                wordpress_source_id=str(row["id"]),
                agency_id=str(row["agency_id"]),
                agency_name=str(row["agency_name"] or ""),
                agency_slug=str(row["agency_slug"] or ""),
                agency_timezone=str(row["agency_timezone"] or ""),
                agency_status=str(row["agency_status"] or ""),
                site_id=str(row["site_id"] or ""),
                name=str(row["name"] or ""),
                site_url=None if row["site_url"] is None else str(row["site_url"]),
                normalized_host=str(row["normalized_host"] or ""),
                status=str(row["status"] or ""),
                has_webhook_secret=bool(row["has_webhook_secret"]),
                last_event_at=_timestamp_to_text(row["last_event_at"]),
                created_at=_timestamp_to_text(row["created_at"]),
                updated_at=_timestamp_to_text(row["updated_at"]),
            )
            for row in rows
        )


__all__ = [
    "WordPressSourceDetailsRecord",
    "WordPressSourceRecord",
    "WordPressSourceStore",
]
