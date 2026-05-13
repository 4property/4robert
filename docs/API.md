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
render_templates (1) ── (N) agency_reel_defaults ← DB-backed render pack selection
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
    → agency_reel_defaults.render_template_id (render pack)
    → enqueue PropertyMediaJob
```

The webhook body **must not** carry `location_id` or any GHL token — those
fields are deliberately ignored. Only `rest_domain` matters for tenancy
resolution. Failures surface as `UNKNOWN_WORDPRESS_SITE` or
`GHL_CONNECTION_NOT_FOUND` so it is obvious which step in the chain broke.

#### Optional accent-color fields (feature 16)

The WordPress webhook payload may include two optional HEX-color
fields used by the `side_banner` render template:

| Field | Type | Purpose |
|---|---|---|
| `wppd_accent_text_color` | string (HEX) | Text color drawn inside the colored top/bottom panels and on the rotated status banner. |
| `wppd_accent_background_color` | string (HEX) | Background color of the top/bottom panels and the vertical status banner. Rendered with an alpha overlay of `@0.85` so the underlying photo bleeds through. |

Both fields are stored verbatim on
`properties.wppd_accent_text_color` / `properties.wppd_accent_background_color`.
Empty or omitted values are persisted as `NULL` and the renderer falls
back to `agency_brand_settings.primary_color` for both. The `classic`
render template ignores these fields entirely (regression-zero).

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
| **Defaults** | `GET / PUT /admin/agencies/{id}/defaults` | `agency_reel_defaults` | `platforms` (canonical owner), `duration_seconds` (5..180), `music_id`, `intro_enabled`, `caption_template`, `render_template_id`, `settings` (free-form jsonb, merged shallow) |
| **Automation** | `GET / PUT /admin/agencies/{id}/automation` | `agency_automation_rules` | `approval_required`, `publish_window_start`, `publish_window_end`, `publish_days`, `trigger_on_status`, `hold_window_seconds` (0..86400), `quiet_hours_enabled`, `skip_weekends` |
| **Social templates** | `GET / PUT /admin/agencies/{id}/social-templates` | `agency_social_templates` | `templates` (map of platform id → caption template) |
| **Render templates** | `GET /admin/agencies/{id}/render-templates`, `PUT /admin/agencies/{id}/render-template` | `render_templates`, `agency_reel_defaults.render_template_id` | `template_id` selection only; catalog edits are DB-only |

Notes:

- **`platforms` is owned by `/defaults`**, not `/automation`. Sending it to
  `/automation` returns 422.
- Platform identifiers currently recognized by the publisher are
  `instagram`, `tiktok`, `facebook`, `linkedin`, `youtube`, `gbp` /
  `google_business_profile` and `pinterest`.
- **`settings` is the free-form bucket on `/defaults`** for UI knobs that
  don't have a typed column (frontend INITIAL_DEFAULTS shape: currency,
  language, aspect, resolution, fps, subFont, subSize, etc., plus any
  namespaced keys like `automation.quietHoursEnabled` the frontend chooses
  to persist there). It is merged shallow with the previously stored object.
- **`render_template_id` selects one DB-backed render pack per agency.**
  Two render templates ship out of the box (feature 16):
  - `classic` (`layout_variant=classic`, `sort_order=0`): the original
    renderer with framed panels on a black-tinted backdrop.
  - `side_banner` (`layout_variant=side_banner`, `sort_order=1`):
    full-bleed photo + top-left info panel + vertical status banner
    pinned to the right edge + full-width agent/agency footer. The
    panel fills and text use per-property accent colors with an alpha
    overlay at `@0.85` (see the webhook fields below); when a property
    omits them, the renderer falls back to `BrandSettings.primary_color`
    of the agency. Applies to both the reel MP4 and the poster JPG.
  Active templates can be selected through
  `PUT /admin/agencies/{id}/render-template`; missing templates return
  404 and disabled templates return 400.
- **PUT bodies are partial.** Omitted fields preserve the previously stored
  value; the section endpoints never overwrite siblings they did not
  receive.
- The Brand endpoint does **not** accept `font` (use `font_family`),
  `tagline`, `watermark_enabled`, `outro_enabled`, `outro_headline` or
  `outro_sub`. The Automation endpoint does **not** accept `publish_mode`,
  `platforms`, `review_window_*`, `auto_captions`, `regen_on_update` or
  `review_emails`. It **does** accept `quiet_hours_enabled`,
  `skip_weekends` and `hold_window_seconds` since feature 13. The Sources
  endpoint does **not** accept `source_name` (use `name`) or
  `source_status` (use `status`).

#### Automation feature-13 fields

- `hold_window_seconds` (integer, `0..86400`, default `0`): delay in
  seconds to wait before computing the publish slot. `0` keeps the
  pre-feature-13 "immediate" behaviour. Values outside `[0, 86400]` are
  rejected with `422` by Pydantic.
- `quiet_hours_enabled` (boolean, default `false`): when `true`, the
  `[publish_window_start, publish_window_end]` interval (interpreted in
  the agency's local timezone, see `agencies.timezone`) is the only
  window during which publication is allowed. Requests that fall
  outside the window are deferred to the next occurrence of
  `publish_window_start`. When `false` the window is **ignored**: see
  the migration note below.
- `skip_weekends` (boolean, default `false`): when `true`, publishes
  scheduled for Saturday or Sunday (agency local) are deferred to the
  next Monday at `publish_window_start`. `publish_days` is still
  honoured on top, so if Monday is excluded the shift keeps walking
  forward.

All three fields follow the same partial-PUT semantics as the rest of
the section: omitted fields preserve the previously stored value.
Defaults only apply on the very first INSERT for a new agency.

**Migration note — semantics of `publish_window_*`.** Feature 11 (the
GHL `scheduleDate` wiring) implicitly treated `publish_window_start` /
`publish_window_end` as the "allowed hours" of the day. Feature 14
moves that interpretation behind the `quiet_hours_enabled` toggle:

* When `quiet_hours_enabled = true` the window is enforced exactly as
  feature 11 did — anything outside is deferred to the next allowed
  start.
* When `quiet_hours_enabled = false` the window is **silent**: the use
  case only defers when `hold_window_seconds > 0` or `skip_weekends`
  trips, and never compares the current time against
  `publish_window_*`. Agencies that existed before the feature-13
  migration receive `quiet_hours_enabled = false` from the column
  default, so their slot calculation effectively switches from "defer
  outside window" to "publish immediately" until the user opts in from
  the Automation UI. This is intentional — the legacy "window = allowed
  hours" reading is now an explicit toggle, not a hidden default.

### Brand logo upload (feature 10)

The admin UI uploads the agency's branding logo through a dedicated
multipart endpoint and then attaches the returned `object_key` to the
typed Brand row via the regular PUT `/admin/agencies/{id}/brand`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/admin/agencies/{agency_id}/brand/logo` | Upload a JPG/PNG (<=5 MB) and persist it under the workspace `_agency_branding/` folder. |
| `GET`  | `/admin/agencies/{agency_id}/brand/logo/file/{filename}` | Stream a previously uploaded logo back. The `{filename}` segment is the trailing component of the persisted `object_key`. |

