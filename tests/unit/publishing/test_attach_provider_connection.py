"""Unit tests for AttachProviderConnectionUseCase."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.publishing.application.use_cases.attach_provider_connection import (
    AttachProviderConnectionInput,
    AttachProviderConnectionUseCase,
)
from modules.publishing.domain import ProviderConnection
from shared.errors import ResourceNotFoundError, ValidationError


def test_attach_persists_connection_via_repo_and_returns_aggregate() -> None:
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
            created_at="2026-04-30T10:00:00Z",
            updated_at="2026-04-30T10:00:00Z",
        )

    uow = _uow(agency_present=True, upsert=upsert)
    result = AttachProviderConnectionUseCase().execute(
        uow=uow,
        data=AttachProviderConnectionInput(
            agency_id="agency-1",
            location_id="loc-1",
            access_token="access-1",
            user_id="user-1",
            refresh_token="refresh-1",
            expires_at="2026-12-31T00:00:00Z",
            status="ACTIVE",
        ),
    )

    assert result.connection_id == "conn-1"
    assert captured["agency_id"] == "agency-1"
    assert captured["provider"] == "gohighlevel"
    assert captured["external_id"] == "loc-1"
    assert captured["status"] == "active"
    assert captured["config"] == {
        "user_id": "user-1",
        "expires_at": "2026-12-31T00:00:00Z",
    }
    assert captured["secrets"] == {
        "access_token": "access-1",
        "refresh_token": "refresh-1",
        "expires_at": "2026-12-31T00:00:00Z",
    }


def test_attach_raises_validation_error_when_location_id_missing() -> None:
    uow = _uow(agency_present=True)
    with pytest.raises(ValidationError) as exc_info:
        AttachProviderConnectionUseCase().execute(
            uow=uow,
            data=AttachProviderConnectionInput(
                agency_id="agency-1",
                location_id="   ",
                access_token="access-1",
            ),
        )
    assert exc_info.value.code == "GHL_LOCATION_ID_REQUIRED"


def test_attach_raises_validation_error_when_access_token_missing() -> None:
    uow = _uow(agency_present=True)
    with pytest.raises(ValidationError) as exc_info:
        AttachProviderConnectionUseCase().execute(
            uow=uow,
            data=AttachProviderConnectionInput(
                agency_id="agency-1",
                location_id="loc-1",
                access_token="",
            ),
        )
    assert exc_info.value.code == "GHL_ACCESS_TOKEN_REQUIRED"


def test_attach_raises_404_when_agency_does_not_exist() -> None:
    uow = _uow(agency_present=False)
    with pytest.raises(ResourceNotFoundError) as exc_info:
        AttachProviderConnectionUseCase().execute(
            uow=uow,
            data=AttachProviderConnectionInput(
                agency_id="missing",
                location_id="loc-1",
                access_token="access-1",
            ),
        )
    assert exc_info.value.code == "ADMIN_AGENCY_NOT_FOUND"


def _uow(*, agency_present: bool, upsert=None) -> SimpleNamespace:
    class _Connections:
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
