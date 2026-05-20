"""Persistence for the ReelState aggregate.

The `reels` table (was `property_pipeline_state`) holds the latest workflow
state per `(external_source_id, source_property_id)` pair. JSONB columns
hold structured snapshots; previous TEXT-JSON columns are gone.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import text

from modules.reels.domain import ReelState, build_empty_reel_state
from shared.db.repository_base import ModuleRepository, utcnow


# Feature 41: ``save_local_artifacts`` accepts an optional
# ``auto_subtitles_snapshot`` kwarg. ``None`` is a legitimate value
# ("clear the snapshot"), so we cannot use ``None`` to mean "do not
# touch the existing value". A sentinel object disambiguates the two
# semantics: callers omit the kwarg (sentinel default) to preserve the
# existing value, and pass an explicit ``list`` / ``None`` to update.
class _Unset:
    """Sentinel type for the ``auto_subtitles_snapshot`` kwarg."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover — debug only
        return "<UNSET>"


_UNSET = _Unset()


def _isoformat(value: object | None) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def _jsonb_to_mapping(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(bytes(raw).decode("utf-8"))
    if isinstance(raw, str):
        return json.loads(raw) if raw.strip() else {}
    return dict(raw)


def _mapping_to_jsonb(value: Mapping[str, Any] | None) -> str:
    return json.dumps(dict(value or {}), separators=(",", ":"))


def _override_to_jsonb_param(value: Mapping[str, Any] | None) -> str | None:
    """Serialize the optional ``descriptions_override`` to a JSONB-ready
    bind parameter.

    Returns ``None`` (mapped to SQL ``NULL``) when the value is ``None``
    or an empty mapping. Otherwise returns a compact JSON string. The
    SQL caster uses ``CAST(:descriptions_override AS jsonb)`` which
    treats a ``NULL`` parameter as a literal SQL ``NULL`` rather than
    the string ``"null"`` — that matches the column's ``nullable=True``
    contract and lets ``None`` mean "no override" everywhere.
    """
    if value is None:
        return None
    coerced = dict(value)
    if not coerced:
        return None
    return json.dumps(coerced, separators=(",", ":"))


def _jsonb_to_optional_mapping(raw: Any) -> dict[str, Any] | None:
    """Decode the optional ``descriptions_override`` JSONB column.

    Mirrors :func:`_jsonb_to_mapping` but returns ``None`` for SQL NULL /
    empty payloads so the domain dataclass can preserve the
    "no override" sentinel.
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        return dict(raw) if raw else None
    if isinstance(raw, (bytes, bytearray)):
        text_value = bytes(raw).decode("utf-8")
        return _jsonb_to_optional_mapping(text_value)
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return None
        parsed = json.loads(stripped)
        if not parsed:
            return None
        return dict(parsed)
    parsed = dict(raw)
    return parsed if parsed else None


def _jsonb_to_optional_list(raw: Any) -> list[dict[str, Any]] | None:
    """Decode the optional ``photos_override`` JSONB column (feature 35).

    Returns ``None`` for SQL NULL, the empty list ``[]`` or any payload
    that is not a non-empty list. Otherwise returns a fresh list of
    dicts with shallow-coerced entries so downstream code can safely
    mutate it without leaking back into the SQLAlchemy row state.
    """
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        text_value = bytes(raw).decode("utf-8")
        return _jsonb_to_optional_list(text_value)
    if isinstance(raw, str):
        stripped = raw.strip()
        if not stripped:
            return None
        parsed = json.loads(stripped)
        return _jsonb_to_optional_list(parsed)
    if isinstance(raw, list):
        coerced: list[dict[str, Any]] = []
        for entry in raw:
            if isinstance(entry, dict):
                coerced.append(dict(entry))
        return coerced or None
    return None


def _photos_override_to_jsonb_param(
    value: list[dict[str, Any]] | None,
) -> str | None:
    """Serialize the optional ``photos_override`` to a JSONB bind param.

    Returns ``None`` (mapped to SQL ``NULL``) when the override is
    cleared (``None`` or empty list). Otherwise returns the compact JSON
    text. The SQL caster uses ``CAST(:photos_override AS jsonb)`` which
    treats a ``NULL`` parameter as a literal SQL ``NULL`` rather than
    the string ``"null"`` — matching the column's ``nullable=True``
    contract.
    """
    if not value:
        return None
    return json.dumps(list(value), separators=(",", ":"))


def _subtitles_override_to_jsonb_param(
    value: list[dict[str, Any]] | None,
) -> str | None:
    """Serialize the optional ``subtitles_override`` to a JSONB bind param.

    Feature 36: the column stores a list of cue dicts
    (``{"index", "text", "in_seconds", "out_seconds"}``). Returns
    ``None`` (mapped to SQL ``NULL``) when the override is cleared
    (``None`` or empty list); otherwise returns the compact JSON text.
    Same shape as :func:`_photos_override_to_jsonb_param` so the
    persistence contract stays homogeneous across overrides.
    """
    if not value:
        return None
    return json.dumps(list(value), separators=(",", ":"))


def _manifest_override_to_jsonb_param(
    value: list[dict[str, Any]] | None,
) -> str | None:
    """Serialize the optional ``manifest_override`` to a JSONB bind param.

    Feature 37: the column stores a list of slide dicts
    (``{"slide_id", "position", "duration_seconds", "kind", ...}``).
    Returns ``None`` (mapped to SQL ``NULL``) when the override is
    cleared (``None`` or empty list); otherwise returns the compact
    JSON text. Same shape as the other override params so the
    persistence contract stays homogeneous.
    """
    if not value:
        return None
    return json.dumps(list(value), separators=(",", ":"))


def _auto_subtitles_snapshot_to_jsonb_param(
    value: list[dict[str, Any]] | None,
) -> str | None:
    """Serialize the optional ``auto_subtitles_snapshot`` to a JSONB bind param.

    Feature 41: the column stores the most recent autoCaptions cues the
    renderer produced (the same shape as ``subtitles_override``).
    Returns ``None`` (mapped to SQL ``NULL``) when the snapshot is
    unset (``None`` or empty list); otherwise returns the compact JSON
    text. Same shape as the other JSONB params so the persistence
    contract stays homogeneous.
    """
    if not value:
        return None
    return json.dumps(list(value), separators=(",", ":"))


def _row_to_reel_state(row) -> ReelState:
    return ReelState(
        agency_id=str(row.agency_id or ""),
        ingestion_source_id=str(row.ingestion_source_id or ""),
        external_source_id=str(row.external_source_id),
        source_property_id=int(row.source_property_id),
        content_fingerprint=str(row.content_fingerprint or ""),
        content_snapshot=_jsonb_to_mapping(row.content_snapshot),
        publish_target_fingerprint=str(row.publish_target_fingerprint or ""),
        publish_target_snapshot=_jsonb_to_mapping(row.publish_target_snapshot),
        render_template_id=str(row.render_template_id or "classic"),
        selected_image_folder=str(row.selected_image_folder or ""),
        artifact_kind=str(row.artifact_kind or ""),
        local_artifact_path=str(row.local_artifact_path or ""),
        local_metadata_path=str(row.local_metadata_path or ""),
        render_profile=str(row.render_profile or ""),
        local_manifest_path=str(row.local_manifest_path or ""),
        local_video_path=str(row.local_video_path or ""),
        render_status=str(row.render_status or ""),
        publish_status=str(row.publish_status or ""),
        workflow_state=str(row.workflow_state or ""),
        publish_details=_jsonb_to_mapping(row.publish_details),
        current_revision_id=str(row.current_revision_id or ""),
        last_published_provider_external_id=str(
            row.last_published_provider_external_id or ""
        ),
        created_at=_isoformat(row.created_at) or "",
        updated_at=_isoformat(row.updated_at) or "",
        descriptions_override=_jsonb_to_optional_mapping(
            getattr(row, "descriptions_override", None)
        ),
        music_id=(
            str(row.music_id)
            if getattr(row, "music_id", None)
            else None
        ),
        photos_override=_jsonb_to_optional_list(
            getattr(row, "photos_override", None)
        ),
        subtitles_override=_jsonb_to_optional_list(
            getattr(row, "subtitles_override", None)
        ),
        manifest_override=_jsonb_to_optional_list(
            getattr(row, "manifest_override", None)
        ),
        auto_subtitles_snapshot=_jsonb_to_optional_list(
            getattr(row, "auto_subtitles_snapshot", None)
        ),
    )


def _relative_to_base(path: Path, base_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(base_dir))
    except ValueError:
        return str(path.resolve())


_REEL_COLUMNS = (
    "agency_id, ingestion_source_id, external_source_id, source_property_id, "
    "content_fingerprint, content_snapshot, publish_target_fingerprint, "
    "publish_target_snapshot, descriptions_override, music_id, photos_override, "
    "subtitles_override, manifest_override, auto_subtitles_snapshot, "
    "render_template_id, "
    "selected_image_folder, artifact_kind, "
    "local_artifact_path, local_metadata_path, render_profile, "
    "local_manifest_path, local_video_path, render_status, publish_status, "
    "workflow_state, publish_details, current_revision_id, "
    "last_published_provider_external_id, created_at, updated_at"
)


class ReelStateRepository(ModuleRepository):
    """The current per-property reel state. PK on (external_source_id, source_property_id)."""

    def __init__(self, session, base_dir: str | Path | None = None) -> None:
        super().__init__(session)
        self.base_dir = Path(base_dir).expanduser().resolve() if base_dir else None

    def get(
        self, *, external_source_id: str, source_property_id: int
    ) -> ReelState | None:
        row = self.session.execute(
            text(
                f"SELECT {_REEL_COLUMNS} FROM reels "
                "WHERE external_source_id = :external_source_id "
                "AND source_property_id = :source_property_id"
            ),
            {
                "external_source_id": external_source_id,
                "source_property_id": source_property_id,
            },
        ).first()
        return _row_to_reel_state(row) if row is not None else None

    def save(self, state: ReelState) -> None:
        now = utcnow().isoformat()
        created_at = state.created_at or now
        updated_at = now
        self.session.execute(
            text(
                "INSERT INTO reels ("
                f"{_REEL_COLUMNS}"
                ") VALUES ("
                ":agency_id, :ingestion_source_id, :external_source_id, "
                ":source_property_id, :content_fingerprint, "
                "CAST(:content_snapshot AS jsonb), :publish_target_fingerprint, "
                "CAST(:publish_target_snapshot AS jsonb), "
                "CAST(:descriptions_override AS jsonb), :music_id, "
                "CAST(:photos_override AS jsonb), "
                "CAST(:subtitles_override AS jsonb), "
                "CAST(:manifest_override AS jsonb), "
                "CAST(:auto_subtitles_snapshot AS jsonb), "
                ":render_template_id, "
                ":selected_image_folder, :artifact_kind, :local_artifact_path, "
                ":local_metadata_path, "
                ":render_profile, :local_manifest_path, :local_video_path, "
                ":render_status, :publish_status, :workflow_state, "
                "CAST(:publish_details AS jsonb), :current_revision_id, "
                ":last_published_provider_external_id, :created_at, :updated_at"
                ") ON CONFLICT (external_source_id, source_property_id) DO UPDATE SET "
                "agency_id = EXCLUDED.agency_id, "
                "ingestion_source_id = EXCLUDED.ingestion_source_id, "
                "content_fingerprint = EXCLUDED.content_fingerprint, "
                "content_snapshot = EXCLUDED.content_snapshot, "
                "publish_target_fingerprint = EXCLUDED.publish_target_fingerprint, "
                "publish_target_snapshot = EXCLUDED.publish_target_snapshot, "
                "descriptions_override = EXCLUDED.descriptions_override, "
                "music_id = EXCLUDED.music_id, "
                "photos_override = EXCLUDED.photos_override, "
                "subtitles_override = EXCLUDED.subtitles_override, "
                "manifest_override = EXCLUDED.manifest_override, "
                "auto_subtitles_snapshot = EXCLUDED.auto_subtitles_snapshot, "
                "render_template_id = EXCLUDED.render_template_id, "
                "selected_image_folder = EXCLUDED.selected_image_folder, "
                "artifact_kind = EXCLUDED.artifact_kind, "
                "local_artifact_path = EXCLUDED.local_artifact_path, "
                "local_metadata_path = EXCLUDED.local_metadata_path, "
                "render_profile = EXCLUDED.render_profile, "
                "local_manifest_path = EXCLUDED.local_manifest_path, "
                "local_video_path = EXCLUDED.local_video_path, "
                "render_status = EXCLUDED.render_status, "
                "publish_status = EXCLUDED.publish_status, "
                "workflow_state = EXCLUDED.workflow_state, "
                "publish_details = EXCLUDED.publish_details, "
                "current_revision_id = EXCLUDED.current_revision_id, "
                "last_published_provider_external_id = "
                "EXCLUDED.last_published_provider_external_id, "
                "updated_at = EXCLUDED.updated_at"
            ),
            {
                "agency_id": state.agency_id,
                "ingestion_source_id": state.ingestion_source_id,
                "external_source_id": state.external_source_id,
                "source_property_id": state.source_property_id,
                "content_fingerprint": state.content_fingerprint,
                "content_snapshot": _mapping_to_jsonb(state.content_snapshot),
                "publish_target_fingerprint": state.publish_target_fingerprint,
                "publish_target_snapshot": _mapping_to_jsonb(state.publish_target_snapshot),
                "descriptions_override": _override_to_jsonb_param(
                    state.descriptions_override
                ),
                # Feature 25: empty string is treated as ``None`` so the
                # repository always writes SQL NULL when the override is
                # cleared (matches the FK ``ON DELETE SET NULL`` contract).
                "music_id": (state.music_id or None),
                "photos_override": _photos_override_to_jsonb_param(
                    state.photos_override
                ),
                "subtitles_override": _subtitles_override_to_jsonb_param(
                    state.subtitles_override
                ),
                "manifest_override": _manifest_override_to_jsonb_param(
                    state.manifest_override
                ),
                "auto_subtitles_snapshot": _auto_subtitles_snapshot_to_jsonb_param(
                    state.auto_subtitles_snapshot
                ),
                "render_template_id": state.render_template_id or "classic",
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
                "publish_details": _mapping_to_jsonb(state.publish_details),
                "current_revision_id": state.current_revision_id,
                "last_published_provider_external_id": state.last_published_provider_external_id,
                "created_at": created_at,
                "updated_at": updated_at,
            },
        )

    def update_publish_status(
        self,
        *,
        agency_id: str,
        ingestion_source_id: str,
        external_source_id: str,
        source_property_id: int,
        status: str,
        details: Mapping[str, Any] | None = None,
        last_published_provider_external_id: str = "",
    ) -> None:
        existing = self.get(
            external_source_id=external_source_id,
            source_property_id=source_property_id,
        ) or build_empty_reel_state(
            external_source_id=external_source_id,
            source_property_id=source_property_id,
        )
        merged_details = dict(details or {})
        self.save(
            ReelState(
                agency_id=existing.agency_id or agency_id,
                ingestion_source_id=existing.ingestion_source_id or ingestion_source_id,
                external_source_id=existing.external_source_id,
                source_property_id=existing.source_property_id,
                content_fingerprint=existing.content_fingerprint,
                content_snapshot=existing.content_snapshot,
                publish_target_fingerprint=existing.publish_target_fingerprint,
                publish_target_snapshot=existing.publish_target_snapshot,
                render_template_id=existing.render_template_id,
                selected_image_folder=existing.selected_image_folder,
                artifact_kind=existing.artifact_kind,
                local_artifact_path=existing.local_artifact_path,
                local_metadata_path=existing.local_metadata_path,
                render_profile=existing.render_profile,
                local_manifest_path=existing.local_manifest_path,
                local_video_path=existing.local_video_path,
                render_status=existing.render_status,
                publish_status=status,
                workflow_state=existing.workflow_state,
                publish_details=merged_details,
                current_revision_id=existing.current_revision_id,
                last_published_provider_external_id=(
                    last_published_provider_external_id
                    or existing.last_published_provider_external_id
                ),
                created_at=existing.created_at,
                updated_at=existing.updated_at,
                descriptions_override=existing.descriptions_override,
                music_id=existing.music_id,
                photos_override=existing.photos_override,
                subtitles_override=existing.subtitles_override,
                manifest_override=existing.manifest_override,
                auto_subtitles_snapshot=existing.auto_subtitles_snapshot,
            )
        )

    def update_workflow_state(
        self,
        *,
        agency_id: str,
        ingestion_source_id: str,
        external_source_id: str,
        source_property_id: int,
        workflow_state: str,
        current_revision_id: str | None = None,
    ) -> None:
        existing = self.get(
            external_source_id=external_source_id,
            source_property_id=source_property_id,
        ) or build_empty_reel_state(
            external_source_id=external_source_id,
            source_property_id=source_property_id,
        )
        self.save(
            ReelState(
                agency_id=existing.agency_id or agency_id,
                ingestion_source_id=existing.ingestion_source_id or ingestion_source_id,
                external_source_id=existing.external_source_id,
                source_property_id=existing.source_property_id,
                content_fingerprint=existing.content_fingerprint,
                content_snapshot=existing.content_snapshot,
                publish_target_fingerprint=existing.publish_target_fingerprint,
                publish_target_snapshot=existing.publish_target_snapshot,
                render_template_id=existing.render_template_id,
                selected_image_folder=existing.selected_image_folder,
                artifact_kind=existing.artifact_kind,
                local_artifact_path=existing.local_artifact_path,
                local_metadata_path=existing.local_metadata_path,
                render_profile=existing.render_profile,
                local_manifest_path=existing.local_manifest_path,
                local_video_path=existing.local_video_path,
                render_status=existing.render_status,
                publish_status=existing.publish_status,
                workflow_state=workflow_state,
                publish_details=existing.publish_details,
                current_revision_id=(
                    existing.current_revision_id
                    if current_revision_id is None
                    else current_revision_id
                ),
                last_published_provider_external_id=existing.last_published_provider_external_id,
                created_at=existing.created_at,
                updated_at=existing.updated_at,
                descriptions_override=existing.descriptions_override,
                music_id=existing.music_id,
                photos_override=existing.photos_override,
                subtitles_override=existing.subtitles_override,
                manifest_override=existing.manifest_override,
                auto_subtitles_snapshot=existing.auto_subtitles_snapshot,
            )
        )

    def save_local_artifacts(
        self,
        *,
        agency_id: str,
        ingestion_source_id: str,
        external_source_id: str,
        source_property_id: int,
        artifact_kind: str = "reel_video",
        artifact_path: Path | None = None,
        metadata_path: Path | None = None,
        render_profile: str = "",
        current_revision_id: str = "",
        manifest_path: Path | None = None,
        video_path: Path | None = None,
        auto_subtitles_snapshot: list[dict[str, Any]] | None | _Unset = _UNSET,
    ) -> None:
        if self.base_dir is None:
            raise RuntimeError(
                "ReelStateRepository.save_local_artifacts needs a base_dir."
            )
        resolved_artifact_path = artifact_path or video_path
        resolved_metadata_path = metadata_path or manifest_path
        if resolved_artifact_path is None:
            raise TypeError("save_local_artifacts requires an artifact_path.")
        existing = self.get(
            external_source_id=external_source_id,
            source_property_id=source_property_id,
        ) or build_empty_reel_state(
            external_source_id=external_source_id,
            source_property_id=source_property_id,
        )
        relative_metadata = (
            ""
            if resolved_metadata_path is None
            else _relative_to_base(resolved_metadata_path, self.base_dir)
        )
        relative_artifact = _relative_to_base(resolved_artifact_path, self.base_dir)
        # Feature 41: the renderer signals "the autoCaptions flow ran
        # this render — refresh the snapshot" by passing an explicit
        # value (a list of cues, or ``None`` to clear). Callers that do
        # not touch subtitles leave the sentinel default so the
        # previously-persisted snapshot is preserved.
        resolved_snapshot = (
            existing.auto_subtitles_snapshot
            if isinstance(auto_subtitles_snapshot, _Unset)
            else auto_subtitles_snapshot
        )
        self.save(
            ReelState(
                agency_id=existing.agency_id or agency_id,
                ingestion_source_id=existing.ingestion_source_id or ingestion_source_id,
                external_source_id=existing.external_source_id,
                source_property_id=existing.source_property_id,
                content_fingerprint=existing.content_fingerprint,
                content_snapshot=existing.content_snapshot,
                publish_target_fingerprint=existing.publish_target_fingerprint,
                publish_target_snapshot=existing.publish_target_snapshot,
                render_template_id=existing.render_template_id,
                selected_image_folder=existing.selected_image_folder,
                artifact_kind=artifact_kind,
                local_artifact_path=relative_artifact,
                local_metadata_path=relative_metadata,
                render_profile=render_profile,
                local_manifest_path=(
                    relative_metadata
                    if artifact_kind == "reel_video" and resolved_metadata_path is not None
                    else ""
                ),
                local_video_path=(
                    relative_artifact if artifact_kind == "reel_video" else ""
                ),
                render_status="completed",
                publish_status=existing.publish_status,
                workflow_state="rendered",
                publish_details=existing.publish_details,
                current_revision_id=current_revision_id or existing.current_revision_id,
                last_published_provider_external_id=existing.last_published_provider_external_id,
                created_at=existing.created_at,
                updated_at=existing.updated_at,
                descriptions_override=existing.descriptions_override,
                music_id=existing.music_id,
                photos_override=existing.photos_override,
                subtitles_override=existing.subtitles_override,
                manifest_override=existing.manifest_override,
                auto_subtitles_snapshot=resolved_snapshot,
            )
        )


__all__ = ["ReelStateRepository"]
