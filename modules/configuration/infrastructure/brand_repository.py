from __future__ import annotations

from sqlalchemy import text

from modules.configuration.domain import BrandSettings
from modules.configuration.infrastructure.repository_helpers import isoformat
from shared.db.repository_base import ModuleRepository, utcnow


class BrandSettingsRepository(ModuleRepository):
    def get(self, agency_id: str) -> BrandSettings | None:
        row = self.session.execute(
            text(
                "SELECT agency_id, primary_color, secondary_color, logo_position, "
                "logo_object_key, intro_logo_object_key, font_family, created_at, "
                "updated_at FROM agency_brand_settings WHERE agency_id = :agency_id"
            ),
            {"agency_id": agency_id},
        ).first()
        if row is None:
            return None
        return BrandSettings(
            agency_id=str(row.agency_id),
            primary_color=str(row.primary_color or ""),
            secondary_color=str(row.secondary_color or ""),
            logo_position=str(row.logo_position or ""),
            logo_object_key=str(row.logo_object_key or ""),
            intro_logo_object_key=str(row.intro_logo_object_key or ""),
            font_family=str(row.font_family or ""),
            created_at=isoformat(row.created_at) or "",
            updated_at=isoformat(row.updated_at) or "",
        )

    def upsert(
        self,
        *,
        agency_id: str,
        primary_color: str | None = None,
        secondary_color: str | None = None,
        logo_position: str | None = None,
        logo_object_key: str | None = None,
        intro_logo_object_key: str | None = None,
        font_family: str | None = None,
    ) -> BrandSettings:
        existing = self.get(agency_id)
        timestamp = utcnow()
        merged = {
            "primary_color": primary_color
            if primary_color is not None
            else (existing.primary_color if existing else "#0F172A"),
            "secondary_color": secondary_color
            if secondary_color is not None
            else (existing.secondary_color if existing else "#FFFFFF"),
            "logo_position": logo_position
            if logo_position is not None
            else (existing.logo_position if existing else "top-right"),
            "logo_object_key": logo_object_key
            if logo_object_key is not None
            else (existing.logo_object_key if existing else ""),
            "intro_logo_object_key": intro_logo_object_key
            if intro_logo_object_key is not None
            else (existing.intro_logo_object_key if existing else ""),
            "font_family": font_family
            if font_family is not None
            else (existing.font_family if existing else ""),
        }
        self.session.execute(
            text(
                "INSERT INTO agency_brand_settings ("
                "agency_id, primary_color, secondary_color, logo_position, "
                "logo_object_key, intro_logo_object_key, font_family, "
                "created_at, updated_at"
                ") VALUES ("
                ":agency_id, :primary_color, :secondary_color, :logo_position, "
                ":logo_object_key, :intro_logo_object_key, :font_family, "
                ":created_at, :updated_at"
                ") ON CONFLICT (agency_id) DO UPDATE SET "
                "primary_color = EXCLUDED.primary_color, "
                "secondary_color = EXCLUDED.secondary_color, "
                "logo_position = EXCLUDED.logo_position, "
                "logo_object_key = EXCLUDED.logo_object_key, "
                "intro_logo_object_key = EXCLUDED.intro_logo_object_key, "
                "font_family = EXCLUDED.font_family, "
                "updated_at = EXCLUDED.updated_at"
            ),
            {
                "agency_id": agency_id,
                **merged,
                "created_at": existing.created_at if existing else timestamp,
                "updated_at": timestamp,
            },
        )
        result = self.get(agency_id)
        assert result is not None
        return result


__all__ = ["BrandSettingsRepository"]
