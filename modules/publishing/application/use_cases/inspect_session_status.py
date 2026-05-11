"""Inspect whether a GoHighLevel embedded session is connected."""

from __future__ import annotations

from dataclasses import dataclass

from modules.publishing.domain import ProviderConnectionWithSecrets
from shared.db import DatabaseUnitOfWork


@dataclass(frozen=True, slots=True)
class SessionStatus:
    location_id: str
    user_id: str
    connected: bool
    has_token: bool
    agency_id: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "location_id": self.location_id,
            "user_id": self.user_id,
            "connected": self.connected,
            "has_token": self.has_token,
            "agency_id": self.agency_id,
        }


class InspectSessionStatusUseCase:
    def __init__(self, *, provider: str = "gohighlevel") -> None:
        self.provider = str(provider or "").strip().lower()

    def execute(
        self,
        *,
        uow: DatabaseUnitOfWork,
        location_id: str,
        user_id: str,
    ) -> SessionStatus:
        normalized_location_id = str(location_id or "").strip()
        if uow.publishing is None:
            raise RuntimeError("The unit of work is not active.")
        record = uow.publishing.connections.get_by_provider_external_id_with_secrets(
            provider=self.provider,
            external_id=normalized_location_id,
        )
        has_token = _has_access_token(record)
        return SessionStatus(
            location_id=normalized_location_id,
            user_id=str(user_id or "").strip(),
            connected=record is not None and has_token,
            has_token=has_token,
            agency_id=record.agency_id if record is not None else None,
        )


def _has_access_token(record: ProviderConnectionWithSecrets | None) -> bool:
    if record is None:
        return False
    return bool(str(record.secrets.get("access_token") or "").strip())


__all__ = ["InspectSessionStatusUseCase", "SessionStatus"]
