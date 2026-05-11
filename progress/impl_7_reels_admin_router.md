# Impl — Feature 7 `reels_admin_router`

## Resumen

Se extrae el surface admin de reels (`/v1/admin/agencies/{id}/reels/*`) desde
`services/transport/http/server.py` a un router per-módulo bajo
`modules/reels/transport/`. Se introducen 4 use cases nuevos (`list_reels`,
`inspect_reel`, `regenerate_reel`, `reject_reel`) y los payloads Pydantic
asociados. La feature elimina la dependencia residual del runtime legacy
sobre `WordPressWebhookApplication.list_agency_reels` /
`get_agency_reel_detail` / `resolve_reel_video_path` /
`enqueue_reel_publish` / `list_reel_property_images` /
`resolve_property_image_path` / `resolve_reel_manifest_path` /
`update_reel_workflow`, y borra `application/dispatch/webhook_acceptance.py`
porque ya no quedan call sites.

## Archivos creados

- `modules/reels/transport/payloads/__init__.py` — paquete vacío.
- `modules/reels/transport/payloads/admin_reels.py` — Pydantic v2 payloads
  (`AgencyReelItemPayload`, `ListReelsResponse`, `InspectReelResponse`,
  `InspectReelResponseItem`, `RegenerateReelResponse`, `RejectReelResponse`).
- `modules/reels/transport/http/admin_reels_router.py` — router con los 8
  endpoints (`/`, `/{site}/{id}`, `/video`, `/images`,
  `/images/{pos}/file`, `/manifest`, `/approve`, `/reject`). Orquesta los
  use cases y resuelve assets locales contra `workspace_dir`.
- `modules/reels/application/use_cases/_admin_support.py` — helpers
  `ensure_agency_exists`, `agency_not_found_error`, `reel_not_found_error`.
- `modules/reels/application/use_cases/list_reels.py` — `ListReelsUseCase`.
- `modules/reels/application/use_cases/inspect_reel.py` — `InspectReelUseCase`.
- `modules/reels/application/use_cases/reject_reel.py` — `RejectReelUseCase`.
- `modules/reels/application/use_cases/regenerate_reel.py` —
  `RegenerateReelUseCase` + dataclass `RegenerateReelResult`. Solo encola job
  (kind `reel_publish`) directamente vía `uow.delivery.jobs` +
  `uow.delivery.webhook_events`, replicando `supersede_queued_jobs` +
  `update_event_status` + `create_event` + `enqueue_job` en una transacción
  del UoW. **No** importa `application.types.SocialPublishContext` ni pasa
  por `WebhookAcceptanceService` — construye `publish_context` como dict
  literal y `provider_secret_bundle` como JSON con
  `{access_token, provider}`.
- `tests/unit/reels/_uow_stubs.py` — stubs ligeros del UoW para los unit
  tests.
- `tests/unit/reels/test_list_reels.py` — 2 tests.
- `tests/unit/reels/test_inspect_reel.py` — 3 tests.
- `tests/unit/reels/test_reject_reel.py` — 3 tests.
- `tests/unit/reels/test_regenerate_reel.py` — 5 tests (camino feliz, 2
  caminos `PUBLISH_PREREQUISITES_MISSING`, 404 agency, 404 reel).
- `tests/integration/reels/_client.py` — `build_admin_reels_client`,
  `seed_property_with_reel`, `seed_property_image`,
  `insert_legacy_queued_job` (helpers de seed inline; siguen el patrón de
  `tests/integration/configuration/_client.py`).
- `tests/integration/reels/test_admin_reels_router.py` — 20 tests cubriendo
  list (vacío + seed + 404), inspect (200, 404 reel, 404 agency,
  `has_video`/`video_url` cuando el fichero existe), video (stream + 404),
  images (lista con `has_local_file`), images/{pos}/file (stream),
  manifest (200 + 404), approve (`publish_enqueued=False` sin prereqs,
  `publish_enqueued=True` con seed completo verificando fila en `jobs`,
  supersede de jobs/eventos previos, 404 agency, 404 reel), reject (200 +
  estado en BD + 404 reel).

## Archivos modificados

- `apps/api/app_factory.py` — registra
  `create_admin_reels_router(...)` en la composición; recibe
  `workspace_dir`, `job_max_attempts` y `default_platforms`.
- `tests/integration/test_http_transport.py` — añade el router admin de
  reels al `_build_client` para que el test legacy
  `test_admin_reels_listing_is_empty_for_a_fresh_agency` siga verde sin
  xfail.
- `feature_list.json` — feature 7 → `in_progress`.
- `progress/current.md` — sesión actual.

