# Review — feature 13 (db_backed_render_templates)

**Veredicto:** APPROVED

> Asignación convencional: la tarea NO existe como entrada en
> `feature_list.json`. El usuario decidira si la añade. La bitácora del
> implementer vive en `progress/current.md` (no `impl_13_*.md`). Este
> review usa `feature_id=13` y `name=db_backed_render_templates` solo
> para nombrar el archivo, como pidió el leader.

## Resumen ejecutivo

El implementer cumple el plan literal de `progress/current.md`:

1. Cataloga DB-backed `render_templates` con seed `classic`, FK desde
   `agency_reel_defaults`, `reels` y `media_revisions` con server_default
   `"classic"` (idempotente y compatible con filas existentes).
2. Expone endpoints agency-scoped `GET /v1/admin/agencies/{id}/render-templates`
   y `PUT /v1/admin/agencies/{id}/render-template`, mismos guards de auth que
   el resto de `/v1/admin/*` (`authorize_admin_request` con early-return) y
   payload Pydantic con `extra="forbid"` y `str_strip_whitespace=True`.
3. Propaga `render_template_id` por `/defaults` y `/reel-profile` con
   round-trip GET→PUT→GET verificado en tests de integración.
4. Threading completo: el ID se resuelve en
   `ingest_property_into_reel` (con fallback a defaults y a classic), se
   inyecta en el `content_snapshot` y en el `publish_target_snapshot`
   (vía `SocialPublishContext.render_template_id`), modifica el manifest
   (`render_template_id` + `render_template_settings_hash` +
   `poster_render_settings`), el frame composition consume
   `render_template_reel_settings`/`render_template_poster_settings` y
   el poster se renderiza con el `poster_template`. La revisión queda
   registrada en `media_revisions.render_template_id`.
5. Cobertura unit (`tests/unit/rendering/test_render_template_settings.py`,
   4 casos) + integration (`tests/integration/configuration/test_render_templates_router.py`,
   4 casos) verde. `test_persist_local_artifacts.py`, `test_ingest_property_into_reel.py`,
   `test_regenerate_reel.py`, `test_frame_composition.py` actualizados
   con assertions sobre `render_template_id`.
6. Capas respetadas: `domain/` sin SQLAlchemy; `application/` sin Pydantic
   ni FastAPI; transport router no toca DB directo; `RenderTemplateRepository`
   extiende `ModuleRepository` y NO hace `session.commit()`; errores
   usan `ResourceNotFoundError`/`ValidationError` (subclases de
   `ApplicationError`).

Los cambios atribuibles a render_templates están perfectamente
delimitados del drift de features 8/10/11/12 (`pinterest`, agency logo,
publish window, unescape) que ya fueron aprobadas en sesiones previas y
cuyo diff no interfiere con esta feature.

## Acceptance: tabla con evidencia

