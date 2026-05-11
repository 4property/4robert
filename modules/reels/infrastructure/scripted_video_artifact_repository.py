"""Persistence for ScriptedVideoArtifact — output of `scripted_render` jobs."""

from __future__ import annotations

from sqlalchemy import text

from modules.reels.domain import ScriptedVideoArtifact
from shared.db.repository_base import ModuleRepository


def _isoformat(value: object | None) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def _row_to_artifact(row) -> ScriptedVideoArtifact:
    return ScriptedVideoArtifact(
        render_id=str(row.render_id),
        agency_id=str(row.agency_id or ""),
        ingestion_source_id=str(row.ingestion_source_id or ""),
        external_source_id=str(row.external_source_id or ""),
        source_property_id=int(row.source_property_id),
        property_slug=str(row.property_slug or ""),
        render_profile=str(row.render_profile or ""),
        status=str(row.status or ""),
        request_manifest_json=str(row.request_manifest_json or ""),
        request_manifest_path=str(row.request_manifest_path or ""),
        resolved_manifest_path=str(row.resolved_manifest_path or ""),
        media_path=str(row.media_path or ""),
        error_message=str(row.error_message or ""),
        created_at=_isoformat(row.created_at) or "",
        updated_at=_isoformat(row.updated_at) or "",
    )


class ScriptedVideoArtifactRepository(ModuleRepository):
    def save_artifact(self, record: ScriptedVideoArtifact) -> None:
        self.session.execute(
            text(
                "INSERT INTO scripted_video_artifacts ("
                "render_id, agency_id, ingestion_source_id, external_source_id, "
                "source_property_id, property_slug, render_profile, status, "
                "request_manifest_json, request_manifest_path, resolved_manifest_path, "
                "media_path, error_message, created_at, updated_at"
                ") VALUES ("
                ":render_id, :agency_id, :ingestion_source_id, :external_source_id, "
                ":source_property_id, :property_slug, :render_profile, :status, "
                ":request_manifest_json, :request_manifest_path, :resolved_manifest_path, "
                ":media_path, :error_message, :created_at, :updated_at"
                ") ON CONFLICT (render_id) DO UPDATE SET "
                "property_slug = EXCLUDED.property_slug, "
                "render_profile = EXCLUDED.render_profile, "
                "status = EXCLUDED.status, "
                "request_manifest_json = EXCLUDED.request_manifest_json, "
                "request_manifest_path = EXCLUDED.request_manifest_path, "
                "resolved_manifest_path = EXCLUDED.resolved_manifest_path, "
                "media_path = EXCLUDED.media_path, "
                "error_message = EXCLUDED.error_message, "
                "updated_at = EXCLUDED.updated_at"
            ),
            {
                "render_id": record.render_id,
                "agency_id": record.agency_id,
                "ingestion_source_id": record.ingestion_source_id,
                "external_source_id": record.external_source_id,
                "source_property_id": record.source_property_id,
                "property_slug": record.property_slug,
                "render_profile": record.render_profile,
                "status": record.status,
                "request_manifest_json": record.request_manifest_json,
                "request_manifest_path": record.request_manifest_path,
                "resolved_manifest_path": record.resolved_manifest_path,
                "media_path": record.media_path,
                "error_message": record.error_message,
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            },
        )

    def get_artifact(self, render_id: str) -> ScriptedVideoArtifact | None:
        row = self.session.execute(
            text(
                "SELECT render_id, agency_id, ingestion_source_id, "
                "external_source_id, source_property_id, property_slug, "
                "render_profile, status, request_manifest_json, "
                "request_manifest_path, resolved_manifest_path, media_path, "
                "error_message, created_at, updated_at "
                "FROM scripted_video_artifacts WHERE render_id = :render_id"
            ),
            {"render_id": render_id},
        ).first()
        return _row_to_artifact(row) if row is not None else None

    def list_artifacts_for_property(
        self,
        *,
        external_source_id: str,
        source_property_id: int,
    ) -> tuple[ScriptedVideoArtifact, ...]:
        rows = self.session.execute(
            text(
                "SELECT render_id, agency_id, ingestion_source_id, "
                "external_source_id, source_property_id, property_slug, "
                "render_profile, status, request_manifest_json, "
                "request_manifest_path, resolved_manifest_path, media_path, "
                "error_message, created_at, updated_at "
                "FROM scripted_video_artifacts "
                "WHERE external_source_id = :external_source_id "
                "AND source_property_id = :source_property_id "
                "ORDER BY created_at DESC, render_id DESC"
            ),
            {
                "external_source_id": external_source_id,
                "source_property_id": source_property_id,
            },
        ).all()
        return tuple(_row_to_artifact(row) for row in rows)


__all__ = ["ScriptedVideoArtifactRepository"]
