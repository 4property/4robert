# Review — feature 7 (`reels_admin_router`)

**Veredicto:** APPROVED

## Resumen

La feature 7 extrae correctamente el surface admin de reels
(`/v1/admin/agencies/{id}/reels/*`) desde
`services/transport/http/server.py` a un router per-módulo bajo
`modules/reels/transport/`, con 4 use cases de naming descriptivo, los 4
GET de assets como helpers de transport, supersede + webhook_event +
enqueue cumpliendo la cadena exacta exigida, sin importar
`application.types.SocialPublishContext`, sin `xfail` y con
`./init.sh` verde (320 tests).

## Foco específico

### 1. Naming descriptivo  ✅
- `modules/reels/application/use_cases/list_reels.py::ListReelsUseCase`
- `modules/reels/application/use_cases/inspect_reel.py::InspectReelUseCase`
- `modules/reels/application/use_cases/regenerate_reel.py::RegenerateReelUseCase`
- `modules/reels/application/use_cases/reject_reel.py::RejectReelUseCase`

Ningún `get_reel_detail` u otro genérico. URLs preservan `/approve`
(compat frontend), use case `regenerate_reel` (descriptivo del
comportamiento real). Endpoints registrados con `tags=["Admin · Content"]`.

### 2. `/reject` incluido  ✅
- `modules/reels/transport/http/admin_reels_router.py:528-560`
  expone `POST .../reject`. Sirve `RejectReelUseCase`. No hay handler
  huérfano en `server.py` (`grep "/admin/agencies/.*reels"` en
  `services/transport/http/server.py` → 0 matches).

### 3. `regenerate_reel` solo encola, NO ejecuta inline  ✅
- `modules/reels/application/use_cases/regenerate_reel.py:226-244`
  llama `uow.delivery.jobs.enqueue_job(JobEnqueueRequest(kind="reel_publish", ...))`.
- Cadena completa de superseding antes del enqueue:
  - `regenerate_reel.py:202-207` → `uow.delivery.jobs.supersede_queued_jobs`.
  - `regenerate_reel.py:208-213` → `uow.delivery.webhook_events.update_event_status(... status="superseded")`.
  - `regenerate_reel.py:215-225` → `uow.delivery.webhook_events.create_event(... status="queued")`.
  - `regenerate_reel.py:226-244` → `enqueue_job` posterior. Orden correcto.
- `regenerate_reel.py:191-195`:
  `provider_secret_bundle = json.dumps({"access_token": access_token, "provider": "gohighlevel"}, ensure_ascii=False, sort_keys=True)`
  — keys exactas. `sort_keys=True` es ortogonal a la fórmula y consistente
  con feature 4 (verificado: el test integration assertea sobre el JSON
  decodificado, no el texto).
- `regenerate_reel.py:102-115` setea `workflow_state='approved'` y
  `publish_status='pending_publish'` ANTES del enqueue (pre-resolución
  de prereqs). Cumple el contrato.
- Sin prereqs (no payload, no GHL, no access_token, JSON inválido):
  `regenerate_reel.py:156-162` retorna `RegenerateReelResult(publish_enqueued=False, reason="PUBLISH_PREREQUISITES_MISSING", hint=...)`.
  El router (`admin_reels_router.py:515-526`) traduce a 200 con
  `{publish_enqueued: false, reason, hint}` preservando el contrato del frontend.

### 4. No importa `application.types.SocialPublishContext`  ✅
- `grep SocialPublishContext modules/reels/application/use_cases/` → 0 matches.
- `regenerate_reel.py:184-190` construye `publish_context` como dict
  literal. La conversión a dataclass la sigue haciendo el bridge consumer
  del worker (`modules/reels/application/orchestrator.py:35,53`), fuera de
  scope de feature 7.

### 5. Borrado legacy  ✅
- `services/transport/http/server.py`: 0 matches para
  `/admin/agencies/.*reels`, `list_agency_reels`,
  `get_agency_reel_detail`, `resolve_reel_video_path`,
  `enqueue_reel_publish`, `list_reel_property_images`,
  `resolve_property_image_path`, `resolve_reel_manifest_path`,
  `update_reel_workflow`, `_serialize_agency_reel`,
  `_guess_image_mime_type`. Todos removidos del runtime.
- `application/dispatch/webhook_acceptance.py` borrado (`ls
  application/dispatch/` → solo `database_dispatcher.py` y
  `__init__.py`).
- `_serialize_agency_reel` y `_guess_image_mime_type` relocalizados a
  `modules/reels/transport/http/admin_reels_router.py` (líneas 47-89).
- Sin compat shims, sin `xfail` en tests (`grep xfail tests/` → 0 matches).

### 6. Aislamiento inter-módulo  ✅
- `grep "from modules\.(?!reels)\w+\.(application|infrastructure)"
  modules/reels/` → 0 matches.
- Atravesando `uow.<bc>.<repo>` (catalog.properties, publishing.connections,
  configuration.defaults/automation/social_templates, delivery.jobs,
  delivery.webhook_events, tenancy.agencies). Ok.
