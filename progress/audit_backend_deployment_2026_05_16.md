# Audit: Backend Deployment Flow & Documentation Gaps
**Date:** 2026-05-16  
**Scope:** Complete mapping of 4Reels-Backend deployment architecture (dev + prod)  
**Status:** Read-only exploration; no files modified.

---

## 1. Inventario de Artefactos Críticos

### 1.1 `init.sh` (raíz)
**File:** `/opt/projects/4Reels-Backend/init.sh`  
**Purpose:** Pre-session environment validation harness; runs on every session start before marking tasks `done`.

**Steps (línea:descripción):**
- **L21-50:** Python interpreter detection (venv-first, fallback system py3.11); version check ≥3.11
- **L52-55:** Import verification: fastapi, pydantic, sqlalchemy, alembic must be importable
- **L60-67:** File baselines: AGENTS.md, CLAUDE.md, feature_list.json, progress/current.md, docs/*.md, CHECKPOINTS.md
- **L70-90:** JSON validation: feature_list.json parsed; max 1 feature in `in_progress` state; all states in {pending, in_progress, done, blocked}
- **L93-109:** Legacy directory regression check: services/, application/, repositories/, core/, domain/ must NOT exist (Phase 2 cleanup)
- **L112-141:** Legacy import scan: 0 files in apps|modules|shared|tests may import from legacy module names
- **L144-156:** Readiness checks: `python -m apps.api --check` and `python -m apps.worker --check` (warnings logged if env/config missing)
- **L159-177:** pytest run: all tests must pass (deselects OK); 3 baseline failures tracked
- **L182-188:** Exit code summary: 0 = ready, 1 = blocked

**Entry point:** `bash ./init.sh` (NOT executable; requires `bash` prefix per current.md line 18)

---

### 1.2 `compose.yml` (raíz)
**File:** `/opt/projects/4Reels-Backend/compose.yml`  
**Purpose:** Docker Compose stack for **local development** (NOT production)

**Services:**
- **postgres** (L2-18): PostgreSQL 16; port 5432; env vars POSTGRES_USER/PASSWORD/DB; healthcheck; volume `postgres_data`
- **api** (L20-41): Builds from `docker/Dockerfile` (missing; see §1.3); image `4reels-api:latest`; runs `python -m apps.api`; port 8000; env: DATABASE_URL + WEBHOOK_HOST/PORT; depends_on postgres healthy; volumes: media + logs
- **worker** (L43-66): Same build; image `4reels-worker:latest`; runs `python -m apps.worker`; env: WORKER_COUNT/QUEUE/JOB config; no exposed ports; same volumes

**Networks:** default (unnamed bridge)  
**Volumes:** postgres_data, property_media, property_media_raw, generated_media, logs

**Design note:** This is **dev-only**. Production uses systemd services on Rocky Linux (see §1.6).

---

### 1.3 `docker/Dockerfile`
**Status:** **MISSING**  
The compose.yml references `docker/Dockerfile` (lines 23, 46) but no Dockerfile exists.
```
$ find /opt/projects/4Reels-Backend -name "Dockerfile*" -type f
(no output)
```
**Risk:** `docker compose up` will fail. This is a **critical gap**.

**What should it contain (inferred from compose.yml):**
- Base: `python:3.11-slim` (or Alpine)
- COPY . /app
- WORKDIR /app
- RUN pip install -r requirements.txt
- EXPOSE 8000 (api) / no expose for worker
- ENTRYPOINT or CMD inherited from compose command

---

### 1.4 `docker/postgresql/`
**Files:** `/opt/projects/4Reels-Backend/docker/postgresql/`
```
initdb/                          (empty — .gitkeep only)
README.md                        (see below)
```

**README.md (L1-10):** States "Use root compose.yml: `docker compose up -d postgres`; data in named volume."  
**initdb/:** Empty placeholder; no init scripts. Database schema is applied via Alembic after container starts, not via SQL scripts.

---

### 1.5 `deploy/rocky-linux/install.sh`
**File:** `/opt/projects/4Reels-Backend/deploy/rocky-linux/install.sh`  
**Purpose:** One-shot installation script for **production Rocky Linux 9 deployment**

**Inputs:**
- `APP_DIR` env var (default `/opt/cpihed`) — where repo is cloned
- `ENV_FILE` env var (default `/etc/cpihed/cpihed.env`) — writable by service user
- `SERVICE_NAME` env var (default `cpihed`)
- `PYTHON_BIN` env var (default `/usr/bin/python3.11`)
- **Precondition:** Repo cloned to `$APP_DIR`; `requirements.txt` present

**Steps (L9-40):**
- **L9-13:** Python binary existence check
- **L15-19:** requirements.txt existence check
- **L21:** mkdir for APP_DIR and ENV_FILE parent
- **L23-25:** Create venv in `$APP_DIR/.venv`; pip install wheel + requirements.txt
- **L27-30:** Copy `.env.example` → `$ENV_FILE` (640 perms) if not exists
- **L32-33:** Install systemd service file from `deploy/rocky-linux/cpihed.service`; daemon-reload
- **L35-40:** Print next steps: edit ENV_FILE, run `--check`, enable service

**Outputs:**
- `.venv/bin/python` + `.venv/bin/pip` ready
- Systemd service registered at `/etc/systemd/system/cpihed.service`
- `/etc/cpihed/cpihed.env` template created (user must edit)

**Note:** This is not idempotent for venv creation (would fail re-run); requires cleanup or conditional logic.

---

### 1.6 Systemd Service Files

#### 1.6.1 `deploy/rocky-linux/cpihed.service` (Production)
**File:** `/opt/projects/4Reels-Backend/deploy/rocky-linux/cpihed.service`  
**Purpose:** Systemd unit for **production API + ingest webhook handler** on Rocky Linux

```ini
[Unit]
Description=CPIHED property webhook pipeline
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=cpihed
Group=cpihed
WorkingDirectory=/opt/cpihed
EnvironmentFile=/etc/cpihed/cpihed.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/cpihed/.venv/bin/python -m apps.api
Restart=on-failure
RestartSec=5
TimeoutStartSec=90
TimeoutStopSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Key details:**
- **Binary:** `/opt/cpihed/.venv/bin/python -m apps.api`
- **User:** `cpihed` (system user; see README L23-25)
- **Config:** Loaded from `/etc/cpihed/cpihed.env` (EnvironmentFile)
- **Ports:** Inferred from `.env.example` L14: `WEBHOOK_HOST=127.0.0.1`, `WEBHOOK_PORT=8000` (must be proxied via Nginx for TLS)
- **Logs:** journalctl (systemd journal)
- **Restart policy:** on-failure, 5s delay, 90s start timeout, 30s stop timeout

**Deployment state:** `cpihed.service` is **PRODUCTION**; referenced in CLAUDE.md L81 as "reels.service en :8000" (actual name mismatch detected — see §6 Risks).

---

#### 1.6.2 `deploy/rocky-linux/reels-test.service` (Test/Staging)
**File:** `/opt/projects/4Reels-Backend/deploy/rocky-linux/reels-test.service`  
**Purpose:** Systemd unit for **test/staging API** on development machine (Rocky Linux / Alma / EL)

```ini
[Unit]
Description=reels test (4Reels-Backend) property webhook pipeline
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=support
Group=support
WorkingDirectory=/opt/projects/4Reels-Backend
EnvironmentFile=/opt/projects/4Reels-Backend/.env
ExecStart=/opt/projects/4Reels-Backend/.venv/bin/python -m apps.api
Restart=on-failure
RestartSec=5

# Hardening (strict sandboxing)
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/opt/projects/4Reels-Backend

StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Key details:**
- **Binary:** `.venv/bin/python -m apps.api` (LOCAL venv, not /opt/cpihed)
- **User:** `support` (local dev user)
- **Config:** `.env` (repo root, NOT `/etc/` system location)
- **Working dir:** `/opt/projects/4Reels-Backend` (repo root)
- **Ports:** inferred from `.env`: `WEBHOOK_HOST=127.0.0.1`, `WEBHOOK_PORT=8001` (per progress/current.md L18 reference)
- **Logs:** journalctl
- **Hardening:** NoNewPrivileges, PrivateTmp, ProtectSystem=strict, explicit ReadWritePaths

**Purpose:** Used for local testing of full stack (API + worker) without docker-compose.

---

#### 1.6.3 `deploy/rocky-linux/reels-test-worker.service` (Test Worker)
**File:** `/opt/projects/4Reels-Backend/deploy/rocky-linux/reels-test-worker.service`  
**Purpose:** Systemd unit for **test/staging worker dispatcher** (job queue consumer)

```ini
[Unit]
Description=reels test (4Reels-Backend) worker
After=network.target postgresql.service

[Service]
Type=simple
User=support
Group=support
WorkingDirectory=/opt/projects/4Reels-Backend
EnvironmentFile=/opt/projects/4Reels-Backend/.env
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/projects/4Reels-Backend/.venv/bin/python -m apps.worker
Restart=on-failure
RestartSec=5

# Hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=/opt/projects/4Reels-Backend

StandardOutput=append:/opt/projects/4Reels-Backend/logs/test-worker.log
StandardError=append:/opt/projects/4Reels-Backend/logs/test-worker.log

[Install]
WantedBy=multi-user.target
```

**Key details:**
- **Binary:** `python -m apps.worker` (job queue consumer; no HTTP ports)
- **Logs:** appended to `/opt/projects/4Reels-Backend/logs/test-worker.log` (file-based, not journalctl)
- **Depends:** `postgresql.service` (not docker.service; assumes external DB)
- **Same config:** `.env` from repo root

**Comparison matrix:**

| Aspect | cpihed.service (prod) | reels-test.service | reels-test-worker.service |
|--------|---|---|---|
| User | cpihed | support | support |
| App dir | /opt/cpihed | /opt/projects/4Reels-Backend | (same) |
| Config file | /etc/cpihed/cpihed.env | .env (repo root) | (same) |
| Binary | apps.api | apps.api | apps.worker |
| Port | 8000 | 8001 (inferred) | — (queue only) |
| Logs | journalctl | journalctl | file: logs/test-worker.log |
| Hardening | none | strict | strict |
| Docker | — | requires docker.service | — |

---

### 1.7 `deploy/rocky-linux/README.md`
**File:** `/opt/projects/4Reels-Backend/deploy/rocky-linux/README.md`  
**Status:** Partially documented; gaps below.

**Coverage:**
- ✅ §Packages: System dependencies (python3.11, ffmpeg, RPM Fusion)
- ✅ §Layout: App dir, env file, service user setup
- ✅ §Install: Manual venv + pip steps; when to use install.sh unclear
- ✅ §Preflight: `.venv/bin/python -m apps.api --check` validation
- ✅ §systemd: enable/status/logs commands
- ✅ §Reverse proxy: nginx + TLS binding; WEBHOOK_HOST/PORT/TRUST_PROXY env vars
- ✅ §Notes: Media dirs, ffmpeg memory tuning, webhook auth troubleshooting

**Gaps:**
- ❌ Does NOT mention install.sh explicitly (line 28–31 shows manual steps but install.sh exists)
- ❌ No database initialization / Alembic migration flow documented
- ❌ No worker service (apps.worker) mentioned; only apps.api
- ❌ No backup/restore procedures
- ❌ No version bumping / hot-deploy strategy
- ❌ No monitoring / healthcheck endpoints explained
- ❌ No comparison with dev (docker-compose) flow

---

### 1.8 `deploy/backups/`
**Files:**
```
miapp_test_pre_20260501_schema.dump    (PostgreSQL dump file; ~1.3MB)
```

**Purpose:** Single PostgreSQL backup from pre-schema-migration era (2026-05-01).  
**Status:** Historical artifact; not actively managed. No backup rotation, no restore script.  
**Gap:** No documented backup strategy (daily, incremental, off-site).

---

### 1.9 `deploy/migrate_legacy_schema_to_20260501.py`
**File:** `/opt/projects/4Reels-Backend/deploy/migrate_legacy_schema_to_20260501.py`  
**Purpose:** One-shot legacy database bridge; migrates Phase 1/2 schema to Phase 3/4 (2026-05-01)

**Summary (L1-6):**
```
Preserves existing rows; renames tables/columns to new names (e.g., 
wordpress_sources → ingestion_sources); creates new tables; 
stamps Alembic head.
```

**Usage:** Run once per legacy database; idempotent downgrade not supported (one-way migration).  
**Status:** Historical; no longer used for new deployments (schema already current). NOT documented in deployment README.

---

## 2. Variables de Entorno Completas

### 2.1 Inventory (all env vars the backend reads)

**Source files scanned:**
- `.env.example` (L1-189): Template with 100+ env vars
- `settings/__init__.py`: Top-level exports
- `settings/app.py`: AppSettings Pydantic model (inferred from imports)
- `compose.yml`: Defaults for local dev
- Service files: No inline override beyond EnvironmentFile

**Complete list (grouped by category):**

#### Logging
| Var | Default | Type | Secret? | Notes |
|-----|---------|------|---------|-------|
| LOG_LEVEL | INFO | str | No | Python logging level |
| PERSISTENT_LOGGING_ENABLED | false (inferred) | bool | No | File-based log rotation |
| PERSISTENT_LOG_DIRECTORY | ./logs | str | No | Relative to workspace |
| PERSISTENT_LOG_MAX_BYTES | 10485760 | int | No | ~10MB per log file |
| PERSISTENT_LOG_BACKUP_COUNT | 5 | int | No | Retention count |

#### Webhook (Ingest)
| Var | Default | Type | Secret? | Notes |
|-----|---------|------|---------|-------|
| WEBHOOK_HOST | 127.0.0.1 | str | No | Bind address (use localhost in prod) |
| WEBHOOK_PORT | 8000 | int | No | TCP port |
| WEBHOOK_ENABLE_DOCS | false | bool | No | Swagger/OpenAPI |
| WEBHOOK_DISABLE_SECURITY | false | bool | No | ⚠️ Testing only; must be false in prod |
| WEBHOOK_PATH | /v1/ingest/wordpress/property | str | No | Webhook endpoint path |
| WEBHOOK_SITE_ID_HEADER | X-WordPress-Site-ID | str | No | Header name |
| WEBHOOK_TIMESTAMP_HEADER | X-WordPress-Timestamp | str | No | Header name |
| WEBHOOK_SIGNATURE_HEADER | X-WordPress-Signature | str | No | Header name |
| WEBHOOK_SITE_SECRETS | example-estate.ie=change-me,... | str | **Yes** | CSV site_id=secret pairs; env-backed; DB-backed per feature 38 |
| WEBHOOK_ALLOWED_HOSTS | (empty) | str | No | Optional Host header allowlist |
| WEBHOOK_TRUST_PROXY_HEADERS | true | bool | No | Nginx X-Forwarded-* headers |
| WEBHOOK_FORWARDED_ALLOW_IPS | 127.0.0.1 | str | No | Trusted proxy IPs |
| WEBHOOK_LIMIT_CONCURRENCY | 64 | int | No | Semaphore for ingest jobs |
| WEBHOOK_MAX_PAYLOAD_BYTES | 1000000 | int | No | ~1MB request body limit |
| WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS | 300 | int | No | ±5min clock skew tolerance |
| WEBHOOK_SHUTDOWN_TIMEOUT_SECONDS | 10 | int | No | Graceful shutdown window |

#### Webhook GoHighLevel (GHL) Custom Pages
| Var | Default | Type | Secret? | Notes |
|-----|---------|------|---------|-------|
| WEBHOOK_GOHIGHLEVEL_LOCATION_ID_HEADER | X-GoHighLevel-Location-ID | str | No | Header for GHL location |
| WEBHOOK_GOHIGHLEVEL_ACCESS_TOKEN_HEADER | X-GoHighLevel-Access-Token | str | No | Header for GHL auth |

#### Worker (Job Queue)
| Var | Default | Type | Secret? | Notes |
|-----|---------|------|---------|-------|
| WORKER_COUNT | 1 | int | No | Concurrent job workers |
| WORKER_QUEUE_POLL_INTERVAL_SECONDS | 0.5 | float | No | Job queue check interval |
| WORKER_QUEUE_LEASE_SECONDS | 900 | int | No | Job lock timeout (15min) |
| WORKER_JOB_MAX_ATTEMPTS | 3 | int | No | Retry limit per job |
| WORKER_JOB_RETRY_BACKOFF_SECONDS | 30 | int | No | Delay before retry |
| WORKER_SHUTDOWN_TIMEOUT_SECONDS | 30 | int | No | Graceful shutdown window |

#### Database
| Var | Default | Type | Secret? | Notes |
|-----|---------|------|---------|-------|
| DATABASE_URL | postgresql+psycopg://postgres:1234@127.0.0.1:5432/miapp | str | **Yes** | SQLAlchemy DSN; prod must use strong password |
| DATABASE_POOL_SIZE | 5 | int | No | Connection pool size |
| DATABASE_MAX_OVERFLOW | 10 | int | No | Max overflow connections |
| DATABASE_POOL_TIMEOUT_SECONDS | 30 | int | No | Pool acquisition timeout |
| DATABASE_ENCRYPTION_KEY | BU3oBe_-NJKkqpct_qYxUMm2QkzIUcTdKZGp1YEahGw= | str | **Yes** | Base64 Fernet key for column encryption (32B) |

#### Admin API
| Var | Default | Type | Secret? | Notes |
|-----|---------|------|---------|-------|
| ADMIN_API_ENABLED | true | bool | No | Enable /v1/admin/* endpoints |
| ADMIN_API_BASE_PATH | /v1/admin | str | No | Prefix for admin routes |
| ADMIN_API_TOKEN | replace-with-a-long-random-token | str | **Yes** | Bearer token for admin auth (if not disabled) |
| ADMIN_API_DISABLE_AUTH_FOR_TESTING | false | bool | No | ⚠️ Testing only |
| ADMIN_AGENCY_TOKEN_SECRET | (empty) | str | **Yes** | HS256 key for agency JWT signing; generate with `openssl rand -base64 48` |
| ADMIN_AGENCY_TOKEN_TTL_SECONDS | 3600 | int | No | Agency token lifetime (60min default, min 60s) |

#### Social Publishing (TikTok, Instagram, LinkedIn, YouTube, Facebook, GBP)
| Var | Default | Type | Secret? | Notes |
|-----|---------|------|---------|-------|
| SOCIAL_PUBLISHING_ENABLED | true | bool | No | Enable reel export to social |
| SOCIAL_PUBLISHING_LOCAL_ONLY | false | bool | No | Render but don't publish (test mode) |
| SOCIAL_PUBLISHING_DEFAULT_PLATFORMS | tiktok,instagram,linkedin,youtube,facebook,google_business_profile | str | No | CSV platform list |
| SOCIAL_PUBLISHING_PROPERTY_URL_TEMPLATE | https://{site_id}/property/{slug} | str | No | Deep-link template for captions |
| SOCIAL_PUBLISHING_PROPERTY_URL_TRACKING_PARAMS | (empty) | str | No | Optional UTM params |
| SOCIAL_PUBLISHING_RETRY_ATTEMPTS | 3 | int | No | Retry count on publish failure |
| SOCIAL_PUBLISHING_RETRY_BACKOFF_SECONDS | 1.5 | float | No | Delay between retries |
| SOCIAL_PUBLISHING_YOUTUBE_POST_TYPE | post | str | No | YouTube asset type |
| SOCIAL_PUBLISHING_POST_STATUS_POLL_ATTEMPTS | 10 | int | No | Polling limit for status check |
| SOCIAL_PUBLISHING_POST_STATUS_POLL_INTERVAL_SECONDS | 3.0 | float | No | Polling interval |

#### GoHighLevel (GHL) Integration
| Var | Default | Type | Secret? | Notes |
|-----|---------|------|---------|-------|
| GO_HIGH_LEVEL_BASE_URL | https://services.leadconnectorhq.com | str | No | GHL API endpoint |
| GO_HIGH_LEVEL_API_VERSION | 2021-07-28 | str | No | GHL API version |
| GO_HIGH_LEVEL_APP_SHARED_SECRET | replace-with-marketplace-app-shared-secret | str | **Yes** | Marketplace app secret (decrypts Custom Page payloads) |

#### Media Cleanup
| Var | Default | Type | Secret? | Notes |
|-----|---------|------|---------|-------|
| PROPERTY_MEDIA_DELETE_TEMPORARY_FILES | true | bool | No | Clean raw downloads after render |
| PROPERTY_MEDIA_DELETE_SELECTED_PHOTOS | false | bool | No | Clean selected_photos after publish |

#### Reel Rendering (Video)
| Var | Default | Type | Secret? | Notes |
|-----|---------|------|---------|-------|
| REEL_TOTAL_DURATION_SECONDS | 35 | int | No | Final reel length |
| REEL_SECONDS_PER_SLIDE | 5 | int | No | Photo dwell time |
| REEL_INTRO_DURATION_SECONDS | 0 | int | No | Intro video length (or 0) |
| REEL_WIDTH | 1080 | int | No | Output width (px) |
| REEL_HEIGHT | 1440 | int | No | Output height (px) |
| REEL_FPS | 24 | int | No | Frames per second |
| REEL_SUBTITLE_FONT_SIZE | 54 | int | No | Subtitle font size |
| REEL_SUBTITLE_FONT_PATH | assets/fonts/Inter/static/Inter_28pt-Bold.ttf | str | No | Relative to project root |
| REEL_BER_ICON_SCALE | 0.5 | float | No | BER certificate overlay scale |
| REEL_AGENCY_LOGO_SCALE | 1.5 | float | No | Agency logo scale |
| REEL_FFMPEG_FILTER_THREADS | 1 | int | No | FFmpeg filter thread pool (memory optimization) |
| REEL_FFMPEG_ENCODER_THREADS | 2 | int | No | FFmpeg encoder thread pool |

#### Poster Rendering (Static Image)
| Var | Default | Type | Secret? | Notes |
|-----|---------|------|---------|-------|
| POSTER_WIDTH | 1080 | int | No | Poster output width |
| POSTER_HEIGHT | 1920 | int | No | Poster output height |
| POSTER_BACKGROUND_BLUR_RADIUS | 36 | int | No | Blur effect radius |
| POSTER_BACKGROUND_BLUR_POWER | 12 | int | No | Blur strength |
| POSTER_PHOTO_SIDE_MARGIN_RATIO | 0.06 | float | No | Side margin as % of width |
| POSTER_PHOTO_SIDE_MARGIN_MIN_PX | 24 | int | No | Minimum side margin |
| POSTER_PHOTO_PANEL_GAP_RATIO | 0.016 | float | No | Gap between photos |
| POSTER_PHOTO_PANEL_GAP_MIN_PX | 16 | int | No | Minimum gap |
| POSTER_FOOTER_BOTTOM_OFFSET_PX | 56 | int | No | Footer offset from bottom |

#### AI / Photo Selection (Gemini)
| Var | Default | Type | Secret? | Notes |
|-----|---------|------|---------|-------|
| GEMINI_API_KEY | replace-me | str | **Yes** | Google Gemini API key (vision model) |
| GEMINI_MODEL | gemini-2.5-flash | str | No | Gemini model version |
| GEMINI_TIMEOUT_SECONDS | 90 | int | No | API request timeout |
| GEMINI_RETRY_ATTEMPTS | 6 | int | No | Retry limit |

#### Email Notifications
| Var | Default | Type | Secret? | Notes |
|-----|---------|------|---------|-------|
| EMAIL_BACKEND | console | str | No | `console` (dev) or `smtp` (prod) |
| SMTP_HOST | localhost | str | No | SMTP server address |
| SMTP_PORT | 587 | int | No | SMTP port |
| SMTP_USER | (empty) | str | No | SMTP username |
| SMTP_PASSWORD | (empty) | str | **Yes** | SMTP password (if auth required) |
| SMTP_USE_TLS | true | bool | No | TLS for SMTP |
| SMTP_FROM_ADDRESS | notifications@4reels.ie | str | No | Sender email address |
| SMTP_FROM_NAME | 4Reels Notifications | str | No | Sender display name |
| FRONTEND_BASE_URL | http://localhost:5173 | str | No | Admin frontend URL (for email links) |

#### HTTP Client
| Var | Default | Type | Secret? | Notes |
|-----|---------|------|---------|-------|
| OUTBOUND_HTTP_TIMEOUT_SECONDS | 30 | int | No | Timeout for external API calls |

### 2.2 Discrepancies: `.env.example` vs. `settings/` reality

**Verified against `settings/__init__.py` exports (line 1–267):**

✅ **Well-documented in .env.example:**
- All webhook transport vars
- All worker config
- All database config
- All social publishing config
- All rendering config (reel + poster)
- All admin API config
- All email/notifications config
- GHL integration

⚠️ **Partially documented; requires digging in `settings/app.py` or `settings/*.py`:**
- `REVIEW_WORKFLOW_ENABLED` — **missing from .env.example** (exported in __init__.py L139)
- `NOTIFICATIONS_ENABLED` — **missing from .env.example** (L140)
- `AI_COPY_ENABLED` — **missing from .env.example** (L141)
- `AI_NARRATION_ENABLED` — **missing from .env.example** (L142)

❌ **Not in .env.example (likely feature-gated or removed):**
- `DEFAULT_PHOTOS_TO_SELECT` (exported L168, used in photo_selection.py)
- `GEMINI_AREA_LABELS`, `GEMINI_AREA_SET`, `GEMINI_VALID_RESULT_AREAS`, etc. (exported L45-50; constants, not env vars)

**Gap:** `.env.example` missing ~4 boolean feature flags. Prod deployments may not have them set, causing silent defaults.

---

## 3. Puertos y Endpoints Externos

### 3.1 Local Development (docker-compose)
| Service | Port | Protocol | Binding | Purpose |
|---------|------|----------|---------|---------|
| postgres | 5432 | TCP | 0.0.0.0 (all IPs) | Database for api + worker |
| api | 8000 | HTTP | 0.0.0.0 | Webhook ingest + admin endpoints |
| worker | — | — | — | Queue consumer; no HTTP |

**Access from host machine:** `http://localhost:8000/`

---

### 3.2 Production (Rocky Linux + systemd)
| Service | Port | Protocol | Binding | Proxy | Purpose |
|---------|------|----------|---------|-------|---------|
| cpihed (apps.api) | 8000 | HTTP | 127.0.0.1 (localhost only) | Nginx (TLS termination) | Webhook ingest + admin |
| — | 443 (Nginx) | HTTPS | 0.0.0.0 | — | Public-facing TLS endpoint |
| postgres | 5432 | TCP | 127.0.0.1 (inferred) | — | Internal DB (not exposed) |

**Note:** postgres binding not specified in service files; assumed localhost per security best-practice. `.env` template suggests external postgres possible (DATABASE_URL is configurable).

---

### 3.3 Test/Staging (reels-test + reels-test-worker)
| Service | Port | Protocol | Binding | Purpose |
|---------|------|----------|---------|---------|
| reels-test (apps.api) | 8001 | HTTP | 127.0.0.1 | Same as prod; staging webhook ingest |
| reels-test-worker | — | — | — | Queue consumer; logs to file |

**Port 8001 inferred from:** progress/current.md line 18 ("`:8001` es test").

---

### 3.4 Health & Status Endpoints
```
GET /health/live            → minimal status (instant)
GET /health/ready           → full readiness check (postgres, schema, directories, ffmpeg, secrets)
GET /health                 → (alias for /health/ready)
```

**Documented in:** `/opt/projects/4Reels-Backend/apps/api/health_router.py` (inferred; not read directly).  
**Note:** `/health/live` and `/health/ready` return minimal status only per README L67; use `python -m apps.api --check` for full diagnostics.

---

## 4. Comandos de Operación

### 4.1 Local Development Stack

**Start:**
```bash
docker compose up -d
# or specific services:
docker compose up -d postgres
docker compose up -d api
docker compose up -d worker
```

**Stop:**
```bash
docker compose down
# Keep volumes:
docker compose down --volumes
# Remove volumes (full reset):
docker compose down -v
```

**Logs:**
```bash
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f postgres
docker compose logs -f                    # all services
```

**Rebuild (after code changes):**
```bash
docker compose build
docker compose up -d
```

**Database reset (local dev only):**
```bash
docker compose down -v postgres
docker compose up -d postgres
# Migrations auto-applied by api on startup (if enabled)
```

---

### 4.2 Production / Test Deployment (Rocky Linux + systemd)

**Initial Setup:**
```bash
# 1. On target machine, clone repo
git clone https://github.com/4reels/4Reels-Backend.git /opt/cpihed
cd /opt/cpihed

# 2. Run install script (venv + systemd service)
sudo bash deploy/rocky-linux/install.sh

# 3. Edit environment file
sudo vi /etc/cpihed/cpihed.env
# At minimum set:
# - DATABASE_URL (with strong password)
# - WEBHOOK_SITE_SECRETS (real secrets, not placeholders)
# - WEBHOOK_DISABLE_SECURITY=false
# - Optionally: GO_HIGH_LEVEL_APP_SHARED_SECRET, GEMINI_API_KEY

# 4. Validate readiness
sudo -u cpihed bash -lc 'cd /opt/cpihed && set -a && source /etc/cpihed/cpihed.env && set +a && .venv/bin/python -m apps.api --check'
# Both "Runtime ready" and "Production ready" must report "Yes"

# 5. Enable and start service
sudo systemctl enable --now cpihed
sudo systemctl status cpihed
```

**Validate Deployment:**
```bash
# Check service status
sudo systemctl status cpihed
sudo systemctl status reels-test          # if using test service

# Tail logs
sudo journalctl -u cpihed -f
sudo tail -f /opt/projects/4Reels-Backend/logs/test-worker.log    # test worker

# Hit health endpoint (through reverse proxy)
curl https://api.yourdomain.tld/health/ready

# Inspect config
sudo cat /etc/cpihed/cpihed.env
```

---

### 4.3 Database Migrations

**Apply migrations (automatic on startup):**
```bash
# Via systemd service (automatic; checked at startup)
sudo systemctl restart cpihed
# Logs will show alembic progress

# Manual (development only)
cd /opt/projects/4Reels-Backend
.venv/bin/python -m alembic upgrade head      # apply all pending
.venv/bin/python -m alembic upgrade -1        # rollback one
.venv/bin/python -m alembic current           # show current revision
.venv/bin/python -m alembic history           # show migration chain
```

**Executed as:** `support` user (dev machine) or `cpihed` user (prod).

**Current head revision (as of 2026-05-16):** `20260515_0005_reels_manifest_override.py`

---

### 4.4 Service Control (Systemd)

**Prod service (cpihed):**
```bash
# Start
sudo systemctl start cpihed

# Stop (graceful shutdown; see TimeoutStopSec=30)
sudo systemctl stop cpihed

# Restart
sudo systemctl restart cpihed

# Reload config (without restart; not applicable to this service)
sudo systemctl reload cpihed

# Status
sudo systemctl status cpihed

# Logs (systemd journal)
sudo journalctl -u cpihed -f
sudo journalctl -u cpihed --since "2 hours ago"
sudo journalctl -u cpihed -n 100              # last 100 lines
```

**Test services (reels-test + reels-test-worker):**
```bash
sudo systemctl start reels-test
sudo systemctl start reels-test-worker
sudo systemctl status reels-test reels-test-worker

# Worker logs (file-based)
tail -f /opt/projects/4Reels-Backend/logs/test-worker.log
```

---

### 4.5 Worker Management

**Start worker:**
```bash
# Via systemd
sudo systemctl start reels-test-worker

# Or manually (dev)
cd /opt/projects/4Reels-Backend
.venv/bin/python -m apps.worker
```

**Worker-specific env vars (from compose.yml):**
```
WORKER_COUNT=1                              # number of concurrent jobs
WORKER_QUEUE_POLL_INTERVAL_SECONDS=0.5      # check queue every 500ms
WORKER_QUEUE_LEASE_SECONDS=900              # hold job for 15min
WORKER_JOB_MAX_ATTEMPTS=3                   # retry 3 times
WORKER_JOB_RETRY_BACKOFF_SECONDS=30         # wait 30s before retry
WORKER_SHUTDOWN_TIMEOUT_SECONDS=30          # graceful shutdown 30s
```

**Logs:**
```bash
# Prod (journalctl)
sudo journalctl -u cpihed -f | grep -i worker

# Test (file)
tail -f /opt/projects/4Reels-Backend/logs/test-worker.log
```

---

### 4.6 Backup / Restore

**⚠️ NOT DOCUMENTED IN REPO.** Gap below.

**Manual PostgreSQL backup:**
```bash
# From host with postgres client
pg_dump -h 127.0.0.1 -U postgres -d miapp > backup_$(date +%Y%m%d_%H%M%S).dump

# From docker (dev)
docker exec cpih-postgres-dev pg_dump -U postgres -d miapp > backup.dump
```

**Restore:**
```bash
psql -h 127.0.0.1 -U postgres -d miapp < backup.dump
```

**Current backup in repo:** `deploy/backups/miapp_test_pre_20260501_schema.dump` (historical; pre-migration).

---

## 5. Workflow de Despliegue Real

**Assumption:** Rocky Linux 9 server with `/opt/cpihed` repo, systemd, Nginx reverse proxy.

### 5.1 Developer → Production Pipeline

```
1. DEVELOPMENT (Local)
   └─ Feature branch: code in /opt/projects/4Reels-Backend
   └─ Test: bash ./init.sh (pytest, --check, init validation)
   └─ Commit & PR (CI: none detected in repo; manual review assumed)

2. MERGE TO MAIN
   └─ Code merged to main branch
   └─ No automatic CI/CD detected (no .github/workflows, no Makefile)

3. DEPLOY TRIGGER (Manual)
   └─ Operator pulls main into /opt/cpihed on prod server
   └─ `git pull origin main` from /opt/cpihed
   └─ ⚠️ If first deploy: run `sudo bash deploy/rocky-linux/install.sh`
   └─ ⚠️ If subsequent: pip installs deps (no automatic; must be manual)

4. APPLY MIGRATIONS
   └─ Operator connects to prod server
   └─ Runs: `sudo -u cpihed bash -lc 'cd /opt/cpihed && .venv/bin/alembic upgrade head'`
   └─ OR: migrations run automatically on service restart (if enabled)

5. RESTART SERVICE
   └─ `sudo systemctl restart cpihed`
   └─ Systemd stops old process (30s timeout), starts new
   └─ Worker (if running separately) also needs restart: `sudo systemctl restart reels-test-worker`

6. VALIDATE
   └─ `sudo systemctl status cpihed`
   └─ `curl https://api.yourdomain.tld/health/ready`
   └─ Logs: `sudo journalctl -u cpihed -f`
   └─ Check ingest webhook payload acceptance

7. ROLLBACK (if needed)
   └─ `git revert <commit>` or `git reset --hard <safe-commit>`
   └─ Re-apply migrations (if schema was rolled back)
   └─ `sudo systemctl restart cpihed`
```

### 5.2 Blue-Green / Canary?
**Status:** NOT USED. No evidence of blue-green or canary deployments.
- Single `cpihed.service` instance; restart incurs brief downtime.
- No load balancer / secondary replica detected.
- Recommendation: Use test environment (`:8001`) for staging before prod.

---

### 5.3 Versioning & Tagging
**Status:** NOT DOCUMENTED. No release tags, version bumping, or changelog.
- Alembic tracks schema version (migrations in `alembic/versions/`).
- No Python package version (no `__version__` export, no setup.py/pyproject.toml semver).
- Recommendation: Tag releases in git (e.g., `v1.0.0`, `v1.1.0`).

---

## 6. Riesgos & Gotchas

### 6.1 Missing Dockerfile
**Severity:** CRITICAL  
**Issue:** `compose.yml` references `docker/Dockerfile` but file doesn't exist.  
**Impact:** `docker compose build` will fail; dev stack cannot start.  
**Fix:** Create `/opt/projects/4Reels-Backend/docker/Dockerfile` with Python 3.11 + pip install requirements.txt.

---

### 6.2 Service Name Mismatch
**Severity:** MEDIUM  
**Issue:** CLAUDE.md L81 refers to "reels.service en :8000" but actual prod service is named `cpihed.service`.  
**Impact:** Operator may fail to find the service or restart wrong one.  
**Current mapping:**
- **Prod API:** `cpihed.service` (port 8000)
- **Test API:** `reels-test.service` (port 8001)
- **Test Worker:** `reels-test-worker.service`
- **No service named `reels.service`** exists.

**Fix:** Update CLAUDE.md to refer to actual service names or document the name mapping.

---

### 6.3 install.sh Not Idempotent
**Severity:** MEDIUM  
**Issue:** `install.sh` creates venv and pip installs on every run (line 23–25). Rerunning will fail if venv already exists.  
**Impact:** Cannot use install.sh for updates; operator must manually manage deps.  
**Fix:** Add conditional or cleanup logic:
```bash
if [ ! -d "$APP_DIR/.venv" ]; then
  "$PYTHON_BIN" -m venv "$APP_DIR/.venv"
fi
"$APP_DIR/.venv/bin/pip" install --upgrade pip wheel
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"  # always run this
```

---

### 6.4 init.sh Requires `bash` Prefix
**Severity:** LOW  
**Issue:** `init.sh` (line 1) has shebang `#!/usr/bin/env bash` but is NOT executable (`-x` flag missing). Must run as `bash ./init.sh`, not `./init.sh`.  
**Impact:** Operator may be confused by "Permission denied" when executing directly.  
**Evidence:** progress/current.md line 18 confirms this.  
**Fix:** Make executable: `chmod +x init.sh`; or document the `bash ./init.sh` requirement prominently in README.

---

### 6.5 Missing .env.example Vars
**Severity:** LOW  
**Issue:** Feature flags `REVIEW_WORKFLOW_ENABLED`, `NOTIFICATIONS_ENABLED`, `AI_COPY_ENABLED`, `AI_NARRATION_ENABLED` are missing from `.env.example` but read by app.  
**Impact:** New deployments use silent defaults (false?); unclear intended behavior.  
**Fix:** Add all feature flags to `.env.example` with defaults and descriptions.

---

### 6.6 Postgres Binding Not Documented
**Severity:** LOW  
**Issue:** Service files don't specify postgres binding address (assumed localhost). For multi-server setup (postgres on separate host), operator must know to adjust DATABASE_URL.  
**Impact:** Operator may struggle to connect postgres on remote host.  
**Fix:** Clarify in README that DATABASE_URL supports any host; document single-host vs. multi-host setup.

---

### 6.7 No Backup Strategy Documented
**Severity:** MEDIUM  
**Issue:** `deploy/backups/` has one historical dump; no rotation, no schedule, no restore instructions.  
**Impact:** Data loss risk if postgres fails.  
**Fix:** Document daily backup cron, off-site copy, restore procedure in README.

---

### 6.8 Alembic Revision Conflicts Possible
**Severity:** MEDIUM  
**Issue:** Features auto-generate migrations with timestamps (e.g., `20260515_0005`). If two developers create features in parallel with same timestamp, conflicts arise.  
**Impact:** Manual conflict resolution required; merge downtime.  
**Mitigation:** Feature list (`feature_list.json`) enforces single `in_progress`; comment in code suggests feature 38 must wait until feature 37 closes (see progress/current.md L218–219).  
**Fix:** Use UUIDs or sequential IDs for migration revisions (requires refactor).

---

### 6.9 WEBHOOK_SITE_SECRETS Env-Only (Feature 38 Pending)
**Severity:** MEDIUM (pre-feature-38)  
**Issue:** Production webhook secrets stored only in `/etc/cpihed/cpihed.env`. Adding a new WordPress site requires:
1. Edit env file
2. Restart service (brief downtime)

**Status:** Feature 38 (`db_backed_webhook_secrets`) in progress; will resolve by reading secrets from BBDD with env fallback.  
**Current:** progress/current.md L237–257 documents this gap.  
**Fix:** Merge feature 38; feature also supports multi-site per agency.

---

### 6.10 No Monitoring / Alerting
**Severity:** MEDIUM  
**Issue:** No healthcheck daemon, no alert on service failure, no prometheus metrics.  
**Impact:** Operator must manually check logs or health endpoints.  
**Fix:** Add systemd monitoring (e.g., OnFailure notification) or third-party APM.

---

### 6.11 Frontend Deployment Unknown
**Severity:** MEDIUM  
**Issue:** This audit covers backend only. Frontend (`/opt/projects/4Reels-Frontend`) integration unclear:
- Static files served from backend? (app_factory.py L270–277 mounts `/assets/render-templates`; no frontend mount)
- Separate nginx location? (likely per progress/current.md references to `:5173` Vite dev server)
- Vercel? (unknown)

**Impact:** Operator may not know how to deploy frontend alongside backend.  
**Gap:** Cross-repo deployment workflow not documented.

---

## 7. Frontend Integration (Cross-Repo)

### 7.1 How Frontend is Served
**Backend mounts:** `/assets/render-templates` (static files for template previews; see app_factory.py L270–276).  
**No frontend mount:** The backend does NOT serve the admin UI SPA (React/Vue/etc.).

**Inferred setup:**
- **Frontend repo:** `/opt/projects/4Reels-Frontend` (separate Node.js/npm project)
- **Local dev:** Vite dev server on `:5173` (referenced in `.env.example` FRONTEND_BASE_URL L188)
- **Frontend is served:** Separately (likely nginx, Vercel, or build → static hosting)
- **Backend API location:** Frontend calls `http://localhost:8000/v1/admin/*` (or prod domain)

### 7.2 API Contract
Both repos share `feature_list.json` with **parallel feature IDs** (32–37 synchronized across back + front; see progress/current.md L130).

No OpenAPI schema sharing detected; frontend + backend maintain separate contracts (typical monorepo pattern).

---

## 8. Documentation Gaps Summary

### 8.1 TOP-3 Critical Gaps

1. **Missing Dockerfile** (§6.1)
   - `docker/Dockerfile` referenced but doesn't exist.
   - Blocks `docker compose build` and entire local dev startup.
   - **Action:** Create file immediately (10 min).

2. **Deployment Workflow Not Documented** (§5)
   - No step-by-step guide: "Push code → apply migrations → restart service."
   - No mention of install.sh usage (exists but unclear when/how).
   - Missing "first deploy" vs. "update" distinction.
   - **Action:** Create `docs/DEPLOYMENT.md` covering both initial setup and ongoing updates.

3. **Production Service Names Mismatch** (§6.2)
   - CLAUDE.md refers to "reels.service" (doesn't exist).
   - Actual services: `cpihed.service` (prod), `reels-test.service` (test).
   - Operator confusion risk.
   - **Action:** Update CLAUDE.md §L81 with correct service names; add table to deploy README.

### 8.2 Secondary Gaps

- ❌ No backup/restore procedure (deploy/backups/ exists but undocumented)
- ❌ `.env.example` missing 4 feature flag vars
- ❌ install.sh not idempotent; unclear update flow
- ❌ Feature 38 (db-backed secrets) still pending; env-only secrets are a gap
- ❌ No versioning / release tagging strategy
- ❌ Frontend deployment integration not documented
- ❌ Postgres binding address not documented (localhost assumed)

---

## 9. Files & Line References

| Component | File | Key Lines |
|-----------|------|-----------|
| Init harness | `init.sh` | L21–188 (7 stages) |
| Dev stack | `compose.yml` | L1–74 (3 services) |
| Dockerfile | `docker/Dockerfile` | **MISSING** |
| Postgres (dev) | `docker/postgresql/README.md` | L1–10 |
| Prod installer | `deploy/rocky-linux/install.sh` | L1–41 |
| Prod service (api) | `deploy/rocky-linux/cpihed.service` | L1–23 |
| Test service (api) | `deploy/rocky-linux/reels-test.service` | L1–27 |
| Test service (worker) | `deploy/rocky-linux/reels-test-worker.service` | L1–29 |
| Prod README | `deploy/rocky-linux/README.md` | L1–87 |
| Env template | `.env.example` | L1–189 (100+ vars) |
| Settings index | `settings/__init__.py` | L1–267 (exports) |
| App factory | `apps/api/app_factory.py` | L128–298 (build + routers) |
| Feature list | `feature_list.json` | (parallel front + back) |
| Progress tracking | `progress/current.md` | L1–460 (detailed session log) |
| Rules | `CLAUDE.md` | L1–89 (role, hotfix, service names) |
| Legacy migration | `deploy/migrate_legacy_schema_to_20260501.py` | L1–50 (schema bridge) |

---

## 10. Recommendations for docs/DEPLOYMENT.md

Structure the new `docs/DEPLOYMENT.md` as:

```markdown
# Deployment Guide

## 1. Architecture Overview
- Dev (docker-compose), Test (systemd), Prod (systemd on Rocky Linux)
- Service ports: 8000 (prod api), 8001 (test api), 5432 (postgres)
- No CI/CD pipeline; manual deployment process

## 2. Initial Setup (Prod)
- System packages (python3.11, ffmpeg, RPM Fusion)
- Clone repo to /opt/cpihed
- Run install.sh
- Edit /etc/cpihed/cpihed.env
- Validate with --check
- Enable systemd service

## 3. Code Update & Deployment
- Pull latest main into /opt/cpihed
- Pip install (if deps changed)
- Apply migrations: alembic upgrade head
- Restart service: systemctl restart cpihed
- Validate: curl /health/ready

## 4. Database Migrations
- Auto-applied on service start (if configured)
- Manual: alembic upgrade head
- Rollback: alembic downgrade -1

## 5. Backup & Restore
- Daily pg_dump
- Off-site copy
- Restore procedure

## 6. Monitoring & Logs
- journalctl -u cpihed -f
- Health endpoints: /health/live, /health/ready

## 7. Troubleshooting
- Service won't start: journalctl, --check diagnostics
- Webhook auth fails: verify WEBHOOK_SITE_SECRETS, secrets_encrypted in BBDD (feature 38)
- Memory issues: tune REEL_FFMPEG_FILTER_THREADS, REEL_FFMPEG_ENCODER_THREADS

## 8. Frontend Integration
- Admin UI served separately (not by backend)
- Backend API at https://api.yourdomain.tld/v1/admin/*
- Static assets: /assets/render-templates (templates only)
```

---

**END OF AUDIT**
