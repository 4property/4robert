from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repositories.postgres.repository import PostgresRepositoryBase, now_iso


def _timestamp_to_text(value: object | None) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


@dataclass(frozen=True, slots=True)
class AgencyRecord:
    agency_id: str
    name: str
    slug: str
    timezone: str
    status: str
    created_at: str | None
    updated_at: str | None


class AgencyStore(PostgresRepositoryBase):
    def __init__(
        self,
        database_locator: str | Path | None,
        *,
        connection=None,
    ) -> None:
        super().__init__(database_locator, connection=connection)

    def get_by_id(self, agency_id: str) -> AgencyRecord | None:
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            return None
        row = self.connection.execute(
            """
            SELECT
                id,
                name,
                slug,
                timezone,
                status,
                created_at,
                updated_at
            FROM agencies
            WHERE id = :agency_id
            """,
            {"agency_id": normalized_agency_id},
        ).fetchone()
        if row is None:
            return None
        return AgencyRecord(
            agency_id=str(row["id"]),
            name=str(row["name"] or ""),
            slug=str(row["slug"] or ""),
            timezone=str(row["timezone"] or ""),
            status=str(row["status"] or ""),
            created_at=_timestamp_to_text(row["created_at"]),
            updated_at=_timestamp_to_text(row["updated_at"]),
        )

    def get_by_slug(self, slug: str) -> AgencyRecord | None:
        normalized_slug = str(slug or "").strip().lower()
        if not normalized_slug:
            return None
        row = self.connection.execute(
            """
            SELECT
                id,
                name,
                slug,
                timezone,
                status,
                created_at,
                updated_at
            FROM agencies
            WHERE slug = :slug
            """,
            {"slug": normalized_slug},
        ).fetchone()
        if row is None:
            return None
        return AgencyRecord(
            agency_id=str(row["id"]),
            name=str(row["name"] or ""),
            slug=str(row["slug"] or ""),
            timezone=str(row["timezone"] or ""),
            status=str(row["status"] or ""),
            created_at=_timestamp_to_text(row["created_at"]),
            updated_at=_timestamp_to_text(row["updated_at"]),
        )

    def create_agency(
        self,
        *,
        agency_id: str,
        name: str,
        slug: str,
        timezone: str = "UTC",
        status: str = "active",
    ) -> None:
        timestamp = now_iso()
        self.connection.execute(
            """
            INSERT INTO agencies (
                id,
                name,
                slug,
                timezone,
                status,
                created_at,
                updated_at
            )
            VALUES (
                :id,
                :name,
                :slug,
                :timezone,
                :status,
                :created_at,
                :updated_at
            )
            """,
            {
                "id": str(agency_id).strip(),
                "name": str(name or "").strip(),
                "slug": str(slug or "").strip().lower(),
                "timezone": str(timezone or "UTC").strip() or "UTC",
                "status": str(status or "active").strip().lower() or "active",
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )

    def update_agency(
        self,
        *,
        agency_id: str,
        name: str,
        slug: str,
        timezone: str,
        status: str,
    ) -> None:
        self.connection.execute(
            """
            UPDATE agencies
            SET
                name = :name,
                slug = :slug,
                timezone = :timezone,
                status = :status,
                updated_at = :updated_at
            WHERE id = :agency_id
            """,
            {
                "agency_id": str(agency_id).strip(),
                "name": str(name or "").strip(),
                "slug": str(slug or "").strip().lower(),
                "timezone": str(timezone or "UTC").strip() or "UTC",
                "status": str(status or "active").strip().lower() or "active",
                "updated_at": now_iso(),
            },
        )


__all__ = ["AgencyRecord", "AgencyStore"]
