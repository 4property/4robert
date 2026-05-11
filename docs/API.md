# API reference — 4reels backend

This document is the high-level guide to the HTTP surface. The runtime
OpenAPI doc is served at `/docs` (Swagger UI). Use this Markdown file for the
mental model — what each endpoint *means* and which DB columns it owns.

For the on-the-wire contract (request bodies, examples, error codes) the
authoritative source is Swagger.

---

## 1. Tenancy model

```
agencies (1) ── (N) ingestion_sources          ← what site sent the webhook
agencies (1) ── (1) provider_connections       ← location_id + access_token (GHL)
agencies (1) ── (1) agency_brand_settings      ← Brand section
agencies (1) ── (1) agency_reel_defaults       ← Defaults section (owns `platforms`)
agencies (1) ── (1) agency_automation_rules    ← Automation section
agencies (1) ── (1) agency_social_templates    ← Social templates section
```

* **`agencies`** — the real-estate agency. The unit of customisation, billing
  and access control.
* **`ingestion_sources`** — every WordPress (or other) site that posts
  webhooks. The `site_id` column equals the value WordPress sends as
  `rest_domain` on the webhook body. One agency can own many sites; the same
  hostname can never be registered twice.
* **`provider_connections`** — exactly one GoHighLevel location is bound to
  an agency. Holds the access token, refresh token and expiry. The webhook
  never receives these directly — the backend resolves them from the agency.
* **Per-section configuration tables** — each customisation tab in the UI
  owns its own typed table. There is no shared `reel_profiles` row and no
  `extra_settings_json` blob. See §3 for the canonical fields each section
  accepts. PUTs are partial: omitted fields preserve the previously stored
  value, and the free-form `agency_reel_defaults.settings` (jsonb) is merged
  shallow.

## 2. Webhook flow

`POST /webhooks/wordpress/property` is the single entry point WordPress
plugins post to. Resolution chain on every call:

```
body.rest_domain
    → site_id (lowercased hostname)
    → ingestion_sources.agency_id
    → provider_connections (location_id + access_token)
    → agency_reel_defaults.platforms (publish targets)
    → enqueue PropertyMediaJob
```

The webhook body **must not** carry `location_id` or any GHL token — those
fields are deliberately ignored. Only `rest_domain` matters for tenancy
resolution. Failures surface as `UNKNOWN_WORDPRESS_SITE` or
`GHL_CONNECTION_NOT_FOUND` so it is obvious which step in the chain broke.

### Scripted render

External scripted-render clients enqueue work through:

`POST /v1/videos/scripted/render`

The endpoint accepts a JSON manifest with `site_id` and
`source_property_id`, resolves the tenant from the active WordPress ingestion
source, writes a `webhook_events` audit row with `source_kind='scripted_api'`,
enqueues a `scripted_render` job, and returns `202 Accepted`:

```json
{
  "status": "accepted",
  "job_id": "<uuid>",
  "event_id": "<uuid>",
  "site_id": "ckp.ie",
  "source_property_id": 170800
}
```

The unversioned scripted-render route has no compatibility alias; clients must
move to the `/v1/` URL.

## 3. Configuration sections

Each customisation tab in the agency-facing UI maps to exactly one endpoint
pair, and each endpoint owns its own typed table (no shared `reel_profiles`
row, no `extra_settings_json` blob). The Pydantic payloads use
`extra="forbid"`, so any unknown key returns 422 — keep frontend bodies in
lockstep with the canonical fields below.

| UI tab | Endpoint pair | Owning table | Canonical fields accepted (PUT) |
|---|---|---|---|
| **Brand** | `GET / PUT /admin/agencies/{id}/brand` | `agency_brand_settings` | `primary_color`, `secondary_color`, `logo_position`, `logo_object_key`, `intro_logo_object_key`, `font_family` |
| **Defaults** | `GET / PUT /admin/agencies/{id}/defaults` | `agency_reel_defaults` | `platforms` (canonical owner), `duration_seconds` (5..180), `music_id`, `intro_enabled`, `caption_template`, `settings` (free-form jsonb, merged shallow) |
| **Automation** | `GET / PUT /admin/agencies/{id}/automation` | `agency_automation_rules` | `approval_required`, `publish_window_start`, `publish_window_end`, `publish_days`, `trigger_on_status` |
| **Social templates** | `GET / PUT /admin/agencies/{id}/social-templates` | `agency_social_templates` | `templates` (map of platform id → caption template) |

Notes:

- **`platforms` is owned by `/defaults`**, not `/automation`. Sending it to
  `/automation` returns 422.
- **`settings` is the free-form bucket on `/defaults`** for UI knobs that
  don't have a typed column (frontend INITIAL_DEFAULTS shape: currency,
  language, aspect, resolution, fps, subFont, subSize, etc., plus any
  namespaced keys like `automation.quietHoursEnabled` the frontend chooses
  to persist there). It is merged shallow with the previously stored object.
