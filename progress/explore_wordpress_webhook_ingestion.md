# WordPress Webhook Ingestion Flow — Read-Only Mapping

**Date:** 2026-05-15  
**Scope:** Entry point, agency resolution, constraints, tests, multi-tenancy

---

## 1. Entry Point (Webhook Endpoint)

### HTTP Endpoint

- **Path:** `/v1/ingest/wordpress/property`  
  **File:** `modules/ingestion/transport/http/wordpress_webhook_router.py:55`

- **Router Definition:**  
  `create_wordpress_webhook_router(…)` at `modules/ingestion/transport/http/wordpress_webhook_router.py:66`  
  Returns a FastAPI `APIRouter` with a single POST endpoint.

- **Handler:** `ingest_wordpress_property_endpoint(request: Request)` at `modules/ingestion/transport/http/wordpress_webhook_router.py:90`  
  Async endpoint returning `JSONResponse` with HTTP 202 (Accepted).

### Request Contract

**Headers:**
- `Content-Type`: Must be `application/json` (validated at line 95-106)
- `X-WP-Site-Id`: Optional site_id override (resolved from header or payload, line 91)
- `X-WP-Timestamp`: Security header for HMAC validation (line 92, 161-176)
- `X-WP-Signature`: HMAC signature for payload verification (line 93, 161-176)

**Payload Shape:** JSON object (array of length 1 unwrapped at `modules/ingestion/transport/http/wordpress_webhook_payloads.py:67-70`)  
**Payload Fields (extracted):**
- `id` (int): Property ID, mapped by `_extract_property_id(payload)` at line 226  
  **File:** `modules/ingestion/transport/http/wordpress_webhook_payloads.py:37-46`
- `rest_domain` (str): WordPress REST domain, used for site_id resolution  
  **File:** `modules/ingestion/transport/http/wordpress_webhook_payloads.py:78-81`
- `site_id` (str, optional): Direct site_id if `rest_domain` unavailable (line 83-85)
- `link` or `guid.rendered` (str): Fallback for hostname extraction (line 87-101)
- Other fields: Passed through as-is in `publish_context` and jobs payload

**Max Payload Size:** `1_048_576` bytes (1 MB) at `modules/ingestion/transport/http/wordpress_webhook_router.py:59`  
Enforced at line 119-142.

**Content-Length Validation:** Required header, validated at line 108-118.

---

## 2. Agency Resolution

### Resolution Logic

**File:** `modules/ingestion/transport/http/wordpress_webhook_router.py:90-150`

1. **Site ID resolution** (line 91-160):
   - Try header `X-WP-Site-Id` (line 91)
   - Fall back to payload's `rest_domain` or `site_id` field (line 149, called via `_resolve_site_id`)
   - Fall back to hostname from `link` or `guid.rendered` (line 148-160)
   - If no site_id can be resolved, return 400 `SITE_ID_REQUIRED` (line 151-160)

2. **Ingestion Source lookup** (line 252-262):
   ```python
   source = uow.ingestion.sources.get_by_kind_external_id(
       kind="wordpress",
       external_id=normalized_site_id,
   )
   ```
   **File:** `modules/ingestion/application/use_cases/ingest_wordpress_property.py:64-67`

3. **Agency ID extraction**:
   - `source.agency_id` is the resolved agency (from `ingestion_sources` row)
   - **Type:** String (UUID format, 36 chars)
   - **Field:** `IngestionSource.agency_id` at `modules/ingestion/domain/ingestion_source.py:18`

### Lookup Table Structure

**Table:** `ingestion_sources`  
**File:** `alembic/versions/20260501_0001_initial_schema.py:49-86`

| Column | Type | Comment |
|--------|------|---------|
| `id` | String(36) | Primary key, ingestion_source_id |
| `agency_id` | String(36) | FK to `agencies.id`, cascade delete |
| `kind` | Text | Discriminator: `'wordpress'` for WordPress sources |
| `external_id` | Text | The `site_id` (e.g., `'ckp.ie'`), normalized to lowercase |
| `name` | Text | Human-readable name (e.g., `'CKP WordPress'`) |
| `config_json` | JSONB | Provider-specific config (e.g., API endpoints, metadata) |
| `secrets_encrypted` | BYTEA | Encrypted webhook signing secret |
| `status` | Text | `'active'` or other (webhook rejected if not `'active'`) |
| `last_event_at` | DateTime | Timestamp of most recent webhook, touched at line 200 |
| `created_at`, `updated_at` | DateTime | Standard audit timestamps |

