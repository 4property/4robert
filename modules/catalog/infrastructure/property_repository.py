"""Persistence for the catalog property aggregate.

Stores canonical property records and image references. The complex JOIN
reads that combine catalog + reels live in
[`modules/reels/infrastructure/reel_query.py`](../../reels/infrastructure/reel_query.py).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import text

from modules.catalog.domain import CatalogPropertyImage, PropertySyncState
from shared.db.repository_base import ModuleRepository, utcnow


def _isoformat(value: object | None) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def _relative_to_base(path: Path, base_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(base_dir))
    except ValueError:
        return str(path.resolve())


class PropertyRepository(ModuleRepository):
    """CRUD for `properties` rows."""

    def __init__(self, session, base_dir: str | Path | None = None) -> None:
        super().__init__(session)
        self.base_dir = Path(base_dir).expanduser().resolve() if base_dir else None

    def get_raw_payload(
        self,
        *,
        external_source_id: str,
        source_property_id: int,
    ) -> str | None:
        normalized = str(external_source_id or "").strip().lower()
        row = self.session.execute(
            text(
                "SELECT raw_json FROM properties WHERE external_source_id = :id "
                "AND source_property_id = :pid"
            ),
            {"id": normalized, "pid": int(source_property_id)},
        ).first()
        if row is None:
            return None
        if row.raw_json is None:
            return None
        if isinstance(row.raw_json, (dict, list)):
            return json.dumps(row.raw_json, ensure_ascii=False)
        text_value = str(row.raw_json).strip()
        return text_value or None

    def get_sync_state(
        self,
        *,
        external_source_id: str,
        source_property_id: int,
    ) -> PropertySyncState | None:
        row = self.session.execute(
            text(
                "SELECT p.modified_gmt, p.raw_json, "
                "COALESCE(r.selected_image_folder, '') AS selected_image_folder, "
                "COALESCE(r.publish_status, '') AS publish_status "
                "FROM properties AS p "
                "LEFT JOIN reels AS r "
                "  ON r.external_source_id = p.external_source_id "
                "  AND r.source_property_id = p.source_property_id "
                "WHERE p.external_source_id = :id "
                "AND p.source_property_id = :pid"
            ),
            {"id": external_source_id, "pid": source_property_id},
        ).first()
        if row is None:
            return None
        raw_value = row.raw_json
        raw_text = (
            json.dumps(raw_value, ensure_ascii=False)
            if isinstance(raw_value, (dict, list))
            else str(raw_value or "")
        )
        return PropertySyncState(
            modified_gmt=None if row.modified_gmt is None else str(row.modified_gmt),
            raw_json=raw_text,
            image_folder=str(row.selected_image_folder or ""),
            social_publish_status=str(row.publish_status or ""),
        )

    def get_property_ids(
        self, *, external_source_id: str | None = None
    ) -> set[int]:
        if external_source_id is None:
            rows = self.session.execute(
                text("SELECT DISTINCT source_property_id FROM properties")
            ).all()
        else:
            rows = self.session.execute(
                text(
                    "SELECT source_property_id FROM properties "
                    "WHERE external_source_id = :id"
                ),
                {"id": external_source_id},
            ).all()
        return {int(row[0]) for row in rows}

    def upsert_property(self, record: dict[str, Any]) -> int:
        """Upsert by (external_source_id, source_property_id) — returns record_id."""
        columns = list(record.keys())
        if "raw_json" in record and not isinstance(record["raw_json"], str):
            record["raw_json"] = json.dumps(record["raw_json"], ensure_ascii=False)
        insert_columns = ", ".join(columns)
        insert_values = ", ".join(
            f"CAST(:{column} AS jsonb)" if column == "raw_json" else f":{column}"
            for column in columns
        )
        update_clause = ", ".join(
            f"{column} = EXCLUDED.{column}"
            for column in columns
            if column not in {"external_source_id", "source_property_id"}
        )
        self.session.execute(
            text(
                f"INSERT INTO properties ({insert_columns}) VALUES ({insert_values}) "
                f"ON CONFLICT (external_source_id, source_property_id) DO UPDATE SET "
                f"{update_clause}"
            ),
            record,
        )
        row = self.session.execute(
            text(
                "SELECT record_id FROM properties WHERE external_source_id = :id "
                "AND source_property_id = :pid"
            ),
            {
                "id": record["external_source_id"],
                "pid": record["source_property_id"],
            },
        ).first()
        if row is None:
            raise RuntimeError("Failed to resolve the stored property record id.")
        return int(row.record_id)


class PropertyImageRepository(ModuleRepository):
    """CRUD for `property_images` rows. Per-record_id positional ordering."""

    def __init__(self, session, base_dir: str | Path | None = None) -> None:
        super().__init__(session)
        self.base_dir = Path(base_dir).expanduser().resolve() if base_dir else None

    def list_for_property(
        self,
        *,
        external_source_id: str,
        source_property_id: int,
    ) -> tuple[CatalogPropertyImage, ...]:
        rows = self.session.execute(
            text(
                "SELECT pi.record_id, pi.position, pi.image_url, pi.local_path "
                "FROM properties AS p "
                "INNER JOIN property_images AS pi ON pi.record_id = p.record_id "
                "WHERE p.external_source_id = :id "
                "AND p.source_property_id = :pid "
                "ORDER BY pi.position ASC"
            ),
            {"id": external_source_id, "pid": source_property_id},
        ).all()
        return tuple(
            CatalogPropertyImage(
                record_id=int(row.record_id),
                position=int(row.position or 0),
                image_url=str(row.image_url or ""),
                local_path=None if row.local_path is None else str(row.local_path),
            )
            for row in rows
        )

    def replace_images(
        self,
        record_id: int,
        downloaded_images: Iterable[tuple[int, str, Path | str | None]],
    ) -> None:
        self.session.execute(
            text("DELETE FROM property_images WHERE record_id = :record_id"),
            {"record_id": record_id},
        )
        for position, image_url, local_path in downloaded_images:
            local_value: str | None
            if local_path is None:
                local_value = None
            elif isinstance(local_path, Path):
                local_value = (
                    _relative_to_base(local_path, self.base_dir)
                    if self.base_dir is not None
                    else str(local_path)
                )
            else:
                local_value = str(local_path)
            self.session.execute(
                text(
                    "INSERT INTO property_images (record_id, position, image_url, local_path) "
                    "VALUES (:record_id, :position, :image_url, :local_path)"
                ),
                {
                    "record_id": record_id,
                    "position": position,
                    "image_url": image_url,
                    "local_path": local_value,
                },
            )


__all__ = ["PropertyImageRepository", "PropertyRepository"]
