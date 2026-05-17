# GoHighLevel (GHL) Integration Mapping

## 1. Schema: GHL Account & Location Persistence

### Primary Table: `provider_connections`
**Path**: `/opt/projects/4Reels-Backend/shared/db/orm.py:101-131`

```
provider_connections (
  id: String(36) PRIMARY KEY,
  agency_id: String(36) FK→agencies.id [CASCADE],
  provider: Text NOT NULL                        -- discriminator: "gohighlevel"
  external_id: Text NOT NULL DEFAULT ''          -- stores location_id
  config_json: JSONB DEFAULT '{}'                -- public metadata (user_id, expires_at)
  secrets_encrypted: LargeBinary NOT NULL        -- encrypted: {access_token, refresh_token, expires_at}
  status: Text DEFAULT 'active'
  created_at: DateTime
  updated_at: DateTime
)
```

**Constraints** (alembic/versions/20260501_0001_initial_schema.py:88-116):
- `UNIQUE(agency_id, provider)` — **One GHL connection per agency** — enforces 1:1 multiplicity
- `INDEX(provider, external_id)` — reverse lookup by location_id across agencies
- `FK(agency_id)` with `ON DELETE CASCADE`

**Key Field Mapping**:
- `external_id` ↔ GHL `location_id` — stored in plain text, queryable
- `config_json` ↔ Public state: `{"user_id": "...", "expires_at": "..."}`
- `secrets_encrypted` ↔ OAuth tokens (access/refresh) + provider info

### No Separate GHL Table
The refactor (20260501_0001_initial_schema.py:1-21) consolidates:
- Legacy `gohighlevel_tokens` → `provider_connections(provider='gohighlevel', external_id=location_id)`
- Legacy `ghl_connections` → Same table with UNIQUE(agency_id, provider)
- Last published location tracked at reel level: `reels.last_published_provider_external_id`

---

## 2. Onboarding / Association: Agency ↔ GHL

### Attachment Flow (Admin-Initiated)

**Endpoint**: `POST /v1/admin/agencies/{agency_id}/ghl-connection`
- **Router**: `/opt/projects/4Reels-Backend/modules/publishing/transport/http/connections_router.py:77-138`
- **Payload**: `ProviderConnectionUpsertPayload` with:
  - `location_id` → validated non-empty
  - `access_token` → validated non-empty
  - `user_id`, `refresh_token`, `expires_at` (optional)
  - `status` (default: "active")

**Use Case**: `AttachProviderConnectionUseCase`
- **Path**: `/opt/projects/4Reels-Backend/modules/publishing/application/use_cases/attach_provider_connection.py:23-78`
- **Logic** (lines 44-78):
  1. Validate `agency_id` exists (→ 404 if not)
  2. Validate `location_id` and `access_token` non-empty (→ 400 if empty)
  3. Store via `ProviderConnectionRepository.upsert()`
     - Splits config (`user_id`, `expires_at`) into plain-text `config_json`
     - Encrypts secrets (`access_token`, `refresh_token`) as `secrets_encrypted` via Fernet
  4. Returns `ProviderConnection` (redacted — no plaintext tokens in response)

**Repository**: `ProviderConnectionRepository`
- **Path**: `/opt/projects/4Reels-Backend/modules/publishing/infrastructure/provider_connection_repository.py:190-260`
- **Upsert Logic** (lines 190-260):
  - Lookup by `(agency_id, provider)` to check if row exists
  - INSERT if new (generates UUID for `id`)
  - UPDATE if exists (preserves `id`, updates tokens + config + status)
  - Both operations use raw SQL with CAST to avoid ORM auto-flush quirks

### Rotation Flow (Token Refresh)

**Endpoint**: `PUT /v1/admin/agencies/{agency_id}/ghl-connection`
- **Router**: `/opt/projects/4Reels-Backend/modules/publishing/transport/http/connections_router.py:140-195`
- **Use Case**: `RotateProviderCredentialsUseCase` (same contract as attach, but fails 404 if no connection exists)

### Session-Based Flow (User Self-Service)

