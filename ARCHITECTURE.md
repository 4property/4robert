# CPIHED Architecture

## Overview

The application is a webhook-driven pipeline for property videos.

1. A WordPress plugin sends a signed property payload to `POST /webhooks/wordpress/property`.
2. The FastAPI adapter validates the request, records a webhook event, and enqueues a job.
3. `PropertyVideoPipeline` orchestrates the runtime modules in this order:
   1. property info ingestion
   2. photo selection
   3. video rendering
   4. video publishing
4. The local `wordpress-webhook-simulator` acts as the stand-in for the future plugin and drives the whole flow in development.

The storage model is multi-site. A property is uniquely identified by `site_id + source_property_id`.

## Modules

### HTTP adapter

File: `services/webhook/server.py`

Responsibilities:

- validate route, method, headers, and JSON body
- verify `X-WordPress-Site-ID`, `X-GoHighLevel-Location-ID`, `X-GoHighLevel-Access-Token`, `X-WordPress-Timestamp`, and `X-WordPress-Signature`
- enforce request size limits
- create a webhook event record for audit and troubleshooting
- create a request-scoped `PropertyVideoJob`, including the current GoHighLevel publish context
- enqueue the job
- return `202 Accepted`

The HTTP adapter is intentionally thin, but it still owns webhook event audit writes because accepted deliveries are recorded at the transport boundary.

### Job dispatcher

File: `application/dispatching.py`

Responsibilities:

- provide a simple `JobDispatcher` interface
- run a bounded in-memory queue
- process jobs with one or more worker threads
- drain in-flight work on shutdown up to a configured timeout

Current limitation:

- the queue is not durable
- queued jobs are lost if the process crashes
- this is acceptable for the current single-node, low-volume deployment
- worker count is intentionally fixed to `1` until keyed locking exists

### Application orchestration

File: `application/property_video_pipeline.py`

Responsibilities:

- make the full workflow readable in one place
- keep the order of the business steps explicit
- depend only on interfaces, not concrete infrastructure

### Property info ingestion

File: `application/default_services.py`

Responsibilities:

- normalize the incoming webhook payload with `Property.from_api_payload()`
- persist the property record
- compute two fingerprints:
  - `content_fingerprint`
  - `publish_target_fingerprint`
- skip duplicate deliveries only when the content fingerprint, publish target fingerprint, and local artifacts all match a completed run
- trigger rerender when property content changes, including `property_status`
- trigger republish without rerender when only the GoHighLevel destination changes
- resolve site-scoped storage paths

Notes:

- the payload field `agent_photo` is stored as `agent_photo_url`
- GoHighLevel access tokens are request-scoped only and are never persisted

### Event tracking

File: `repositories/webhook_event_repository.py`

Responsibilities:

- store one event row per accepted delivery
- track status transitions: `received`, `queued`, `processing`, `completed`, `noop`, `failed`
- store `site_id`, `property_id`, `received_at`, `raw_payload_hash`, and `error_message`

### Photo selection

Files:

- `application/default_services.py`
- `services/wordpress_image/*`

Responsibilities:

- download the candidate property photos
- filter them into the selected set
- save the selected image paths in the repository

The application depends on a photo-selection boundary rather than the concrete heuristic implementation, so this module can later be replaced by a Gemini-backed selector.
The application now uses a Gemini-backed selector that classifies candidate photos, reserves the featured image as the first slide when available, and writes a per-property JSON audit of the decision.

### Video rendering

Files:

- `application/default_services.py`
- `services/property_reel/*`

Responsibilities:

- build the manifest from prepared `PropertyRenderData`
- render the MP4 from prepared `PropertyRenderData`
- write both outputs into a temporary staging directory

The render layer does not query SQLite directly. The application layer prepares the full render input first.

### Video publishing

File: `application/default_services.py`

Responsibilities:

- move staged render outputs into the final site-scoped publish folder
- optionally publish the final MP4 to external social channels through a separate service
- keep the publishing concern separate from the rendering concern

The runtime publisher is `CompositeVideoPublisher`:

- `FileSystemVideoPublisher` writes the final outputs into `generated_reels/<safe_site_id>/`
- `GoHighLevelPropertyPublisher` publishes reels to GoHighLevel Social Planner using the request-scoped publish context from the webhook
- the current external proof of concept publishes only to TikTok
- GoHighLevel publication retries are in-memory only inside the current worker job

## Storage

### Database

File: `repositories/wordpress_property_repository.py`

The repository uses a v2 schema with:

- `record_id` as the internal primary key
- `site_id`
- `source_property_id`
- `UNIQUE(site_id, source_property_id)`
- a dedicated `property_pipeline_state` table for render/publish state

The same SQLite database also stores the `webhook_events` audit table.

The `property_pipeline_state` table stores:

- content and publish fingerprints
- selected image folder
- local manifest and video paths
- render status
- publish status and details
- last published GoHighLevel location id

No raw GoHighLevel access token is stored in SQLite.

Legacy single-site databases are migrated automatically and assigned `LEGACY_SITE_ID`.

### Filesystem

Site-scoped paths are resolved in `services/webhook_transport/site_storage.py`.

Current roots:

- `property_media/<safe_site_id>/`
- `property_media_raw/<safe_site_id>/`
- `generated_reels/<safe_site_id>/`

## Public service layer

The public HTTP entrypoint is now FastAPI.

Reasons:

- the app needs operational endpoints such as liveness and readiness checks
- request handling and validation are clearer than with the previous stdlib adapter
- the HTTP adapter still remains separate from the business pipeline

Recommended production deployment:

- Linux host or container
- reverse proxy with HTTPS termination and rate limiting
- `uvicorn` as the ASGI server

## Simulator Contract

The simulator mirrors the future plugin contract and sends:

- `X-WordPress-Site-ID`
- `X-GoHighLevel-Location-ID`
- `X-GoHighLevel-Access-Token`
- `X-WordPress-Timestamp`
- `X-WordPress-Signature`

The signature covers:

- timestamp
- site id
- GoHighLevel location id
- GoHighLevel access token
- raw JSON body

Per-site webhook secrets and GoHighLevel routing values are configured in `wordpress-webhook-simulator`, not in the main app settings.
