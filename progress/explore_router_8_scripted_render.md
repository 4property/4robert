# Explore — Feature 8 `rendering_scripted_router`

> Read-only mapping for the implementer. Goal: extract `POST /videos/scripted/render`
> from `services/transport/http/server.py` into
> `modules/rendering/transport/http/scripted_router.py`, and turn it from a
> synchronous inline render into an enqueue-only endpoint that pushes a job of
> `kind="scripted_render"` onto `delivery.jobs`. The worker handler for that
> kind is **already wired** (feature 16 is *not* a blocker for the enqueue side).

---

## 1. Current route & handler in `services/transport/http/server.py`

- **Path:** `POST /videos/scripted/render`
- **Decorator:** `services/transport/http/server.py:3841-3851`
- **Handler:** `async def render_scripted_video(request: Request) -> JSONResponse`
  defined at `services/transport/http/server.py:3852-3960` (closure inside
  `WordPressWebhookServer._build_app` — no router; FastAPI app decorator).
- **Total LoC of the handler block** (decorator → end of `return JSONResponse`):
  **120 LoC** (`server.py:3841-3960`).
- **Dependencies (helpers used inside the handler):**
  - `_get_runtime(request)` → `services/transport/http/server.py:4012-4013`
    returns the `WordPressWebhookApplication` instance from `request.app.state.runtime`.
  - `runtime.max_payload_bytes` (settings; comes from `WEBHOOK_MAX_PAYLOAD_BYTES`).
  - `_parse_content_length` → `services/transport/http/server.py:4408-4415`.
  - `_parse_json_object_payload` → `services/transport/http/server.py:4442-4460`.
  - `_json_error` (alias of `apps.api.error_handlers.json_error`) →
    `services/transport/http/server.py:93`.
  - `_format_client` (from `apps.api.admin_auth`) →
    `services/transport/http/server.py:91`.
  - `format_console_block`, `format_detail_line`, `log_persistent_event` from
    `shared/observability/`.
  - Errors caught: `ValidationError`, `ResourceNotFoundError`, `ApplicationError`
    from `core.errors` (legacy module — equivalent today lives at
    `shared/errors/`).

- **Body contract (today):** must be `Content-Type: application/json` with a
  single JSON object describing the manifest. The body is parsed lazily into a
  `dict` and forwarded as `payload=…` to
  `runtime.render_scripted_video(payload=…)` →
  `services/transport/http/server.py:1316-1321`, which **calls
  `self.scripted_video_service.render_from_manifest(payload)` synchronously**
  (`application/scripted_render/service.py:88-276` — full ffmpeg render,
  artifact persistence, returns `ScriptedVideoRenderResult`).

- **Response (today):** `201 Created`, body
  `{status: "rendered", render_id, site_id, source_property_id, video_path,
  manifest_path, request_manifest_path}` (`server.py:3949-3960`).

- **CHANGE OF CONTRACT (RISK).** Today the endpoint is **synchronous** and
  blocks until ffmpeg finishes (can take minutes). After feature 8 it becomes
  **`202 Accepted`** with `{status: "accepted", job_id, event_id}` and the
  worker does the render asynchronously.
  - The wire-format response shape changes: `render_id` / `video_path` /
    `manifest_path` are no longer returned (they don't exist yet at enqueue
    time). Clients that parsed those fields will break.
  - OpenAPI doc also has to flip from `201` → `202` (decoration in
    `services/transport/http/openapi_docs.py:359-454` — `_decorate_scripted_render_operation`).
  - Result polling: there is no GET endpoint for scripted artifacts today; the
    artifact persists in `scripted_video_artifacts` (table owned by
    `modules/reels/infrastructure/scripted_video_artifact_repository.py`) but
    nothing exposes it over HTTP. Implementer must decide whether feature 8
    just returns `{job_id, event_id}` and leaves the polling route for a
    future feature, or also adds a GET. The `feature_list.json` acceptance
    only mandates the enqueue side.

---

## 2. Existing use case `RenderScriptedVideoUseCase`

- **Files (duplicated content):**
  - `modules/reels/application/use_cases/render_scripted_video.py:1-42`
  - `modules/reels/application/use_cases/__init__.py:1-42` (same class — the
    `__init__.py` re-defines it instead of importing from the sibling module;
    this is pre-existing and not in scope to fix here).
