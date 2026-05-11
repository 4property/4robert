# Review — feature 16 (`worker_real_use_cases_and_drop_noop_dispatcher`)

**Veredicto:** APPROVED

## Resumen

Acceptance literal cumplida. `ReelPipeline.handle` reescrito (62 → 278 LoC en
`modules/reels/application/orchestrator.py`) compone los 4 use cases reales
(`Ingest`/`Prepare`/`Persist`/`Publish`) + `DefaultMediaRenderer` con un
`_LocalArtifactsPublisher` adapter inline; ya no delega en
`application.bootstrap.runtime.build_default_job_handler`. `_NoopDispatcher`
borrado de `apps/api/app_factory.py` (428 → 390 LoC); sustituido por
`dispatcher_state = (lambda: True) if dispatcher_accepting_jobs is None else
dispatcher_accepting_jobs` (`:202-204`) y `lifespan` queda en `yield`
(`:207-208`). 4 archivos huérfanos del pipeline legacy borrados:
`application/pipeline/{media_pipeline.py, interfaces.py, job_runner.py}` y
`application/bootstrap/pipeline_adapters.py`. `application/bootstrap/{runtime,__init__}.py`
limpiados a 68 LoC (≤95) byte-iguales (`diff` exit 0). `modules/reels/application/use_cases/__init__.py`
reducido a 28 LoC (≤30): la copia duplicada de `RenderScriptedVideoUseCase`
ha sido sustituida por un re-export limpio. 2 tests integration nuevos en
`tests/integration/delivery/test_worker_dispatcher_flow.py` (397 LoC) cubren
`claim → handler real → outbox` para ambos kinds. **`./init.sh` verde con 455
passed (baseline 453 + 2 nuevos)** en 191.76s. `apps.api --check` y
`apps.worker --check` exit 0.

La desviación del UoW compartido (cada use case abre su UoW corto en lugar
del UoW único del plan) está documentada en §2.2/§4.1 del informe del
implementer con evidencia técnica del deadlock (`psycopg/waiting.py:265
wait_select` → `reel_state_repository.py:120 save`) y reproduce el patrón
de `tests/integration/reels/test_publish_reel_flow.py:171,207,244`. Decisión
ACEPTADA per la cláusula del leader. Sugerencia menor: feature 18 podría
revisitar la atomicidad end-to-end refactorizando el `local_publisher`
Protocol intermedio.

## Checks superados

### A. Acceptance literal

- [x] **A1** `apps/worker/runtime.py:271-278` registra `pipeline.handle`
  (`reel_publish`) y `scripted.execute` (`scripted_render`). Lazy
  instantiation con `workspace_dir` y `database_locator` en `:262-270`. **OK**.
- [x] **A2** `_NoopDispatcher` removido de `apps/api/app_factory.py`.
  `Grep "_NoopDispatcher"` en repo: hits solo en `progress/*.md` y
  `REFACTOR_STATUS.md` (informes históricos). 0 hits en código vivo. **OK**.
- [x] **A3** `tests/integration/delivery/test_worker_dispatcher_flow.py`
  (397 LoC) con 2 tests significativos:
  - `test_reel_publish_handler_completes_job_and_writes_outbox` (`:90-199`):
    `claim → ReelPipeline.handle (real) → ack` con
    `LocalPhotoSelectionEngine.select_photos`, `DefaultMediaRenderer.render_media`
    y `_build_default_social_property_publisher` stubeados. Verifica
    `jobs.status=completed`, `webhook_events.status=completed`, fila
    `outbox_events.event_type=publish_completed` con `status=completed`.
  - `test_scripted_render_handler_processes_job` (`:201-263`): `claim →
    RenderScriptedVideoUseCase.execute → ack` con
    `ScriptedVideoRenderService.{__init__,render_from_manifest}` stubeados.
    Verifica `jobs.status=completed` y `webhook_events.status=completed`.
  Reusa `temporary_postgres_schema`, `temporary_workspace`, `seed_tenant`,
  `seed_provider_connection` de `tests/support/postgres.py`. **OK**.
- [x] **A4** `pytest -q` end-to-end verde con **455 passed** en 191.76s
  (baseline 453 + 2 nuevos ≥ 455). **OK**.
- [x] **A5** `python -m apps.api --check` exit 0 + `python -m apps.worker
  --check` exit 0 (verificados por `init.sh` step 5). **OK**.

### B. Calidad del código

