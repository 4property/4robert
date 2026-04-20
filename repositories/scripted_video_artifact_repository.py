from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from repositories.postgres.repository import PostgresRepositoryBase

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


class ScriptedVideoArtifactRepository(PostgresRepositoryBase):
    def __init__(
        self,
        database_path: str | Path | None,
        *,
        connection=None,
    ) -> None:
        super().__init__(database_path, connection=connection)

    def save_artifact(self, record: ScriptedVideoArtifactRecord) -> None:
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
            VALUES (
                :render_id,
                :site_id,
                :source_property_id,
                :property_slug,
                :render_profile,
                :status,
                :request_manifest_json,
                :request_manifest_path,
                :resolved_manifest_path,
                :media_path,
                :error_message,
                :created_at,
                :updated_at
            )
            ON CONFLICT (render_id) DO UPDATE SET
                property_slug = EXCLUDED.property_slug,
                render_profile = EXCLUDED.render_profile,
                status = EXCLUDED.status,
                request_manifest_json = EXCLUDED.request_manifest_json,
                request_manifest_path = EXCLUDED.request_manifest_path,
                resolved_manifest_path = EXCLUDED.resolved_manifest_path,
                media_path = EXCLUDED.media_path,
                error_message = EXCLUDED.error_message,
                updated_at = EXCLUDED.updated_at
            """,
            {
                "render_id": record.render_id,
                "site_id": record.site_id,
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
            WHERE render_id = :render_id
            """,
            {"render_id": render_id},
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
            WHERE site_id = :site_id
            AND source_property_id = :source_property_id
            ORDER BY created_at DESC, render_id DESC
            """,
            {
                "site_id": site_id,
                "source_property_id": source_property_id,
            },
        ).fetchall()
        return tuple(_row_to_scripted_video_artifact(row) for row in rows)


def _row_to_scripted_video_artifact(row) -> ScriptedVideoArtifactRecord:
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
