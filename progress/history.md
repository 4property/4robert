# Bitácora — sesiones anteriores

> Append-only. Cada cierre de sesión añade una entrada al final.
> Formato: `## YYYY-MM-DD — feature <id>: <name>`.

## Sesión cerrada — feature 1 (api_helpers_and_router_skeleton) — 2026-04-30

- Módulo: `apps/api/`. No toca schema.
- Archivos clave creados: `apps/api/admin_auth.py`, `apps/api/error_handlers.py`, `apps/api/logging_middleware.py`, `apps/api/range_response.py`.
- `services/transport/http/server.py` reducido a compat shim: re-exporta los helpers extraídos y `_authorize_admin_request` queda como wrapper de 1 línea sobre `apps.api.admin_auth.authorize_admin_request`. `persist_http_traffic` se monta vía `register_logging_middleware(app)`.
- `apps/api/app_factory.py` añade `register_error_handlers(server.app)` tras construir el server (mapeo `ApplicationError → JSON` con shape canónico).
- Tests añadidos: 30 en `tests/unit/apps_api/` (admin auth: 9, error handlers: 6, range response: 8, logging middleware: 7). Total `pytest -q`: 146 passed (baseline 116 + 30).
- Decisión no obvia: el shim re-exporta `register_error_handlers` desde `server.py:93` aunque no se invoca allí (solo en `app_factory.py:101`). Import muerto consciente; se limpiará al borrar server.py en feature 9.
- `python -m apps.api --check` y `python -m apps.worker --check` exit 0; `./init.sh` verde.
- Informe del implementer: `progress/impl_1_api_helpers_and_router_skeleton.md`.
- Review (APPROVED): `progress/review_1_api_helpers_and_router_skeleton.md`.

## Sesion cerrada - feature 2 (publishing_sessions_router) - 2026-04-30

- Modulo: `modules/publishing/`. No toca schema.
- Rutas `/v1/sessions/gohighlevel/{tokens,context,session,test}` extraidas desde `services/transport/http/server.py` a `modules/publishing/transport/http/sessions_router.py`.
- Payloads Pydantic movidos a `modules/publishing/transport/payloads/sessions.py`.
- Use cases creados/renombrados: `decode_session_context`, `list_provider_sessions`, `inspect_session_status`, `probe_provider_connection`.
- `apps/api/app_factory.py` registra el nuevo router con `shared.db.DatabaseUnitOfWork`; `server.py` ya no declara los handlers ni payloads inline de sesiones.
- Tests anadidos: `tests/integration/publishing/test_gohighlevel_session_router.py` y `tests/unit/publishing/test_session_use_cases.py`. Total `pytest -q`: 155 passed.
- Verificacion: `python -m apps.api --check` OK, `python -m apps.worker --check` OK, `init.sh` OK con 155 tests.
- Review (APPROVED): `progress/review_2_publishing_sessions_router.md`.

## Sesión cerrada — feature 3 (tenancy_admin_agencies_router) — 2026-04-30

# SesiÃ³n actual

> Este archivo se vacÃ­a al cerrar cada sesiÃ³n y se mueve a `history.md`.
> Mientras trabajas, **mantenlo actualizado en tiempo real**, no al final.

- **Feature en curso:** `3 - tenancy_admin_agencies_router`
- **Inicio:** `2026-04-30 17:12 Europe/Dublin`
- **Agente:** `Codex`
- **MÃ³dulo afectado:** `modules/tenancy/`
- **Â¿Toca schema?:** `No`

## Plan

- Extraer `/v1/admin/agencies` y `/v1/admin/agencies/{agency_id}` a `modules/tenancy/transport/http/admin_agencies_router.py`.
- Crear use cases descriptivos `register/list/inspect/reconfigure/decommission_agency`.
- Registrar el router en `apps/api/app_factory.py` y adaptarlo en `tests/integration/test_http_transport.py`.
- Borrar payloads/handlers/helpers legacy del bloque de agencies en `services/transport/http/server.py` sin tocar legacy aÃºn consumido por features 4-7.
- AÃ±adir tests unitarios e integraciÃ³n y volver a ejecutar checks.

## BitÃ¡cora

- 17:09 - LeÃ­dos `AGENTS.md`, `feature_list.json`, `progress/current.md`, `docs/phase_2_operating_rules.md` y `progress/explore_router_3_tenancy_admin_agencies.md`.
- 17:12 - `init.sh` no pudo ejecutarse por ausencia de Bash funcional en este entorno Windows; se reprodujeron sus checks equivalentes con PowerShell y `.venv\\Scripts\\python.exe`.
- 17:13 - Baseline verificado: `python -m apps.api --check`, `python -m apps.worker --check` y `pytest -q` verdes (`155 passed`).
- 17:15 - Inspeccionados `apps/api/app_factory.py`, `modules/publishing/transport/http/sessions_router.py`, `shared/db/uow.py`, `services/transport/http/server.py` y los repos tipados necesarios para hidratar `sources`, `ghl_connection` y `reel_profile`.
- 17:28 - Implementados los use cases `register_agency`, `list_agencies`, `inspect_agency`, `reconfigure_agency`, `decommission_agency` y el router `modules/tenancy/transport/http/admin_agencies_router.py` con payloads propios.
- 17:30 - Registrado el router en `apps/api/app_factory.py`, adaptado `tests/integration/test_http_transport.py` y eliminado de `services/transport/http/server.py` el bloque legacy especÃ­fico de `/v1/admin/agencies`.
- 17:32 - VerificaciÃ³n focalizada verde: `tests/unit/tenancy`, `tests/integration/tenancy/test_admin_agencies_router.py`, `tests/integration/test_http_transport.py` y `python -m apps.api --check`.
- 17:34 - VerificaciÃ³n global verde: `python -m pytest -q --no-header` (`168 passed`) y `python -m apps.worker --check`.

## PrÃ³ximo paso

- Pendiente solo el cierre administrativo/review del arnÃ©s antes de pasar la feature a `done`.

## Sesión cerrada — feature 4 (ingestion_routers) — 2026-04-30

# Sesión actual

> Este archivo se vacía al cerrar cada sesión y se mueve a `history.md`.
> Mientras trabajas, **mantenlo actualizado en tiempo real**, no al final.

- **Feature en curso:** 4 — ingestion_routers
- **Inicio:** 2026-04-30
- **Agente:** implementer (general-purpose)
- **Módulo afectado:** modules/ingestion/
- **¿Toca schema?:** no

## Plan

- Mover `services/transport/http/security.py` (HMAC helpers) a `shared/http/webhook_signature.py`
  preservando la fórmula byte-a-byte (incluye `location_id` y `access_token` con defaults `""`).
- Crear use cases en `modules/ingestion/application/use_cases/`:
  `register_ingestion_source`, `list_ingestion_sources`, `inspect_ingestion_source`,
  `reconfigure_ingestion_source`, `decommission_ingestion_source`, `ingest_wordpress_property`.
- Crear `modules/ingestion/transport/payloads/sources.py` (Pydantic create/update/response).
- Crear `modules/ingestion/transport/http/sources_router.py` (5 verbos CRUD)
  y `wordpress_webhook_router.py` (POST `/v1/ingest/wordpress/property`).
- Registrar ambos routers en `apps/api/app_factory.py` y borrar handlers/payload legacy
  en `services/transport/http/server.py` (POST/DELETE sources, webhook handler,
  helpers privados sin más call sites).
- Adaptar `tests/integration/test_http_transport.py` (los 4 tests del webhook).
- Crear `tests/unit/ingestion/` (un test por use case) y
  `tests/integration/ingestion/test_wordpress_webhook_flow.py` +
  `test_sources_router.py`.
- Ejecutar `./init.sh` y dejar verde.

## Bitácora

- Lectura inicial completada: AGENTS protocol, phase_2_operating_rules.md (sección 5), explore_router_4_ingestion.md, ARCHITECTURE.md, docs/architecture.md, conventions.md, feature_list.json (4).
- Mapeo de archivos legacy a tocar:
  - `services/transport/http/server.py:163-194` (`_AdminAgencySourceUpsertPayload`).
  - `services/transport/http/server.py:1562-1674` (POST/DELETE sources handlers).
  - `services/transport/http/server.py:2966-3317` (webhook handler).
  - `services/transport/http/server.py:_get_runtime`, `_authorize_admin_request`,
    `_format_client`, `_get_request_id`, `_log_webhook_acceptance_failure`,
    `_build_acceptance_error_details`, `_serialize_wordpress_source_details`
    (conservados o reusados desde `apps/api/`).
  - `services/transport/http/security.py` -> `shared/http/webhook_signature.py`.

## Próximo paso

- Implementación completa. `./init.sh` verde con 197 tests pasando.
- Detalles en `progress/impl_4_ingestion_routers.md`.
- Esperando revisión (NO marcar `done`).

## Sesión cerrada — feature 5 (publishing_connections_router) — 2026-04-30

# Sesión actual

> Este archivo se vacía al cerrar cada sesión y se mueve a `history.md`.
> Mientras trabajas, **mantenlo actualizado en tiempo real**, no al final.

- **Feature en curso:** 5 — publishing_connections_router
- **Inicio:** 2026-04-30
- **Agente:** implementer (general-purpose)
- **Módulo afectado:** modules/publishing/
- **¿Toca schema?:** no

## Plan

- Crear payloads `modules/publishing/transport/payloads/connections.py` (compat con shape legacy del frontend).
- Crear use cases `attach`/`list`/`inspect`/`rotate`/`detach`_provider_connection (5 archivos en modules/publishing/application/use_cases/). `probe_provider_connection` ya existe — reutilizar.
- Crear `modules/publishing/transport/http/connections_router.py` con 5 endpoints (POST/GET/PUT/DELETE + POST /test).
- Registrar el router en `apps/api/app_factory.py`. Borrar de `services/transport/http/server.py` los 3 handlers `/ghl-connection*`, el payload `_AdminGhlConnectionUpsertPayload`, y los runtime methods `upsert_ghl_connection`/`delete_ghl_connection` que dejen de tener call sites. Conservar `get_ghl_connection_by_agency` y `test_gohighlevel_connection` (los usan `social-accounts`/`enqueue_reel_publish` hasta features 7/9).
- Adaptar `tests/integration/test_http_transport.py:470-491` (test del PUT) sin xfail, usando `uow.publishing.connections` en vez de `GoHighLevelConnectionStore`. Crear suite nueva en `tests/integration/publishing/test_connections_router.py` y unit tests en `tests/unit/publishing/test_attach/list/inspect/rotate/detach_provider_connection.py`.

## Bitácora

- 2026-04-30: leído implementer.md, phase_2_operating_rules.md (sección 5), explore_router_5_publishing_connections.md, feature_list.json, AGENTS.md, ARCHITECTURE.md, conventions.md.
- Verificado que `repositories/stores/ghl_connection_store.py` SIGUE siendo consumido por `repositories/postgres/uow.py` y por 4 runtime methods en `server.py:727,739,744,748` (que features 7/9 borran). NO se puede borrar el store en feature 5 — los runtime methods `get_ghl_connection_by_agency`/`require_ghl_connection_for_agency` los usan otros endpoints (`social-accounts`, `enqueue_reel_publish`). Decisión: dejar el store vivo, borrar solo lo que ESTA feature deja huérfano (`upsert_ghl_connection`/`delete_ghl_connection`, payload Pydantic, 3 handlers).

## Próximo paso

Esperando review. Informe en `progress/impl_5_publishing_connections_router.md`.
- 225 tests pasaron (init.sh verde).
- apps.api / apps.worker --check OK.
- No se marca `done` — pendiente de reviewer.

## Sesión cerrada — feature 6 (configuration_routers) — 2026-04-30

# Sesión actual

> Este archivo se vacía al cerrar cada sesión y se mueve a `history.md`.
> Mientras trabajas, **mantenlo actualizado en tiempo real**, no al final.

- **Feature en curso:** 6 — `configuration_routers`
- **Inicio:** 2026-04-30
- **Agente:** implementer (general-purpose)
- **Módulo afectado:** modules/configuration/
- **¿Toca schema?:** no

## Plan

- [x] Crear 5 routers descriptivos en `modules/configuration/transport/http/`.
- [x] Crear 13 use cases (Opción A: directo a `uow.configuration.<section>`).
- [x] Ampliar `MusicTracksRepository` (get + update) y
      `SocialTemplatesRepository` (bulk replace).
- [x] Borrar handlers / payloads / serializers de `services/transport/http/server.py`.
- [x] Adaptar tests legacy (3) y borrar el del stub `/music-tracks`.
- [x] Crear unit tests (13, 43 casos) + integration tests (5, 20 casos).
- [x] `./init.sh` verde — 287 tests pasan en 122s.

## Bitácora

- Implementación cerrada en una sola sesión.
- Informe en `progress/impl_6_configuration_routers.md`.
- `runtime.get_reel_profile`, `runtime.apply_reel_profile_section` y
  `ReelProfileStore` se conservan: tienen call sites fuera de feature
  6 (server.py:835, :1401, :1437, repositories/postgres/uow.py,
  application/persistence.py). Eliminación corresponde a feature 9 / 17.

## Próximo paso

- Revisión por reviewer antes de marcar `done`.

## Sesión cerrada — feature 7 (reels_admin_router) — 2026-04-30

# Sesión actual

> Este archivo se vacía al cerrar cada sesión y se mueve a `history.md`.
> Mientras trabajas, **mantenlo actualizado en tiempo real**, no al final.

- **Feature en curso:** 7 — reels_admin_router
- **Inicio:** 2026-04-30
- **Agente:** implementer (general-purpose)
- **Módulo afectado:** modules/reels/
- **¿Toca schema?:** no

## Plan

- Crear payloads Pydantic en `modules/reels/transport/payloads/admin_reels.py`.
- Crear 4 use cases: `list_reels`, `inspect_reel`, `regenerate_reel`, `reject_reel`
  en `modules/reels/application/use_cases/`.
- Crear router `modules/reels/transport/http/admin_reels_router.py` con los 8
  endpoints (`/`, `/{site_id}/{property_id}`, `/video`, `/images`,
  `/images/{pos}/file`, `/manifest`, `/approve`, `/reject`).
- Registrar el router en `apps/api/app_factory.py`.
- Borrar handlers, helpers y métodos del runtime en
  `services/transport/http/server.py` (8 handlers + `_serialize_agency_reel` +
  `_guess_image_mime_type` + 8 métodos del runtime).
- Adaptar test existente en `tests/integration/test_http_transport.py:653`
  (sin xfail) y crear `tests/integration/reels/test_admin_reels_router.py`
  + `tests/unit/reels/test_<verbo>.py` por use case.

## Bitácora

- 2026-04-30: Lectura del protocolo `implementer.md`,
  `phase_2_operating_rules.md` (sección 5 feature 7),
  `progress/explore_router_7_reels_admin.md`, `ARCHITECTURE.md`,
  `docs/architecture.md`, `docs/conventions.md`. Marcada feature 7 como
  `in_progress` en `feature_list.json`.

## Próximo paso

- Crear payloads + use cases.

## Sesión cerrada — feature 8 (rendering_scripted_router) — 2026-04-30

