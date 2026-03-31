from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from repositories.sqlite_connection import create_sqlite_connection

MEDIA_REVISION_TABLE_NAME = "media_revisions"


@dataclass(frozen=True, slots=True)
class MediaRevisionRecord:
    revision_id: str
    site_id: str
    source_property_id: int
    artifact_kind: str
    render_profile: str
    media_path: str
    metadata_path: str
    mime_type: str
    content_fingerprint: str
    publish_target_fingerprint: str
    workflow_state: str
    created_at: str


def _build_media_revision_table_sql() -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {MEDIA_REVISION_TABLE_NAME} (
            revision_id TEXT PRIMARY KEY,
            site_id TEXT NOT NULL,
            source_property_id INTEGER NOT NULL,
            artifact_kind TEXT NOT NULL DEFAULT '',
            render_profile TEXT NOT NULL DEFAULT '',
            media_path TEXT NOT NULL DEFAULT '',
            metadata_path TEXT NOT NULL DEFAULT '',
            mime_type TEXT NOT NULL DEFAULT '',
            content_fingerprint TEXT NOT NULL DEFAULT '',
            publish_target_fingerprint TEXT NOT NULL DEFAULT '',
            workflow_state TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_media_revisions_site_property_created_at
        ON {MEDIA_REVISION_TABLE_NAME} (site_id, source_property_id, created_at DESC);
    """


class MediaRevisionRepository:
    def __init__(
        self,
        database_path: str | Path,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self._owns_connection = connection is None
        self.connection = connection or create_sqlite_connection(self.database_path)

    def __enter__(self) -> "MediaRevisionRepository":
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
        self.connection.executescript(_build_media_revision_table_sql())

    def save_media_revision(self, record: MediaRevisionRecord) -> None:
        created_at = record.created_at or datetime.now(timezone.utc).isoformat()
        self.connection.execute(
            f"""
            INSERT INTO {MEDIA_REVISION_TABLE_NAME} (
                revision_id,
                site_id,
                source_property_id,
                artifact_kind,
                render_profile,
                media_path,
                metadata_path,
                mime_type,
                content_fingerprint,
                publish_target_fingerprint,
                workflow_state,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(revision_id) DO UPDATE SET
                workflow_state = excluded.workflow_state,
                media_path = excluded.media_path,
                metadata_path = excluded.metadata_path,
                mime_type = excluded.mime_type
            """,
            (
                record.revision_id,
                record.site_id,
                record.source_property_id,
                record.artifact_kind,
                record.render_profile,
                record.media_path,
                record.metadata_path,
                record.mime_type,
                record.content_fingerprint,
                record.publish_target_fingerprint,
                record.workflow_state,
                created_at,
            ),
        )

    def get_media_revision(self, revision_id: str) -> MediaRevisionRecord | None:
        row = self.connection.execute(
            f"""
            SELECT
                revision_id,
                site_id,
                source_property_id,
                artifact_kind,
                render_profile,
                media_path,
                metadata_path,
                mime_type,
                content_fingerprint,
                publish_target_fingerprint,
                workflow_state,
                created_at
            FROM {MEDIA_REVISION_TABLE_NAME}
            WHERE revision_id = ?
            """,
            (revision_id,),
        ).fetchone()
        if row is None:
            return None
        return _row_to_media_revision(row)

    def list_media_revisions(
        self,
        *,
        site_id: str,
        source_property_id: int,
    ) -> tuple[MediaRevisionRecord, ...]:
        rows = self.connection.execute(
            f"""
            SELECT
                revision_id,
                site_id,
                source_property_id,
                artifact_kind,
                render_profile,
                media_path,
                metadata_path,
                mime_type,
                content_fingerprint,
                publish_target_fingerprint,
                workflow_state,
                created_at
            FROM {MEDIA_REVISION_TABLE_NAME}
            WHERE site_id = ?
            AND source_property_id = ?
            ORDER BY created_at DESC, revision_id DESC
            """,
            (site_id, source_property_id),
        ).fetchall()
        return tuple(_row_to_media_revision(row) for row in rows)


def _row_to_media_revision(row: sqlite3.Row) -> MediaRevisionRecord:
    return MediaRevisionRecord(
        revision_id=str(row["revision_id"]),
        site_id=str(row["site_id"]),
        source_property_id=int(row["source_property_id"]),
        artifact_kind=str(row["artifact_kind"] or ""),
        render_profile=str(row["render_profile"] or ""),
        media_path=str(row["media_path"] or ""),
        metadata_path=str(row["metadata_path"] or ""),
        mime_type=str(row["mime_type"] or ""),
        content_fingerprint=str(row["content_fingerprint"] or ""),
        publish_target_fingerprint=str(row["publish_target_fingerprint"] or ""),
        workflow_state=str(row["workflow_state"] or ""),
        created_at=str(row["created_at"] or ""),
    )


__all__ = [
    "MEDIA_REVISION_TABLE_NAME",
    "MediaRevisionRecord",
    "MediaRevisionRepository",
]
