"""Unit tests for `build_property_media_job` access-token unwrapping.

Regression coverage for the production hotfix where the orchestrator was
forwarding the full provider secret JSON blob as the GHL Bearer token
(`{"access_token": "pit-...", "provider": "gohighlevel"}`), producing
``401 Invalid JWT``. The bundle persisted in ``jobs.provider_secrets_encrypted``
is a JSON object; ``build_property_media_job`` must pull the
``access_token`` field out of it before handing the publish context to
the social publisher.

Three flavours of bundle are exercised:

* JSON object → token field is extracted (the production happy path).
* Empty string → no override; ``SocialPublishContext.access_token`` ends
  up empty without crashing the worker.
* Raw non-JSON string (legacy / scripted_render path) → forwarded as-is
  so older queued jobs keep working.
"""

from __future__ import annotations

import json
import unittest

from modules.delivery.domain import Job
from modules.reels.application.orchestrator import build_property_media_job


def _make_job(
    *,
    provider_secret_bundle: str,
    publish_context: dict[str, object] | None = None,
) -> Job:
    if publish_context is None:
        publish_context = {
            "provider": "gohighlevel",
            "location_id": "loc1",
            "platforms": ["tiktok"],
        }
    return Job(
        job_id="job-1",
        event_id="event-1",
        agency_id="agency-1",
        ingestion_source_id="source-1",
        kind="reel_publish",
        external_source_id="example.test",
        property_id=123,
        received_at="2026-05-12T12:00:00+00:00",
        raw_payload_hash="hash-1",
        status="processing",
        payload={"id": 123},
        publish_context=publish_context,
        provider_secret_bundle=provider_secret_bundle,
        attempt_count=1,
        max_attempts=3,
        available_at="2026-05-12T12:00:00+00:00",
        lease_expires_at=None,
        worker_id="worker-1",
        last_error=None,
        created_at="2026-05-12T12:00:00+00:00",
        updated_at="2026-05-12T12:00:00+00:00",
        finished_at=None,
        superseded_by_job_id="",
    )


class BuildPropertyMediaJobAccessTokenTests(unittest.TestCase):
    def test_json_bundle_unwraps_access_token_field(self) -> None:
        bundle = json.dumps(
            {"access_token": "pit-test-12345", "provider": "gohighlevel"},
            ensure_ascii=False,
            sort_keys=True,
        )
        job = _make_job(provider_secret_bundle=bundle)

        media_job = build_property_media_job(job)

        self.assertIsNotNone(media_job.publish_context)
        assert media_job.publish_context is not None
        self.assertEqual(
            media_job.publish_context.access_token, "pit-test-12345"
        )
        # Defensive: the raw JSON blob must never leak into the token slot.
        self.assertNotIn(
            "access_token", media_job.publish_context.access_token
        )
        self.assertNotIn("{", media_job.publish_context.access_token)

    def test_empty_bundle_leaves_access_token_empty(self) -> None:
        job = _make_job(provider_secret_bundle="")

        media_job = build_property_media_job(job)

        self.assertIsNotNone(media_job.publish_context)
        assert media_job.publish_context is not None
        self.assertEqual(media_job.publish_context.access_token, "")

    def test_non_json_bundle_is_forwarded_as_raw_token(self) -> None:
        job = _make_job(provider_secret_bundle="raw-token-abc")

        media_job = build_property_media_job(job)

        self.assertIsNotNone(media_job.publish_context)
        assert media_job.publish_context is not None
        self.assertEqual(
            media_job.publish_context.access_token, "raw-token-abc"
        )

    def test_json_bundle_missing_access_token_falls_back_to_raw(self) -> None:
        bundle = json.dumps({"provider": "gohighlevel"})
        job = _make_job(provider_secret_bundle=bundle)

        media_job = build_property_media_job(job)

        self.assertIsNotNone(media_job.publish_context)
        assert media_job.publish_context is not None
        # No ``access_token`` field in the bundle → fall back to the raw
        # serialized payload so legacy/scripted jobs keep flowing.
        self.assertEqual(media_job.publish_context.access_token, bundle)


if __name__ == "__main__":
    unittest.main()
