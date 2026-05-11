"""Integration tests for the GoHighLevel sessions router."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.publishing.application.use_cases.probe_provider_connection import (
    ProbeProviderConnectionUseCase,
)
from modules.publishing.transport.http.sessions_router import create_sessions_router
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.support.postgres import (
    seed_provider_connection,
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


@dataclass(frozen=True, slots=True)
class _Account:
    id: str
    name: str
    platform: str
    account_type: str
    is_expired: bool


def _build_client(
    *,
    database_url: str,
    workspace_dir: Path,
    shared_secret: str = "",
    agency_token_secret: str = "",
    agency_token_ttl_seconds: int = 3600,
    admin_disable_auth_for_testing: bool = False,
    probe_provider_connection: ProbeProviderConnectionUseCase | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_sessions_router(
            unit_of_work_factory=lambda: DatabaseUnitOfWork(database_url, workspace_dir),
            shared_secret=shared_secret,
            agency_token_secret=agency_token_secret,
            agency_token_ttl_seconds=agency_token_ttl_seconds,
            admin_disable_auth_for_testing=admin_disable_auth_for_testing,
            probe_provider_connection=probe_provider_connection,
        )
    )
    return TestClient(app)


def test_tokens_lists_saved_gohighlevel_connections_without_plaintext_tokens() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            connection_id = seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                config={"user_id": "user-1", "expires_at": "2026-05-01T00:00:00Z"},
                secrets={
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_at": "2026-05-01T00:00:00Z",
                },
            )
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.get("/v1/sessions/gohighlevel/tokens")

            assert response.status_code == 200
            payload = response.json()
            assert payload["count"] == 1
            assert payload["items"] == [
                {
                    "connection_id": connection_id,
                    "agency_id": seeded.agency_id,
                    "location_id": "loc-1",
                    "user_id": "user-1",
                    "has_access_token": True,
                    "has_refresh_token": True,
                    "expires_at": "2026-05-01T00:00:00Z",
                    "status": "active",
                    "created_at": payload["items"][0]["created_at"],
                    "updated_at": payload["items"][0]["updated_at"],
                }
            ]
            assert "access_token" not in payload["items"][0]
            assert "refresh_token" not in payload["items"][0]


def test_context_decrypts_custom_page_payload() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            shared_secret = "test-shared-secret"
            client = _build_client(
                database_url=database.url,
                workspace_dir=workspace_dir,
                shared_secret=shared_secret,
            )
            encrypted_payload = _encrypt_cryptojs_payload(
                {
                    "userId": "user-1",
                    "companyId": "agency-1",
                    "role": "admin",
                    "type": "agency",
                    "activeLocation": "loc-1",
                    "userName": "Jane Admin",
                    "email": "jane@example.test",
                },
                shared_secret=shared_secret,
            )

            response = client.post(
                "/v1/sessions/gohighlevel/context",
                json={"encryptedData": encrypted_payload},
            )

            assert response.status_code == 200
            payload = response.json()
            assert payload["ok"] is True
            assert payload["source"] == "ghl-sso-decrypted"
            assert payload["location_id"] == "loc-1"
            assert payload["user_id"] == "user-1"


def test_session_reports_connected_agency_for_saved_location() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "access-token"},
            )
            client = _build_client(
                database_url=database.url,
                workspace_dir=workspace_dir,
                admin_disable_auth_for_testing=True,
            )

            response = client.post(
                "/v1/sessions/gohighlevel/session",
                json={"location_id": "loc-1", "user_id": "user-1"},
            )

            assert response.status_code == 200
            assert response.json() == {
                "ok": True,
                "location_id": "loc-1",
                "user_id": "user-1",
                "connected": True,
                "has_token": True,
                "agency_id": seeded.agency_id,
            }


def test_session_emits_agency_token_when_secret_configured() -> None:
    """When the secret is set and the location is connected, the response
    includes a decodable JWT and an ISO-8601 expiry."""
    from apps.api.agency_token import decode_agency_token

    secret = "test-agency-secret-please-make-it-32-bytes-long-okay"
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "access-token"},
            )
            client = _build_client(
                database_url=database.url,
                workspace_dir=workspace_dir,
                agency_token_secret=secret,
                agency_token_ttl_seconds=3600,
            )

            response = client.post(
                "/v1/sessions/gohighlevel/session",
                json={"location_id": "loc-1", "user_id": "user-1"},
            )

            assert response.status_code == 200
            payload = response.json()
            assert payload["connected"] is True
            assert payload["agency_id"] == seeded.agency_id
            assert isinstance(payload["agency_token"], str) and payload["agency_token"]
            assert payload["agency_token_expires_at"].endswith("Z")
            claims = decode_agency_token(payload["agency_token"], secret=secret)
            assert claims.agency_id == seeded.agency_id
            assert claims.location_id == "loc-1"
            assert claims.user_id == "user-1"
            assert claims.scope == "agency"


def test_session_omits_agency_token_when_not_connected() -> None:
    secret = "test-agency-secret-please-make-it-32-bytes-long-okay"
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(
                database_url=database.url,
                workspace_dir=workspace_dir,
                agency_token_secret=secret,
            )
            response = client.post(
                "/v1/sessions/gohighlevel/session",
                json={"location_id": "loc-orphan", "user_id": "user-1"},
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["connected"] is False
            assert "agency_token" not in payload
            assert "agency_token_expires_at" not in payload


def test_session_returns_503_when_secret_unset_and_auth_not_bypassed() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "access-token"},
            )
            client = _build_client(
                database_url=database.url,
                workspace_dir=workspace_dir,
                # agency_token_secret defaults to "" and bypass is False
            )
            response = client.post(
                "/v1/sessions/gohighlevel/session",
                json={"location_id": "loc-1", "user_id": "user-1"},
            )
            assert response.status_code == 503
            assert response.json()["code"] == "AGENCY_AUTH_NOT_CONFIGURED"


def test_probe_uses_saved_token_and_returns_social_accounts() -> None:
    captured: dict[str, str] = {}

    def account_lister(*, location_id: str, access_token: str) -> tuple[_Account, ...]:
        captured["location_id"] = location_id
        captured["access_token"] = access_token
        return (
            _Account(
                id="acct-1",
                name="Instagram",
                platform="instagram",
                account_type="business",
                is_expired=False,
            ),
        )

    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            seeded = seed_tenant(database.url, site_id="ckp.ie")
            seed_provider_connection(
                database.url,
                agency_id=seeded.agency_id,
                external_id="loc-1",
                secrets={"access_token": "access-token"},
            )
            client = _build_client(
                database_url=database.url,
                workspace_dir=workspace_dir,
                probe_provider_connection=ProbeProviderConnectionUseCase(
                    account_lister=account_lister,
                ),
            )

            response = client.post(
                "/v1/sessions/gohighlevel/test",
                json={"location_id": "loc-1"},
            )

            assert response.status_code == 200
            assert captured == {"location_id": "loc-1", "access_token": "access-token"}
            assert response.json() == {
                "ok": True,
                "location_id": "loc-1",
                "account_count": 1,
                "accounts": [
                    {
                        "id": "acct-1",
                        "name": "Instagram",
                        "platform": "instagram",
                        "account_type": "business",
                        "is_expired": False,
                    }
                ],
            }


def test_probe_returns_not_found_when_location_has_no_connection() -> None:
    with temporary_workspace() as workspace_dir:
        with temporary_postgres_schema(DATABASE_URL) as database:
            client = _build_client(database_url=database.url, workspace_dir=workspace_dir)

            response = client.post(
                "/v1/sessions/gohighlevel/test",
                json={"location_id": "loc-missing"},
            )

            assert response.status_code == 404
            assert response.json()["code"] == "GHL_CONNECTION_NOT_FOUND"


def _encrypt_cryptojs_payload(
    payload: dict[str, object],
    *,
    shared_secret: str,
    salt: bytes = b"12345678",
) -> str:
    key, iv = _derive_cryptojs_key_and_iv(
        password=shared_secret.encode("utf-8"),
        salt=salt,
    )
    padder = padding.PKCS7(128).padder()
    plaintext = json.dumps(payload).encode("utf-8")
    padded_plaintext = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded_plaintext) + encryptor.finalize()
    return base64.b64encode(b"Salted__" + salt + ciphertext).decode("ascii")


def _derive_cryptojs_key_and_iv(*, password: bytes, salt: bytes) -> tuple[bytes, bytes]:
    derived = b""
    previous = b""
    while len(derived) < 48:
        previous = hashlib.md5(previous + password + salt).digest()  # noqa: S324
        derived += previous
    return derived[:32], derived[32:48]