- **Class:** `RenderScriptedVideoUseCase`
  - `__init__(*, workspace_dir, database_locator=None)` — stores both, lazy.
  - `execute(job: Job) -> object | None` — Worker-shaped contract: receives a
    `Job` (`modules/delivery/domain/job.py:34-58`), reads `job.payload`,
    backfills `site_id` from `job.external_source_id` and `source_property_id`
    from `job.property_id`, then delegates to the legacy
    `ScriptedVideoRenderService.render_from_manifest(payload)`.
- **Critical:** the use case takes a `Job`, **not** an HTTP body. So the
  router cannot call it directly even if it wanted to (and per inter-module
  rules it must not — see §8). The router just enqueues a job; the worker's
  dispatcher loads the use case and feeds it the claimed `Job`.

---

## 3. `delivery.jobs` table and the `scripted_render` kind

- **Schema column:** `jobs.kind` is `sa.Text()` with `server_default="reel_publish"`,
  no enum / no CHECK constraint
  (`alembic/versions/20260501_0001_initial_schema.py:522`).
- **Repository:** `JobRepository` —
  `modules/delivery/infrastructure/job_repository.py:81-365`.
  - `enqueue_job(JobEnqueueRequest)` → `job_repository.py:84-122` (line 107
    normalizes `kind` to lowercase before insert, no allow-list filter).
- **Domain DTO:** `JobEnqueueRequest` —
  `modules/delivery/domain/job.py:15-31` (frozen slots dataclass, requires
  `kind: str` plus `agency_id`, `ingestion_source_id`, `external_source_id`,
  `property_id` (nullable), `received_at`, `raw_payload_hash`, `payload` mapping,
  `publish_context` mapping, `provider_secret_bundle: str`, `max_attempts`,
  `available_at`, `created_at`).
- **Catalog of kinds:**
  - Documented at `ARCHITECTURE.md:99` and `modules/delivery/domain/job.py:1-7`
    (docstring): `reel_publish` and `scripted_render`.
  - Worker registry: `apps/worker/runtime.py:271-278` already calls
    `dispatcher.register_handler("scripted_render", scripted_render.execute)`.
  - **Conclusion:** kind `scripted_render` is **already** part of the catalog;
    no migration is needed; no schema change.

---

## 4. Job payload shape

- The HTTP body is the scripted render **manifest** (the same dict the
  legacy `ScriptedVideoRenderService.render_from_manifest` consumes today).
- Required top-level fields the manifest validator expects (see
  `application/scripted_render/service.py:106-107` plus `_resolve_request`
  at `service.py:282-370`):
  - `site_id` (str, required) — used for tenant resolution.
  - `source_property_id` (int, required) — used for property lookup.
  - `title` (str, required), `property_status` (str, required).
  - `slides` (non-empty array, required) — each slide must have either
    `image_path` or `sources[0].path`, optional `caption`. Paths must resolve
    inside the workspace.
  - Optional: `render_profile`, `render_settings` (object validated by
    `_ScriptedRenderSettingsPayload`), `link`, `featured_image_url`,
    `bedrooms`, `bathrooms`, `ber_rating`, agent_*, price_*, area/county
    labels, `eircode`, `agency_logo_url`, `agency_psra`, `listing_lifecycle`,
    `banner_text`, `price_display_text`, `background_audio_path`.
  - The OpenAPI request schema is encoded in
    `services/transport/http/openapi_docs.py:748-1001`.