**Endpoint**: `POST /v1/sessions/gohighlevel/session`
- **Router**: `/opt/projects/4Reels-Backend/modules/publishing/transport/http/sessions_router.py:142-194`
- **Input**: `GoHighLevelSessionPayload(location_id, user_id)`
- **Use Case**: `InspectSessionStatusUseCase`
  - **Path**: `/opt/projects/4Reels-Backend/modules/publishing/application/use_cases/inspect_session_status.py:30-55`
  - **Query** (line 44): `get_by_provider_external_id_with_secrets(provider='gohighlevel', external_id=location_id)`
  - Returns `SessionStatus`: `{location_id, user_id, connected: bool, has_token: bool, agency_id: str | None}`
  - If connected + authenticated, issues JWT `agency_token` (feature 14c)

**SSO Context Decoding**:
- **Endpoint**: `POST /v1/sessions/gohighlevel/context`
- **Router**: `/opt/projects/4Reels-Backend/modules/publishing/transport/http/sessions_router.py:75-140`
- **Use Case**: `DecodeSessionContextUseCase`
  - Decrypts GHL iframe `userData` blob using `GO_HIGH_LEVEL_APP_SHARED_SECRET`
  - Extracts `activeLocation` → `location_id`
  - **No direct DB write** — context is decrypted only, lookup happens in next step (`/session`)

---

## 3. Runtime Lookup: Agency ↔ GHL Location Resolution

### Path: Webhook → Job Enqueue → Worker → Publish

#### **Step 1: Webhook Acceptance (IngestWordPressPropertyUseCase)**
- **Path**: `/opt/projects/4Reels-Backend/modules/ingestion/application/use_cases/ingest_wordpress_property.py`
- **Lines 79-96**: Resolve GHL connection by agency
  ```python
  ghl_connection = uow.publishing.connections.get_with_secrets(
      agency_id=source.agency_id,
      provider="gohighlevel",
  )
  ```
  - **Query**: `ProviderConnectionRepository.get_with_secrets(agency_id, provider='gohighlevel')`
  - **Assumption**: 1:1 mapping — one active GHL per agency
  - **Failure**: 404 `GHL_CONNECTION_NOT_FOUND` if missing → webhook rejected

- **Lines 137-151**: Build `publish_context` for the job
  ```python
  publish_context = {
      "provider": "gohighlevel",
      "location_id": ghl_connection.external_id,  # ← Location ID from provider_connections
      "platforms": list(platforms),
      "approval_required": approval_required,
      ...
  }
  ```

#### **Step 2: Job Enqueue (JobRepository.enqueue_job)**
- **Path**: `/opt/projects/4Reels-Backend/modules/delivery/infrastructure/job_repository.py`
- **Storage**: 
  - `publish_context` → `jobs.publish_context_json` (JSONB)
  - `ghl_connection.secrets` (with access_token) → `jobs.provider_secrets_encrypted` (LargeBinary, encrypted)

#### **Step 3: Worker: Job Fetch & Property Media Job Build**
- **Path**: `/opt/projects/4Reels-Backend/modules/reels/application/orchestrator.py:114-122`
  ```python
  media_job = build_property_media_job(job)
  ```
  - **Line 281**: Deserializes `job.publish_context_json` → dict
  - **Line 277-282**: Merges `access_token` from `job.provider_secrets_encrypted` into publish_context
  - **Result**: `PropertyMediaJob` with `publish_context` containing:
    - `location_id` (from `provider_connections.external_id`)
    - `access_token` (decrypted from `provider_secrets_encrypted`)
    - `platforms`, `approval_required`, etc.

#### **Step 4: Publishing (GoHighLevelPropertyPublisher)**
- **Path**: `/opt/projects/4Reels-Backend/modules/publishing/infrastructure/adapters/gohighlevel/property_publisher.py:54-109`
- **Publish Request** (lines 90-105):
  ```python
  request = MultiPlatformPublishRequest(
      location_id=context.publish_context.location_id,
      access_token=context.publish_context.access_token,
      ...
  )
  ```
- **Direct HTTP to GHL API** (no additional DB lookup):
  - `GoHighLevelClient` uses `location_id` + `access_token` directly
  - No reverse lookup; assumes 1:1 agency↔location

### Summary: Assumption of 1:1
**Every query for "which GHL location for this agency?" assumes 0 or 1 result**:
- `UNIQUE(agency_id, provider)` enforces it at schema level
- `get_with_secrets(agency_id='X', provider='gohighlevel')` returns exactly one row or NULL
- **No support for multi-location per agency** — would require schema/query redesign

