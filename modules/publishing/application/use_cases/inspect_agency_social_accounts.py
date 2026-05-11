"""Inspect the social accounts attached to the agency's GoHighLevel location.

Powers ``GET /v1/admin/agencies/{agency_id}/social-accounts``. The
admin drawer surfaces every social channel registered with the
GoHighLevel location for the agency. The handler keeps the response 200
even when the agency is not connected: in that case it returns an empty
list with a ``reason`` code so the frontend can render an empty state.

The legacy GoHighLevel HTTP client (``GoHighLevelClient`` /
``GoHighLevelSocialService``) lives under ``services/publishing/``.
Phase 2 keeps it in place; Phase 3 dissolves the directory.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import ContextManager

from modules.publishing.domain import ProviderConnectionWithSecrets
from modules.publishing.infrastructure.adapters.gohighlevel.client import GoHighLevelClient
from modules.publishing.infrastructure.adapters.gohighlevel.models import SocialAccount
from modules.publishing.infrastructure.adapters.gohighlevel.social_service import (
    GoHighLevelSocialService,
)
from settings import (
    GO_HIGH_LEVEL_API_VERSION,
    GO_HIGH_LEVEL_BASE_URL,
    OUTBOUND_HTTP_TIMEOUT_SECONDS,
)
from shared.db import DatabaseUnitOfWork
from shared.errors import ApplicationError

UnitOfWorkContext = ContextManager[DatabaseUnitOfWork]


@dataclass(frozen=True, slots=True)
class AgencySocialAccountsResult:
    """Outcome of an inspect call.

    ``reason`` is set when the listing could not be produced (no
    connection, upstream API error). ``items`` is always a tuple, possibly
    empty; ``location_id`` is set when a connection exists.
    """

    agency_id: str
    connected: bool
    location_id: str | None
    items: tuple[SocialAccount, ...]
    reason: str | None
    error: str | None


GoHighLevelClientFactory = Callable[[], GoHighLevelClient]


def _default_client_factory() -> GoHighLevelClient:
    return GoHighLevelClient(
        base_url=GO_HIGH_LEVEL_BASE_URL,
        api_version=GO_HIGH_LEVEL_API_VERSION,
        timeout_seconds=OUTBOUND_HTTP_TIMEOUT_SECONDS,
    )


class InspectAgencySocialAccountsUseCase:
    def __init__(
        self,
        *,
        client_factory: GoHighLevelClientFactory | None = None,
    ) -> None:
        self._client_factory = client_factory or _default_client_factory

    def execute(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWorkContext],
        agency_id: str,
    ) -> AgencySocialAccountsResult:
        with unit_of_work_factory() as uow:
            connection = _load_connection(uow=uow, agency_id=agency_id)

        if connection is None or not str(
            connection.secrets.get("access_token") or ""
        ).strip():
            return AgencySocialAccountsResult(
                agency_id=agency_id,
                connected=False,
                location_id=None,
                items=(),
                reason="GHL_CONNECTION_NOT_FOUND",
                error=None,
            )

        access_token = str(connection.secrets.get("access_token") or "")
        location_id = connection.external_id
        client = self._client_factory()
        try:
            try:
                accounts = GoHighLevelSocialService(client=client).list_accounts(
                    location_id=location_id,
                    access_token=access_token,
                )
            except ApplicationError as error:
                return AgencySocialAccountsResult(
                    agency_id=agency_id,
                    connected=True,
                    location_id=location_id,
                    items=(),
                    reason=getattr(error, "code", "GHL_CONNECTION_TEST_FAILED"),
                    error=str(error),
                )
        finally:
            client.close()

        return AgencySocialAccountsResult(
            agency_id=agency_id,
            connected=True,
            location_id=location_id,
            items=tuple(accounts),
            reason=None,
            error=None,
        )


def _load_connection(
    *,
    uow: DatabaseUnitOfWork,
    agency_id: str,
) -> ProviderConnectionWithSecrets | None:
    if uow.publishing is None:
        raise RuntimeError("The unit of work is not active.")
    return uow.publishing.connections.get_with_secrets(
        agency_id=agency_id,
        provider="gohighlevel",
    )


__all__ = [
    "AgencySocialAccountsResult",
    "GoHighLevelClientFactory",
    "InspectAgencySocialAccountsUseCase",
]