- **PUT bodies are partial.** Omitted fields preserve the previously stored
  value; the section endpoints never overwrite siblings they did not
  receive.
- The Brand endpoint does **not** accept `font` (use `font_family`),
  `tagline`, `watermark_enabled`, `outro_enabled`, `outro_headline` or
  `outro_sub`. The Automation endpoint does **not** accept `publish_mode`,
  `platforms`, `review_window_*`, `quiet_hours_*`, `skip_weekends`,
  `auto_captions`, `regen_on_update` or `review_emails`. The Sources
  endpoint does **not** accept `source_name` (use `name`) or
  `source_status` (use `status`).

## 4. Read-only content endpoints

These power the agency-facing dashboard. They are read-only and do not modify
any state.

| Endpoint | Returns |
|---|---|
| `GET /admin/agencies/{id}/reels` | recent property reels (`properties` ⨝ `property_pipeline_state` ⨝ latest `media_revisions`) |
| `GET /admin/agencies/{id}/social-accounts` | the GHL location's connected social accounts (Instagram, TikTok, …); falls back to `connected: false` if the agency has no GHL connection |

### Music library

The agency music library is real CRUD, not the old dashboard stub. Clients use
the versioned admin surface:

| Verb | Path | Response |
|---|---|---|
| `POST` | `/v1/admin/agencies/{id}/music` | `201 { status, agency_id, music_track }` |
| `GET` | `/v1/admin/agencies/{id}/music` | `200 { agency_id, items, count }` |
| `GET` | `/v1/admin/agencies/{id}/music/{music_id}` | `200 { agency_id, music_track }` |
| `PUT` | `/v1/admin/agencies/{id}/music/{music_id}` | `200 { status, agency_id, music_track }` |
| `DELETE` | `/v1/admin/agencies/{id}/music/{music_id}` | `200 { status, agency_id, music_id }` |

`music_track` objects carry:

```json
{
  "music_id": "<uuid>",
  "agency_id": "<uuid>",
  "display_name": "Sunset Drive",
  "object_key": "agencies/ckp/music/sunset-drive.mp3",
  "duration_seconds": 28,
  "is_default": false,
  "created_at": "2026-05-06T09:00:00Z"
}
```

Create requires `display_name`, `object_key` and a positive
`duration_seconds`; `is_default` defaults to `false`. Reconfigure accepts the
same fields as optional partial updates. Relevant error codes are
`MUSIC_TRACK_SAVE_FAILED`, `MUSIC_TRACK_NOT_FOUND`,
`MUSIC_TRACK_DISPLAY_NAME_REQUIRED`, `MUSIC_TRACK_OBJECT_KEY_REQUIRED`,
`MUSIC_TRACK_INVALID_DURATION` and `ADMIN_AGENCY_NOT_FOUND`.

The legacy `/v1/admin/agencies/{id}/music-tracks` stub is not exposed by the
backend.

## 5. Sessions

The backend does **not** expose `GET /me` and will not expose it. There is no
`users` table and no per-user authentication: the effective identity is
derived entirely on the frontend.

* **Platform super-admin** — identified by the bearer admin token. The
  frontend builds the user object locally via `buildMvpAdminUser` (hardcoded
  `role: 'Super Admin'`, permissions map with `admin: 'rw'` and everything
  else `'none'`).
* **Agency user** — identified by the GoHighLevel SSO context (location id
  + user id, optionally decrypted via `POST /v1/sessions/gohighlevel/context`
  when the iframe parent only ships encrypted payload). The frontend builds
  the user object via `buildMvpUser`, hydrating `agency_id` from the response
  of `POST /v1/sessions/gohighlevel/session`.

Both builders, the SSO context resolver and the permissions map live in
`4reels front/src/features/session/ghlMvpContext.js`. The session bootstrap
endpoints exposed by the backend are:

| Verb | Path | Purpose |
|---|---|---|
| `POST` | `/v1/sessions/gohighlevel/context` | Decrypt the encrypted SSO payload that GHL ships in the iframe. |
| `POST` | `/v1/sessions/gohighlevel/session` | Bind a `(location_id, user_id)` pair to the agency record and return `{agency_id, connected, agency_token?, agency_token_expires_at?}`. |
| `POST` | `/v1/sessions/gohighlevel/test`    | Probe the GHL connection for a given `location_id`. |

The frontend never calls a `/me` endpoint; if it did, the request would 404.

### 5.1 Admin authentication — super-admin vs agency-scoped

`/v1/admin/*` accepts two kinds of bearer tokens. The auth check lives in
`apps/api/admin_auth.py:authorize_admin_request`. Each handler under
`/v1/admin/*` MUST call it at the top before doing any work.

