# API reference — 4reels backend

This document is the high-level guide to the HTTP surface. The runtime
OpenAPI doc is served at `/docs` (Swagger UI). Use this Markdown file for the
mental model — what each endpoint *means* and which DB columns it owns.

For the on-the-wire contract (request bodies, examples, error codes) the
authoritative source is Swagger.

---

## 1. Tenancy model

```
agencies (1) ── (N) wordpress_sources         ← what site sent the webhook
agencies (1) ── (1) ghl_connections            ← location_id + access_token
agencies (1) ── (1) reel_profiles              ← all customisation
```

* **`agencies`** — the real-estate agency. The unit of customisation, billing
  and access control.
* **`wordpress_sources`** — every WordPress site that posts webhooks. The
  `site_id` column equals the value WordPress sends as `rest_domain` on the
  webhook body. One agency can own many sites; the same hostname can never be
  registered twice.
* **`ghl_connections`** — exactly one GoHighLevel location is bound to an
  agency. Holds the access token, refresh token and expiry. The webhook never
  receives these directly — the backend resolves them from the agency.
* **`reel_profiles`** — every aspect of how the agency's reels are produced
  and published. Holds typed top-level columns (the most-frequently-touched
  knobs) plus an `extra_settings_json` blob keyed by section
  (`brand`, `defaults`, `automation`, `social_templates`). Each per-section
  endpoint described below replaces only its slice; siblings are preserved.

## 2. Webhook flow

`POST /webhooks/wordpress/property` is the single entry point WordPress
plugins post to. Resolution chain on every call:

```
body.rest_domain
    → site_id (lowercased hostname)
    → wordpress_sources.agency_id
    → ghl_connections (location_id + access_token)
    → reel_profiles.platforms (publish targets)
    → enqueue PropertyMediaJob
```

The webhook body **must not** carry `location_id` or any GHL token — those
fields are deliberately ignored. Only `rest_domain` matters for tenancy
resolution. Failures surface as `UNKNOWN_WORDPRESS_SITE` or
`GHL_CONNECTION_NOT_FOUND` so it is obvious which step in the chain broke.

## 3. Configuration sections

Each customisation tab in the agency-facing UI maps to exactly one endpoint
pair. The endpoints are documented under their own Swagger tag so the contract
is self-explanatory.

| UI tab | Endpoint pair | Top-level columns it edits | extra_settings key |
|---|---|---|---|
| **Brand** | `GET / PUT /admin/agencies/{id}/brand` | `brand_primary_color`, `brand_secondary_color`, `logo_position` | `brand` (font, tagline, watermark_enabled, outro_*) |
| **Defaults** | `GET / PUT /admin/agencies/{id}/defaults` | `intro_enabled`, `duration_seconds` | `defaults` (full INITIAL_DEFAULTS-shaped object: format & locale, subtitles, video & timing, audio, captions) |
| **Automation** | `GET / PUT /admin/agencies/{id}/automation` | `approval_required` (= `publish_mode === 'review'`), `platforms` | `automation` (review_window_*, quiet_hours_*, skip_weekends, auto_captions, regen_on_update, review_emails) |
| **Social templates** | `GET / PUT /admin/agencies/{id}/social-templates` | none | `social_templates` (map of platform id → caption template) |
| **Reel settings (raw, admin)** | `GET / PUT /admin/agencies/{id}/reel-profile` | every column | every key (replaces wholesale) |

The four section endpoints share a single internal helper that:

1. Loads the existing reel profile.
2. Replaces the top-level columns the section claims (any column not present in
   the body is left at its current value).
3. Merges the section's `extra_settings` slice with the existing one — only
   the keys claimed by that section are touched, everything else under
   `extra_settings_json` is preserved.

This is what guarantees that two tabs saving in parallel never stomp each
other.

## 4. Read-only content endpoints

These power the agency-facing dashboard. They are read-only and do not modify
any state.

| Endpoint | Returns |
|---|---|
| `GET /admin/agencies/{id}/reels` | recent property reels (`properties` ⨝ `property_pipeline_state` ⨝ latest `media_revisions`) |
| `GET /admin/agencies/{id}/social-accounts` | the GHL location's connected social accounts (Instagram, TikTok, …); falls back to `connected: false` if the agency has no GHL connection |
| `GET /admin/agencies/{id}/music-tracks` | **stub** — returns `{ items: [], implemented: false }` until the music library schema is added |

## 5. Admin-versus-agency routing

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

## 6. Swagger tags

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
| `Webhooks` | the WordPress webhook + scripted-render endpoint |

## 7. Conventions

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