- [x] **B1** `modules/reels/application/orchestrator.py` reescrito (62 →
  278 LoC). `ReelPipeline.__init__` (`:69-111`) instancia los 4 use cases
  + `DefaultMediaRenderer` + `_LocalArtifactsPublisher` adapter inline.
  `ReelPipeline.handle` (`:113-220`) compone los 3 caminos (`is_noop`,
  `not requires_render`, feliz) con `LoggedProcess` blocks por fase.
  Imports verificados con `Grep "^from "`: solo `application.types`,
  `domain.tenancy.context`, `modules.delivery.domain`, `modules.reels.application.use_cases.*`,
  `modules.rendering.application.frame_composition`, `settings`,
  `shared.db`, `shared.observability`. **No importa de
  `<otro>.application` ni `<otro>.infrastructure`**. (Nota:
  `modules.rendering.application.frame_composition` es la única
  cross-module application import, pero es la `DefaultMediaRenderer`
  que feature 14 movió allí explícitamente — coherente con el plan
  R10 del explore). **OK**.
- [x] **B2** Desviación del UoW único documentada en `progress/impl_16_worker_real_use_cases.md`
  §2.2 y §4.1. Evidencia técnica: deadlock reproducido con
  `faulthandler.dump_traceback_later`, traceback bloqueado en
  `psycopg/waiting.py:265 wait_select` →
  `reel_state_repository.py:120 save`. El patrón `uow=None` por step
  reproduce `tests/integration/reels/test_publish_reel_flow.py:171,207,244`
  (cada use case abre su propio UoW). Comportamiento funcional
  preservado: filas en `reels`, `media_revisions`, `outbox_events` se
  escriben (verificado por test nuevo `outbox_event_types` ∋
  `"publish_completed"`). **ACEPTADA**.
- [x] **B3** `apps/api/app_factory.py:202-204` reemplaza la rama
  `_NoopDispatcher` por `dispatcher_state = (lambda: True) if
  dispatcher_accepting_jobs is None else dispatcher_accepting_jobs`.
  `lifespan` (`:206-208`) en `yield`. Docstring del módulo (`:18-23`)
  actualizada para retirar la referencia a `_NoopDispatcher` y explicar
  el contrato HTTP `dispatcher_accepting_jobs=True` para el proceso API.
  **OK**.
- [x] **B4** `application/bootstrap/runtime.py` y `__init__.py` byte-iguales
  (verificado: `diff` exit 0). 68 LoC (≤95). Conservan
  `WEBHOOK_SHUTDOWN_TIMEOUT_SECONDS`, `build_runtime_unit_of_work_factory`,
  `build_default_social_property_publisher`, `build_default_unit_of_work_factory`.
  Eliminan `build_default_property_media_pipeline`, `build_default_job_handler`,
  `build_default_job_dispatcher` + imports asociados (`PropertyMediaPipeline`,
  `DatabaseJobDispatcher`, `PropertyMediaJobRunner`, `DefaultMediaRenderer`,
  los 4 adapters de `pipeline_adapters`). `Grep
  "build_default_property_media_pipeline|build_default_job_handler|build_default_job_dispatcher"`
  en código vivo: 0 hits. **OK**.
- [x] **B5** `modules/reels/application/use_cases/__init__.py` 28 LoC
  (≤30). Solo re-exports + `__all__`. La copia duplicada de
  `RenderScriptedVideoUseCase` (`:22-51` legacy en pre-feature-16) ha
  sido sustituida por:
  ```python
  from modules.reels.application.use_cases.render_scripted_video import (
      RenderScriptedVideoUseCase,
  )
  ```
  Definición canónica intacta en `render_scripted_video.py:10-39`. **OK**.
- [x] **B6** Sin `print()`, `xfail`, TODO, FIXME en código vivo:
  - `modules/reels/application/orchestrator.py`: 0 hits.
  - `tests/integration/delivery/test_worker_dispatcher_flow.py`: 0 hits.
  - `apps/api/app_factory.py`: 0 hits.
  **OK**.

### C. Tests

- [x] **C1** Unit + integration tests verdes. 455 passed in `init.sh` step 6. **OK**.
- [x] **C2** Tests legacy (453 baseline) intactos. 453 + 2 = 455. **OK**.
- [x] **C3** `tests/integration/delivery/test_worker_dispatcher_flow.py`
  con 2 tests significativos (uno `reel_publish`, uno `scripted_render`).
  Stubs apropiados (renderer, photo selection, social publisher,
  ScriptedVideoRenderService) sin tocar el dispatcher real. **OK**.
- [x] **C4** Verificado independiente:
  `tests/integration/test_http_transport.py` + `tests/integration/apps_api/test_health_router.py`
  → **25 passed in 33.28s**. **OK**.

### D. Borrados