Request shape for the upload:

- `Content-Type: multipart/form-data` with a single `file` field.
- Accepted content types: `image/jpeg`, `image/png`.
- Accepted file extensions: `.jpg`, `.jpeg`, `.png`. The extension and
  the content-type must agree (a `.jpg` with content-type
  `image/png` is rejected with 422 to defeat trivial mime spoofing).
- Maximum payload size: **5 MB**. Larger uploads return 413 with
  code `BRAND_LOGO_UPLOAD_TOO_LARGE`.

Success response (200):

```json
{
  "object_key": "agencies/<safe_agency>/logo-<sha1-12><ext>",
  "url": "/v1/admin/agencies/{agency_id}/brand/logo/file/logo-<sha1-12><ext>"
}
```

The admin client then patches the brand row with:

```http
PUT /v1/admin/agencies/{agency_id}/brand
Content-Type: application/json

{ "logo_object_key": "agencies/<safe_agency>/logo-<sha1-12>.png" }
```

Error reference for the upload endpoint:

| Status | `code` | Meaning |
|---|---|---|
| 200 | — | Logo persisted. Response carries `object_key` + `url`. |
| 401 / 403 | (auth) | Missing or invalid admin bearer / agency JWT. |
| 404 | `ADMIN_AGENCY_NOT_FOUND` | Path agency does not exist. |
| 413 | `BRAND_LOGO_UPLOAD_TOO_LARGE` | Payload exceeded 5 MB. |
| 415 | `BRAND_LOGO_UPLOAD_UNSUPPORTED_TYPE` | Content-type was not `image/jpeg` or `image/png` (or the request was not `multipart/form-data`). |
| 422 | `BRAND_LOGO_UPLOAD_UNSUPPORTED_EXTENSION` | Filename extension is not `.jpg`/`.jpeg`/`.png`. |
| 422 | `BRAND_LOGO_UPLOAD_TYPE_EXTENSION_MISMATCH` | Content-type and filename extension disagree. |
| 422 | `BRAND_LOGO_UPLOAD_MALFORMED` | The body could not be parsed as `multipart/form-data`. |
| 422 | `BRAND_LOGO_UPLOAD_MISSING_FIELD` | The `file` multipart field was not present. |
| 422 | `BRAND_LOGO_UPLOAD_EMPTY` | The uploaded file body was empty. |
| 500 | `BRAND_LOGO_UPLOAD_WRITE_FAILED` | Server could not write the logo to disk. |

