"""Persistence for the MediaRevision aggregate.

Append-only history of every render. The pointer to "the current one" lives
in `reels.current_revision_id`.
"""

from __future__ import annotations

from sqlalchemy import text

from modules.reels.domain import MediaRevision
from shared.db.repository_base import ModuleRepository


def _isoformat(value: object | None) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def _row_to_revision(row) -> MediaRevision:
    return MediaRevision(
        revision_id=str(row.revision_id),
        agency_id=str(row.agency_id or ""),
        ingestion_source_id=str(row.ingestion_source_id or ""),
        external_source_id=str(row.external_source_id or ""),
        source_property_id=int(row.source_property_id),
        artifact_kind=str(row.artifact_kind or ""),
        render_profile=str(row.render_profile or ""),
        render_template_id=str(row.render_template_id or "classic"),
        media_path=str(row.media_path or ""),
        metadata_path=str(row.metadata_path or ""),
        mime_type=str(row.mime_type or ""),
        content_fingerprint=str(row.content_fingerprint or ""),
        publish_target_fingerprint=str(row.publish_target_fingerprint or ""),
        workflow_state=str(row.workflow_state or ""),
        created_at=_isoformat(row.created_at) or "",
    )


class MediaRevisionRepository(ModuleRepository):
    def save_revision(self, record: MediaRevision) -> None:
        self.session.execute(
            text(
                "INSERT INTO media_revisions ("
                "revision_id, agency_id, ingestion_source_id, external_source_id, "
                "source_property_id, artifact_kind, render_profile, media_path, "
                "render_template_id, metadata_path, mime_type, content_fingerprint, "
                "publish_target_fingerprint, workflow_state, created_at"
                ") VALUES ("
                ":revision_id, :agency_id, :ingestion_source_id, :external_source_id, "
                ":source_property_id, :artifact_kind, :render_profile, :media_path, "
                ":render_template_id, :metadata_path, :mime_type, :content_fingerprint, "
                ":publish_target_fingerprint, :workflow_state, :created_at"
                ") ON CONFLICT (revision_id) DO UPDATE SET "
                "workflow_state = EXCLUDED.workflow_state, "
                "render_template_id = EXCLUDED.render_template_id, "
                "media_path = EXCLUDED.media_path, "
                "metadata_path = EXCLUDED.metadata_path, "
                "mime_type = EXCLUDED.mime_type"
            ),
            {
                "revision_id": record.revision_id,
                "agency_id": record.agency_id,
                "ingestion_source_id": record.ingestion_source_id,
                "external_source_id": record.external_source_id,
                "source_property_id": record.source_property_id,
                "artifact_kind": record.artifact_kind,
                "render_profile": record.render_profile,
                "render_template_id": record.render_template_id or "classic",
                "media_path": record.media_path,
                "metadata_path": record.metadata_path,
                "mime_type": record.mime_type,
                "content_fingerprint": record.content_fingerprint,
                "publish_target_fingerprint": record.publish_target_fingerprint,
                "workflow_state": record.workflow_state,
                "created_at": record.created_at,
            },
        )

    def get_revision(self, revision_id: str) -> MediaRevision | None:
        row = self.session.execute(
            text(
                "SELECT revision_id, agency_id, ingestion_source_id, "
                "external_source_id, source_property_id, artifact_kind, "
                "render_profile, render_template_id, media_path, metadata_path, mime_type, "
                "content_fingerprint, publish_target_fingerprint, workflow_state, "
                "created_at FROM media_revisions WHERE revision_id = :revision_id"
            ),
            {"revision_id": revision_id},
        ).first()
        return _row_to_revision(row) if row is not None else None

    def list_revisions(
        self,
        *,
        external_source_id: str,
        source_property_id: int,
    ) -> tuple[MediaRevision, ...]:
        rows = self.session.execute(
            text(
                "SELECT revision_id, agency_id, ingestion_source_id, "
                "external_source_id, source_property_id, artifact_kind, "
                "render_profile, render_template_id, media_path, metadata_path, mime_type, "
                "content_fingerprint, publish_target_fingerprint, workflow_state, "
                "created_at FROM media_revisions "
                "WHERE external_source_id = :external_source_id "
                "AND source_property_id = :source_property_id "
                "ORDER BY created_at DESC, revision_id DESC"
            ),
            {
                "external_source_id": external_source_id,
                "source_property_id": source_property_id,
            },
        ).all()
        return tuple(_row_to_revision(row) for row in rows)


__all__ = ["MediaRevisionRepository"]