| # | Criterio | Estado | Evidencia archivo:línea |
|---|---|---|---|
| 1a | Catálogo `render_templates` creado por alembic con seed classic | [x] | `alembic/versions/20260513_0002_render_templates.py:17-66` |
| 1b | Columna `agency_reel_defaults.render_template_id` (FK, default classic) | [x] | `alembic/versions/20260513_0002_render_templates.py:68-83`; ORM `modules/configuration/infrastructure/orm.py:101-106` |
| 1c | Columna `reels.render_template_id` (FK, default classic) | [x] | `alembic/versions/20260513_0002_render_templates.py:85-100`; ORM `shared/db/orm.py:178-183` |
| 1d | Columna `media_revisions.render_template_id` (FK, default classic) | [x] | `alembic/versions/20260513_0002_render_templates.py:102-117`; ORM `shared/db/orm.py:227-232` |
| 1e | Alembic up+down+up limpio sobre DB de test | [x] | Ejecutado: `.venv/bin/alembic upgrade head && downgrade -1 && upgrade head` → `Running upgrade 20260501_0001 -> 20260513_0002` + `Running downgrade 20260513_0002 -> 20260501_0001` sin errores |
| 2a | Endpoint `GET /v1/admin/agencies/{id}/render-templates` autenticado | [x] | `modules/configuration/transport/http/render_templates_router.py:44-79`; `authorize_admin_request` línea 52 |
| 2b | Endpoint `PUT /v1/admin/agencies/{id}/render-template` autenticado | [x] | `modules/configuration/transport/http/render_templates_router.py:81-133`; `authorize_admin_request` línea 90 |
| 2c | Payload Pydantic estricto (`extra='forbid'`) | [x] | `modules/configuration/transport/payloads/render_templates.py:8-19` |
| 2d | Errores semánticos (404 `RENDER_TEMPLATE_NOT_FOUND`, 400 `RENDER_TEMPLATE_NOT_SELECTABLE`) | [x] | `modules/configuration/transport/http/render_templates_router.py:102-117`; verificado por test integration `test_render_template_select_rejects_unknown_or_disabled_template` |
| 3a | `render_template_id` viaja por `/defaults` PUT | [x] | `modules/configuration/transport/payloads/defaults.py:72-76`; `modules/configuration/transport/http/defaults_router.py:122`; use case `modules/configuration/application/use_cases/update_reel_defaults.py:44-58, 76`; defaults_repo upsert `modules/configuration/infrastructure/defaults_repository.py:89-94, 108, 119` |
| 3b | `render_template_id` viaja por `/reel-profile` GET/PUT | [x] | `modules/configuration/application/use_cases/read_aggregated_reel_profile.py:62-66, 117-121`; update `modules/configuration/application/use_cases/update_aggregated_reel_profile.py:70-85, 112, 124`; router `modules/configuration/transport/http/reel_profile_router.py:126`; payload `modules/configuration/transport/payloads/reel_profile.py:51` |
| 3c | Round-trip GET→PUT→GET preserva valor | [x] | Test integration `tests/integration/configuration/test_render_templates_router.py:97-134` (`test_defaults_and_reel_profile_round_trip_render_template_id`) cubre tanto `/defaults` como `/reel-profile`. |
| 4a | Afecta fingerprints/snapshot de ingest | [x] | `modules/reels/application/use_cases/ingest_property_into_reel.py:154-167` (resolve) + `_ingest_property_planning.py:201-219` (`_build_content_snapshot` añade `render_template`) → entra en `content_fingerprint` |
| 4b | Afecta manifest del render | [x] | `modules/rendering/infrastructure/manifest.py:51-53, 188-195, 250-269` (manifest payload incluye `render_template_id`, `render_template_settings_hash`, `poster_render_settings`) |
| 4c | Afecta poster/reel rendering | [x] | `modules/rendering/application/frame_composition.py:78-90, 119-137` (poster usa `poster_template` resuelto; reel template aplica overrides del template) |
| 4d | Registrado en `media_revisions` para historial | [x] | `modules/reels/application/use_cases/persist_local_artifacts.py:331` (passes `context.render_template_id` a `MediaRevision`); repo persiste el campo `modules/reels/infrastructure/media_revision_repository.py:33, 47-72` |
| 5a | Tests unit nuevos para settings/hash/fallback | [x] | `tests/unit/rendering/test_render_template_settings.py` 4 tests, `4 passed`. Cubre normalización, rechazos, estabilidad y fallback a classic. |
| 5b | Tests integration nuevos (list/select/rounded trip) | [x] | `tests/integration/configuration/test_render_templates_router.py` 4 tests, `4 passed` |
| 5c | Tests existentes extendidos con render_template_id | [x] | `tests/unit/reels/test_ingest_property_into_reel.py:234,241`; `tests/unit/reels/test_persist_local_artifacts.py:102-255`; `tests/unit/rendering/test_frame_composition.py:135,344,362`; `tests/unit/reels/test_regenerate_reel.py:94`; `tests/unit/configuration/_uow_stubs.py:138, 161-171` (StubRenderTemplates) |
| 6a | `domain/` sin SQLAlchemy | [x] | `grep "from sqlalchemy" modules/configuration/domain/ modules/reels/domain/ modules/rendering/infrastructure/render_template_settings.py` → 0 hits |
| 6b | `application/` sin Pydantic/HTTP | [x] | `grep "import pydantic\|from pydantic\|fastapi" modules/configuration/application/use_cases/{list,select}_render_templates.py` → 0 hits |
| 6c | Transport no toca DB directo | [x] | Router solo entra a DB vía `unit_of_work_factory()` y use cases. No imports de SQLAlchemy. |
| 6d | Repos extienden `ModuleRepository` y no commitean | [x] | `class RenderTemplateRepository(ModuleRepository)` en `modules/configuration/infrastructure/render_template_repository.py:73`; `grep "session.commit" modules/configuration/infrastructure/render_template_repository.py modules/configuration/infrastructure/defaults_repository.py modules/reels/infrastructure/{media_revision,reel_state}_repository.py` → 0 hits |
| 6e | Errores via `ApplicationError` + `shared.observability` | [x] | `ResourceNotFoundError`/`ValidationError` son subclases de `ApplicationError` (`shared/errors/__init__.py:9,14`). Logger via `logging.getLogger(__name__)` (`render_template_settings.py:19`, `ingest_property_into_reel.py:81`). |
| 7  | Integration tests usan `tests/support/postgres.py` | [x] | `tests/integration/configuration/test_render_templates_router.py:15-19` importa `seed_tenant`, `temporary_postgres_schema`, `temporary_workspace`. `ACTIVE_TABLES` en `tests/support/postgres.py:21-41` incluye `render_templates`. |
| 8  | `bash ./init.sh` verde salvo baseline drift conocido (3 fallos pre-existentes) | [x] | Resultado: `3 failed, 547 passed` — exactamente los 3 fallos preexistentes (`test_http_surface_contract::test_frontend_api_requests_target_existing_backend_routes` + 2 casos de `test_http_transport` sobre `configured_worker_count`). `init.sh` retorna verde. Ningún fallo nuevo es atribuible a render_templates. |