| Token sent | Path | Status | Code |
|---|---|---|---|
| _(none)_ | any `/v1/admin/*` | 401 | `ADMIN_AUTH_REQUIRED` |
| `ADMIN_API_TOKEN` (super-admin) | any `/v1/admin/*` | 200 | _(allowed)_ |
| Agency JWT (valid) | `/v1/admin/agencies/{my_agency_id}/...` | 200 | _(allowed)_ |
| Agency JWT (valid) | `/v1/admin/agencies/{other_agency_id}/...` | 403 | `AGENCY_TOKEN_AGENCY_MISMATCH` |
| Agency JWT (valid) | `/v1/admin/agencies` (list/create) | 403 | `AGENCY_TOKEN_FORBIDDEN_GLOBAL_ROUTE` |
| Agency JWT (valid) | `/v1/admin/wordpress-sources` (global) | 403 | `AGENCY_TOKEN_FORBIDDEN_GLOBAL_ROUTE` |
| Agency JWT (expired or bad signature) | any `/v1/admin/*` | 401 | `INVALID_ADMIN_TOKEN` |

The agency JWT is HS256-signed by `ADMIN_AGENCY_TOKEN_SECRET` and minted by
`POST /v1/sessions/gohighlevel/session` when the location has an agency
connected. Default TTL is 3600 s (`ADMIN_AGENCY_TOKEN_TTL_SECONDS`). The
response of that endpoint, in the connected case, looks like:

```json
{
  "ok": true,
  "location_id": "loc-1",
  "user_id": "user-1",
  "connected": true,
  "has_token": true,
  "agency_id": "<uuid>",
  "agency_token": "<jwt>",
  "agency_token_expires_at": "2026-05-07T15:00:00Z"
}
```

If `ADMIN_AGENCY_TOKEN_SECRET` is unset in production, the endpoint returns
503 `AGENCY_AUTH_NOT_CONFIGURED` so the misconfiguration is visible (it is
*not* silently downgraded to a no-token response). Tests that need the
endpoint to succeed without a secret set
`ADMIN_API_DISABLE_AUTH_FOR_TESTING=true`, in which case the two new fields
are simply omitted from the response.

The frontend stores the agency token in memory (preferred) or
`sessionStorage`, sends it as `Authorization: Bearer <jwt>` on every
admin request, and rotates by calling
`POST /v1/sessions/gohighlevel/session` again before expiry.

## 6. Admin-versus-agency routing

The frontend distinguishes two kinds of users:

* **Platform super-admin** — opens the app via `?admin=1` or the
  `VITE_MVP_ADMIN_*` env. Sees the **Admin** tab only — the agency
  configuration tabs (Reels, Music, Brand, Defaults, Automation, Social) are
  hidden.
* **Agency user** — opens the app from inside a GoHighLevel sub-account. Sees
  the configuration tabs but **not** the Admin tab.

Permissions are declared on the user object in
`src/features/session/ghlMvpContext.js`:

```js
buildMvpAdminUser → { admin: 'rw', everything else: 'none' }
buildMvpUser      → { admin: 'none', everything else: 'rw' }
```

The Topbar and `<RequirePermission>` already filter routes based on each
page's `requires` declaration in `src/app/pages.js`, so swapping the user
permissions is the only thing needed to enforce the split.

## 7. Swagger tags

The OpenAPI document is split into focused tags so `/docs` is easy to
navigate:

| Tag | Endpoints |
|---|---|
| `Admin · Agencies` | list / create / get / patch / delete agencies |
| `Admin · Sources` | list / get / upsert / delete WordPress sources (global and agency-scoped) |
| `Admin · GHL connection` | upsert / delete / test the agency's GHL connection |
| `Admin · Brand` | brand identity slice |
| `Admin · Defaults` | reel rendering defaults slice |
| `Admin · Automation` | automation rules slice |
| `Admin · Social templates` | per-network description templates |
| `Admin · Reel profile (raw)` | low-level full-document view |
| `Admin · Content` | read-only dashboards (reels, social accounts, music) |
| `Session · GoHighLevel` | iframe SSO decryption, session bootstrap, connection probe |
| `Webhooks` | WordPress ingest + `POST /v1/videos/scripted/render` |

## 8. Conventions

* All JSON error responses follow the same shape:
  ```json
  {
    "error": "Human-readable message.",
    "code": "MACHINE_READABLE_CODE",
    "hint": "Optional remediation hint.",
    "details": { /* context */ }
  }
  ```
* Timestamps are ISO-8601 strings (UTC) — both in JSON and in the DB.
* Money / sizes are always strings preserving the source formatting (e.g.
  `"€385,000"`).
* `agency_id` is a UUID string. `site_id` is a lowercase hostname.
