"""Unit tests for RotateProviderCredentialsUseCase."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.publishing.application.use_cases.rotate_provider_credentials import (
    RotateProviderCredentialsInput,
    RotateProviderCredentialsUseCase,
)
from modules.publishing.domain import ProviderConnection
from shared.errors import ResourceNotFoundError, ValidationError


def test_rotate_replaces_tokens_when_connection_already_exists() -> None:
    existing = ProviderConnection(
        connection_id="conn-1",
        agency_id="agency-1",
        provider="gohighlevel",
        external_id="loc-old",
        config={"user_id": "old"},
        status="active",
        has_secret=True,
    )
    captured: dict[str, object] = {}

    def upsert(**kwargs):
        captured.update(kwargs)
        return ProviderConnection(
            connection_id="conn-1",
            agency_id=kwargs["agency_id"],
            provider=kwargs["provider"],
            external_id=kwargs["external_id"],
            config=kwargs["config"],
            status=kwargs["status"],
            has_secret=True,
        )

    uow = _uow(agency_present=True, existing=existing, upsert=upsert)
    result = RotateProviderCredentialsUseCase().execute(
        uow=uow,
        data=RotateProviderCredentialsInput(
            agency_id="agency-1",
            location_id="loc-new",
            access_token="access-new",
            refresh_token="refresh-new",
            expires_at="2027-01-01T00:00:00Z",
        ),
    )

    assert result.external_id == "loc-new"
    assert captured["secrets"]["access_token"] == "access-new"
    assert captured["secrets"]["refresh_token"] == "refresh-new"


def test_rotate_raises_when_no_existing_connection() -> None:
    uow = _uow(agency_present=True, existing=None)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        RotateProviderCredentialsUseCase().execute(
            uow=uow,
            data=RotateProviderCredentialsInput(
                agency_id="agency-1",
                location_id="loc-1",
                access_token="access-1",
            ),
        )
    assert exc_info.value.code == "GHL_CONNECTION_NOT_FOUND"


def test_rotate_raises_when_agency_missing() -> None:
    uow = _uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        RotateProviderCredentialsUseCase().execute(
            uow=uow,
            data=RotateProviderCredentialsInput(
                agency_id="missing",
                location_id="loc-1",
                access_token="access-1",
            ),
        )
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"


def test_rotate_validates_required_fields() -> None:
    uow = _uow(agency_present=True)
    with pytest.raises(ValidationError) as exc_info:
        RotateProviderCredentialsUseCase().execute(
            uow=uow,
            data=RotateProviderCredentialsInput(
                agency_id="agency-1",
                location_id="",
                access_token="access-1",
            ),
        )
    assert exc_info.value.code == "GHL_LOCATION_ID_REQUIRED"


def _uow(*, agency_present: bool, existing=None, upsert=None) -> SimpleNamespace:
    class _Connections:
        def get_by_agency_and_provider(self, *, agency_id, provider):
            del agency_id, provider
            return existing

        def upsert(self, **kwargs):
            if upsert is None:
                return ProviderConnection(
                    connection_id="conn",
                    agency_id=kwargs["agency_id"],
                    provider=kwargs["provider"],
                    external_id=kwargs["external_id"],
                    config=kwargs["config"],
                    status=kwargs["status"],
                    has_secret=True,
                )
            return upsert(**kwargs)

    class _Agencies:
        def get_by_id(self, agency_id: str):
            return SimpleNamespace(agency_id=agency_id) if agency_present else None

    return SimpleNamespace(
        publishing=SimpleNamespace(connections=_Connections()),
        tenancy=SimpleNamespace(agencies=_Agencies()),
    )
