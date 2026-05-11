# Architecture

> **Phase 1 complete (2026-04-30).** Schema, infrastructure, and the API/worker
> process split are in place. The legacy code under `services/`,
> `application/`, `repositories/`, `core/` and `domain/` keeps working through
> compatibility shims; Phase 2 dissolves it into per-module use cases. See
> [REFACTOR_STATUS.md](REFACTOR_STATUS.md) for the running checklist.

## Product

4reels is a multi-tenant SaaS that turns property feeds into vertical reels and
publishes them through social-channel adapters.

```
ingestion source ──► catalog ──► reel pipeline ──► publishing adapter
   (WordPress)      (properties)  (render+poster)    (GoHighLevel)
```

Each tenant ("agency") configures its own ingestion sources, brand assets, reel
defaults, automation rules, social copy templates and publishing connections.
The schema and module layout are designed so that **adding a new ingestion
source or a new publisher is an additive change**: a row in
`ingestion_sources(kind=…)` or `provider_connections(provider=…)` plus an
adapter under the corresponding module. No table is added.

## Top-level layout

```
4reels back/
├── apps/
│   ├── api/            # FastAPI process (HTTP only, no worker threads)
│   └── worker/         # Decoupled worker process (job dispatcher)
├── modules/                 # Bounded contexts
│   ├── tenancy/             # agencies + super-admin + tenant resolution
│   ├── ingestion/           # ingestion_sources(kind) + adapters
│   ├── catalog/             # properties + property_images
│   ├── reels/               # reel pipeline + state + media_revisions
│   ├── configuration/       # brand / defaults / automation / social / music
│   ├── publishing/          # provider_connections(provider) + adapters
│   ├── rendering/           # ffmpeg + layout + photo selection
│   └── delivery/            # jobs + outbox + dispatcher contract
├── shared/                  # Cross-cutting (renamed from `platform/` to
│   │                        #   avoid shadowing Python's stdlib)
│   ├── db/                  # SQLAlchemy session, engine, UoW, security
│   ├── http/                # Shared FastAPI primitives
│   ├── observability/       # logging + persistent events + readiness checks
│   ├── errors/              # ApplicationError + subclasses
│   ├── locking/             # exclusive_file_lock
│   ├── crypto/              # secret_box for encrypting tokens at rest
│   ├── storage/             # site storage path resolution
│   └── media_cleanup/       # raw + temporary file cleanup
├── settings/                # Split by concern
├── alembic/versions/
│   └── 20260501_0001_initial_schema.py    # Single clean migration
├── compose.yml              # postgres + api + worker as separate services
└── tests/{unit,integration,support}/
```

Each module is internally split into:

```
modules/<bounded-context>/
├── domain/           # Plain Python value objects, no SQLAlchemy
├── application/      # Use cases — one verb-resource per file
│   └── use_cases/
├── infrastructure/   # SQLAlchemy repositories, external clients
└── transport/        # FastAPI routers + Pydantic payloads
```

**Module rules**

- A module may import from `shared/` and from another module's `domain/`.
- A module may **not** import another module's `application/` or
  `infrastructure/`.
- Cross-module composition lives in `apps/api/app_factory.py` or
  `apps/worker/runtime.py`, never inside a module.

## Schema

A single Alembic migration
([`alembic/versions/20260501_0001_initial_schema.py`](alembic/versions/20260501_0001_initial_schema.py))
defines 16 tables.

| Table | Owner module | Discriminator |
|---|---|---|
| `agencies` | tenancy | — |
| `ingestion_sources` | ingestion | `kind` (`wordpress`, …) |
| `provider_connections` | publishing | `provider` (`gohighlevel`, …) |
| `agency_brand_settings` | configuration | — |
| `agency_reel_defaults` | configuration | — |
| `agency_automation_rules` | configuration | — |
| `agency_social_templates` | configuration | (per-platform PK) |
| `agency_music_tracks` | configuration | — |
| `properties` | catalog | — |
| `property_images` | catalog | — |
| `reels` (was `property_pipeline_state`) | reels | — |
| `media_revisions` | reels | — |
| `webhook_events` | delivery | — |
| `jobs` (was `job_queue`) | delivery | `kind` (`reel_publish`, `scripted_render`) |
| `outbox_events` | delivery | — |
| `scripted_video_artifacts` | reels | — |

