from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repositories.postgres.repository import PostgresRepositoryBase, now_iso
from repositories.postgres.security import encrypt_text


@dataclass(frozen=True, slots=True)
class WordPressSourceRecord:
    wordpress_source_id: str
    agency_id: str
    site_id: str
    name: str
    site_url: str | None
    normalized_host: str
    status: str


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


__all__ = ["WordPressSourceRecord", "WordPressSourceStore"]