**Lookup Query:**
```sql
SELECT id, agency_id, kind, external_id, name, config_json, secrets_encrypted, status, 
       last_event_at, created_at, updated_at
FROM ingestion_sources 
WHERE kind = :kind AND external_id = :external_id
```
**File:** `modules/ingestion/infrastructure/ingestion_source_repository.py:79-92`  
Normalization: `external_id` is lowercased (line 81), matching the inbound `site_id` after normalization (line 63 of use case).

**Relationship: 1 webhook site ↔ 1 agency (many sources per agency possible)**

A single WordPress site (`site_id`) maps to one and only one agency through its `ingestion_source` row:
- Multiple WordPress sites can belong to the same agency (1:N from agency perspective)
- Each site's webhook resolves to a unique agency via the `ingestion_sources` lookup
- **No shared sites across agencies** — if site A is provisioned for agency 1, it cannot send webhooks to agency 2

---

## 3. Constraints (UNIQUE, FK, etc.)

### Ingestion Sources Table Constraints

**File:** `shared/db/orm.py:64-96`

```python
class IngestionSourceORM(Base):
    __tablename__ = "ingestion_sources"
    __table_args__ = (
        UniqueConstraint("kind", "external_id", 
                        name="uq_ingestion_sources_kind_external_id"),
        UniqueConstraint("agency_id", "kind", "external_id",
                        name="uq_ingestion_sources_agency_kind_external"),
        Index("idx_ingestion_sources_agency_kind", "agency_id", "kind"),
    )
```

**Constraint 1: `uq_ingestion_sources_kind_external_id` (line 67)**  
```sql
UNIQUE(kind, external_id)
```
- **Prevents:** Two sources of the same kind with the same external_id globally
- **Implication:** Only one WordPress site named `'ckp.ie'` can exist in the entire platform (globally unique across all agencies)
- **Webhook implication:** If webhook tries to POST for `site_id='ckp.ie'`, the lookup will find the exact same source row every time (deterministic)
- **Backward compat note:** Replaces legacy schema's implicit per-agency uniqueness with global uniqueness

**Constraint 2: `uq_ingestion_sources_agency_kind_external` (line 74-79)**  
```sql
UNIQUE(agency_id, kind, external_id)
```
- **Redundant note:** This constraint is implied by Constraint 1 (if `(kind, external_id)` is unique, then `(agency_id, kind, external_id)` is also unique)
- **Serves:** Clarity in intent — per-agency, per-kind, per-site uniqueness is guaranteed
- **Practical:** Within agency A, only one `kind='wordpress'` source with `external_id='ckp.ie'` can exist

**Index: `idx_ingestion_sources_agency_kind` (line 74)**  
```sql
INDEX(agency_id, kind)
```
- **For:** Queries listing all WordPress sources for an agency (feature 31: `list_ingestion_sources`)
- **Hit rate:** High for admin UI, provisioning flows

### Foreign Key Constraint

**File:** `alembic/versions/20260501_0001_initial_schema.py:54-57`

```sql
CONSTRAINT fk_ingestion_sources_agency_id
  FOREIGN KEY (agency_id) REFERENCES agencies(id) ON DELETE CASCADE
```
- **Cascade delete:** If agency is deleted, all its ingestion sources are deleted
- **Enforcement:** PostgreSQL at database level

### Webhook Signing Secret Storage

**Column:** `ingestion_sources.secrets_encrypted` (BYTEA)  
**File:** `modules/ingestion/infrastructure/ingestion_source_repository.py:177`

Secrets are encrypted via `encrypt_text(secret)` before storage (line 177):
- **Encryption:** Fernet-based, implemented in `shared/db/security.py`
- **Decryption:** On-demand during webhook validation (line 200-206 in router)
- **Constraint:** No unique constraint on secrets — multiple sources can share the same signing key (although not recommended)

### Authentication Flow

**File:** `modules/ingestion/transport/http/wordpress_webhook_router.py:178-224`

1. Lookup expected secret from configuration:
   ```python
   expected_secret = settings.site_secrets.get(site_id)
   ```
   Line 179 — reads from `WordPressWebhookSettings.site_secrets` dict (environment-loaded at startup)

2. Verify signature via `verify_webhook_signature(…)`:
   **File:** `shared/http/webhook_signature.py:92-136`
   - Checks timestamp freshness (tolerance: 300 seconds by default, line 60)
   - Checks HMAC-SHA256 signature (line 200-206 in router)

3. Return 401 if authentication fails (line 208-224)