- [x] **D1** `application/pipeline/media_pipeline.py` borrado. **OK**.
- [x] **D2** `application/pipeline/interfaces.py` borrado. **OK**.
- [x] **D3** `application/pipeline/job_runner.py` borrado. **OK**.
- [x] **D4** `application/bootstrap/pipeline_adapters.py` borrado. **OK**.
- [x] **D5** `application/pipeline/content_generation.py` y
  `application/scripted_render/service.py` CONSERVADOS. `ls
  application/pipeline/`: solo `__init__.py` y `content_generation.py`. **OK**.

### E. Imports huérfanos

- [x] **E1** `Grep "from application.pipeline.media_pipeline\|from
  application.pipeline.interfaces\|from application.pipeline.job_runner\|from
  application.bootstrap.pipeline_adapters\|PropertyMediaPipeline\|PropertyMediaJobRunner\|_NoopDispatcher"`:
  todos los hits son en `progress/*.md` (informes históricos) o en
  docstrings de archivos vivos (`orchestrator.py:6` "replaces ``PropertyMediaPipeline``"
  y `frame_composition.py:22` "the legacy ``MediaRenderer`` Protocol").
  0 hits en imports/declaraciones de código vivo. **OK**.

### F. Schema

- [x] **F1** `ls alembic/versions/`: solo `20260501_0001_initial_schema.py`.
  Sin nueva migración. **OK**.

## Verificaciones de Ejecución

| # | Comando | Resultado |
|---|---------|-----------|
| 1 | `wc -l modules/reels/application/orchestrator.py` | 278 (rewrite). **OK**. |
| 2 | `wc -l apps/api/app_factory.py` | 390 (vs 428 pre-feature, -38). **OK**. |
| 3 | `wc -l application/bootstrap/runtime.py __init__.py` | 68 cada uno (≤95). **OK**. |
| 4 | `wc -l modules/reels/application/use_cases/__init__.py` | 28 (≤30). **OK**. |
| 5 | `wc -l tests/integration/delivery/test_worker_dispatcher_flow.py` | 397. **OK**. |
| 6 | `diff application/bootstrap/runtime.py application/bootstrap/__init__.py` | exit 0 (byte-iguales). **OK**. |
| 7 | `Grep "_NoopDispatcher"` en código vivo | 0 hits. **OK**. |
| 8 | `Grep "from application.pipeline.{media_pipeline,interfaces,job_runner}\|from application.bootstrap.pipeline_adapters"` en código vivo | 0 hits. **OK**. |
| 9 | `Grep "PropertyMediaPipeline\|PropertyMediaJobRunner"` en código vivo | 0 hits (solo docstring mentions). **OK**. |
| 10 | `Grep "build_default_property_media_pipeline\|build_default_job_handler\|build_default_job_dispatcher"` en código vivo | 0 hits. **OK**. |
| 11 | `ls application/pipeline/` | `__init__.py` + `content_generation.py`. **OK** (D1-D3 + D5 cumplidos). |
| 12 | `ls application/bootstrap/` | `__init__.py` + `runtime.py`. **OK** (D4 cumplido). |
| 13 | `ls alembic/versions/` | solo `20260501_0001_initial_schema.py`. **OK**. |
| 14 | `./init.sh` end-to-end | **455 passed in 191.76s**. ≥ 455 esperado. **OK**. |
| 15 | `python -m apps.api --check` | exit 0. **OK**. |
| 16 | `python -m apps.worker --check` | exit 0. **OK**. |
| 17 | `pytest tests/integration/test_http_transport.py tests/integration/apps_api/test_health_router.py` | 25 passed in 33.28s. **OK**. |
| 18 | Firmas `execute(uow=)` de los 4 use cases | preservadas (verificado: `ingest_property_into_reel.py:263`, `prepare_reel_assets.py:149`, `persist_local_artifacts.py:138`, `publish_reel.py:148`, todas con `*, uow: DatabaseUnitOfWork \| None = None`). **OK**. |

## Recorrido de CHECKPOINTS.md

- **C1 (arnés completo)**: [x] `init.sh` exit 0; archivos base presentes
  (AGENTS.md, CLAUDE.md, feature_list.json, progress/current.md,
  docs/{architecture,conventions,verification}.md, CHECKPOINTS.md).
- **C2 (estado coherente)**: [x] `feature_list.json` feature 16 en
  `in_progress` (closer la promueve a `done`). Como mucho una feature
  `in_progress`. Todas las anteriores `done`.
