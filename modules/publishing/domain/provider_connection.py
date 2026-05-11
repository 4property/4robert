"""ProviderConnection aggregate.

A tenant's authenticated link to one publishing destination — today
GoHighLevel (`provider='gohighlevel'`), tomorrow Meta or TikTok directly.
The single physical table `provider_connections` carries any provider; the
`provider` discriminator picks the adapter under
`modules/publishing/infrastructure/adapters/`.

Tokens (access/refresh) and any provider-specific secret live encrypted in
`secrets_encrypted`. Public state (location_id-equivalent, user_id, expires_at)
sits in `config_json` so tooling can query without decrypting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ProviderConnection:
    connection_id: str
    agency_id: str
    provider: str
    external_id: str
    config: Mapping[str, Any] = field(default_factory=dict)
    status: str = "active"
    has_secret: bool = False
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderConnectionWithSecrets(ProviderConnection):
    """Read model for adapters that need the decrypted secret bundle.

    Only the worker decrypts; the API never reads tokens.
    """

    secrets: Mapping[str, Any] = field(default_factory=dict)


__all__ = ["ProviderConnection", "ProviderConnectionWithSecrets"]
