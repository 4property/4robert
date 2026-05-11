"""Persistence for the IngestionSource aggregate.

The single physical table `ingestion_sources` carries any kind of feed
(`kind='wordpress'` today). New kinds add a row, not a column.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from sqlalchemy import text

from modules.ingestion.domain import IngestionSource, IngestionSourceWithAgency
from shared.db.repository_base import ModuleRepository, utcnow
from shared.db.security import encrypt_text


def _isoformat(value: object | None) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        return str(isoformat())
    return str(value)


def _config_to_jsonb(config: Mapping[str, Any] | None) -> str:
    return json.dumps(dict(config or {}), separators=(",", ":"))


def _jsonb_to_config(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (bytes, bytearray)):
        return json.loads(bytes(raw).decode("utf-8"))
    if isinstance(raw, str):
        return json.loads(raw) if raw.strip() else {}
    return dict(raw)


def _row_to_source(row) -> IngestionSource:
    secrets_value = row.secrets_encrypted
    has_secret = bool(secrets_value) and len(bytes(secrets_value)) > 0
    return IngestionSource(
        ingestion_source_id=str(row.id),
        agency_id=str(row.agency_id),
        kind=str(row.kind or ""),
        external_id=str(row.external_id or ""),
        name=str(row.name or ""),
        config=_jsonb_to_config(row.config_json),
        status=str(row.status or ""),
        has_secret=has_secret,
        last_event_at=_isoformat(row.last_event_at),
        created_at=_isoformat(row.created_at),
        updated_at=_isoformat(row.updated_at),
    )


class IngestionSourceRepository(ModuleRepository):
    """CRUD for tenant feeds. The `kind` discriminator routes to the right adapter."""

    def get_by_id(self, ingestion_source_id: str) -> IngestionSource | None:
        normalized = str(ingestion_source_id or "").strip()
        if not normalized:
            return None
        row = self.session.execute(
            text(
                "SELECT id, agency_id, kind, external_id, name, config_json, "
                "secrets_encrypted, status, last_event_at, created_at, updated_at "
                "FROM ingestion_sources WHERE id = :id"
            ),
            {"id": normalized},
        ).first()
        return _row_to_source(row) if row is not None else None

    def get_by_kind_external_id(self, *, kind: str, external_id: str) -> IngestionSource | None:
        normalized_kind = str(kind or "").strip().lower()
        normalized_external = str(external_id or "").strip().lower()
        if not normalized_kind or not normalized_external:
            return None
        row = self.session.execute(
            text(
                "SELECT id, agency_id, kind, external_id, name, config_json, "
                "secrets_encrypted, status, last_event_at, created_at, updated_at "
                "FROM ingestion_sources WHERE kind = :kind AND external_id = :external_id"
            ),
            {"kind": normalized_kind, "external_id": normalized_external},
        ).first()
        return _row_to_source(row) if row is not None else None

    def list_for_agency(self, agency_id: str) -> tuple[IngestionSourceWithAgency, ...]:
        normalized_agency_id = str(agency_id or "").strip()
        if not normalized_agency_id:
            return ()
        rows = self.session.execute(
            text(
                "SELECT s.id, s.agency_id, s.kind, s.external_id, s.name, "
                "s.config_json, s.secrets_encrypted, s.status, s.last_event_at, "
                "s.created_at, s.updated_at, "
                "a.name AS agency_name, a.slug AS agency_slug, "
                "a.timezone AS agency_timezone, a.status AS agency_status "
                "FROM ingestion_sources AS s "
                "INNER JOIN agencies AS a ON a.id = s.agency_id "
                "WHERE s.agency_id = :agency_id "
                "ORDER BY s.kind ASC, s.external_id ASC"
            ),
            {"agency_id": normalized_agency_id},
        ).all()
        return tuple(
            IngestionSourceWithAgency(
                source=_row_to_source(row),
                agency_name=str(row.agency_name or ""),
                agency_slug=str(row.agency_slug or ""),
                agency_timezone=str(row.agency_timezone or ""),
                agency_status=str(row.agency_status or ""),
            )
            for row in rows
        )

    def list_all(self) -> tuple[IngestionSourceWithAgency, ...]:
        rows = self.session.execute(
            text(
                "SELECT s.id, s.agency_id, s.kind, s.external_id, s.name, "
                "s.config_json, s.secrets_encrypted, s.status, s.last_event_at, "
                "s.created_at, s.updated_at, "
                "a.name AS agency_name, a.slug AS agency_slug, "
                "a.timezone AS agency_timezone, a.status AS agency_status "
                "FROM ingestion_sources AS s "
                "INNER JOIN agencies AS a ON a.id = s.agency_id "
                "ORDER BY s.kind ASC, s.external_id ASC"
            )
        ).all()
        return tuple(
            IngestionSourceWithAgency(
                source=_row_to_source(row),
                agency_name=str(row.agency_name or ""),
                agency_slug=str(row.agency_slug or ""),
                agency_timezone=str(row.agency_timezone or ""),
                agency_status=str(row.agency_status or ""),
            )
            for row in rows
        )

    def create(
        self,
        *,
        ingestion_source_id: str,
        agency_id: str,
        kind: str,
        external_id: str,
        name: str,
        config: Mapping[str, Any] | None = None,
        secret: str = "",
        status: str = "active",
    ) -> None:
        timestamp = utcnow()
        self.session.execute(
            text(
                "INSERT INTO ingestion_sources ("
                "id, agency_id, kind, external_id, name, config_json, "
                "secrets_encrypted, status, last_event_at, created_at, updated_at"
                ") VALUES ("
                ":id, :agency_id, :kind, :external_id, :name, CAST(:config_json AS jsonb), "
                ":secrets_encrypted, :status, NULL, :created_at, :updated_at"
                ")"
            ),
            {
                "id": str(ingestion_source_id).strip(),
                "agency_id": str(agency_id).strip(),
                "kind": str(kind or "").strip().lower(),
                "external_id": str(external_id or "").strip().lower(),
                "name": str(name or "").strip(),
                "config_json": _config_to_jsonb(config),
                "secrets_encrypted": encrypt_text(secret),
                "status": str(status or "active").strip().lower() or "active",
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )

    def update(
        self,
        *,
        ingestion_source_id: str,
        name: str,
        config: Mapping[str, Any] | None = None,
        status: str = "active",
        secret: str | None = None,
    ) -> None:
        assignments = [
            "name = :name",
            "config_json = CAST(:config_json AS jsonb)",
            "status = :status",
            "updated_at = :updated_at",
        ]
        parameters: dict[str, Any] = {
            "id": str(ingestion_source_id).strip(),
            "name": str(name or "").strip(),
            "config_json": _config_to_jsonb(config),
            "status": str(status or "active").strip().lower() or "active",
            "updated_at": utcnow(),
        }
        if secret is not None:
            assignments.append("secrets_encrypted = :secrets_encrypted")
            parameters["secrets_encrypted"] = encrypt_text(secret)
        self.session.execute(
            text(
                f"UPDATE ingestion_sources SET {', '.join(assignments)} "
                f"WHERE id = :id"
            ),
            parameters,
        )

    def touch_last_event(self, ingestion_source_id: str) -> None:
        normalized = str(ingestion_source_id or "").strip()
        if not normalized:
            return
        timestamp = utcnow()
        self.session.execute(
            text(
                "UPDATE ingestion_sources SET last_event_at = :timestamp, "
                "updated_at = :timestamp WHERE id = :id"
            ),
            {"id": normalized, "timestamp": timestamp},
        )

    def delete(self, ingestion_source_id: str) -> bool:
        normalized = str(ingestion_source_id or "").strip()
        if not normalized:
            return False
        row = self.session.execute(
            text("DELETE FROM ingestion_sources WHERE id = :id RETURNING id"),
            {"id": normalized},
        ).first()
        return row is not None


__all__ = ["IngestionSourceRepository"]
