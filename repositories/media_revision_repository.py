from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repositories.postgres.repository import PostgresRepositoryBase

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


class MediaRevisionRepository(PostgresRepositoryBase):
    def __init__(
        self,
        database_path: str | Path | None,
        *,
        connection=None,
    ) -> None:
        super().__init__(database_path, connection=connection)

    def save_media_revision(self, record: MediaRevisionRecord) -> None:
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
            VALUES (
                :revision_id,
                :site_id,
                :source_property_id,
                :artifact_kind,
                :render_profile,
                :media_path,
                :metadata_path,
                :mime_type,
                :content_fingerprint,
                :publish_target_fingerprint,
                :workflow_state,
                :created_at
            )
            ON CONFLICT (revision_id) DO UPDATE SET
                workflow_state = EXCLUDED.workflow_state,
                media_path = EXCLUDED.media_path,
                metadata_path = EXCLUDED.metadata_path,
                mime_type = EXCLUDED.mime_type
            """,
            {
                "revision_id": record.revision_id,
                "site_id": record.site_id,
                "source_property_id": record.source_property_id,
                "artifact_kind": record.artifact_kind,
                "render_profile": record.render_profile,
                "media_path": record.media_path,
                "metadata_path": record.metadata_path,
                "mime_type": record.mime_type,
                "content_fingerprint": record.content_fingerprint,
                "publish_target_fingerprint": record.publish_target_fingerprint,
                "workflow_state": record.workflow_state,
                "created_at": record.created_at,
            },
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
            WHERE revision_id = :revision_id
            """,
            {"revision_id": revision_id},
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
            WHERE site_id = :site_id
            AND source_property_id = :source_property_id
            ORDER BY created_at DESC, revision_id DESC
            """,
            {
                "site_id": site_id,
                "source_property_id": source_property_id,
            },
        ).fetchall()
        return tuple(_row_to_media_revision(row) for row in rows)


def _row_to_media_revision(row) -> MediaRevisionRecord:
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