---

## 4. Tests Covering Agency ↔ GHL Association

### Connection Tests (Attach/Rotate)
- **Path**: `/opt/projects/4Reels-Backend/tests/integration/publishing/test_connections_router.py`
  - `test_attach_persists_connection_with_encrypted_tokens()` (lines 65-104)
    - Validates: attach endpoint → row in `provider_connections` with encrypted tokens
    - Verifies: redacted response (no plaintext tokens)
  - `test_attach_returns_404_for_unknown_agency()` (lines 107-120)
  - `test_attach_rejects_empty_access_token_with_400()` (lines 123-133)
  - `test_inspect_returns_redacted_view_when_connection_exists()` (lines 136-150)

### Session Tests (User Self-Service)
- **Path**: `/opt/projects/4Reels-Backend/tests/integration/publishing/test_gohighlevel_session_router.py`
  - `test_tokens_lists_saved_gohighlevel_connections_without_plaintext_tokens()` (lines 63-100)
    - Validates: `/v1/sessions/gohighlevel/tokens` lists all agencies with GHL
  - `test_context_decrypts_custom_page_payload()` (lines 103-135)
    - Validates: SSO context decryption extracts `location_id`
  - `test_session_reports_connected_agency_for_saved_location()` (lines 138-150)
    - Validates: `/v1/sessions/gohighlevel/session` lookup by location_id → agency_id

### Webhook → Job → Publish Flow
- **Path**: `/opt/projects/4Reels-Backend/tests/integration/ingestion/test_wordpress_webhook_flow.py`
  - `test_wordpress_webhook_resolves_agency_and_enqueues_job()` (lines 41-83)
    - **Setup**: seed tenant + GHL connection with `external_id="loc-1"` + `secrets={"access_token": "tok-1"}`
    - **POST** `/v1/ingest/wordpress/property` → webhook
    - **Verify**: 
      - Job enqueued with `provider_secret_bundle = {"access_token": "tok-1", "provider": "gohighlevel"}`
      - Job's `publish_context` carries location_id
  - `test_wordpress_webhook_rejects_when_agency_has_no_ghl_connection()` (lines 101-114)
    - Validates: 404 `GHL_CONNECTION_NOT_FOUND` if connection missing

- **Path**: `/opt/projects/4Reels-Backend/tests/integration/reels/test_publish_reel_flow.py`
  - End-to-end: webhook → enqueue → worker ingest → persist → publish
  - Uses seeded GHL connection to provide location_id + access_token to publisher

### Unit Tests (Use Cases)
- **Path**: `/opt/projects/4Reels-Backend/tests/unit/publishing/test_attach_provider_connection.py`
  - Tests validation and encryption in isolation
- **Path**: `/opt/projects/4Reels-Backend/tests/unit/publishing/test_inspect_provider_connection.py`
  - Tests lookup and redaction logic

---

## 5. Key Files & Lines Summary

| Aspect | File | Lines | Note |
|--------|------|-------|------|
| **Schema** | `shared/db/orm.py` | 101–131 | `ProviderConnectionORM` table |
| **Migration** | `alembic/versions/20260501_0001_initial_schema.py` | 88–116 | CREATE TABLE + UNIQUE constraint |
| **Domain** | `modules/publishing/domain/provider_connection.py` | 1–43 | Data classes + secrets wrapper |
| **Repository** | `modules/publishing/infrastructure/provider_connection_repository.py` | 1–277 | CRUD, encryption/decryption |
| **Attach Use Case** | `modules/publishing/application/use_cases/attach_provider_connection.py` | 1–85 | Validation + upsert |
| **Session Inspect** | `modules/publishing/application/use_cases/inspect_session_status.py` | 1–65 | Query by location_id → agency_id |
| **Connections Router** | `modules/publishing/transport/http/connections_router.py` | 1–250+ | Admin endpoints (attach/rotate) |
| **Sessions Router** | `modules/publishing/transport/http/sessions_router.py` | 1–250+ | User SSO endpoints |
| **Ingestion** | `modules/ingestion/application/use_cases/ingest_wordpress_property.py` | 79–151 | Webhook → GHL lookup → job enqueue |
| **Orchestrator** | `modules/reels/application/orchestrator.py` | 114–122, 267–297 | Worker entry point + job build |
| **Publisher** | `modules/publishing/infrastructure/adapters/gohighlevel/property_publisher.py` | 54–109 | Direct publish with location_id + token |
| **Tests (Integration)** | `tests/integration/publishing/test_connections_router.py` | 65–150 | Attach/rotate/inspect tests |
| **Tests (Integration)** | `tests/integration/publishing/test_gohighlevel_session_router.py` | 63–150 | Session + SSO tests |
| **Tests (Integration)** | `tests/integration/ingestion/test_wordpress_webhook_flow.py` | 41–114 | Webhook → job enqueue |
| **Tests (Integration)** | `tests/integration/reels/test_publish_reel_flow.py` | Various | End-to-end publish |