**Note:** `site_secrets` are environment variables (`WEBHOOK_SITE_SECRETS`), not database-backed. The `secrets_encrypted` column in `ingestion_sources` is for other purposes (future: per-site webhook secret management).

---

## 4. Tests

### Integration Tests

**File:** `tests/integration/ingestion/test_wordpress_webhook_flow.py`

#### Test: Webhook resolves agency and enqueues job
- **Line:** 41-83
- **Setup:** Seed tenant with `site_id='ckp.ie'`, provision GHL connection
- **POST:** `/v1/ingest/wordpress/property` with `rest_domain='ckp.ie'` and `id=1234`
- **Assertions:**
  - Status 202 (accepted)
  - Response includes `event_id`, `job_id`, `site_id`, `property_id`
  - `webhook_events` row created with agency_id matching seeded agency
  - `jobs` row created with `kind='reel_publish'`, `external_source_id='ckp.ie'`, `property_id=1234`
  - `provider_secret_bundle` includes GHL token

#### Test: Webhook rejects unknown site
- **Line:** 86-98
- **POST:** With `rest_domain='ghost.example'` (no ingestion source for it)
- **Assertion:** 404 `UNKNOWN_WORDPRESS_SITE` (thrown at line 69-77 of use case)

#### Test: Webhook rejects when agency has no GHL connection
- **Line:** 101-114
- **Setup:** Seed tenant but no provider connection
- **Assertion:** 404 `GHL_CONNECTION_NOT_FOUND` (thrown at line 84-92 of use case)

#### Test: Webhook enqueues even when dispatcher paused
- **Line:** 117-139
- **Setup:** Dispatcher state returns `False`
- **Assertion:** 202 (still accepted), job enqueued (not skipped)

#### Test: Webhook supersedes previous job for same property
- **Line:** 142-169
- **Setup:** POST twice with same `property_id=42`
- **Assertions:**
  - First job marked `status='superseded'`, `superseded_by_job_id=<second_job_id>`
  - First event marked `status='superseded'`
  - Second job `status='queued'`
- **Files involved:**
  - Supersede logic: `modules/ingestion/application/use_cases/ingest_wordpress_property.py:157-168`
  - Query: `modules/delivery/infrastructure/job_repository.py` (supersede_queued_jobs method)

#### Test: Webhook includes scheduled_at for quiet hours (Feature 15)
- **Line:** 172-299
- **Complex E2E:** Webhook → persisted job → worker ingest → scheduled_at computation
- **Setup:** Automation rules with quiet hours 09:00-18:00, wall clock frozen at 23:00 Dublin
- **Assertion:** Returned `scheduled_at` is deferred to next 09:00 Dublin and in future relative to wall clock
- **Note:** Webhook does **not** compute `scheduled_at`; that's the worker's job via `IngestPropertyIntoReelUseCase`

### Unit Tests

**File:** `tests/unit/ingestion/test_ingest_wordpress_property.py`

#### Test: Enqueues job with provider secret bundle
- **Line:** 18-57
- **Setup:** Mock repositories, mock sources/connections
- **Assertion:** Job enqueued with `provider_secret_bundle={"access_token": "tok-abc", "provider": "gohighlevel"}`

#### Test: Supersedes previous jobs
- **Line:** 60-89
- **Assertions:** `supersede_queued_jobs` called, webhook_events status updated to `'superseded'`

#### Test: Raises when site unknown
- **Line:** 92-111
- **Assertion:** `ResourceNotFoundError` with code `'UNKNOWN_WORDPRESS_SITE'`

#### Test: Forwards rich social templates (Feature 20)
- **Line:** 114-170
- **Setup:** Mock social templates with title_template and hashtags
- **Assertions:**
  - `social_templates` includes (platform, description) tuples
  - `social_title_templates` includes (platform, title) tuples (only non-empty)
  - `social_hashtags` is a dict mapping platform → list of hashtags (only if at least one)

#### Test: Raises when GHL connection missing
- **Line:** 173-193
- **Assertion:** `ResourceNotFoundError` with code `'GHL_CONNECTION_NOT_FOUND'`

### Test Fixtures / Seed Helpers

**File:** `tests/support/postgres.py`

- `seed_tenant(database_url, site_id=…)` → Tuple with pre-provisioned ingestion source
  - Returns: `seeded.agency_id`, `seeded.ingestion_source_id`, `seeded.external_source_id` (= site_id)
- `seed_provider_connection(database_url, agency_id, …)` → GoHighLevel provider connection row
- `temporary_postgres_schema(DATABASE_URL)` → Yields isolated test database instance

### Payload Contracts

