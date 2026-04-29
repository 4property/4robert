from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from core.errors import ResourceNotFoundError, ValidationError
from repositories.postgres.repository import PostgresRepositoryBase, now_iso


@dataclass(frozen=True, slots=True)
class GoHighLevelConnectionRecord:
    connection_id: str
    agency_id: str
    location_id: str
    user_id: str
    access_token: str
    refresh_token: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str

    def to_public_dict(self) -> dict[str, object]:
        return {
            "connection_id": self.connection_id,
            "agency_id": self.agency_id,
            "location_id": self.location_id,
            "user_id": self.user_id,
            "has_access_token": bool(self.access_token.strip()),
            "has_refresh_token": bool(self.refresh_token.strip()),
            "expires_at": self.expires_at,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class GoHighLevelConnectionStore(PostgresRepositoryBase):
    def __init__(
        self,
        database_locator: str | Path | None,
        *,
        connection=None,
    ) -> None:
        super().__init__(database_locator, connection=connection)

    def get_by_agency_id(self, agency_id: str) -> GoHighLevelConnectionRecord | None:
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            return None
        row = self.connection.execute(
            """
            SELECT
                id,
                agency_id,
                location_id,
                user_id,
                access_token,
                refresh_token,
                expires_at,
                status,
                created_at,
                updated_at
            FROM ghl_connections
            WHERE agency_id = :agency_id
            """,
            {"agency_id": normalized_agency_id},
        ).fetchone()
        if row is None:
            return None
        return _row_to_record(row)

    def get_by_location_id(self, location_id: str) -> GoHighLevelConnectionRecord | None:
        normalized_location_id = str(location_id or "").strip()
        if not normalized_location_id:
            return None
        row = self.connection.execute(
            """
            SELECT
                id,
                agency_id,
                location_id,
                user_id,
                access_token,
                refresh_token,
                expires_at,
                status,
                created_at,
                updated_at
            FROM ghl_connections
            WHERE location_id = :location_id
            """,
            {"location_id": normalized_location_id},
        ).fetchone()
        if row is None:
            return None
        return _row_to_record(row)

    def list_connections(self) -> tuple[GoHighLevelConnectionRecord, ...]:
        rows = self.connection.execute(
            """
            SELECT
                id,
                agency_id,
                location_id,
                user_id,
                access_token,
                refresh_token,
                expires_at,
                status,
                created_at,
                updated_at
            FROM ghl_connections
            ORDER BY updated_at DESC
            """
        ).fetchall()
        return tuple(_row_to_record(row) for row in rows)

    def upsert_for_agency(
        self,
        *,
        agency_id: str,
        location_id: str,
        user_id: str,
        access_token: str,
        refresh_token: str = "",
        expires_at: str = "",
        status: str = "active",
    ) -> GoHighLevelConnectionRecord:
        normalized_agency_id = _require_text(
            agency_id,
            field_name="agency_id",
            code="GHL_AGENCY_ID_REQUIRED",
        )
        normalized_location_id = _require_text(
            location_id,
            field_name="location_id",
            code="GHL_LOCATION_ID_REQUIRED",
        )
        normalized_user_id = str(user_id or "").strip() or "manual"
        normalized_access_token = _require_text(
            access_token,
            field_name="access_token",
            code="GHL_ACCESS_TOKEN_REQUIRED",
        )
        normalized_status = str(status or "active").strip().lower() or "active"
        timestamp = now_iso()
        existing = self.get_by_agency_id(normalized_agency_id)
        if existing is None:
            connection_id = str(uuid4())
            row = self.connection.execute(
                """
                INSERT INTO ghl_connections (
                    id,
                    agency_id,
                    location_id,
                    user_id,
                    access_token,
                    refresh_token,
                    expires_at,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (
                    :id,
                    :agency_id,
                    :location_id,
                    :user_id,
                    :access_token,
                    :refresh_token,
                    :expires_at,
                    :status,
                    :created_at,
                    :updated_at
                )
                RETURNING
                    id,
                    agency_id,
                    location_id,
                    user_id,
                    access_token,
                    refresh_token,
                    expires_at,
                    status,
                    created_at,
                    updated_at
                """,
                {
                    "id": connection_id,
                    "agency_id": normalized_agency_id,
                    "location_id": normalized_location_id,
                    "user_id": normalized_user_id,
                    "access_token": normalized_access_token,
                    "refresh_token": str(refresh_token or "").strip(),
                    "expires_at": str(expires_at or "").strip(),
                    "status": normalized_status,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            ).fetchone()
        else:
            row = self.connection.execute(
                """
                UPDATE ghl_connections
                SET
                    location_id = :location_id,
                    user_id = :user_id,
                    access_token = :access_token,
                    refresh_token = :refresh_token,
                    expires_at = :expires_at,
                    status = :status,
                    updated_at = :updated_at
                WHERE agency_id = :agency_id
                RETURNING
                    id,
                    agency_id,
                    location_id,
                    user_id,
                    access_token,
                    refresh_token,
                    expires_at,
                    status,
                    created_at,
                    updated_at
                """,
                {
                    "agency_id": normalized_agency_id,
                    "location_id": normalized_location_id,
                    "user_id": normalized_user_id,
                    "access_token": normalized_access_token,
                    "refresh_token": str(refresh_token or "").strip(),
                    "expires_at": str(expires_at or "").strip(),
                    "status": normalized_status,
                    "updated_at": timestamp,
                },
            ).fetchone()

        if row is None:
            raise ResourceNotFoundError(
                "The GoHighLevel connection could not be saved.",
                code="GHL_CONNECTION_SAVE_FAILED",
                context={"agency_id": normalized_agency_id},
            )
        return _row_to_record(row)

    def delete_by_agency_id(self, agency_id: str) -> bool:
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            raise ValidationError(
                "The agency_id is required.",
                code="GHL_AGENCY_ID_REQUIRED",
                context={"field": "agency_id"},
            )
        row = self.connection.execute(
            """
            DELETE FROM ghl_connections
            WHERE agency_id = :agency_id
            RETURNING id
            """,
            {"agency_id": normalized_agency_id},
        ).fetchone()
        return row is not None

    def require_for_agency(self, agency_id: str) -> GoHighLevelConnectionRecord:
        record = self.get_by_agency_id(agency_id)
        if record is None or not record.access_token.strip() or not record.location_id.strip():
            raise ResourceNotFoundError(
                "No GoHighLevel connection is configured for this agency.",
                code="GHL_CONNECTION_NOT_FOUND",
                context={"agency_id": str(agency_id or "").strip()},
                hint=(
                    "Configure a GoHighLevel connection (location id + access token) "
                    "for the agency in the admin panel before sending webhooks."
                ),
            )
        return record


def _require_text(value: str, *, field_name: str, code: str) -> str:
    normalized_value = str(value or "").strip()
    if normalized_value:
        return normalized_value
    raise ValidationError(
        f"The {field_name} is required.",
        code=code,
        context={"field": field_name},
    )


def _row_to_record(row) -> GoHighLevelConnectionRecord:
    return GoHighLevelConnectionRecord(
        connection_id=str(row["id"] or ""),
        agency_id=str(row["agency_id"] or ""),
        location_id=str(row["location_id"] or ""),
        user_id=str(row["user_id"] or ""),
        access_token=str(row["access_token"] or ""),
        refresh_token=str(row["refresh_token"] or ""),
        expires_at=str(row["expires_at"] or ""),
        status=str(row["status"] or ""),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
    )


__all__ = ["GoHighLevelConnectionRecord", "GoHighLevelConnectionStore"]
