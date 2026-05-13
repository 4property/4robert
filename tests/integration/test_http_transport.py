"""Integration coverage for the FastAPI transport.

The webhook is agency-scoped: the WordPress payload identifies the source via
`rest_domain`, the backend resolves the agency, and pulls the GoHighLevel
connection from the agency's stored row. Every test here builds the test
client + seeds the postgres schema fresh, so suites can run in parallel
without leaking state.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

APPLICATION_ROOT = Path(__file__).resolve().parents[2]
if str(APPLICATION_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLICATION_ROOT))

from apps.api.app_factory import build_api_app
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.support.postgres import (
    seed_provider_connection,
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


class _RecordingDispatcher:
    """Stub dispatcher: implements the interface but never spawns workers."""

    def __init__(self, *, accepting_jobs: bool = True) -> None:
        self.accepting_jobs = accepting_jobs

    def start(self) -> None:
        return None

    def stop(self, timeout: float | None = None) -> None:
        del timeout

    def enqueue(self, job) -> None:
        del job

    def wait_for_idle(self, timeout: float = 5.0) -> bool:
        del timeout
        return True

    def is_accepting_jobs(self) -> bool:
        return self.accepting_jobs


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


async def _call_options_preflight(
    app,
    *,
    path: str,
    headers: dict[str, str],
) -> tuple[int, dict[str, str]]:
    messages: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "OPTIONS",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": [
                (name.encode("ascii"), value.encode("ascii"))
                for name, value in headers.items()
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8001),
        },
        receive,
        send,
    )
    start = next(message for message in messages if message["type"] == "http.response.start")
    response_headers = {
        name.decode("latin-1").lower(): value.decode("latin-1")
        for name, value in start["headers"]
    }
    return int(start["status"]), response_headers


_ADMIN_BEARER = {"Authorization": "Bearer test-admin-token"}


class HttpTransportIntegrationTests(unittest.TestCase):
    def _build_client(
        self,
        workspace_dir: Path,
        database_url: str,
        *,
        dispatcher: _RecordingDispatcher | None = None,
        readiness: dict[str, object] | None = None,
        admin_api_token: str = "test-admin-token",
        admin_api_disable_auth_for_testing: bool = False,
        admin_agency_token_secret: str = "test-agency-secret-for-http-transport-suite",
        gohighlevel_app_shared_secret: str = "",
        webhook_auto_provision_unknown_sites_for_testing: bool = False,
    ) -> TestClient:
        active_dispatcher = dispatcher or _RecordingDispatcher()
        readiness_payload = readiness or {"ready": True}
        app = build_api_app(
            workspace_dir=workspace_dir,
            database_locator=database_url,
            admin_api_enabled=True,
            admin_api_token=admin_api_token,
            admin_api_disable_auth_for_testing=admin_api_disable_auth_for_testing,
            admin_agency_token_secret=admin_agency_token_secret,
            gohighlevel_app_shared_secret=gohighlevel_app_shared_secret,
            webhook_auto_provision_unknown_sites_for_testing=(
                webhook_auto_provision_unknown_sites_for_testing
            ),
            site_secrets={},
            enable_docs=False,
            security_disabled=True,
            job_max_attempts=3,
            dispatcher_accepting_jobs=active_dispatcher.is_accepting_jobs,
            readiness_provider=lambda: readiness_payload,
        )
        return TestClient(app)

    # â”€â”€ Health â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_health_endpoints_return_minimal_payloads(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                client = self._build_client(workspace_dir, database.url)
                self.assertEqual(client.get("/health/live").json(), {"status": "ok"})
                self.assertEqual(
                    client.get("/health").json(),
                    {"status": "ready", "dispatcher_accepting_jobs": True},
                )
                self.assertEqual(
                    client.get("/health/ready").json(),
                    {"status": "ready", "dispatcher_accepting_jobs": True},
                )

    def test_health_endpoints_include_paused_dispatcher_state(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                client = self._build_client(
                    workspace_dir,
                    database.url,
                    dispatcher=_RecordingDispatcher(accepting_jobs=False),
                )
                self.assertEqual(
                    client.get("/health").json(),
                    {"status": "ready", "dispatcher_accepting_jobs": False},
                )

    def test_cors_allows_private_network_preflight_for_local_ghl_embed(self) -> None:
        with temporary_workspace() as workspace_dir:
            app = build_api_app(
                workspace_dir=workspace_dir,
                database_locator=DATABASE_URL,
                admin_api_enabled=True,
                admin_api_token="test-admin-token",
                admin_api_disable_auth_for_testing=False,
                admin_agency_token_secret="test-agency-secret-for-cors-suite",
                gohighlevel_app_shared_secret="test-shared-secret",
                site_secrets={},
                enable_docs=False,
                security_disabled=True,
                job_max_attempts=3,
                readiness_provider=lambda: {"ready": True},
            )
            status_code, headers = asyncio.run(
                _call_options_preflight(
                    app,
                    path="/v1/sessions/gohighlevel/context",
                    headers={
                        "origin": "https://app.gohighlevel.com",
                        "access-control-request-method": "POST",
                        "access-control-request-headers": "content-type",
                        "access-control-request-private-network": "true",
                    },
                )
            )

            self.assertEqual(status_code, 200)
            self.assertEqual(headers["access-control-allow-origin"], "*")
            self.assertEqual(headers["access-control-allow-private-network"], "true")

    # â”€â”€ Webhook â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_webhook_resolves_agency_from_rest_domain_and_uses_stored_ghl_connection(
        self,
    ) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                seeded = seed_tenant(database.url, site_id="ckp.ie")
                seed_provider_connection(
                    database.url,
                    agency_id=seeded.agency_id,
                    external_id="loc-1",
                    secrets={"access_token": "token-1"},
                )
                client = self._build_client(workspace_dir, database.url)

                response = client.post(
                    "/v1/ingest/wordpress/property",
                    json={
                        "id": 173757,
                        "slug": "sample-property",
                        "rest_domain": seeded.site_id,
                    },
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(response.status_code, 202, response.text)
                payload = response.json()

                with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                    assert uow.delivery is not None
                    event = uow.delivery.webhook_events.get_event(payload["event_id"])
                    job = uow.delivery.jobs.get_job(payload["job_id"])

                assert event is not None
                assert job is not None
                self.assertEqual(event.agency_id, seeded.agency_id)
                self.assertEqual(event.ingestion_source_id, seeded.ingestion_source_id)
                self.assertEqual(job.agency_id, seeded.agency_id)
                bundle = json.loads(job.provider_secret_bundle)
                self.assertEqual(bundle["access_token"], "token-1")
                self.assertEqual(bundle["provider"], "gohighlevel")

    def test_webhook_rejects_unknown_site(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                client = self._build_client(workspace_dir, database.url)

                response = client.post(
                    "/v1/ingest/wordpress/property",
                    json={"id": 1, "slug": "unknown", "rest_domain": "ghost.ie"},
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["code"], "UNKNOWN_WORDPRESS_SITE")

    def test_webhook_rejects_when_agency_has_no_ghl_connection(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                seeded = seed_tenant(database.url, site_id="ckp.ie")
                client = self._build_client(workspace_dir, database.url)

                response = client.post(
                    "/v1/ingest/wordpress/property",
                    json={
                        "id": 1,
                        "slug": "no-conn",
                        "rest_domain": seeded.site_id,
                    },
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["code"], "GHL_CONNECTION_NOT_FOUND")

    def test_webhook_acceptance_still_enqueues_when_dispatcher_reports_paused(
        self,
    ) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                seeded = seed_tenant(database.url, site_id="ckp.ie")
                seed_provider_connection(database.url, agency_id=seeded.agency_id)
                client = self._build_client(
                    workspace_dir,
                    database.url,
                    dispatcher=_RecordingDispatcher(accepting_jobs=False),
                )

                response = client.post(
                    "/v1/ingest/wordpress/property",
                    json={
                        "id": 9,
                        "slug": "paused",
                        "rest_domain": seeded.site_id,
                    },
                    headers={"Content-Type": "application/json"},
                )
                self.assertEqual(response.status_code, 202)
                payload = response.json()
                with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                    assert uow.delivery is not None
                    job = uow.delivery.jobs.get_job(payload["job_id"])
                self.assertIsNotNone(job)

    # â”€â”€ GoHighLevel session endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_gohighlevel_session_returns_agency_id_when_connection_is_saved(
        self,
    ) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                seeded = seed_tenant(database.url, site_id="ckp.ie")
                seed_provider_connection(
                    database.url,
                    agency_id=seeded.agency_id,
                    external_id="loc-1",
                )
                client = self._build_client(workspace_dir, database.url)

                response = client.post(
                    "/v1/sessions/gohighlevel/session",
                    json={"location_id": "loc-1", "user_id": "user-1"},
                )
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertTrue(payload["connected"])
                self.assertEqual(payload["agency_id"], seeded.agency_id)

    def test_gohighlevel_session_reports_disconnected_when_no_connection(
        self,
    ) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                client = self._build_client(workspace_dir, database.url)

                response = client.post(
                    "/v1/sessions/gohighlevel/session",
                    json={"location_id": "loc-x", "user_id": "user-x"},
                )
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertFalse(payload["connected"])
                self.assertIsNone(payload["agency_id"])

    def test_gohighlevel_context_decrypts_custom_page_payload(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                shared_secret = "test-shared-secret"
                client = self._build_client(
                    workspace_dir,
                    database.url,
                    gohighlevel_app_shared_secret=shared_secret,
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
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["location_id"], "loc-1")
                self.assertEqual(payload["user_id"], "user-1")

    def test_gohighlevel_context_requires_shared_secret(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                client = self._build_client(workspace_dir, database.url)
                response = client.post(
                    "/v1/sessions/gohighlevel/context",
                    json={"encryptedData": "not-real"},
                )
                self.assertEqual(response.status_code, 503)
                self.assertEqual(
                    response.json()["code"], "GHL_CONTEXT_DECRYPT_FAILED"
                )

    # â”€â”€ Admin auth gate â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_admin_routes_require_bearer_token(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                client = self._build_client(workspace_dir, database.url)
                response = client.get("/v1/admin/agencies")
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["code"], "ADMIN_AUTH_REQUIRED")

    def test_admin_routes_can_disable_auth_for_testing(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                client = self._build_client(
                    workspace_dir,
                    database.url,
                    admin_api_disable_auth_for_testing=True,
                    admin_api_token="",
                )
                response = client.get("/v1/admin/agencies")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["count"], 0)

    # â”€â”€ Admin: agencies CRUD â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_admin_can_create_get_and_delete_an_agency(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                client = self._build_client(workspace_dir, database.url)

                created = client.post(
                    "/v1/admin/agencies",
                    json={"name": "CKP", "timezone": "Europe/Dublin"},
                    headers=_ADMIN_BEARER,
                )
                self.assertEqual(created.status_code, 201, created.text)
                agency_id = created.json()["agency"]["agency_id"]

                detail = client.get(
                    f"/v1/admin/agencies/{agency_id}",
                    headers=_ADMIN_BEARER,
                )
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(detail.json()["agency"]["name"], "CKP")

                deleted = client.delete(
                    f"/v1/admin/agencies/{agency_id}",
                    headers=_ADMIN_BEARER,
                )
                self.assertEqual(deleted.status_code, 200)

                with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                    assert uow.tenancy is not None
                    self.assertIsNone(uow.tenancy.agencies.get_by_id(agency_id))

    # â”€â”€ Admin: WordPress sources â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_admin_can_provision_a_wordpress_source_with_global_endpoint(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                client = self._build_client(workspace_dir, database.url)

                response = client.put(
                    "/v1/admin/wordpress-sources/ckp.ie",
                    json={
                        "source_name": "CKP",
                        "agency_name": "CKP Estate Agents",
                        "agency_slug": "ckp",
                        "agency_timezone": "Europe/Dublin",
                    },
                    headers=_ADMIN_BEARER,
                )
                self.assertEqual(response.status_code, 201, response.text)
                payload = response.json()
                self.assertEqual(payload["status"], "created")
                self.assertEqual(payload["source"]["site_id"], "ckp.ie")

                with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                    assert uow.ingestion is not None
                    record = uow.ingestion.sources.get_by_kind_external_id(
                        kind="wordpress", external_id="ckp.ie"
                    )
                self.assertIsNotNone(record)

    # â”€â”€ Admin: GHL connection per agency â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_admin_upserts_and_reads_ghl_connection_for_an_agency(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                seeded = seed_tenant(database.url, site_id="ckp.ie")
                client = self._build_client(workspace_dir, database.url)

                attach = client.post(
                    f"/v1/admin/agencies/{seeded.agency_id}/ghl-connection",
                    json={
                        "location_id": "loc-9",
                        "user_id": "user-9",
                        "access_token": "tok-9",
                    },
                    headers=_ADMIN_BEARER,
                )
                self.assertEqual(attach.status_code, 200, attach.text)
                self.assertNotIn("tok-9", attach.text)

                with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                    assert uow.publishing is not None
                    saved = uow.publishing.connections.get_with_secrets(
                        agency_id=seeded.agency_id,
                        provider="gohighlevel",
                    )
                assert saved is not None
                self.assertEqual(saved.external_id, "loc-9")
                self.assertEqual(saved.secrets.get("access_token"), "tok-9")

    # â”€â”€ Admin: per-section reel-profile endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_brand_endpoint_only_touches_its_section(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                seeded = seed_tenant(database.url, site_id="ckp.ie")
                client = self._build_client(workspace_dir, database.url)

                # Pre-populate an unrelated section so we can prove the brand
                # PUT does not stomp it.
                with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                    assert uow.configuration is not None
                    uow.configuration.automation.upsert(
                        agency_id=seeded.agency_id,
                        approval_required=True,
                        publish_window_start="08:00",
                    )

                resp = client.put(
                    f"/v1/admin/agencies/{seeded.agency_id}/brand",
                    json={
                        "primary_color": "#0F172A",
                        "secondary_color": "#FFFFFF",
                        "logo_position": "top-right",
                        "font_family": "Inter",
                    },
                    headers=_ADMIN_BEARER,
                )
                self.assertEqual(resp.status_code, 200, resp.text)
                self.assertEqual(resp.json()["brand"]["primary_color"], "#0F172A")

                with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                    assert uow.configuration is not None
                    saved_brand = uow.configuration.brand.get(seeded.agency_id)
                    saved_automation = uow.configuration.automation.get(
                        seeded.agency_id
                    )
                assert saved_brand is not None
                self.assertEqual(saved_brand.primary_color, "#0F172A")
                self.assertEqual(saved_brand.font_family, "Inter")
                # Sibling section stayed intact.
                assert saved_automation is not None
                self.assertTrue(saved_automation.approval_required)
                self.assertEqual(saved_automation.publish_window_start, "08:00")

    def test_automation_endpoint_drives_approval_required(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                seeded = seed_tenant(database.url, site_id="ckp.ie")
                client = self._build_client(workspace_dir, database.url)

                resp = client.put(
                    f"/v1/admin/agencies/{seeded.agency_id}/automation",
                    json={
                        "approval_required": True,
                        "publish_window_start": "09:00",
                        "publish_window_end": "20:00",
                    },
                    headers=_ADMIN_BEARER,
                )
                self.assertEqual(resp.status_code, 200, resp.text)
                self.assertTrue(resp.json()["automation"]["approval_required"])

                with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                    assert uow.configuration is not None
                    saved = uow.configuration.automation.get(seeded.agency_id)
                assert saved is not None
                self.assertTrue(saved.approval_required)
                self.assertEqual(saved.publish_window_start, "09:00")
                self.assertEqual(saved.publish_window_end, "20:00")

    def test_social_templates_endpoint_persists_per_network_templates(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                seeded = seed_tenant(database.url, site_id="ckp.ie")
                client = self._build_client(workspace_dir, database.url)

                resp = client.put(
                    f"/v1/admin/agencies/{seeded.agency_id}/social-templates",
                    json={
                        "templates": {
                            "instagram": "{{property_title}} Â· {{price}}",
                            "tiktok": "Just listed: {{property_title}}",
                        }
                    },
                    headers=_ADMIN_BEARER,
                )
                self.assertEqual(resp.status_code, 200, resp.text)

                with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                    assert uow.configuration is not None
                    saved = uow.configuration.social_templates.list_for_agency(
                        seeded.agency_id
                    )
                templates_by_platform = {
                    record.platform: record.description_template
                    for record in saved
                }
                self.assertEqual(
                    templates_by_platform["instagram"],
                    "{{property_title}} Â· {{price}}",
                )
                self.assertEqual(
                    templates_by_platform["tiktok"],
                    "Just listed: {{property_title}}",
                )

    # â”€â”€ Admin: read-only content surfaces â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def test_admin_reels_listing_is_empty_for_a_fresh_agency(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                seeded = seed_tenant(database.url, site_id="ckp.ie")
                client = self._build_client(workspace_dir, database.url)

                resp = client.get(
                    f"/v1/admin/agencies/{seeded.agency_id}/reels",
                    headers=_ADMIN_BEARER,
                )
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json(), {"items": [], "count": 0})

    def test_admin_social_accounts_returns_disconnected_when_no_ghl(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                seeded = seed_tenant(database.url, site_id="ckp.ie")
                client = self._build_client(workspace_dir, database.url)

                resp = client.get(
                    f"/v1/admin/agencies/{seeded.agency_id}/social-accounts",
                    headers=_ADMIN_BEARER,
                )
                self.assertEqual(resp.status_code, 200)
                payload = resp.json()
                self.assertFalse(payload["connected"])
                self.assertEqual(payload["reason"], "GHL_CONNECTION_NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