- Módulo: `modules/rendering/`. No toca schema (`webhook_events.source_kind`
  y `jobs.kind` son `sa.Text()` sin CHECK constraint).
- Router nuevo: `modules/rendering/transport/http/scripted_router.py`
  (POST `/videos/scripted/render` ahora responde **202 accepted** con
  `{status, job_id, event_id, site_id, source_property_id}` — cambio
  sync→async confirmado).
- Use case nuevo: `modules/rendering/application/use_cases/enqueue_scripted_render.py`
  (`EnqueueScriptedRenderUseCase`). Tenant resolution inline vía
  `uow.ingestion.sources.get_by_kind_external_id` →
  `uow.tenancy.agencies.get_by_id`. Encola
  `JobEnqueueRequest(kind="scripted_render", payload=dict(body))`,
  `provider_secret_bundle=""`, `publish_context={}`. `webhook_events.source_kind="scripted_api"`.
- Payloads: `modules/rendering/transport/payloads/scripted.py` con
  `ScriptedRenderResponse`.
- Registrado en `apps/api/app_factory.py`.
- Borrado legacy en la misma sesión: handler `render_scripted_video` en
  `services/transport/http/server.py:1054-1173`,
  `WordPressWebhookApplication.render_scripted_video` (`server.py:492-497`),
  el atributo `scripted_video_service`, el import de
  `ScriptedVideoRenderService`, y `_decorate_scripted_render_operation`
  + helpers huérfanos en `services/transport/http/openapi_docs.py:359-454`.
- Worker intacto: el handler `scripted_render` ya estaba registrado en
  `apps/worker/runtime.py:259-279` (no requiere cambios; feature 14
  borrará `application/scripted_render/service.py`).
- Tests añadidos: 5 unit (`tests/unit/rendering/test_enqueue_scripted_render.py`)
  + 6 integration (`tests/integration/rendering/test_scripted_router.py`).
  Total `pytest -q`: 331 passed (baseline previa 320).
- Verificación: `./init.sh` verde, `python -m apps.api --check` exit 0,
  `python -m apps.worker --check` exit 0.
- Implementer: `progress/impl_8_rendering_scripted_router.md`.
- Review (APPROVED): `progress/review_8_rendering_scripted_router.md`.

## Sesión cerrada — feature 9 (retire_wordpress_webhook_server) — 2026-05-01

- Módulo afectado: `apps/api/`, `modules/ingestion/`, `modules/configuration/`, `modules/publishing/`, `services/transport/http/` (borrado). No toca schema (migración inicial intacta).
- Borrada la god-class `WordPressWebhookServer` y la fábrica `create_fastapi_app`: `apps/api/app_factory.py` ahora construye `FastAPI()` directo y registra los 16 routers (12 existentes + 4 nuevos).
- `apps/api/main.py` consume `app` desnudo desde `build_api_app` (sin `server.app`/`server.runtime`).
- Routers nuevos creados: `apps/api/health_router.py`, `modules/ingestion/transport/http/wordpress_sources_router.py`, `modules/configuration/transport/http/reel_profile_router.py`, `modules/publishing/transport/http/social_accounts_router.py`.
- Helpers nuevos: `apps/api/host_filter.py` (resolve_allowed_hosts, should_enable_docs, is_local_docs_host, normalise_allowed_host, looks_like_hostname) y `build_admin_access_policy` en `apps/api/admin_auth.py`.
- Use cases creados: `list_global_wordpress_sources`, `inspect_wordpress_source_by_site_id`, `provision_wordpress_source` (+ `_wordpress_support`) en `modules/ingestion/application/use_cases/`; `read_aggregated_reel_profile`, `update_aggregated_reel_profile` en `modules/configuration/application/use_cases/`; `inspect_agency_social_accounts` en `modules/publishing/application/use_cases/`.
- Payloads nuevos: `modules/ingestion/transport/payloads/wordpress_sources.py`, `modules/configuration/transport/payloads/reel_profile.py`.
- Borrados (LoC): `services/transport/http/server.py` (1436), `services/transport/http/openapi_docs.py` (644), `services/transport/http/uvicorn_protocols.py` (276), `application/admin/wordpress_source_management.py` (~500) + `application/admin/__init__.py` (12). El paquete entero `application/admin/` desaparece.
- `tests/integration/test_http_transport.py` adaptado para invocar `apps.api.app_factory.build_api_app(...)` con kwargs nuevos; ya no importa de `services.transport.http.server`.
- Tests añadidos: 45 netos (27 unit + 18 integration). Total `pytest -q`: 376 passed (baseline pre-feature 331 + 45).
- Verificación: `./init.sh` verde, `python -m apps.api --check` exit 0 ("Runtime ready: Yes"), `python -m apps.worker --check` exit 0 (`kinds=reel_publish, scripted_render worker_count=1`).
- Decisión 1: kwargs `readiness_provider` y `dispatcher_accepting_jobs` en `build_api_app` permiten inyección determinista en tests con `TestClient` sin abrir `lifespan`; producción sigue corriendo `_NoopDispatcher` real y `services.transport.http.operations.build_readiness_report` real.
- Decisión 2: `provision_wordpress_source` persiste `site_url` y `normalized_host` dentro de `ingestion_sources.config_json` (no en columnas dedicadas legacy); el GET reconstruye el shape legacy desde ahí preservando contrato HTTP byte-a-byte.
- Decisión 3: el endpoint `/v1/admin/agencies/{id}/reel-profile` se reescribió desde el UoW agregado de `configuration` (`uow.configuration.brand/defaults/automation/social_templates/music`); NO pasa por `ReelProfileStore`. `to_public_dict()` reproduce el shape legacy completo.
- Observaciones menores (no bloqueantes): docstrings con referencia histórica a `WordPressWebhookServer`/`WordPressWebhookApplication` en 4 archivos; test intermitente `test_automation_put_persists_typed_record` (race en `temporary_postgres_schema`, pre-existente); `apps/api/main.py` aún importa `services.transport.http.operations.build_readiness_report` (deuda para feature 18).
- Implementer: `progress/impl_9_retire_wordpress_webhook_server.md`.
- Review (APPROVED): `progress/review_9_retire_wordpress_webhook_server.md`.

## Feature 10 — `reels_use_case_ingest_property_into_reel`
- **Cerrada:** 2026-05-02
- **Resultado:** done (APPROVED por reviewer)
- **Cambio LoC clave:** application/pipeline/media_services.py 1839 → 1034
- **Tests:** 376 → 380 (3 unit + 1 integration añadidos)
- **Documentos:** progress/explore_feature_10_ingest_property_into_reel.md,
  progress/impl_10_ingest_property_into_reel.md,
  progress/review_10_ingest_property_into_reel.md
- **Notas:**
  - D1 respetado (no se escribe `media_revisions` en ingest).
  - Adapter `DefaultPropertyInfoService` queda como bridge delgado (~33 LoC).
  - Cambio defensivo en `tests/support/postgres.py` (disposición del engine cacheado en el `finally` de `temporary_postgres_schema`) — aceptado por reviewer.
  - Pendiente futuro (sugerencia menor del reviewer): `application/pipeline/__init__.py` (1839 LoC) es dead code; agendar borrado en feature 14 o 18.

## Sesión 2026-05-05 — feature 11 (reels_use_case_prepare_reel_assets)

- **Cerrada:** 2026-05-05
- **Resultado:** done (APPROVED por reviewer tras fix post-review)
- **Módulo afectado:** `modules/reels/` (extracción del paso 2 del pipeline desde `application/pipeline/media_services.py`). No toca schema.
- **Archivos creados:** `modules/reels/application/use_cases/prepare_reel_assets.py` (447 LoC), `tests/unit/reels/test_prepare_reel_assets.py` (399 LoC, 7 tests), `tests/integration/reels/test_prepare_reel_assets_flow.py` (169 LoC, 1 test).
- **Archivos modificados:** `application/pipeline/media_services.py` (1034 → 807 LoC, reducción ~22%), `application/pipeline/default_services.py` (re-exports), `modules/reels/application/use_cases/ingest_property_into_reel.py` (cierre R1), `modules/reels/application/use_cases/__init__.py` (re-export), `feature_list.json` (status done).
- **Cambios clave:** R1 cerrado (`_state_for_legacy_helpers` eliminado, comentario "feature 11 absorbs ..." borrado, lazy import de `PrepareReelAssetsUseCase`), D4 borrado (`DefaultPhotoSelectionService` eliminado de `media_services.py` y `default_services.py`), R8/R9 cumplidos (imports huérfanos limpios y re-export `LocalPhotoSelectionEngine`), fix post-review aplicado (restaurado `build_log_context` en import multilínea de `core.logging`, 3 call sites en líneas 452/482/543 ya resuelven el símbolo).
- **Tests:** 380 → 388 (7 unit + 1 integration añadidos). `./init.sh` exit 0, `apps.api --check` y `apps.worker --check` exit 0.
- **Documentos:** `progress/explore_feature_11_prepare_reel_assets.md`, `progress/impl_11_prepare_reel_assets.md`, `progress/review_11_prepare_reel_assets.md`.

## Sesión 2026-05-05 — feature 12 (reels_use_case_persist_local_artifacts)

- **Cerrada:** 2026-05-05
- **Resultado:** done (APPROVED por reviewer)
- **Módulo afectado:** `modules/reels/` (extracción del paso 3 del pipeline — persistencia local de artefactos — desde `application/pipeline/media_services.py`). No toca schema.
- **Archivos creados:** `modules/reels/application/use_cases/persist_local_artifacts.py` (351 LoC), `tests/unit/reels/test_persist_local_artifacts.py` (388 LoC, 7 tests), `tests/integration/reels/test_persist_local_artifacts_flow.py` (227 LoC, 1 test).
- **Archivos modificados:** `application/pipeline/media_services.py` (807 → 677 LoC, reducción 130 LoC ~16%), `application/bootstrap/runtime.py` (+1 LoC `workspace_dir=workspace_path`), `application/bootstrap/__init__.py` (+1 LoC idéntico — `diff` exit 0), `modules/reels/application/use_cases/__init__.py` (re-export), `feature_list.json` (status done).
- **Cambios clave:** extracción de `FileSystemMediaPublisher.publish_media` + `publish_existing_media` + helpers privados (`_resolve_output_dir`, `_publish_related_poster`, `_replace_atomically`) al use case `PersistLocalArtifactsUseCase`. Bootstrap pasa `workspace_dir` al adapter (D3). Adapter `FileSystemMediaPublisher` queda delgado (~46 LoC con 4 alias). `MediaRevision` moderno (`from modules.reels.domain`) con `ingestion_source_id`/`external_source_id` (no legacy). Class shadow `class FileSystemMediaPublisher(FileSystemMediaPublisher): pass` eliminado (R5). Imports huérfanos limpiados (`os`, `shutil`, `should_cleanup_render_staging_dir`). `build_log_context` conservado (R6 — no se repite la regresión post-review feature 11). `outbox.add_event` requiere `created_at` no vacío (descubrimiento R10/§4.1).
- **Tests:** 388 → 396 (7 unit + 1 integration añadidos). `./init.sh` exit 0 con 396 passed. `apps.api --check` y `apps.worker --check` exit 0.
- **Documentos:** `progress/explore_feature_12_persist_local_artifacts.md`, `progress/impl_12_persist_local_artifacts.md`, `progress/review_12_persist_local_artifacts.md`.

## Sesión 2026-05-05 — feature 13 (reels_use_case_publish_reel)

- **Cerrada:** 2026-05-05
- **Resultado:** done (APPROVED por reviewer)
- **Módulo afectado:** `modules/reels/` (extracción del paso 4 del pipeline — publish externo + persistencia de la transición de workflow — desde `application/pipeline/media_services.py`). No toca schema.
- **Archivos creados:** `modules/reels/application/use_cases/publish_reel.py` (495 LoC), `tests/unit/reels/test_publish_reel.py` (623 LoC, 12 tests), `tests/integration/reels/test_publish_reel_flow.py` (304 LoC, 1 test).
- **Archivos modificados:** `application/pipeline/media_services.py` (677 → 377 LoC, reducción 300 LoC ~44%), `application/bootstrap/runtime.py` (+1 LoC `workspace_dir=workspace_path`), `application/bootstrap/__init__.py` (+1 LoC idéntico — `diff` exit 0), `modules/reels/application/use_cases/__init__.py` (re-export `PublishReelUseCase`), `feature_list.json` (status done).
- **Cambios clave:** extracción de `CompositeMediaPublisher.publish_media` + `_publish_externally` + `_persist_workflow_transition` + `_build_publish_details` al use case `PublishReelUseCase` (`execute` / `execute_existing`). Adapter `CompositeMediaPublisher` queda delgado (~50 LoC con docstring + 4 alias `publish_media`/`publish_video`/`publish_existing_media`/`publish_existing_video`). Outbox pasa `status='completed'` solo en camino `publish_completed` (D5/R11 — cambio semántico intencional vs legacy). Rename `last_published_location_id` → `last_published_provider_external_id` aplicado (D6). `EXISTING_MEDIA_REQUIRED` unificado: `execute_existing` delega a `local_publisher.publish_existing_media` sin duplicar check (D7). Helpers de módulo `_now_iso` / `_relative_path_text` / `_build_workflow_payload` borrados de `media_services.py` (R9, duplicados ahora viven en el use case). Class shadow `class CompositeMediaPublisher(CompositeMediaPublisher): pass` eliminado (R4). Import legacy `MediaRevisionRecord` borrado junto con 11 imports huérfanos más (R8). Camino `failed` re-eleva la excepción tras persistir (R13).
- **Tests:** 396 → 409 (12 unit + 1 integration añadidos). `./init.sh` exit 0 con 409 passed. `apps.api --check` y `apps.worker --check` exit 0.
- **Documentos:** `progress/explore_feature_13_publish_reel.md`, `progress/impl_13_publish_reel.md`, `progress/review_13_publish_reel.md`.

## Sesión 2026-05-05 — feature 14 (rendering_pure_renderer_and_delete_media_services)

- **Cerrada:** 2026-05-05
- **Resultado:** done (APPROVED por reviewer)
- **Módulo afectado:** `modules/rendering/`, `application/pipeline/` (borrado), `application/bootstrap/`. No toca schema.
- **Archivos creados:** `modules/rendering/application/frame_composition.py` (renderer puro `DefaultMediaRenderer`, sin DB), `application/bootstrap/pipeline_adapters.py` (4 adapters delgados — verbatim), `tests/unit/rendering/test_frame_composition.py` (8 tests con monkeypatch sobre primitivas).
- **Archivos borrados:** `application/pipeline/media_services.py` (377 LoC), `application/pipeline/default_services.py` (17 LoC), `application/pipeline/__init__.py` (1839 LoC dead code → reducido a marker de 1 LoC).
- **Archivos modificados:** `application/bootstrap/runtime.py` y `application/bootstrap/__init__.py` (imports redirigidos a `pipeline_adapters` + `modules.rendering.application.frame_composition`, byte-igualdad mantenida), `feature_list.json` (status done).
- **Cambios clave:** Opción C aplicada — separación adapters delgados vs renderer puro. Cierre del trabajo iniciado en features 10-13 (pipeline god-file completamente desmantelado). Import muerto histórico (1839 LoC `__init__.py` legacy) eliminado.
- **Tests:** 409 → 417 (8 unit nuevos). `./init.sh` exit 0 con 417 passed. `apps.api --check` y `apps.worker --check` exit 0.
- **Documentos:** `progress/explore_feature_14_pure_renderer_and_delete_media_services.md`, `progress/impl_14_pure_renderer_and_delete_media_services.md`, `progress/review_14_pure_renderer_and_delete_media_services.md`.

