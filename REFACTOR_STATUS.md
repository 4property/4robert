# Refactor status â€” modular monolith + decoupled worker

This document tracks the migration from the legacy single-process layout
(`services/`, `application/`, `repositories/`, `core/`, `domain/`) to the
modular-monolith target described in [ARCHITECTURE.md](ARCHITECTURE.md).

Phasing: **Phase 1 foundation âœ… DONE â†’ Phase 2 god-file split âœ… DONE
(2026-05-06) â†’ Phase 3 URL rename + frontend lockstep âœ… DONE
(2026-05-06) â†’ Phase 4 frontend/backend live contract hardening âœ… DONE
(2026-05-07)**.

---

## Phase 1 â€” Foundation âœ… DONE

Schema, infrastructure, and the API/worker process split are in place. The
legacy code that imports from `repositories/`, `services/`, `application/`,
`core/`, `domain/` keeps working through compatibility shims; Phase 2
dissolves those into module use cases.

### Test status

```
$ .\.venv\Scripts\python.exe -m pytest -q
116 passed
```

Unit, integration, and full backend suites are green. The former persistent
logging date mismatch is fixed: dated log files and line timestamps now use
the same injected date provider.

### What landed

**Schema + ORM**
- Single Alembic migration
  ([`alembic/versions/20260501_0001_initial_schema.py`](alembic/versions/20260501_0001_initial_schema.py))
  builds the full 16-table schema. The three previous migrations are gone.
- ORM mappings live in [`shared/db/orm.py`](shared/db/orm.py) (16 classes);
  Alembic `env.py` targets `shared.db.base.Base.metadata`.
- DB recreated from scratch and validated. `.env` switched from
  `127.0.0.1:5432` to `localhost:5432` because a VS Code port-forward was
  intercepting the loopback socket and routing to a stale postgres.

**Skeleton**
- `apps/{api,worker}/`,
  `modules/<8 contexts>/{domain,application,infrastructure,transport}/`,
  `shared/{db,http,observability,errors,locking,crypto,storage,media_cleanup}/`.
  Originally `platform/` â€” renamed to `shared/` because Python's stdlib
  `platform` is imported by numpy / imageio_ffmpeg at runtime.

**`shared/db/`**
- [`engine.py`](shared/db/engine.py), [`session.py`](shared/db/session.py),
  [`security.py`](shared/db/security.py),
  [`repository_base.py`](shared/db/repository_base.py) â€” Postgres-only,
  no SQLite compat layer.
- [`uow.py`](shared/db/uow.py) â€” `DatabaseUnitOfWork` with seven
  module-namespaced repository facades:

  ```python
  with DatabaseUnitOfWork() as uow:
      uow.tenancy.agencies            # AgencyRepository
      uow.ingestion.sources           # IngestionSourceRepository (kind discriminator)
      uow.publishing.connections      # ProviderConnectionRepository (provider discriminator)
      uow.catalog.properties          # PropertyRepository
      uow.catalog.images              # PropertyImageRepository
      uow.reels.states                # ReelStateRepository
      uow.reels.revisions             # MediaRevisionRepository
      uow.reels.scripted_artifacts    # ScriptedVideoArtifactRepository
      uow.reels.queries               # ReelQuery (cross-aggregate JOIN reads)
      uow.configuration.brand         # BrandSettingsRepository
      uow.configuration.defaults      # ReelDefaultsRepository
      uow.configuration.automation    # AutomationRulesRepository
      uow.configuration.social_templates  # SocialTemplatesRepository
      uow.configuration.music         # MusicTracksRepository
      uow.delivery.jobs               # JobRepository (kind discriminator)
      uow.delivery.outbox             # OutboxRepository
      uow.delivery.webhook_events     # WebhookEventRepository
  ```