**File:** `modules/ingestion/transport/http/wordpress_webhook_payloads.py`

**Property ID extraction** (line 37-46):
```python
def _extract_property_id(payload: dict[str, Any]) -> int | None:
    value = payload.get("id")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
```

**Site ID resolution** (line 78-103):
1. Try `payload['rest_domain']` (preferred)
2. Try `payload['site_id']` (fallback)
3. Try hostname from `payload['link']` or `payload['guid']['rendered']`
4. Return normalized hostname (lowercase, strip port/protocol)

---

## 5. Multi-Site Concept

### Current State

**No multi-site within agency in WordPress ingestion path.**

Each ingestion source (`external_id`) is a standalone WordPress site. The `external_id` field itself acts as the site identifier:
- WordPress site `'ckp.ie'` → ingestion source with `external_id='ckp.ie'`
- WordPress site `'4pm.ie'` → separate ingestion source with `external_id='4pm.ie'`

Both sites can belong to the same agency (multiple rows with same `agency_id` but different `external_id`).

### URL Structure in Admin Reels

**File:** `modules/reels/transport/http/admin_reels_router.py:6-14`

Admin reels endpoints include `{site_id}` in the path:
```
GET  /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}
GET  /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/approve
...
```

Here, `site_id` is the `external_source_id` from `ingestion_sources` (the WordPress domain, e.g., `'ckp.ie'`).

**Not an independent multi-tenant sub-unit:**  
The `site_id` in the URL is **not** a separate "multi-tenancy layer" within the agency. It is simply the ingestion source identifier used for routing lookups in the reel pipeline. See line 6-22 comments.

### Feature 37 (Manifest Override)

**File:** `modules/reels/transport/http/admin_reels_router.py:57-60`

