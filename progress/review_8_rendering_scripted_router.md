# Review — feature 8 (`rendering_scripted_router`)

**Veredicto:** APPROVED

## Foco específico (todos los puntos del prompt del leader)

1. **Sync→async aplicado.** Verificado:
   - `modules/rendering/transport/http/scripted_router.py:54-65` declara
     `status_code=202` y `response_model=ScriptedRenderResponse`.
   - `modules/rendering/transport/http/scripted_router.py:208-215` devuelve
     `JSONResponse(status_code=202, content={"status": "accepted",
     "job_id", "event_id", "site_id", "source_property_id"})`.
   - El use case `EnqueueScriptedRenderUseCase.execute` solo encola
     (`uow.delivery.jobs.enqueue_job(JobEnqueueRequest(kind="scripted_render", ...))`)
     — no ejecuta ffmpeg.
   - El integration test `test_scripted_render_enqueues_job_and_returns_202`
     (`tests/integration/rendering/test_scripted_router.py:48-72`) afirma
     `response.status_code == 202`, `payload["status"] == "accepted"`, y
     `job.kind == "scripted_render"` con `status == "queued"`.

2. **Use case naming descriptivo.** Archivo
   `modules/rendering/application/use_cases/enqueue_scripted_render.py`,
   clase `EnqueueScriptedRenderUseCase`. Cumple
   `docs/phase_2_operating_rules.md:83`.