Renames captured in the single migration:

| Was | Now |
|---|---|
| `site_id` | `external_source_id` |
| `wordpress_source_id` | `ingestion_source_id` |
| `last_published_location_id` | `last_published_provider_external_id` |
| `gohighlevel_access_token_encrypted` | `provider_secrets_encrypted` |
| JSON-in-`TEXT` columns | `JSONB` |

## Persistence: Unit of Work

[`shared/db/uow.py`](shared/db/uow.py) exposes module-namespaced repositories:

```python
from shared.db import DatabaseUnitOfWork

with DatabaseUnitOfWork() as uow:
    agency = uow.tenancy.agencies.get_by_slug("acme")
    source = uow.ingestion.sources.get_by_kind_external_id(
        kind="wordpress", external_id="acme.example.com",
    )
    ghl = uow.publishing.connections.get_with_secrets(
        agency_id=agency.agency_id, provider="gohighlevel",
    )
```

Each `<Aggregate>Repository` extends
[`shared/db/repository_base.py::ModuleRepository`](shared/db/repository_base.py)
and receives a SQLAlchemy `Session` from the UoW. Repositories never commit on
their own — `__exit__` commits on success and rolls back on exception.

Encryption: secrets that must round-trip (publisher tokens, webhook secrets)
go through [`shared/db/security.py`](shared/db/security.py) (Fernet) before
landing in `*.secrets_encrypted` BYTEA columns.

## API process — `apps/api/`

Stateless FastAPI process. Handles inbound webhooks, admin/tenant management
endpoints, reel preview streaming with HTTP Range requests, and GoHighLevel
session decoding for the embedded app. **The API does not run the dispatcher
loop.** Lifespan only opens the UoW factory and the outbox relay.

URL surface: `/v1/*` (renamed in Phase 3). Health probes at `/health{,/live,/ready}`.

## Worker process — `apps/worker/`

Separate process sharing only Postgres with the API. Claims jobs via
`SELECT … FOR UPDATE SKIP LOCKED`, dispatches by `jobs.kind`:

```
reel_publish     → modules/reels/application/orchestrator.ReelPipeline
scripted_render  → modules/reels/application/use_cases/render_scripted_video
```

SIGTERM-safe shutdown: drains in-flight jobs and releases leases before exit.

Multi-worker safe: the property-level serialization rule
("don't process two jobs for the same `(external_source_id, property_id)`
concurrently") is encoded in the SQL `claim_next_ready_job` query.

## Settings

[`settings/`](settings/) is split by concern (no `app.py` god-file):
`application`, `database`, `http`, `worker`, `publishing`, `rendering`,
`observability`. Environment variables are documented in
[`.env.example`](.env.example). The worker-only knobs are namespaced
`WORKER_*` (renamed from `WEBHOOK_WORKER_*`) so it's clear which side of the
split they affect.

## Outbox

`outbox_events` decouples the writer (use cases inside the worker) from
external consumers (notifications, analytics). The relay polls
`status='pending'` rows and dispatches them; consumers acknowledge by status.

Today's events: `media_rendered`, `review_requested`, `publish_completed`,
`publish_failed`, `publish_skipped`. Adding a new consumer is an additive
change — it reads the same table.

## Errors and logging

[`shared/errors/`](shared/errors/) (was `core/errors.py`) defines
`ApplicationError` with `stage`, `code`, `retryable`, `context`,
`external_trace_id`.

[`shared/observability/`](shared/observability/) hosts the logging filter +
persistent event log. Console output stays rich for development; the
structured fields drive production alerting.

## Deployment

`compose.yml` runs three services:

```
postgres ──► api    (python -m apps.api)
         └─► worker (python -m apps.worker)
```

api and worker share `DATABASE_URL` and the on-disk `property_media/` /
`generated_media/` workspace volumes. They do not communicate over HTTP.
