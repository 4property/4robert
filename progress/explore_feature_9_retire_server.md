# Explore — Feature 9 `retire_wordpress_webhook_server`

> Mapeo de exploración (no código). Estado actual del legacy
> `services/transport/http/server.py` después de cerrar features 2-8 y lo
> que falta para que la feature 9 borre la god-class y deje
> `apps/api/app_factory.py` componiendo FastAPI directo.

---

## Inventario de `services/transport/http/server.py`

Archivo: `C:\Users\4pm\Desktop\4reels\4reels back\services\transport\http\server.py`

- **LoC totales hoy:** 1436 (medido con `wc -l`).
- Se compone de 2 clases vivas + 1 factory + 7 endpoints residuales + 1
  helper de uvicorn + 13 helpers privados al módulo.

### Clases / funciones vivas (no borradas por features 2-8)

1. `class WordPressWebhookApplication` — `server.py:210-485` (~275 LoC).
   - `__init__` (`server.py:211-273`) — construye `unit_of_work_factory`,
     `wordpress_source_admin_service`, `admin_access_policy`, atributos
     de webhook (path, headers, secrets), shutdown timeout, etc.
   - `start` (`server.py:275-374`) — `configure_logging` + `run_startup_checks` +
     `dispatcher.start()` + logs de "Webhook Runtime Started".
   - `stop` (`server.py:376-388`) — `dispatcher.stop()` + log "Webhook Runtime Stopped".
   - `wait_for_idle` (`server.py:390-391`).
   - `build_readiness_report` (`server.py:393-402`) — wrapper sobre
     `services.transport.http.operations.build_readiness_report`.
   - `get_ghl_connection_by_agency` (`server.py:404-406`).
   - `require_ghl_connection_for_agency` (`server.py:408-410`).
   - `get_reel_profile` (`server.py:412-414`).
   - `upsert_reel_profile` (`server.py:416-419`).
   - `delete_reel_profile` (`server.py:421-424`).
   - `apply_reel_profile_section` (`server.py:426-462`).
   - `get_agency` (`server.py:464-466`).
   - `list_sources_for_agency` (`server.py:468-470`).
   - `test_gohighlevel_connection` (`server.py:472-485`).

2. `class WordPressWebhookServer` — `server.py:487-550`.
   - `__init__` (`server.py:488-547`) — construye `WordPressWebhookApplication`
     y `create_fastapi_app(application=self.runtime)`.
   - `wait_for_idle` (`server.py:549-550`).

3. `def create_fastapi_app(*, application)` — `server.py:553-1041`.
   - Crea `FastAPI(...)` con `lifespan` que arranca/para el `application`.
   - Aplica `TrustedHostMiddleware`, `CORSMiddleware`,
     `install_openapi_examples`, `register_logging_middleware`.
   - Asigna `app.state.runtime = application` (`server.py:588`).
   - Registra **7 endpoints residuales** (los demás los moverá feature 9):
     - `GET /health/live` (`server.py:603-605`).
     - `GET /health` (`server.py:616-618`).
     - `GET /health/ready` (`server.py:620-622`).
     - `GET {admin_base}/wordpress-sources` (`server.py:624-655`)
       — `list_admin_wordpress_sources` (global). NO existe router
       reemplazo. La feature 4 solo movió las rutas per-agency.
     - `GET {admin_base}/wordpress-sources/{site_id}` (`server.py:657-714`)
       — `get_admin_wordpress_source`. Sin router reemplazo.
     - `PUT {admin_base}/wordpress-sources/{site_id}` (`server.py:716-860`)
       — `upsert_admin_wordpress_source`. Sin router reemplazo. Usa
       `_AdminWordPressSourceUpsertPayload` (`server.py:105-152`).
     - `GET {admin_base}/agencies/{agency_id}/reel-profile` (`server.py:870-901`)
       — `get_admin_agency_reel_profile`. Sin router reemplazo.
     - `PUT {admin_base}/agencies/{agency_id}/reel-profile` (`server.py:903-965`)
       — `upsert_admin_agency_reel_profile`. Sin router reemplazo. Usa
       `_AdminReelProfileUpsertPayload` (`server.py:155-207`).
     - `GET {admin_base}/agencies/{agency_id}/social-accounts` (`server.py:967-1039`)
       — `list_admin_agency_social_accounts`. Sin router reemplazo.

4. `def run_wordpress_webhook_server(...)` — `server.py:1044-1088`.
   - Entrypoint legacy: construye `WordPressWebhookServer` + invoca
     `uvicorn.run`. **No tiene call sites externos** hoy
     (`apps/api/main.py` ya construye su propio `uvicorn.run`).

### Helpers privados al módulo (vivos en server.py)

