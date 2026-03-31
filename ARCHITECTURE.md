# CPIHED Architecture

## Overview

CPIHED is a multi-site property media workflow triggered by WordPress webhooks.

1. A property webhook is accepted at `POST /webhooks/wordpress/property`.
2. The transport layer validates the request, records an audit event, and enqueues durable work in SQLite.
3. The dispatcher processes jobs with keyed serialization by `site_id + property_id` so the same property is not processed concurrently by multiple workers.
4. `PropertyMediaPipeline` executes five stable stages:
   1. ingestion and normalization
   2. campaign planning
   3. asset preparation
   4. reel rendering
   5. local publish and external social delivery
5. Local publish persists a durable media revision and emits an outbox event.
6. Social delivery publishes through GoHighLevel to the configured platforms, recording `published`, `partial`, `failed`, or `skipped` outcomes per property.

The current media output is always a reel video. `for_sale` and `to_let` use the full reel template. `sale_agreed`, `sold`, `let_agreed`, and `let` use a short status reel with a single moving primary image.

## Workflow State

`property_pipeline_state` keeps the latest delivery state for each property. The runtime uses these states today:

- `ingested`
- `assets_prepared`
- `rendered`
- `awaiting_review`
- `published`
- `partial`
- `failed`
- `skipped`

`awaiting_review` is the durable handoff point for a future preview-and-approval flow. The code emits outbox events for that path, but review remains optional and disabled by default.

## Main Modules

### Transport

Files:

- `services/webhook_transport/server.py`
- `services/webhook_transport/operations.py`

Responsibilities:

- validate headers, payload shape, and optional security signature
- accept the current webhook header format
- create webhook audit rows
- enqueue durable jobs
- expose liveness and readiness endpoints

Readiness is capability-based. Core webhook processing can be ready even if optional AI, notification, or review capabilities are not configured.

### Durable Queue and Dispatch

Files:

- `application/dispatching.py`
- `repositories/property_job_repository.py`

Responsibilities:

- durable SQLite-backed queue
- lease-based worker claims
- retry scheduling for transient external failures
- keyed serialization for the same property across multiple workers

This replaces the earlier single-worker-only safety model. Worker count can be greater than `1` without allowing concurrent processing of the same property.

### Application Workflow

Files:

- `application/property_video_pipeline.py`
- `application/media_services.py`
- `application/content_generation.py`
- `application/media_planning.py`

Responsibilities:

- map raw property status into the business lifecycle
- decide render profile and asset strategy
- generate deterministic copy through the `ContentGenerator` boundary
- prepare curated or primary-only assets
- render the reel
- publish locally and externally

The deterministic copy generator is the default implementation today. It is intentionally isolated so future AI-generated captions, narration scripts, or overlay copy can be added without rewriting the renderer or social publisher.

### Rendering

Files:

- `services/reel_rendering/*`

Responsibilities:

- build the reel manifest
- compute a Python-side overlay layout before ffmpeg
- render text blocks that auto-fit, wrap, or clamp safely
- omit optional fields when they are missing
- persist the resolved overlay layout in the manifest for audit and preview use

The layout engine is the authority for text fitting. ffmpeg now paints a resolved layout rather than making ad hoc overflow decisions inline.

### Social Delivery

Files:

- `services/social_delivery/*`

Responsibilities:

- upload media to GoHighLevel
- select one location user and one account per platform
- publish sequentially across the configured platforms
- apply per-platform validation policies
- treat missing accounts or unsupported platforms as partial/skipped results rather than fatal pipeline errors

The job succeeds if at least one platform publishes successfully. Only total failure across all requested platforms fails the job.

## Persistence Model

SQLite stores the full operational state:

- `properties`: normalized property payloads
- `property_images`: downloaded/selected image metadata
- `property_pipeline_state`: latest render and publish state, workflow state, and current revision id
- `webhook_events`: transport audit trail
- `job_queue`: durable background jobs
- `media_revisions`: immutable render revisions
- `outbox_events`: durable domain events for future notification/review consumers

`media_revisions` separates revision history from the mutable current state. That is the foundation for future preview, approval, and republish workflows.

## Filesystem Layout

Site-scoped directories are resolved in `services/webhook_transport/site_storage.py`.

Current roots:

- `property_media/<site>/`
- `property_media_raw/<site>/`
- `generated_media/<site>/reels/`

`generated_media/<site>/reels/` is the canonical output location.

## Logging and Error Model

Files:

- `core/errors.py`
- `core/logging.py`

Errors now carry structured fields:

- `stage`
- `code`
- `retryable`
- `context`
- `external_trace_id`

Rich console output remains for development, but the log content itself now includes enough structured detail to diagnose stage failures, publish API failures, and layout clamp events in deployment.

## Outbox and Future Extensions

The outbox currently records events such as:

- `media_rendered`
- `review_requested`
- `publish_completed`
- `publish_failed`
- `publish_skipped`

That outbox is the intended integration point for:

- email notifications
- preview/review workflows
- analytics or audit sinks
- future asynchronous AI content generation

## Deployment Notes

Recommended production model:

- run FastAPI behind a reverse proxy with HTTPS and rate limiting
- keep SQLite on durable local storage
- run with one or more workers depending on throughput needs
- forward stdout/stderr to centralized logging

Optional capabilities such as AI copy, AI narration, notifications, and review can be enabled incrementally without blocking the core webhook workflow.
