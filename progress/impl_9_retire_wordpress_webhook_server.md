# impl_9 — retire_wordpress_webhook_server

> Implementación de la feature 9 (`feature_list.json[id=9]`). Estado actual:
> `in_progress`. Pendiente de revisión por el reviewer / cierre admin.

## Resumen

- Borrada la god-class `WordPressWebhookServer` y la fábrica
  `create_fastapi_app` de `services/transport/http/server.py` (1436 LoC).
- Borrados también `services/transport/http/openapi_docs.py` (644 LoC) y
  `services/transport/http/uvicorn_protocols.py` (276 LoC).
- Borrado el servicio legacy `application/admin/wordpress_source_management.py`
  y su `__init__.py` (paquete entero) — ningún call site queda.
- `apps/api/app_factory.py` ahora construye `FastAPI()` directo: middlewares,
  `lifespan` con `_NoopDispatcher`, `AdminAccessPolicy` vía helper, e incluye
  los 16 routers (12 existentes + 4 nuevos creados en esta feature).
- `apps/api/main.py` actualizado: ya no consume `server.app`/`server.runtime`;
  recibe `FastAPI` desnudo de `build_api_app`.
- Tests adaptados: `tests/integration/test_http_transport.py` ya no importa
  de `services.transport.http.server`. Baseline pre-feature 331 tests →
  376 verdes (45 nuevos, ningún test perdido).

## Archivos creados

| Tipo | Path |
|------|------|
| Router (transport) | `apps/api/health_router.py` |
| Helper (transport) | `apps/api/host_filter.py` |
| Helper (admin auth) | `apps/api/admin_auth.py` (nueva función `build_admin_access_policy`) |
| Router (transport) | `modules/ingestion/transport/http/wordpress_sources_router.py` |
| Payload | `modules/ingestion/transport/payloads/wordpress_sources.py` |
| Use case | `modules/ingestion/application/use_cases/list_global_wordpress_sources.py` |
| Use case | `modules/ingestion/application/use_cases/inspect_wordpress_source_by_site_id.py` |
| Use case | `modules/ingestion/application/use_cases/provision_wordpress_source.py` |
| Helper internal | `modules/ingestion/application/use_cases/_wordpress_support.py` |
| Router (transport) | `modules/configuration/transport/http/reel_profile_router.py` |
| Payload | `modules/configuration/transport/payloads/reel_profile.py` |
| Use case | `modules/configuration/application/use_cases/read_aggregated_reel_profile.py` |
| Use case | `modules/configuration/application/use_cases/update_aggregated_reel_profile.py` |
| Router (transport) | `modules/publishing/transport/http/social_accounts_router.py` |
| Use case | `modules/publishing/application/use_cases/inspect_agency_social_accounts.py` |
| Test (unit) | `tests/unit/apps_api/test_host_filter.py` |
| Test (unit) | `tests/unit/apps_api/test_build_admin_access_policy.py` |
| Test (unit) | `tests/unit/configuration/test_read_aggregated_reel_profile.py` |
| Test (unit) | `tests/unit/configuration/test_update_aggregated_reel_profile.py` |
| Test (unit) | `tests/unit/ingestion/test_list_global_wordpress_sources.py` |
| Test (unit) | `tests/unit/ingestion/test_inspect_wordpress_source_by_site_id.py` |
| Test (unit) | `tests/unit/ingestion/test_provision_wordpress_source.py` |
| Test (unit) | `tests/unit/publishing/test_inspect_agency_social_accounts.py` |
| Test (integration) | `tests/integration/apps_api/test_health_router.py` |
| Test (integration) | `tests/integration/ingestion/test_wordpress_sources_global_router.py` |
| Test (integration) | `tests/integration/configuration/test_reel_profile_router.py` |
| Test (integration) | `tests/integration/publishing/test_social_accounts_router.py` |

## Archivos modificados

