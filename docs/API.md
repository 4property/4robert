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

Feature 29 wires `agency_brand_settings.secondary_color` to the rotated
status banner that the `side_banner` template draws. The cascade is:

1. `agency_brand_settings.secondary_color` (per-agency override) wins
   when the brand row carries a HEX value.
2. The renderer falls back to the hardcoded `#FECF4D` ribbon background
   (introduced by feature 17) when the brand row is missing the colour.

The WordPress webhook does not currently expose a "secondary" accent
field, so the cascade has two levels rather than three. The `classic`
render template does not consume `secondary_color`; the colour only
reaches the rotated ribbon under `layout_variant="side_banner"`.

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
| **Social templates** | `GET / PUT /admin/agencies/{id}/social-templates` | `agency_social_templates` | `templates` (map of platform id → caption template **or** rich object with `description_template`, `title_template`, `hashtags`) |
| **Render templates** | `GET /admin/agencies/{id}/render-templates`, `PUT /admin/agencies/{id}/render-template` | `render_templates`, `agency_reel_defaults.render_template_id` | `template_id` selection only; catalog edits are DB-only |

Notes:

- **`platforms` is owned by `/defaults`**, not `/automation`. Sending it to
  `/automation` returns 422.
- Platform identifiers currently recognized by the publisher are
  `instagram`, `tiktok`, `facebook`, `linkedin`, `youtube`, `gbp` /
  `google_business_profile` and `pinterest`.
- **Default `platforms` for new agencies** (server default of
  `agency_reel_defaults.platforms`, applied on first INSERT when the row
  is created without an explicit list):
  `["tiktok", "instagram", "linkedin", "youtube", "facebook", "gbp",
  "pinterest"]`. Migration `20260514_0001` flipped the server default
  to include `pinterest` (feature 19) and appended `pinterest` to any
  pre-existing row that did not already contain it; existing rows that
  already had `pinterest` (e.g. set via PUT `/defaults`) were left
  untouched. The downgrade reverts the server default only — it does
  not strip `pinterest` from rows that already carry it.
- **`settings` is the free-form bucket on `/defaults`** for UI knobs that
  don't have a typed column (frontend INITIAL_DEFAULTS shape: currency,
  language, aspect, resolution, fps, subFont, subSize, etc., plus any
  namespaced keys like `automation.quietHoursEnabled` the frontend chooses
  to persist there). It is merged shallow with the previously stored object.
- **`settings.music.selection_rules` is a typed sub-document** (feature 24).
  Today it carries a single boolean:
  - `fallback_to_full_library` (default `true`): if the agency default
    music pool is empty (no track marked `is_default=true`), the
    renderer falls back to the full per-agency library. When set to
    `false` the renderer raises `MUSIC_NO_DEFAULT_TRACKS` instead so
    the reel fails loudly. The flag only branches the "no default
    tracks" path — when at least one default exists the renderer
    always uses the default pool regardless of the flag.

  The block is validated by `SettingsMusicPayload`/
  `SettingsMusicSelectionRulesPayload` with `extra="forbid"`: unknown
  keys under `settings.music.*` or
  `settings.music.selection_rules.*` are rejected with 422. The
  default value is **not** persisted on PUT — the JSONB column keeps
  the absence verbatim. The GET response, however, fills it in so the
  frontend Toggle starts with a defined value. Shape (PUT and GET):

  ```json
  {
    "settings": {
      "music": {
        "selection_rules": {
          "fallback_to_full_library": true
        }
      }
    }
  }
  ```
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
- **`font_family` is validated against the catalogue** (feature 28). The
  payload must match one of the canonical names listed by
  `GET /v1/admin/fonts` exactly (case-sensitive). Unknown values are
  rejected with `422`; the validator error message starts with
  `UNKNOWN_FONT_FAMILY:` and includes the full list of allowed
  families. Sending `null` clears the override (the renderer falls back
  to Inter); sending an empty string is equivalent to `null`.

#### Font catalogue (feature 28)

```
GET /v1/admin/fonts
```

Admin-scope read-only endpoint that surfaces the catalogue of fonts
shipped with the backend. The frontend `/brand` dropdown should
populate from this endpoint so the selector and the `PUT /brand`
validator stay in lockstep. No per-agency scoping (the catalogue is
global).

Response shape:

```json
{
  "items": [
    {"family": "Inter", "display_name": "Inter", "available": true},
    {"family": "Manrope", "display_name": "Manrope", "available": true},
    {"family": "Plus Jakarta Sans", "display_name": "Plus Jakarta Sans", "available": true},
    {"family": "Montserrat", "display_name": "Montserrat", "available": true},
    {"family": "Poppins", "display_name": "Poppins", "available": true},
    {"family": "Roboto", "display_name": "Roboto", "available": true}
  ],
  "count": 6
}
```

`available` is `false` when the underlying TTF file is missing on
disk — useful to diagnose a broken deploy without reading worker logs.
The `family` value is the exact string `PUT /brand` expects on
`font_family`.

**Render-time wiring.** When a reel is ingested,
`IngestPropertyIntoReelUseCase` resolves the agency
`BrandSettings.font_family` against this catalogue and stamps the
regular + bold TTF paths onto the render template overrides
(`render_template_reel_settings.font_path` /
`render_template_reel_settings.bold_font_path`, same for the poster).
A legacy persisted family that left the catalogue falls back to Inter
with a warning instead of crashing the render.

#### Brand secondary colour and the side_banner ribbon (feature 29)

`agency_brand_settings.secondary_color` was historically write-only: the
UI persisted it from feature 6 but no renderer consumed the value.
Feature 29 wires the field to the rotated status banner emitted by the
`side_banner` render template. The ingest helper
`_resolve_brand_secondary_color` stashes the HEX value on
`render_template_reel_settings.side_banner_ribbon_background_color` (a
renderer-internal key, filtered out by
`normalize_property_reel_template_overrides`), and
`DefaultMediaRenderer._build_render_data` propagates it onto
`PropertyRenderData.side_banner_ribbon_background_color` so
`preparation.prepare_reel_render_assets` can render the ribbon with the
agency colour. When the brand row carries no override, the renderer
falls back to the hardcoded `#FECF4D` ribbon background (introduced by
feature 17). The `classic` render template does not build the rotated
banner, so the secondary colour has no visual effect there.

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