---

## 6. Architecture Summary

```
┌─────────────────────────────────────────────────────────────┐
│ Admin Panel / OAuth Flow                                     │
│ POST /admin/agencies/{id}/ghl-connection                     │
│ + location_id + access_token                                 │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
            ┌─────────────────────────┐
            │  AttachProviderConnection│
            │  UseCase                 │
            └────────┬────────────────┘
                     │
                     ▼
        ┌──────────────────────────────┐
        │ ProviderConnectionRepository │
        │ .upsert()                    │
        └────────┬─────────────────────┘
                 │
                 ▼
    ╔═════════════════════════════════════════════════════════╗
    ║  provider_connections table                              ║
    ║  ─────────────────────────────────────────────────      ║
    ║  id (PK)                                                 ║
    ║  agency_id (FK, part of UNIQUE)                          ║
    ║  provider = "gohighlevel" (part of UNIQUE)               ║
    ║  external_id = location_id ◄─ plain text, indexed       ║
    ║  config_json = {user_id, expires_at}                     ║
    ║  secrets_encrypted = {access_token, refresh_token}      ║
    ║  status = "active"                                       ║
    ║  ─────────────────────────────────────────────────      ║
    ║  UNIQUE(agency_id, provider) ◄─ enforces 1:1            ║
    ║  INDEX(provider, external_id)                            ║
    ╚═════════════════════════════════════════════════════════╝
         │                │
         │ WEBHOOK        │ SESSION LOOKUP
         │ FLOW           │
         ▼                ▼
    POST /ingest/   /sessions/gohighlevel/session
    wordpress       (location_id) ──┐
         │                          │
         ▼                          ▼
    Ingest Use Case  InspectSessionStatus
    - query: get_with_secrets    - query: get_by_provider_external_id_with_secrets
      (agency_id, "gohighlevel")   (provider, location_id)
    - returns: 1 connection      - returns: connection → agency_id
         │                          │
         │ BUILD                    ▼
         │ publish_context          JWT agency_token
         │ {location_id,
         │  access_token,
         │  platforms, ...}
         │
         ▼
    JobRepository.enqueue_job()
    - publish_context → jobs.publish_context_json
    - access_token → jobs.provider_secrets_encrypted
         │
         │ WORKER PULLS JOB
         │
         ▼
    ReelPipeline.handle()
    - Rebuilds publish_context from job
    - Merges decrypted access_token
         │
         ▼
    GoHighLevelPropertyPublisher
    - location_id + access_token → POST /api/locations/{location_id}/...
```

---

## 7. Caveats & Assumptions

1. **1:1 Agency ↔ GHL Location**: Schema enforces `UNIQUE(agency_id, provider)`. 
   - If future requirement is multi-location per agency, requires schema refactor (composite PK or new table).
   
2. **No Location Migration Tracking**: No audit trail when location_id changes. Changing attachment overwrites `external_id`.

3. **Access Token in Plain Text in Job**: `provider_secret_bundle` is encrypted at rest but decrypted every time a job runs. No refresh token automation — tokens must be manually rotated via admin endpoint.

4. **Session Lookup Assumes Unique Location**: `get_by_provider_external_id()` treats location_id as globally unique. If multiple agencies could own the same location (unlikely but possible), this breaks.

5. **No Validation of location_id Format**: Accepts any non-empty string; doesn't validate against GHL API at attach time.