**Domain models** (plain dataclasses under each module's `domain/`):
`Agency`, `IngestionSource`, `ProviderConnection`, `Job`, `OutboxEvent`,
`WebhookEvent`, `ReelState`, `MediaRevision`, `ScriptedVideoArtifact`,
`BrandSettings`, `ReelDefaults`, `AutomationRules`, `SocialTemplate`,
`MusicTrack`, `CatalogProperty`, `CatalogPropertyImage`,
`AgencyReelSummary`, `PropertyReelRecord`, `PropertySyncState`.

**`shared/<observability,errors,locking,media_cleanup>/`** are re-export
shims over `core/` for Phase 1 (Phase 2 relocates the implementations).

**`apps/worker/`**
- [`main.py`](apps/worker/main.py): `python -m apps.worker [--check]`
  entry point with SIGTERM-safe shutdown.
- [`runtime.py`](apps/worker/runtime.py): `JobDispatcher` with a
  `kind â†’ handler` registry, `FOR UPDATE SKIP LOCKED` claim,
  property-level serialization, retry-with-backoff, and dead-letter
  through `JobRepository.mark_job_failed`.
- Default registry: `reel_publish` and `scripted_render`. Phase 2 now uses
  app-level bridge handlers into the legacy implementations until the real
  module use cases are fully extracted.

**`apps/api/`**
- [`main.py`](apps/api/main.py): `python -m apps.api [--check]` entry
  point with the same readiness-report pattern as the legacy entry.
- [`app_factory.py`](apps/api/app_factory.py): builds the FastAPI app
  with a `_NoopDispatcher` because the worker runs in a separate
  process. Lifespan is HTTP-only.

**`compose.yml`** runs three services: `postgres`, `api`
(`python -m apps.api`), `worker` (`python -m apps.worker`). The api +
worker share named volumes for `property_media/`, `property_media_raw/`,
`generated_media/`, `logs/` and the same `DATABASE_URL`.

**`.env` / `.env.example`** add the new `WORKER_*` variable namespace; the
legacy `WEBHOOK_WORKER_*` names still work as a fallback during the
transition. Phase 3 drops the legacy names.

**Tests**
- [`tests/support/postgres.py`](tests/support/postgres.py) rewritten:
  `ACTIVE_TABLES` now lists the new 16 tables; `seed_tenant` writes to
  `ingestion_sources(kind='wordpress')`; `seed_provider_connection`
  replaces `seed_ghl_connection` (kept as a thin alias).
- All 11 legacy stores under `repositories/stores/` rewritten to target
  the new schema while preserving their public API. This is the
  compatibility layer that lets the existing `application/`, `services/`,
  `domain/` code keep working until Phase 2.
- `services/transport/http/operations.py::_REQUIRED_POSTGRES_TABLES`
  updated for the new schema; readiness check + the GHL 404 mapping
  recognise `GHL_CONNECTION_NOT_FOUND`.

### Verification

```
$ python -m apps.api --check        # OK (runtime ready)
$ python -m apps.worker --check     # OK (kinds=reel_publish,scripted_render)
$ pytest -q                         # 116 passed
$ alembic upgrade head              # 17 tables present
```

---

## Phase 2 â€” God-file split âœ… DONE (2026-05-06)

Phase 2 turned the legacy compatibility shims under `application/`,
`services/`, `domain/`, `repositories/stores/`, `core/` into per-module
use cases and routers, then deleted those directories. After feature 18
(sub-features 18a/18b/18c) the legacy tree is fully retired.

**Final state:**
- `services/`, `application/`, `repositories/`, `core/`, `domain/` removed.
- `Grep "from (services|application|repositories|core|domain)\."` in
  `apps/`, `modules/`, `shared/`, `tests/`: **0 hits**.
- All cross-cutting helpers live under `shared/{db,errors,observability,
  locking,media_cleanup,storage,http,crypto}/`.
- Bounded contexts under `modules/<bc>/` are self-contained: rendering
  primitives in `modules/rendering/infrastructure/`, GoHighLevel adapter
  in `modules/publishing/infrastructure/adapters/gohighlevel/`, social
  copy builders in `modules/publishing/infrastructure/social_copy/`.
- **Baseline: 394 tests passing.** Two legacy root god-tests
  (`test_social_publishing.py`, `test_reel_pipeline.py`, ~3 100 LoC
  combined) were retired by sub-feature 18b because their coverage is
  duplicated by the modern integration suites under
  `tests/integration/{publishing,reels,delivery}/`.

### Progress landed after Phase 1

- `apps/worker/runtime.py` now executes real work via app-level legacy
  bridge handlers for `reel_publish` and `scripted_render` instead of
  failing claimed jobs with placeholders. The bridge is temporary: it keeps
  the worker decoupled while the real use cases move into `modules/`.
- The worker accepts an injectable `database_locator`, so integration tests
  can run it against isolated Alembic-created schemas.
- Worker job completion/retry/failure now updates the matching
  `webhook_events` row (`completed`, `noop`, `queued`, `failed`) and clears
  encrypted provider secrets on completion.
- `modules/delivery/infrastructure/webhook_event_repository.py` now writes
  the required `source_kind` column when using the module UoW directly.
- GoHighLevel SSO context decoding moved from
  `services/transport/http/server.py` into
  `modules/publishing/application/use_cases/decode_gohighlevel_session.py`.
- Catalog ORM mappings for `properties` and `property_images` moved to
  `modules/catalog/infrastructure/orm.py`; `shared/db/orm.py` remains the
  Alembic metadata aggregator and is now below 500 LoC.
- Reel rendering runtime was split under
  `modules/rendering/infrastructure/runtime/`; the legacy
  `services/media/reel_rendering/runtime.py` is now a compatibility facade.
- ffmpeg command/filter/render logic was split under
  `modules/rendering/infrastructure/ffmpeg/`; the legacy
  `services/media/reel_rendering/render.py` is now a compatibility facade.
- GoHighLevel publisher logic moved into
  `modules/publishing/infrastructure/adapters/gohighlevel/` as small mixins.
  The legacy `services/publishing/social_delivery/gohighlevel_publisher.py`
  re-exports the adapter.
- Configuration repositories and ORM mappings were split by section under
  `modules/configuration/infrastructure/`.
- `repositories/stores/property_store.py` is below 500 LoC and delegates
  shared records/query helpers to
  `modules/catalog/infrastructure/property_store_compat.py`. Reel detail
  lookups now query `external_source_id` instead of the old `site_id` column.
- `core/logging.py` now uses a persistent-log formatter whose timestamps are
  aligned with the daily log directory provider.

Verification after this increment:

```
$ python -m apps.api --check        # OK
$ python -m apps.worker --check     # OK
$ python -m alembic current         # 20260501_0001 (head)
$ pytest tests/unit -q              # 7 passed
$ pytest tests/integration -q       # 24 passed
$ pytest -q                         # 116 passed
```

| God-file | LoC | Becomes |
|---|---:|---|
| [`services/transport/http/server.py`](services/transport/http/server.py) | 4 941 | Per-module routers under `modules/<bc>/transport/http/<resource>_router.py` + reusable helpers under `apps/api/{range_response,admin_auth,error_handlers,logging_middleware,â€¦}.py`. The `WordPressWebhookApplication` god-class disappears â€” each method becomes a use case. Composition lives in `apps/api/app_factory.py`. |
| [`application/pipeline/media_services.py`](application/pipeline/media_services.py) | 1 839 | Use cases under `modules/reels/application/use_cases/` (`ingest_property_into_reel`, `prepare_reel_assets`, `persist_local_artifacts`, `publish_reel`, â€¦) plus pure-compute renderer in `modules/rendering/application/`. |
| [`services/publishing/social_delivery/gohighlevel_publisher.py`](services/publishing/social_delivery/gohighlevel_publisher.py) | facade | Done: implementation split under `modules/publishing/infrastructure/adapters/gohighlevel/`. |
| [`services/media/reel_rendering/{layout,render,runtime}.py`](services/media/reel_rendering/) | partial | Done for `render.py` and `runtime.py`; `layout.py` still needs the final split. |
| [`repositories/stores/property_store.py`](repositories/stores/property_store.py) | 464 | Partially done: helpers moved into `modules/catalog/infrastructure/`; full legacy deletion waits for the old UoW to retire. |

After Phase 2:

- The temporary worker bridge handlers are replaced by real module use cases:
  `reel_publish` â†’ `ReelPipeline`, `scripted_render` â†’ `RenderScriptedVideoUseCase`.
- The `_NoopDispatcher` in `apps/api/app_factory.py` disappears; the
  dispatcher lives only in `apps/worker/`.
- `repositories/`, `core/`, and most of `application/`, `services/`,
  `domain/` are deleted.
- No file under `modules/`, `apps/`, or `shared/` exceeds ~500 LoC.

---

## Phase 3 â€” URL rename closeout + frontend lockstep (DONE 2026-05-06)

**Reduced scope (2026-05-06).** El grueso del rename a `/v1/...` se
ejecutÃ³ de facto durante Phase 2: cada feature 2-9 que extrajo un
router lo registrÃ³ ya bajo la convenciÃ³n nueva (`ADMIN_API_BASE_PATH=
/v1/admin`, `WEBHOOK_PATH=/v1/ingest/wordpress/property`,
`sessions_router.py` con prefix hard-coded `/v1/sessions/gohighlevel`).
El frontend tambiÃ©n se adaptÃ³ en paralelo. Phase 3 cerro el trabajo
residual con **4 features pequeÃ±as** (ver `feature_list.json` y
`docs/phase_3_operating_rules.md` para el detalle ejecutable):

| # | Feature | Repos | Estado |
|---|---|---|---|
| 1 | `rename_scripted_render_to_v1` | back | done |
| 2 | `align_music_endpoint_front_to_back` | back (docs) + front | done |
| 3 | `resolve_session_me_endpoint` | front (Â±back) | done |
| 4 | `http_surface_audit_and_contract_test` | back (lee front) | done |

### Estado del rename de URLs (auditado 2026-05-06)

| Was (Phase 1) | Now | Estado |
|---|---|---|
| `POST /webhooks/wordpress/property` | `POST /v1/ingest/wordpress/property` | âœ… hecho en Phase 2 feature 4 (`WEBHOOK_PATH` env var) |
| `/admin/agencies` | `/v1/admin/agencies` | âœ… hecho en Phase 2 feature 3 (`ADMIN_API_BASE_PATH=/v1/admin`) |
| `/admin/agencies/{id}/sources` | `/v1/admin/agencies/{id}/sources` | âœ… hecho en Phase 2 feature 4 |
| `/admin/agencies/{id}/ghl-connection` | `/v1/admin/agencies/{id}/ghl-connection` | âœ… hecho en Phase 2 feature 5 (path conserva `ghl-connection` por compat con front) |
| `/admin/agencies/{id}/{brand,defaults,automation,social-templates}` | `/v1/admin/agencies/{id}/{brand,defaults,automation,social-templates}` | âœ… hecho en Phase 2 feature 6 |
| `/admin/agencies/{id}/music-tracks` (stub) | `/v1/admin/agencies/{id}/music` (CRUD real) | done in Phase 3 feature 2 (back docs/test + front CRUD/mock) |
| `/admin/agencies/{id}/reels/...` | `/v1/admin/agencies/{id}/reels/...` | âœ… hecho en Phase 2 feature 7 |
| `/mvp/gohighlevel/*` | `/v1/sessions/gohighlevel/*` | âœ… hecho en Phase 2 feature 2 |
| unversioned scripted render endpoint | `/v1/videos/scripted/render` | done in Phase 3 feature 1 |

Worker-only env vars renamed: `WEBHOOK_WORKER_COUNT` â†’ `WORKER_COUNT`,
`WEBHOOK_QUEUE_*` â†’ `WORKER_QUEUE_*`. âœ… hecho durante Phase 1; los
fallbacks legacy ya estÃ¡n removidos.

### Frontend lockstep â€” auditorÃ­a 2026-05-06

`grep` confirma que `4reels front/src/**` ya no llama a `/me`; feature 3
de Phase 3 cerro la rama `ApiSessionProvider` y dejo la identidad derivada
en el frontend desde admin-direct mode o SSO GoHighLevel.

`src/features/music/api.js` y `tests/support/mock-backend.js` ya usan
`/v1/admin/agencies/{id}/music`; feature 2 de Phase 3 cerrada el
2026-05-06. Feature 4 anadio el contrato automatizado para evitar nueva
deriva front<->back: `tests/integration/test_http_surface_contract.py`
extrae 37 llamadas `apiRequest(...)` y las compara contra rutas FastAPI.

### Cierre de Phase 3

Con `done` de las 4 features:

- Todos los endpoints HTTP del back estarÃ¡n bajo `/v1/...` (excepto
  `/health{,/live,/ready}`, intencionalmente sin versionar).
- Cada `apiRequest(...)` del front tendrÃ¡ un endpoint vivo en el back
  (verificado por `tests/integration/test_http_surface_contract.py`).
- `docs/http_surface.md` y `docs/openapi.json` quedan versionados como
  contrato canÃ³nico.

---

## Phase 4 — frontend/backend live contract hardening (DONE 2026-05-07)

Phase 4 cubrio el hardening del contrato live front<->back para que el
frontend pueda operar contra el backend real con autenticacion estricta y
payloads compatibles con Pydantic. Alcance: 2 features cross-repo, ambas
APPROVED en review (la feature 6 con un fix mecanico post-review trivial
sobre el placeholder `ingestionSourceId` en `test_http_surface_contract.py`).

| # | Feature | Repos | Estado |
|---|---|---|---|
| 5 | `frontend_admin_auth_lockstep` | back + front | done |
| 6 | `fix_frontend_backend_payload_contract` | back + front | done |

**Resultado neto:**

- `apps/api/admin_auth.py` acepta super-admin token (`ADMIN_API_TOKEN`)
  y agency-scoped JWT HS256 stateless emitido por
  `POST /v1/sessions/gohighlevel/session` (scope `agency`, issuer
  `4reels-back`); rechazo cross-tenant validado por
  `tests/integration/auth/test_admin_auth.py`.
- Frontend adjunta `Authorization: Bearer <token>` desde
  `src/lib/api/authToken.js`; admin-direct mode con input local oculto
  detras de `MVP_ADMIN_ENABLED` (sin secretos `VITE_*` en bundle).
- Pydantic estricto preservado en `/sources`, `/brand`, `/automation`,
  `/defaults`; el frontend envia exactamente los campos canonicos. Los
  7 toggles huerfanos de Automation + `platforms` se persisten en
  `defaults.settings` con keys namespaced (`automation.<key>`).
- Contrato cross-repo verde end-to-end: `tests/integration/test_http_surface_contract.py`
  (feature 4 de Phase 3) sigue blindando que cada `apiRequest(...)` del
  front matchea una ruta FastAPI viva.
- **Baseline: 434 tests passing** (Phase 2 baseline 394 + 22 feature 5 + 18 feature 6).

**Nota:** las "Phase 4 backlog candidates" listadas debajo eran el
backlog desde la perspectiva de Phase 3; ya cumplieron su funcion como
contenedor del scope que finalmente se ejecuto en Phase 4 (auth real +
payload contract). Cualquier item residual permanece como backlog para
una eventual Phase 5, **no aprobada**.

---

## Phase 4 backlog candidates (no aprobado)

Anotado para no perderlo; **no arrancar sin aprobaciÃ³n del usuario**.
Cuando se apruebe, mover a `feature_list.json` con el alcance exacto.

- **Multi-provider real en `provider_connections`.** Hoy solo hay
  `gohighlevel`; el schema (`provider` discriminator) lo permite.
  Validar la abstracciÃ³n aÃ±adiendo un segundo adaptador (Meta?
  Instagram via Graph API? otra integraciÃ³n CRM?).
- **Multi-source de ingestiÃ³n.** Hoy solo `wordpress`. Validar el
  `kind` discriminator de `ingestion_sources` con un segundo adapter
  (CSV upload? feed RSS? API REST de un CRM inmobiliario?).
- **Dashboard operativo de jobs/outbox.** Visibilidad de quÃ© pasa en
  el worker (jobs en `pending`/`processing`/`failed`, retries, outbox
  pendiente). Endpoint `/v1/admin/ops/*` + UI en el front.
- **Hardening de observabilidad.** MÃ©tricas Prometheus, traces
  OpenTelemetry, alertas sobre `outbox_events.status='failed'` y
  `jobs.status='failed' AND attempts >= max_attempts`.
- **MigraciÃ³n WEBHOOK_* â†’ INGEST_*.** Renombrar las env vars del
  webhook de WordPress (`WEBHOOK_PATH`, `WEBHOOK_HOST`,
  `WEBHOOK_SITE_SECRETS`, etc.) a `INGEST_*` para alinear con el
  rename de `WEBHOOK_WORKER_*` â†’ `WORKER_*` ya hecho en Phase 1.
  Cambio cosmÃ©tico pero alinea naming.