Each `description_template` and `title_template` value in
`PUT /admin/agencies/{id}/social-templates` may reference any of the
variables below using the `{{variable_name}}` syntax. Whitespace inside the
braces is tolerated (`{{ property_title }}` matches the same key as
`{{property_title}}`); names are case-insensitive and matched against the
lowercased catalog. Unknown variables are rejected with
`422 SOCIAL_TEMPLATE_UNKNOWN_VARIABLE`; the error body lists the offending
keys per platform (and per field, when `title_template` is involved) and
the full allowed catalog.

#### Payload union — legacy string vs rich object (feature 20)

The PUT body keeps backward-compat with admin clients pinned to the v1
contract that posted a plain caption string per platform. A new rich object
form is accepted alongside it; clients may mix both forms in the same
request body during the rollout.

```jsonc
// Legacy shape (still accepted):
{
  "templates": {
    "instagram": "Visit {{property_title}} in {{city}}"
  }
}

// Rich shape:
{
  "templates": {
    "pinterest": {
      "description_template": "See {{property_title}} in {{city}}",
      "title_template": "{{property_title}} · {{price}}",
      "hashtags": ["#realestate", "#dublin"]
    }
  }
}
```

A plain string is interpreted exactly as
`{description_template: "<string>", title_template: "", hashtags: []}` by
the server, and the GET response of the following call exposes the three
fields on each row of `items[]`.

**`title_template`** is forwarded to networks with a dedicated title slot
(Pinterest, YouTube). Networks that ignore the title (Instagram, TikTok,
Facebook, LinkedIn, GBP) silently drop it.

**`hashtags`** is a list of strings (max **30** per platform). Each entry
must match the regex `^#[\w-]{1,50}$`. At publish time the worker appends
the joined hashtags to the rendered description with a `\n\n` separator:

```
<rendered description>

#tag1 #tag2 #tag3
```

Invalid hashtags or lists that exceed 30 entries are rejected with
`422 SOCIAL_TEMPLATE_INVALID_HASHTAG` before the row is persisted.

**`templates` in the GET response** is kept as a flat
`{ platform: description }` map for backward-compat with admin clients that
only consume the description. Frontend feature 20 reads
`title_template`/`hashtags` from `items[]` instead.

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
| 200 | — | Block saved; response carries the persisted `templates` map and full `items[]`. |
| 404 | `ADMIN_AGENCY_NOT_FOUND` | Path agency does not exist. |
| 422 | `SOCIAL_TEMPLATE_UNKNOWN_VARIABLE` | At least one `description_template` or `title_template` references a variable outside the catalog. `details.unknown_variables_by_platform` keys offending platforms. When only the description carries unknown variables the value is a flat `["var", ...]` list (legacy shape). When `title_template` is involved the value becomes a nested `{description_template: [...], title_template: [...]}` mapping so the admin UI can render the error next to the right field. `details.allowed_variables` lists every accepted name. |
| 422 | `SOCIAL_TEMPLATE_INVALID_HASHTAG` | At least one platform declared a hashtag that does not match `^#[\w-]{1,50}$`, or its hashtag list exceeded 30 entries. `details.hashtag_errors_by_platform` is keyed by platform; `invalid: [...]` lists the offending hashtag values and `count`/`max` report a too-long list. |
| 500 | `SOCIAL_TEMPLATES_SAVE_FAILED` | Persistence layer failure. |

## 4. Read-only content endpoints

These power the agency-facing dashboard. They are read-only and do not modify
any state.

| Endpoint | Returns |
|---|---|
| `GET /admin/agencies/{id}/reels` | recent property reels (`properties` ⨝ `property_pipeline_state` ⨝ latest `media_revisions`); paginated + filterable since feature 32 — see below |
| `GET /admin/agencies/{id}/social-accounts` | the GHL location's connected social accounts (Instagram, TikTok, Pinterest, …); falls back to `connected: false` if the agency has no GHL connection |

#### `GET /reels` — pagination and filters (feature 32)

```http
GET /v1/admin/agencies/{agency_id}/reels
    ?page=1
    &page_size=25
    &workflow_state=needs_approval,approved
    &publish_status=pending_publish
    &q=cranford
```

| Query param | Type | Default | Notes |
|---|---|---|---|
| `page` | integer | `1` | Clamped to `>=1`. `0` and negatives collapse to `1`. |
| `page_size` | integer | `25` | Clamped to `[1, 100]`. `500` collapses to `100`. |
| `workflow_state` | CSV | — | Filters `reels.workflow_state`. Unknown values → **422 `INVALID_FILTER_VALUE`**. |
| `publish_status` | CSV | — | Filters `reels.publish_status`. Unknown values → **422 `INVALID_FILTER_VALUE`**. |
| `q` | string | — | Trimmed; empty / whitespace-only collapses to no filter. `ILIKE %q%` over `reels.title`, `reels.slug` and the related `properties.list_reference` (the property reference). |
| `limit` | integer | — | **Legacy.** If `page` is absent, `limit` is interpreted as `page_size` with `page=1`. If `page_size` is also present, `page_size` wins and `limit` is ignored. |

Response (200):

```json
{
  "items": [ /* AgencyReelItemPayload, see below */ ],
  "count": 25,
  "count_total": 137,
  "page": 1,
  "page_size": 25,
  "has_more": true
}
```

- `count` is preserved as an alias of `len(items)` so legacy consumers
  keep working.
- `count_total` reflects the **same WHERE** as the items query (filters
  applied).
- `has_more = page * page_size < count_total`.

### Music library

The agency music library is real CRUD, not the old dashboard stub. Clients use
the versioned admin surface:

