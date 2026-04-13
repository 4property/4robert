from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from repositories.sqlite_connection import create_sqlite_connection

SCRIPTED_VIDEO_ARTIFACT_TABLE_NAME = "scripted_video_artifacts"


@dataclass(frozen=True, slots=True)
class ScriptedVideoArtifactRecord:
    render_id: str
    site_id: str
    source_property_id: int
    property_slug: str
    render_profile: str
    status: str
    request_manifest_json: str
    request_manifest_path: str
    resolved_manifest_path: str
    media_path: str
    error_message: str
    created_at: str
    updated_at: str


def _build_scripted_video_artifact_table_sql() -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {SCRIPTED_VIDEO_ARTIFACT_TABLE_NAME} (
            render_id TEXT PRIMARY KEY,
            site_id TEXT NOT NULL,
            source_property_id INTEGER NOT NULL,
            property_slug TEXT NOT NULL DEFAULT '',
            render_profile TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            request_manifest_json TEXT NOT NULL DEFAULT '',
            request_manifest_path TEXT NOT NULL DEFAULT '',
            resolved_manifest_path TEXT NOT NULL DEFAULT '',
            media_path TEXT NOT NULL DEFAULT '',
            error_message TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_scripted_video_artifacts_site_property_created_at
        ON {SCRIPTED_VIDEO_ARTIFACT_TABLE_NAME} (site_id, source_property_id, created_at DESC);
    """


class ScriptedVideoArtifactRepository:
    def __init__(
        self,
        database_path: str | Path,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self._owns_connection = connection is None
        self.connection = connection or create_sqlite_connection(self.database_path)

    def __enter__(self) -> "ScriptedVideoArtifactRepository":
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
        self.connection.executescript(_build_scripted_video_artifact_table_sql())

    def save_artifact(self, record: ScriptedVideoArtifactRecord) -> None:
        now = datetime.now(timezone.utc).isoformat()
        created_at = record.created_at or now
        updated_at = now
        self.connection.execute(
            f"""
            INSERT INTO {SCRIPTED_VIDEO_ARTIFACT_TABLE_NAME} (
                render_id,
                site_id,
                source_property_id,
                property_slug,
                render_profile,
                status,
                request_manifest_json,
                request_manifest_path,
                resolved_manifest_path,
                media_path,
                error_message,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(render_id) DO UPDATE SET
                property_slug = excluded.property_slug,
                render_profile = excluded.render_profile,
                status = excluded.status,
                request_manifest_json = excluded.request_manifest_json,
                request_manifest_path = excluded.request_manifest_path,
                resolved_manifest_path = excluded.resolved_manifest_path,
                media_path = excluded.media_path,
                error_message = excluded.error_message,
                updated_at = excluded.updated_at
            """,
            (
                record.render_id,
                record.site_id,
                record.source_property_id,
                record.property_slug,
                record.render_profile,
                record.status,
                record.request_manifest_json,
                record.request_manifest_path,
                record.resolved_manifest_path,
                record.media_path,
                record.error_message,
                created_at,
                updated_at,
            ),
        )

    def get_artifact(self, render_id: str) -> ScriptedVideoArtifactRecord | None:
        row = self.connection.execute(
            f"""
            SELECT
                render_id,
                site_id,
                source_property_id,
                property_slug,
                render_profile,
                status,
                request_manifest_json,
                request_manifest_path,
                resolved_manifest_path,
                media_path,
                error_message,
                created_at,
                updated_at
            FROM {SCRIPTED_VIDEO_ARTIFACT_TABLE_NAME}
            WHERE render_id = ?
            """,
            (render_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_scripted_video_artifact(row)

    def list_artifacts_for_property(
        self,
        *,
        site_id: str,
        source_property_id: int,
    ) -> tuple[ScriptedVideoArtifactRecord, ...]:
        rows = self.connection.execute(
            f"""
            SELECT
                render_id,
                site_id,
                source_property_id,
                property_slug,
                render_profile,
                status,
                request_manifest_json,
                request_manifest_path,
                resolved_manifest_path,
                media_path,
                error_message,
                created_at,
                updated_at
            FROM {SCRIPTED_VIDEO_ARTIFACT_TABLE_NAME}
            WHERE site_id = ?
            AND source_property_id = ?
            ORDER BY created_at DESC, render_id DESC
            """,
            (site_id, source_property_id),
        ).fetchall()
        return tuple(_row_to_scripted_video_artifact(row) for row in rows)


def _row_to_scripted_video_artifact(row: sqlite3.Row) -> ScriptedVideoArtifactRecord:
    return ScriptedVideoArtifactRecord(
        render_id=str(row["render_id"]),
        site_id=str(row["site_id"]),
        source_property_id=int(row["source_property_id"]),
        property_slug=str(row["property_slug"] or ""),
        render_profile=str(row["render_profile"] or ""),
        status=str(row["status"] or ""),
        request_manifest_json=str(row["request_manifest_json"] or ""),
        request_manifest_path=str(row["request_manifest_path"] or ""),
        resolved_manifest_path=str(row["resolved_manifest_path"] or ""),
        media_path=str(row["media_path"] or ""),
        error_message=str(row["error_message"] or ""),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
    )


__all__ = [
    "SCRIPTED_VIDEO_ARTIFACT_TABLE_NAME",
    "ScriptedVideoArtifactRecord",
    "ScriptedVideoArtifactRepository",
]