## Sesión 2026-05-05 — feature 15 (rendering_layout_split)

- **Cerrada:** 2026-05-05
- **Resultado:** done (APPROVED por reviewer)
- **Módulo afectado:** `modules/rendering/infrastructure/layout/` (nuevo paquete) + facade en `services/media/reel_rendering/layout.py`. No toca schema.
- **Archivos creados:** 5 submódulos en `modules/rendering/infrastructure/layout/` (`models.py` 148 LoC, `text_measurement.py` 477 LoC, `panels.py` 412 LoC, `subtitles.py` 134 LoC, `composition.py` 107 LoC; todos < 500 LoC) + `__init__.py` (26 LoC, re-exports). Tests: `tests/unit/rendering/conftest.py` (helpers compartidos) + 5 archivos `test_layout_{models,text_measurement,panels,subtitles,composition}.py` (36 tests nuevos).
- **Archivos modificados:** `services/media/reel_rendering/layout.py` reducido de 1038 → 27 LoC (facade re-exporta los 6 públicos). Imports actualizados en 3 callers: `modules/rendering/infrastructure/ffmpeg/filter_graph.py:9`, `modules/rendering/infrastructure/ffmpeg/render_reel.py:18`, `tests/test_reel_pipeline.py:20`. Los 4 callers legacy bajo `services/media/reel_rendering/{filters,preparation,poster,manifest}.py` siguen vía facade hasta feature 18. `feature_list.json` (status done).
- **Cambios clave:** `build_overlay_layout` partido en 3 fases públicas con kwargs explícitos (`compose_top_panel`, `compose_bottom_panel`, `compose_subtitle_segments`); orquestador `composition.build_overlay_layout` (~90 LoC) ensambla `OverlayLayout` preservando orden top → bottom → subtitles. Renames a público: `MeasuredTextBlock`, `measure_text_block`, `measure_address_blocks`. Helpers internos conservan `_` prefix. `OverlayLayoutTests` legacy verde verbatim (solo cambia el import de la línea 20).
- **Tests:** 417 → 453 (36 unit nuevos). `./init.sh` exit 0 con 453 passed. `apps.api --check` y `apps.worker --check` exit 0.
- **Documentos:** `progress/explore_feature_15_layout_split.md`, `progress/impl_15_layout_split.md`, `progress/review_15_layout_split.md`.

## Sesión 2026-05-05 — feature 16 (worker_real_use_cases_and_drop_noop_dispatcher)

- **Cerrada:** 2026-05-05
- **Resultado:** done (APPROVED por reviewer)
- **Módulo afectado:** `apps/worker/`, `apps/api/app_factory.py`, `modules/reels/application/orchestrator.py`, `application/bootstrap/`, `application/pipeline/` (borrado). No toca schema.
- **Archivos creados:** `tests/integration/delivery/test_worker_dispatcher_flow.py` (cubre claim → handler → outbox end-to-end con stubs de renderer/social para los kinds `reel_publish` y `scripted_render`).
- **Archivos modificados:** `modules/reels/application/orchestrator.py` reescrito (instancia los 4 use cases ingest/prepare/persist/publish + renderer + helper local; rutas `is_noop`, `requires_render=False` y feliz). `apps/api/app_factory.py` sin `_NoopDispatcher` (rama default ahora `dispatcher_state = lambda: True` + lifespan no-op). `application/bootstrap/runtime.py` y `application/bootstrap/__init__.py` limpios (eliminados `build_default_property_media_pipeline`, `build_default_job_handler`, `build_default_job_dispatcher` + imports).
- **Archivos borrados:** `application/pipeline/media_pipeline.py`, `application/pipeline/interfaces.py`, `application/pipeline/job_runner.py`, `application/bootstrap/pipeline_adapters.py` (4 archivos).
- **Tests:** 453 → 455 (post-feature, +2 integration). `./init.sh` exit 0 con 455 passed. `apps.api --check` y `apps.worker --check` exit 0.
- **Desviación importante:** la idea inicial era compartir un único `DatabaseUnitOfWork` entre los 4 use cases dentro de `ReelPipeline.handle`; en la práctica se observó deadlock (cada use case tomaba locks largos sobre las mismas tablas dentro del mismo UoW). Decisión documentada: cada use case abre su propio UoW corto y la orquestación pasa los IDs/payloads necesarios entre pasos. Documentado en `progress/impl_16_worker_real_use_cases.md` §5.
- **Documentos:** `progress/explore_feature_16_worker_real_use_cases.md`, `progress/impl_16_worker_real_use_cases.md`, `progress/review_16_worker_real_use_cases.md`.

## Sesión 2026-05-05 — feature 17 (retire_property_store_and_repositories_stores)

- **Inicio / Cierre:** 2026-05-05 / 2026-05-05
- **Resultado:** done (APPROVED por reviewer)
- **Módulo afectado:** `repositories/` (borrado entero) + `modules/catalog/infrastructure/property_store_compat.py` (borrado) + readiness moderno en `apps/api/`. No toca schema.
- **Archivos creados:** `apps/api/readiness.py` (438 LoC, reimplementa `build_readiness_report` / `cleanup_stale_staging_directories` / `ensure_runtime_is_supported` sobre `shared.db.{uow,engine}`), `tests/unit/apps_api/test_readiness.py` (202 LoC, 5 tests: ready=true / DB failure / storage failure / missing site secrets / security disabled warning).
- **Archivos modificados:** `apps/api/main.py:82` (import → `apps.api.readiness`), `apps/api/health_router.py` (docstrings 13/49 + lazy import :112 reapuntados), `application/bootstrap/runtime.py:5` y `application/bootstrap/__init__.py:5` (1 LoC cada: `from shared.db.uow import DatabaseUnitOfWork`; `diff` exit 0), `services/media/reel_rendering/data.py` y `services/publishing/social_delivery/description.py` (R7: `PropertyReelRecord` inline 31 fields), `application/scripted_render/{__init__,service}.py` (R8 ampliado: inline `ScriptedVideoArtifactRecord` + alias `UnitOfWork = object`), `feature_list.json` (status done).
- **Archivos borrados:** `repositories/` recursivo (~3 610 LoC: 8 archivos en `postgres/` + 11 stores + 12 ORM models legacy + `__init__.py`), `modules/catalog/infrastructure/property_store_compat.py` (278 LoC), `tests/unit/test_architecture_cleanup.py` (78 LoC) y `tests/unit/test_tenancy.py` (73 LoC). Total: ~4 039 LoC borradas.
- **Cambios clave:** demolición de la capa legacy `repositories/`. La cadena `apps.api → services/transport/http/operations → repositories` queda sustituida por `apps.api.readiness` moderno. `services/transport/http/operations.py` queda frozen (lo borra feature 18). Desviación frente al plan §R8 documentada en review (`mock.patch` sobre `application.scripted_render.service` carga el módulo y forzaba el ciclo legacy roto).
- **Tests:** 455 → 454 (post-feature: -6 borrados de los 2 archivos legacy + 5 nuevos en `test_readiness.py`). `./init.sh` exit 0 con 454 passed in 234.56s. `apps.api --check` y `apps.worker --check` exit 0.
- **Documentos:** `progress/explore_feature_17_retire_repositories.md`, `progress/impl_17_retire_repositories.md`, `progress/review_17_retire_repositories.md`.

## Sesión 2026-05-06 — feature 18 (delete_legacy_dirs_and_close_phase_2) — Phase 2 DONE

- **Cerrada:** 2026-05-06. Resultado: done (APPROVED por reviewer tras splits post-review).
- **Cierre Phase 2:** ejecutado vía 3 sub-tareas + 4 splits post-review:
  - 18a — disolución de `core/` (logging, errors, ids) → `shared/observability/`, `shared/errors/`, `shared/ids/`. APPROVED.
  - 18b — disolución de `domain/` y `application/` → `modules/<bc>/domain/types.py`, `modules/rendering/application/scripted_video/`, `modules/publishing/infrastructure/adapters/gohighlevel/factory.py`, `shared/media_cleanup/`, `shared/locking/`. APPROVED.
  - 18c — disolución de `services/` (rendering, publishing, ai, media, transport) y cierre Phase 2. APPROVED tras 4 splits adicionales para cumplir A4 (≤500 LoC) sin deuda residual.
- **5 dirs frozen borrados a lo largo de Phase 2:** `services/`, `application/`, `core/`, `domain/`, `repositories/`.
- **LoC neto borrado a lo largo de Phase 2:** del legacy `media_services.py` original (1 839 LoC) + ~4 039 LoC en `repositories/` (feature 17) + ~7 700 LoC en `services/` (sub-feature 18c) + miles más en `application/`, `core/`, `domain/` (18a/18b) y los routers/use cases que reemplazaron `WordPressWebhookServer` (features 1-9). Total estimado: **~12-15 k LoC borradas**, sustituidas por código modular en `apps/`, `modules/`, `shared/` (todos los archivos ≤ 495 LoC).
- **Archivos clave creados durante feature 18:** `shared/observability/{logging,console_format}.py`, `shared/errors/<implementación>.py`, `shared/media_cleanup/<implementación>.py`, `shared/locking/<implementación>.py`, `shared/storage/site_layout.py`, `modules/reels/domain/types.py`, `modules/rendering/application/scripted_video/`, `modules/rendering/infrastructure/{models,formatting,data,manifest,poster,preparation,ffmpeg/filters}.py`, `modules/rendering/infrastructure/ai_photo_selection/{client,prompting,audit,selection,classify}.py`, `modules/rendering/infrastructure/photos/{naming,filesystem,downloads,selection}.py`, `modules/publishing/infrastructure/adapters/gohighlevel/{client,models,media_service,social_service,interfaces,platform_policy,user_selection,property_publisher,factory}.py`, `modules/publishing/infrastructure/social_copy/{post_copy,description}.py`, `modules/ingestion/transport/http/_wordpress_webhook_helpers.py`, `modules/reels/transport/http/admin_reels_assets.py`, `modules/reels/application/use_cases/{_ingest_property_planning,_ingest_property_assets,_ingest_property_diffs}.py`, `apps/api/readiness.py`.
- **Verificación final:** `pytest -q` 394 passed in 223.90s (baseline final Phase 2). `apps.api --check` y `apps.worker --check` exit 0. `./init.sh` exit 0 (sin dirs legacy, 0 imports legacy bajo `apps|modules|shared|tests`). Ningún archivo bajo `apps|modules|shared` excede 495 LoC.
- **AGENTS.md / REFACTOR_STATUS.md:** marcan Phase 2 DONE.
- **Phase 3 active:** URL rename (`/v1/...`) + frontend lockstep.
- **Documentos:** `progress/explore_feature_18_close_phase_2.md`, `progress/impl_18a_dissolve_core.md`, `progress/review_18a_dissolve_core.md`, `progress/impl_18b_dissolve_domain_application.md`, `progress/review_18b_dissolve_domain_application.md`, `progress/impl_18c_dissolve_services_close_phase_2.md` (incluye §9 splits post-review), `progress/review_18c_dissolve_services_close_phase_2.md`.

## Sesion 2026-05-06 - feature 1 Phase 3 (rename_scripted_render_to_v1)

- **Inicio / cierre:** 2026-05-06 / 2026-05-06.
- **Resultado:** done (APPROVED por review local siguiendo `.claude/agents/reviewer.md`).
- **Modulo afectado:** `modules/rendering/transport/http`. No toca schema.
- **Archivos modificados:** `modules/rendering/transport/http/scripted_router.py`, `tests/integration/rendering/test_scripted_router.py`, `docs/API.md`, `REFACTOR_STATUS.md`, `feature_list.json`.
- **Archivos creados:** `progress/impl_1_rename_scripted_render_to_v1.md`, `progress/review_1_rename_scripted_render_to_v1.md`.
- **Cambios clave:** `POST /videos/scripted/render` se movio a `POST /v1/videos/scripted/render` usando `APIRouter(prefix="/v1")`; no se publico alias legacy. La suite del router cubre el 202 de la ruta nueva y el 404 de la ruta sin version.
- **Tests:** `apps.api --check` verde, `apps.worker --check` verde, `pytest tests\integration\rendering\test_scripted_router.py -q` con 7 passed, `pytest -q --no-header` con 395 passed.
- **Nota entorno:** `bash ./init.sh` no arranca en este Windows porque falta `/bin/bash`; se ejecuto el flujo equivalente con `.venv\Scripts\python.exe`.

## Sesion 2026-05-06 - feature 2 Phase 3 (align_music_endpoint_front_to_back)

- **Inicio / cierre:** 2026-05-06 / 2026-05-06.
- **Resultado:** done (APPROVED por review local siguiendo los protocolos de back y front).
- **Modulo afectado:** `modules/configuration` (docs/tests) + `4reels front/src/features/music`. No toca schema.
- **Back:** `docs/API.md` documenta el CRUD de musica; `test_music_router.py` fija el shape de list; `REFACTOR_STATUS.md` marca feature 2 cerrada.
- **Front:** `musicApi` usa `/v1/admin/agencies/{id}/music` y expone 5 verbos; UI Music consume el shape canonico; mock Playwright sirve CRUD in-memory; `tests/music.spec.js` cubre listar/crear/editar/borrar.
- **Tests:** back `apps.api --check`, `apps.worker --check`, `pytest -q --no-header` con 395 passed. Front `npm run lint --silent`, `npm run build --silent`, `npm run test:smoke` con 40 passed/2 skipped, `npm run test:e2e` con 43 passed/2 skipped.
- **Documentos:** `progress/impl_2_align_music_endpoint_front_to_back.md`, `progress/review_2_align_music_endpoint_front_to_back.md`, `4reels front/progress/impl_2_align_music_endpoint_front_to_back.md`, `4reels front/progress/review_2_align_music_endpoint_front_to_back.md`.

## Sesion 2026-05-06 - feature 3 Phase 3 (resolve_session_me_endpoint)

- **Inicio / cierre:** 2026-05-06 / 2026-05-06.
- **Resultado:** done (APPROVED en `progress/review_3_resolve_session_me.md`).
- **Decision:** Opcion B; el backend no expone `GET /me` y el frontend deriva identidad desde admin-direct mode o SSO GoHighLevel.
- **Front:** eliminado `getCurrentUser` y `ApiSessionProvider`; `SessionProvider` renderiza siempre `GhlMvpSessionProvider`; sin literales `/me` en `src/`.
- **Back:** `docs/API.md` documenta que `/me` no existe y lista los endpoints `/v1/sessions/gohighlevel/*`.
- **Tests reportados:** front lint/build/smoke verdes; back `pytest -q` con 395 passed. Revalidado despues por feature 4 antes de cierre final.
- **Documentos:** `progress/explore_feature_3_resolve_me.md`, `progress/impl_3_resolve_session_me.md`, `progress/review_3_resolve_session_me.md`, `4reels front/progress/impl_3_resolve_session_me.md`.

