# Implementación Feature 4 — `ingestion_routers`

> Bitácora extensa en `progress/current.md`. Este informe resume archivos
> tocados, salida de verificación y decisiones no obvias.

## Archivos creados

### Use cases (modules/ingestion/application/use_cases/)
- `_source_support.py` — helpers privados de validación/normalización compartidos por los 5 verbos CRUD.
- `register_ingestion_source.py` — `RegisterIngestionSourceUseCase` + `RegisterIngestionSourceInput` (POST).
- `list_ingestion_sources.py` — `ListIngestionSourcesUseCase` (GET listado por agency).
- `inspect_ingestion_source.py` — `InspectIngestionSourceUseCase` (GET detalle con datos de agency).
- `reconfigure_ingestion_source.py` — `ReconfigureIngestionSourceUseCase` (PUT). `update_secret=True`+`secret=""` rota a vacío; `update_secret=False` no toca el blob.
- `decommission_ingestion_source.py` — `DecommissionIngestionSourceUseCase` (DELETE).
- `ingest_wordpress_property.py` — `IngestWordPressPropertyUseCase` con `AcceptedWebhookDelivery`. Resuelve tenant via `uow.ingestion.sources.get_by_kind_external_id`, lee `uow.publishing.connections.get_with_secrets`, configuración via `uow.configuration.{defaults,automation,social_templates}`, super-sede jobs previos y encola `kind="reel_publish"` con `provider_secret_bundle = json.dumps({"access_token", "provider": "gohighlevel"}, sort_keys=True)`.

### Transport
- `modules/ingestion/transport/payloads/__init__.py` y `sources.py` — Pydantic `IngestionSourceCreatePayload`, `IngestionSourceUpdatePayload` (sin guion bajo en públicos, `extra="forbid"`).
- `modules/ingestion/transport/http/sources_router.py` — `create_sources_router` con los 5 verbos descriptivos en `/v1/admin/agencies/{agency_id}/sources[/{ingestion_source_id}]`.
- `modules/ingestion/transport/http/wordpress_webhook_router.py` — `create_wordpress_webhook_router` con `WordPressWebhookSettings` (path, headers, max_payload_bytes, tolerance_seconds, security_disabled, site_secrets, default_platforms). Replica content-type/Content-Length/raw-body validation, header/body site_id resolution, HMAC + timestamp tolerance via `shared/http/webhook_signature.verify_webhook_signature`, logging en éxito/fallo y la traducción HTTP de `ResourceNotFoundError`/`ValidationError`/`ApplicationError`/`Exception`.

### Shared
- `shared/http/webhook_signature.py` — movido desde `services/transport/http/security.py`. Preserva la fórmula HMAC byte-a-byte (`timestamp\n + site_id\n + location_id\n + access_token\n + raw_body`, defaults `""`). Añade `verify_webhook_signature(...)` como envoltorio one-shot que combina `is_timestamp_fresh` + `is_signature_valid`.

### Tests unit (tests/unit/ingestion/)
- `test_register_ingestion_source.py`
- `test_list_ingestion_sources.py`
- `test_inspect_ingestion_source.py`
- `test_reconfigure_ingestion_source.py`
- `test_decommission_ingestion_source.py`
- `test_ingest_wordpress_property.py` — cubre camino feliz (bundle correcto), supersede de jobs previos, `UNKNOWN_WORDPRESS_SITE`, `GHL_CONNECTION_NOT_FOUND`.

### Tests integration (tests/integration/ingestion/)
- `test_wordpress_webhook_flow.py` — 5 tests: resolves+enqueue feliz, unknown site, missing GHL, paused dispatcher, supersede de jobs previos.
- `test_sources_router.py` — 5 tests: requires bearer token, full CRUD lifecycle, agency 404 al crear, duplicate site_id 400, inspect 404 cuando id desconocido.

## Archivos modificados

