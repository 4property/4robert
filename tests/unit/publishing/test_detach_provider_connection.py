"""Unit tests for DetachProviderConnectionUseCase."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from modules.publishing.application.use_cases.detach_provider_connection import (
    DetachProviderConnectionUseCase,
)
from shared.errors import ResourceNotFoundError


def test_detach_returns_true_when_repo_deletes_row() -> None:
    captured: dict[str, str] = {}

    class _Connections:
        def delete(self, *, agency_id, provider):
            captured["agency_id"] = agency_id
            captured["provider"] = provider
            return True

    uow = SimpleNamespace(publishing=SimpleNamespace(connections=_Connections()))
    result = DetachProviderConnectionUseCase().execute(uow=uow, agency_id="agency-1")

    assert result is True
    assert captured == {"agency_id": "agency-1", "provider": "gohighlevel"}


def test_detach_raises_when_no_connection_exists() -> None:
    class _Connections:
        def delete(self, *, agency_id, provider):
            del agency_id, provider
            return False

    uow = SimpleNamespace(publishing=SimpleNamespace(connections=_Connections()))
    with pytest.raises(ResourceNotFoundError) as exc_info:
        DetachProviderConnectionUseCase().execute(uow=uow, agency_id="agency-1")

    assert exc_info.value.code == "GHL_CONNECTION_NOT_FOUND"