## Sesion 2026-05-06 - feature 4 Phase 3 (http_surface_audit_and_contract_test)

- **Inicio / cierre:** 2026-05-06 / 2026-05-06.
- **Resultado:** done (APPROVED en `progress/review_4_http_surface_audit_and_contract_test.md`).
- **Modulo afectado:** `scripts/`, `docs/`, `tests/integration/`. No toca schema ni codigo runtime de producto.
- **Archivos creados:** `scripts/generate_http_surface.py`, `scripts/__init__.py`, `docs/http_surface.md`, `docs/openapi.json`, `tests/integration/test_http_surface_contract.py`, `progress/impl_4_http_surface_audit_and_contract_test.md`, `progress/review_4_http_surface_audit_and_contract_test.md`.
- **Cambios clave:** tabla canonica de 51 rutas generada desde `build_api_app(...)`; OpenAPI versionado; test cross-repo que extrae 37 `apiRequest(...)` del front y valida metodo+path contra FastAPI.
- **Regresion validada:** copia temporal rota del front falla con mensaje accionable que incluye `src\features\admin\api.js:9` y ruta backend cercana.
- **Tests:** back `apps.api --check`, `apps.worker --check`, `pytest -q --no-header` con 396 passed. Front `npm run lint`, `npm run build`, `npm run test:smoke` con 40 passed/2 skipped.
- **Estado:** Phase 3 cerrada. Phase 4 queda como backlog no aprobado.

## Sesion 2026-05-07 - feature 5 Phase 4 (frontend_admin_auth_lockstep)

- **Inicio / cierre:** 2026-05-07 / 2026-05-07.
- **Resultado:** done (APPROVED en `progress/review_5_frontend_admin_auth_lockstep.md`, cross-repo back+front).
- **Modulo afectado (back):** `apps/api/`, `modules/publishing/transport/http/`, `settings/`, `tests/`. No toca schema (JWT HS256 stateless, sin tabla `agency_sessions`).
- **Archivos clave creados (back):** `apps/api/agency_token.py` (issue/decode HS256 con scope `agency` + issuer `4reels-back`, rechaza `alg=none`/HS512), `tests/unit/apps_api/test_agency_token.py` (10 tests), `tests/integration/auth/test_admin_auth.py` (7 tests cubriendo super-admin / agency valido / mismatch / global / expirado / firma).
- **Archivos clave modificados (back):** `apps/api/admin_auth.py` (matriz §2.4 super-admin vs agency JWT + `_extract_path_agency_id`), `apps/api/app_factory.py`, `modules/publishing/transport/http/sessions_router.py` (emite `agency_token` + `agency_token_expires_at`; 503 `AGENCY_AUTH_NOT_CONFIGURED` cuando connected y secret vacio), `settings/{app,admin,__init__}.py` (`ADMIN_AGENCY_TOKEN_SECRET`/`ADMIN_AGENCY_TOKEN_TTL_SECONDS`), `tests/integration/publishing/test_gohighlevel_session_router.py` (+3 tests), `tests/integration/test_http_transport.py` (helper inyecta secret de tests), `tests/integration/delivery/test_worker_dispatcher_flow.py` (mock.patch para independencia del `.env` del operador), `requirements.txt` (`PyJWT==2.12.1`), `.env.example`, `docs/API.md`, `docs/conventions.md`, `docs/openapi.json`, `docs/http_surface.md`.
- **Cross-repo (front):** `src/lib/api/authToken.js` (nuevo, store plano + hidratacion `sessionStorage`), `src/lib/api/client.js` (`getAuthHeaders` adjunta `Authorization: Bearer`, dispara `notifyUnauthorized` ante 401 en `/v1/admin/*`), `src/features/session/SessionProvider.jsx` (siembra/limpia token, banner especifico para 503 `AGENCY_AUTH_NOT_CONFIGURED`, input local super-admin oculto detras de `MVP_ADMIN_ENABLED`), `tests/support/mock-backend.js` (emite `agency_token` canonico), `tests/admin_auth.spec.js` (3 casos x 3 viewports = 9 passed), `.env.example`, `DOCS.md`.
- **Verificacion:** back `pytest -q --no-header` 416 passed (baseline Phase 2 394 + 22 nuevos), `apps.api --check` y `apps.worker --check` exit 0; front `npm run lint` verde, `npm run build` verde (gzip 103.53 kB), `npm run test:smoke` 40 passed/2 skipped, `npx playwright test tests/admin_auth.spec.js` 9 passed.
- **Coherencia cross-repo:** back emite `agency_token`/`agency_token_expires_at`, front lee exactamente esos nombres; codigos de error compartidos (`AGENCY_AUTH_NOT_CONFIGURED` 503, `AGENCY_TOKEN_FORBIDDEN_GLOBAL_ROUTE` 403, `AGENCY_TOKEN_AGENCY_MISMATCH` 403, `INVALID_ADMIN_TOKEN` 401, `ADMIN_AUTH_REQUIRED` 401); sin secretos `VITE_*` en el bundle.
- **Documentos:** `progress/impl_5_frontend_admin_auth_lockstep_back.md`, `progress/review_5_frontend_admin_auth_lockstep.md`, `4reels front/progress/impl_5_frontend_admin_auth_lockstep_front.md`.

## Sesion 2026-05-07 - feature 6 Phase 4 (fix_frontend_backend_payload_contract) - Phase 4 DONE

- **Inicio / cierre:** 2026-05-07 / 2026-05-07.
- **Resultado:** done (APPROVED en `progress/review_6_fix_frontend_backend_payload_contract.md`, cross-repo back+front, post-fix mecanico de placeholder).
- **Modulo afectado (back):** `tests/integration/{configuration,ingestion}/`, `tests/integration/test_http_surface_contract.py`, `docs/API.md`. No toca schema, routers, payloads, use cases, repositorios ni ORM (Pydantic ya tenia `extra='forbid'` en los 4 endpoints relevantes).
- **Archivos clave modificados (back):** `tests/integration/configuration/test_brand_router.py` (+`test_brand_put_rejects_legacy_keys` parametrizado x6: `font`, `tagline`, `watermark_enabled`, `outro_enabled`, `outro_headline`, `outro_sub`), `tests/integration/configuration/test_automation_router.py` (+`test_automation_put_rejects_legacy_keys` parametrizado x8: `publish_mode`, `review_window_enabled`, `review_window_hours`, `quiet_hours_enabled`, `skip_weekends`, `auto_captions`, `regen_on_update`, `review_emails`), `tests/integration/ingestion/test_sources_router.py` (+`test_sources_post_rejects_legacy_keys` x2 + `test_sources_put_persists_partial_update` x1), `tests/integration/configuration/test_defaults_router.py` (+`test_defaults_put_persists_namespaced_automation_settings` x1), `tests/integration/test_http_surface_contract.py:17` (+`"ingestionSourceId": "ingestion_source_id"` para mapear el placeholder del nuevo PUT que el front introduce en `reconfigureAgencySource`), `docs/API.md` (§ Tenancy model + § Configuration sections actualizadas a las tablas tipadas reales `agency_brand_settings`/`agency_reel_defaults`/`agency_automation_rules`/`agency_social_templates`).
- **Cross-repo (front):** ver `4reels front/progress/history.md` entrada equivalente — Sources (`name`/`status` canonicos + `reconfigureAgencySource` PUT), Brand (4 campos canonicos + `font_family`, retira tagline/watermark/outro), Automation (PUT `/automation` solo con `approval_required` + window/days/trigger; los 7 toggles huerfanos + `platforms` van a `/defaults` con keys namespaced via hook compuesto `useAutomationSave`), mock-backend rechazo 422 shape Pydantic-like, nuevo `tests/payload_contract.spec.js`.
- **Verificacion:** back `pytest -q` **434 passed** (baseline Phase 4 feature 5: 416 + 18 nuevos), `apps.api --check` y `apps.worker --check` exit 0; front `npm run lint` verde, `npm run build` verde (`built in 1.67s`), `npm run test:smoke` (40 passed, 2 skipped), `npx playwright test tests/payload_contract.spec.js` (6 passed across desktop/tablet/mobile, 19.4s).
- **Decisiones clave:** Pydantic estricto preservado en el back (sin aceptar campos legacy); los 7 toggles huerfanos de Automation se persisten en `defaults.settings` con keys namespaced (`automation.<key>`); `platforms` UI sigue en Automation pero se guarda via `/defaults`; cierre cross-repo del contrato HTTP iniciado por feature 4 de Phase 3.
- **Cierre Phase 4:** ambas features de Phase 4 (id 5 y 6) cerradas. Phase 4 DONE 2026-05-07.
- **Documentos:** `progress/impl_6_fix_frontend_backend_payload_contract_back.md`, `progress/review_6_fix_frontend_backend_payload_contract.md`, `4reels front/progress/impl_6_fix_frontend_backend_payload_contract_front.md`.

## 2026-05-12 — Sesión cierre Phase 4 (features 7, 8 + saneamiento entorno)

# Sesion actual

> Este archivo se vacia al cerrar cada sesion y se mueve a `history.md`.
> Mientras trabajas, **mantenlo actualizado en tiempo real**, no al final.

- **Feature en curso:** 8 `pinterest_social_platform_support`
- **Inicio:** 2026-05-12
- **Agente:** Codex
- **Modulo afectado:** Publishing / Configuration / Tenancy
- **Toca schema?:** No

## Plan

- Añadir Pinterest al registro de plataformas GoHighLevel.
- Incluir Pinterest en defaults de publicación y perfil agregado.
- Cubrir social-accounts/defaults con tests focalizados.
- Verificar con pytest focalizado y readiness si el entorno lo permite.

## Bitacora

- `bash ./init.sh` arranca con Bash pero no queda verde: detecta directorios legacy (`services`, `application`, `repositories`, `core`, `domain`), `apps.api --check` y `apps.worker --check` fallan, y el venv no tiene `pytest` instalado aunque el script imprime "pytest verde".
- `feature_list.json` no tiene tareas pending; features 1-6 estan `done`.
- `.env` sincronizado con `.env.example`: rutas `/v1`, claves `WORKER_*`, `ADMIN_AGENCY_TOKEN_*`, seguridad webhook/admin activa y `WEBHOOK_ALLOWED_HOSTS` limitado a `testserver,localhost,127.0.0.1`.
- Docker Postgres comprobado: contenedor `cpih-postgres-test` activo en `0.0.0.0:5433`, `pg_isready` OK para `miapp_test`.
- Base de datos legacy en revision Alembic retirada `20260429_0003`; se creo backup `deploy/backups/miapp_test_pre_20260501_schema.dump`.
- Se ejecuto migracion in-place `deploy/migrate_legacy_schema_to_20260501.py`; Alembic queda en `20260501_0001 (head)` y readiness API/worker pasan.
- Se limpiaron directorios legacy que solo contenian `__pycache__/*.pyc`.
- Alcance ajustado por usuario: dejar frontend por ahora; no cerrar ni corregir el test cross-repo `tests/integration/test_http_surface_contract.py`.
- Verificacion backend-only final:
  - `.venv/bin/alembic current` -> `20260501_0001 (head)`.
  - `.venv/bin/python -m apps.api --check` -> runtime/prod ready.
  - `.venv/bin/python -m apps.worker --check` -> OK.
  - `.venv/bin/python -m pytest -q --ignore=tests/integration/test_http_surface_contract.py` -> 433 passed, 14 warnings.
- 2026-05-11: Diagnostico error frontend `Connect GoHighLevel`: `GET /health/live` en `http://127.0.0.1:8001` responde OK y CORS normal responde con `access-control-allow-origin: *`, pero la preflight de Chrome con `Access-Control-Request-Private-Network: true` falla con `400 Disallowed CORS private-network`.
- 2026-05-11: Se aplica fix backend limitado a CORS private-network para permitir el flujo local desde iframe HighLevel HTTPS hacia backend local durante desarrollo.
- 2026-05-11: Verificacion del fix: test nuevo `test_cors_allows_private_network_preflight_for_local_ghl_embed` pasa; instancia temporal en `127.0.0.1:8002` responde `200 OK` con `access-control-allow-private-network: true`. `apps.api --check` y `apps.worker --check` salen con codigo 0.

## Proximo paso

- Pendiente si se retoma frontend: resolver/ejecutar `tests/integration/test_http_surface_contract.py` con `FRONTEND_REPO_ROOT` valido.
- Pendiente decision leader sobre feature 7 `ghl_probe_fb_gbp`: emitir OAuth Marketplace token con scopes ampliados vs cambiar copy del front.

## 2026-05-11 - Feature 7 `ghl_probe_fb_gbp` (implementer)

- Bug reportado: `POST /v1/admin/agencies/{agency_id}/ghl-connection/test` devuelve 4 cuentas en lugar de 6 (faltan Facebook Page y Google Business Profile que el usuario tiene conectadas en la UI de GHL).
- Investigacion API live (location `v8H1XNB3YCQmVHRhqDoM`, Location API key 40 chars):
  - `GET /social-media-posting/{locationId}/accounts` -> 200, 4 cuentas (IG/LinkedIn/TikTok/YouTube), `groups: []`. Parametros `includeAll/includeGroups/all` -> 422.
  - `GET /social-media-posting/{locationId}/accounts?platform=facebook|google` -> 200 con `accounts: []`.
  - `GET /social-media-posting/oauth/{facebook|google|instagram|tiktok|linkedin|youtube}/accounts?locationId=...` -> **401 "The token is not authorized for this scope."** (rutas existen pero el token no tiene scope).
  - Variantes `/oauth/{locationId}/{platform}/...`, `/oauth/{platform}/pages`, `/oauth/{platform}/locations`, `/locations/{id}/integrations`, `/integrations` -> 404.
- Conclusion: bloqueo por scope/token, no por codigo. La ruta canonica `/social-media-posting/oauth/{platform}/accounts` esta pero requiere OAuth Marketplace token con scopes `socialplanner/oauth.readonly` (y/o `socialplanner/account.readonly`).
- Resultado: feature `id: 7` anadida a `feature_list.json` con status `blocked`. **No se modifica codigo ni tests** — cualquier llamada con el token actual seguiria devolviendo 401. Informe completo (tabla de probes con status codes, causa raiz, workarounds) en `progress/impl_ghl_probe_fb_gbp.md`.
- 2026-05-12: Se abre feature 8 `pinterest_social_platform_support` para reconocer Pinterest como plataforma social conectada/publicable via GoHighLevel. `bash ./init.sh` inicial arranca, pero `apps.api --check` y `apps.worker --check` siguen avisando rojo por config previa; pytest queda en ejecucion al empezar la implementacion.
- 2026-05-12: Pinterest anadido al registro de plataformas, defaults de publicacion, perfil agregado, admin agencies, docs y tests focalizados.
- 2026-05-12: Verificacion focalizada verde:
  - `.venv/bin/python -m pytest tests/unit/publishing/test_platform_registry.py tests/unit/publishing/test_inspect_agency_social_accounts.py tests/integration/publishing/test_social_accounts_router.py tests/integration/configuration/test_defaults_router.py -q` -> 14 passed.
  - `FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend .venv/bin/python -m pytest tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes -q` -> 1 passed.