Feature 37 adds per-reel slide manifest overrides but operates within the existing single-site-per-source model:
- Endpoints PATCH `/v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/slides`
- Override is keyed by `(external_source_id, source_property_id)` (reel's composite PK)
- No change to multi-tenancy model; this is per-reel customization within a source

---

## 6. Security: Authentication

### Webhook Signature Validation

**File:** `shared/http/webhook_signature.py:92-136`

```python
def verify_webhook_signature(
    *,
    secret: str,
    timestamp: str,
    site_id: str,
    raw_body: bytes,
    signature: str,
    tolerance_seconds: int,
    location_id: str = "",
    access_token: str = "",
    now: int | None = None,
) -> tuple[bool, str | None, str | None]:
```

**Signed message format** (line 22-40):
```
timestamp + \n + site_id + \n + location_id + \n + access_token + \n + raw_body
```

**Algorithm:** HMAC-SHA256 with secret key  
**Timestamp tolerance:** 300 seconds (configurable via `WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS`)  
**Timestamp validation:** Checks `|now - timestamp| <= tolerance_seconds` (line 109-117)

### Credentials Flow

**Router** (line 178-224):
1. Load expected secret from environment: `settings.site_secrets.get(site_id)` (line 179)
2. Call `verify_webhook_signature(secret=expected_secret, …)` (line 200-206)
3. Return 401 if:
   - Timestamp missing or outside window (line 162-176)
   - Signature missing (line 161-176)
   - No secret configured for site (line 180-199)
   - HMAC validation fails (line 208-224)

**Environment variable:** `WEBHOOK_SITE_SECRETS` (dict of `site_id → secret`)  
**File:** `settings/webhook.py:21` and `settings/app.py` (loads from env)

---

## 7. Payload Acceptance & Queuing

### HTTP Response Contract

**File:** `modules/ingestion/transport/http/wordpress_webhook_router.py:372-382`

**Success (202):**
```json
{
  "status": "accepted",
  "event_id": "<uuid>",
  "job_id": "<uuid>",
  "site_id": "<external_source_id>",
  "property_id": 1234,
  "site_auto_provisioned": false
}
```

**Errors:**
- 400: Invalid payload, missing site_id, invalid content-type, payload too large
- 401: Authentication failure (invalid secret or timestamp)
- 404: Unknown site or missing GHL connection
- 500: Internal error (database, configuration)

### Database Writes on Acceptance

**File:** `modules/ingestion/application/use_cases/ingest_wordpress_property.py:170-200`

1. **webhook_events row created** (line 170-180):
   - `event_id`: UUID
   - `agency_id`: From resolved ingestion source
   - `ingestion_source_id`: From resolved ingestion source
   - `external_source_id`: From resolved ingestion source
   - `property_id`: Extracted from payload
   - `status`: `'queued'`
   - `raw_payload_hash`: SHA256 of raw body (line 227)
   - `source_kind`: `'wordpress'`

2. **jobs row created** (line 181-199):
   - `job_id`: UUID
   - `event_id`: Linked to webhook_events row
   - `kind`: `'reel_publish'`
   - `external_source_id`, `property_id`: From payload
   - `payload_json`: Full webhook payload (line 192)
   - `publish_context_json`: Agency defaults + configuration (lines 137-146)
   - `provider_secrets_encrypted`: GHL access token (lines 147-151)
   - `status`: `'queued'`
   - `available_at`: Now (line 196)
   - `max_attempts`: From router setting (typically 3)

3. **ingestion_sources row touched** (line 200):
   - `last_event_at`: Updated to now

### Configuration Included in Job

**File:** `modules/ingestion/application/use_cases/ingest_wordpress_property.py:98-146`

Worker receives a complete context from agency configuration:

```python
publish_context = {
    "provider": "gohighlevel",
    "location_id": ghl_connection.external_id,
    "platforms": list(platforms),  # From defaults or use case input
    "approval_required": approval_required,  # From automation rules
    "social_templates": list(social_templates),  # Platform-specific copy
    "social_title_templates": list(social_title_templates),  # Feature 20
    "social_hashtags": social_hashtags_map,  # Feature 20
    "render_template_id": render_template_id,  # From defaults
}
```

This context is read from:
- `agency_reel_defaults` (platforms, render_template_id)
- `agency_automation_rules` (approval_required)
- `agency_social_templates` (rich copy templates)

---

## 8. Key Files Summary

| Path | Purpose | Key Line Refs |
|------|---------|---------------|
| `modules/ingestion/transport/http/wordpress_webhook_router.py` | HTTP endpoint definition | 55 (path), 80-382 (handler) |
| `modules/ingestion/application/use_cases/ingest_wordpress_property.py` | Agency resolution + job enqueue | 48-210 (execute) |
| `modules/ingestion/transport/http/wordpress_webhook_payloads.py` | Payload parsing helpers | 27-120 (parsing) |
| `modules/ingestion/infrastructure/ingestion_source_repository.py` | Source CRUD + lookup | 79-92 (get_by_kind_external_id) |
| `modules/ingestion/domain/ingestion_source.py` | Source value object | 15-28 (IngestionSource) |
| `shared/http/webhook_signature.py` | HMAC validation | 92-136 (verify_webhook_signature) |
| `shared/db/orm.py` | SQLAlchemy ORM mappings | 64-96 (IngestionSourceORM) |
| `alembic/versions/20260501_0001_initial_schema.py` | Schema definition | 49-86 (ingestion_sources table) |
| `tests/integration/ingestion/test_wordpress_webhook_flow.py` | Integration tests | 41-323 (full flow tests) |
| `tests/unit/ingestion/test_ingest_wordpress_property.py` | Unit tests | 18-193 (use case tests) |

---

## Summary

### Entry Point
- **Endpoint:** `POST /v1/ingest/wordpress/property` (line 55 of wordpress_webhook_router.py)
- **Payload shape:** JSON object with `id`, `rest_domain`/`site_id`, optional `link`/`guid`
- **Headers:** `Content-Type`, optional `X-WP-Site-Id`, `X-WP-Timestamp`, `X-WP-Signature`
- **Max size:** 1 MB

### Agency Resolution
- Webhook is routed by `site_id` (WordPress domain, e.g., `'ckp.ie'`)
- Lookup: `ingestion_sources.get_by_kind_external_id(kind='wordpress', external_id=site_id)`
- Returns `source.agency_id` (UUID from that row)

### Constraints
- **UNIQUE(kind, external_id):** Only one WordPress site with a given domain globally
- **UNIQUE(agency_id, kind, external_id):** Redundant, but explicit per-agency uniqueness
- **FK(agency_id):** CASCADE delete on agency removal
- **Signing secrets:** Environment-loaded (`WEBHOOK_SITE_SECRETS`), not database-backed

### Tests
- Integration: Happy path, unknown site, missing GHL, paused dispatcher, supersede, quiet hours (features 15, 20)
- Unit: Job enqueue, supersede, social templates, error cases

### Multi-Site
- No multi-tenant sub-unit within agency for WordPress ingestion
- Each WordPress site is a separate `ingestion_source` row
- Multiple WordPress sites can belong to the same agency (1:N relationship)
- `site_id` in admin URLs is simply the `external_source_id` for routing, not a separate tenant layer
- Feature 37 (slide manifest override) operates within the existing model

