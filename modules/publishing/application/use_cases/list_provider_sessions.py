"""List saved publishing-provider sessions."""

from __future__ import annotations

from typing import Any, Mapping

from modules.publishing.domain import ProviderConnection, ProviderConnectionWithSecrets
from shared.db import DatabaseUnitOfWork


class ListProviderSessionsUseCase:
    def __init__(self, *, provider: str = "gohighlevel") -> None:
        self.provider = str(provider or "").strip().lower()

    def execute(self, *, uow: DatabaseUnitOfWork) -> dict[str, object]:
        if uow.publishing is None:
            raise RuntimeError("The unit of work is not active.")
        records = uow.publishing.connections.list_by_provider(
            provider=self.provider,
            with_secrets=True,
        )
        items = [_to_public_session(record) for record in records]
        return {"count": len(items), "items": items}


def _to_public_session(connection: ProviderConnection) -> dict[str, object]:
    config = dict(connection.config or {})
    secrets = _connection_secrets(connection)
    return {
        "connection_id": connection.connection_id,
        "agency_id": connection.agency_id,
        "location_id": connection.external_id,
        "user_id": str(config.get("user_id") or ""),
        "has_access_token": bool(str(secrets.get("access_token") or "").strip()),
        "has_refresh_token": bool(str(secrets.get("refresh_token") or "").strip()),
        "expires_at": str(secrets.get("expires_at") or config.get("expires_at") or ""),
        "status": connection.status,
        "created_at": connection.created_at,
        "updated_at": connection.updated_at,
    }


def _connection_secrets(connection: ProviderConnection) -> Mapping[str, Any]:
    if isinstance(connection, ProviderConnectionWithSecrets):
        return connection.secrets
    return {}


__all__ = ["ListProviderSessionsUseCase"]
