"""Persistence for the ProviderConnection aggregate.

GoHighLevel today; Meta / TikTok / YouTube direct in the future. New providers
add a row, not a column.
"""

from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import text

from modules.publishing.domain import (
    ProviderConnection,
    ProviderConnectionWithSecrets,
)
from shared.db.repository_base import ModuleRepository, utcnow
from shared.db.security import decrypt_text, encrypt_text


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


def _row_to_connection(row, *, with_secrets: bool = False):
    secrets_raw = row.secrets_encrypted
    has_secret = bool(secrets_raw) and len(bytes(secrets_raw)) > 0
    base = ProviderConnection(
        connection_id=str(row.id),
        agency_id=str(row.agency_id),
        provider=str(row.provider or ""),
        external_id=str(row.external_id or ""),
        config=_jsonb_to_config(row.config_json),
        status=str(row.status or ""),
        has_secret=has_secret,
        created_at=_isoformat(row.created_at),
        updated_at=_isoformat(row.updated_at),
    )
    if not with_secrets:
        return base
    secrets: dict[str, Any] = {}
    if has_secret:
        decoded = decrypt_text(bytes(secrets_raw))
        if decoded:
            try:
                parsed = json.loads(decoded)
                if isinstance(parsed, dict):
                    secrets = parsed
            except json.JSONDecodeError:
                secrets = {"raw": decoded}
    return ProviderConnectionWithSecrets(
        connection_id=base.connection_id,
        agency_id=base.agency_id,
        provider=base.provider,
        external_id=base.external_id,
        config=base.config,
        status=base.status,
        has_secret=base.has_secret,
        created_at=base.created_at,
        updated_at=base.updated_at,
        secrets=secrets,
    )


