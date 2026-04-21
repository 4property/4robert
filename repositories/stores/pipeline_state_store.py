from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repositories.postgres.repository import PostgresRepositoryBase

PIPELINE_STATE_TABLE_NAME = "property_pipeline_state"


@dataclass(slots=True)
class PropertyPipelineState:
    agency_id: str
    wordpress_source_id: str
    site_id: str
    source_property_id: int
    content_fingerprint: str
    content_snapshot_json: str
    publish_target_fingerprint: str
    publish_target_snapshot_json: str
    selected_image_folder: str
    artifact_kind: str
    local_artifact_path: str
    local_metadata_path: str
    render_profile: str
    local_manifest_path: str
    local_video_path: str
    render_status: str
    publish_status: str
    workflow_state: str
    publish_details_json: str
    current_revision_id: str
    last_published_location_id: str
    created_at: str
    updated_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _relative_to_base(path: Path, base_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(base_dir))
    except ValueError:
        return str(path.resolve())


def build_empty_pipeline_state(site_id: str, source_property_id: int) -> PropertyPipelineState:
    return PropertyPipelineState(
        agency_id="",
        wordpress_source_id="",
        site_id=site_id,
        source_property_id=source_property_id,
        content_fingerprint="",
        content_snapshot_json="",
        publish_target_fingerprint="",
        publish_target_snapshot_json="",
        selected_image_folder="",
        artifact_kind="",
        local_artifact_path="",
        local_metadata_path="",
        render_profile="",
        local_manifest_path="",
        local_video_path="",
        render_status="",
        publish_status="",
        workflow_state="",
        publish_details_json="",
        current_revision_id="",
        last_published_location_id="",
        created_at="",
        updated_at="",
    )