3. **Aislamiento inter-módulo.** Verificado:
   - Grep `from modules\.reels|import modules\.reels|from modules\.publishing|from modules\.catalog`
     sobre `modules/rendering/`: 0 hits.
   - Grep `application.scripted_render` sobre `modules/rendering/`: 0 hits.
   - El use case importa solamente
     `from modules.delivery.domain import JobEnqueueRequest`
     (peer module's domain, permitido por `ARCHITECTURE.md:72-74`),
     `from shared.db import DatabaseUnitOfWork`,
     `from shared.errors import ResourceNotFoundError, ValidationError`.
   - El router atraviesa el shared UoW
     (`uow.ingestion.sources.get_by_kind_external_id`,
      `uow.tenancy.agencies.get_by_id`,
      `uow.delivery.jobs.enqueue_job`,
      `uow.delivery.webhook_events.create_event`).

4. **Tenant resolution inline.** Verificado en
   `modules/rendering/application/use_cases/enqueue_scripted_render.py:79-101`:
   ```python
   source = uow.ingestion.sources.get_by_kind_external_id(
       kind="wordpress", external_id=normalized_site_id,
   )
   ...
   agency = uow.tenancy.agencies.get_by_id(source.agency_id)
   ```
   No hay import de `TenantResolver` legacy.

5. **`webhook_events.source_kind="scripted_api"` sin CHECK constraint.**
   Verificado en `alembic/versions/20260501_0001_initial_schema.py:486`:
   `sa.Column("source_kind", sa.Text(), nullable=False)` — sin
   constraint. El integration test confirma con SQL directo
   (`test_scripted_router.py:74-87`) que la fila se persiste con
   `source_kind = "scripted_api"`.

6. **Job payload shape.** Verificado en
   `enqueue_scripted_render.py:119-137`:
   - `kind="scripted_render"`.
   - `payload=dict(data.payload)` — body completo verbatim (el test
     unit afirma `job_request.payload["title"] == "Sample"` y el
     integration test afirma `job.payload == manifest`).
   - `publish_context={}`.
   - `provider_secret_bundle=""`.
   - `external_source_id=source.external_id`.
   - `property_id=data.source_property_id`.

7. **Borrado legacy.** Verificado:
   - Grep `scripted` (case-insensitive) sobre `services/transport/http/server.py`:
     0 hits (handler `render_scripted_video` y método
     `WordPressWebhookApplication.render_scripted_video` borrados,
     import de `ScriptedVideoRenderService` borrado).
   - Grep `scripted` (case-insensitive) sobre `services/transport/http/openapi_docs.py`:
     0 hits (`_decorate_scripted_render_operation` y helpers borrados;
     la etiqueta `Video Rendering` se actualizó a "Encolado asíncrono…").
   - Sin compat shims, sin `xfail` (grep en tests: 0 ocurrencias de
     `xfail` sobre los tests nuevos).
   - **`apps/worker/runtime.py` intacto.** Verificado en
     `apps/worker/runtime.py:259-279`: `RenderScriptedVideoUseCase` se
     instancia y se registra como handler `scripted_render` igual que
     antes.
   - **`application/scripted_render/service.py` intacto** (sigue
     existiendo; se borrará en feature 14, como exige la regla de
     coordinación cross-feature).

8. **Worker check.** Ejecutado por el revisor:
   `python -m apps.worker --check` → exit 0.
   Output: `Worker --check OK: kinds=reel_publish, scripted_render
   worker_count=1 lease=900s poll=0.50s`.

9. **Tests.**
   - `tests/integration/rendering/test_scripted_router.py` — 6 tests:
     202 feliz (con verificación SQL directa de
     `webhook_events.source_kind`), 404 site desconocido, 400 sin
     `site_id`, 400 sin `source_property_id`, 400 body no-JSON, 400
     content-type incorrecto.
   - `tests/unit/rendering/test_enqueue_scripted_render.py` — 5 tests:
     enqueue feliz, site desconocido, source paused, site_id en
     blanco, agency huérfana.
   - Total `pytest -q`: **331 passed in 159.85s**. Baseline pre-feature
     ≥ 320; suma 11 tests nuevos (6 integración + 5 unit) → 320 + 11 =
     331. ✅

10. **`./init.sh` verde.** Ejecutado por el revisor: termina con
    `[OK] Entorno listo. Puedes empezar a trabajar.`. El único `[WARN]`
    es informativo (31 archivos modificados en directorios legacy en las
    últimas 24h) y corresponde al borrado esperado en
    `services/transport/http/{server.py,openapi_docs.py}`.

## Checkpoints

- C1 — arnés completo: [x] (`AGENTS.md`, `CLAUDE.md`, `init.sh`,
  `feature_list.json`, `progress/current.md`, los 3 docs y
  `CHECKPOINTS.md` presentes; `./init.sh` exit 0).
- C2 — estado coherente: [x] (`feature_list.json[id=8].status =
  "in_progress"`, no `done`; `progress/current.md` describe la sesión
  activa; `progress/impl_8_*.md` y este review presentes).
- C3 — arquitectura respetada:
  - [x] `modules/rendering/` no importa de
    `modules/<otro>/application` ni `modules/<otro>/infrastructure`.
  - [x] `domain/` libre de SQLAlchemy (no hay nuevo `domain/` en
    rendering; el use case está en `application/`).
  - [x] No hay nuevo repositorio en esta feature; los UoW namespaces
    usados ya extienden `ModuleRepository` y no commitean.
  - [x] `provider_secret_bundle=""` — no se persisten secrets en
    plano (no hay secret en el flujo scripted).
  - [x] No hay código nuevo en `services/`, `application/`,
    `repositories/`, `core/`, `domain/`. Las modificaciones a
    `services/transport/http/server.py` y `…/openapi_docs.py` son
    **borrados** legacy (esperados por
    `phase_2_operating_rules.md` §2).
- C4 — verificación real:
  - [x] Use case nuevo cubierto por unit (5 tests) + integration (6
    tests).
  - [x] Tests integración usan `tests/support/postgres.py`
    (`temporary_postgres_schema`, `seed_tenant`,
    `temporary_workspace`).
  - [x] `pytest -q`: 331 passed, ningún flake.
  - [x] `python -m apps.api --check` y `python -m apps.worker --check`
    exit 0.
- C5 — schema/migraciones: [x] No hay cambios de schema en esta
  feature; `webhook_events.source_kind` ya soporta `scripted_api` (sin
  CHECK constraint en
  `alembic/versions/20260501_0001_initial_schema.py:486`).
- C6 — sesión cerrada bien:
  - [x] No `*.tmp`, `__pycache__/` fuera de `.gitignore`, etc.
  - [x] feature 8 sigue `in_progress` (correcto: el cierre admin lo
    hace otro agente).
  - [x] Sin `print()` ni TODOs sin contexto en el código nuevo.
  - [x] No se han colado credenciales.

## Observaciones menores (no bloqueantes)

- El router define helpers privados `_parse_content_length` y
  `_parse_json_object_payload` inline
  (`scripted_router.py:220-249`). Otros routers de Phase 2 los inlinean
  por igual; no hay un módulo compartido en `apps/api/json_payload.py`
  todavía. No es un blocker — se podría consolidar en una feature
  housekeeping futura.
- La response Pydantic tiene `source_property_id: int | None = None`,
  pero el router siempre lo recibe como `int` (rechaza `None` en el
  validador eager). Es consistente con el dominio — `property_id` en
  `JobEnqueueRequest` admite `None` por contrato.
- El test `test_scripted_render_rejects_missing_source_property_id`
  envía `slides: []` con un site_id válido. La validación de slides la
  hace el worker; el router rechaza primero por
  `SOURCE_PROPERTY_ID_REQUIRED`. Comportamiento esperado.

## Cambios requeridos

Ninguno.

APPROVED -> ver progress/review_8_rendering_scripted_router.md
