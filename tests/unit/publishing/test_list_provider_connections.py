"""Unit tests for ListProviderConnectionsUseCase."""

from __future__ import annotations

from types import SimpleNamespace

from modules.publishing.application.use_cases.list_provider_connections import (
    ListProviderConnectionsUseCase,
)
from modules.publishing.domain import ProviderConnection


def test_list_filters_by_agency_when_agency_id_given() -> None:
    connection = ProviderConnection(
        connection_id="conn-1",
        agency_id="agency-1",
        provider="gohighlevel",
        external_id="loc-1",
        status="active",
        has_secret=True,
    )

    class _Connections:
        def get_by_agency_and_provider(self, *, agency_id, provider):
            assert agency_id == "agency-1"
            assert provider == "gohighlevel"
            return connection

        def list_by_provider(self, *, provider, with_secrets=False):
            del provider, with_secrets
            raise AssertionError("list_by_provider should not be called")

    uow = SimpleNamespace(publishing=SimpleNamespace(connections=_Connections()))
    result = ListProviderConnectionsUseCase().execute(uow=uow, agency_id="agency-1")

    assert result == (connection,)


def test_list_returns_empty_tuple_when_agency_has_no_connection() -> None:
    class _Connections:
        def get_by_agency_and_provider(self, *, agency_id, provider):
            del agency_id, provider
            return None

    uow = SimpleNamespace(publishing=SimpleNamespace(connections=_Connections()))
    result = ListProviderConnectionsUseCase().execute(uow=uow, agency_id="ghost")
    assert result == ()


def test_list_falls_back_to_provider_listing_when_no_agency_filter() -> None:
    connections = (
        ProviderConnection(
            connection_id="conn-1",
            agency_id="agency-1",
            provider="gohighlevel",
            external_id="loc-1",
            status="active",
            has_secret=True,
        ),
        ProviderConnection(
            connection_id="conn-2",
            agency_id="agency-2",
            provider="gohighlevel",
            external_id="loc-2",
            status="active",
            has_secret=False,
        ),
    )

    class _Connections:
        def list_by_provider(self, *, provider, with_secrets=False):
            assert provider == "gohighlevel"
            assert with_secrets is False
            return connections

    uow = SimpleNamespace(publishing=SimpleNamespace(connections=_Connections()))
    result = ListProviderConnectionsUseCase().execute(uow=uow)
    assert result == connections