- 2026-05-12: `bash ./init.sh` final con Postgres accesible: readiness verde (`apps.api --check`, `apps.worker --check`) y proceso sale 0, pero la salida de pytest contiene 3 fallos preexistentes/no relacionados:
  - `test_http_surface_contract` falla sin `FRONTEND_REPO_ROOT` porque el default Windows no existe en este workspace.
  - Dos tests de `test_http_transport.py` esperan payload minimo de `/health`, pero el codigo actual devuelve tambien `configured_worker_count`.

## 2026-05-12 — Feature 12 `unescape_html_entities_everywhere` cerrada

# Sesion actual

> Este archivo se vacia al cerrar cada sesion y se mueve a `history.md`.
> Mientras trabajas, **mantenlo actualizado en tiempo real**, no al final.

## Feature en curso: 12 — `unescape_html_entities_everywhere`

- **Modulo afectado**: `modules/rendering/`, `modules/publishing/`, `modules/reels/` (content_generator vive aqui pese a la mencion del JSON a `modules/rendering/`).
- **Toca schema?**: No (`schema: "No"` en feature_list.json).
- **Agent**: implementer (Opus 4.7 1M).

## Plan

1. Aplicar `html.unescape()` al final de `render_template_with_property()` en `modules/reels/application/content_generator.py` para limpiar entidades remanentes en los valores sustituidos del template (title, area, etc.).
2. Aplicar `html.unescape()` al inicio del input de `normalize_caption()` en `modules/rendering/infrastructure/ai_photo_selection/prompting.py:79` para que las captions persistidas en cache/manifest queden decodificadas tanto si vienen de Gemini como del fallback `excerpt_html`.
3. Aplicar `html.unescape()` a `description` y `title` justo antes de armar `json_body` en `GoHighLevelSocialService.create_social_post()` en `modules/publishing/infrastructure/adapters/gohighlevel/social_service.py` para que el `summary` del POST a GHL salga limpio aunque el caller envie entidades crudas.
4. Tests: 6+ casos cubriendo decimal (`&#8217;`), hex (`&#x2019;`), named (`&amp;`, `&quot;`), anidados (`&amp;amp;` -> `&amp;` -> `&` segun spec de `html.unescape`), idempotencia (no re-decodificar texto ya limpio), y string vacio/None.
5. Verificacion: `pytest tests/unit/rendering/ tests/unit/publishing/ -q` (focal) + `FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend bash ./init.sh` final.

## Bitacora

- 2026-05-12 (sesion implementer): feature_list.json marcado `in_progress`. Inicio de la implementacion.
- 2026-05-12: Mapeados los 3 puntos finales. `extract_rendered_text` en `modules/catalog/domain/_property_conversions.py` no decodifica entidades, asi que el problema empieza en `Property.from_api_payload`; el wrapper en 3 puntos es la solucion minima sin tocar el dominio.
- 2026-05-12: `html` ya importado en `prompting.py` (line 11). En `content_generator.py` y `social_service.py` hay que anadir el import.
- 2026-05-12: Baseline `pytest tests/unit/rendering/ tests/unit/publishing/ -q` -> 83 passed.
- 2026-05-12: Tests escritos primero (21 casos en 3 archivos). 15 fallan en rojo contra el codigo sin tocar como esperado.
- 2026-05-12: Aplicado `html.unescape()` en los 3 puntos: `content_generator.render_template_with_property`, `prompting.normalize_caption`, `social_service.create_social_post`. Imports anadidos donde faltaban.
- 2026-05-12: Ajustado un test (`normalize_caption` con named entities terminales) para reflejar la interaccion legacy con `strip("\"'")`, documentado en el comentario del test. No es regresion: es comportamiento preexistente de `normalize_caption`.
- 2026-05-12: `pytest tests/unit/rendering/ tests/unit/publishing/ -q` -> 97 passed (83 baseline + 14 nuevos). `pytest tests/unit/reels/test_content_generator_unescape.py -q` -> 7 passed. `tests/test_gemini_photo_selection.py` (usa `normalize_caption`) -> 15 passed sin cambios.
- 2026-05-12: `FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend bash ./init.sh` -> exit 0. 471 passed, 2 failed (los preexistentes `test_http_transport.py::test_health_endpoints_*` documentados por el leader, fuera de scope). El tercer fallo preexistente (`test_http_surface_contract.py`) desaparece al exportar `FRONTEND_REPO_ROOT`.
- 2026-05-12: Impl report escrito en `progress/impl_12_unescape_html_entities_everywhere.md`. Feature pendiente de review.
- 2026-05-12: NO se marca `done` (paso 10 del protocolo, lo hace el implementer despues del veredicto del reviewer en sesion posterior).

## 2026-05-12 — Feature 9 `agency_default_descriptions_ui` cerrada (decisión leader: KEEP `caption_template`)

# Sesion actual

> Este archivo se vacia al cerrar cada sesion y se mueve a `history.md`.
> Mientras trabajas, **mantenlo actualizado en tiempo real**, no al final.

## Feature en curso: 9 - agency_default_descriptions_ui

**Modulo afectado**: `modules/configuration/` (domain + transport) + un import
desde `modules/reels/application/content_generator.py`.

**Toca schema?**: NO (decision leader: KEEP `caption_template` como dead code;
se limpiara en una feature futura aparte si procede).

**Plan**:
- [x] Anadir validacion de variables permitidas en `description_template` en el PUT.
- [x] Anadir tests de integracion (5 nuevos: 422 con desconocida, 200 con permitidas,
      200 sin variables, 200 con llaves literales, 422 multi-plataforma).
- [x] Anadir test unit que pina las 16 keys del catalogo + sync con runtime.
- [x] Documentar las variables permitidas y el codigo de error en `docs/API.md`.
- [x] Constante unica para las variables permitidas, importada por router y
      por content_generator (single source of truth).

**Decisiones**:
- Constante `ALLOWED_TEMPLATE_VARIABLES` vive en
  `modules/configuration/domain/social_templates_variables.py`. Razon: la
  regla del back prohibe que `modules/<bc>/transport/` importe de
  `modules/<otro-bc>/application/`. Pero `modules/<otro-bc>/application/` SI
  puede importar de `modules/<bc>/domain/`. Ergo el domain del bounded
  context dueno del contrato (configuration, dueno de
  `agency_social_templates`) es la unica colocacion legal. `content_generator`
  la importa desde alli (linea 16 del fichero, solo `TEMPLATE_VARIABLE_PATTERN`
  porque la constante de nombres no se usa en runtime).
- Codigo de error: `SOCIAL_TEMPLATE_UNKNOWN_VARIABLE`. Status code: 422.
- Validacion en el router (no `field_validator`). Razon: para devolver shape
  canonico `{error, code, hint, details}` con codigo controlado. Si la
  validacion vive en `field_validator` Pydantic, FastAPI devuelve un 422 pero
  con el shape de Pydantic v2 (`{"detail": [...]}`), no el nuestro.

**Bitacora**:
- Leida la spike `progress/explore_feature_9_social_templates_state.md`.
- Leidas conventions (regla de capas: transport no importa de application de otro modulo).
- Marcada feature 9 como `in_progress`.
- Implementacion completada: 4 archivos creados/modificados (domain, payload,
  router, content_generator) + 2 archivos de tests + `docs/API.md`.
- Tests: 7 nuevos unit + 5 nuevos integration, todos en verde.
- `tests/unit/configuration/` + `tests/integration/configuration/`: 100 passed.
- `tests/unit/reels/`: 55 passed (no regresion del cambio en `content_generator`).
- `./init.sh` exit 0: 483 passed, 2 failures preexistentes de `/health` que
  el leader ya advirtio que no bloquean.
- `apps.api --check` / `apps.worker --check`: ambos exit 0.
- Informe en `progress/impl_9_agency_default_descriptions_ui.md`.
- Estado: pendiente de review.

## 2026-05-13 — Feature 10 `agency_logo_upload` cerrada

# Sesion actual

> Este archivo se vacia al cerrar cada sesion y se mueve a `history.md`.
> Mientras trabajas, **mantenlo actualizado en tiempo real**, no al final.

## Feature en curso: 10 — agency_logo_upload

- Modulo afectado: `modules/configuration/`, `modules/rendering/`, `modules/reels/`, `shared/storage/`
- Toca schema: NO (columnas ya existen, `Text NOT NULL DEFAULT ""`)
- Estado: implementacion completa, **review pendiente**

### Plan

1. Crear helper FS-agnostico `resolve_agency_branding_destination(...)` en
   `shared/storage/site_layout.py` para alojar uploads de logo (layout
   por agencia, no por site/slug). [DONE]
2. Crear endpoint `POST /v1/admin/agencies/{agency_id}/brand/logo` con
   multipart/form-data, validacion JPG/PNG (content_type + extension) y
   tamaño <= 5 MB. Persistir a disco bajo el helper. Retornar
   `{object_key, url}` donde `url` apunta a un GET admin de descarga.
   [DONE]
3. Anyadir GET handler para servir el binario subido (patron similar a
   `stream_admin_agency_reel_image`). [DONE]
4. Cablear preferencia en rendering:
   - Cargar `BrandSettings` del agency cuando se construye `PropertyContext`
     en `ingest_property_into_reel`. [DONE]
   - Resolver `object_key` a un Path local y pasarlo via
     `PropertyContext.agency_logo_local_path` → `PropertyRenderData`. [DONE]
   - En `prepare_cover_logo_image`, preferir el override local sobre el
     webhook URL. Si el path no existe, fallback al URL. [DONE]
5. Tests:
   - Unit `tests/unit/rendering/test_branding_preference.py` con cuatro
     escenarios (override valido, override sin URL, override stale → fallback
     al URL, ni override ni URL → None). [DONE]
   - Integration `tests/integration/configuration/test_brand_logo_router.py`
     con: JPG valido, PNG valido, content_type incorrecto (415),
     extension incorrecta (422), mismatch type/extension (422), >5MB (413),
     empty (422), sin auth (401/403), agency desconocida (404),
     GET file 404. [DONE - 10 tests passed]
6. `docs/API.md`: nueva seccion "Brand logo upload (feature 10)" con
   request/response, tabla de errores, contrato de deletion via empty
   string. [DONE]

### Decisiones leader aplicadas

- NO modificar `BrandSettingsUpsertPayload`.
- NO migracion alembic.
- Borrar logo = `logo_object_key: ""`, NO `null`.
- Storage FS-only, sin boto3/S3.

### Decisiones propias notables

- Router separado `brand_logo_router.py` en lugar de extender
  `brand_router.py`: agrupa POST upload + GET stream + constantes.
- Helper en `shared/storage/site_layout.py` (no en
  `modules/rendering/infrastructure/runtime/assets.py`) porque
  `modules/reels/application` no puede importar de otra
  `infrastructure/`.
- Multipart parseado con `email.parser` de stdlib en lugar de anyadir
  `python-multipart` como dep (la regla prohibe deps nuevas).
- `object_key = agencies/<safe_agency>/logo-<sha1-12><ext>` donde el
  digest es sobre los bytes → idempotente.

### Bitacora

- Hora inicio: 2026-05-13.
- Spike leido: `progress/explore_feature_10_agency_logo_upload_state.md`.
- `feature_list.json`: feature 10 → `in_progress`.
- Implementacion + tests + docs + impl report: completos.
- `pytest tests/unit/configuration/ tests/integration/configuration/ tests/unit/rendering/`:
  170 passed.
- `FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend bash ./init.sh`:
  497 passed, 2 failed (preexistentes de `/health`, no introducidos por
  esta feature).
- `apps.api --check` y `apps.worker --check`: exit 0.
- Informe: `progress/impl_10_agency_logo_upload.md`.
- Pendiente: revision por el reviewer (no marco `done`).

## 2026-05-13 — Feature 11 `wire_automation_publish_window_to_ghl_schedule` cerrada (cierre del batch Phase 4)

# Sesion actual

> Este archivo se vacia al cerrar cada sesion y se mueve a `history.md`.
> Mientras trabajas, **mantenlo actualizado en tiempo real**, no al final.

## Feature en curso: 11 — wire_automation_publish_window_to_ghl_schedule

- **Estado**: implementado (pendiente de revisión).
- **Módulo afectado**: `modules/configuration/`, `modules/reels/`, `modules/publishing/`, `modules/delivery/`.
- **¿Toca schema?**: No.
- **Plan ejecutado**:
  1. Nuevo use case puro `compute_next_publish_slot(rules, now_utc)` en `modules/configuration/application/use_cases/`. 26 tests verdes en `tests/unit/configuration/test_compute_next_publish_slot.py`.
  2. Threading completo: `regenerate_reel.py` calcula `scheduled_at`, lo añade a `publish_context`; `SocialPublishContext`, `MultiPlatformPublishRequest` y `social_service.create_social_post` lo propagan; GHL recibe `scheduleDate` + `status="scheduled"`.
  3. Idempotent replay: `ActiveJob` y `find_active_job_for_property` ampliados con `publish_context_json`; el `scheduled_at` se recupera del JSON parseado.
  4. Response del approve: `RegenerateReelResult.scheduled_at`; handler emite `body["scheduled_at"]` siempre (con `null` cuando aplica) si `publish_enqueued=True`.
  5. Tests unit + integration verdes (26 + 13 + 12 + 24 = 75 nuevos + actualizados).
- **Verificación**:
  - `pytest tests/unit/configuration/ tests/unit/publishing/ tests/unit/reels/ tests/integration/reels/ tests/integration/publishing/ -q` → verde.
  - `FRONTEND_REPO_ROOT=/opt/projects/4Reels-Frontend bash ./init.sh` → exit 0; solo los 2 fallos preexistentes de `/health` en `tests/integration/test_http_transport.py`.
  - `python -m apps.api --check` y `python -m apps.worker --check` → exit 0.
- **Entregables**:
  - `progress/impl_11_wire_automation_publish_window_to_ghl_schedule.md` con archivos modificados/creados, decisiones, output focal de pytest y edge cases del use case puro.
  - `feature_list.json` feature 11 → `in_progress`.
  - `docs/API.md` actualizado con el campo `scheduled_at` y la semántica del `scheduleDate` del body GHL.
- **Próximo paso**: lanzar `reviewer`.

## 2026-05-13 — Feature 16 `side_banner_render_template` cerrada (APPROVED por reviewer pass-2)

- **Feature**: 16 — `side_banner_render_template` (Phase 4)
- **Modulos afectados**: catalog, configuration, rendering, reels, alembic, shared/errors
- **Toca schema?**: Si (2 migraciones nuevas: 0003 properties accent colors + 0004 seed side_banner render template)
- **Plan ejecutado** (7 sub-tareas serializadas 16-A..16-G):
  1. **16-A** Schema + ingestion accent colors: `Property` dataclass + ORM + migracion alembic 0003 + extraccion en `from_api_payload`.
  2. **16-B** Render template config + seed: `SUPPORTED_LAYOUT_VARIANTS = {"classic", "side_banner"}` + migracion alembic 0004 con INSERT en `render_templates`.
  3. **16-C** Threading accent colors hasta `PropertyRenderData` + fallback `BrandSettings.primary_color` enriquecido en `ingest_property_into_reel.py` (via `uow.configuration.brand` singular, no `brands` como decia el spike).
  4. **16-D** Layout branching por `layout_variant` (kwarg en `build_overlay_layout`, `outer_margin=0` y top panel ~65% cuando `side_banner`).
  5. **16-E** FFmpeg colores parametrizables (`top_panel_color`, `bottom_panel_color`, `text_override_color`, `vertical_banner_*`) + helper `apply_alpha_to_hex` + `resolve_text_color` con override.
  6. **16-F** Banner vertical rotado via ffmpeg puro (`drawbox+drawtext+transpose=1`); PIL evitado por no estar en requirements.
  7. **16-G** Tests integration end-to-end + `docs/API.md` con nuevo template + dos campos webhook.
