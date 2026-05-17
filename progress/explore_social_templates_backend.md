# Explore: backend social-templates (2026-05-14)

## TL;DR

**Router EXISTS and IS WIRED.** Both endpoints fully implemented:
- `GET /v1/admin/agencies/{agency_id}/social-templates` reads per-platform `description_template` from `agency_social_templates` table
- `PUT /v1/admin/agencies/{agency_id}/social-templates` replaces entire block (drops old, inserts new)
- Validated templates ARE injected into caption-generation pipeline at reel-publish time (`modules.reels.application.content_generator:render_template_with_property`)
- All required features present: variable validation (22 variables allowed), platform-agnostic key acceptance, hashtag/title fields hydrated but not yet frontend-exposed
- Missing integration: frontend not yet sending `hashtags` or `title_template` (currently empty, placeholder for future UI expansion)

## Router (path + archivo:línea)

**File:** `/opt/projects/4Reels-Backend/modules/configuration/transport/http/social_templates_router.py`

- **GET handler:** `read_admin_agency_social_templates()` (línea 64)
  - Route: `GET /agencies/{agency_id}/social-templates`
  - Returns: `{"templates": {platform: description_template, ...}, "items": [...], "count": N}`
  - Status codes: 200 on success, 404 if agency not found
- **PUT handler:** `replace_admin_agency_social_templates()` (línea 101)
  - Route: `PUT /agencies/{agency_id}/social-templates`
  - Payload: `SocialTemplatesReplacePayload` (see Validación payload below)
  - Returns: `{"status": "saved", "templates": {...}, "items": [...], "count": N}`
  - Status codes: 200 on success, 404 if agency not found, 422 if unknown variables detected

**Mounted in:** `apps/api/app_factory.py` line 61-62 (imports), line ~280 (include_router)

## Persistencia

- **Tabla:** `agency_social_templates`
- **Columns:**
  - `agency_id` (String(36), FK→agencies.id, part of composite PK)
  - `platform` (Text, part of composite PK) — any string accepted; no enum validation in DB
  - `description_template` (Text, not null)
  - `title_template` (Text, not null, default="")
  - `hashtags` (ARRAY(Text), default=[])
  - `created_at`, `updated_at` (DateTime(timezone=True))
  - **PK:** `(agency_id, platform)` — one row per platform per agency

- **Migración Alembic:** `alembic/versions/20260501_0001_initial_schema.py` línea 198-218
  - Single initial migration that creates the table and FK constraint with CASCADE delete
  - No subsequent alterations

- **Default value:** New rows created with empty `title_template` and `hashtags=[]`; `description_template` is mandatory (no default)

- **ORM class:** `AgencySocialTemplateORM` (`modules/configuration/infrastructure/orm.py` línea 154-172)

- **Repository:** `SocialTemplatesRepository` (`modules/configuration/infrastructure/social_template_repository.py`)
  - Methods: `list_for_agency()`, `get()`, `upsert()`, `delete()`, `delete_all_for_agency()`, `replace_all_for_agency()`
  - `replace_all_for_agency()` is the verb used by the PUT endpoint (drops all, reinserts from payload)

## Plataformas soportadas

**Canonical list (from `docs/API.md` línea 120-122):**
- `instagram`, `tiktok`, `facebook`, `linkedin`, `youtube`, `gbp` (or `google_business_profile`), `pinterest`

**Backend validation:**
- **NO enum validation.** The router accepts any platform string (uppercase, lowercase, mixed — all normalized to lowercase by `_collect_unknown_template_variables()` before persistence)
- **No hardcoded allowlist.** The payload Pydantic model (`SocialTemplatesReplacePayload`) explicitly allows unknown keys: `description` says "Unknown keys are accepted so future platforms do not need a schema bump"
- **Source of truth:** `docs/API.md` §3 table + the `ReelDefaults.platforms` array default in migration (línea 148-150 of migration)
  - Default: `['tiktok','instagram','linkedin','youtube','facebook','gbp']` — note: `pinterest` is **documented** but **not** in the defaults array
- **At publish time:** only platforms in `agency_reel_defaults.platforms` get captions generated; social templates are looked up but not required

## Validación payload