**Deletion contract.** The brand columns
`logo_object_key` and `intro_logo_object_key` are `TEXT NOT NULL
DEFAULT ''`. To remove an attached logo, the admin sends the empty
string explicitly:

```json
{ "logo_object_key": "" }
```

`null` is **not** a delete operator: the brand PUT treats omitted
fields and JSON `null` values identically as "preserve the previously
stored value", so the only way to clear the attachment is the
empty-string sentinel.

**Rendering preference.** When `logo_object_key` resolves to a real
file on disk, the reel renderer uses that logo over the WordPress
webhook `agency_logo` URL (see
`modules/rendering/infrastructure/runtime/branding.py:prepare_cover_logo_image`).
If `logo_object_key` is empty, missing, or points to a deleted file the
renderer falls back to the webhook URL as before.

### Social template variables

Each `description_template` value in `PUT /admin/agencies/{id}/social-templates`
may reference any of the variables below using the `{{variable_name}}` syntax.
Whitespace inside the braces is tolerated (`{{ property_title }}` matches the
same key as `{{property_title}}`); names are case-insensitive and matched
against the lowercased catalog. Unknown variables are rejected with
`422 SOCIAL_TEMPLATE_UNKNOWN_VARIABLE`; the error body lists the offending
keys per platform and the full allowed catalog.

| Variable | Source on the `Property` ingested from the WordPress webhook |
|---|---|
| `property_title` | `property_item.title` |
| `price` | `property_item.price` |
| `bedrooms` | `property_item.bedrooms` (rendered as integer, empty string when null) |
| `bathrooms` | `property_item.bathrooms` (rendered as integer, empty string when null) |
| `size_m2` | `property_item.property_size` |
| `property_type` | `property_item.property_type_label` |
| `city` | `property_item.property_county_label` |
| `neighborhood` | `property_item.property_area_label` |
| `neighborhood_tag` | `property_item.property_area_label`, lowercased and stripped of spaces (intended for hashtag use) |
| `eircode` | `property_item.eircode` (Irish postcode) |
| `short_description` | `property_item.excerpt_html` (stripped) |
| `agent_name` | `property_item.agent_name` |
| `agent_phone` | `property_item.agent_mobile`, falling back to `property_item.agent_number` |
| `agent_email` | `property_item.agent_email` |
| `booking_link` | the resolved property URL |
| `property_url` | same as `booking_link` (alias kept for template ergonomics) |

The authoritative list lives in
`modules.configuration.domain.social_templates_variables.ALLOWED_TEMPLATE_VARIABLES`;
the runtime substitution table that produces the rendered caption is
`modules.reels.application.content_generator._build_property_template_variables`.
A unit test pins both in lockstep so the validator never drifts from the
pipeline.

Stray braces that do not form a complete `{{name}}` token (for example
`{{ }}`, `{{`, `}}`, or `{{ has space inside }}`) are treated as literal
text by both the validator and the substitution engine. Plain captions
without any placeholder remain accepted.

Error code reference for this endpoint:

| Status | `code` | Meaning |
|---|---|---|
| 200 | — | Block saved; response carries the persisted `templates` map. |
| 404 | `ADMIN_AGENCY_NOT_FOUND` | Path agency does not exist. |
| 422 | `SOCIAL_TEMPLATE_UNKNOWN_VARIABLE` | At least one template references a variable outside the catalog. The body's `details.unknown_variables_by_platform` lists the offending keys per platform and `details.allowed_variables` lists every accepted name. |
| 500 | `SOCIAL_TEMPLATES_SAVE_FAILED` | Persistence layer failure. |