- **Pass 2 - nits del reviewer 1a vuelta** (4 nits resueltos):
  - Nit 1 VERDE: import `apply_alpha_to_hex` movido al top en `poster.py:24`.
  - Nit 2 VERDE: helper `is_valid_hex_color()` en `shared/errors/validation.py` + warning-but-fallback en `ingest_property_into_reel.py:140`.
  - Nit 3 VERDE: golden snapshot del filter graph classic en `tests/unit/rendering/test_overlay_filter_classic_snapshot.py` (2 tests deterministicos).
  - Nit 4 AMARILLO documentado: drift en `docs/openapi.json` + `docs/http_surface.md` consolidado conscientemente (+4 routes, 2 de feature 16/15 + 2 de feature 10 pre-existente; atribucion verificable).
- **Verificacion final**:
  - `pytest -q` → 640 passed, 3 failed (los 3 pre-existentes sobre `configured_worker_count` en `/health`, NO relacionados; baseline 547 → +93 tests nuevos sumados a lo largo de pass-1 + pass-2).
  - `bash ./init.sh` → exit 0.
  - `python -m apps.api --check` y `python -m apps.worker --check` → exit 0.
  - Alembic cycle (0003 + 0004) `upgrade head` / `downgrade -1` x2 / `upgrade head` → verde. `alembic check` → schema y ORM en sync.
- **Entregables**:
  - `progress/explore_feature_16_side_banner_template.md` (plan maestro consolidado).
  - `progress/explore_feature_16_ingestion_accent_colors.md` (sub-spike A).
  - `progress/explore_feature_16_layout_side_banner.md` (sub-spike B).
  - `progress/impl_16_side_banner.md` (informe del implementer, pass-1 + pass-2).
  - `progress/review_16_side_banner.md` (review pass-1 con 4 nits + pass-2 final APPROVED).
  - 2 migraciones alembic: `20260513_0003_add_property_accent_colors.py`, `20260513_0004_seed_side_banner_render_template.py`.
  - Helper nuevo: `shared/errors/validation.py::is_valid_hex_color`.
  - `docs/API.md`, `docs/http_surface.md`, `docs/openapi.json` actualizados.
- **Decisiones de diseno** (alineadas con usuario en la sesion):
  - Alcance: reel + poster (mismo `layout_variant`).
  - Color toning: alpha overlay `@0.85` en drawbox (rebajar sin remapear HSL).
  - Banner texto: dinamico via `build_status_ribbon_text(property_data)`.
  - Fallback color: `BrandSettings.primary_color` de la agencia.
  - Naming: `template_id="side_banner"`, `display_name="Side Banner"`, `sort_order=1`.
- **Veredicto reviewer pass-2**: APPROVED sin reservas. Cero regresiones, cero imports inter-modulo prohibidos, cero tests eliminados.

## 2026-05-13 — feature 17 side_banner_ribbon_polish

# Sesion actual

> Este archivo se vacia al cerrar cada sesion y se mueve a `history.md`.
> Mientras trabajas, **mantenlo actualizado en tiempo real**, no al final.

- **Feature en curso:** 17 — side_banner_ribbon_polish
- **Inicio:** 2026-05-13
- **Agente:** implementer
- **Modulos afectados:** `modules/rendering/infrastructure/preparation.py`, `modules/rendering/infrastructure/layout/panels.py`
- **Toca schema?:** no

## Plan

- Anadir constante `_SIDE_BANNER_RIBBON_BACKGROUND = "#FECF4D"` en `preparation.py` (hardcode temporal documentado en comentario).
- Usar la constante en la llamada a `_render_vertical_status_banner` y forzar `alpha=1.0` en el `apply_alpha_to_hex` del drawbox de fondo (rama principal + fallback). Subir `body_height` a `max(420, round(settings.height * 0.325))`. Bajar `font_size` rotado a `max(20, round(horizontal_height * 0.40))`. Mantener `text_hex` dinamico.
- En `panels.py`, mover BER badge en `side_banner`: `side_ber_x = round(width * 0.36)`.
- Actualizar `tests/unit/rendering/test_layout_composition_side_banner.py` (BER x: 0.36) y anadir un test nuevo que verifique que `_render_vertical_status_banner` recibe `background_hex='#FECF4D'` ignorando el accent_background_color de la propiedad (mockeando `subprocess.run`).
- Verificacion final: `pytest tests/unit/rendering/ tests/integration/rendering/`, `apps.api --check`, `apps.worker --check`.

## Bitacora

- Leidas spec 16 + 17, panels/preparation/formatting + apply_alpha_to_hex; el helper retorna `0xRRGGBB@A`. Con `alpha=1.0` quedaria `0xfecf4d@1.00`, formato valido para `drawbox=color=...` en ffmpeg.
- No hay tests existentes que asercien sobre alpha 0.85 del banner vertical, font_size del ribbon, ni body_height: el unico cambio en tests existentes es el BER x del side_banner.
- Aplicados los 4 cambios surgicales: constante `_SIDE_BANNER_RIBBON_BACKGROUND="#FECF4D"`, hardcode en llamada a `_render_vertical_status_banner`, `body_height = max(420, round(h*0.325))`, `font_size = max(20, round(h*0.40))`, alpha 1.0 en drawbox (rama principal + fallback), `side_ber_x = round(width*0.36)`.
- Test actualizado: `test_layout_composition_side_banner.py` BER x ahora `round(1080 * 0.36)`.
- Test nuevo: `tests/unit/rendering/test_preparation_side_banner_ribbon_hardcode.py` (4 tests; constante, subprocess captura, `inspect.getsource` wiring, body_height >= 0.325).
- Verificacion: `pytest tests/unit/rendering/ tests/integration/rendering/` 121 passed; `apps.api --check` exit 0; `apps.worker --check` exit 0; `bash ./init.sh` exit 0 (3 fallos baseline ya documentados en sesion previa).

## Proximo paso

- Pasar a reviewer. Informe completo en `progress/impl_17_side_banner_ribbon_polish.md`. No marcar `done` hasta que el reviewer apruebe.
- **Cierre**: feature 16 `status: "done"` en `feature_list.json`.

## 2026-05-14 — feature 19: include_pinterest_in_reel_defaults_platforms

- **Resultado:** done (APPROVED por review local, 0 blockers, 1 nit informativo).
- **Archivos principales:**
  - `alembic/versions/20260514_0001_include_pinterest_in_reel_defaults.py` (NEW) — `revision="20260514_0001"`, `down_revision="20260513_0005"`.
  - `modules/configuration/infrastructure/orm.py` — `server_default` de `AgencyReelDefaultsORM.platforms` sincronizado con el array de 7 plataformas.
  - `docs/API.md` §3 — default canónico actualizado y nota referenciando la migración y la decisión de downgrade.
  - `tests/integration/configuration/test_pinterest_in_reel_defaults_platforms.py` (NEW) — 3 tests integración.
- **Cambios clave:**
  - `ALTER COLUMN agency_reel_defaults.platforms SET DEFAULT ARRAY['tiktok','instagram','linkedin','youtube','facebook','gbp','pinterest']::text[]` (la columna es `text[]`, no JSONB; sintaxis adaptada).
  - Data migration idempotente: `UPDATE agency_reel_defaults SET platforms = array_append(platforms, 'pinterest') WHERE NOT ('pinterest' = ANY(platforms))`.
  - `downgrade()` revierte solo el `server_default`; deliberadamente NO arranca pinterest de filas existentes (decisión documentada en el docstring de la migración para preservar configuración intencional del usuario).
- **Tests reportados:**
  - `pytest tests/integration/configuration/test_pinterest_in_reel_defaults_platforms.py -q`: 3 passed.
  - `pytest tests/integration/configuration/ -q`: 64 passed (61 baseline + 3 nuevos).
  - `bash ./init.sh`: exit 0 (los 3 fallos baseline de `test_http_surface_contract.py` y `test_http_transport.py` siguen iguales, no introducidos por feature 19).
  - `apps.api --check` y `apps.worker --check`: exit 0.
  - `alembic heads`: `20260514_0002` (la migración del hotfix de Codex `classic_render_template_preview` quedó encadenada con `down_revision="20260514_0001"`).
- **Documentos:** `progress/impl_19_include_pinterest_in_reel_defaults_platforms.md`, `progress/review_19_include_pinterest_in_reel_defaults_platforms.md`.

## 2026-05-14 — feature 20: extend_social_templates_payload_with_title_and_hashtags

- **Resultado:** done (APPROVED por review local, 0 blockers; 4 nits/fyi puramente documentales, sin cambios de código requeridos).
- **Archivos principales:**
  - Transport: `modules/configuration/transport/payloads/social_templates.py` (union `str | SocialTemplateRichPayload`), `modules/configuration/transport/http/social_templates_router.py` (`_normalize_templates`, `_collect_unknown_template_variables` ampliado a `title_template`, nuevos `_collect_hashtag_errors` y `_invalid_hashtag_response`).
  - Domain: `modules/configuration/domain/agency_settings.py` (nuevo `SocialTemplateUpsert`), `modules/configuration/domain/social_templates_variables.py` (`HASHTAG_PATTERN`, `MAX_HASHTAGS_PER_PLATFORM=30`, `is_valid_hashtag`, `find_invalid_hashtags`), `modules/configuration/domain/__init__.py`.
  - Application/Infrastructure: `modules/configuration/application/use_cases/replace_social_templates.py`, `modules/configuration/infrastructure/social_template_repository.py` (persiste los 3 campos vía `upsert`).
  - Reels/ingestion pipeline: `modules/reels/domain/types.py` (`SocialPublishContext` con `social_title_templates` y `social_hashtags`, `from_dict`/`to_dict` backward-compat), `modules/reels/application/content_generator.py` (`append_hashtags`, render de title), `modules/reels/application/use_cases/_ingest_property_planning.py`, `modules/ingestion/application/use_cases/ingest_wordpress_property.py`.
  - Tests: `tests/integration/configuration/test_social_templates_router.py` (+6), `tests/unit/configuration/test_social_templates_payload.py` (nuevo), `tests/unit/configuration/test_social_templates_hashtags.py` (nuevo), `tests/unit/reels/test_content_generator_hashtags_and_titles.py` (nuevo), `tests/unit/configuration/test_replace_social_templates.py` (+1), `tests/unit/ingestion/test_ingest_wordpress_property.py` (+1), `tests/unit/configuration/_uow_stubs.py` (firma rica).
  - Docs: `docs/API.md` (shape union, 2 códigos 422 y regla de concatenación de hashtags).
- **Cambios clave:**
  - Payload union backward-compat: el PUT acepta `dict[str, str]` legacy y `dict[str, {description_template, title_template, hashtags}]` rico; el GET mantiene `templates: dict[str, str]` y expone los 3 campos en `items[]` (no breaking).
  - Pipeline title+hashtags: `content_generator` renderiza `title_template` con las mismas variables canónicas y concatena hashtags al final de la descripción con separador `\n\n`; `PublishMediaRequest.title` (preexistente) se rellena vía `publish_titles_by_platform` para redes que lo soportan (Pinterest, YouTube).
  - Validaciones nuevas: `SOCIAL_TEMPLATE_UNKNOWN_VARIABLE` con shape mixto (lista plana para description-only, dict `{description_template, title_template}` cuando title participa) y `SOCIAL_TEMPLATE_INVALID_HASHTAG` con `details.hashtag_errors_by_platform[platform] = {invalid:[...], count, max}`.
- **Tests reportados:**
  - `pytest tests/integration/configuration/test_social_templates_router.py -q`: 15 passed (9 originales + 6 nuevos).
  - `pytest tests/unit/configuration/test_social_templates_payload.py tests/unit/configuration/test_social_templates_hashtags.py tests/unit/reels/test_content_generator_hashtags_and_titles.py -v`: 22 passed.
  - `pytest tests/integration/reels/ -q`: 29 passed.
  - `pytest -q` global: 3 failed, 699 passed (los 3 fallos = baseline preexistente: `test_http_surface_contract` + 2 `test_http_transport`).
  - `apps.api --check` y `apps.worker --check`: exit 0.
  - `alembic heads`: `20260514_0002` (sin cambios, feature 20 no añade migración).
- **Documentos:** `progress/impl_20_extend_social_templates_payload_with_title_and_hashtags.md`, `progress/review_20_extend_social_templates_payload_with_title_and_hashtags.md`.

## 2026-05-14 — feature 21: per_reel_description_override_endpoint

- **Resultado:** done (APPROVED por review local, 0 blockers, 0 cambios solicitados; cierre del lado backend — frontend pendiente como cross-repo).
- **Archivos principales:**
  - Schema/ORM: `alembic/versions/20260514_0003_reels_descriptions_override.py` (NEW; `down_revision="20260514_0002"`), `shared/db/orm.py` (`reels.descriptions_override` JSONB nullable).
  - Dominio + persistencia: `modules/reels/domain/reel_state.py` (campo `descriptions_override`), `modules/reels/infrastructure/reel_state_repository.py` (helpers `_override_to_jsonb_param` / `_jsonb_to_optional_mapping`, INSERT con `CAST(:descriptions_override AS jsonb)`, propagación en `ON CONFLICT DO UPDATE` y en `update_publish_status`/`update_workflow_state`/`save_local_artifacts`).
  - Aplicación: `modules/reels/application/use_cases/update_reel_descriptions_override.py` (NEW), `modules/reels/application/use_cases/ingest_property_into_reel.py` (helper `_apply_descriptions_override` aplicado tras calcular `publish_descriptions_by_platform` y antes del snapshot), `modules/reels/application/use_cases/_ingest_property_assets.py` (propaga `state.descriptions_override` en re-ingest).
  - Transport: `modules/reels/transport/payloads/reel_descriptions_override.py` (NEW; `extra='forbid'`), `modules/reels/transport/http/admin_reels_router.py` (PATCH `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/descriptions` con mapping 404/409/422).
  - Docs: `docs/API.md`, `docs/http_surface.md`.
  - Tests: `tests/integration/reels/test_admin_reels_descriptions_override.py` (NEW, 7 tests), `tests/unit/reels/test_ingest_applies_descriptions_override.py` (NEW, 5 tests).