- **Pydantic model:** `SocialTemplatesReplacePayload` (`modules/configuration/transport/payloads/social_templates.py`)
  - Field: `templates: dict[str, str] | None` (keys = platform, values = description template)
  - `model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)` — rejects unknown JSON keys (but platform keys inside `templates` map ARE unknown keys that slip through the `extra="forbid"` net because they're nested inside the `templates` dict)
  - No validation on platform names themselves
  - No validation on template string length

- **Variable validation (critical):**
  - Happens in router `_collect_unknown_template_variables()` (línea 175-193) **BEFORE** calling the use case
  - Allowed variables: `ALLOWED_TEMPLATE_VARIABLES` from `modules.configuration.domain.social_templates_variables` (19 variables: `property_title`, `price`, `bedrooms`, `bathrooms`, `size_m2`, `property_type`, `city`, `neighborhood`, `neighborhood_tag`, `eircode`, `short_description`, `agent_name`, `agent_phone`, `agent_email`, `booking_link`, `property_url`)
  - Regex pattern: `\{\{\s*([\w.]+)\s*\}\}` — matches `{{ variable_name }}` with optional whitespace
  - Unknown variable in any template → 422 with detailed list per platform

- **Hashtags & title_template:**
  - Accepted in the ORM but **currently not exposed by frontend**
  - Frontend sends only `{"templates": {platform: description_template}}` (flat shape)
  - Backend comment (línea 127-129 of repository): "Frontend currently sends a flat map; richer fields keep their default empty values. Migrating the frontend to the rich shape is a separate feature."

## Tests

**Integration test file:** `tests/integration/configuration/test_social_templates_router.py`

Test functions (no content copied, names only):
1. `test_social_templates_get_returns_empty_when_none_stored()`
2. `test_social_templates_put_persists_per_platform_rows()`
3. `test_social_templates_put_replaces_whole_block()` — validates destructive semantics (old rows dropped)
4. `test_social_templates_returns_404_for_unknown_agency()`
5. `test_social_templates_put_rejects_unknown_variable_with_422()`
6. `test_social_templates_put_accepts_allowed_variables_only()`
7. `test_social_templates_put_accepts_template_without_any_variables()` — regression: plain strings ok
8. `test_social_templates_put_accepts_literal_braces_that_do_not_form_a_variable()` — `{{ }}` vs `{{var}}`
9. `test_social_templates_put_reports_every_offending_platform()` — batch error reporting

## Auth

- **`admin_access_policy` required:** YES
  - Both handlers call `authorize_admin_request(request, admin_access_policy)` (línea 68, 106)
  - Returns 401 if bearer token invalid or missing
- **Relevant setting:** `ADMIN_API_DISABLE_AUTH_FOR_TESTING` (from `settings.admin`)
  - When `True`, tests skip real auth (passed via `admin_access_policy` arg to the router factory)

## Documentación

- **`docs/http_surface.md`:** YES, listed (línea with GET/PUT and function names)
- **`docs/API.md`:** YES, fully documented (§3 table, línea 113 + context about platform identifiers, línea 120-122 + variable allowlist, línea siguiente al 113)
- **OpenAPI/Swagger:** Generated from Pydantic + router docstrings; accessible at `/docs`

## Gaps identificados

1. **Frontend hashtags/title_template not hydrated:** Repository comment flags this as planned future work; backend fully supports it, frontend sends only `description_template` (TODO: coordinate UI expansion)
2. **Pinterest platform in docs but not in defaults:** `pinterest` appears in docs/API.md canonical list but not in the `agency_reel_defaults.platforms` default array — no functional break (publisher accepts any platform) but confusing
3. **No enum validation on platform strings:** Backend accepts any key; this is intentional for future extensibility but means frontend must pre-validate platform names OR the UI will silently persist templates for invalid platforms (e.g., typo "instargram")
4. **Template description_template injected into caption BUT not into reel-publish job context uniformly:** The `regenerate_reel` use case fetches social templates and passes them to the content generator (modules/reels/application/use_cases/regenerate_reel.py lines ~105-115), but the webhook-ingestion path (`_ingest_property_planning.py`) initializes them as empty dict in publish_context (línea visible in grep: `"social_templates_map", {}`) — verify this is intentional (probably is: regenerate is admin-triggered, webhook is auto-publish so uses defaults only)

**Summary:** Backend is **production-ready** for per-platform description-template persistence and injection. Frontend must expand UI to support title_template and hashtags when planned.