| Verb | Path | Response |
|---|---|---|
| `POST` | `/v1/admin/agencies/{id}/music/upload` | `201 { status, agency_id, music_track }` |
| `GET` | `/v1/admin/agencies/{id}/music` | `200 { agency_id, items, count }` |
| `GET` | `/v1/admin/agencies/{id}/music/{music_id}` | `200 { agency_id, music_track }` |
| `GET` | `/v1/admin/agencies/{id}/music/{music_id}/file/{filename}` | `200` audio stream |
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

#### Upload (feature 22)

`POST /v1/admin/agencies/{id}/music/upload` accepts a multipart body with:

- `file` (binary) — the audio asset. Supported MIME types: `audio/mpeg`,
  `audio/mp4`, `audio/wav` (alias `audio/x-wav`). Max size **20 MB**.
- `display_name` (text, 1..200 chars) — required, label shown in the music
  picker.
- `is_default` (text, `true`/`false`) — optional, defaults to `false`.

The backend persists the binary under
`workspace/generated_media/_agency_music/{safe_agency_id}/` (the path is
resolved by `shared.storage.site_layout.resolve_agency_music_destination` so
a future S3 backend can drop in without changing this HTTP contract),
derives `object_key`, probes `duration_seconds` via `ffprobe` and registers
the row. Response:

```json
{
  "status": "created",
  "agency_id": "<uuid>",
  "music_track": { /* same shape as above, includes agency_id */ }
}
```

Error codes:

- `MUSIC_TRACK_AUDIO_INVALID` (400) — unsupported MIME, magic-byte mismatch,
  ffprobe failure, zero duration, or `duration_seconds > 600`.
- `MUSIC_TRACK_UPLOAD_TOO_LARGE` (413) — payload > 20 MB.
- `MUSIC_TRACK_UPLOAD_UNSUPPORTED_TYPE` (415) — request is not
  `multipart/form-data`.
- `MUSIC_TRACK_UPLOAD_MALFORMED` (422) — multipart body cannot be parsed.
- `MUSIC_TRACK_DISPLAY_NAME_REQUIRED` (422) — `display_name` missing/blank.
- `MUSIC_TRACK_DISPLAY_NAME_TOO_LONG` (422) — `display_name` > 200 chars.
- `MUSIC_TRACK_UPLOAD_EMPTY` (422) — zero-byte file.
- `ADMIN_AGENCY_NOT_FOUND` (404) — unknown `agency_id`.

#### Stream (feature 22)

`GET /v1/admin/agencies/{id}/music/{music_id}/file/{filename}` streams the
binary registered for `music_id`. `filename` must match the trailing
segment of the track's `object_key` (returned by the upload endpoint).
Cross-agency requests respond 404 (`MUSIC_TRACK_NOT_FOUND`). Filename
mismatch responds 404 (`MUSIC_TRACK_FILE_NOT_FOUND`).

#### Reconfigure / decommission

`PUT /v1/admin/agencies/{id}/music/{music_id}` only accepts `display_name`
(1..200 chars) and `is_default` (bool). `object_key` is owned by the upload
endpoint and `duration_seconds` is derived from `ffprobe`, so the PATCH
payload rejects both with 422 (`extra='forbid'`). Relevant error codes:
`MUSIC_TRACK_SAVE_FAILED`, `MUSIC_TRACK_NOT_FOUND`,
`MUSIC_TRACK_DISPLAY_NAME_REQUIRED`, `ADMIN_AGENCY_NOT_FOUND`.

#### Retired endpoints

- `POST /v1/admin/agencies/{id}/music` (direct metadata POST) returns 405
  (`METHOD_NOT_ALLOWED`) — feature 22 replaced it with the multipart upload
  above.
- The legacy `/v1/admin/agencies/{id}/music-tracks` stub is not exposed by
  the backend.

### Outro video (feature 33)

The admin UI uploads the agency's outro clip through a dedicated multipart
endpoint. The outro is appended to every rendered reel when
`agency_reel_defaults.outro_enabled = true` AND the agency has an
`outro_source = "uploaded"` asset. The asset row lives in
`agency_intro_outro_assets` (migration `20260515_0002`), keyed by
`(agency_id, kind="outro")`.

| Verb | Path | Purpose |
|---|---|---|
| `POST` | `/v1/admin/agencies/{agency_id}/outro/upload` | Upload a fresh MP4/MOV outro and replace the previously stored asset (if any). |
| `GET`  | `/v1/admin/agencies/{agency_id}/outro/file` | Stream the binary back to the editor for preview. |
| `DELETE` | `/v1/admin/agencies/{agency_id}/outro` | Reset `outro_source='none'`, clear `object_key`, remove the on-disk blob. Idempotent. |

#### Upload contract

`POST /v1/admin/agencies/{agency_id}/outro/upload` accepts a multipart body
with a single `file` field:

- **Accepted MIME types**: `video/mp4`, `video/quicktime`. The endpoint
  also accepts the common alias `video/x-quicktime` for `.mov`. Anything
  else returns **422 `OUTRO_INVALID_MIME`**.
- **Maximum payload size**: **unrestricted**. The 50 MB cap was removed
  so the SaaS admin can upload outros of any weight. Empty bodies still
  return **422 `OUTRO_FILE_EMPTY`**.
- **Duration window**: **unrestricted**. The `[1, 10]` s window was
  removed; `ffprobe` is still invoked to derive
  `outro_duration_seconds` for the response and for downstream
  rendering, but the duration is no longer validated against a range.

Successful response (200):

```json
{
  "outro_object_key": "agencies/<safe_agency>/outro/<sha1-12>.mp4",
  "outro_duration_seconds": 6,
  "outro_source": "uploaded"
}
```

`outro_duration_seconds` is the integer floor of the probed duration.
The asset is persisted at
`workspace/generated_media/_agency_outro/{safe_agency_id}/<sha1-12><ext>`
(the path is resolved by
`shared.storage.site_layout.resolve_agency_intro_outro_destination` so a
future S3 backend can drop in without changing this HTTP contract; the
`object_key` shape stays `agencies/{safe_agency}/outro/{filename}`).

#### Stream contract