## Archivos borrados

- `application/dispatch/webhook_acceptance.py` — ya no quedan callers
  (sólo lo usaban los handlers que esta feature mueve).
- `application/dispatch/__init__.py` — reducido a 1 línea de docstring.

## Borrados dentro de `services/transport/http/server.py`

- 8 handlers de `/admin/agencies/{id}/reels/*` (list, detail, video,
  images, image-file, manifest, approve, reject) bajo el banner
  `# Admin · Content`.
- Helpers `_serialize_agency_reel` y `_guess_image_mime_type`.
- Métodos del runtime: `list_agency_reels`, `get_agency_reel_detail`,
  `resolve_reel_video_path`, `enqueue_reel_publish`,
  `list_reel_property_images`, `resolve_property_image_path`,
  `resolve_reel_manifest_path`, `update_reel_workflow`.
- Construcción del `acceptance_service: WebhookAcceptanceService` (huérfana
  tras los borrados anteriores).
- Imports innecesarios: `hashlib`, `Response`, `StreamingResponse`,
  `TenantResolver`, `WebhookAcceptanceService`, `SocialPublishContext`,
  `WORKER_JOB_MAX_ATTEMPTS`, `_build_range_response` y
  `job_max_attempts` del `__init__` del runtime.

Verificado por grep: ningún archivo bajo `apps/`, `modules/`, `shared/`,
`tests/` referencia los símbolos borrados.

## Decisiones no obvias

- **Use case `regenerate_reel` solo encola, no ejecuta** (acceptance literal
  de feature 7). Construye el `publish_context` como dict y NO importa
  `application.types.SocialPublishContext` — la conversión a dataclass la
  hace el bridge consumer del worker (deuda de feature 13). Usa
  `defaults.platforms` (canónico) con fallback a `default_platforms`
  inyectado vía constructor.
- **404 vs 200 en regenerate sin prereqs:** se preserva el contrato actual
  del frontend → 200 con `{publish_enqueued: false, reason:
  "PUBLISH_PREREQUISITES_MISSING", hint: …, reel: …}`. El estado del reel se
  marca `approved` / `pending_publish` antes de detectar la falta de
  prereqs, igual que el handler legacy.
- **`AgencyReelSummary` se importa con `TYPE_CHECKING`** en los use cases
  para evitar un ciclo de imports cuando los tests cargan el use case antes
  de `shared.db` (la cadena
  `inspect_reel → reel_query → shared.db.repository_base → shared.db.__init__ → uow → reel_query.ReelQuery`
  fallaba con import circular sólo durante la colección unitaria). En
  ejecución real, `shared.db` siempre se carga primero.
- **`__init__.py` en los nuevos dirs de tests:** se eliminaron porque
  pytest, en modo rootdir, colisionaba `tests/unit/reels` y
  `tests/integration/reels` como dos paquetes con el mismo nombre `reels`.
  Resto de dirs de tests también carecen de `__init__.py`, lo que
  confirma la convención del repo.
- **Helpers de transport vs use case:** los GET de `video`, `images`,
  `images/{pos}/file` y `manifest` no tienen use case dedicado (lectura de
  fichero local). El handler reutiliza `inspect_reel` para validar
  agency+reel y luego resuelve el path contra `workspace_dir`.

## Verificación

- `apps.api --check` → OK.
- `apps.worker --check` → OK.
- `pytest -q` → **320 passed** (287 baseline + 33 nuevos: 13 unit + 20
  integration).
- `./init.sh` → verde (warning no bloqueante por archivos modificados en
  `services/`, esperado: feature 2-8 borra surface legacy a su paso).

```
── 6. Ejecutando tests ─────────────────────────────────
........................................................................ [ 22%]
........................................................................ [ 45%]
........................................................................ [ 67%]
........................................................................ [ 90%]
................................                                         [100%]
320 passed in 151.95s (0:02:31)
[OK]    pytest verde
```

## Pendiente para el reviewer

- Confirmar que el router debería responder 200 (preservando contrato) o
  pasar a 422 cuando faltan prereqs. Implementación actual mantiene 200
  según overrides en `docs/phase_2_operating_rules.md` §5.
- `last_published_location_id` en el payload se mapea desde
  `last_published_provider_external_id` del dataclass — alias preservado
  por compat con el frontend (Phase 3 hará el rename de la URL surface).
- `application.types.SocialPublishContext` queda vivo: lo usan
  `application/pipeline/`, `domain/`, `tests/test_social_publishing.py` y
  el bridge worker. Phase 13 lo migra a
  `modules/publishing/domain/social_publish_context.py`.
