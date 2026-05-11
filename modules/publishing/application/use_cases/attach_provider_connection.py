"""Attach (create or replace) a provider connection for an agency."""

from __future__ import annotations

from dataclasses import dataclass

from modules.publishing.domain import ProviderConnection
from shared.db import DatabaseUnitOfWork
from shared.errors import ResourceNotFoundError, ValidationError


@dataclass(frozen=True, slots=True)
class AttachProviderConnectionInput:
    agency_id: str
    location_id: str
    access_token: str
    user_id: str | None = None
    refresh_token: str | None = None
    expires_at: str | None = None
    status: str | None = None


class AttachProviderConnectionUseCase:
    def __init__(self, *, provider: str = "gohighlevel") -> None:
        self.provider = str(provider or "").strip().lower()

    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        data: AttachProviderConnectionInput,
    ) -> ProviderConnection:
        if uow.publishing is None or uow.tenancy is None:
            raise RuntimeError("The unit of work is not active.")

        agency_id = str(data.agency_id or "").strip()
        location_id = str(data.location_id or "").strip()
        access_token = str(data.access_token or "").strip()
        user_id = str(data.user_id or "").strip() or "manual"
        refresh_token = str(data.refresh_token or "").strip()
        expires_at = str(data.expires_at or "").strip()
        status = (str(data.status or "active").strip().lower()) or "active"

        if not location_id:
            raise ValidationError(
                "A GoHighLevel location id is required.",
                code="GHL_LOCATION_ID_REQUIRED",
                context={"agency_id": agency_id},
            )
        if not access_token:
            raise ValidationError(
                "A GoHighLevel access token is required.",
                code="GHL_ACCESS_TOKEN_REQUIRED",
                context={"agency_id": agency_id},
            )

        agency = uow.tenancy.agencies.get_by_id(agency_id)
        if agency is None:
            raise ResourceNotFoundError(
                "The agency does not exist.",
                code="ADMIN_AGENCY_NOT_FOUND",
                context={"agency_id": agency_id},
            )

        config = {"user_id": user_id, "expires_at": expires_at}
        secrets = {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
        }
        return uow.publishing.connections.upsert(
            agency_id=agency_id,
            provider=self.provider,
            external_id=location_id,
            config=config,
            secrets=secrets,
            status=status,
        )


__all__ = [
    "AttachProviderConnectionInput",
    "AttachProviderConnectionUseCase",
]