`GET /v1/admin/agencies/{agency_id}/outro/file` streams the bytes back
with `Content-Disposition: inline` and `Cache-Control: private, max-age=600`.
Returns **404 `OUTRO_FILE_NOT_FOUND`** when no outro is configured or
when the on-disk blob has been removed out-of-band.

#### Delete contract

`DELETE /v1/admin/agencies/{agency_id}/outro` resets the asset row to
`outro_source='none'` (clears `object_key`) and removes the on-disk blob.
It is idempotent: a DELETE without a prior upload returns the same
200 payload with `outro_source: "none"`.

Error reference (upload):

| Status | `code` | Meaning |
|---|---|---|
| 200 | — | Outro persisted. Response carries the three `outro_*` fields. |
| 401 / 403 | (auth) | Missing or invalid admin bearer / agency JWT. |
| 404 | `ADMIN_AGENCY_NOT_FOUND` | Path agency does not exist. |
| 415 | `OUTRO_UPLOAD_UNSUPPORTED_TYPE` | Request was not `multipart/form-data`. |
| 422 | `OUTRO_INVALID_MIME` | `file` content-type was not `video/mp4` or `video/quicktime`. |
| 422 | `OUTRO_FILE_EMPTY` | `file` multipart field carried zero bytes. |
| 422 | `OUTRO_UPLOAD_MALFORMED` | Body could not be parsed as `multipart/form-data`. |
| 422 | `OUTRO_UPLOAD_MISSING_FIELD` | `file` multipart field absent. |

#### Surfaced in `GET /defaults`

`GET /v1/admin/agencies/{agency_id}/defaults` now includes the four
`outro_*` fields so the frontend can render the Defaults tab without a
second round trip:

```json
{
  "outro_enabled": true,
  "outro_object_key": "agencies/<safe_agency>/outro/<sha1-12>.mp4",
  "outro_duration_seconds": 6,
  "outro_source": "uploaded"
}
```

When the agency has never uploaded an outro the three asset fields are
`null` / `"none"` and `outro_enabled` reflects the persisted toggle.
`outro_enabled` is also writable through `PUT /defaults` (the
upload/delete endpoints only own the asset; the on/off toggle stays in
`agency_reel_defaults`).

### Intro video (feature 34)

Symmetric to the outro endpoints (feature 33). The intro row shares the
`agency_intro_outro_assets` table with the outro, discriminated by
`kind`. The unique constraint `(agency_id, kind)` (migration
`20260515_0002`) means each agency can have at most one intro and one
outro at any time.

| Verb | Path | Purpose |
|---|---|---|
| `POST` | `/v1/admin/agencies/{agency_id}/intro/upload` | Upload a fresh MP4/MOV intro and replace the previously stored asset (if any). |
| `GET`  | `/v1/admin/agencies/{agency_id}/intro/file` | Stream the binary back to the editor for preview. |
| `DELETE` | `/v1/admin/agencies/{agency_id}/intro` | Reset `intro_source='none'`, clear `object_key`, remove the on-disk blob. Idempotent. |

#### Upload contract

`POST /v1/admin/agencies/{agency_id}/intro/upload` accepts a multipart
body with a single `file` field:

- **Accepted MIME types**: `video/mp4`, `video/quicktime`. Anything else
  returns **422 `INTRO_INVALID_MIME`**.
- **Maximum payload size**: **unrestricted**. The 50 MB cap was removed
  so the SaaS admin can upload intros of any weight. Empty bodies still
  return **422 `INTRO_FILE_EMPTY`**.
- **Duration window**: **unrestricted**. The `[1, 10]` s window was
  removed; `ffprobe` is still invoked to derive
  `intro_duration_seconds` for the response and for downstream
  rendering, but the duration is no longer validated against a range.

Successful response (200):

```json
{
  "intro_object_key": "agencies/<safe_agency>/intro/<sha1-12>.mp4",
  "intro_duration_seconds": 5,
  "intro_source": "uploaded"
}
```

The asset is persisted at
`workspace/generated_media/_agency_intro/{safe_agency_id}/<sha1-12><ext>`;
`object_key` is shaped `agencies/{safe_agency}/intro/{filename}`. The
disk layout helper is the same
`resolve_agency_intro_outro_destination` used by the outro path, with
`kind="intro"` as the discriminator.

Error reference (upload) mirrors the outro table — codes start with
`INTRO_` instead of `OUTRO_`:

| Status | `code` |
|---|---|
| 404 | `ADMIN_AGENCY_NOT_FOUND` |
| 415 | `INTRO_UPLOAD_UNSUPPORTED_TYPE` |
| 422 | `INTRO_INVALID_MIME` |
| 422 | `INTRO_FILE_EMPTY` |
| 422 | `INTRO_UPLOAD_MALFORMED` |
| 422 | `INTRO_UPLOAD_MISSING_FIELD` |

#### Surfaced in `GET /defaults`

`GET /v1/admin/agencies/{agency_id}/defaults` likewise carries the four
`intro_*` fields:

```json
{
  "intro_enabled": true,
  "intro_object_key": "agencies/<safe_agency>/intro/<sha1-12>.mp4",
  "intro_duration_seconds": 5,
  "intro_source": "uploaded"
}
```

`intro_enabled` is writable through `PUT /defaults`; the asset itself
is owned by the upload/delete endpoints above.

### Reel approval and publish status

The reel workflow exposes the following transition endpoints under the admin surface:

| Verb | Path | Effect |
|---|---|---|
| `POST` | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/approve` | Marks the reel `approved` / `pending_publish` and enqueues a fresh `reel_publish` job. **Idempotent**: see below. |
| `POST` | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/reject` | Marks the reel `rejected` so it stays out of the publish queue. |
| `POST` | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/regenerate` | **(feature 40)** Re-render the reel from its current configuration + overrides without touching `workflow_state` or `publish_status`. See the dedicated `POST .../regenerate` section below. |
| `PATCH` | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/descriptions` | **(feature 21)** Overrides the rendered captions for one or more platforms before publish. Persists into `reels.descriptions_override` JSONB. |
| `PATCH` | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/music` | **(feature 25)** Overrides the background music for one reel and re-enqueues a render job. Persists into `reels.music_id` FK. `music_id=null` clears the override and the next render falls back to the agency pool. |
| `PATCH` | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/photos` | **(feature 35)** Overrides the photo order / selection for one reel and re-enqueues a render job. Persists into `reels.photos_override` JSONB. `photos=null` (or `[]`) clears the override. |
| `PATCH` | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/subtitles` | **(feature 36)** Overrides the on-screen subtitles for one reel and re-enqueues a render job. Persists into `reels.subtitles_override` JSONB. `cues=null` (or `[]`) clears the override and the renderer falls back to the autoCaptions flow. |
| `PATCH` | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/slides` | **(feature 37)** Overrides the slide manifest for one reel and re-enqueues a render job. Persists into `reels.manifest_override` JSONB. `slides=null` (or `[]`) clears the override and the renderer falls back to the auto-generated manifest. |

#### `POST .../regenerate` (feature 40)

The editor's "Render again" button. Re-enqueues a fresh `reel_publish`
job from the reel's currently stored configuration + overrides
(`photos_override` / `subtitles_override` / `manifest_override` /
`descriptions_override` / `music_id`) **without** mutating
`workflow_state` or `publish_status`. It is the sibling of
`POST .../approve`; both share the use case
`RegenerateReelUseCase` and differ only by the `mode` flag the router
passes to it:

| Endpoint | `mode` | Effect on workflow |
|---|---|---|
| `POST .../approve` | `approve_and_regenerate` (implicit) | Moves the reel to `workflow_state='approved'` / `publish_status='pending_publish'` **and** enqueues a fresh render. |
| `POST .../regenerate` | `manual_only` | Leaves `workflow_state` / `publish_status` untouched. Only enqueues a fresh render job (the editor stays in its current state). |

```http
POST /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/regenerate
Content-Type: application/json

{ "reason": "swapped intro music" }
```

The body is **optional**. `{}` or no body are both accepted. When
present, the body must satisfy `ReelManualRegeneratePayload`
(`extra="forbid"`):

- `reason` (string, ≤500 chars, optional) — free-text justification.
  When set, it is persisted on the new job's
  `publish_context_json.manual_reason` for traceability. Bodies that
  exceed 500 characters or carry unknown keys return **422
  `INVALID_REGENERATE_PAYLOAD`**.

Successful response (200, render queued):

```json
{
  "render_status": "pending",
  "job_id": "<uuid>",
  "queued_at": "2026-05-15T10:42:18Z"
}
```

When publish prerequisites are missing (no GHL connection or no
WordPress payload), the response stays 200 with the same `render_status`
but `job_id` / `queued_at` are `null` and the body carries a
`reason` / `hint` pair — mirroring the `POST /approve` shape so the
frontend can render a consistent "saved but not queued" state:

```json
{
  "render_status": "pending",
  "job_id": null,
  "queued_at": null,
  "publish_enqueued": false,
  "reason": "GHL_CONNECTION_NOT_FOUND",
  "hint": "Connect a GoHighLevel location before regenerating."
}
```

Error contract:

| Status | Code | When |
|---|---|---|
| 404 | `ADMIN_AGENCY_NOT_FOUND` | The agency does not exist. |
| 404 | `ADMIN_REEL_NOT_FOUND` | No reel row matches `(site_id, source_property_id)` for this agency. |
| 409 | `REGENERATE_PUBLISHED_FORBIDDEN` | The reel is already `publish_status='published'`. The editor must reject + re-approve from scratch instead of re-rendering on top of a live publish. |
| 409 | `REGENERATE_ALREADY_IN_FLIGHT` | A `reel_publish` job for the same `(external_source_id, source_property_id)` is still `queued` or `processing`. The editor must wait for the running render to drain instead of stacking another one. |
| 422 | `INVALID_REGENERATE_PAYLOAD` | Body is not valid JSON, has unknown keys (`extra='forbid'`), or `reason` exceeds 500 chars. |

#### `PATCH .../descriptions` (feature 21)

Replace-semantics: the client always submits the full
`descriptions_by_platform` map. The override is written wholesale into
`reels.descriptions_override` (a JSONB column added by migration
`20260514_0003_reels_descriptions_override`). On the next render+publish
pass, the worker's `IngestPropertyIntoReelUseCase` merges the override on
top of the auto-generated captions before they flow into the
`PropertyContext` consumed by `PublishReelUseCase`. Per-platform
`null`/empty values are ignored defensively so a partial edit cannot
silently wipe out untouched platforms; an empty object (`{}`) clears the
override back to the templated captions.

```http
PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/descriptions
Content-Type: application/json

{
  "descriptions_by_platform": {
    "instagram": "Custom IG copy with emojis ✨",
    "linkedin": "Professional LinkedIn caption."
  }
}
```

Response (200):

```json
{
  "status": "updated",
  "descriptions_by_platform": {
    "instagram": "Custom IG copy with emojis ✨",
    "linkedin": "Professional LinkedIn caption."
  }
}
```

Error contract:

| Status | Code | When |
|---|---|---|
| 404 | `ADMIN_AGENCY_NOT_FOUND` | The agency does not exist. |
| 404 | `ADMIN_REEL_NOT_FOUND` | No reel row matches `(site_id, source_property_id)` for this agency. |
| 409 | `REEL_NOT_EDITABLE` | The reel has already cleared the review gate (`publish_status` outside `{pending, pending_review, needs-approval, ''}`). |
| 422 | `PLATFORM_NOT_ENABLED` | One or more platform keys are not present in `agency_reel_defaults.platforms`. |

The endpoint never re-renders templates: the request body must carry the
already-materialised caption text the editor showed the user. If the
agency later edits the social template via `PUT /v1/admin/agencies/{id}/social-templates`,
reels that already carry an override keep the overridden text — the
override always wins per-platform.

#### `PATCH .../music` (feature 25)

