"""Unit tests for InspectProviderConnectionUseCase."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.publishing.application.use_cases.inspect_provider_connection import (
    InspectProviderConnectionUseCase,
)
from modules.publishing.domain import ProviderConnection
from shared.errors import ResourceNotFoundError


def test_inspect_returns_connection_without_decrypting_secrets() -> None:
    connection = ProviderConnection(
        connection_id="conn-1",
        agency_id="agency-1",
        provider="gohighlevel",
        external_id="loc-1",
        config={"user_id": "user-1"},
        status="active",
        has_secret=True,
    )
    uow = _uow(agency_present=True, connection=connection)

    result = InspectProviderConnectionUseCase().execute(
        uow=uow,
        agency_id="agency-1",
    )

    assert result is connection


def test_inspect_raises_when_agency_missing() -> None:
    uow = _uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        InspectProviderConnectionUseCase().execute(uow=uow, agency_id="missing")
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"


def test_inspect_raises_when_connection_missing() -> None:
    uow = _uow(agency_present=True, connection=None)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        InspectProviderConnectionUseCase().execute(uow=uow, agency_id="agency-1")
    assert exc_info.value.code == "GHL_CONNECTION_NOT_FOUND"


def _uow(*, agency_present: bool, connection=None) -> SimpleNamespace:
    class _Connections:
        def get_by_agency_and_provider(self, *, agency_id, provider):
            del agency_id, provider
            return connection

    class _Agencies:
        def get_by_id(self, agency_id: str):
            return SimpleNamespace(agency_id=agency_id) if agency_present else None

    return SimpleNamespace(
        publishing=SimpleNamespace(connections=_Connections()),
        tenancy=SimpleNamespace(agencies=_Agencies()),
    )