class ProviderConnectionRepository(ModuleRepository):
    """CRUD for outbound publishing connections, one per (agency, provider)."""

    def get_by_agency_and_provider(
        self, *, agency_id: str, provider: str
    ) -> ProviderConnection | None:
        normalized_agency = str(agency_id or "").strip()
        normalized_provider = str(provider or "").strip().lower()
        if not normalized_agency or not normalized_provider:
            return None
        row = self.session.execute(
            text(
                "SELECT id, agency_id, provider, external_id, config_json, "
                "secrets_encrypted, status, created_at, updated_at "
                "FROM provider_connections "
                "WHERE agency_id = :agency_id AND provider = :provider"
            ),
            {"agency_id": normalized_agency, "provider": normalized_provider},
        ).first()
        return _row_to_connection(row) if row is not None else None

    def get_with_secrets(
        self, *, agency_id: str, provider: str
    ) -> ProviderConnectionWithSecrets | None:
        normalized_agency = str(agency_id or "").strip()
        normalized_provider = str(provider or "").strip().lower()
        if not normalized_agency or not normalized_provider:
            return None
        row = self.session.execute(
            text(
                "SELECT id, agency_id, provider, external_id, config_json, "
                "secrets_encrypted, status, created_at, updated_at "
                "FROM provider_connections "
                "WHERE agency_id = :agency_id AND provider = :provider"
            ),
            {"agency_id": normalized_agency, "provider": normalized_provider},
        ).first()
        return _row_to_connection(row, with_secrets=True) if row is not None else None

    def get_by_provider_external_id(
        self, *, provider: str, external_id: str
    ) -> ProviderConnection | None:
        normalized_provider = str(provider or "").strip().lower()
        normalized_external = str(external_id or "").strip()
        if not normalized_provider or not normalized_external:
            return None
        row = self.session.execute(
            text(
                "SELECT id, agency_id, provider, external_id, config_json, "
                "secrets_encrypted, status, created_at, updated_at "
                "FROM provider_connections "
                "WHERE provider = :provider AND external_id = :external_id"
            ),
            {"provider": normalized_provider, "external_id": normalized_external},
        ).first()
        return _row_to_connection(row) if row is not None else None

    def get_by_provider_external_id_with_secrets(
        self, *, provider: str, external_id: str
    ) -> ProviderConnectionWithSecrets | None:
        normalized_provider = str(provider or "").strip().lower()
        normalized_external = str(external_id or "").strip()
        if not normalized_provider or not normalized_external:
            return None
        row = self.session.execute(
            text(
                "SELECT id, agency_id, provider, external_id, config_json, "
                "secrets_encrypted, status, created_at, updated_at "
                "FROM provider_connections "
                "WHERE provider = :provider AND external_id = :external_id"
            ),
            {"provider": normalized_provider, "external_id": normalized_external},
        ).first()
        return _row_to_connection(row, with_secrets=True) if row is not None else None

    def list_by_provider(
        self, *, provider: str, with_secrets: bool = False
    ) -> tuple[ProviderConnection, ...]:
        normalized_provider = str(provider or "").strip().lower()
        if not normalized_provider:
            return ()
        rows = self.session.execute(
            text(
                "SELECT id, agency_id, provider, external_id, config_json, "
                "secrets_encrypted, status, created_at, updated_at "
                "FROM provider_connections "
                "WHERE provider = :provider ORDER BY updated_at DESC"
            ),
            {"provider": normalized_provider},
        ).all()
        return tuple(_row_to_connection(row, with_secrets=with_secrets) for row in rows)

    def list_all(self) -> tuple[ProviderConnection, ...]:
        rows = self.session.execute(
            text(
                "SELECT id, agency_id, provider, external_id, config_json, "
                "secrets_encrypted, status, created_at, updated_at "
                "FROM provider_connections ORDER BY updated_at DESC"
            )
        ).all()
        return tuple(_row_to_connection(row) for row in rows)

    def upsert(
        self,
        *,
        agency_id: str,
        provider: str,
        external_id: str,
        config: Mapping[str, Any] | None = None,
        secrets: Mapping[str, Any] | None = None,
        status: str = "active",
    ) -> ProviderConnection:
        normalized_agency = str(agency_id or "").strip()
        normalized_provider = str(provider or "").strip().lower()
        normalized_external = str(external_id or "").strip()
        normalized_status = str(status or "active").strip().lower() or "active"
        timestamp = utcnow()
        secrets_payload = json.dumps(dict(secrets or {}), separators=(",", ":"))
        secrets_encrypted = encrypt_text(secrets_payload) if secrets_payload != "{}" else b""

        existing = self.get_by_agency_and_provider(
            agency_id=normalized_agency, provider=normalized_provider
        )
        if existing is None:
            connection_id = str(uuid4())
            self.session.execute(
                text(
                    "INSERT INTO provider_connections ("
                    "id, agency_id, provider, external_id, config_json, "
                    "secrets_encrypted, status, created_at, updated_at"
                    ") VALUES ("
                    ":id, :agency_id, :provider, :external_id, "
                    "CAST(:config_json AS jsonb), :secrets_encrypted, "
                    ":status, :created_at, :updated_at"
                    ")"
                ),
                {
                    "id": connection_id,
                    "agency_id": normalized_agency,
                    "provider": normalized_provider,
                    "external_id": normalized_external,
                    "config_json": _config_to_jsonb(config),
                    "secrets_encrypted": secrets_encrypted,
                    "status": normalized_status,
                    "created_at": timestamp,
                    "updated_at": timestamp,
                },
            )
        else:
            self.session.execute(
                text(
                    "UPDATE provider_connections SET "
                    "external_id = :external_id, "
                    "config_json = CAST(:config_json AS jsonb), "
                    "secrets_encrypted = :secrets_encrypted, "
                    "status = :status, updated_at = :updated_at "
                    "WHERE agency_id = :agency_id AND provider = :provider"
                ),
                {
                    "agency_id": normalized_agency,
                    "provider": normalized_provider,
                    "external_id": normalized_external,
                    "config_json": _config_to_jsonb(config),
                    "secrets_encrypted": secrets_encrypted,
                    "status": normalized_status,
                    "updated_at": timestamp,
                },
            )
        result = self.get_by_agency_and_provider(
            agency_id=normalized_agency, provider=normalized_provider
        )
        assert result is not None
        return result

    def delete(self, *, agency_id: str, provider: str) -> bool:
        normalized_agency = str(agency_id or "").strip()
        normalized_provider = str(provider or "").strip().lower()
        if not normalized_agency or not normalized_provider:
            return False
        row = self.session.execute(
            text(
                "DELETE FROM provider_connections "
                "WHERE agency_id = :agency_id AND provider = :provider RETURNING id"
            ),
            {"agency_id": normalized_agency, "provider": normalized_provider},
        ).first()
        return row is not None


__all__ = ["ProviderConnectionRepository"]