- **Cambios clave:**
  - Override per-reel en columna nueva `reels.descriptions_override` (JSONB nullable, default NULL); `None` y `{}` mapean al mismo sentinel SQL NULL, así `WHERE descriptions_override IS NULL` sigue siendo equivalente a "no override".
  - Worker honra la precedencia override → snapshot: el merge per-platform se aplica en `IngestPropertyIntoReelUseCase` justo antes de construir `publish_target_snapshot`, así tanto la ingestión inicial como el flujo approve→publish (que re-encola un job que pasa por `ReelPipeline.handle` → ingest → publish) ven el override en `context.publish_descriptions_by_platform`. `publish_reel.py` queda intacto.
  - Endpoint PATCH con state guard: solo edita reels en `publish_status in {needs-approval, pending_review, pending, ''}`; estados terminales rechazan con **409 `REEL_NOT_EDITABLE`** (semántico, en vez del genérico `RESOURCE_LOCKED`); platform fuera de `agency_reel_defaults.platforms` → **422 `PLATFORM_NOT_ENABLED`**; cuerpo con campo extra → 422 (Pydantic `extra='forbid'`).
  - Path real del endpoint adaptado al esquema de tupla del router admin: `(agency_id, site_id, source_property_id)` en vez del `reel_id` UUID literal del plan (no existe ningún endpoint admin que use UUID).
- **Tests reportados:**
  - `pytest tests/integration/reels/test_admin_reels_descriptions_override.py tests/unit/reels/test_ingest_applies_descriptions_override.py -q`: 12 passed.
  - `pytest tests/integration/reels/ tests/unit/reels/ -q`: 123 passed.
  - `pytest -q` global vía `bash ./init.sh`: 711 passed, 3 fallos baseline preexistentes (`test_http_surface_contract` + 2 `test_http_transport`).
  - `apps.api --check` y `apps.worker --check`: exit 0.
  - `alembic upgrade head` / `downgrade -1` / `upgrade head`: OK.
  - `alembic heads`: `20260514_0003` (head única, encadenada tras el hotfix Codex `20260514_0002_classic_render_template_preview`).
- **Documentos:** `progress/impl_21_per_reel_description_override_endpoint.md`, `progress/review_21_per_reel_description_override_endpoint.md`.

## 2026-05-14 — feature 22: agency_music_upload (back)

- **Resultado:** done (APPROVED por review local, 0 blockers; 1 fyi cleanup-on-fail ordering, 1 nit kwarg muerto, 4 fyi informativos).
- **Archivos principales:**
  - Transport (nuevo): `modules/configuration/transport/http/music_upload_router.py` (multipart parser stdlib + `POST /music/upload` + `GET /music/{music_id}/file/{filename}`).
  - Transport (modificado): `modules/configuration/transport/http/music_router.py` (POST metadata-only retirado a 405; PUT ya no propaga `object_key`/`duration_seconds`), `modules/configuration/transport/payloads/music.py` (`MusicTrackPatchPayload` reducido a `display_name`+`is_default`, `extra='forbid'`).
  - Application (nuevo): `modules/configuration/application/use_cases/upload_music_track.py` (`UploadMusicTrackUseCase` con atomic write → ffprobe → register + cleanup-on-fail).
  - Storage: `shared/storage/site_layout.py` (`resolve_agency_music_destination`, `resolve_agency_music_local_path`, constante `AGENCY_MUSIC_UPLOAD_DIRNAME`).
  - Wiring: `apps/api/app_factory.py` (include del router nuevo).
  - Docs: `docs/API.md`, `docs/http_surface.md`, `docs/openapi.json` regenerado.
  - Tests: `tests/integration/configuration/test_music_upload_router.py` (11), `tests/integration/configuration/test_music_router.py` (refresh 7), `tests/unit/configuration/test_upload_music_track.py` (5), fixtures `tests/integration/configuration/_fixtures/`.
- **Cambios clave:** `POST /v1/admin/agencies/{id}/music/upload` recibe multipart (file + display_name + is_default) y persiste el blob bajo la carpeta de la agencia derivando `object_key` y `duration_seconds` vía `ffprobe`; `GET .../music/{music_id}/file/{filename}` streamea el blob con admin auth scope-checked; el POST metadata-only queda retirado a 405 y el PUT bloquea `object_key`/`duration_seconds` con 422 (`extra='forbid'`); helper `resolve_agency_music_destination` en `shared/storage/site_layout` para tener S3 enchufable mañana sin tocar HTTP.
- **Tests reportados:**
  - `pytest tests/integration/configuration/test_music_upload_router.py tests/integration/configuration/test_music_router.py tests/unit/configuration/ -v`: 134 passed (11 upload + 7 router + 5 unit + resto suite configuration).
  - `pytest tests/integration/configuration/ tests/integration/tenancy/ -q`: 89 passed.
  - `bash ./init.sh`: exit 0 — 731 passed, 3 fallos baseline preexistentes (`test_http_surface_contract` + 2 `test_http_transport`), sin nuevos fallos introducidos.
  - `apps.api --check` y `apps.worker --check`: exit 0.
  - `alembic heads`: `20260514_0004` (sin nueva migración para feature 22; head única encadenada tras feature 21).
- **Documentos:** `progress/impl_22_agency_music_upload_back.md`, `progress/review_22_agency_music_upload.md`.
- **Cross-repo:** Frontend feature 22 sigue `in_progress` (code-complete awaiting back deploy). Tras el reinicio del API+worker quedará pendiente solo la verificación manual cross-repo para cerrarla.

## 2026-05-14 — feature 23: wire_render_to_agency_music_tracks (back)

- **Resultado:** done (APPROVED por review local).
- **Archivos principales:**
  - Alembic: `alembic/versions/20260514_0005_seed_existing_agencies_with_ncs_music_tracks.py` (NEW; seed por agencia + copia de blobs con marker `_seed_ncs_`).
  - Rendering/runtime: `modules/rendering/infrastructure/runtime/assets.py` (`resolve_background_audio_paths` con kwarg `music_tracks`, helper nuevo `resolve_agency_music_local_paths`), `modules/rendering/infrastructure/preparation.py`, `modules/rendering/infrastructure/manifest.py`, `modules/rendering/infrastructure/readiness.py` (3 call sites en lockstep), `modules/rendering/infrastructure/default_media_renderer.py` (propaga `music_tracks=` a `prepare_reel_render_assets`).
  - Reels application: `modules/reels/application/use_cases/_resolve_agency_music_pool.py` (NEW; default → library → raise `MUSIC_NO_TRACKS`), `modules/reels/application/use_cases/ingest_property_into_reel.py` (resuelve candidatos antes del render), `PropertyContext` extendido con `background_audio_candidates`.
  - Configuration/domain: lectura de tracks vía repositorio existente de `agency_music_tracks`.
  - Tenancy/application: `modules/tenancy/application/use_cases/register_agency.py` (hook seed tras social_templates: `seed_default_music_tracks_for_agency`).
  - Tests: `tests/integration/rendering/`, `tests/unit/rendering/`, `tests/integration/reels/` (20 tests nuevos cubriendo agency con/ sin default, library fallback, MUSIC_NO_TRACKS, cross-agency isolation, blob ausente).
  - Docs: `docs/API.md` (sección Rendering), `REFACTOR_STATUS.md`.
- **Cambios clave:** Migración `20260514_0005` semilla cada agencia preexistente con copia propia de las 4 NCS y dispara hook idéntico en `RegisterAgencyUseCase` para agencias nuevas; `resolve_background_audio_paths` acepta kwarg opcional `music_tracks` que tiene prioridad sobre el scan legacy de `assets/music/` (fallback dev preservado); helper `resolve_agency_music_local_paths` traduce `object_key`→`Path` y nuevo `_resolve_agency_music_pool` aplica la regla default→library→raise, con marker `_seed_ncs_` para que el downgrade selectivo solo borre lo creado por la migración.
- **Tests reportados:** 752 passed, 3 baseline failed, 20 tests nuevos.
- **Documentos:** `progress/impl_23_wire_render_to_agency_music_tracks.md`, `progress/review_23_wire_render_to_agency_music_tracks.md`, `progress/explore_23_render_to_agency_music_tracks.md`.
- **Bloquea-resuelto:** features 24 y 25 pueden arrancar.
- **Cross-repo:** Frontend feature 23 es noop (sin cambios de código); el leader la marcará done en el siguiente paso.

## 2026-05-14 — feature 24: agency_music_selection_rules (back)

- **Resultado:** done (APPROVED por review local).
- **Archivos principales:** modules/configuration/transport/payloads/defaults.py (SettingsMusicPayload + SettingsMusicSelectionRulesPayload, validator), modules/configuration/application/use_cases/{update_aggregated_reel_profile.py, read_aggregated_reel_profile.py} (asimétrico read/write + helper resolve_music_selection_rules), modules/reels/application/use_cases/_resolve_agency_music_pool.py (acepta fallback_to_full_library kwarg), modules/reels/application/use_cases/ingest_property_into_reel.py (helper _resolve_music_selection_rules), tests, docs/API.md.
- **Cambios clave:** payload Pydantic anidado opcional bajo settings.music.selection_rules.fallback_to_full_library (extra='forbid' en ambas capas; default true surfaced solo en GET). _resolve_agency_music_pool honra el flag: default vacío + false → MUSIC_NO_DEFAULT_TRACKS; true → fallback a library (comportamiento previo).
- **Tests reportados:** 763 passed, 3 baseline failed (sin regresión). Tests específicos: 224 passed.
- **Documentos:** progress/impl_24_agency_music_selection_rules.md, progress/review_24_agency_music_selection_rules.md.
- **Caveats follow-up (no bloqueantes):** (1) update_reel_defaults usa merge shallow a settings.*; si feature 25 añade hermanas a music.selection_rules, considerar deep merge; (2) error code Pydantic `extra_forbidden` cuando se manda clave desconocida bajo settings.music.* — coincide con "equivalente" del acceptance.
- **Cross-repo:** Frontend feature 24 sigue pending; el leader la arrancará en el siguiente paso tras reiniciar servicios.

## 2026-05-14 — feature 25: per_reel_music_override (back)

- **Resultado:** done (APROBADO por review local).
- **Archivos principales:** alembic/versions/20260514_0006_reels_music_id_override.py, shared/db/orm.py (columna nueva), modules/reels/{domain/reel_state.py, infrastructure/reel_state_repository.py, application/use_cases/update_reel_music_override.py, application/use_cases/_ingest_property_planning.py, application/use_cases/regenerate_reel.py, transport/payloads/reel_music_override.py, transport/http/admin_reels_router.py}, modules/reels/domain/types.py (SocialPublishContext.override_music_track_id), tests, docs/API.md, docs/http_surface.md.
- **Cambios clave:** PATCH /v1/admin/agencies/{a}/reels/{s}/{p}/music (body {music_id: str|null}) persiste override y re-encola job de render con override_music_track_id en publish_context. Worker sustituye la pool por la pista única; si la track fue borrada en race → warning + fallback a pool default. Cross-agency colapsado a 404 ADMIN_MUSIC_TRACK_NOT_FOUND (no leak existencia). Estados editables iguales que feature 21 (needs-approval/pending_review/pending/'').
- **Tests reportados:** 778 passed, 3 baseline failed (sin relación). 15 tests nuevos focalizados (9 integration + 6 unit).
- **Documentos:** progress/impl_25_per_reel_music_override.md, progress/review_25_per_reel_music_override.md.
- **Caveats follow-up (no bloqueantes):** (1) `_maybe_enqueue_publish_job` duplicado entre update_music_override y regenerate_reel; (2) PATCH no fuerza transición de workflow_state; (3) import privado `_EDITABLE_PUBLISH_STATUSES` desde feature 21.
- **Bloquea-resuelto:** backlog música completo (22-24 ya done, 25 cerrada). Frontend 25 sigue pending; el leader la arrancará tras este cierre.
- **Cross-repo:** Frontend feature 25 pending — selector de pista per-reel en /reels editor.

## 2026-05-14 — feature 28: font_catalog_and_brand_font_in_render (back)

- **Resultado:** done (APPROVED por review local).
- **Archivos principales:** assets/fonts/{Manrope,Plus_Jakarta_Sans,Montserrat,Poppins,Roboto}/{Regular.ttf,Bold.ttf,OFL.txt}, modules/configuration/domain/font_catalog.py, modules/configuration/application/use_cases/list_available_fonts.py, modules/configuration/transport/http/fonts_router.py, modules/configuration/transport/payloads/brand.py (validator), modules/reels/application/use_cases/ingest_property_into_reel.py (_resolve_brand_font_descriptor + inyección al render dict), apps/api/app_factory.py (montar router), tests, docs/API.md, docs/http_surface.md, docs/openapi.json.
- **Cambios clave:** catálogo Google OFL de 6 fuentes (Inter+Manrope+Plus Jakarta Sans+Montserrat+Poppins+Roboto) servido por GET /v1/admin/fonts; Pydantic validator UNKNOWN_FONT_FAMILY en BrandSettingsUpsertPayload.font_family (Option A: mensaje en detail[0].msg con allowed families); ingest resuelve FontDescriptor por agency.brand.font_family (fallback Inter con warning si la family está fuera de catálogo) e inyecta font_path/bold_font_path en render_template_reel_settings + _poster_settings. Renderer ya consumía el atributo del template; no requirió cambios.
- **Tests reportados:** 803 passed, 3 baseline failed (sin regresión). 35 tests nuevos focalizados (13 unit catalog + 3 integration fonts router + 4 brand router + 3 ingest injection + suites colaterales).
- **Documentos:** progress/impl_28_..., progress/review_28_..., progress/explore_brand_colors_and_fonts.md, progress/design_email_notifications_and_brand_customisation.md.
- **Follow-ups no bloqueantes:** (1) Option B del 422 (handler RequestValidationError que serialice allowed_families como objeto) si el frontend lo necesita programático; (2) 4 fuentes (Manrope/PJS/Montserrat/Roboto) tienen Bold = Regular duplicado del TTF variable upstream — estético, no funcional; (3) docstring de _resolve_brand_font_descriptor dice "three axes" pero cubre 5-6 caminos.
- **Cross-repo:** Frontend feature 28 sigue pending (dropdown dinámico + reset to default); el leader la arrancará tras este cierre y reinicio.

## 2026-05-14 — feature 29: secondary_color_side_banner (back, sin frontend counterpart)

- **Resultado:** done (APPROVED por review local).
- **Archivos principales:** modules/reels/application/use_cases/ingest_property_into_reel.py (_resolve_brand_secondary_color + key side_banner_ribbon_background_color en render_template_reel_settings), modules/rendering/application/scripted_video/frame_composition.py (_build_render_data lifte la key + _RENDERER_INTERNAL_OVERRIDE_KEYS), modules/rendering/application/scripted_video/models.py (PropertyRenderData.side_banner_ribbon_background_color), modules/rendering/infrastructure/preparation.py:209,236 (call site del fallback + constante preservada), tests, docs/API.md.
- **Cambios clave:** Cascada de 2 niveles BrandSettings.secondary_color → #FECF4D (el webhook WP no trae color secundario; el feed solo tiene wppd_accent_text/background consumidos como par primario por feature 16). El render del template side_banner ahora lee side_banner_ribbon_background_color del template; classic intacto. Hotfixes Codex en filters.py y panels.py NO tocados.
- **Tests reportados:** 811 passed, 3 baseline failed (sin regresión). 8 tests nuevos (3 integration rendering + 1 integration reels-2 casos + 1 unit composition + 1 unit settings + 2 unit preparation).
- **Documentos:** progress/impl_29_secondary_color_side_banner.md, progress/review_29_secondary_color_side_banner.md.
- **Cadena brand customisation completa:** feature 28 (font_catalog + dynamic dropdown + reset) + feature 29 (secondary_color en side_banner) cerradas. Features 26-27 (email notifications) siguen pending por decisión del usuario.