Swap the background music for one specific reel. The override is
persisted into `reels.music_id` (a nullable FK to `agency_music_tracks`
added by migration `20260514_0006_reels_music_id_override`, with
`ON DELETE SET NULL` so the column quietly resets when the agency
deletes the picked track). The use case then re-enqueues a fresh
`reel_publish` job with `override_music_track_id` set on its
`publish_context_json`; the worker's ingest step swaps the agency music
pool for a single-element tuple containing just the override track.

```http
PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/music
Content-Type: application/json

{
  "music_id": "5a09a4f3-2b8f-4f6e-8b2b-9c5c1f6f3c4b"
}
```

Response (200, override saved and a new job enqueued):

```json
{
  "status": "saved",
  "reel_id": "ckp.ie:42",
  "music_id": "5a09a4f3-2b8f-4f6e-8b2b-9c5c1f6f3c4b",
  "publish_enqueued": true,
  "event_id": "<uuid>",
  "job_id": "<uuid>"
}
```

Response (200, override cleared — `music_id=null`):

```json
{
  "status": "saved",
  "reel_id": "ckp.ie:42",
  "music_id": null,
  "publish_enqueued": true,
  "event_id": "<uuid>",
  "job_id": "<uuid>"
}
```

When publish prerequisites are missing (no GHL connection or no
WordPress payload), the override is still persisted but the response
carries `publish_enqueued: false` and `reason`/`hint` fields — mirroring
the `POST /approve` contract so the frontend renders a consistent
state.

Error contract:

| Status | Code | When |
|---|---|---|
| 404 | `ADMIN_AGENCY_NOT_FOUND` | The agency does not exist. |
| 404 | `ADMIN_REEL_NOT_FOUND` | No reel row matches `(site_id, source_property_id)` for this agency. |
| 404 | `ADMIN_MUSIC_TRACK_NOT_FOUND` | The `music_id` is unknown OR owned by another agency (cross-tenant 404 — never leaks existence). |
| 409 | `REEL_NOT_EDITABLE` | The reel has already cleared the review gate (`publish_status` outside `{pending, pending_review, needs-approval, ''}`). |
| 422 | (pydantic) | Extra keys (`extra='forbid'`). |

Cross-tenant policy: we deliberately fold "track does not exist" and
"track belongs to a different agency" into the same `404 ADMIN_MUSIC_TRACK_NOT_FOUND`
so the response never leaks the existence of a track owned by another
tenant — consistent with the cross-agency 404 convention adopted by
feature 22 / configuration music endpoints.

Race with track deletion: if the agency deletes the override track
between the PATCH and the render, the FK's `ON DELETE SET NULL` wipes
`reels.music_id` automatically. The already-enqueued job still carries
the old `override_music_track_id` in its `publish_context_json`; the
worker's ingest step detects the missing/cross-agency track and falls
back to the resolved agency pool with a warning, instead of failing
the render.

#### `PATCH .../photos` (feature 35)

Reorder / drop the source photos for one reel before render. The
override is persisted into `reels.photos_override` (a nullable JSONB
column added by migration `20260515_0003_reels_photos_override`). The
use case re-enqueues a fresh `reel_publish` job so the worker picks
up the new order and re-renders; the renderer reads the persisted
column at ingest time (via `PropertyContext.photos_override`) so a
PATCH between enqueue and dispatch always wins over the
`publish_context` payload.

```http
PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/photos
Content-Type: application/json

{
  "photos": [
    {"position": 0, "selected": true},
    {"position": 1, "selected": false},
    {"position": 2, "selected": true}
  ]
}
```

Response (200, override saved and a new job enqueued):

```json
{
  "photos_override": [
    {"position": 0, "selected": true},
    {"position": 1, "selected": false},
    {"position": 2, "selected": true}
  ],
  "render_status": "pending",
  "publish_enqueued": true,
  "event_id": "<uuid>",
  "job_id": "<uuid>"
}
```

`photos=null` and `photos=[]` both clear the override and the next
render falls back to the default order from
`property_images`/`media_revisions`.

Validation contract:

* Positions must cover `[0, N)` exactly once, where `N` is the number
  of photos in the property's catalog.
* `selected` must be a strict boolean (no truthy strings).
* `extra='forbid'` at the body level and inside each entry.

Error contract:

| Status | Code | When |
|---|---|---|
| 404 | `ADMIN_AGENCY_NOT_FOUND` | The agency does not exist. |
| 404 | `ADMIN_REEL_NOT_FOUND` | No reel row matches `(site_id, source_property_id)` for this agency. |
| 409 | `PHOTOS_OVERRIDE_LOCKED` | The reel has already cleared the editorial gate (`workflow_state='approved'` or `publish_status='published'`). |
| 422 | `PHOTOS_OVERRIDE_LENGTH_MISMATCH` / `PHOTOS_OVERRIDE_DUPLICATE_POSITION` / `PHOTOS_OVERRIDE_POSITION_OUT_OF_RANGE` / `PHOTOS_OVERRIDE_NO_PHOTOS` | Shape violation. |

#### `PATCH .../subtitles` (feature 36)

Override the on-screen subtitles for one reel. The override is
persisted into `reels.subtitles_override` (a nullable JSONB column
added by migration `20260515_0004_reels_subtitles_override`). When
set, the renderer bypasses the autoCaptions composer entirely and
burns the cues through the same drawtext pipeline. When clear, the
renderer falls back to the historical autoCaptions flow (rendered
when `automation.autoCaptions` is enabled, nothing otherwise).

```http
PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/subtitles
Content-Type: application/json

{
  "cues": [
    {"index": 0, "text": "Welcome to this property", "in_seconds": 0.0, "out_seconds": 3.0},
    {"index": 1, "text": "Beautiful kitchen", "in_seconds": 3.0, "out_seconds": 6.0}
  ]
}
```

Response (200):

```json
{
  "subtitles_override": [
    {"index": 0, "text": "Welcome to this property", "in_seconds": 0.0, "out_seconds": 3.0},
    {"index": 1, "text": "Beautiful kitchen", "in_seconds": 3.0, "out_seconds": 6.0}
  ],
  "render_status": "pending",
  "publish_enqueued": true,
  "event_id": "<uuid>",
  "job_id": "<uuid>"
}
```

