"""Detach (delete) the saved provider connection for an agency."""

from __future__ import annotations

from shared.db import DatabaseUnitOfWork
from shared.errors import ResourceNotFoundError


class DetachProviderConnectionUseCase:
    def __init__(self, *, provider: str = "gohighlevel") -> None:
        self.provider = str(provider or "").strip().lower()

    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        agency_id: str,
    ) -> bool:
        if uow.publishing is None:
            raise RuntimeError("The unit of work is not active.")

        normalized_agency = str(agency_id or "").strip()
        deleted = uow.publishing.connections.delete(
            agency_id=normalized_agency,
            provider=self.provider,
        )
        if not deleted:
            raise ResourceNotFoundError(
                "No GoHighLevel connection saved for this agency.",
                code="GHL_CONNECTION_NOT_FOUND",
                context={"agency_id": normalized_agency},
            )
        return True


__all__ = ["DetachProviderConnectionUseCase"]