class PipelineStateStore(PostgresRepositoryBase):
    def __init__(
        self,
        database_locator: str | Path | None,
        base_dir: str | Path,
        *,
        connection=None,
    ) -> None:
        super().__init__(database_locator, connection=connection)
        self.base_dir = Path(base_dir).expanduser().resolve()

    def get_property_pipeline_state(
        self,
        *,
        site_id: str,
        source_property_id: int,
    ) -> PropertyPipelineState | None:
        row = self.connection.execute(
            f"""
            SELECT
                agency_id,
                wordpress_source_id,
                site_id,
                source_property_id,
                content_fingerprint,
                content_snapshot_json,
                publish_target_fingerprint,
                publish_target_snapshot_json,
                selected_image_folder,
                artifact_kind,
                local_artifact_path,
                local_metadata_path,
                render_profile,
                local_manifest_path,
                local_video_path,
                render_status,
                publish_status,
                workflow_state,
                publish_details_json,
                current_revision_id,
                last_published_location_id,
                created_at,
                updated_at
            FROM {PIPELINE_STATE_TABLE_NAME}
            WHERE site_id = :site_id
            AND source_property_id = :source_property_id
            """,
            {
                "site_id": site_id,
                "source_property_id": source_property_id,
            },
        ).fetchone()
        if row is None:
            return None

        return PropertyPipelineState(
            agency_id=str(row["agency_id"] or ""),
            wordpress_source_id=str(row["wordpress_source_id"] or ""),
            site_id=str(row["site_id"]),
            source_property_id=int(row["source_property_id"]),
            content_fingerprint=str(row["content_fingerprint"] or ""),
            content_snapshot_json=str(row["content_snapshot_json"] or ""),
            publish_target_fingerprint=str(row["publish_target_fingerprint"] or ""),
            publish_target_snapshot_json=str(row["publish_target_snapshot_json"] or ""),
            selected_image_folder=str(row["selected_image_folder"] or ""),
            artifact_kind=str(row["artifact_kind"] or ""),
            local_artifact_path=str(row["local_artifact_path"] or row["local_video_path"] or ""),
            local_metadata_path=str(
                row["local_metadata_path"] or row["local_manifest_path"] or ""
            ),
            render_profile=str(row["render_profile"] or ""),
            local_manifest_path=str(row["local_manifest_path"] or ""),
            local_video_path=str(row["local_video_path"] or ""),
            render_status=str(row["render_status"] or ""),
            publish_status=str(row["publish_status"] or ""),
            workflow_state=str(row["workflow_state"] or ""),
            publish_details_json=str(row["publish_details_json"] or ""),
            current_revision_id=str(row["current_revision_id"] or ""),
            last_published_location_id=str(row["last_published_location_id"] or ""),
            created_at=str(row["created_at"] or ""),
            updated_at=str(row["updated_at"] or ""),
        )

    def save_property_pipeline_state(self, state: PropertyPipelineState) -> None:
        now = _now_iso()
        created_at = state.created_at or now
        updated_at = now
        self.connection.execute(
            f"""
            INSERT INTO {PIPELINE_STATE_TABLE_NAME} (
                agency_id,
                wordpress_source_id,
                site_id,
                source_property_id,
                content_fingerprint,
                content_snapshot_json,
                publish_target_fingerprint,
                publish_target_snapshot_json,
                selected_image_folder,
                artifact_kind,
                local_artifact_path,
                local_metadata_path,
                render_profile,
                local_manifest_path,
                local_video_path,
                render_status,
                publish_status,
                workflow_state,
                publish_details_json,
                current_revision_id,
                last_published_location_id,
                created_at,
                updated_at
            )
            VALUES (
                :agency_id,
                :wordpress_source_id,
                :site_id,
                :source_property_id,
                :content_fingerprint,
                :content_snapshot_json,
                :publish_target_fingerprint,
                :publish_target_snapshot_json,
                :selected_image_folder,
                :artifact_kind,
                :local_artifact_path,
                :local_metadata_path,
                :render_profile,
                :local_manifest_path,
                :local_video_path,
                :render_status,
                :publish_status,
                :workflow_state,
                :publish_details_json,
                :current_revision_id,
                :last_published_location_id,
                :created_at,
                :updated_at
            )
            ON CONFLICT (site_id, source_property_id) DO UPDATE SET
                agency_id = EXCLUDED.agency_id,
                wordpress_source_id = EXCLUDED.wordpress_source_id,
                content_fingerprint = EXCLUDED.content_fingerprint,
                content_snapshot_json = EXCLUDED.content_snapshot_json,
                publish_target_fingerprint = EXCLUDED.publish_target_fingerprint,
                publish_target_snapshot_json = EXCLUDED.publish_target_snapshot_json,
                selected_image_folder = EXCLUDED.selected_image_folder,
                artifact_kind = EXCLUDED.artifact_kind,
                local_artifact_path = EXCLUDED.local_artifact_path,
                local_metadata_path = EXCLUDED.local_metadata_path,
                render_profile = EXCLUDED.render_profile,
                local_manifest_path = EXCLUDED.local_manifest_path,
                local_video_path = EXCLUDED.local_video_path,
                render_status = EXCLUDED.render_status,
                publish_status = EXCLUDED.publish_status,
                workflow_state = EXCLUDED.workflow_state,
                publish_details_json = EXCLUDED.publish_details_json,
                current_revision_id = EXCLUDED.current_revision_id,
                last_published_location_id = EXCLUDED.last_published_location_id,
                updated_at = EXCLUDED.updated_at
            """,
            {
                "agency_id": state.agency_id,
                "wordpress_source_id": state.wordpress_source_id,
                "site_id": state.site_id,
                "source_property_id": state.source_property_id,
                "content_fingerprint": state.content_fingerprint,
                "content_snapshot_json": state.content_snapshot_json,
                "publish_target_fingerprint": state.publish_target_fingerprint,
                "publish_target_snapshot_json": state.publish_target_snapshot_json,
                "selected_image_folder": state.selected_image_folder,
                "artifact_kind": state.artifact_kind,
                "local_artifact_path": state.local_artifact_path,
                "local_metadata_path": state.local_metadata_path,
                "render_profile": state.render_profile,
                "local_manifest_path": state.local_manifest_path,
                "local_video_path": state.local_video_path,
                "render_status": state.render_status,
                "publish_status": state.publish_status,
                "workflow_state": state.workflow_state,
                "publish_details_json": state.publish_details_json,
                "current_revision_id": state.current_revision_id,
                "last_published_location_id": state.last_published_location_id,
                "created_at": created_at,
                "updated_at": updated_at,
            },
        )

    def update_social_publish_status(
        self,
        *,
        agency_id: str,
        wordpress_source_id: str,
        site_id: str,
        source_property_id: int,
        status: str,
        details: dict[str, Any] | None = None,
        last_published_location_id: str = "",
    ) -> None:
        details_json = ""
        if details:
            details_json = json.dumps(details, ensure_ascii=False, sort_keys=True)
        state = self.get_property_pipeline_state(
            site_id=site_id,
            source_property_id=source_property_id,
        ) or build_empty_pipeline_state(site_id, source_property_id)
        self.save_property_pipeline_state(
            PropertyPipelineState(
                agency_id=state.agency_id or agency_id,
                wordpress_source_id=state.wordpress_source_id or wordpress_source_id,
                site_id=state.site_id,
                source_property_id=state.source_property_id,
                content_fingerprint=state.content_fingerprint,
                content_snapshot_json=state.content_snapshot_json,
                publish_target_fingerprint=state.publish_target_fingerprint,
                publish_target_snapshot_json=state.publish_target_snapshot_json,
                selected_image_folder=state.selected_image_folder,
                artifact_kind=state.artifact_kind,
                local_artifact_path=state.local_artifact_path,
                local_metadata_path=state.local_metadata_path,
                render_profile=state.render_profile,
                local_manifest_path=state.local_manifest_path,
                local_video_path=state.local_video_path,
                render_status=state.render_status,
                publish_status=status,
                workflow_state=state.workflow_state,
                publish_details_json=details_json,
                current_revision_id=state.current_revision_id,
                last_published_location_id=(
                    last_published_location_id or state.last_published_location_id
                ),
                created_at=state.created_at,
                updated_at=state.updated_at,
            )
        )

    def update_workflow_state(
        self,
        *,
        agency_id: str,
        wordpress_source_id: str,
        site_id: str,
        source_property_id: int,
        workflow_state: str,
        current_revision_id: str | None = None,
    ) -> None:
        state = self.get_property_pipeline_state(
            site_id=site_id,
            source_property_id=source_property_id,
        ) or build_empty_pipeline_state(site_id, source_property_id)
        self.save_property_pipeline_state(
            PropertyPipelineState(
                agency_id=state.agency_id or agency_id,
                wordpress_source_id=state.wordpress_source_id or wordpress_source_id,
                site_id=state.site_id,
                source_property_id=state.source_property_id,
                content_fingerprint=state.content_fingerprint,
                content_snapshot_json=state.content_snapshot_json,
                publish_target_fingerprint=state.publish_target_fingerprint,
                publish_target_snapshot_json=state.publish_target_snapshot_json,
                selected_image_folder=state.selected_image_folder,
                artifact_kind=state.artifact_kind,
                local_artifact_path=state.local_artifact_path,
                local_metadata_path=state.local_metadata_path,
                render_profile=state.render_profile,
                local_manifest_path=state.local_manifest_path,
                local_video_path=state.local_video_path,
                render_status=state.render_status,
                publish_status=state.publish_status,
                workflow_state=workflow_state,
                publish_details_json=state.publish_details_json,
                current_revision_id=(
                    state.current_revision_id
                    if current_revision_id is None
                    else current_revision_id
                ),
                last_published_location_id=state.last_published_location_id,
                created_at=state.created_at,
                updated_at=state.updated_at,
            )
        )

    def save_local_artifacts(
        self,
        *,
        agency_id: str,
        wordpress_source_id: str,
        site_id: str,
        source_property_id: int,
        artifact_kind: str = "reel_video",
        artifact_path: Path | None = None,
        metadata_path: Path | None = None,
        render_profile: str = "",
        current_revision_id: str = "",
        manifest_path: Path | None = None,
        video_path: Path | None = None,
    ) -> None:
        resolved_artifact_path = artifact_path or video_path
        resolved_metadata_path = metadata_path or manifest_path
        if resolved_artifact_path is None:
            raise TypeError("save_local_artifacts requires an artifact_path.")
        state = self.get_property_pipeline_state(
            site_id=site_id,
            source_property_id=source_property_id,
        ) or build_empty_pipeline_state(site_id, source_property_id)
        self.save_property_pipeline_state(
            PropertyPipelineState(
                agency_id=state.agency_id or agency_id,
                wordpress_source_id=state.wordpress_source_id or wordpress_source_id,
                site_id=state.site_id,
                source_property_id=state.source_property_id,
                content_fingerprint=state.content_fingerprint,
                content_snapshot_json=state.content_snapshot_json,
                publish_target_fingerprint=state.publish_target_fingerprint,
                publish_target_snapshot_json=state.publish_target_snapshot_json,
                selected_image_folder=state.selected_image_folder,
                artifact_kind=artifact_kind,
                local_artifact_path=_relative_to_base(resolved_artifact_path, self.base_dir),
                local_metadata_path=(
                    ""
                    if resolved_metadata_path is None
                    else _relative_to_base(resolved_metadata_path, self.base_dir)
                ),
                render_profile=render_profile,
                local_manifest_path=(
                    _relative_to_base(resolved_metadata_path, self.base_dir)
                    if artifact_kind == "reel_video" and resolved_metadata_path is not None
                    else ""
                ),
                local_video_path=(
                    _relative_to_base(resolved_artifact_path, self.base_dir)
                    if artifact_kind == "reel_video"
                    else ""
                ),
                render_status="completed",
                publish_status=state.publish_status,
                workflow_state="rendered",
                publish_details_json=state.publish_details_json,
                current_revision_id=current_revision_id or state.current_revision_id,
                last_published_location_id=state.last_published_location_id,
                created_at=state.created_at,
                updated_at=state.updated_at,
            )
        )


__all__ = [
    "PIPELINE_STATE_TABLE_NAME",
    "PipelineStateStore",
    "PropertyPipelineState",
    "build_empty_pipeline_state",
]