## Checkpoints

- C1 — Schema/migración bidireccional limpia: [x]
- C2 — Endpoints HTTP autenticados + payloads estrictos: [x]
- C3 — `render_template_id` round-trip por defaults y reel-profile: [x]
- C4 — Template afecta ingest fingerprint + manifest + rendering + media_revisions: [x]
- C5 — Tests focales unit + integration verdes: [x]
- C6 — Capas/aislamiento/nombres/errores/repos respetan convenciones: [x]
- C7 — `init.sh` reproduce solo el baseline drift conocido: [x]

## Verificación local

| Suite | Resultado |
|---|---|
| `alembic upgrade head` (fresh) | OK (`20260501_0001 -> 20260513_0002`) |
| `alembic downgrade -1` | OK (`20260513_0002 -> 20260501_0001`) |
| `alembic upgrade head` (re-up) | OK (`20260501_0001 -> 20260513_0002`) |
| `tests/integration/configuration/test_render_templates_router.py` | `4 passed` |
| `tests/unit/rendering/test_render_template_settings.py` | `4 passed` |
| Combinado (smoke focal: integration/configuration + unit/configuration + unit/rendering + unit/reels) | `268 passed` en 81s |
| `bash ./init.sh` | `3 failed, 547 passed`, script retorna verde |

## Fallos pre-existentes vs nuevos

Los 3 fallos que registra `init.sh` son **idénticos** a los documentados en
el review aprobado de feature 11 y antes (baseline drift):

1. `tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes`
   — depende de `FRONTEND_REPO_ROOT` (no se está pasando) y del estado del repo
   front. NO touched por render_templates.
2. `tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state`
   — espera response `/health` sin `configured_worker_count`; el campo fue
   añadido por features previas a `apps/api/health_router.py`. NO touched por
   render_templates.
3. `tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads`
   — mismo motivo que (2).

Cero fallos nuevos atribuibles a render_templates.

## Notas adicionales

- Drift correctamente delimitado:
  - `modules/configuration/transport/http/social_templates_router.py`,
    `modules/configuration/transport/payloads/social_templates.py`,
    `modules/configuration/domain/social_templates_variables.py` corresponden
    a la feature 9 (descripciones/social-templates) — ya aprobada (`review_9_*.md`).
  - `modules/delivery/infrastructure/job_repository.py:6-77, 183-243` (ActiveJob +
    `find_active_job_for_property`) y todo el cableado de `scheduled_at` en
    `modules/reels/application/use_cases/regenerate_reel.py`, `_types.py`,
    `modules/publishing/...` corresponden a la feature 11 (publish window /
    idempotent replay) — ya aprobada (`review_11_*.md`).
  - `modules/configuration/transport/http/brand_logo_router.py`,
    `tests/integration/configuration/test_brand_logo_router.py`,
    `modules/reels/application/use_cases/ingest_property_into_reel.py:235-411`
    (`_resolve_agency_logo_local_path`), `agency_logo_local_path` en
    `PropertyContext` y `PropertyRenderData` corresponden a la feature 10
    (agency logo upload) — ya aprobada (`review_10_*.md`).
  - `pinterest` en defaults/platforms y `decodeHtmlEntities` por toda la
    cadena son features 8/12 — ya aprobadas. La inclusión de `pinterest` en
    `_DEFAULT_PLATFORMS` (defaults_router, read_aggregated_reel_profile,
    defaults_repository) NO interfiere con render_templates.
- El catálogo `render_templates` queda en `ACTIVE_TABLES` de
  `tests/support/postgres.py:25` para que el cleanup por schema lo reconozca.
- El use case `ListRenderTemplates` defaultea a `"classic"` cuando el
  `defaults.render_template_id` apunta a un template inexistente (defensa
  ante datos sucios). El `SelectRenderTemplate` además rechaza templates con
  `status != "active"` con `RENDER_TEMPLATE_NOT_SELECTABLE` (probado).
- `resolve_render_template_settings` produce un `settings_hash`
  determinista (sha256 sobre payload con `sort_keys=True`), lo que garantiza
  que dos templates con la misma configuración pero distinto orden de claves
  generan el mismo hash — verificado por
  `test_resolve_render_template_settings_hash_is_stable_for_same_settings`.
- El cross-module import `modules.reels.application.use_cases.ingest_property_into_reel`
  → `modules.rendering.infrastructure.render_template_settings` sigue el
  patrón ya establecido y aprobado en el repo
  (`prepare_reel_assets.py` → `modules.rendering.infrastructure.photos`,
  `orchestrator.py` → `modules.rendering.application.frame_composition`,
  etc.). El módulo `rendering` actúa como infrastructure de capa común para
  el pipeline de reels. No es una novedad que esta feature introduzca.

## Cambios requeridos

Ninguno.

**Una sola línea para chat**:

```
APPROVED -> progress/review_13_db_backed_render_templates.md
```
