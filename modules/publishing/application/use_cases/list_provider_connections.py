"""List provider connections, optionally filtered by agency.

Returns aggregates without decrypted secrets — same view as `inspect`.
"""

from __future__ import annotations

from modules.publishing.domain import ProviderConnection
from shared.db import DatabaseUnitOfWork


class ListProviderConnectionsUseCase:
    def __init__(self, *, provider: str = "gohighlevel") -> None:
        self.provider = str(provider or "").strip().lower()

    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str | None = None,
    ) -> tuple[ProviderConnection, ...]:
        if uow.publishing is None:
            raise RuntimeError("The unit of work is not active.")

        normalized_agency = str(agency_id or "").strip()
        if normalized_agency:
            connection = uow.publishing.connections.get_by_agency_and_provider(
                agency_id=normalized_agency,
                provider=self.provider,
            )
            return (connection,) if connection is not None else ()
        return uow.publishing.connections.list_by_provider(
            provider=self.provider,
            with_secrets=False,
        )


__all__ = ["ListProviderConnectionsUseCase"]