- **C3 (arquitectura)**: [x] `modules/reels/application/orchestrator.py`
  no importa de `<otro>.application` (excepto `modules.rendering.application.frame_composition`,
  el `DefaultMediaRenderer` movido por feature 14 — explícitamente
  permitido por el plan R10) ni `<otro>.infrastructure`. `domain/`
  (`domain.tenancy.context`) sin SQLAlchemy. Repositorios no se han
  tocado. Los 4 use cases NO se han tocado (firmas `execute(uow=)`
  preservadas). Modificaciones en `application/bootstrap/` son
  compat-shim cleanup (Phase 2 §2 "borrar todo lo legacy a medida que
  se mueve"). **OK**.
- **C4 (verificación real)**: [x] 2 integration tests nuevos cubren
  `claim → handler real → outbox`; usan `tests/support/postgres.py`
  (`temporary_postgres_schema`, `seed_tenant`, `seed_provider_connection`),
  no mocks de Postgres. `pytest -q` 455 verdes; `apps.api --check` /
  `apps.worker --check` exit 0.
- **C5 (schema)**: [x] No se modificó `shared/db/orm.py`; sin nueva
  migración.
- **C6 (cierre limpio)**: [x] Sin `__pycache__/.tmp_*` residual
  (gitignore). `feature_list.json` feature 16 `in_progress` (closer
  promueve a `done`). Sin `print()` debug; sin TODOs nuevos.

## Sobre la desviación del UoW compartido (§2.2 / §4.1 impl)

**ACEPTADA**. Razones:

1. **Justificación técnica con evidencia**: el implementer reproduce el
   deadlock con `faulthandler.dump_traceback_later` y captura la
   traceback bloqueada en `psycopg/waiting.py:265 wait_select` →
   `reel_state_repository.py:120 save`. El motivo es que
   `_LocalArtifactsPublisher.publish_media` delega en
   `PersistLocalArtifactsUseCase.execute(context, rendered_media)` sin
   `uow=`, abriendo una conexión nueva que choca contra el row-lock que
   el UoW exterior ya tiene sobre la fila `reels`. Esto NO es un
   deadlock teórico: el implementer documenta haberlo reproducido.
2. **Coherencia con el patrón existente**: el comportamiento es
   funcionalmente equivalente al legacy `PropertyMediaPipeline.run_job`
   que ya abría 4 UoWs separados (cada adapter tenía el suyo).
   Reproduce `tests/integration/reels/test_publish_reel_flow.py:171,207,244`
   (también UoWs separados). No introduce regresiones de comportamiento
   funcional.
3. **Tests pasan**: `outbox_events.event_type=publish_completed` con
   `status=completed` se escribe (`test_reel_publish_handler_completes_job_and_writes_outbox`
   verifica). Las filas en `reels`, `media_revisions`, `outbox_events`
   son consistentes con el flujo pre-feature-16.
4. **Alternativa razonablemente rechazada**: cambiar la firma de
   `local_publisher.publish_media` para aceptar `uow=` requeriría tocar
   `PublishReelUseCase.execute` (out-of-scope feature 16, regla dura).

**Sugerencia menor (no bloquea)**: feature 18 (o Phase 3) puede
revisitar la atomicidad end-to-end. La ruta limpia probablemente
implica refactorizar el `local_publisher` Protocol intermedio para que
`PublishReelUseCase` invoque `PersistLocalArtifactsUseCase` con `uow=`
explícito y se permita un UoW exterior compartido.

## Sugerencias menores (no bloquean)

1. `orchestrator.py` 278 LoC vs ~170 estimados. La diferencia es
   docstring extendida (módulo + adapter + helper) y `LoggedProcess`
   blocks con detalle por línea. Aceptable: conservar logging es R8 del
   explore.
2. `_build_default_social_property_publisher` (`orchestrator.py:245-250`)
   sigue haciendo lazy import de `application.bootstrap.runtime` para
   romper el ciclo de imports. Coherente con el patrón de los use
   cases. Feature 17/18 puede mover esta función a `modules/publishing/`
   cuando retire el módulo legacy.
3. Test `test_reel_publish_handler_completes_job_and_writes_outbox`
   accede al atributo privado `pipeline._publish.social_publisher`
   (`:161-162`) para inyectar el fake. Preferible un constructor kwarg
   explícito en `ReelPipeline` (p. ej. `social_publisher_factory=`),
   pero out-of-scope feature 16.
4. WARN de `init.sh` step 4 ("4 archivos modificados en legacy en
   últimas 24h") es esperado: 2 modificaciones en
   `application/bootstrap/{runtime,__init__}.py` + 4 borrados en
   `application/{pipeline,bootstrap}/`. Coherente con el patrón
   aplicado en features 10-15.

**Fin de la review.**
