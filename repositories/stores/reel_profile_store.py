from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from uuid import uuid4

from core.errors import ResourceNotFoundError, ValidationError
from repositories.postgres.repository import PostgresRepositoryBase, now_iso


DEFAULT_PLATFORMS = ("tiktok", "instagram", "linkedin", "youtube", "facebook", "gbp")


@dataclass(frozen=True, slots=True)
class ReelProfileRecord:
    profile_id: str
    agency_id: str
    name: str
    platforms: tuple[str, ...]
    duration_seconds: int
    music_id: str
    intro_enabled: bool
    logo_position: str
    brand_primary_color: str
    brand_secondary_color: str
    caption_template: str
    approval_required: bool
    extra_settings: dict
    created_at: str
    updated_at: str

    def to_public_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "agency_id": self.agency_id,
            "name": self.name,
            "platforms": list(self.platforms),
            "duration_seconds": self.duration_seconds,
            "music_id": self.music_id,
            "intro_enabled": self.intro_enabled,
            "logo_position": self.logo_position,
            "brand_primary_color": self.brand_primary_color,
            "brand_secondary_color": self.brand_secondary_color,
            "caption_template": self.caption_template,
            "approval_required": self.approval_required,
            "extra_settings": dict(self.extra_settings),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ReelProfileStore(PostgresRepositoryBase):
    def __init__(
        self,
        database_locator: str | Path | None,
        *,
        connection=None,
    ) -> None:
        super().__init__(database_locator, connection=connection)

    def get_by_agency_id(self, agency_id: str) -> ReelProfileRecord | None:
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            return None
        row = self.connection.execute(
            """
            SELECT
                id,
                agency_id,
                name,
                platforms_json,
                duration_seconds,
                music_id,
                intro_enabled,
                logo_position,
                brand_primary_color,
                brand_secondary_color,
                caption_template,
                approval_required,
                extra_settings_json,
                created_at,
                updated_at
            FROM reel_profiles
            WHERE agency_id = :agency_id
            """,
            {"agency_id": normalized_agency_id},
        ).fetchone()
        if row is None:
            return None
        return _row_to_record(row)

    def upsert_for_agency(
        self,
        *,
        agency_id: str,
        name: str | None = None,
        platforms: list | tuple | None = None,
        duration_seconds: int | None = None,
        music_id: str | None = None,
        intro_enabled: bool | None = None,
        logo_position: str | None = None,
        brand_primary_color: str | None = None,
        brand_secondary_color: str | None = None,
        caption_template: str | None = None,
        approval_required: bool | None = None,
        extra_settings: dict | None = None,
    ) -> ReelProfileRecord:
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            raise ValidationError(
                "The agency_id is required.",
                code="REEL_PROFILE_AGENCY_ID_REQUIRED",
                context={"field": "agency_id"},
            )

        existing = self.get_by_agency_id(normalized_agency_id)
        timestamp = now_iso()

        merged = {
            "name": (name if name is not None else (existing.name if existing else "Default")),
            "platforms_json": json.dumps(
                list(platforms)
                if platforms is not None
                else (list(existing.platforms) if existing else list(DEFAULT_PLATFORMS))
            ),
            "duration_seconds": int(
                duration_seconds
                if duration_seconds is not None
                else (existing.duration_seconds if existing else 30)
            ),
            "music_id": str(
                music_id if music_id is not None else (existing.music_id if existing else "")
            ),
            "intro_enabled": bool(
                intro_enabled
                if intro_enabled is not None
                else (existing.intro_enabled if existing else True)
            ),
            "logo_position": str(
                logo_position
                if logo_position is not None
                else (existing.logo_position if existing else "top-right")
            ),
            "brand_primary_color": str(
                brand_primary_color
                if brand_primary_color is not None
                else (existing.brand_primary_color if existing else "#0F172A")
            ),
            "brand_secondary_color": str(
                brand_secondary_color
                if brand_secondary_color is not None
                else (existing.brand_secondary_color if existing else "#FFFFFF")
            ),
            "caption_template": str(
                caption_template
                if caption_template is not None
                else (existing.caption_template if existing else "")
            ),
            "approval_required": bool(
                approval_required
                if approval_required is not None
                else (existing.approval_required if existing else False)
            ),
            "extra_settings_json": json.dumps(
                dict(extra_settings)
                if extra_settings is not None
                else (dict(existing.extra_settings) if existing else {})
            ),
        }

        if existing is None:
            profile_id = str(uuid4())
            row = self.connection.execute(
                """
                INSERT INTO reel_profiles (
                    id,
                    agency_id,
                    name,
                    platforms_json,
                    duration_seconds,
                    music_id,
                    intro_enabled,
                    logo_position,
                    brand_primary_color,
                    brand_secondary_color,
                    caption_template,
                    approval_required,
                    extra_settings_json,
                    created_at,
                    updated_at
                )
                VALUES (
                    :id,
                    :agency_id,
                    :name,
                    :platforms_json,
                    :duration_seconds,
                    :music_id,
                    :intro_enabled,
                    :logo_position,
                    :brand_primary_color,
                    :brand_secondary_color,
                    :caption_template,
                    :approval_required,
                    :extra_settings_json,
                    :created_at,
                    :updated_at
                )
                RETURNING
                    id,
                    agency_id,
                    name,
                    platforms_json,
                    duration_seconds,
                    music_id,
                    intro_enabled,
                    logo_position,
                    brand_primary_color,
                    brand_secondary_color,
                    caption_template,
                    approval_required,
                    extra_settings_json,
                    created_at,
                    updated_at
                """,
                {
                    "id": profile_id,
                    "agency_id": normalized_agency_id,
                    **merged,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            ).fetchone()
        else:
            row = self.connection.execute(
                """
                UPDATE reel_profiles
                SET
                    name = :name,
                    platforms_json = :platforms_json,
                    duration_seconds = :duration_seconds,
                    music_id = :music_id,
                    intro_enabled = :intro_enabled,
                    logo_position = :logo_position,
                    brand_primary_color = :brand_primary_color,
                    brand_secondary_color = :brand_secondary_color,
                    caption_template = :caption_template,
                    approval_required = :approval_required,
                    extra_settings_json = :extra_settings_json,
                    updated_at = :updated_at
                WHERE agency_id = :agency_id
                RETURNING
                    id,
                    agency_id,
                    name,
                    platforms_json,
                    duration_seconds,
                    music_id,
                    intro_enabled,
                    logo_position,
                    brand_primary_color,
                    brand_secondary_color,
                    caption_template,
                    approval_required,
                    extra_settings_json,
                    created_at,
                    updated_at
                """,
                {
                    "agency_id": normalized_agency_id,
                    **merged,
                    "updated_at": timestamp,
                },
            ).fetchone()

        if row is None:
            raise ResourceNotFoundError(
                "The reel profile could not be saved.",
                code="REEL_PROFILE_SAVE_FAILED",
                context={"agency_id": normalized_agency_id},
            )
        return _row_to_record(row)

    def delete_by_agency_id(self, agency_id: str) -> bool:
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            return False
        row = self.connection.execute(
            """
            DELETE FROM reel_profiles
            WHERE agency_id = :agency_id
            RETURNING id
            """,
            {"agency_id": normalized_agency_id},
        ).fetchone()
        return row is not None


def _row_to_record(row) -> ReelProfileRecord:
    raw_platforms = row["platforms_json"] or "[]"
    try:
        parsed_platforms = json.loads(raw_platforms)
    except json.JSONDecodeError:
        parsed_platforms = list(DEFAULT_PLATFORMS)
    raw_extra = row["extra_settings_json"] or "{}"
    try:
        parsed_extra = json.loads(raw_extra)
    except json.JSONDecodeError:
        parsed_extra = {}
    return ReelProfileRecord(
        profile_id=str(row["id"] or ""),
        agency_id=str(row["agency_id"] or ""),
        name=str(row["name"] or "Default"),
        platforms=tuple(str(item) for item in parsed_platforms if item is not None),
        duration_seconds=int(row["duration_seconds"] or 30),
        music_id=str(row["music_id"] or ""),
        intro_enabled=bool(row["intro_enabled"]),
        logo_position=str(row["logo_position"] or "top-right"),
        brand_primary_color=str(row["brand_primary_color"] or "#0F172A"),
        brand_secondary_color=str(row["brand_secondary_color"] or "#FFFFFF"),
        caption_template=str(row["caption_template"] or ""),
        approval_required=bool(row["approval_required"]),
        extra_settings=parsed_extra if isinstance(parsed_extra, dict) else {},
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
    )


__all__ = ["DEFAULT_PLATFORMS", "ReelProfileRecord", "ReelProfileStore"]
