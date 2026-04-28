# Architecture

## Flow

1. WordPress posts to `POST /webhooks/wordpress/property`.
2. Transport validates the request, writes a webhook audit row, and enqueues a job.
3. The dispatcher leases jobs and serializes work by `site_id + property_id` so the same property is never processed concurrently.
4. The pipeline runs five stages: ingest → plan → prepare assets → render reel + poster → publish.
5. Publish persists a media revision and emits an outbox event; social delivery runs through GoHighLevel.

`for_sale` / `to_let` use the full reel template. `sale_agreed`, `sold`, `let_agreed`, `let` use a short status reel with a single moving image.

## Workflow states

`property_pipeline_state` tracks the latest state per property:

`ingested`, `assets_prepared`, `rendered`, `awaiting_review`, `published`, `partial`, `failed`, `skipped`.

`awaiting_review` is the handoff point for a future preview/approval flow. The outbox already emits the events; review itself is optional.

## Modules

### Transport — `services/transport/http/`

`server.py`, `operations.py`, `security.py`. Validates headers and signatures, accepts the webhook, writes audit rows, enqueues jobs, and exposes `/health/live` and `/health/ready`. Readiness is capability-based: core processing can be ready while optional features remain unconfigured.

### Dispatch & queue — `application/dispatch/`, `repositories/stores/job_queue_store.py`

PostgreSQL-backed durable queue with lease-based claims, retry backoff for transient failures, and keyed serialization. Worker count can exceed 1 without breaking property-level ordering.

### Pipeline — `application/pipeline/`

`media_pipeline.py` orchestrates the stages. `media_services.py` wires asset preparation, rendering, and publishing. `content_generation.py` produces deterministic captions behind a boundary so an AI implementation can be swapped in later. `application/admin/` exposes management endpoints for WordPress sources.

### Rendering — `services/media/reel_rendering/`

Builds the reel manifest, computes overlay layout in Python before ffmpeg, renders text that auto-fits / wraps / clamps, omits missing optional fields, and persists the resolved layout in the manifest for audit. ffmpeg paints a layout that's already resolved.

### Social delivery — `services/publishing/social_delivery/`

Uploads media to GoHighLevel, picks one location user and account per platform, publishes sequentially, and applies per-platform validation. GBP posts use the poster image. The job succeeds if at least one platform publishes; only total failure across all requested platforms fails the job.

### Site storage — `services/media/site_storage.py`

Resolves per-site paths under `property_media/<site>/`, `property_media_raw/<site>/`, `generated_media/<site>/reels/`, `generated_media/<site>/posters/`.

## Persistence

PostgreSQL tables (`repositories/postgres/models/`):

- `agencies`, `wordpress_sources` — tenancy
- `properties`, `property_images` — normalized payloads and image metadata
- `property_pipeline_state` — latest workflow + delivery state and current revision id
- `webhook_events` — transport audit
- `job_queue` — durable background work
- `media_revisions` — immutable render history
- `outbox_events` — domain events for downstream consumers
- `scripted_video_artifacts` — scripted render outputs

`media_revisions` separates revision history from mutable current state, which is the foundation for preview, approval, and republish flows.

## Errors and logging

`core/errors.py`, `core/logging.py`. Errors carry `stage`, `code`, `retryable`, `context`, and `external_trace_id`. Console output stays rich for development; the structured fields make stage failures, publish errors, and layout clamps diagnosable in production.

## Outbox events

`media_rendered`, `review_requested`, `publish_completed`, `publish_failed`, `publish_skipped`. Intended consumers: notifications, review workflows, analytics, async AI generation.

## Deployment

- FastAPI behind a reverse proxy with TLS.
- PostgreSQL with the Alembic schema applied.
- One or more workers depending on throughput.
- Forward stdout/stderr to centralized logs.

Rocky Linux specifics: [`deploy/rocky-linux/README.md`](deploy/rocky-linux/README.md).
