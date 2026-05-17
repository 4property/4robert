from __future__ import annotations

from typing import Final

from sqlalchemy import text

from modules.configuration.domain import BrandSettings
from modules.configuration.infrastructure.repository_helpers import isoformat
from shared.db.repository_base import ModuleRepository, utcnow


class _Unset:
    """Sentinel for ``BrandSettingsRepository.upsert`` callers that want to
    keep the existing value untouched. Distinct from ``None``, which now
    means "clear the override / persist the empty string"."""

    _instance: "_Unset | None" = None

    def __new__(cls) -> "_Unset":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return "UNSET"

    def __bool__(self) -> bool:  # pragma: no cover - defensive
        return False


UNSET: Final[_Unset] = _Unset()


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
        primary_color: str | None | _Unset = UNSET,
        secondary_color: str | None | _Unset = UNSET,
        logo_position: str | None | _Unset = UNSET,
        logo_object_key: str | None | _Unset = UNSET,
        intro_logo_object_key: str | None | _Unset = UNSET,
        font_family: str | None | _Unset = UNSET,
    ) -> BrandSettings:
        """Upsert the brand row.

        ``UNSET`` (the default) means "leave the column untouched", so
        callers that only want to change one field can omit the rest.
        ``None`` (explicit) means "clear the override — persist the
        empty string", which is what the Reset to default button in the
        frontend sends. A non-``None`` string is persisted verbatim.

        The schema declares each colour / position / object_key column
        ``NOT NULL`` with a server_default, so a "cleared" override is
        always stored as ``""`` (empty string). The renderer treats
        ``""`` and the absence of a row identically when deciding which
        fallback to apply.
        """
        existing = self.get(agency_id)
        timestamp = utcnow()

        def _resolve(
            value: str | None | _Unset,
            attr: str,
            default: str,
        ) -> str:
            if isinstance(value, _Unset):
                return getattr(existing, attr) if existing else default
            if value is None:
                return ""
            return value

        merged = {
            "primary_color": _resolve(primary_color, "primary_color", "#0F172A"),
            "secondary_color": _resolve(secondary_color, "secondary_color", "#FFFFFF"),
            "logo_position": _resolve(logo_position, "logo_position", "top-right"),
            "logo_object_key": _resolve(logo_object_key, "logo_object_key", ""),
            "intro_logo_object_key": _resolve(
                intro_logo_object_key, "intro_logo_object_key", ""
            ),
            "font_family": _resolve(font_family, "font_family", ""),
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


__all__ = ["BrandSettingsRepository", "UNSET"]
