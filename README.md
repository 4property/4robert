# CPIHED

Webhook-driven property media pipeline for multi-site real estate content.

It ingests WordPress property payloads, prepares images, renders short reels with companion posters, and publishes through GoHighLevel.

## What it does

- Multi-site webhook ingestion with per-site secrets
- PostgreSQL job queue with keyed serialization per property
- Full reels for `for_sale` / `to_let`, short status reels for `sale_agreed`, `sold`, `let_agreed`, `let`
- Poster image generated alongside every reel
- Publishing to TikTok, Instagram, LinkedIn, YouTube, Facebook, and Google Business Profile via GoHighLevel
- Durable media revisions and an outbox of domain events

## Layout

- `apps/` — process entry points (`apps.api`, `apps.worker`) and their bootstrap (`app_factory`, `runtime`, readiness)
- `modules/` — bounded contexts: `ingestion`, `reels`, `rendering`, `delivery`, `publishing`, `configuration`, `tenancy`, `notifications` (each with `domain/`, `application/`, `infrastructure/`, `transport/` per Phase 4 layering)
- `shared/` — cross-module primitives: `db/` (ORM, security, unit-of-work), `http/`, `storage/`, `logging/`, etc.
- `settings/` — Pydantic environment configuration; one source of truth for every `.env` value
- `alembic/` — schema migrations; head is the source of truth for the database shape
- `tests/` — `unit/`, `integration/`, `architecture/` regression coverage
- `docs/`, `deploy/`, `docker/`, `compose.yml`, `init.sh` — operational entrypoints

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate            # or .venv/Scripts/activate on Windows
pip install -r requirements.txt
pip install -r requirements-dev.txt
cp .env.example .env                 # then fill in DATABASE_URL, secrets, etc.
.venv/bin/python -m alembic upgrade head
```

The fastest path to a working stack (postgres + api + worker) is `docker compose up -d`. See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for the three deployment modes (local docker, test/staging on the dev box, production).

## Run

```bash
.venv/bin/python -m apps.api                       # start the API server
.venv/bin/python -m apps.api --check               # readiness check, no server
.venv/bin/python -m apps.api --check --readiness-json   # machine-readable output
.venv/bin/python -m apps.worker                    # start the job worker
.venv/bin/python -m apps.worker --check            # worker readiness check
```

## Test

```bash
bash ./init.sh                                     # full harness used by Codex/Claude (init.sh has no exec bit by design)
.venv/bin/python -m pytest -q                      # plain pytest run
```

## Runtime folders (gitignored)

- `property_media/` — selected images per property
- `property_media_raw/` — downloaded originals
- `generated_media/` — rendered reels and posters
- `logs/` — persistent log output

## Notes

- A reel is only considered complete if its companion poster also exists.
- Optional capabilities (AI copy, AI narration, notifications, review) can stay disabled without blocking the core flow.
- Google Business Profile must already be connected to the target HighLevel sub-account in Social Planner before webhooks are sent.
- A single agency can register N WordPress sites via `PUT /v1/admin/wordpress-sources/{site_id}` (per feature 38). Secrets persist in `ingestion_sources.secrets_encrypted` — no service restart required when adding sites.
- Deployment (compose, systemd test/staging, production from sibling repo): [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).
- Rocky Linux walkthrough (canonical manual install): [`deploy/rocky-linux/README.md`](deploy/rocky-linux/README.md).
- Architecture detail: [`ARCHITECTURE.md`](ARCHITECTURE.md). Frontend pairing: [`/opt/projects/4Reels-Frontend`](../4Reels-Frontend).

## License

Copyright (C) 2026 Roberto Gaviño Hurtado.

This project is licensed under the GNU General Public License, version 2 only
(GPL-2.0-only). See [`LICENSE`](LICENSE) for details.
