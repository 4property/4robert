# Deployment

Three deployment modes coexist for this repository. Pick the one that matches your goal.

| Mode | Use when | Stack | Host |
|---|---|---|---|
| **Local docker** | Developing on your laptop, smoke-testing the stack end to end | Docker Compose (postgres + api + worker) | Your workstation |
| **Test / staging on the dev box** | Internal QA against a live database, exercised at `:8001` | systemd (`reels-test.service`, `reels-test-worker.service`) running from `/opt/projects/4Reels-Backend` | The Rocky Linux dev box (`support` user) |
| **Production** | Live customer traffic at `:8000` | systemd (`reels.service`, currently named `cpihed.service` in this repo's deploy assets) running from `/opt/cpihed` | A separate Rocky Linux host, fed from sibling repo `4property/4robert` on branch `ghl` |

Production and test/staging are independent processes — restarting one does not affect the other. CLAUDE.md and AGENTS.md describe `reels.service` (the prod service running on the production host); the unit file shipped in this repo at `deploy/rocky-linux/cpihed.service` is the same systemd template but named after the legacy CPIHED tag. Treat them as synonyms.

---

## 1. Local docker (developer workstation)

Fastest way to spin up the whole stack without a real database.

```bash
docker compose up -d            # build + start postgres, api, worker
docker compose logs -f api      # follow api logs
docker compose ps               # state of each service
docker compose down             # stop, keep volumes
docker compose down -v          # stop, drop volumes (DB reset)
```

The compose stack uses `docker/Dockerfile` (Python 3.12 slim + ffmpeg + the project's `requirements.txt`). The image is shared between api and worker; the only difference is the entrypoint command in `compose.yml`. Code changes require `docker compose build && docker compose up -d`.

Defaults exposed on the host:

- `localhost:8000` → api / webhook ingest
- `localhost:5432` → postgres (user `postgres`, password `1234`, db `miapp`)
- Worker has no exposed port (it polls the job queue).

Override via env or a top-level `.env`:

```
POSTGRES_USER=postgres
POSTGRES_PASSWORD=1234
POSTGRES_DB=miapp
```

Volumes persist between restarts: `postgres_data`, `property_media`, `property_media_raw`, `generated_media`, `logs`.

### Apply migrations against the compose database

```bash
# from the host, against the dockerized postgres
DATABASE_URL=postgresql+psycopg://postgres:1234@127.0.0.1:5432/miapp \
  .venv/bin/python -m alembic upgrade head
```

Or, from inside the api container:

```bash
docker compose exec api python -m alembic upgrade head
```

---

## 2. Test / staging on the dev box

This is what `/opt/projects/4Reels-Backend` runs as on the Rocky Linux dev box, exposed at port `:8001`. Two units are involved.

| Unit | Binary | Port | Logs |
|---|---|---|---|
| `reels-test.service` | `apps.api` | 8001 | `journalctl -u reels-test` |
| `reels-test-worker.service` | `apps.worker` | — | `logs/test-worker.log` (file-based) |

Both run as the `support` user, read the repo's local `.env`, and use the repo's `.venv`. Unit files live in `deploy/rocky-linux/`.

### Install (one-shot)

```bash
sudo install -m 644 deploy/rocky-linux/reels-test.service        /etc/systemd/system/
sudo install -m 644 deploy/rocky-linux/reels-test-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now reels-test reels-test-worker
```

### Day-to-day

```bash
sudo systemctl status  reels-test
sudo systemctl restart reels-test          # picks up code changes
journalctl -u reels-test -n 100 --no-pager
journalctl -u reels-test -f
tail -f logs/test-worker.log               # worker output
```

The test API binds to `127.0.0.1:8001` per `.env`. Anything public-facing (Cloudflare Tunnel, nginx) is configured outside this repo.

### Schema migrations

```bash
.venv/bin/python -m alembic current
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m alembic downgrade -1
```

Run these from the repo root as the `support` user. Restart `reels-test` (and the worker, if the migration changes ORM models) afterwards.

---

## 3. Production

Production lives at `/opt/cpihed` on a separate host. The code there is fed from sibling repo `4property/4robert`, branch `ghl` — **not** from this repository directly. Treat changes to production as a deploy event in that other repo. From this repository you only:

- Iterate locally, push to `ghl` here.
- Cross-publish to `4property/4robert` via whatever sync the team uses (manual cherry-pick, automated mirror).
- Restart production **only** with explicit user confirmation in the same turn (per CLAUDE.md / AGENTS.md).

The unit file `deploy/rocky-linux/cpihed.service` is the canonical systemd template for production. It runs as user `cpihed`, with config in `/etc/cpihed/cpihed.env`, listening on `127.0.0.1:8000` behind nginx.

### Bootstrapping a new prod host

```bash
# 1. System dependencies (Rocky / EL 9)
sudo dnf install -y git python3.11 python3.11-pip python3.11-devel epel-release
sudo dnf install -y https://download1.rpmfusion.org/free/el/rpmfusion-free-release-9.noarch.rpm
sudo dnf install -y ffmpeg

# 2. Service user + dirs
sudo useradd --system --create-home --home-dir /opt/cpihed --shell /sbin/nologin cpihed
sudo mkdir -p /opt/cpihed /etc/cpihed
sudo chown -R cpihed:cpihed /opt/cpihed /etc/cpihed

# 3. Clone the production repo (4property/4robert, branch ghl)
sudo -u cpihed git clone <prod-repo-url> /opt/cpihed
cd /opt/cpihed
sudo -u cpihed git checkout ghl

# 4. Install (creates venv, installs deps, registers systemd unit, seeds env template)
sudo bash deploy/rocky-linux/install.sh

# 5. Fill in /etc/cpihed/cpihed.env (see "Environment variables" below)
sudo vi /etc/cpihed/cpihed.env

# 6. Readiness check (must report "Production ready: Yes")
sudo -u cpihed bash -lc 'cd /opt/cpihed && set -a && source /etc/cpihed/cpihed.env && set +a && .venv/bin/python -m apps.api --check'

# 7. Apply migrations
sudo -u cpihed bash -lc 'cd /opt/cpihed && set -a && source /etc/cpihed/cpihed.env && set +a && .venv/bin/python -m alembic upgrade head'

# 8. Start the service
sudo systemctl enable --now cpihed
sudo systemctl status  cpihed
journalctl -u cpihed -f
```

### Iterating on existing prod host

```bash
# As the service user, pull and reinstall deps
sudo -u cpihed bash -lc 'cd /opt/cpihed && git fetch && git reset --hard origin/ghl'
sudo -u cpihed bash -lc 'cd /opt/cpihed && .venv/bin/pip install -r requirements.txt'

# Run migrations BEFORE restart so the worker picks the new schema
sudo -u cpihed bash -lc 'cd /opt/cpihed && set -a && source /etc/cpihed/cpihed.env && set +a && .venv/bin/python -m alembic upgrade head'

# Restart only after explicit user confirmation
sudo systemctl restart cpihed
```

### Nginx in front of production

The service binds to localhost only. Terminate TLS in nginx and forward to `127.0.0.1:8000`. Send `X-Forwarded-For` / `X-Forwarded-Host` / `X-Forwarded-Proto` and keep these env vars in `cpihed.env`:

```
WEBHOOK_HOST=127.0.0.1
WEBHOOK_PORT=8000
WEBHOOK_TRUST_PROXY_HEADERS=true
WEBHOOK_FORWARDED_ALLOW_IPS=127.0.0.1
WEBHOOK_ALLOWED_HOSTS=api.yourdomain.tld
```

---

## Environment variables

A complete sample lives in `.env.example`. The non-negotiables for any non-dev deployment:

| Variable | Why it matters |
|---|---|
| `DATABASE_URL` | Real DSN, not the docker default. Strong password, TLS to RDS/CloudSQL if remote. |
| `DATABASE_ENCRYPTION_KEY` | Base64 Fernet key (32 bytes). Used to encrypt provider tokens and webhook secrets in DB. Rotating this breaks all existing rows. Generate once per environment. |
| `WEBHOOK_DISABLE_SECURITY` | Must be `false` in any shared environment. |
| `WEBHOOK_SITE_SECRETS` | Legacy CSV `site_id=secret`. Per **feature 38**, the webhook now reads `ingestion_sources.secrets_encrypted` first and only falls back to this env if the DB row has no secret. New sites should be onboarded via `PUT /v1/admin/wordpress-sources/{site_id}` instead of editing this var. |
| `ADMIN_API_TOKEN` | Bearer token for `/v1/admin/*` (unless `ADMIN_API_DISABLE_AUTH_FOR_TESTING=true`). |
| `ADMIN_AGENCY_TOKEN_SECRET` | HS256 secret for agency JWTs. Generate with `openssl rand -base64 48`. |
| `GO_HIGH_LEVEL_APP_SHARED_SECRET` | Marketplace app secret; decrypts GHL Custom Page payloads. |
| `GEMINI_API_KEY` | Required if AI photo selection or AI copy is enabled. |
| `SMTP_*` + `EMAIL_BACKEND=smtp` | For email notifications in prod. Defaults to `console` (logs only). |
| `WEBHOOK_TRUST_PROXY_HEADERS` | `true` behind nginx so client IPs and host validation work. |

The full list (logging, worker queue tuning, reel / poster geometry, FFmpeg threading) is annotated in `.env.example`. The audit in `progress/audit_backend_deployment_2026_05_16.md` lists every value with defaults and which file consumes it.

### Provisioning a new WordPress source (post-feature 38)

```bash
curl -X PUT https://api.yourdomain.tld/v1/admin/wordpress-sources/<site-id> \
  -H "Authorization: Bearer $ADMIN_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
        "agency_id": "<existing-agency-uuid>",
        "source_name": "Example Estate WordPress",
        "site_url": "https://example.com",
        "webhook_secret": "<long-random-string>"
      }'
```

The secret is persisted encrypted in `ingestion_sources.secrets_encrypted`. No service restart is required. Verify with a signed test webhook against `POST /v1/ingest/wordpress/property`.

---

## Health, logs, backups

### Health checks

```
GET /health/live   → process is up
GET /health/ready  → postgres reachable, schema at expected head, ffmpeg present, fonts/music available, secrets non-placeholder
GET /health        → alias for /health/ready
```

For full diagnostics use `python -m apps.api --check` (validates the same surface but with verbose human output and a non-zero exit code on failure).

### Logs

- **Compose:** `docker compose logs -f api worker postgres`
- **systemd api (test or prod):** `journalctl -u <service> -f`
- **systemd worker (test):** `tail -f logs/test-worker.log` (file-based by design)
- **Persistent log rotation:** controlled by `PERSISTENT_LOGGING_ENABLED`, `PERSISTENT_LOG_DIRECTORY`, `PERSISTENT_LOG_MAX_BYTES`, `PERSISTENT_LOG_BACKUP_COUNT`.

### Backups

Production currently has **no automated backup pipeline** shipped from this repo. `deploy/backups/` contains a single historical `miapp_test_pre_20260501_schema.dump` from the schema-rewrite cutover; treat it as an archive, not a strategy.

Recommended one-liner backup against the prod database:

```bash
PGPASSWORD=$DB_PASSWORD pg_dump \
  -h $DB_HOST -U $DB_USER -d $DB_NAME -F c \
  -f /backups/4reels-$(date +%Y%m%d-%H%M).dump
```

Hook this into cron or your platform's snapshot policy. Restore is `pg_restore -d <db> --clean --if-exists <file>.dump` against an empty database followed by `alembic stamp head` if the dump's schema already matches code.

### Legacy schema migration helper

`deploy/migrate_legacy_schema_to_20260501.py` is a one-shot bridge from the pre-2026-05-01 schema. New deployments do **not** need to run it — Alembic from `20260501_0001_initial_schema` covers everything from a fresh database.

---

## Migration cookbook

```bash
# What is applied now?
.venv/bin/python -m alembic current

# Apply everything up to head
.venv/bin/python -m alembic upgrade head

# Roll back one revision (only for surgical fixes)
.venv/bin/python -m alembic downgrade -1

# Show full chain
.venv/bin/python -m alembic history
```

Order of operations on prod when shipping a schema change:

1. Pull code (`git fetch && git reset --hard origin/ghl`).
2. `pip install -r requirements.txt` if dependencies changed.
3. `alembic upgrade head` — must succeed before restarting any process.
4. `systemctl restart cpihed` (and worker, if affected).
5. Tail logs for ~30 s to catch ORM mismatches.

If a migration fails mid-way, **do not** mark the deployment as done. Alembic transactions are typically per-revision; the schema is left at the last successful revision. Investigate, fix, and re-run before restart.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `docker compose build` fails on `docker/Dockerfile` not found | The Dockerfile was missing prior to 2026-05-16; pull the latest `ghl`. |
| `python -m apps.api --check` reports `Production ready: No` | One of the placeholder env values is still set (look for `replace-me`, `change-me`), or `WEBHOOK_DISABLE_SECURITY=true`, or fonts/music files are missing on disk. |
| Webhook returns 401 `INVALID_WEBHOOK_CREDENTIALS` after feature 38 | The site row has no `secrets_encrypted` and `WEBHOOK_SITE_SECRETS` doesn't include it either. Provision it via `PUT /v1/admin/wordpress-sources/{site_id}`. |
| Worker not picking up jobs | Check `reels-test-worker` / production worker is actually running. The api will still accept webhooks and enqueue jobs even if the worker is dead. |
| `ffmpeg` reports `Cannot allocate memory` | Lower `REEL_FFMPEG_FILTER_THREADS` and `REEL_FFMPEG_ENCODER_THREADS`. |
| Health check 200 but admin UI 401 | Either `ADMIN_API_TOKEN` mismatch, or the agency JWT signed by an old `ADMIN_AGENCY_TOKEN_SECRET`. Re-issue tokens after rotating the secret. |

---

## Reference

- `compose.yml`, `docker/Dockerfile`, `init.sh` (dev environment harness).
- `deploy/rocky-linux/README.md` (canonical prod README, with the manual install walkthrough).
- `deploy/rocky-linux/install.sh`, `cpihed.service`, `reels-test.service`, `reels-test-worker.service`.
- `progress/audit_backend_deployment_2026_05_16.md` (1041-line audit with every env var, port, command and gap).
- Sister frontend deployment: `/opt/projects/4Reels-Frontend/docs/DEPLOYMENT.md`.