- `apps/api/app_factory.py` — registra `create_sources_router` y `create_wordpress_webhook_router` con `WordPressWebhookSettings` cableado a las settings reales (`WEBHOOK_PATH`, `SOCIAL_PUBLISHING_DEFAULT_PLATFORMS`, `WORKER_JOB_MAX_ATTEMPTS`, etc.) y `dispatcher_state=server.runtime.dispatcher.is_accepting_jobs`.
- `services/transport/http/server.py`:
  - Borra el modelo Pydantic legacy `_AdminAgencySourceUpsertPayload`.
  - Borra los handlers `upsert_admin_agency_source` y `delete_admin_agency_source`.
  - Borra el handler `receive_property_webhook` (~352 LoC).
  - Borra los métodos `WordPressWebhookApplication.authenticate`, `authenticate_with_details`, `accept_webhook_delivery`, `delete_wordpress_source` (sin más call sites tras la limpieza).
  - Borra el `from services.transport.http.security import …` (solo lo usaban los métodos eliminados).
- `services/transport/__init__.py`, `services/transport/http/__init__.py` — eliminan los re-exports de `build_raw_payload_hash`/`build_signature`/`is_signature_valid`/`is_timestamp_fresh` ahora que `security.py` ya no existe.
- `tests/integration/test_http_transport.py` — el `_build_client` registra los dos routers nuevos; los 4 tests legacy del webhook adaptados para leer `uow.delivery.webhook_events` / `uow.delivery.jobs` y desempaquetar `provider_secret_bundle` con `json.loads`. **Ningún test marcado `xfail`.**
- `feature_list.json` — feature 4 cambia a `in_progress`.
- `progress/current.md` — bitácora de la sesión.

## Archivos eliminados

- `services/transport/http/security.py` — su único call site (`server.py`) dejó de necesitarlo tras borrar `authenticate_with_details`. Re-exports en `services/transport/__init__.py` y `services/transport/http/__init__.py` actualizados.

## Verificación

```
$ bash init.sh
── 5. Ejecutando readiness checks ──────────────────────
[OK]    apps.api --check verde
[OK]    apps.worker --check verde

── 6. Ejecutando tests ─────────────────────────────────
........................................................................ [ 36%]
........................................................................ [ 73%]
.....................................................                    [100%]
197 passed in 76.85s
[OK]    pytest verde

── 7. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

Tests añadidos en esta feature: 19 unit + 10 integration = 29.
Ningún test legacy se marcó `xfail`; los 4 del webhook se adaptaron para apuntar al router nuevo y leer las nuevas tablas vía UoW.

## Decisiones no obvias

- **CRUD literal de 5 verbos** (siguiendo `phase_2_operating_rules.md` §5 Feature 4) en lugar de la paridad upsert+DELETE legacy. POST falla con 400 `INGESTION_SOURCE_DUPLICATE` cuando `(kind, external_id)` ya existe. PUT no permite reasignar a otra agencia (`ADMIN_SOURCE_AGENCY_MISMATCH`).
- **No se importa `WordPressSourceAdminService` ni `TenantResolver`** desde el router nuevo. La normalización de site_id/host está duplicada en `_source_support.py` (~30 LoC) — el legacy sigue vivo solo para el endpoint global `/v1/admin/wordpress-sources/{site_id}`, que retira feature 9.
- **Auto-provisionamiento legacy** (`unsafe_test_source_provisioner` en `application/tenancy/resolver.py`) no se replica. Ningún test depende de él (los integration nuevos seedean explícitamente). El router nuevo exige fuente `status='active'` o devuelve `UNKNOWN_WORDPRESS_SITE` 404.
- **`provider_secret_bundle` shape** fija: `json.dumps({"access_token": …, "provider": "gohighlevel"}, sort_keys=True)`. Coordinar con feature 16 antes de añadir más claves.
- **`publish_context_json`** sale del legacy `SocialPublishContext` (que el módulo no puede importar) y se construye como dict literal en el use case con campos `provider`, `location_id`, `platforms` (lista), `approval_required`, `social_templates` (lista de pares `[platform, template]`).
- **Sin shims**: `services/transport/http/security.py` borrado en el mismo PR; los re-exports en `services/transport/__init__.py` y `services/transport/http/__init__.py` también borrados.

## No se marca `done`. Pendiente revisión.