## 2026-05-15 — feature 31: subtitle_settings_wiring (back)

- **Resultado:** done (APPROVED por review local).
- **Archivos principales:** modules/rendering/infrastructure/models.py (SubtitleStyle en PropertyRenderData), modules/rendering/infrastructure/render_template_settings.py (_RENDERER_INTERNAL_OVERRIDE_KEYS +11 keys), modules/rendering/application/frame_composition.py (_build_subtitle_style + propagación), modules/rendering/infrastructure/layout/subtitles.py (max_chars + position + uppercase + alignment), modules/rendering/infrastructure/ffmpeg/filters.py (drawtext con SubtitleStyle + skip si enabled=False), modules/reels/application/use_cases/ingest_property_into_reel.py (_resolve_subtitle_settings_overrides), modules/configuration/domain/font_catalog.py (resolve_weighted), tests.
- **Cambios clave:** 10 settings sub* + auto_captions cableados end-to-end desde defaults.settings hasta el filter graph ffmpeg. `pill` colapsa a `block` en MVP. `font_family` desconocida → fallback al subtitle_font_path legacy. Color default subtítulo cambia de 0xF4D03F a 0xffffff alineado con el preview del front.
- **Tests reportados:** 842 passed, 3 baseline failed; 21 tests nuevos (5 font_catalog + 7 unit subtitle_style + 9 integration wiring).
- **Documentos:** progress/impl_31_subtitle_settings_wiring.md, progress/review_31_subtitle_settings_wiring.md.
- **Cross-repo:** Frontend feature 31 (cleanup + autoCaptions switch) sigue pending; el leader la arrancará tras este cierre y reinicio.

## 2026-05-15 — feature 26: email_notification_infrastructure (back)

- **Resultado:** done (APPROVED por review local).
- **Archivos principales:** shared/email/{__init__.py, sender.py, factory.py, backends/__init__.py, backends/console_sender.py, backends/smtp_sender.py}, settings/notifications.py, settings/__init__.py (re-exports), alembic/versions/20260514_0007_email_notifications.py, modules/notifications/{__init__.py, domain/{__init__.py, email_record.py, status.py}, infrastructure/{__init__.py, email_notification_repository.py}}, shared/db/uow.py (NotificationsNamespace.emails), .env.example, docs/API.md (sección 7b Notifications), docs/conventions.md, tests/unit/notifications/{test_email_message,test_console_sender,test_smtp_sender,test_factory}.py, tests/integration/notifications/{test_migration_20260514_0007,test_email_notification_repository}.py.
- **Cambios clave:** Capa pura `shared/email/` con `EmailSender` Protocol + dos backends (`ConsoleEmailSender` para dev/tests y `SmtpEmailSender` con stdlib `smtplib`, STARTTLS opcional, auth opcional, `Message-ID` generado vía `email.utils.make_msgid` y conexión cerrada en `finally`). Factory `build_email_sender(settings)` selecciona backend según `EMAIL_BACKEND ∈ {console, smtp}` (otro valor → `ValueError`). `settings/notifications.py::load_notification_settings()` parsea `EMAIL_BACKEND`, `SMTP_HOST/PORT/USER/PASSWORD/USE_TLS/FROM_ADDRESS/FROM_NAME`, `FRONTEND_BASE_URL` con defaults seguros. Migración `20260514_0007` crea tabla `email_notifications` (FK agency_id ON DELETE CASCADE + UNIQUE `uq_email_notifications_dedup` sobre (agency_id, site_id, source_property_id, recipient_email, event_kind) + 2 índices status y agency_id+created_at DESC). `EmailNotificationRepository` con `insert_pending` idempotente (`ON CONFLICT DO UPDATE SET updated_at` para devolver siempre la fila), `mark_sent`, `mark_failed`, `find_recent_sent` (preparación throttle de #27), `list_by_agency/status`. Enchufado al UoW como `uow.notifications.emails`. **Sin business logic**: publish_reel intacto, sin handler `email_send` en worker, sin templates — eso es #27.
- **Tests reportados:** 869 passed + 27 nuevos (4 unit + 2 integration), 3 baseline failed sin regresión. `apps.api --check` y `apps.worker --check` exit 0 (kinds=reel_publish, scripted_render).
- **Desviaciones aceptadas:** (1) `EmailRecord.sent_at` como `str` ISO-8601 (no `datetime`) por consistencia con `repository_helpers.isoformat`; la API tipada se preserva en parámetros del repo. (2) `insert_pending` usa `ON CONFLICT DO UPDATE SET updated_at = EXCLUDED.updated_at RETURNING *` (no `DO NOTHING`) para garantizar fila devuelta. (3) Sin `__init__.py` en `tests/unit/notifications/` ni `tests/integration/notifications/` (consistente con hermanos).
- **Documentos:** progress/impl_26_email_notification_infrastructure.md, progress/review_26_email_notification_infrastructure.md, progress/design_email_notifications_and_brand_customisation.md §A, progress/explore_email_notifications_back.md.
- **Cross-repo:** Backlog email continúa. Próximo paso: arrancar back #27 `email_notification_review_requested` (subscriber del outbox + handler worker `email_send` + templates). Frontend #26 (chip editor multi-email en /automation) sigue pending, depende de back #26+#27 desplegadas.

## 2026-05-15 — feature 27: email_notification_review_requested (back + cross-repo close pipeline email)

- **Resultado:** done (APPROVED por review local).
- **Archivos principales:** shared/email/{validators,url_builder,templates}.py, assets/email/templates/review_requested.{txt,html}, modules/notifications/application/{__init__.py, use_cases/{__init__.py, dispatch_review_requested_email.py, send_email_job_handler.py}}, apps/worker/outbox_subscriber.py (NUEVO loop), apps/worker/{runtime.py, main.py}, modules/delivery/infrastructure/outbox_repository.py (+mark_status +claim_pending_event), shared/email/__init__.py, docs/email_notifications.md, docs/API.md (sección 7c Notifications review_requested flow), docs/architecture.md, tests/unit/notifications/{test_review_emails_normaliser, test_url_builder, test_template_renderer}.py, tests/integration/notifications/{test_review_requested_flow, test_review_requested_throttle, test_review_requested_resent, test_email_send_handler_failure}.py.
- **Cambios clave:** Subscriber del outbox (`apps/worker/outbox_subscriber.py`, primer relay real del repo) que polea `outbox_events.status='pending'` por tipo registrado vía `OutboxRepository.claim_pending_event` con `FOR UPDATE SKIP LOCKED LIMIT 1` (multi-worker safe), transición `pending → processing → dispatched|failed`. `DispatchReviewRequestedEmailUseCase` lee `defaults.settings.automation.reviewEmails` (acepta `list[str]` o CSV legacy), normaliza vía `normalise_review_emails` (lowercase + dedup + regex), aplica throttle de 60s por (agency, recipient) vía `find_recent_sent`, resuelve `event_kind` (`review_requested` vs `review_requested_resent` para preservar la UNIQUE en re-envíos), inserta N filas en `email_notifications` y encola 1 job `email_send` con shape rico `{recipient_emails, email_notification_ids, context}`. `SendEmailJobHandler` renderiza plain + HTML (renderer minimal `str.format` + `html.escape`, sin Jinja), manda con el `EmailSender` inyectado y propaga `provider_message_id` a las N filas. Templates en `assets/email/templates/review_requested.{txt,html}` con placeholders `{agency_name}, {property_title}, {property_address}, {reel_url}`. URL builder `build_reel_editor_url(FRONTEND_BASE_URL, site_id, property_id)` con percent-escape del site_id. Worker arranca `OutboxSubscriber` antes del `JobDispatcher` y lo para en `finally`. `--check` reporta `kinds=email_send, reel_publish, scripted_render outbox_events=review_requested`. `publish_reel.py` intacto (0 líneas diff).
- **Tests reportados:** 897 passed + 28 nuevos (10 normaliser + 6 URL + 7 templates en unit; 4 flow + 1 throttle + 1 resent + 1 failure en integration), 3 baseline failed sin regresión.
- **Desviaciones aceptadas:** (1) `mark_status` genérico en `OutboxRepository` en vez de transición ad-hoc por estado — soporta `processing/dispatched/failed` con la misma firma; (2) **Workaround `webhook_events` sintético** con `source_kind='notification'`: el dispatcher inserta una fila previa al `enqueue_job(email_send)` porque el runtime del worker (`JobDispatcher._process_next_job`) hace `update_event_status(event_id)` sobre `webhook_events`. Verificado que ninguna query filtra por `source_kind`, así que no rompe semánticas. Refactor (desacoplar `webhook_events` del runtime) marcado como follow-up no bloqueante; (3) `property_title/property_address` se resuelven en el dispatcher desde `properties.raw_json` (fallback a payload outbox) porque `publish_reel.py` no incluye esos campos en `_build_workflow_payload` y la feature acordó NO tocar el publisher.
- **Documentos:** progress/impl_27_email_notification_review_requested.md, progress/review_27_email_notification_review_requested.md, progress/design_email_notifications_and_brand_customisation.md §A+§D.
- **Cross-repo:** Cierra el pipeline email completo end-to-end. (a) **back #26** done previa — infra `shared/email/` + tabla + repo. (b) **back #27** done con este cierre — subscriber + handler + templates. (c) **front #26** (chip editor multi-email en `/automation`) cerrado autónomamente por el equipo front; ya manda `list[str]` y `normalise_review_emails` mantiene backward compat con CSV legacy. Flujo activo tras restart del :8001: `publish_reel(approval_required) → outbox.review_requested → OutboxSubscriber → DispatchReviewRequestedEmailUseCase → email_notifications×N pending + 1 job email_send → SendEmailJobHandler → EmailSender.send → mark_sent×N`. Próximas features email (publish_completed, etc.) reutilizan el subscriber con un `register_handler` adicional.

## 2026-05-18 — feature 42 galaxy_render_template

# Feature 42 — galaxy_render_template (Claude leader, en curso)

- **Inicio:** 2026-05-18
- **Agente:** Claude (rol leader; ningún subagente lanzado todavía)
- **Toca schema?:** No (data-model intacto; reutiliza cascades side_banner_panel_color + side_banner_ribbon_background_color + accent_*).
- **Modulos afectados:** `modules/rendering/infrastructure/{render_template_settings.py, layout/panels.py, layout/composition.py, ffmpeg/filters.py, preparation.py}`, `alembic/versions/20260518_0001*.py` + `20260518_0002*.py`, `assets/render-templates/galaxy-template.png`, `tests/{unit,integration}/rendering/`, `tests/integration/configuration/test_render_templates_router.py`, `tests/integration/apps_api/test_render_template_assets.py`.

## Plan

- **Referencia visual**: `example-template-galaxy.png` (1054×1492, portrait).
- **Decisiones del usuario (este turno)**:
  - El círculo central con el logo grande (visible en la referencia) se omite en v1.
  - Colores/parámetros del template son modificables verbatim igual que side_banner — cero data-model nuevo.
- **Baseline init.sh antes de delegar**: 3 failed (test_http_surface_contract.py + 2 en test_http_transport.py — históricos), 1063 passed, exit 0.
- **Exploradores ya escritos**:
  - `progress/explore_galaxy_arch.md` — geometría side_banner end-to-end (panels.py, filters.py, preparation.py).
  - `progress/explore_galaxy_seed.md` — schema render_templates, repo, router, app_factory mount, cadena Alembic (HEAD = 20260517_0001).
  - `progress/explore_galaxy_preview.md` — rig de iteración con `generate_property_poster_from_data(..., layout_variant='galaxy')` (~5s por frame, escrito a `progress/galaxy_iter_<N>.png`).
- **Próximo paso**: dispatch implementer iteración 1 (un solo Agent call); el implementer escribe código + tests + migraciones + un PNG iter_1. Yo (leader) comparo visualmente contra `example-template-galaxy.png` y decido si re-iterar antes de lanzar reviewer.

## Bitacora

- 2026-05-18: 3 exploradores lanzados en paralelo (Explore subagent). Uno volcó contenido en chat sin file → leader lo persistió a `progress/explore_galaxy_arch.md`. Otro escribió a `/tmp` → leader lo movió a `progress/`.
- 2026-05-18: Feature 42 abierta en `feature_list.json` con status `pending`. Total features = 39.
- 2026-05-18 14:35: Implementer arranca. Status `pending` → `in_progress`.
- 2026-05-18 14:46: Implementer cierra iteración 1. Reporte en `progress/impl_42.md`. `progress/galaxy_iter_1.png` (1054×1492) generado vía rig visual. `bash ./init.sh` exit 0 con 1087 passed + 3 baseline failed + 1 deselected (visual_iter). Status sigue `in_progress`; el reviewer lo marca `done` tras validar y decidir si promover el iter_1 PNG como asset preview o pedir iteración 2.
- 2026-05-18 15:14: Implementer iter 2 cierra (sección "Iter 2" en `progress/impl_42.md`). Footer ancla a `frame_bottom - bottom_margin`; helper `_resolve_galaxy_panel_radius` (floor `max(24, round(h*0.020))`). `progress/galaxy_iter_2.png` generado. `bash ./init.sh` exit 0 con 1090 passed + 3 baseline failed.
- 2026-05-18 15:30: Implementer iter 3 arranca. Plan acotado:
  1. `panels.py compose_bottom_panel`: elevar floor `bottom_panel_height` galaxy de `max(round(h*0.113), …)` a `max(round(h*0.150), …)` (~224 px @ 1492); recalcular `bottom_panel.y` con la nueva altura conservando la fórmula iter 2 (`y = frame_height - bottom_panel_height - max(20, round(h*0.018))`).
  2. `panels.py bottom_font_bounds`: bumpear bounds galaxy para `agent_name` (max 32, round h*0.022 / min 26) y `agent_phone|agent_email|agency_psra` (max 26, round h*0.017 / min 22). Side_banner conserva sus bounds; se diferencia vía un flag `is_galaxy`.
  3. Actualizar tests galaxy con la nueva fórmula + comentario `# iter 3: chunky footer + bigger agent text`. No tocar side_banner ni classic.
  4. Generar `progress/galaxy_iter_3.png` vía rig visual.
  5. Verificación focal galaxy + regression side_banner + `bash ./init.sh`.
- 2026-05-18 15:44: Implementer iter 3 cierra (sección "Iter 3" en `progress/impl_42.md`). Cambios: `panels.py` desdobla `bottom_font_bounds` y `bottom_panel_height` por variant (galaxy vs side_banner) sin helper nuevo. Tests galaxy +3 nuevos + 1 assert nuevo (chunky footer + bigger agent text + low-res floor). `progress/galaxy_iter_3.png` generado: footer claramente chunky, agent_name visiblemente bolder que contact rows. `bash ./init.sh` exit 0 con **1093 passed** + 3 baseline failed + 1 deselected. Side_banner / classic regression verde (38 passed). Status sigue `in_progress`; el reviewer decide si promover el iter_3 PNG como asset preview o pedir más iteración.
