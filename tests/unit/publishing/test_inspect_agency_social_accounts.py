"""Unit tests for InspectAgencySocialAccountsUseCase."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from modules.publishing.application.use_cases.inspect_agency_social_accounts import (
    InspectAgencySocialAccountsUseCase,
)
from modules.publishing.domain import ProviderConnectionWithSecrets
from modules.publishing.infrastructure.adapters.gohighlevel.models import SocialAccount
from shared.errors import SocialPublishingError


def test_returns_disconnected_when_no_connection_row() -> None:
    use_case = InspectAgencySocialAccountsUseCase(
        client_factory=_unused_client_factory,
    )
    result = use_case.execute(
        unit_of_work_factory=_uow_factory(connection=None),
        agency_id="agency-1",
    )
    assert result.connected is False
    assert result.reason == "GHL_CONNECTION_NOT_FOUND"
    assert result.items == ()


def test_returns_disconnected_when_access_token_missing() -> None:
    record = _connection_with_secrets(secrets={"access_token": "   "})
    use_case = InspectAgencySocialAccountsUseCase(
        client_factory=_unused_client_factory,
    )
    result = use_case.execute(
        unit_of_work_factory=_uow_factory(connection=record),
        agency_id="agency-1",
    )
    assert result.connected is False
    assert result.reason == "GHL_CONNECTION_NOT_FOUND"


def test_returns_items_when_upstream_succeeds() -> None:
    record = _connection_with_secrets(secrets={"access_token": "tok-1"})
    fake_account = SocialAccount(
        id="ac-1",
        name="Brand IG",
        platform="instagram",
        account_type="page",
        is_expired=False,
        raw_data={},
    )

    fake_client = _FakeClient()

    def factory():
        return fake_client

    with patch(
        "modules.publishing.application.use_cases.inspect_agency_social_accounts."
        "GoHighLevelSocialService"
    ) as service_factory:
        service_factory.return_value.list_accounts.return_value = (fake_account,)
        use_case = InspectAgencySocialAccountsUseCase(client_factory=factory)
        result = use_case.execute(
            unit_of_work_factory=_uow_factory(connection=record),
            agency_id="agency-1",
        )

    assert result.connected is True
    assert result.location_id == "loc-1"
    assert result.items == (fake_account,)
    assert result.reason is None
    assert fake_client.closed is True


def test_returns_reason_when_upstream_fails() -> None:
    record = _connection_with_secrets(secrets={"access_token": "tok-1"})
    fake_client = _FakeClient()

    with patch(
        "modules.publishing.application.use_cases.inspect_agency_social_accounts."
        "GoHighLevelSocialService"
    ) as service_factory:
        service_factory.return_value.list_accounts.side_effect = SocialPublishingError(
            "boom",
            code="GHL_API_500",
        )
        use_case = InspectAgencySocialAccountsUseCase(
            client_factory=lambda: fake_client,
        )
        result = use_case.execute(
            unit_of_work_factory=_uow_factory(connection=record),
            agency_id="agency-1",
        )

    assert result.connected is True
    assert result.reason == "GHL_API_500"
    assert result.error == "boom"
    assert result.items == ()
    assert fake_client.closed is True


def _unused_client_factory():
    raise AssertionError("Client factory should not be called when no connection.")


def _connection_with_secrets(*, secrets: dict[str, str]) -> ProviderConnectionWithSecrets:
    return ProviderConnectionWithSecrets(
        connection_id="conn-1",
        agency_id="agency-1",
        provider="gohighlevel",
        external_id="loc-1",
        config={},
        status="active",
        has_secret=True,
        created_at=None,
        updated_at=None,
        secrets=secrets,
    )


def _uow_factory(*, connection: ProviderConnectionWithSecrets | None):
    @contextmanager
    def factory():
        yield SimpleNamespace(
            publishing=SimpleNamespace(
                connections=SimpleNamespace(
                    get_with_secrets=lambda *, agency_id, provider: connection
                )
            ),
        )

    return factory


class _FakeClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True
