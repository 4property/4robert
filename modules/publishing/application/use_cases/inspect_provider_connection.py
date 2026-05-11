"""Inspect the saved provider connection for an agency.

Returns a public DTO without decrypted secrets — only `has_access_token`
and `has_refresh_token` flags so the admin panel can show whether a token is
present without ever exposing it.
"""

from __future__ import annotations

from modules.publishing.domain import ProviderConnection
from shared.db import DatabaseUnitOfWork
from shared.errors import ResourceNotFoundError


class InspectProviderConnectionUseCase:
    def __init__(self, *, provider: str = "gohighlevel") -> None:
        self.provider = str(provider or "").strip().lower()

    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> ProviderConnection:
        if uow.publishing is None or uow.tenancy is None:
            raise RuntimeError("The unit of work is not active.")

        normalized_agency = str(agency_id or "").strip()
        agency = uow.tenancy.agencies.get_by_id(normalized_agency)
        if agency is None:
            raise ResourceNotFoundError(
                "The agency does not exist.",
                code="ADMIN_AGENCY_NOT_FOUND",
                context={"agency_id": normalized_agency},
            )

        connection = uow.publishing.connections.get_by_agency_and_provider(
            agency_id=normalized_agency,
            provider=self.provider,
        )
        if connection is None:
            raise ResourceNotFoundError(
                "No GoHighLevel connection saved for this agency.",
                code="GHL_CONNECTION_NOT_FOUND",
                context={"agency_id": normalized_agency},
            )
        return connection


__all__ = ["InspectProviderConnectionUseCase"]
