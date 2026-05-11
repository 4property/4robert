"""Unit tests for GoHighLevel session use cases."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.publishing.application.use_cases.inspect_session_status import (
    InspectSessionStatusUseCase,
)
from modules.publishing.application.use_cases.list_provider_sessions import (
    ListProviderSessionsUseCase,
)
from modules.publishing.application.use_cases.probe_provider_connection import (
    ProbeProviderConnectionUseCase,
)
from modules.publishing.domain import ProviderConnectionWithSecrets
from shared.errors import ResourceNotFoundError


def test_list_provider_sessions_returns_redacted_session_summaries() -> None:
    uow = _uow_with(
        ProviderConnectionWithSecrets(
            connection_id="conn-1",
            agency_id="agency-1",
            provider="gohighlevel",
            external_id="loc-1",
            config={"user_id": "user-1"},
            status="active",
            has_secret=True,
            created_at="2026-04-30T10:00:00Z",
            updated_at="2026-04-30T11:00:00Z",
            secrets={"access_token": "access", "refresh_token": "refresh"},
        )
    )

    result = ListProviderSessionsUseCase().execute(uow=uow)

    assert result == {
        "count": 1,
        "items": [
            {
                "connection_id": "conn-1",
                "agency_id": "agency-1",
                "location_id": "loc-1",
                "user_id": "user-1",
                "has_access_token": True,
                "has_refresh_token": True,
                "expires_at": "",
                "status": "active",
                "created_at": "2026-04-30T10:00:00Z",
                "updated_at": "2026-04-30T11:00:00Z",
            }
        ],
    }


def test_inspect_session_status_reports_disconnected_without_saved_token() -> None:
    status = InspectSessionStatusUseCase().execute(
        uow=_uow_with(),
        location_id="loc-missing",
        user_id="user-1",
    )

    assert status.to_dict() == {
        "ok": True,
        "location_id": "loc-missing",
        "user_id": "user-1",
        "connected": False,
        "has_token": False,
        "agency_id": None,
    }


def test_probe_provider_connection_uses_saved_access_token() -> None:
    captured: dict[str, str] = {}

    def account_lister(*, location_id: str, access_token: str) -> tuple[str, ...]:
        captured["location_id"] = location_id
        captured["access_token"] = access_token
        return ("account",)

    uow = _uow_with(
        ProviderConnectionWithSecrets(
            connection_id="conn-1",
            agency_id="agency-1",
            provider="gohighlevel",
            external_id="loc-1",
            config={},
            status="active",
            has_secret=True,
            secrets={"access_token": "access"},
        )
    )

    result = ProbeProviderConnectionUseCase(account_lister=account_lister).execute(
        uow=uow,
        location_id="loc-1",
    )

    assert result == ("account",)
    assert captured == {"location_id": "loc-1", "access_token": "access"}


def test_probe_provider_connection_raises_when_location_is_unknown() -> None:
    with pytest.raises(ResourceNotFoundError) as exc_info:
        ProbeProviderConnectionUseCase(account_lister=lambda **_: ()).execute(
            uow=_uow_with(),
            location_id="loc-missing",
        )

    assert exc_info.value.code == "GHL_CONNECTION_NOT_FOUND"
    assert exc_info.value.context == {"location_id": "loc-missing"}


def _uow_with(*connections: ProviderConnectionWithSecrets) -> SimpleNamespace:
    return SimpleNamespace(
        publishing=SimpleNamespace(
            connections=_Connections(connections),
        )
    )


class _Connections:
    def __init__(self, connections: tuple[ProviderConnectionWithSecrets, ...]) -> None:
        self.connections = connections

    def list_by_provider(
        self,
        *,
        provider: str,
        with_secrets: bool = False,
    ) -> tuple[ProviderConnectionWithSecrets, ...]:
        del with_secrets
        return tuple(
            connection for connection in self.connections if connection.provider == provider
        )

    def get_by_provider_external_id_with_secrets(
        self,
        *,
        provider: str,
        external_id: str,
    ) -> ProviderConnectionWithSecrets | None:
        for connection in self.connections:
            if connection.provider == provider and connection.external_id == external_id:
                return connection
        return None
