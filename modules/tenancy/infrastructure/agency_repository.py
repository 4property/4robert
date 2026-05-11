"""Persistence for the Agency aggregate.

Talks directly to the `agencies` table via the SQLAlchemy session bound by
the Unit of Work. No transaction control — `DatabaseUnitOfWork` decides when
to commit.
"""

from __future__ import annotations

from sqlalchemy import text

from modules.tenancy.domain import Agency
from shared.db.repository_base import ModuleRepository, utcnow


def _isoformat(value: object | None) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def _row_to_agency(row) -> Agency:
    return Agency(
        agency_id=str(row.id),
        name=str(row.name or ""),
        slug=str(row.slug or ""),
        timezone=str(row.timezone or ""),
        status=str(row.status or ""),
        created_at=_isoformat(row.created_at),
        updated_at=_isoformat(row.updated_at),
    )


class AgencyRepository(ModuleRepository):
    """CRUD for tenant agencies (1 row per customer in this multi-tenant SaaS)."""

    def get_by_id(self, agency_id: str) -> Agency | None:
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            return None
        row = self.session.execute(
            text(
                "SELECT id, name, slug, timezone, status, created_at, updated_at "
                "FROM agencies WHERE id = :agency_id"
            ),
            {"agency_id": normalized_agency_id},
        ).first()
        return _row_to_agency(row) if row is not None else None

    def get_by_slug(self, slug: str) -> Agency | None:
        normalized_slug = str(slug or "").strip().lower()
        if not normalized_slug:
            return None
        row = self.session.execute(
            text(
                "SELECT id, name, slug, timezone, status, created_at, updated_at "
                "FROM agencies WHERE slug = :slug"
            ),
            {"slug": normalized_slug},
        ).first()
        return _row_to_agency(row) if row is not None else None

    def list_all(self) -> tuple[Agency, ...]:
        rows = self.session.execute(
            text(
                "SELECT id, name, slug, timezone, status, created_at, updated_at "
                "FROM agencies ORDER BY name ASC"
            )
        ).all()
        return tuple(_row_to_agency(row) for row in rows)

    def create(
        self,
        *,
        agency_id: str,
        name: str,
        slug: str,
        timezone: str = "UTC",
        status: str = "active",
    ) -> None:
        timestamp = utcnow()
        self.session.execute(
            text(
                "INSERT INTO agencies (id, name, slug, timezone, status, created_at, updated_at) "
                "VALUES (:id, :name, :slug, :timezone, :status, :created_at, :updated_at)"
            ),
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

    def update(
        self,
        *,
        agency_id: str,
        name: str,
        slug: str,
        timezone: str,
        status: str,
    ) -> None:
        self.session.execute(
            text(
                "UPDATE agencies SET name = :name, slug = :slug, timezone = :timezone, "
                "status = :status, updated_at = :updated_at WHERE id = :agency_id"
            ),
            {
                "agency_id": str(agency_id).strip(),
                "name": str(name or "").strip(),
                "slug": str(slug or "").strip().lower(),
                "timezone": str(timezone or "UTC").strip() or "UTC",
                "status": str(status or "active").strip().lower() or "active",
                "updated_at": utcnow(),
            },
        )

    def delete(self, agency_id: str) -> bool:
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            return False
        row = self.session.execute(
            text("DELETE FROM agencies WHERE id = :agency_id RETURNING id"),
            {"agency_id": normalized_agency_id},
        ).first()
        return row is not None


__all__ = ["AgencyRepository"]