| Path | Cambio |
|------|--------|
| `apps/api/app_factory.py` | Reescrito: ahora compone `FastAPI()` directo, expone kwargs override (`admin_api_*`, `gohighlevel_app_shared_secret`, `webhook_auto_provision_unknown_sites_for_testing`, `site_secrets`, `enable_docs`, `security_disabled`, `worker_count`, `job_max_attempts`, `dispatcher_accepting_jobs`, `readiness_provider`). Conserva `_NoopDispatcher` (lo borra feature 16). |
| `apps/api/main.py` | `server.app` → `app`, `server.runtime.path` → `WEBHOOK_PATH` import directo. |
| `apps/api/admin_auth.py` | Añade helper `build_admin_access_policy`. |
| `tests/integration/test_http_transport.py` | `_build_client` reescrito para invocar `apps.api.app_factory.build_api_app(...)` con los kwargs nuevos. Verificación legacy `WordPressSourceStore.get_details_by_site_id` migrada a `uow.ingestion.sources.get_by_kind_external_id`. |
| `feature_list.json` | `features[id=9].status` cambiado a `in_progress` (no a `done` — eso lo hace el cierre admin tras review). |
| `progress/current.md` | Plan + bitácora de la feature. |

## Archivos borrados

| Path | LoC |
|------|------|
| `services/transport/http/server.py` | 1436 |
| `services/transport/http/openapi_docs.py` | 644 |
| `services/transport/http/uvicorn_protocols.py` | 276 |
| `application/admin/wordpress_source_management.py` | ~500 |
| `application/admin/__init__.py` | 12 |

`application/bootstrap/runtime.py` se queda: lo siguen usando
`modules/reels/application/use_cases/render_scripted_video.py` y el
`__init__.py` del paquete reels (verificado con grep). Feature 18 lo
disuelve junto con `application/`.

## Output verificación

### `pytest -q`

```
376 passed in 195.09s (0:03:15)
```

Baseline pre-feature-9 = 331 tests; feature 9 suma 45 tests netos:

- 27 unit (apps_api ×2, configuration ×2, ingestion ×3, publishing ×1).
- 18 integration (apps_api/health ×5, ingestion/wordpress_sources ×7,
  configuration/reel_profile ×4, publishing/social_accounts ×2).

### `python -m apps.api --check`

```
RUNTIME READY: Yes
PRODUCTION READY: No
... (full readiness report) ...
EXIT=0
```

### `python -m apps.worker --check`

```
Worker --check OK: kinds=reel_publish, scripted_render worker_count=1 lease=900s poll=0.50s
EXIT=0
```

### `init.sh`

`Entorno listo. Puedes empezar a trabajar.` (todos los pasos en verde).

### Grep guards

- `WordPressWebhookServer|WordPressWebhookApplication` en `apps/`,
  `modules/`, `shared/`, `tests/` → solo aparece en docstrings (no
  ejecutables) en 4 archivos: `apps/api/app_factory.py`,
  `apps/api/admin_auth.py`,
  `modules/configuration/transport/payloads/reel_profile.py`,
  `modules/ingestion/transport/payloads/wordpress_sources.py`.
- `services\.transport\.http\.server` en `apps/`, `modules/`, `shared/`,
  `tests/` → 0 hits.
- `from application\.admin` en todo el árbol → 0 hits.

## Decisiones no obvias

1. **`readiness_provider` kwarg en `build_api_app`**: la nueva ruta
   `/health` corre `services.transport.http.operations.build_readiness_report`
   sobre el workspace real, lo cual romperá los tests si no hay ffmpeg /
   font / site_secrets en el fixture. En vez de stub mucky en
   `test_http_transport.py`, añadí un `readiness_provider` opcional al
   `health_router` y a `build_api_app` para que tests inyecten un
   readiness determinista. Producción sigue corriendo el report real.
2. **`dispatcher_accepting_jobs` kwarg en `build_api_app`**: producción
   pasa por el `_NoopDispatcher` cuyo flag se flippea en el `lifespan`.
   Tests con `TestClient` no abren el lifespan (no se usa context manager)
   y necesitan estado determinista, así que `dispatcher_accepting_jobs`
   permite inyectar un closure directo (`_RecordingDispatcher.is_accepting_jobs`).
3. **`provision_wordpress_source` escribe a `ingestion_sources.config_json`**:
   los campos `site_url` / `normalized_host` que la API legacy persistía
   en columnas dedicadas (`wordpress_sources` table) ahora viven en el
   `config_json` jsonb del aggregate `ingestion_sources`. El response del
   endpoint los reconstruye desde ahí para preservar el contrato HTTP
   externo byte-a-byte.