| Símbolo | Línea | Uso interno | ¿Vivo fuera de server.py? |
|---|---|---|---|
| `_AdminWordPressSourceUpsertPayload` (Pydantic) | 105-152 | `server.py:729` | No |
| `_AdminReelProfileUpsertPayload` (Pydantic) | 155-207 | `server.py:917` | No |
| `_get_runtime` | 1091-1092 | server.py | No (los routers usan UoW directo) |
| `_serialize_wordpress_source_details` | 1098-1117 | server.py:652, 713, 858 | **Sí** — `modules/tenancy/transport/http/admin_agencies_router.py:326` lo duplica (deuda de feature 3). |
| `_authorize_admin_request` | 1120-1124 | server.py | No (wrapper de 1 línea sobre `apps.api.admin_auth.authorize_admin_request`). Compat shim. |
| `_build_minimal_readiness_payload` | 1127-1131 | server.py:613 | No |
| `_build_acceptance_error_details` | 1134-1147 | NINGUNO interno hoy | No (huérfano tras features 4-7) |
| `_get_request_id` | 1150-1154 | server.py:642, 705, 737, 825, 837, 1220 | No |
| `_log_webhook_acceptance_failure` | 1157-1207 | NINGUNO interno hoy | No (huérfano) |
| `_log_admin_failure` | 1210-1259 | server.py:677, 756, 773, 790, 807 | No (los routers nuevos no lo usan) |
| `_resolve_allowed_hosts` | 1262-1283 | server.py:291, 576 | No |
| `_should_enable_docs` | 1286-1289 | server.py:565 | No |
| `_is_local_docs_host` | 1292-1301 | server.py:1289 | No |
| `_normalise_allowed_host` | 1304-1317 | server.py:1275, 1321 | No |
| `_looks_like_hostname` | 1320-1328 | server.py:1268 | No |
| `_parse_content_length` | 1331-1338 | NINGUNO interno hoy | No (`modules/ingestion/.../wordpress_webhook_router.py:380` y `modules/rendering/.../scripted_router.py:220` redefinen su propia copia) |
| `_extract_property_id` | 1341-1350 | NINGUNO interno hoy | No (`modules/ingestion/.../wordpress_webhook_router.py:390` redefine) |
| `_get_header_value` | 1353-1358 | NINGUNO interno hoy | No (`modules/ingestion/.../wordpress_webhook_router.py:402` redefine) |
| `_parse_webhook_payload` | 1361-1363 | NINGUNO interno hoy | No (`modules/ingestion/.../wordpress_webhook_router.py:410` redefine) |
| `_parse_json_object_payload` | 1365-1383 | server.py:1362 + NINGUNO externo hoy | No (`modules/rendering/.../scripted_router.py:230` redefine) |
| `_resolve_site_id` | 1386-1411 | NINGUNO interno hoy | No (`modules/ingestion/.../wordpress_webhook_router.py:431` redefine) |
| `_hostname_from_value` | 1414-1427 | server.py:1389, 1393 | No |

**Conclusión:** todos los helpers privados (excepto
`_serialize_wordpress_source_details`, ya duplicado en tenancy router)
mueren con `server.py`. No hay nada que reubicar fuera del propio
borrado.

### Imports al tope (`server.py:1-97`) y su estado tras features 2-8

| Import | Línea | ¿Sigue justificado? |
|---|---|---|
| `json`, `logging`, `secrets`, `time`, `urllib.parse.urlparse`, `pathlib.Path`, `typing.Any`, `contextlib.asynccontextmanager`, `dataclasses.dataclass` | 3-11 | `secrets` y `time` están **muertos** (no se usan). `dataclass` también muerto. El resto se usa (`json`, `logging`, `urllib`, `Path`, `Any`, `asynccontextmanager`). Sin embargo, todo desaparece con el archivo. |
| `fastapi.FastAPI`, `Request` | 13 | Se usan en `create_fastapi_app`. |
| `fastapi.middleware.cors.CORSMiddleware` | 14 | Usado. |
| `fastapi.responses.JSONResponse` | 15 | Usado. |
| `pydantic.BaseModel, ConfigDict, Field` | 16 | Usado por `_AdminWordPressSourceUpsertPayload` / `_AdminReelProfileUpsertPayload`. |
| `starlette.middleware.trustedhost.TrustedHostMiddleware` | 17 | Usado. |
| `application.admin.UpsertWordPressSourceRequest, WordPressSourceAdminService` | 19 | Usado por `WordPressWebhookApplication.__init__` (246) y handler PUT (740). El servicio legacy `application/admin/wordpress_source_management.py` solo lo importa server.py — ver §"Otros punteros legacy". |
| `application.bootstrap.runtime.build_default_job_dispatcher, build_runtime_unit_of_work_factory` | 20-23 | `build_default_job_dispatcher` solo lo usa `WordPressWebhookServer.__init__` (516). `build_runtime_unit_of_work_factory` lo usa `WordPressWebhookApplication.__init__` (242). Mueren con el archivo si ningún otro callsite los necesita (verificar). |
| `application.pipeline.interfaces.JobDispatcher` | 24 | Usado en typing. Cuando server.py muere, `JobDispatcher` deja de tener importadores en server.py. |
| `settings.*` (~38 símbolos) | 25-61 | Casi todos solo los usa este archivo. `SOCIAL_PUBLISHING_DEFAULT_PLATFORMS` está importado pero **no se usa** dentro de server.py — import muerto. |
| `core.errors.{ApplicationError, DependencyNotInstalledError, ResourceNotFoundError, ValidationError, extract_error_details}` | 62-68 | Todos usados internamente. Mueren con el archivo. |
| `core.logging.{configure_logging, format_console_block, format_context_line, format_detail_line, log_persistent_event, resolve_log_directory}` | 69-76 | Usados. Su shim de Phase 1 vive en `core/logging.py`; tras feature 9 quedará sin call sites desde transport (lo seguirá usando `apps/api/main.py` que importa `shared.observability.{configure_logging, format_console_block, ...}` — ya migrados). |
| `apps.api.admin_auth.{AdminAccessPolicy as _AdminAccessPolicy, authorize_admin_request as _authorize_admin_request_helper, extract_bearer_token, format_client}` | 77-82 | Compat shim. `extract_bearer_token` solo aparece importado pero no se llama localmente — re-export muerto del compat shim. |
| `apps.api.error_handlers.json_error as _json_error` | 83 | Usado en server.py. |
| `apps.api.logging_middleware.*` | 84-92 | `register_logging_middleware` se usa en línea 601. Los otros (`DEFAULT_SENSITIVE_*`, `decode_body_for_logging`, `extract_response_body`, `rebuild_request_with_body`, `sanitize_headers_for_logging`) **se importan como re-exports del compat shim** (cierre feature 1) pero no se llaman dentro de server.py. |
| `services.transport.http.operations.{build_readiness_report, run_startup_checks}` | 93 | `build_readiness_report` también lo usa `apps/api/main.py:81`; `run_startup_checks` solo lo usa server.py. |
| `services.transport.http.openapi_docs.{OpenApiDocsConfig, install_openapi_examples}` | 94 | Solo lo usa server.py. |
| `services.transport.http.uvicorn_protocols.VerboseAutoHTTPProtocol` | 95 | Solo lo usa `run_wordpress_webhook_server` (1080). Tras borrar server.py queda huérfano. |
| `services.publishing.social_delivery.gohighlevel_client.GoHighLevelClient` | 96 | Solo lo usa `WordPressWebhookApplication.test_gohighlevel_connection` (473). |
| `services.publishing.social_delivery.gohighlevel_social_service.GoHighLevelSocialService` | 97 | Igual: solo lo usa `test_gohighlevel_connection` (479). El use case `probe_provider_connection` (módulo publishing) ya tiene su propio camino al cliente legacy — verificar. |

