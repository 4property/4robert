from __future__ import annotations

import unittest

from modules.delivery.domain import Job
from modules.reels.application.orchestrator import build_property_media_job


class WorkerRuntimeAdapterTests(unittest.TestCase):
    def test_reel_job_adapter_restores_tenant_and_publish_context(self) -> None:
        job = Job(
            job_id="job-1",
            event_id="event-1",
            agency_id="agency-1",
            ingestion_source_id="source-1",
            kind="reel_publish",
            external_source_id="example.test",
            property_id=123,
            received_at="2026-04-30T12:00:00+00:00",
            raw_payload_hash="hash-1",
            status="processing",
            payload={"id": 123, "slug": "home"},
            publish_context={
                "provider": "gohighlevel",
                "location_id": "loc-1",
                "platforms": ["Instagram", "YouTube"],
                "approval_required": True,
                "social_templates": {"instagram": "caption"},
            },
            provider_secret_bundle="token-1",
            attempt_count=1,
            max_attempts=3,
            available_at="2026-04-30T12:00:00+00:00",
            lease_expires_at=None,
            worker_id="worker-1",
            last_error=None,
            created_at="2026-04-30T12:00:00+00:00",
            updated_at="2026-04-30T12:00:00+00:00",
            finished_at=None,
            superseded_by_job_id="",
        )

        media_job = build_property_media_job(job)

        self.assertEqual(media_job.job_id, "job-1")
        self.assertEqual(media_job.tenant.agency_id, "agency-1")
        self.assertEqual(media_job.tenant.wordpress_source_id, "source-1")
        self.assertEqual(media_job.site_id, "example.test")
        self.assertEqual(media_job.payload["slug"], "home")
        self.assertIsNotNone(media_job.publish_context)
        self.assertEqual(media_job.publish_context.access_token, "token-1")
        self.assertEqual(media_job.publish_context.platforms, ("instagram", "youtube"))
        self.assertTrue(media_job.publish_context.approval_required)


if __name__ == "__main__":
    unittest.main()