- **Transformations applied to build the job payload:**
  - The router parses the body via `_parse_json_object_payload` and forwards
    the resulting dict **verbatim** into `JobEnqueueRequest.payload`.
  - The use case at execution time (`__init__.py:34-37`) does
    `payload.setdefault("site_id", job.external_source_id)` and
    `payload.setdefault("source_property_id", job.property_id)`. So storing
    them in the job is convenient but not strictly required — however to keep
    `external_source_id` and `property_id` populated on the row (for the
    dispatcher's per-property serialization), the router **must** also extract
    them from the body and pass them as separate `JobEnqueueRequest` fields:
    - `external_source_id = payload["site_id"]` (lowercased).
    - `property_id = payload.get("source_property_id")`.
  - `raw_payload_hash`: hash the body bytes with sha256 (same pattern as
    `enqueue_reel_publish` at `server.py:1183`).
  - `publish_context`: empty `{}` (scripted renders do not publish to GHL —
    confirm with leader; if scripted artifacts ever publish, that's
    out-of-scope for feature 8).
  - `provider_secret_bundle`: empty string `""` (no provider needed).
  - `max_attempts`: take from settings (`WORKER_JOB_MAX_ATTEMPTS` if
    present, else default 1 — needs to be confirmed in
    `settings/`).

---

## 5. Worker dispatcher

- **Path:** `apps/worker/runtime.py:259-279` —
  `build_default_dispatcher(*, settings) -> JobDispatcher` already constructs
  `RenderScriptedVideoUseCase(...)` and registers
  `"scripted_render" → scripted_render.execute` via
  `dispatcher.register_handler` at line 275-278.
- The handler is a **bridge** today: lazily imports
  `application.scripted_render.service.ScriptedVideoRenderService` at first
  call (`modules/reels/application/use_cases/render_scripted_video.py:22-32`).
  Feature 14/16 will replace the bridge with a pure use case, but for
  feature 8 the bridge is enough — the worker will already pick up
  `scripted_render` jobs as soon as the API enqueues them.
- **No new handler registration is needed in this feature.** The implementer
  should NOT touch `apps/worker/runtime.py`.

---

## 6. Pydantic payloads to add under `modules/rendering/transport/payloads/`

There is **no existing Pydantic payload module for rendering**; the dir
`modules/rendering/transport/` does not exist yet.

Implementer should create:

- `modules/rendering/transport/__init__.py` and
  `modules/rendering/transport/http/__init__.py` and
  `modules/rendering/transport/payloads/__init__.py`.
- `modules/rendering/transport/payloads/scripted.py` — at minimum:
  - `ScriptedRenderResponse(BaseModel)` with `status: Literal["accepted"]`,
    `job_id: str`, `event_id: str`, plus optional echoes
    (`site_id`, `source_property_id`).
  - **Decision for the request body:** because the manifest is a large /
    semi-open JSON object, current code parses it as `dict[str, Any]` and
    delegates validation to `ScriptedVideoRenderService` at execution time.
    The router can keep this approach and only validate required top-level
    keys (`site_id`, `source_property_id`) eagerly — anything else is
    re-validated by the worker. Alternative: build a strict
    `ScriptedRenderRequest` from the OpenAPI schema in `openapi_docs.py`. The
    implementer should pick the lighter eager validation to avoid duplicating
    the manifest schema in two places (the legacy service is the source of
    truth until feature 14 moves it).

---

## 7. Cross-cutting helpers needed

- `apps/api/error_handlers.json_error` — already extracted in feature 1.
  Import directly.
- `apps/api/admin_auth.format_client` — for log lines (no admin auth required
  for `/videos/scripted/render`; today it's an open endpoint).
- `_parse_json_object_payload` and `_parse_content_length` are still inside
  `services/transport/http/server.py:4408-4460`. They are **not** yet
  extracted to `apps/api/`. Two options:
  1. Inline a small private `_parse_json_object` helper in the new router (≤
     20 LoC).
  2. Promote the helpers to `apps/api/json_payload.py` (or similar) and
     import from both places. **Recommended** since features 2-7 will need
     the same primitives.
- `shared.observability.format_console_block`, `format_detail_line`,
  `log_persistent_event` — already used elsewhere. Import directly.
- `shared.errors.ValidationError`, `ResourceNotFoundError`,
  `ApplicationError` — modern path to use from the new router (legacy
  `core.errors` re-exports the same classes via shim).

---

## 8. Cross-module import constraints

The router lives under `modules/rendering/transport/`. The use case lives
under `modules/reels/application/`. Per `ARCHITECTURE.md:70-76` and
`docs/architecture.md:21-26`, **a module may not import another module's
`application/` or `infrastructure/`**.

- The router **must not** import `RenderScriptedVideoUseCase` from
  `modules/reels/application/`. Doing so would violate the inter-module rule
  (rendering → reels.application).
- The router **does not need** to import the use case anyway. Its only job
  is to enqueue a job:
  - Resolve tenant for `site_id` (read from `uow.ingestion.sources` /
    `uow.tenancy.agencies` via shared UoW — both are read-only lookups
    against tables owned by other modules; reading a different module's
    *infrastructure* via the **shared UoW namespace** is the canonical
    pattern documented in `shared/db/uow.py:1-17` and is **not** forbidden,
    because the import goes through `shared.db`, not directly into another
    module).
  - Build a `JobEnqueueRequest` (`from modules.delivery.domain import
    JobEnqueueRequest`) — delivery is a peer module and importing its
    `domain/` is allowed (`docs/architecture.md:22`).
  - Call `uow.delivery.jobs.enqueue_job(...)` — same pattern.
  - Optionally also call `uow.delivery.webhook_events.create_event(...)` so
    the queued job has a paired `webhook_events` row (the worker's claim
    loop calls `update_event_status` against it; if no row exists it will
    silently no-op the audit). The wordpress webhook sets
    `source_kind="wordpress"` — for scripted render, the implementer can
    pass `source_kind="scripted_api"` or similar; that column has no enum
    constraint at the schema level (verify
    `alembic/versions/20260501_0001_initial_schema.py` for the
    `webhook_events` table).
- **Tenant resolution:** the legacy `WebhookAcceptanceService`
  (`application/dispatch/webhook_acceptance.py:38-114`) used a
  `TenantResolver` (`application/tenancy/resolver.py:13-58`). Both live in
  the legacy `application/` tree. The new router has two clean paths:
  - **(a) Inline lookup in the router (recommended for feature 8).** Use the
    UoW directly:
    ```python
    with DatabaseUnitOfWork(...) as uow:
        source = uow.ingestion.sources.get_by_kind_external_id(
            kind="wordpress", external_id=site_id_normalized,
        )
        # source has .agency_id and .id (ingestion_source_id)
    ```
    This is shared infra and does not violate inter-module rules.
  - **(b) New `EnqueueScriptedRenderUseCase` under
    `modules/rendering/application/use_cases/enqueue_scripted_render.py`.**
    Cleaner long-term but adds scope. Acceptable per the feature
    description ("solo mueve el transport y conecta el flujo POST →
    enqueue") — option (a) is closer to what the feature literally
    requires.

---

## 9. Existing tests touching `/videos/scripted/render` or the use case

- **No existing tests** under `tests/` reference `/videos/scripted/render`,
  `RenderScriptedVideo`, or `scripted_render` job kind directly.
  Verified via grep over the entire `tests/` tree.
- The closest precedent the implementer can copy:
  - `tests/integration/test_worker_runtime.py:97-144` — pattern for seeding
    a `webhook_events` row + enqueuing a `JobEnqueueRequest` via the UoW.
  - `tests/integration/test_http_transport.py` — pattern for HTTP-level
    integration tests against the FastAPI app.
- Required tests per `feature_list.json` feature 8 acceptance:
  - **Unit:** verifies the router enqueues a job with the correct
    `JobEnqueueRequest` (mock UoW or in-memory repo).
  - **Integration:** posts a body, asserts a row appears in `jobs` with
    `kind='scripted_render'`, `payload_json` matching the body, status
    `queued`. Recommended layout:
    `tests/integration/rendering/test_scripted_router.py`.

---

## 10. Cross-feature coupling

- **Feature 16 (`worker_real_use_cases_and_drop_noop_dispatcher`)** —
  feature 16 will replace the bridge `RenderScriptedVideoUseCase` with a
  pure use case (and drop `_NoopDispatcher`). For feature 8 this is
  irrelevant: the bridge is **already** registered in
  `apps/worker/runtime.py:259-279` and pulls `scripted_render` jobs today.
  Feature 8 does **not** depend on feature 16; the implementer should leave
  `apps/worker/runtime.py` untouched.
- **Feature 14 (`rendering_pure_renderer_and_delete_media_services`)** —
  later removes `application/scripted_render/service.py` and moves the
  rendering logic to `modules/rendering/application/`. Feature 8 must not
  import `application.scripted_render.*` from the new router (that import
  would have to be migrated again at feature 14). The router only needs
  `JobEnqueueRequest` and the UoW.
- **Feature 9 (`retire_wordpress_webhook_server`)** — needs feature 8 done
  before it can run. Specifically, feature 9 will delete `server.py`; until
  feature 8 lands, `/videos/scripted/render` still has its only handler
  there.

---

## 11. Estimated LoC to move

| Block                                           | Approx LoC |
|-------------------------------------------------|------------|
| Existing handler `render_scripted_video` (server.py:3841-3960) | 120 |
| New router file (`modules/rendering/transport/http/scripted_router.py`) | ~120-140 |
| New payloads file (`modules/rendering/transport/payloads/scripted.py`) | ~30-50 |
| `apps/api/app_factory.py` registration                          | ~5-10 |
| `services/transport/http/server.py` removal of decorator + handler | -120 |
| `services/transport/http/server.py` removal of `WordPressWebhookApplication.render_scripted_video` (1316-1321) | -6 |
| `services/transport/http/openapi_docs.py` decoration (359-454) | leave or relocate to router (~95) |
| Unit + integration tests                                      | ~150-220 |

**Total net add: ~250-400 LoC** (router + payloads + tests). Net delete from
legacy: ~125 LoC.

---

## 12. Risks & blockers

1. **Behaviour change sync → async (HARD CONTRACT BREAK).** Today's response
   includes `render_id`, `video_path`, `manifest_path`. After feature 8
   those fields are not yet known at HTTP-response time. Any consumer
   relying on the synchronous shape **breaks**. The leader must confirm
   with the user whether it's acceptable to ship the breaking change in
   feature 8, or whether a transitional GET endpoint (e.g.
   `/videos/scripted/{render_id}`) for polling artifacts is needed. The
   feature description explicitly says "encolar un job, NO ejecutar
   inline", so the break is intentional — but it should be flagged in the
   review/PR notes for the user.
2. **OpenAPI doc drift.** `services/transport/http/openapi_docs.py:359-454`
   currently documents the 201/synchronous shape. The implementer must
   either:
   - delete `_decorate_scripted_render_operation` and let FastAPI auto-doc
     from the new router's response model, OR
   - move the decoration into the new router and rewrite for `202 Accepted`
     with the new response shape.
3. **Worker pre-condition.** The acceptance bullet
   `python -m apps.worker --check termina exit 0` must pass. Worker
   already registers `scripted_render` (`apps/worker/runtime.py:271-278`)
   so this should be green out of the box; mention it in the impl report
   to make the reviewer's life easier.
4. **Tenant resolution on unknown sites.** Legacy
   `WordPressWebhookApplication` had
   `webhook_auto_provision_unknown_sites_for_testing` flag (server.py
   ctor). For the new router, decide whether the same auto-provision flag
   applies. Default: do **not** auto-provision; fail with 404
   `UNKNOWN_WORDPRESS_SITE` if `ingestion_sources.kind='wordpress',
   external_id=site_id` does not exist (matches the use case validation
   at `application/scripted_render/service.py:111-117`).
5. **Worker workspace mismatch.** The router enqueues a job; the worker
   reads it. They share `DATABASE_URL` and the on-disk workspace
   (`compose.yml`). If the API and worker run with different
   `WORKSPACE_DIR`, the worker's `RenderScriptedVideoUseCase` will not be
   able to resolve the relative `image_path`/`sources` of the manifest.
   Document the assumption in the impl report (no fix needed for
   feature 8).
6. **Job audit row.** Decision: create an associated `webhook_events` row
   (with a non-`wordpress` `source_kind`) so the worker's per-claim
   `update_event_status(...)` does not silently no-op. Quick win, low
   cost. The implementer should choose `source_kind="scripted_api"` or
   similar and check whether `webhook_events.source_kind` has any CHECK
   constraint (verify alembic schema before final implementation).

---

## TL;DR for the implementer

- Create `modules/rendering/transport/http/scripted_router.py` exposing
  `POST /videos/scripted/render` returning `202` + `{job_id, event_id}`.
- Build a `JobEnqueueRequest(kind="scripted_render", payload=<body dict>,
  external_source_id=<site_id>, property_id=<source_property_id>, ...)`
  via `DatabaseUnitOfWork` (`uow.delivery.jobs.enqueue_job(...)`).
- Resolve agency/ingestion_source via `uow.ingestion.sources.get_by_kind_external_id(
  kind="wordpress", external_id=site_id)` — do NOT import from
  `application/tenancy/`.
- Do NOT import `RenderScriptedVideoUseCase` from
  `modules/reels/application/` — the worker already has it registered.
- Register the router in `apps/api/app_factory.py` and remove the inline
  handler + `WordPressWebhookApplication.render_scripted_video` from
  `services/transport/http/server.py`.
- Update / delete OpenAPI decoration for `/videos/scripted/render` in
  `services/transport/http/openapi_docs.py:359-454`.
- Add unit + integration tests; the latter should assert a `jobs` row
  with `kind='scripted_render'` and the expected `payload_json`.
- No alembic migration required (`jobs.kind` is unconstrained Text;
  `scripted_render` already documented as a valid kind).
- Flag the sync→async response shape change in the impl + review report.
