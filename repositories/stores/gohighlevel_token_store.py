from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.errors import ResourceNotFoundError, ValidationError
from repositories.postgres.repository import PostgresRepositoryBase, now_iso


@dataclass(frozen=True, slots=True)
class GoHighLevelTokenRecord:
    location_id: str
    user_id: str
    access_token: str
    refresh_token: str
    expires_at: str
    created_at: str
    updated_at: str

    def to_public_dict(self) -> dict[str, object]:
        return {
            "location_id": self.location_id,
            "user_id": self.user_id,
            "has_access_token": bool(self.access_token.strip()),
            "has_refresh_token": bool(self.refresh_token.strip()),
            "expires_at": self.expires_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class GoHighLevelTokenStore(PostgresRepositoryBase):
    def __init__(
        self,
        database_locator: str | Path | None,
        *,
        connection=None,
    ) -> None:
        super().__init__(database_locator, connection=connection)

    def upsert_token(
        self,
        *,
        location_id: str,
        user_id: str,
        access_token: str,
        refresh_token: str = "",
        expires_at: str = "",
    ) -> GoHighLevelTokenRecord:
        normalized_location_id = _require_text(
            location_id,
            field_name="location_id",
            code="GHL_LOCATION_ID_REQUIRED",
        )
        normalized_user_id = _require_text(
            user_id,
            field_name="user_id",
            code="GHL_USER_ID_REQUIRED",
        )
        normalized_access_token = _require_text(
            access_token,
            field_name="access_token",
            code="GHL_ACCESS_TOKEN_REQUIRED",
        )
        timestamp = now_iso()
        row = self.connection.execute(
            """
            INSERT INTO gohighlevel_tokens (
                location_id,
                user_id,
                access_token,
                refresh_token,
                expires_at,
                created_at,
                updated_at
            )
            VALUES (
                :location_id,
                :user_id,
                :access_token,
                :refresh_token,
                :expires_at,
                :created_at,
                :updated_at
            )
            ON CONFLICT (location_id) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                access_token = EXCLUDED.access_token,
                refresh_token = EXCLUDED.refresh_token,
                expires_at = EXCLUDED.expires_at,
                updated_at = EXCLUDED.updated_at
            RETURNING
                location_id,
                user_id,
                access_token,
                refresh_token,
                expires_at,
                created_at,
                updated_at
            """,
            {
                "location_id": normalized_location_id,
                "user_id": normalized_user_id,
                "access_token": normalized_access_token,
                "refresh_token": str(refresh_token or "").strip(),
                "expires_at": str(expires_at or "").strip(),
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        ).fetchone()
        if row is None:
            raise ResourceNotFoundError(
                "The GoHighLevel token could not be saved.",
                code="GHL_TOKEN_SAVE_FAILED",
                context={"location_id": normalized_location_id},
            )
        return _row_to_token_record(row)

    def get_by_location_id(self, location_id: str) -> GoHighLevelTokenRecord | None:
        normalized_location_id = str(location_id or "").strip()
        if not normalized_location_id:
            return None
        row = self.connection.execute(
            """
            SELECT
                location_id,
                user_id,
                access_token,
                refresh_token,
                expires_at,
                created_at,
                updated_at
            FROM gohighlevel_tokens
            WHERE location_id = :location_id
            """,
            {"location_id": normalized_location_id},
        ).fetchone()
        if row is None:
            return None
        return _row_to_token_record(row)

    def list_tokens(self) -> tuple[GoHighLevelTokenRecord, ...]:
        rows = self.connection.execute(
            """
            SELECT
                location_id,
                user_id,
                access_token,
                refresh_token,
                expires_at,
                created_at,
                updated_at
            FROM gohighlevel_tokens
            ORDER BY updated_at DESC, location_id ASC
            """
        ).fetchall()
        return tuple(_row_to_token_record(row) for row in rows)

    def delete_by_location_id(self, location_id: str) -> bool:
        normalized_location_id = str(location_id or "").strip()
        if not normalized_location_id:
            raise ValidationError(
                "The location_id is required.",
                code="GHL_LOCATION_ID_REQUIRED",
                context={"field": "location_id"},
            )
        row = self.connection.execute(
            """
            DELETE FROM gohighlevel_tokens
            WHERE location_id = :location_id
            RETURNING location_id
            """,
            {"location_id": normalized_location_id},
        ).fetchone()
        return row is not None

    def require_access_token(self, location_id: str) -> str:
        record = self.get_by_location_id(location_id)
        if record is None or not record.access_token.strip():
            raise ResourceNotFoundError(
                "No GoHighLevel token is saved for this location.",
                code="GHL_TOKEN_NOT_FOUND",
                context={"location_id": str(location_id or "").strip()},
                hint=(
                    "Save a token first with POST /mvp/gohighlevel/token, then retry the "
                    "frontend session or WordPress webhook."
                ),
            )
        return record.access_token


def _require_text(value: str, *, field_name: str, code: str) -> str:
    normalized_value = str(value or "").strip()
    if normalized_value:
        return normalized_value
    raise ValidationError(
        f"The {field_name} is required.",
        code=code,
        context={"field": field_name},
    )


def _row_to_token_record(row) -> GoHighLevelTokenRecord:
    return GoHighLevelTokenRecord(
        location_id=str(row["location_id"] or ""),
        user_id=str(row["user_id"] or ""),
        access_token=str(row["access_token"] or ""),
        refresh_token=str(row["refresh_token"] or ""),
        expires_at=str(row["expires_at"] or ""),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
    )


__all__ = ["GoHighLevelTokenRecord", "GoHighLevelTokenStore"]
