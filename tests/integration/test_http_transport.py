from __future__ import annotations

import sys
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

APPLICATION_ROOT = Path(__file__).resolve().parents[2]
if str(APPLICATION_ROOT) not in sys.path:
    sys.path.insert(0, str(APPLICATION_ROOT))

from repositories.stores.job_queue_store import PropertyJobRepository
from repositories.stores.webhook_event_store import WebhookDeliveryRepository
from settings import DATABASE_URL
from services.transport.http.server import WordPressWebhookApplication, create_fastapi_app
from tests.support.postgres import seed_tenant, temporary_postgres_schema, temporary_workspace


class _RecordingDispatcher:
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
        return True


class HttpTransportIntegrationTests(unittest.TestCase):
    def _build_client(self, workspace_dir: Path, database_url: str) -> TestClient:
        runtime = WordPressWebhookApplication(
            workspace_dir,
            dispatcher=_RecordingDispatcher(),
            database_locator=database_url,
            security_disabled=True,
            enable_docs=False,
            site_secrets={},
        )
        runtime.start = lambda: None
        runtime.stop = lambda: None
        runtime.build_readiness_report = lambda: {"ready": True}
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
                self.assertEqual(health.json(), {"status": "ready"})
                self.assertEqual(ready.json(), {"status": "ready"})
                self.assertEqual(live.json(), {"status": "ok"})

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


if __name__ == "__main__":
    unittest.main()
