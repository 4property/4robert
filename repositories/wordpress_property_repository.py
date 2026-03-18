from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeAlias

from config import DATABASE_FILENAME, PROPERTY_COLUMN_DEFINITIONS
from models.property import Property
DownloadedImage: TypeAlias = tuple[int, str, Path | None]


def _relative_to_base(path: Path, base_dir: Path) -> str:
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return str(path)


class WordpressPropertyRepository:
    def __init__(self, database_path: str | Path, base_dir: str | Path) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.base_dir = Path(base_dir).expanduser().resolve()
        self.connection = sqlite3.connect(self.database_path)
        self.connection.execute("PRAGMA foreign_keys = ON")

    def __enter__(self) -> "WordpressPropertyRepository":
        self.initialise()
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        if exc_type is None:
            self.connection.commit()
        else:
            self.connection.rollback()
        self.connection.close()

    def initialise(self) -> None:
        property_columns_sql = ",\n                ".join(
            f"{column} {definition}"
            for column, definition in PROPERTY_COLUMN_DEFINITIONS
        )

        self.connection.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS properties (
                {property_columns_sql}
            );

            CREATE TABLE IF NOT EXISTS property_images (
                property_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                image_url TEXT NOT NULL,
                local_path TEXT,
                PRIMARY KEY (property_id, position),
                FOREIGN KEY (property_id) REFERENCES properties(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_properties_slug
            ON properties (slug);
            """
        )
        self._ensure_property_columns()

    def _ensure_property_columns(self) -> None:
        existing_columns = {
            row[1]
            for row in self.connection.execute("PRAGMA table_info(properties)")
        }

        for column, definition in PROPERTY_COLUMN_DEFINITIONS:
            if column in existing_columns:
                continue
            self.connection.execute(
                f"ALTER TABLE properties ADD COLUMN {column} {definition}"
            )

    def _upsert_property_record(self, record: dict[str, Any]) -> None:
        columns = list(record.keys())
        placeholders = ", ".join("?" for _ in columns)
        update_clause = ",\n                ".join(
            f"{column} = excluded.{column}"
            for column in columns
            if column != "id"
        )

        self.connection.execute(
            f"""
            INSERT INTO properties (
                {", ".join(columns)}
            )
            VALUES ({placeholders})
            ON CONFLICT(id) DO UPDATE SET
                {update_clause}
            """,
            tuple(record[column] for column in columns),
        )

    def _replace_property_images(
        self,
        property_id: int,
        downloaded_images: list[DownloadedImage],
    ) -> None:
        self.connection.execute(
            "DELETE FROM property_images WHERE property_id = ?",
            (property_id,),
        )
        self.connection.executemany(
            """
            INSERT INTO property_images (
                property_id,
                position,
                image_url,
                local_path
            )
            VALUES (?, ?, ?, ?)
            """,
            [
                (
                    property_id,
                    position,
                    image_url,
                    None if local_path is None else _relative_to_base(local_path, self.base_dir),
                )
                for position, image_url, local_path in downloaded_images
            ],
        )

    def get_property_ids(self) -> set[int]:
        rows = self.connection.execute("SELECT id FROM properties")
        return {int(row[0]) for row in rows}

    def _save_property_record(
        self,
        property_item: Property,
        *,
        image_folder: str,
        downloaded_images: list[DownloadedImage],
    ) -> None:
        fetched_at = datetime.now(timezone.utc).isoformat()
        record = property_item.to_db_record(
            image_folder=image_folder,
            fetched_at=fetched_at,
        )
        self._upsert_property_record(record)
        self._replace_property_images(property_item.id, downloaded_images)

    def save_property_data(
        self,
        property_item: Property,
        *,
        image_folder: str = "",
    ) -> None:
        self._save_property_record(
            property_item,
            image_folder=image_folder,
            downloaded_images=[
                (position, image_url, None)
                for position, image_url in enumerate(property_item.image_urls, start=1)
            ],
        )

    def save_property_images(
        self,
        property_item: Property,
        property_dir: Path,
        downloaded_images: list[DownloadedImage],
    ) -> None:
        self._save_property_record(
            property_item,
            image_folder=_relative_to_base(property_dir, self.base_dir),
            downloaded_images=downloaded_images,
        )

    def save_downloaded_images(
        self,
        property_item: Property,
        property_dir: Path,
        downloaded_images: list[DownloadedImage],
    ) -> None:
        self.save_property_images(property_item, property_dir, downloaded_images)


__all__ = [
    "DATABASE_FILENAME",
    "DownloadedImage",
    "WordpressPropertyRepository",
]
