from __future__ import annotations

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

from repositories.stores.agency_store import AgencyStore
from repositories.stores.job_queue_store import PropertyJobRepository
from repositories.stores.webhook_event_store import WebhookDeliveryRepository
from repositories.stores.wordpress_source_store import WordPressSourceStore
from settings import DATABASE_URL
from services.transport.http.server import WordPressWebhookApplication, create_fastapi_app
from tests.support.postgres import seed_tenant, temporary_postgres_schema, temporary_workspace


class _RecordingDispatcher:
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
        gohighlevel_app_shared_secret: str = "",
        webhook_auto_provision_unknown_sites_for_testing: bool = False,
    ) -> TestClient:
        active_dispatcher = dispatcher or _RecordingDispatcher()
        runtime = WordPressWebhookApplication(
            workspace_dir,
            dispatcher=active_dispatcher,
            database_locator=database_url,
            security_disabled=True,
            enable_docs=False,
            site_secrets={},
            admin_api_enabled=True,
            admin_api_token=admin_api_token,
            admin_api_disable_auth_for_testing=admin_api_disable_auth_for_testing,
            gohighlevel_app_shared_secret=gohighlevel_app_shared_secret,
            webhook_auto_provision_unknown_sites_for_testing=webhook_auto_provision_unknown_sites_for_testing,
        )
        runtime.start = lambda: None
        runtime.stop = lambda: None
        runtime.build_readiness_report = lambda: readiness or {
            "ready": True,
            "dispatcher_accepting_jobs": active_dispatcher.is_accepting_jobs(),
        }
        return TestClient(create_fastapi_app(application=runtime))

    def test_health_endpoints_return_minimal_payloads(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                client = self._build_client(workspace_dir, database.url)

                health = client.get("/health")
                live = client.get("/health/live")
                ready = client.get("/health/ready")

                self.assertEqual(health.status_code, 200)
                self.assertEqual(ready.status_code, 200)
                self.assertEqual(live.status_code, 200)
                self.assertEqual(
                    health.json(),
                    {"status": "ready", "dispatcher_accepting_jobs": True},
                )
                self.assertEqual(
                    ready.json(),
                    {"status": "ready", "dispatcher_accepting_jobs": True},
                )
                self.assertEqual(live.json(), {"status": "ok"})

    def test_health_endpoints_include_paused_dispatcher_state(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                client = self._build_client(
                    workspace_dir,
                    database.url,
                    dispatcher=_RecordingDispatcher(accepting_jobs=False),
                )

                health = client.get("/health")
                ready = client.get("/health/ready")

                self.assertEqual(health.status_code, 200)
                self.assertEqual(ready.status_code, 200)
                self.assertEqual(
                    health.json(),
                    {"status": "ready", "dispatcher_accepting_jobs": False},
                )
                self.assertEqual(
                    ready.json(),
                    {"status": "ready", "dispatcher_accepting_jobs": False},
                )

    def test_webhook_acceptance_persists_tenant_columns(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                seeded = seed_tenant(database.url, site_id="site-a")
                client = self._build_client(workspace_dir, database.url)

                response = client.post(
                    "/webhooks/wordpress/property",
                    json={"id": 173757, "slug": "sample-property"},
                    headers={
                        "Content-Type": "application/json",
                        "X-WordPress-Site-ID": seeded.site_id,
                        "X-GoHighLevel-Location-ID": "loc-1",
                        "X-GoHighLevel-Access-Token": "token-1",
                    },
                )

                self.assertEqual(response.status_code, 202)
                payload = response.json()

                with WebhookDeliveryRepository(database.url) as repository:
                    event = repository.get_event(payload["event_id"])
                with PropertyJobRepository(database.url) as repository:
                    job = repository.get_job(payload["job_id"])

                self.assertIsNotNone(event)
                self.assertIsNotNone(job)
                assert event is not None
                assert job is not None
                self.assertEqual(event.agency_id, seeded.agency_id)
                self.assertEqual(event.wordpress_source_id, seeded.wordpress_source_id)
                self.assertEqual(job.agency_id, seeded.agency_id)
                self.assertEqual(job.wordpress_source_id, seeded.wordpress_source_id)
                self.assertEqual(event.site_id, seeded.site_id)
                self.assertEqual(job.site_id, seeded.site_id)

    def test_mvp_token_store_allows_webhook_without_access_token_header(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                seeded = seed_tenant(database.url, site_id="site-a")
                client = self._build_client(workspace_dir, database.url)

                save_response = client.post(
                    "/mvp/gohighlevel/token",
                    json={
                        "location_id": "loc-1",
                        "user_id": "user-1",
                        "access_token": "token-1",
                    },
                )
                self.assertEqual(save_response.status_code, 200)
                self.assertTrue(save_response.json()["token"]["has_access_token"])

                session_response = client.post(
                    "/mvp/gohighlevel/session",
                    json={
                        "location_id": "loc-1",
                        "user_id": "user-1",
                    },
                )
                self.assertEqual(session_response.status_code, 200)
                self.assertTrue(session_response.json()["connected"])

                response = client.post(
                    "/webhooks/wordpress/property",
                    json={"id": 173757, "slug": "sample-property"},
                    headers={
                        "Content-Type": "application/json",
                        "X-WordPress-Site-ID": seeded.site_id,
                        "X-GoHighLevel-Location-ID": "loc-1",
                    },
                )

                self.assertEqual(response.status_code, 202)
                payload = response.json()
                with PropertyJobRepository(database.url) as repository:
                    job = repository.get_job(payload["job_id"])

                self.assertIsNotNone(job)
                assert job is not None
                self.assertEqual(job.gohighlevel_access_token, "token-1")

    def test_mvp_admin_can_list_and_delete_gohighlevel_tokens(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                client = self._build_client(workspace_dir, database.url)

                save_response = client.post(
                    "/mvp/gohighlevel/token",
                    json={
                        "location_id": "loc-admin",
                        "user_id": "admin-user",
                        "access_token": "token-admin",
                    },
                )
                self.assertEqual(save_response.status_code, 200)

                list_response = client.get("/mvp/gohighlevel/tokens")
                self.assertEqual(list_response.status_code, 200)
                self.assertEqual(list_response.json()["count"], 1)
                self.assertEqual(
                    list_response.json()["items"][0]["location_id"],
                    "loc-admin",
                )
                self.assertNotIn("access_token", list_response.json()["items"][0])

                delete_response = client.delete("/mvp/gohighlevel/token/loc-admin")
                self.assertEqual(delete_response.status_code, 200)
                self.assertEqual(delete_response.json()["status"], "deleted")

                session_response = client.post(
                    "/mvp/gohighlevel/session",
                    json={
                        "location_id": "loc-admin",
                        "user_id": "admin-user",
                    },
                )
                self.assertEqual(session_response.status_code, 200)
                self.assertFalse(session_response.json()["connected"])

    def test_mvp_gohighlevel_context_decrypts_custom_page_payload(self) -> None:
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
                    "/mvp/gohighlevel/context",
                    json={"encryptedData": encrypted_payload},
                )

                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertTrue(payload["ok"])
                self.assertEqual(payload["location_id"], "loc-1")
                self.assertEqual(payload["user_id"], "user-1")
                self.assertEqual(payload["user_name"], "Jane Admin")
                self.assertEqual(payload["email"], "jane@example.test")
                self.assertEqual(payload["source"], "ghl-sso-decrypted")

    def test_mvp_gohighlevel_context_requires_shared_secret(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                client = self._build_client(workspace_dir, database.url)

                response = client.post(
                    "/mvp/gohighlevel/context",
                    json={"encryptedData": "not-real"},
                )

                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["code"], "GHL_CONTEXT_DECRYPT_FAILED")

    def test_webhook_without_access_token_header_requires_saved_mvp_token(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                seeded = seed_tenant(database.url, site_id="site-a")
                client = self._build_client(workspace_dir, database.url)

                response = client.post(
                    "/webhooks/wordpress/property",
                    json={"id": 173757, "slug": "sample-property"},
                    headers={
                        "Content-Type": "application/json",
                        "X-WordPress-Site-ID": seeded.site_id,
                        "X-GoHighLevel-Location-ID": "loc-1",
                    },
                )

                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["code"], "GHL_TOKEN_NOT_FOUND")

    def test_webhook_acceptance_still_enqueues_when_dispatcher_reports_paused(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                seeded = seed_tenant(database.url, site_id="site-a")
                client = self._build_client(
                    workspace_dir,
                    database.url,
                    dispatcher=_RecordingDispatcher(accepting_jobs=False),
                )

                response = client.post(
                    "/webhooks/wordpress/property",
                    json={"id": 173757, "slug": "sample-property"},
                    headers={
                        "Content-Type": "application/json",
                        "X-WordPress-Site-ID": seeded.site_id,
                        "X-GoHighLevel-Location-ID": "loc-1",
                        "X-GoHighLevel-Access-Token": "token-1",
                    },
                )

                self.assertEqual(response.status_code, 202)
                payload = response.json()

                with WebhookDeliveryRepository(database.url) as repository:
                    event = repository.get_event(payload["event_id"])
                with PropertyJobRepository(database.url) as repository:
                    job = repository.get_job(payload["job_id"])

                self.assertIsNotNone(event)
                self.assertIsNotNone(job)

    def test_admin_routes_require_bearer_token(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                client = self._build_client(workspace_dir, database.url)

                response = client.get("/admin/wordpress-sources")

                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["code"], "ADMIN_AUTH_REQUIRED")

    def test_admin_put_provisions_wordpress_source(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                client = self._build_client(workspace_dir, database.url)

                response = client.put(
                    "/admin/wordpress-sources/ckp.ie",
                    json={
                        "source_name": "CKP WordPress",
                        "agency_name": "Casey Kennedy Property",
                        "agency_slug": "casey-kennedy-property",
                        "agency_timezone": "Europe/Dublin",
                        "webhook_secret": "admin-test-secret",
                    },
                    headers={"Authorization": "Bearer test-admin-token"},
                )

                self.assertEqual(response.status_code, 201)
                payload = response.json()
                self.assertEqual(payload["status"], "created")
                self.assertEqual(payload["source"]["site_id"], "ckp.ie")
                self.assertTrue(payload["source"]["has_webhook_secret"])
                self.assertEqual(
                    payload["source"]["agency"]["slug"],
                    "casey-kennedy-property",
                )

                with WordPressSourceStore(database.url) as repository:
                    source = repository.get_details_by_site_id("ckp.ie")
                with AgencyStore(database.url) as repository:
                    agency = repository.get_by_id(payload["source"]["agency"]["agency_id"])

                self.assertIsNotNone(source)
                self.assertIsNotNone(agency)
                assert source is not None
                assert agency is not None
                self.assertEqual(source.site_id, "ckp.ie")
                self.assertEqual(source.name, "CKP WordPress")
                self.assertEqual(source.agency_name, "Casey Kennedy Property")
                self.assertEqual(agency.slug, "casey-kennedy-property")

    def test_admin_routes_can_disable_auth_for_testing(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                client = self._build_client(
                    workspace_dir,
                    database.url,
                    admin_api_disable_auth_for_testing=True,
                    admin_api_token="",
                )

                response = client.get("/admin/wordpress-sources")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["count"], 0)

    def test_admin_list_returns_existing_sources(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                seeded = seed_tenant(database.url, site_id="site-a")
                client = self._build_client(workspace_dir, database.url)

                listing = client.get(
                    "/admin/wordpress-sources",
                    headers={"Authorization": "Bearer test-admin-token"},
                )
                detail = client.get(
                    f"/admin/wordpress-sources/{seeded.site_id}",
                    headers={"Authorization": "Bearer test-admin-token"},
                )

                self.assertEqual(listing.status_code, 200)
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(listing.json()["count"], 1)
                self.assertEqual(listing.json()["items"][0]["site_id"], seeded.site_id)
                self.assertEqual(detail.json()["source"]["site_id"], seeded.site_id)

    def test_webhook_acceptance_can_auto_provision_unknown_site_for_testing(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                client = self._build_client(
                    workspace_dir,
                    database.url,
                    webhook_auto_provision_unknown_sites_for_testing=True,
                )

                response = client.post(
                    "/webhooks/wordpress/property",
                    json={"id": 173757, "slug": "sample-property"},
                    headers={
                        "Content-Type": "application/json",
                        "X-WordPress-Site-ID": "ckp.ie",
                        "X-GoHighLevel-Location-ID": "loc-1",
                        "X-GoHighLevel-Access-Token": "token-1",
                    },
                )

                self.assertEqual(response.status_code, 202)
                payload = response.json()
                self.assertTrue(payload["site_auto_provisioned"])
                self.assertEqual(payload["site_id"], "ckp.ie")

                with WordPressSourceStore(database.url) as repository:
                    source = repository.get_details_by_site_id("ckp.ie")
                with WebhookDeliveryRepository(database.url) as repository:
                    event = repository.get_event(payload["event_id"])
                with PropertyJobRepository(database.url) as repository:
                    job = repository.get_job(payload["job_id"])

                self.assertIsNotNone(source)
                self.assertIsNotNone(event)
                self.assertIsNotNone(job)
                assert source is not None
                self.assertEqual(source.status, "active")
                self.assertEqual(source.site_id, "ckp.ie")


if __name__ == "__main__":
    unittest.main()
