from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from repositories.postgres.security import encrypt_text
from repositories.postgres.session import CompatConnection, create_session


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresRepositoryBase:
    def __init__(
        self,
        database_locator: str | Path | None,
        *,
        connection: CompatConnection | None = None,
    ) -> None:
        self.database_locator = database_locator
        self._owns_connection = connection is None
        self.connection = connection or CompatConnection(create_session(database_locator))

    def __enter__(self):
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

    def initialise(self) -> None:
        return None


def ensure_site_context(connection: CompatConnection, site_id: str) -> None:
    normalized_site_id = str(site_id or "").strip().lower()
    if not normalized_site_id:
        return
    agency_row = connection.execute(
        """
        SELECT id
        FROM agencies
        WHERE slug = :slug
        """,
        {"slug": normalized_site_id},
    ).fetchone()
    if agency_row is None:
        agency_id = str(uuid4())
        timestamp = now_iso()
        connection.execute(
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
                'UTC',
                'active',
                :created_at,
                :updated_at
            )
            """,
            {
                "id": agency_id,
                "name": normalized_site_id,
                "slug": normalized_site_id,
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )
    else:
        agency_id = str(agency_row["id"])

    source_row = connection.execute(
        """
        SELECT id
        FROM wordpress_sources
        WHERE site_id = :site_id
        """,
        {"site_id": normalized_site_id},
    ).fetchone()
    if source_row is not None:
        return

    timestamp = now_iso()
    connection.execute(
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
            'active',
            NULL,
            :created_at,
            :updated_at
        )
        """,
        {
            "id": str(uuid4()),
            "agency_id": agency_id,
            "site_id": normalized_site_id,
            "name": normalized_site_id,
            "site_url": f"https://{normalized_site_id}",
            "normalized_host": normalized_site_id,
            "webhook_secret_encrypted": encrypt_text(""),
            "created_at": timestamp,
            "updated_at": timestamp,
        },
    )


__all__ = ["PostgresRepositoryBase", "ensure_site_context", "now_iso"]