- Único cross-module domain import:
  `from modules.delivery.domain import JobEnqueueRequest` en
  `regenerate_reel.py:26` — permitido por reglas (`<otro>.domain`).

### 7. Tests adaptados, no `xfail`  ✅
- `tests/integration/test_http_transport.py:47-48` importa
  `create_admin_reels_router`. `_build_client`
  (`test_http_transport.py:206-214`) registra el router. El test
  `test_admin_reels_listing_is_empty_for_a_fresh_agency`
  (`test_http_transport.py:665-676`) sigue verde sirviéndose del router
  nuevo, mismo path HTTP.
- `tests/integration/reels/test_admin_reels_router.py` cubre 20 tests:
  list (vacío + seed + 404), inspect (200, 404 reel/agency,
  has_video/video_url), video (stream + 404), images (lista con
  has_local_file), images/{pos}/file (stream), manifest (200 + 404),
  approve (publish_enqueued false sin prereqs verificando estado en BD,
  publish_enqueued true con seed completo, supersede de jobs/eventos
  previos verificado vía SQL directo, 404 agency, 404 reel), reject
  (200 + estado en BD + 404).
- El test integration de regenerate (test_approve_enqueues_job_with_full_prereqs,
  `test_admin_reels_router.py:389-429`) verifica fila real en `jobs` con
  `kind='reel_publish'` y bundle exacto.
- `test_approve_supersedes_previously_queued_job_for_same_property`
  (`test_admin_reels_router.py:432-491`) lee `jobs` y `webhook_events` con
  SQL directo y comprueba `status='superseded'` y `superseded_by_job_id`.
- Unit tests:
  `tests/unit/reels/test_list_reels.py` (2),
  `tests/unit/reels/test_inspect_reel.py` (3),
  `tests/unit/reels/test_regenerate_reel.py` (5: camino feliz, 2
  paths PUBLISH_PREREQUISITES_MISSING, 404 agency, 404 reel),
  `tests/unit/reels/test_reject_reel.py` (3).
- Conteo: 320 = 287 baseline + 33 nuevos (13 unit + 20 integration). ≥ 287.

### 8. Repos sin `session.commit()`. Pydantic NO en application/  ✅
- `grep session\.commit modules/` → 0 matches.
- `grep "from pydantic|BaseModel" modules/reels/application/` → 0 matches.

### 9. `./init.sh` verde  ✅
Ejecutado por el reviewer:
```
[OK]    apps.api --check verde
[OK]    apps.worker --check verde
320 passed in 151.58s
[OK]    pytest verde
[OK]    Entorno listo. Puedes empezar a trabajar.
```
El `[WARN]` de "modificados 30 archivos en directorios legacy" es
esperado: phase 2 borra surface legacy a su paso (la pista del propio
init.sh: "Confirma que son cambios de compat shim, no features
nuevas"). Aquí los cambios en `services/` son **borrados**, no nuevas
features.

### 10. CHECKPOINTS.md  ✅
Recorrido abajo.

## Checkpoints

- C1: [x] AGENTS.md, CLAUDE.md, init.sh, feature_list.json,
  progress/current.md, docs/architecture.md, docs/conventions.md,
  docs/verification.md presentes. `./init.sh` exit 0.
- C2: [x] Solo feature 7 en `in_progress` en feature_list.json. Tests
  verdes. `progress/current.md` describe la sesión activa de feature 7.
  `progress/history.md` con entradas previas.
- C3: [x] Sin imports cross-module a `application/`/`infrastructure/`.
  `modules/reels/domain/` libre de SQLAlchemy. Repos extienden
  `ModuleRepository`, no llaman `commit()`. Sin código nuevo en
  `services/`/`application/`/`repositories/`/`core/`/`domain/` (solo
  borrados).
- C4: [x] Tests para los 4 use cases nuevos (unit) + 20 integration.
  Usan `tests/support/postgres.py` (`temporary_postgres_schema`,
  `seed_tenant`, `seed_provider_connection`, `temporary_workspace`).
  `pytest -q` 320 verdes. `python -m apps.api --check` y
  `python -m apps.worker --check` exit 0.
- C5: [x] Feature 7 no toca schema (sin nueva migración requerida).
- C6: [x] No hay archivos sin trackear sospechosos. Feature reflejada
  en feature_list.json (`in_progress`, esperando cierre del leader).
  Sin `print()` de debug. Sin TODOs sin contexto.

## Observaciones (no bloqueantes)

- `regenerate_reel._load_reel_summary` (`regenerate_reel.py:253-276`)
  recorre hasta 500 filas filtrando en Python. Aceptable mientras la
  page-size cap del query sea 500. Documentado por el implementer
  como deuda; un método dedicado en `ReelQuery` sería más limpio.
- `provider_secret_bundle` usa `sort_keys=True`, lo cual no rompe la
  comparación funcional (bundle es JSON parseado por el worker) pero
  agrega un detalle no exigido. No bloqueante.
- `last_published_location_id` permanece como alias en el payload
  (`admin_reels_router.py:80`,
  `payloads/admin_reels.py:36`) para preservar contrato frontend.
  Phase 3 lo unificará. Documentado.

## Cierre

APPROVED -> ver progress/review_7_reels_admin_router.md