### `__all__` (`server.py:1430-1435`)

`["WordPressWebhookApplication", "WordPressWebhookServer", "create_fastapi_app", "run_wordpress_webhook_server"]`

Ningún import externo usa `create_fastapi_app` o `run_wordpress_webhook_server`
salvo el test `tests/integration/test_http_transport.py:54` (ver §"Tests
afectados").

---

## Call sites externos de `WordPressWebhookServer` / `WordPressWebhookApplication`

Búsqueda con `Grep` sobre todo el árbol bajo
`apps/`, `modules/`, `shared/`, `tests/`, `services/`. Los hits en
`progress/`, `feature_list.json`, `docs/`, `REFACTOR_STATUS.md`,
`.claude/agents/leader.md` son comentarios — no afectan ejecución.

### Hits ejecutables

1. **`apps/api/app_factory.py:96`** — `from services.transport.http.server import WordPressWebhookServer`.
   - **`apps/api/app_factory.py:109-134`** — instancia `WordPressWebhookServer(...)` con todos los parámetros del runtime.
   - **`apps/api/app_factory.py:135-222`** — sobre `server.app` registra los 12 routers nuevos + un `register_error_handlers(server.app)` final.
   - **`apps/api/app_factory.py:144, 150, 156, 162, 168, 174, 180, 186, 192`** — pasa `server.runtime.admin_access_policy` a cada `create_*_router`.
   - **`apps/api/app_factory.py:220`** — pasa `server.runtime.dispatcher.is_accepting_jobs` al webhook router.
   - **`apps/api/main.py:116, 122, 130`** — recibe el `server` retornado por `build_api_app` y lee `server.runtime.path` (122) + `server.app` (130).
   - **Reemplazo propuesto:** `build_api_app()` debe (a) instanciar la `FastAPI()` directamente; (b) crear in-line el `unit_of_work_factory`; (c) construir el `AdminAccessPolicy` localmente desde los settings (sin pasar por `WordPressWebhookApplication`); (d) calcular `allowed_hosts` con un helper local (replicar `_resolve_allowed_hosts`/`_normalise_allowed_host`/`_looks_like_hostname` directamente en `apps/api/app_factory.py` o sacarlos a `apps/api/host_filter.py`); (e) montar `TrustedHostMiddleware`, `CORSMiddleware`, `register_logging_middleware`, `register_error_handlers`, `install_openapi_examples` (o su sucesor en `apps/api/openapi_docs.py`); (f) registrar los 12 routers nuevos + uno nuevo para los endpoints residuales (`/health*`, `/wordpress-sources*`, `/agencies/{id}/reel-profile`, `/agencies/{id}/social-accounts`); (g) montar `lifespan` que arranca/detiene un dispatcher (hoy `_NoopDispatcher`, ver §`_NoopDispatcher`); (h) devolver el `app` desnudo (no un wrapper). `apps/api/main.py` debe reemplazar `server.runtime.path` por leer `WEBHOOK_PATH` directo del settings y `server.app` por el `app` devuelto por `build_api_app`.

2. **`tests/integration/test_http_transport.py:54`** — `from services.transport.http.server import WordPressWebhookApplication, create_fastapi_app`.
   - **`tests/integration/test_http_transport.py:131-151`** — el helper `_build_client` instancia `WordPressWebhookApplication(...)`, monkeypatchea `start`/`stop`/`build_readiness_report`, y luego llama `app = create_fastapi_app(application=runtime)`.
   - **`tests/integration/test_http_transport.py:152-227`** — sobre ese `app` registra los routers nuevos y `register_error_handlers`.
   - **Reemplazo propuesto:** reescribir `_build_client` para que invoque `apps.api.app_factory.build_api_app(workspace_dir=..., database_locator=...)` y devuelva un `TestClient(app)`. La inyección de configuraciones de test (`security_disabled=True`, `enable_docs=False`, `site_secrets={}`, `admin_api_disable_auth_for_testing=...`, `gohighlevel_app_shared_secret=...`) requiere que `build_api_app` acepte esos overrides explícitamente o que el test los inyecte vía monkeypatch sobre los settings (preferible la primera: añadir kwargs opcionales a `build_api_app`).

3. **Comentarios y docs (no ejecutables, no requieren cambio para feature 9):**
   - `feature_list.json:25, 29, 161, 162, 167, 224` (descripción del backlog).
   - `docs/phase_2_operating_rules.md:39, 50` (regla de borrado legacy).
   - `REFACTOR_STATUS.md:196`.
   - `.claude/agents/leader.md:46`.
   - `progress/explore_router_*.md`, `progress/impl_*.md`, `progress/review_*.md`, `progress/history.md` — bitácora histórica.

---

## Estado de `apps/api/app_factory.py`

Archivo: `C:\Users\4pm\Desktop\4reels\4reels back\apps\api\app_factory.py` (227 LoC).

### Cómo construye la app HOY

1. Importa `WordPressWebhookServer` **dentro de la función** (`app_factory.py:96`) — import diferido para evitar coste de import al cargar el módulo.
2. Resuelve `workspace_dir` (98-102) y `database_locator` (103) y construye `unit_of_work_factory` (104-107) como lambda sobre `DatabaseUnitOfWork`.
3. Instancia `WordPressWebhookServer(resolved_workspace, dispatcher=_NoopDispatcher(), ...)` (`app_factory.py:109-134`).
4. Sobre `server.app` (la `FastAPI` construida por `create_fastapi_app`), llama `include_router(...)` 12 veces (`app_factory.py:135-222`):
   - `create_sessions_router` (publishing)
   - `create_admin_agencies_router` (tenancy)
   - `create_connections_router` (publishing)
   - `create_sources_router` (ingestion)
   - `create_brand_router`, `create_defaults_router`, `create_automation_router`, `create_social_templates_router`, `create_music_router` (configuration)
   - `create_admin_reels_router` (reels)
   - `create_scripted_router` (rendering)
   - `create_wordpress_webhook_router` (ingestion)
5. `register_error_handlers(server.app)` (`app_factory.py:223`).
6. `return server` (`app_factory.py:224`) — `apps/api/main.py:116` recibe el `server` y usa `server.runtime.path` + `server.app`.

### Routers de `modules/<bc>/` ya registrados

Listado completo (path completo + función `include_router(...)` + línea):

| Router (path completo) | Función registrada | Línea |
|---|---|---|
| `modules/publishing/transport/http/sessions_router.py` | `create_sessions_router(unit_of_work_factory=..., shared_secret=GO_HIGH_LEVEL_APP_SHARED_SECRET)` | `app_factory.py:135-140` |
| `modules/tenancy/transport/http/admin_agencies_router.py` | `create_admin_agencies_router(unit_of_work_factory=..., admin_access_policy=server.runtime.admin_access_policy)` | `app_factory.py:141-146` |
| `modules/publishing/transport/http/connections_router.py` | `create_connections_router(unit_of_work_factory=..., admin_access_policy=server.runtime.admin_access_policy)` | `app_factory.py:147-152` |
| `modules/ingestion/transport/http/sources_router.py` | `create_sources_router(unit_of_work_factory=..., admin_access_policy=server.runtime.admin_access_policy)` | `app_factory.py:153-158` |
| `modules/configuration/transport/http/brand_router.py` | `create_brand_router(...)` | `app_factory.py:159-164` |
| `modules/configuration/transport/http/defaults_router.py` | `create_defaults_router(...)` | `app_factory.py:165-170` |
| `modules/configuration/transport/http/automation_router.py` | `create_automation_router(...)` | `app_factory.py:171-176` |
| `modules/configuration/transport/http/social_templates_router.py` | `create_social_templates_router(...)` | `app_factory.py:177-182` |
| `modules/configuration/transport/http/music_router.py` | `create_music_router(...)` | `app_factory.py:183-188` |
| `modules/reels/transport/http/admin_reels_router.py` | `create_admin_reels_router(unit_of_work_factory=..., admin_access_policy=..., workspace_dir=..., job_max_attempts=WORKER_JOB_MAX_ATTEMPTS, default_platforms=tuple(SOCIAL_PUBLISHING_DEFAULT_PLATFORMS))` | `app_factory.py:189-197` |
| `modules/rendering/transport/http/scripted_router.py` | `create_scripted_router(unit_of_work_factory=..., job_max_attempts=WORKER_JOB_MAX_ATTEMPTS, max_payload_bytes=WEBHOOK_MAX_PAYLOAD_BYTES)` | `app_factory.py:198-204` |
| `modules/ingestion/transport/http/wordpress_webhook_router.py` | `create_wordpress_webhook_router(unit_of_work_factory=..., settings=WordPressWebhookSettings(...), job_max_attempts=WORKER_JOB_MAX_ATTEMPTS, dispatcher_state=server.runtime.dispatcher.is_accepting_jobs)` | `app_factory.py:205-222` |

### `_NoopDispatcher` (`app_factory.py:67-87`)

- Vive **aquí**, en `apps/api/app_factory.py`, NO en `services/transport/http/server.py`.
- Implementa la interfaz `JobDispatcher` mínima (`start`, `stop`, `wait_for_idle`, `is_accepting_jobs`, `count_active_jobs`) sin spawnear workers — el proceso API delega el dispatcher al worker.
- `app_factory.py:111` lo pasa al `WordPressWebhookServer(...)` como `dispatcher=_NoopDispatcher()`.
- `app_factory.py:220` lee `server.runtime.dispatcher.is_accepting_jobs` para inyectar `dispatcher_state` en el webhook router.
- **Decisión: `_NoopDispatcher` se queda en feature 9.** La feature 16
  (`worker_real_use_cases_and_drop_noop_dispatcher`) lo elimina cuando
  el worker ejecute los use cases reales y la API deje de necesitar
  exponer `dispatcher_state`. Feature 9 solo tiene que reubicar **la
  responsabilidad de instanciarlo y conectarlo al webhook router** —
  pero NO borrarlo, porque el webhook router todavía depende del
  callable `dispatcher_state` (que viene del `is_accepting_jobs` del
  Noop). El plan: `app_factory.py` mantiene `_NoopDispatcher`,
  instancia uno local (`dispatcher = _NoopDispatcher()`), llama
  `dispatcher.start()` en el `lifespan` del FastAPI, y pasa
  `dispatcher.is_accepting_jobs` al webhook router. Así feature 16
  solo tiene que limpiar el dispatcher cuando los use cases reales lo
  reemplacen.

### Error handlers / middlewares / range responses / admin auth — dónde viven

| Cross-cutting | Helper canónico (post feature 1) | Cómo se monta hoy |
|---|---|---|
| Error handlers (`ApplicationError → JSON`) | `apps/api/error_handlers.py` (`register_error_handlers`, `json_error`) | `app_factory.py:223` llama `register_error_handlers(server.app)`. Tras feature 9 se llama sobre `app` directo. |
| Logging middleware (`persist_http_traffic`, request-id seeding) | `apps/api/logging_middleware.py` (`register_logging_middleware`) | Hoy lo monta `services.transport.http.server.create_fastapi_app:601`. Tras feature 9 se monta directo en `app_factory.build_api_app()`. |
| Admin auth (`AdminAccessPolicy`, `authorize_admin_request`, `extract_bearer_token`, `format_client`) | `apps/api/admin_auth.py` | Hoy server.py `_AdminAccessPolicy` lo construye dentro de `WordPressWebhookApplication.__init__` (server.py:263-268); los routers nuevos la reciben vía `server.runtime.admin_access_policy` (`app_factory.py:144, 150, 156, ...`). Tras feature 9 `app_factory` la construye localmente desde settings y la pasa a cada router. |
| Range responses (multipart/single-range) | `apps/api/range_response.py` (`build_range_response`) | Lo usa `modules/reels/transport/http/admin_reels_router.py` directamente; server.py NO lo invoca tras feature 7. |
| OpenAPI examples (Postman docs) | `services/transport/http/openapi_docs.py` (sigue legacy) | Lo monta server.py:589 con `install_openapi_examples`. Tras feature 9 hay que decidir: borrarlo (recomendado, ver §"Estado de openapi_docs.py") o moverlo a `apps/api/openapi_docs.py`. |
| TrustedHost / CORS middleware | inline en `server.py:577-587` | Tras feature 9 `app_factory` los monta directo. |
| Health endpoints (`/health/live`, `/health`, `/health/ready`) | inline en `server.py:603-622` | Necesitan una nueva ubicación: o un router en `apps/api/health_router.py`, o inline en `app_factory.build_api_app()`. **Recomendación: `apps/api/health_router.py`** (cohesivo con el resto de helpers de la API). |

---

## Estado de `services/transport/http/openapi_docs.py`

Archivo: `C:\Users\4pm\Desktop\4reels\4reels back\services\transport\http\openapi_docs.py` (644 LoC).

### ¿Sigue vivo?

Sí, pero **solo lo usa `services/transport/http/server.py:94`**. Búsqueda
exhaustiva (`Grep` sobre todo el árbol):

- `services/transport/http/server.py:94` → `from services.transport.http.openapi_docs import OpenApiDocsConfig, install_openapi_examples`
- `services/transport/http/server.py:589-600` → `install_openapi_examples(app, config=OpenApiDocsConfig(...))`

Ningún router en `modules/<bc>/transport/` lo importa. Ningún test, ni
`apps/`, ni `shared/`.

### Decisión propuesta

**Borrar el archivo entero junto con server.py en feature 9.** Razón:

- Solo decora 4 endpoints: `/health/live`, `/health/ready`, `POST {webhook_path}` (más tags genéricos en `_merge_tags`). El handler scripted-render (`_decorate_scripted_render_operation`, mencionado en `docs/phase_2_operating_rules.md:275-276` como código del rango 359-454) **YA NO EXISTE** en el archivo actual — feature 8 lo borró. El archivo hoy solo tiene `_decorate_health_operations` y `_decorate_webhook_operation`.
- El webhook router nuevo (`modules/ingestion/transport/http/wordpress_webhook_router.py`) ya tiene su propio decorator de OpenAPI (Pydantic + decoradores FastAPI) — basta con dejar que FastAPI genere el schema natural sin la sobreescritura del Postman example.
- Los health endpoints, cuando se muevan a `apps/api/health_router.py`, pueden documentarse con `summary`/`description` directos del decorador FastAPI.
- El "Postman example" (carga el JSON del Postman collection del workspace) es valor marginal: el desarrollador puede mirar el Postman directo.

**Si el leader prefiere preservar la enriquecida OpenAPI:** mover el
contenido a `apps/api/openapi_docs.py` o a
`modules/ingestion/transport/openapi/wordpress_webhook_examples.py`. La
firma `install_openapi_examples(app, config=OpenApiDocsConfig(...))` se
mantendría idéntica.

---

## Tests afectados

### Tests que importan `WordPressWebhookServer` / `WordPressWebhookApplication` o `services.transport.http.server`

Búsqueda exhaustiva con `Grep` sobre `tests/`:

1. **`tests/integration/test_http_transport.py`** — único archivo de tests con dependencia ejecutable.
   - Línea 54: `from services.transport.http.server import WordPressWebhookApplication, create_fastapi_app`.
   - Línea 131-151: `runtime = WordPressWebhookApplication(...)` + `app = create_fastapi_app(application=runtime)`.
   - Líneas 27, 131-227: el helper `_build_client` también re-importa `WordPressSourceStore` (legacy de `repositories/stores/`) en línea 27 — eso lo limpia feature 17, no es problema de feature 9.
   - **Acción para feature 9:** reescribir `_build_client(...)` para que invoque `apps.api.app_factory.build_api_app(...)` (post-refactor) en vez de instanciar el legacy. Casos de test cubiertos (helper recibe overrides):
     - `dispatcher` (custom `_RecordingDispatcher`).
     - `readiness` (no se usa más tras la limpieza — el endpoint `/health` lo construye `app_factory` directo).
     - `admin_api_token` / `admin_api_disable_auth_for_testing` / `gohighlevel_app_shared_secret` / `webhook_auto_provision_unknown_sites_for_testing`.
   - **Recomendación:** `build_api_app()` añade kwargs opcionales para esos overrides (override de settings vía argumentos), o el test usa `monkeypatch.setattr(settings, ...)` para inyectarlos. Decisión final del leader.

2. Ningún otro test bajo `tests/unit/` o `tests/integration/<bc>/` importa de `services.transport.http.server` (verificado vía `Grep`).

3. Los tests `tests/integration/<bc>/test_*.py` creados por features 2-8 ya construyen sus apps con `FastAPI()` desnudo + `include_router(...)` y NO dependen de la god-class. Pueden quedarse intactos.

---

## Otros punteros legacy

### Re-exports de `services/`

- `services/__init__.py` — no se inspeccionó como crítico (no hay re-export de la god-class). El proyecto importa siempre con paths explícitos `services.transport.http.*`.
- `services/transport/__init__.py` (`services/transport/__init__.py:1-12`) — re-exporta `SiteStorageLayout`, `resolve_site_storage_layout`, `safe_site_dirname` desde `services.media.site_storage`. **NO** re-exporta `WordPressWebhookServer` ni `WordPressWebhookApplication`. Seguro de tocar.
- `services/transport/http/__init__.py` (`services/transport/http/__init__.py:1-11`) — re-exporta los mismos símbolos de `site_storage`. Tampoco re-exporta la god-class. Seguro.

**Conclusión:** no hay side-effect de import que rompa al borrar `server.py`.

### `application/`, `core/`, `domain/` que importen `services/transport/http/server.py`

Búsqueda con `Grep` sobre `application/`, `core/`, `domain/`,
`repositories/`, `shared/`: ningún archivo bajo esas carpetas importa
`services.transport.http.server`. Confirma la regla de capas (transport
nunca lo importa nada interior).

### Otros consumidores externos del directorio `services/transport/http/`

- **`apps/api/main.py:81`** — `from services.transport.http.operations import build_readiness_report`. Sigue viva: la usa el `--check`. **NO la toca feature 9** (el archivo `operations.py` se queda; lo borrará/migrará feature 18 cuando disuelva `services/`).
- `services/transport/http/uvicorn_protocols.py` (276 LoC) — solo lo usa `server.py:1080` (`run_wordpress_webhook_server` que está muerto). Tras feature 9 queda **huérfano**: se puede borrar también o dejar a feature 18.
- `services/transport/http/operations.py` (466 LoC) — viva, la consume `apps/api/main.py:81` para `--check`. Feature 18 la disuelve. Su contenido (readiness report) eventualmente migra a `apps/api/readiness.py` o similar (Phase 3).

### `application/admin/wordpress_source_management.py` (`WordPressSourceAdminService`)

- Solo lo importa `services/transport/http/server.py:19`. Sin ese
  import el servicio queda huérfano. **Acción feature 9:** una vez
  borrado server.py, eliminar `application/admin/wordpress_source_management.py`
  y `application/admin/__init__.py` si el servicio era el único símbolo
  re-exportado. La lógica del global `/wordpress-sources/*` debe
  reimplementarse como un nuevo router (ver §"Plan recomendado") usando
  `uow.ingestion.sources` directo. Esto es coherente con
  `docs/phase_2_operating_rules.md:165-167` (la regla "Borra
  `WordPressSourceAdminService` legacy si esta feature deja sin call
  sites" — feature 4 lo conservó porque server.py todavía lo usaba).

### Métodos de `WordPressWebhookApplication` que dejan de tener call sites tras feature 9

- `start`, `stop`, `wait_for_idle`, `build_readiness_report` —
  desaparecen al desaparecer la clase. El lifecycle del dispatcher pasa
  al `lifespan` del FastAPI nuevo.
- `get_ghl_connection_by_agency`, `require_ghl_connection_for_agency`,
  `get_reel_profile`, `upsert_reel_profile`, `delete_reel_profile`,
  `apply_reel_profile_section`, `get_agency`, `list_sources_for_agency`,
  `test_gohighlevel_connection` — todos eran wrappers sobre el UoW
  legacy. Sus únicos call sites quedan dentro del propio server.py
  (`/social-accounts`, `/reel-profile`, `/wordpress-sources` global).
  Los nuevos routers que feature 9 cree deben llamar al UoW directo
  (`uow.publishing.connections.get_with_secrets(...)`,
  `uow.configuration.<section>`, `uow.ingestion.sources`,
  `uow.tenancy.agencies.get_by_id`).
- `test_gohighlevel_connection` (`server.py:472-485`) — su lógica
  (instanciar `GoHighLevelClient` + `GoHighLevelSocialService.list_accounts`)
  debe reubicarse en el nuevo router de social-accounts (o en un use
  case `inspect_agency_social_accounts` si el leader prefiere). Es 14
  LoC que mueren con la clase.

---

## Plan recomendado feature 9 paso a paso

> Una sola feature, una sola sesión. Sin commits intermedios. Modo serial estricto (Phase 2 §1).

### Paso 1 — Crear los routers/handlers para los endpoints residuales

Los 7 endpoints que server.py todavía sirve hoy NO tienen reemplazo en
`modules/<bc>/`. Feature 9 debe crearlos antes de borrar server.py.

1. **Health router** — `apps/api/health_router.py` con `/health/live`, `/health`, `/health/ready`.
   - Para `/health` y `/health/ready` necesita reportar `dispatcher_accepting_jobs`. Como el dispatcher pasa a vivir en el `lifespan`, exponer un callable `() -> bool` desde `app_factory` y cerrar sobre él (mismo patrón que `dispatcher_state` en el webhook router).
   - El "readiness report" completo (lo que hoy es `WordPressWebhookApplication.build_readiness_report`) lo sigue construyendo `services.transport.http.operations.build_readiness_report` — el endpoint puede llamarlo directo. Migrarlo a `apps/api/readiness.py` no es alcance de feature 9 (lo hace feature 18).

2. **Wordpress sources global router** — `modules/ingestion/transport/http/wordpress_sources_router.py` con:
   - `GET /v1/admin/wordpress-sources` (list global).
   - `GET /v1/admin/wordpress-sources/{site_id}` (get by site_id).
   - `PUT /v1/admin/wordpress-sources/{site_id}` (upsert + auto-create agency si falta).
   - Sustituir `WordPressSourceAdminService` por use cases nuevos
     (`list_global_wordpress_sources`, `inspect_wordpress_source_by_site_id`,
     `provision_wordpress_source`) que escriban directo al UoW
     (`uow.tenancy.agencies`, `uow.ingestion.sources`).
   - Borrar `application/admin/wordpress_source_management.py` y
     `application/admin/__init__.py` cuando no quede call site.

3. **Reel profile raw router** — decisión del leader entre dos opciones:
   - **(A)** `modules/configuration/transport/http/reel_profile_router.py` con `GET`/`PUT /v1/admin/agencies/{id}/reel-profile`. Ahí hay que decidir si seguir leyendo/escribiendo el `reel_profiles` legacy (que `repositories/postgres/uow.py` aún expone) o migrar la lectura agregando los 5 sub-aggregates (`brand`, `defaults`, `automation`, `social_templates`, `music`) y devolver una vista compuesta. **La lectura agregada NO existe hoy**: el endpoint actual lee `reel_profiles` (legacy via `runtime.get_reel_profile`).
   - **(B)** Borrar el endpoint completamente. El frontend ya migró a las rutas per-section (`/brand`, `/defaults`, ...) en feature 6. Si "Reel settings" tab del admin frontend dejó de usar `/reel-profile`, este endpoint es obsoleto. **Verificar con el leader/frontend antes.**
   - **Recomendación si está en duda:** opción (A) con la lectura agregada vía UoW (no `ReelProfileStore`). Esto deja a feature 17 (`retire_property_store_and_repositories_stores`) borrar `ReelProfileStore` de un disparo.

4. **Social-accounts router** — `modules/publishing/transport/http/social_accounts_router.py` con:
   - `GET /v1/admin/agencies/{id}/social-accounts`.
   - El handler resuelve la conexión GHL vía `uow.publishing.connections.get_with_secrets(agency_id, "gohighlevel")` y llama `GoHighLevelClient.list_accounts(...)` directamente. La lógica `test_gohighlevel_connection` muere con el método del runtime.
   - Los clientes `GoHighLevelClient` y `GoHighLevelSocialService` viven hoy en `services/publishing/social_delivery/`. Feature 9 NO los toca — los disuelve Phase 3 (no hay feature concreta de Phase 2). El nuevo router los importa con `from services.publishing.social_delivery.gohighlevel_client import GoHighLevelClient` exactamente como hoy.

### Paso 2 — Refactorizar `apps/api/app_factory.py`

1. Eliminar el import diferido `from services.transport.http.server import WordPressWebhookServer` (línea 96).
2. Construir `app = FastAPI(title=..., docs_url=..., openapi_url=..., lifespan=lifespan)` directo.
3. Construir `admin_access_policy = AdminAccessPolicy(enabled=ADMIN_API_ENABLED, base_path=ADMIN_API_BASE_PATH, bearer_token=ADMIN_API_TOKEN, disable_auth_for_testing=ADMIN_API_DISABLE_AUTH_FOR_TESTING)` directo en `app_factory`.
4. Reubicar los helpers de host/docs (`_resolve_allowed_hosts`, `_normalise_allowed_host`, `_looks_like_hostname`, `_should_enable_docs`, `_is_local_docs_host`) a `apps/api/host_filter.py` (helper privado del paquete API).
5. Crear el `lifespan` que (a) instancia `_NoopDispatcher()`, (b) hace `dispatcher.start()`, (c) `yield`, (d) `dispatcher.stop()`. Inyectar `dispatcher.is_accepting_jobs` en el webhook router y health router via closure o `app.state`.
6. Montar middlewares: `TrustedHostMiddleware`, `CORSMiddleware`, `register_logging_middleware`, `register_error_handlers`, OpenAPI examples (si se conservan) o eliminarlas.
7. `app.include_router(...)` para los 12 routers existentes + los 4 nuevos del paso 1 (health, wordpress-sources global, reel-profile raw, social-accounts).
8. Devolver `app` directo (no un wrapper `server`).

### Paso 3 — Refactorizar `apps/api/main.py`

- `apps/api/main.py:114-130`: cambiar `server = build_api_app(...)` a `app = build_api_app(...)`. Reemplazar `server.runtime.path` (línea 122) por `WEBHOOK_PATH` desde `settings`. Reemplazar `server.app` (130) por `app`.
- `apps/api/main.py:81` (`from services.transport.http.operations import build_readiness_report`) — **NO tocar**. Se queda hasta feature 18.

### Paso 4 — Borrar `services/transport/http/server.py`

- Después de pasos 1-3, borrar el archivo completo.
- Borrar también `services/transport/http/openapi_docs.py` (si la decisión es eliminar — opción recomendada).
- `services/transport/http/uvicorn_protocols.py` queda huérfano: se puede borrar en este mismo PR o dejarlo para feature 18. **Recomendación: borrarlo** para alinearse con la regla §2 de `phase_2_operating_rules` ("Borrar todo lo legacy a medida que se mueve").
- `services/transport/http/__init__.py` y `services/transport/__init__.py` solo re-exportan `site_storage` — dejarlos hasta feature 18.

### Paso 5 — Borrar `application/admin/`

- `application/admin/wordpress_source_management.py` (~500 LoC) y
  `application/admin/__init__.py` quedan sin call sites tras paso 1.
- Borrarlos en este mismo PR (regla §2).

### Paso 6 — Adaptar `tests/integration/test_http_transport.py`

- Reescribir `_build_client` para usar `apps.api.app_factory.build_api_app(...)`.
- `from services.transport.http.server import ...` (línea 54) — eliminar.
- Verificar que los 18 tests del archivo siguen verdes contra los routers nuevos (incluyendo health, wordpress-sources, social-accounts, reel-profile raw).
- Mantener los nombres de los tests; mantener el contrato HTTP (mismos paths, mismas responses).

### Paso 7 — Verificación

- `./init.sh` verde.
- `pytest -q` verde (≥ 320 tests, baseline post-feature-7).
- `python -m apps.api --check` exit 0.
- `python -m apps.worker --check` exit 0.
- `Grep "WordPressWebhookServer\|WordPressWebhookApplication"` en
  `apps/`, `modules/`, `shared/`, `tests/` no retorna hits.
- `Grep "services.transport.http.server"` en
  `apps/`, `modules/`, `shared/`, `tests/` no retorna hits.

### Bloqueantes señalados

- **`_NoopDispatcher` se mantiene en feature 9.** No es bloqueante para
  9; lo elimina feature 16. El plan respeta el orden (16 viene después
  de 10-14 según `feature_list.json:17`).
- **Decisión `/reel-profile` raw (paso 1.3):** consultar al leader si
  borrar el endpoint o reescribirlo. Si el frontend admin ya no lo
  consume, opción B (borrar) es la limpia. Si lo sigue consumiendo,
  opción A (reescribir leyendo del UoW agregado).
- **Decisión `openapi_docs.py` (paso 4):** consultar al leader si
  preservar el "Postman example" enriquecido o aceptar el OpenAPI
  natural de FastAPI. Recomendación: borrar.
- **Lectura agregada del reel-profile legacy:** el endpoint actual lee
  `reel_profiles` vía `WordPressWebhookApplication.get_reel_profile`
  → `unit_of_work.reel_profile_store.get_by_agency_id(agency_id)`. Ese
  store legacy lo borra feature 17. Si feature 9 reescribe el endpoint
  para leer del UoW agregado de `configuration`, libera a feature 17 de
  cualquier dependencia. **No es bloqueante** pero es la opción
  recomendada.
- **`UpsertWordPressSourceRequest` / `WordPressSourceAdminService`:**
  paso 5. El borrado es seguro porque server.py es el único call site.

---

## Riesgos y preguntas abiertas

1. **`/v1/admin/agencies/{id}/reel-profile` raw — ¿se conserva o se borra?** Pregunta para el leader/frontend. Impacta el alcance de feature 9 y el trabajo a feature 17.
2. **`services/transport/http/openapi_docs.py` — ¿borrar o reubicar?** Recomendación: borrar (los Postman examples no aportan a producción y el OpenAPI natural de FastAPI ya cubre los endpoints). Si se reubica: a `apps/api/openapi_docs.py` o `modules/ingestion/transport/openapi/...`.
3. **`services/transport/http/uvicorn_protocols.py`** — queda huérfano tras borrar `run_wordpress_webhook_server`. Recomendación: borrarlo en feature 9. El `apps/api/main.py` actual NO lo usa (uvicorn.run sin protocolo custom — `apps/api/main.py:129-140`). Si se quiere preservar el comportamiento "VerboseAutoHTTPProtocol" para producción, hay que pasarlo explícitamente vía `uvicorn.run(..., http=VerboseAutoHTTPProtocol)`. **El estado actual de `apps/api/main.py` ya NO lo usa**, por lo que borrarlo es seguro respecto al runtime API actual.
4. **`apps/api/main.py:81` importa `services.transport.http.operations.build_readiness_report`.** Este import sobrevive feature 9. Es deuda explícita para feature 18.
5. **`application/bootstrap/runtime.{build_default_job_dispatcher, build_runtime_unit_of_work_factory}`** — solo los importa server.py. Tras feature 9 quedan huérfanos. Verificar otros call sites (un `Grep` mínimo basta) y borrarlos en feature 9 si no quedan callers — alinea con regla §2 ("Imports de `application/`, `core/`, `repositories/stores/` que dejan de tener call sites tras esta feature").
6. **Inyección de overrides en `build_api_app` para tests:** decidir si `build_api_app` admite kwargs (`security_disabled`, `admin_api_token`, etc.) o si los tests usan `monkeypatch.setattr(settings, ...)`. Decisión del leader.
7. **`AdminAccessPolicy` se construye en server.py hoy.** En feature 9 hay que decidir si pasa a `apps/api/admin_auth.build_admin_access_policy(settings)` (helper nuevo) o se construye inline en `app_factory.py`. Recomendación: helper nuevo para mantener `app_factory` ordenado.
8. **Side-effects de import:** ningún `__init__.py` re-exporta `WordPressWebhookServer`/`WordPressWebhookApplication`. El borrado del archivo no rompe ningún import implícito. Confirmado vía lectura de `services/__init__.py`, `services/transport/__init__.py`, `services/transport/http/__init__.py`.
9. **`core/logging.py` queda con menos call sites tras feature 9** — `apps/api/main.py` ya migró a `shared.observability.{configure_logging, ...}`. Solo `services/transport/http/server.py` y `application/...` siguen usándolo. Feature 9 reduce su superficie pero no lo borra; eso es alcance de feature 18.