## 4. Read-only content endpoints

These power the agency-facing dashboard. They are read-only and do not modify
any state.

| Endpoint | Returns |
|---|---|
| `GET /admin/agencies/{id}/reels` | recent property reels (`properties` ⨝ `property_pipeline_state` ⨝ latest `media_revisions`) |
| `GET /admin/agencies/{id}/social-accounts` | the GHL location's connected social accounts (Instagram, TikTok, Pinterest, …); falls back to `connected: false` if the agency has no GHL connection |

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

### Reel approval and publish status

The reel workflow exposes two transition endpoints under the admin surface:

| Verb | Path | Effect |
|---|---|---|
| `POST` | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/approve` | Marks the reel `approved` / `pending_publish` and enqueues a fresh `reel_publish` job. **Idempotent**: see below. |
| `POST` | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/reject` | Marks the reel `rejected` so it stays out of the publish queue. |

`POST /approve` is idempotent against rapid double-clicks and concurrent
requests. Before enqueuing a new job, the use case looks up any active
`reel_publish` job (`status IN ('queued', 'processing')`) for the same
property. If one exists, the handler returns `200 OK` with the existing
`job_id` / `event_id` and an extra `"idempotent_replay": true` flag,
without enqueuing a duplicate. Clients can read this flag if they want to
distinguish the two cases, but it is safe to ignore — the response shape
is otherwise identical to a fresh approve.

Response shape:

```json
{
  "status": "approved",
  "publish_enqueued": true,
  "reel": { "...": "..." },
  "event_id": "<uuid>",
  "job_id": "<uuid>",
  "idempotent_replay": true,
  "scheduled_at": "2026-05-18T09:00:00+00:00"
}
```

When the agency or the original WordPress payload is missing,
`publish_enqueued` is `false` and the body carries `reason` + `hint`
instead of `event_id` / `job_id`. The HTTP status stays `200` so the
frontend can render a consistent state.

#### `scheduled_at` (feature 11)

`scheduled_at` is always present in the response when `publish_enqueued`
is `true`, and is either:

* a string formatted as ISO 8601 UTC (e.g. `2026-05-18T09:00:00+00:00`)
  giving the next valid slot inside the agency's recurring publish window
  (`agency_automation_rules.publish_window_start` /
  `publish_window_end` / `publish_days`), **or**
* `null` when the request was made inside the configured window (or no
  window is configured — empty `publish_window_start` / empty
  `publish_days` / no `agency_automation_rules` row), meaning "publish
  immediately".

The slot is computed in the approve use case
(`compute_next_publish_slot(rules, now_utc)`), persisted into the job's
`publish_context_json` so an `idempotent_replay` returns the original
slot rather than recomputing, and threaded through the publishing
pipeline to GoHighLevel.

In the request that the worker eventually fires against GHL
(`POST /social-media-posting/{locationId}/posts`), `scheduled_at`
becomes:

* `json_body["scheduleDate"] = "<scheduled_at>"` and
  `json_body["status"] = "scheduled"` when `scheduled_at` is non-null —
  GHL keeps the post in `scheduled` state until that UTC instant.
* `json_body["status"] = "published"` and no `scheduleDate` key when
  `scheduled_at` is null — GHL publishes immediately, preserving the
  pre-feature-11 contract.

`quiet_hours_enabled`, `skip_weekends` and `hold_window_seconds` are
persisted columns on `agency_automation_rules` and fields on the
`AutomationRules` dataclass (feature 13).

#### `scheduled_at` (feature 14 — timezone + hold/quiet/skip)

Feature 14 extends `compute_next_publish_slot` with an
``agency_timezone`` kwarg and the three feature-13 toggles. The pure
function now applies (in order):

1. **Hold window** — adds `rules.hold_window_seconds` (clamped to
   `[0, 86_400]`) to `now_utc` and uses the result as the target.
2. **Timezone resolution** — `agency.timezone` (loaded from the
   `agencies` table) is parsed as an IANA string via
   `zoneinfo.ZoneInfo`. Any failure (invalid string, missing tzdata)
   falls back to UTC and emits a WARNING in `warnings-errors.log` so
   the approve flow never crashes on a bad value.
3. **`skip_weekends`** — if enabled and the target lands on Sat/Sun in
   agency local time, advance to the next day in `publish_days` at
   `publish_window_start` (Monday by default).