`cues=null` and `cues=[]` both clear the override.

Validation contract:

* `index` is `>= 0`, unique and monotonically increasing.
* `text` is 1-200 characters of literal caption text (no `{{ variables }}`).
* `in_seconds >= 0`, `out_seconds > in_seconds`.
* Consecutive cue windows must not overlap.
* `extra='forbid'` at the body level and inside each cue.

Error contract:

| Status | Code | When |
|---|---|---|
| 404 | `ADMIN_AGENCY_NOT_FOUND` / `ADMIN_REEL_NOT_FOUND` | Missing agency or reel. |
| 409 | `SUBTITLES_OVERRIDE_LOCKED` | Reel already approved or published. |
| 422 | `SUBTITLES_OVERRIDE_INVALID_INDEX` / `SUBTITLES_OVERRIDE_EMPTY_TEXT` / `SUBTITLES_OVERRIDE_TEXT_TOO_LONG` / `SUBTITLES_OVERRIDE_NEGATIVE_TIME` / `SUBTITLES_OVERRIDE_INVALID_WINDOW` / `SUBTITLES_OVERRIDE_NON_MONOTONIC_INDEX` / `SUBTITLES_OVERRIDE_OVERLAP` | Shape violation. |

#### `PATCH .../slides` (feature 37)

Replace the slide manifest for one reel. The override is persisted
into `reels.manifest_override` (a nullable JSONB column added by
migration `20260515_0005_reels_manifest_override`). When set, the
renderer drives the photo array from the override's `photo`-kind
entries (sorted by `position`, mapped through `photo_position`) and
the other slide kinds (`voiceover`, `text`, `intro_card`,
`outro_card`) are persisted for the FE editor preview. When clear,
the renderer falls back to the auto-generated manifest pipeline.

```http
PATCH /v1/admin/agencies/{agency_id}/reels/{site_id}/{property_id}/slides
Content-Type: application/json

{
  "slides": [
    {"slide_id": "intro-1", "position": 0, "duration_seconds": 2.0, "kind": "intro_card", "title": "Welcome"},
    {"slide_id": "photo-A", "position": 1, "duration_seconds": 3.0, "kind": "photo", "photo_position": 2},
    {"slide_id": "photo-B", "position": 2, "duration_seconds": 3.0, "kind": "photo", "photo_position": 0},
    {"slide_id": "vo-1", "position": 3, "duration_seconds": 1.5, "kind": "voiceover", "audio_url": "https://cdn.example.com/vo.mp3"},
    {"slide_id": "photo-C", "position": 4, "duration_seconds": 3.0, "kind": "photo", "photo_position": 4},
    {"slide_id": "outro-1", "position": 5, "duration_seconds": 2.0, "kind": "outro_card", "title": "Thanks", "call_to_action": "Book a viewing"}
  ]
}
```

Response (200):

```json
{
  "manifest_override": [
    {"slide_id": "intro-1", "position": 0, "duration_seconds": 2.0, "kind": "intro_card", "title": "Welcome"},
    {"slide_id": "photo-A", "position": 1, "duration_seconds": 3.0, "kind": "photo", "photo_position": 2},
    {"slide_id": "photo-B", "position": 2, "duration_seconds": 3.0, "kind": "photo", "photo_position": 0},
    {"slide_id": "vo-1", "position": 3, "duration_seconds": 1.5, "kind": "voiceover", "audio_url": "https://cdn.example.com/vo.mp3"},
    {"slide_id": "photo-C", "position": 4, "duration_seconds": 3.0, "kind": "photo", "photo_position": 4},
    {"slide_id": "outro-1", "position": 5, "duration_seconds": 2.0, "kind": "outro_card", "title": "Thanks", "call_to_action": "Book a viewing"}
  ],
  "render_status": "pending",
  "publish_enqueued": true,
  "event_id": "<uuid>",
  "job_id": "<uuid>"
}
```

`slides=null` and `slides=[]` both clear the override.

Validation contract (Pydantic discriminated union on `kind`):

* `kind` must be one of `{"photo", "voiceover", "text", "intro_card", "outro_card"}`.
* Every slide carries `slide_id` (non-empty unique string), `position`
  (covering `[0, N)` exactly once), `duration_seconds` (positive).
* Sum of `duration_seconds` ≤ `target_duration_seconds * 1.5` where
  `target_duration_seconds` is `agency_reel_defaults.duration_seconds`
  for the agency (falls back to the system default
  `REEL_TOTAL_DURATION_SECONDS` for agencies without a row).
