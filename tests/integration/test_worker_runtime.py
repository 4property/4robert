from __future__ import annotations

import unittest
from datetime import datetime, timezone
from uuid import uuid4

from apps.worker.runtime import JobDispatcher, WorkerSettings
from modules.delivery.domain import Job, JobEnqueueRequest
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from shared.errors import TransientSocialPublishingError
from tests.support.postgres import (
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


class WorkerRuntimeIntegrationTests(unittest.TestCase):
    def test_dispatcher_processes_ready_job_and_updates_webhook_event(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                tenant = seed_tenant(database.url, site_id="worker-success.test")
                job_id, event_id = _enqueue_job(
                    database.url,
                    agency_id=tenant.agency_id,
                    ingestion_source_id=tenant.ingestion_source_id,
                    external_source_id=tenant.external_source_id,
                    property_id=101,
                )
                seen_jobs: list[Job] = []
                dispatcher = JobDispatcher(
                    settings=WorkerSettings(
                        base_dir=workspace_dir,
                        database_locator=database.url,
                    )
                )
                dispatcher.register_handler(
                    "reel_publish",
                    lambda job: seen_jobs.append(job) or {"ok": True},
                )

                processed = dispatcher._process_next_job("worker-test")

                self.assertTrue(processed)
                self.assertEqual([job.job_id for job in seen_jobs], [job_id])
                with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                    job = uow.delivery.jobs.get_job(job_id)
                    event = uow.delivery.webhook_events.get_event(event_id)
                self.assertIsNotNone(job)
                self.assertEqual(job.status, "completed")
                self.assertEqual(job.provider_secret_bundle, "")
                self.assertIsNotNone(event)
                self.assertEqual(event.status, "completed")
                self.assertIsNone(event.error_message)

    def test_dispatcher_requeues_retryable_failure_and_updates_webhook_event(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                tenant = seed_tenant(database.url, site_id="worker-retry.test")
                job_id, event_id = _enqueue_job(
                    database.url,
                    agency_id=tenant.agency_id,
                    ingestion_source_id=tenant.ingestion_source_id,
                    external_source_id=tenant.external_source_id,
                    property_id=202,
                    max_attempts=3,
                )
                dispatcher = JobDispatcher(
                    settings=WorkerSettings(
                        base_dir=workspace_dir,
                        database_locator=database.url,
                        retry_backoff_seconds=0.0,
                    )
                )

                def fail_retryable(job: Job) -> object:
                    raise TransientSocialPublishingError("temporary upstream failure")

                dispatcher.register_handler("reel_publish", fail_retryable)

                processed = dispatcher._process_next_job("worker-test")

                self.assertTrue(processed)
                with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                    job = uow.delivery.jobs.get_job(job_id)
                    event = uow.delivery.webhook_events.get_event(event_id)
                self.assertIsNotNone(job)
                self.assertEqual(job.status, "queued")
                self.assertEqual(job.attempt_count, 1)
                self.assertEqual(job.last_error, "temporary upstream failure")
                self.assertIsNotNone(event)
                self.assertEqual(event.status, "queued")
                self.assertEqual(event.error_message, "temporary upstream failure")


def _enqueue_job(
    database_url: str,
    *,
    agency_id: str,
    ingestion_source_id: str,
    external_source_id: str,
    property_id: int,
    max_attempts: int = 1,
) -> tuple[str, str]:
    now = datetime.now(timezone.utc).isoformat()
    job_id = str(uuid4())
    event_id = str(uuid4())
    with DatabaseUnitOfWork(database_url) as uow:
        uow.delivery.webhook_events.create_event(
            event_id=event_id,
            agency_id=agency_id,
            ingestion_source_id=ingestion_source_id,
            external_source_id=external_source_id,
            source_kind="wordpress",
            property_id=property_id,
            received_at=now,
            raw_payload_hash="hash-test",
            status="queued",
        )
        uow.delivery.jobs.enqueue_job(
            JobEnqueueRequest(
                job_id=job_id,
                event_id=event_id,
                agency_id=agency_id,
                ingestion_source_id=ingestion_source_id,
                kind="reel_publish",
                external_source_id=external_source_id,
                property_id=property_id,
                received_at=now,
                raw_payload_hash="hash-test",
                payload={"id": property_id, "slug": "home"},
                publish_context={
                    "provider": "gohighlevel",
                    "location_id": "loc-test",
                    "platforms": ["instagram"],
                },
                provider_secret_bundle="token-test",
                max_attempts=max_attempts,
                available_at=now,
                created_at=now,
            )
        )
    return job_id, event_id


if __name__ == "__main__":
    unittest.main()
