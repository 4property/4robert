"""Probe a saved GoHighLevel provider connection."""

from __future__ import annotations

from typing import Protocol

from settings import (
    GO_HIGH_LEVEL_API_VERSION,
    GO_HIGH_LEVEL_BASE_URL,
    OUTBOUND_HTTP_TIMEOUT_SECONDS,
)
from shared.db import DatabaseUnitOfWork
from shared.errors import ResourceNotFoundError


class AccountLister(Protocol):
    def __call__(self, *, location_id: str, access_token: str) -> tuple[object, ...]:
        ...


class ProbeProviderConnectionUseCase:
    def __init__(
        self,
        *,
        provider: str = "gohighlevel",
        account_lister: AccountLister | None = None,
    ) -> None:
        self.provider = str(provider or "").strip().lower()
        self.account_lister = account_lister

    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        location_id: str,
    ) -> tuple[object, ...]:
        normalized_location_id = str(location_id or "").strip()
        if uow.publishing is None:
            raise RuntimeError("The unit of work is not active.")
        record = uow.publishing.connections.get_by_provider_external_id_with_secrets(
            provider=self.provider,
            external_id=normalized_location_id,
        )
        access_token = str(record.secrets.get("access_token") if record is not None else "").strip()
        if record is None or not access_token:
            raise ResourceNotFoundError(
                "No GoHighLevel connection is saved for this location.",
                code="GHL_CONNECTION_NOT_FOUND",
                context={"location_id": normalized_location_id},
                hint=(
                    "Configure a GoHighLevel connection for the agency that owns "
                    "this location."
                ),
            )
        if self.account_lister is not None:
            return tuple(
                self.account_lister(
                    location_id=record.external_id,
                    access_token=access_token,
                )
            )
        return _list_accounts_with_legacy_client(
            location_id=record.external_id,
            access_token=access_token,
        )


def _list_accounts_with_legacy_client(
    *,
    location_id: str,
    access_token: str,
) -> tuple[object, ...]:
    from modules.publishing.infrastructure.adapters.gohighlevel.client import GoHighLevelClient
    from modules.publishing.infrastructure.adapters.gohighlevel.social_service import (
        GoHighLevelSocialService,
    )

    client = GoHighLevelClient(
        base_url=GO_HIGH_LEVEL_BASE_URL,
        api_version=GO_HIGH_LEVEL_API_VERSION,
        timeout_seconds=OUTBOUND_HTTP_TIMEOUT_SECONDS,
    )
    try:
        social_service = GoHighLevelSocialService(client=client)
        return tuple(
            social_service.list_accounts(
                location_id=location_id,
                access_token=access_token,
            )
        )
    finally:
        client.close()


__all__ = ["AccountLister", "ProbeProviderConnectionUseCase"]
