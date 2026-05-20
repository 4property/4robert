# 4Reels Backend — v1.0.0

Webhook-driven property media pipeline for multi-site real estate content.

It ingests WordPress property payloads, prepares images, renders short reels with companion posters, and publishes through GoHighLevel.

> **Version 1.0.0** — first stable release. Current version of record lives in [`VERSION`](VERSION). Bump it together with a `git tag vX.Y.Z` on every release.

## What it does

- Multi-site webhook ingestion with per-site secrets (encrypted in DB; legacy CSV env fallback still supported).
- PostgreSQL job queue with keyed serialization per property.
- Full reels for `for_sale` / `to_let`, short status reels for `sale_agreed`, `sold`, `let_agreed`, `let`.
- Poster image generated alongside every reel.
- Publishing to TikTok, Instagram, LinkedIn, YouTube, Facebook, and Google Business Profile via GoHighLevel.
- Durable media revisions and an outbox of domain events.

## Layout

- `apps/` — process entry points (`apps.api`, `apps.worker`) and their bootstrap (`app_factory`, `runtime`, readiness).
- `modules/` — bounded contexts: `ingestion`, `reels`, `rendering`, `delivery`, `publishing`, `configuration`, `tenancy`, `notifications` (each with `domain/`, `application/`, `infrastructure/`, `transport/`).
- `shared/` — cross-module primitives: `db/` (ORM, security, unit-of-work), `http/`, `storage/`, `logging/`.
- `settings/` — Pydantic environment configuration; one source of truth for every `.env` value.
- `alembic/` — schema migrations; the head is the source of truth for the database shape.
- `tests/` — `unit/`, `integration/`, `architecture/` regression coverage.
- `docs/`, `deploy/`, `docker/`, `compose.yml`, `init.sh` — operational entrypoints.

## Quick start (developer workstation)

```bash
python3.12 -m venv .venv
source .venv/bin/activate            # or .venv/Scripts/activate on Windows
pip install -r requirements.txt
pip install -r requirements-dev.txt
cp .env.example .env                 # fill in DATABASE_URL, secrets, etc.
.venv/bin/python -m alembic upgrade head
```

The fastest way to a working stack (postgres + api + worker) is:

```bash
docker compose up -d
```

## Run

```bash
.venv/bin/python -m apps.api                                # start the API server
.venv/bin/python -m apps.api --check                        # readiness check, no server
.venv/bin/python -m apps.api --check --readiness-json       # machine-readable output
.venv/bin/python -m apps.worker                             # start the job worker
.venv/bin/python -m apps.worker --check                     # worker readiness check
```

## Test

```bash
bash ./init.sh                                     # full harness used by Codex/Claude (no exec bit by design)
.venv/bin/python -m pytest -q                      # plain pytest run
```

## Deploy

Three deployment modes coexist. Pick the one that matches the host you are working on; **full step-by-step in [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)**.

| Mode | Use when | Stack | Where it runs |
|---|---|---|---|
| **Local docker** | Developing on your laptop, smoke-testing end-to-end | Docker Compose (postgres + api + worker) | Your workstation, port `:8000` |
| **Test / staging** | Internal QA against a live DB, exercised from the SaaS admin | systemd units `reels-test.service` + `reels-test-worker.service`, repo at `/opt/projects/4Reels-Backend` | Rocky Linux dev box, port `:8001` |
| **Production** | Live customer traffic | systemd unit `cpihed.service` (alias `reels.service`), checkout at `/opt/cpihed`, fed from sibling repo `4property/4robert` branch `ghl` | Separate Rocky Linux host, port `:8000` behind nginx |

Key operational rules:

- **Production restart requires explicit user confirmation in the same turn** (see [`CLAUDE.md`](CLAUDE.md), [`AGENTS.md`](AGENTS.md)).
- Migrations run **before** restart: `alembic upgrade head` must succeed first. If a migration fails mid-way the schema is left at the last successful revision — investigate before retrying.
- The Rocky Linux canonical install (manual, without compose) lives in [`deploy/rocky-linux/README.md`](deploy/rocky-linux/README.md).

### Minimum non-dev environment variables

Sample with annotations in [`.env.example`](.env.example). Non-negotiables for any shared environment:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Real PostgreSQL DSN, TLS if remote. |
| `DATABASE_ENCRYPTION_KEY` | Base64 Fernet key (32 bytes). Encrypts provider tokens and webhook secrets. Rotating breaks all rows — generate once per env. |
| `WEBHOOK_DISABLE_SECURITY` | Must be `false` outside local dev. |
| `WEBHOOK_SITE_SECRETS` | Legacy CSV `site_id=secret`. New sites are added via `PUT /v1/admin/wordpress-sources/{site_id}`; this env is only a fallback. |
| `ADMIN_API_TOKEN` | Bearer for `/v1/admin/*`. |
| `ADMIN_AGENCY_TOKEN_SECRET` | HS256 secret for agency JWTs (`openssl rand -base64 48`). |
| `GO_HIGH_LEVEL_APP_SHARED_SECRET` | Marketplace app secret; decrypts GHL Custom Page payloads. |
| `GEMINI_API_KEY` | Required if AI photo selection / AI copy is enabled. |
| `SMTP_*` + `EMAIL_BACKEND=smtp` | Required for prod email notifications (defaults to `console`). |
| `WEBHOOK_TRUST_PROXY_HEADERS` | `true` behind nginx so client IPs and host validation work. |

## Health, logs, runtime folders

```
GET /health/live   → process is up
GET /health/ready  → postgres reachable, schema at expected head, ffmpeg present, fonts/music available, secrets non-placeholder
GET /health        → alias for /health/ready
```

Full diagnostics: `.venv/bin/python -m apps.api --check`.

Runtime folders (gitignored, must be writable by the service user):

- `property_media/` — selected images per property
- `property_media_raw/` — downloaded originals
- `generated_media/` — rendered reels and posters
- `logs/` — persistent log output

## Notes

- A reel is only considered complete if its companion poster also exists.
- Optional capabilities (AI copy, AI narration, notifications, review) can stay disabled without blocking the core flow.
- Google Business Profile must already be connected to the target HighLevel sub-account in Social Planner before webhooks are sent.
- A single agency can register N WordPress sites via `PUT /v1/admin/wordpress-sources/{site_id}` (feature 38). Secrets persist in `ingestion_sources.secrets_encrypted` — no service restart required when adding sites.
- Architecture detail: [`ARCHITECTURE.md`](ARCHITECTURE.md). Frontend pairing: [`/opt/projects/4Reels-Frontend`](../4Reels-Frontend).

## License

Copyright (C) 2026 Roberto Gaviño Hurtado.

This project is licensed under the GNU General Public License, version 2 only
(GPL-2.0-only). See [`LICENSE`](LICENSE) for details.