4. **`quiet_hours_enabled`** — if enabled and the target lands outside
   `[publish_window_start, publish_window_end]` (supports wrap-around
   windows like `22:00 → 07:00`), advance to the next allowed
   `publish_window_start` respecting `publish_days`.
5. If every toggle is off and the hold is zero, return `None`
   (immediate publish — preserves the pre-feature-13 contract). If the
   shifts cancel out to `now_utc`, also return `None`.

The approve use case (`regenerate_reel`) loads
`uow.tenancy.agencies.get_by_id(agency_id)` and forwards
`agency_timezone` to `compute_next_publish_slot`. Missing agency rows
fall back to `"UTC"` defensively.

#### `scheduled_at` (feature 15 — webhook auto-publish)

Feature 15 extends the same scheduling contract to the **webhook
auto-publish branch**. Previously the WordPress webhook flow
(`IngestWordPressPropertyUseCase`) persisted the `reel_publish` job
without a `scheduled_at` and the worker fired the GHL POST with
`status:"published"` (immediate). The auto-publish branch therefore
ignored the Automation window, while the manual approve flow honoured
it — two competing contracts for the same agency.

The slot is now computed inside the worker step
(`IngestPropertyIntoReelUseCase`) rather than at webhook acceptance
time:

1. The webhook endpoint (`POST /v1/ingest/wordpress/property`) enqueues
   the job exactly as before — `jobs.publish_context_json` does **not**
   carry `scheduled_at` at this point (it is computed lazily on
   dequeue).
2. When the worker dequeues the job, the orchestrator runs
   `IngestPropertyIntoReelUseCase.execute(job, uow=uow)`. Right after
   `_resolve_publish_inputs(...)` the use case loads
   `uow.configuration.automation.get(agency_id)` plus
   `uow.tenancy.agencies.get_by_id(agency_id).timezone` and calls
   `compute_next_publish_slot(rules, datetime.now(timezone.utc),
   agency_timezone=agency_timezone)`.
3. If the slot is non-`None`, the use case
   `dataclasses.replace`s the runtime `SocialPublishContext` so its
   `scheduled_at` carries the ISO-8601 UTC instant. The downstream
   GoHighLevel publisher (`property_publisher.create_social_post`)
   reads `context.publish_context.scheduled_at` and emits the same
   `scheduleDate` + `status:"scheduled"` body as the manual approve
   flow.
4. If the slot is `None` (all Automation toggles off, no rules row, or
   shifts cancel out), the `publish_context` is left untouched and the
   worker preserves the pre-feature-15 "publish immediately" contract.

Defensive notes:

* `publish_context is None` (i.e. `social_publishing_enabled=False`
  or the job arrived without a publish context) → the helper returns
  the `None` unchanged. No `dataclasses.replace(None, ...)` crash.
* `approval_required=True` on `AutomationRules` does **not**
  short-circuit slot computation here: the slot is computed and
  stamped on the context regardless. The downstream pipeline decides
  whether to park the reel pending manual approve based on
  `publish_context.approval_required`, which is set by the
  job/webhook upstream. When the manual approve fires,
  `regenerate_reel` computes its own slot (feature 11/14) and
  overrides whatever feature 15 stamped.

### Multi-platform publish aggregation

After the worker runs a `reel_publish` job, each desired platform yields
one of these outcomes (stored in `reels.publish_details.platform_results`):

| Outcome | Counts as success? | Penalises aggregate? |
|---|---|---|
| `published` (post id returned by GHL) | yes | — |
| `failed` (real upstream error) | no | yes |
| `skipped_missing_account` (no connected account for that platform) | no | **no** |

`reels.publish_status` / `workflow_state` ends up as:

* `published` — every "effective" desired platform succeeded.
  `skipped_missing_account` platforms are excluded from "effective".
  Example: an agency with only Instagram and LinkedIn connected requests
  six platforms; the four with no account get `skipped_missing_account`,
  the two with accounts succeed → reel is `published`.
* `partial` — at least one success and at least one real failure (e.g.
  one platform's upstream API errored). The frontend renders this as a
  "Published" badge — the reel did go out.
* `failed` — zero successes among effective platforms, **or** every
  desired platform returned `skipped_missing_account` (a misconfigured
  agency with no networks linked at all).
* `skipped` — `desired_platforms` was empty.

This means an agency without Facebook or Google Business Profile linked
in GoHighLevel still gets a green reel as long as the platforms they
*do* have connected publish successfully.

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
| `Admin · Render templates` | list/select DB-backed render packs |
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