* Per-kind required fields:
  - `photo` → `photo_position: int >= 0` (index into the property's source photo set).
  - `voiceover` → `audio_url: str` (URL or workspace-relative path).
  - `text` → `text: str` (1-500 characters, literal copy, no `{{ variables }}`).
  - `intro_card` → optional `title`, optional `subtitle`.
  - `outro_card` → optional `title`, optional `subtitle`, optional `call_to_action`.
* `extra='forbid'` at the body level and inside every slide.

Error contract:

| Status | Code | When |
|---|---|---|
| 404 | `ADMIN_AGENCY_NOT_FOUND` / `ADMIN_REEL_NOT_FOUND` | Missing agency or reel. |
| 409 | `SLIDES_OVERRIDE_LOCKED` | Reel already approved or published. |
| 422 | `SLIDES_OVERRIDE_INVALID_KIND` / `SLIDES_OVERRIDE_EMPTY_SLIDE_ID` / `SLIDES_OVERRIDE_DUPLICATE_SLIDE_ID` / `SLIDES_OVERRIDE_INVALID_POSITION` / `SLIDES_OVERRIDE_DUPLICATE_POSITION` / `SLIDES_OVERRIDE_POSITION_GAP` / `SLIDES_OVERRIDE_INVALID_DURATION` / `SLIDES_OVERRIDE_DURATION_CAP_EXCEEDED` / `SLIDES_OVERRIDE_MISSING_KIND_FIELD` / `SLIDES_OVERRIDE_INVALID_KIND_FIELD` | Shape violation. |

The override layer is editorial: today the renderer consumes the
`photo`-kind entries to drive the rendered slide images. The other
kinds (voiceover, text, intro_card, outro_card) are persisted for
the FE editor preview and a future pass that wires them into the
ffmpeg pipeline. A stale `photo_position` (e.g. one that references
a deleted source photo) is logged and skipped at render time — the
override layer never blocks a render.


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

## 7b. Notifications (internal — feature 26)

Feature 26 ships only the infrastructure for email notifications; there
is **no public HTTP surface yet**. The full review-requested flow
(outbox subscriber + worker handler + templates) arrives in feature 27.

What feature 26 adds:

* **`shared/email/`** — `EmailSender` Protocol with two concrete
  backends: `ConsoleEmailSender` (prints to stdout, default in dev /
  tests) and `SmtpEmailSender` (stdlib `smtplib` + `email.message`).
  Selected at runtime by `EMAIL_BACKEND=console|smtp`.
* **`settings.NotificationSettings`** — env-driven configuration
  loader. Reads `EMAIL_BACKEND`, `SMTP_HOST/PORT/USER/PASSWORD/USE_TLS`,
  `SMTP_FROM_ADDRESS` (default `notifications@4reels.ie`),
  `SMTP_FROM_NAME` (default `4Reels Notifications`) and
  `FRONTEND_BASE_URL` (default `http://localhost:5173`).
* **`email_notifications` table** — audit + idempotency for outbound
  email, created by migration `20260514_0007`. Columns: `id`,
  `agency_id` (FK → `agencies.id` ON DELETE CASCADE), `event_kind`,
  `site_id`, `source_property_id`, `recipient_email`, `status`
  (`queued` / `sent` / `failed` / `bounced`), `provider_message_id`,
  `error_message`, `sent_at`, `created_at`, `updated_at`. UNIQUE on
  `(agency_id, site_id, source_property_id, recipient_email,
  event_kind)` so the dispatch use case can `ON CONFLICT` upsert
  idempotently.
* **`uow.notifications.emails`** — `EmailNotificationRepository` with
  `insert_pending`, `get`, `list_by_agency`, `list_by_status`,
  `mark_sent`, `mark_failed`, and `find_recent_sent` (used by the
  feature-27 throttle to keep one send per agency+recipient per
  minute).

The rows in `email_notifications` are an internal audit trail today.
Admin / agency users cannot list or replay them via the public API;
that surface (e.g. `GET /v1/admin/agencies/{id}/notifications`) will
be considered when product needs it.

## 7c. Notifications — review_requested flow (feature 27)

Feature 27 wires the outbox event `review_requested` (emitted by
`PublishReelUseCase` when an agency requires manual approval) to the
notifications layer shipped in feature 26.

### Outbox subscriber

`apps/worker/outbox_subscriber.py` runs alongside the job dispatcher.
The poller selects pending `outbox_events` rows of type
`review_requested` using `FOR UPDATE SKIP LOCKED` so it is multi-worker
safe. Each event is handed to
`DispatchReviewRequestedEmailUseCase`, which:

1. Reads `agency_reel_defaults.settings['automation.reviewEmails']`
   for the target agency. Accepts both the canonical `list[str]` and
   the legacy CSV `string` (defensive `split(',')`). Recipients are
   normalised (lowercased, trimmed, deduped) and validated against a
   pragmatic email regex; invalid entries are dropped silently.
2. **Throttles** each surviving recipient by querying
   `email_notifications` for any `status='sent'` row with
   `sent_at >= now - 60s` (configurable). Hits are skipped; the
   outbox event is still transitioned to `dispatched`.
3. Resolves the `event_kind`:
    * `review_requested` if no previous row exists for the slot
      `(agency, site, property, recipient)`.
    * `review_requested_resent` otherwise. The UNIQUE constraint on
      `(agency, site, property, recipient, event_kind)` lets the new
      rows coexist with the originals.
4. Inserts one `queued` row per recipient in `email_notifications` via
   `insert_pending`.
5. Enqueues **one** `email_send` job carrying every recipient (the
   design calls for a single SMTP envelope with all `To:` headers
   visible).
6. Transitions the outbox row to `status='dispatched'`.

### `email_send` job contract

The worker handler `SendEmailJobHandler` is registered for
`kind='email_send'` in `apps.worker.runtime.build_default_dispatcher`.
Payload schema:

```json
{
  "event_kind": "review_requested",            // or "review_requested_resent"
  "agency_id": "uuid",
  "site_id": "ckp.ie",
  "source_property_id": 137,
  "email_notification_ids": ["uuid-a", "uuid-b"],
  "recipient_emails": ["a@x.com", "b@x.com"],
  "context": {
    "agency_name": "CKP Properties",
    "property_title": "Casa Azul",
    "property_address": "Ballsbridge, Dublin",
    "reel_url": "https://admin.example.com/reels?site_id=ckp.ie&property_id=137"
  }
}
```

On success the handler updates every row in
`email_notification_ids` with the same `provider_message_id` returned
by the configured `EmailSender` (or `None` for `ConsoleEmailSender`)
and a tz-aware `sent_at`. On exception every row is transitioned to
`status='failed'` with the error string persisted, and the exception
is re-raised so the worker treats the job as a failed attempt
(eligible for retry per the global queue policy).

### Templates

Plain text + optional HTML templates live in
`assets/email/templates/`:

* `review_requested.txt` (canonical body).
* `review_requested.html` (optional HTML alternative with a
  "Review reel" button).

`EmailTemplateRenderer.render_html` HTML-escapes every value in the
context dict before substitution. Missing placeholders raise
`KeyError` instead of leaking the literal `"{...}"` into the email.

### Re-render semantics

Feature 27 does **not** modify `PublishReelUseCase` or
`regenerate_reel`. The re-render path (admin Approve flow that
re-emits `review_requested` after a regenerate) is already wired into
the outbox; the subscriber treats every fresh outbox row as a new
dispatch and chooses the `review_requested_resent` event kind when a
previous row exists for the slot.

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
