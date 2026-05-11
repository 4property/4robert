# Explore — Feature 16 `worker_real_use_cases_and_drop_noop_dispatcher`

> Reemplazo del puente legacy del worker (que sigue cayendo en
> `PropertyMediaPipeline` via `application/bootstrap/runtime.py`) por una
> composición moderna de los 4 use cases (`ingest`/`prepare`/`persist`/`publish`)
> compartiendo un único `DatabaseUnitOfWork`, retirada del `_NoopDispatcher`
> de `apps/api/app_factory.py`, y test integración nuevo bajo
> `tests/integration/delivery/test_worker_dispatcher_flow.py`.
>
> Esta es la última feature antes de 17/18 que cierran Phase 2 borrando
> `repositories/`, `application/`, `services/`, `core/`, `domain/`. Esta
> feature pone el punto y final al doble UoW: tras 16, los 4 use cases
> comparten un único UoW por job.

Contexto leído (en el orden exigido por la tarea):

1. `feature_list.json` (entry id=16, acceptance literal). Nota de orden:
   "La feature 16 NO puede empezar hasta que 10-14 estén done (necesita
   los use cases reales)" — features 10-15 marcadas `done`.
2. `progress/explore_feature_15_layout_split.md` (estructura del informe;
   patrón de § §0 alcance / §1 LoC / §… discrepancias),
   `progress/impl_15_layout_split.md` (LoC reales: 453 tests verdes
   post-15) y `progress/review_15_layout_split.md` (APPROVED).
3. `progress/explore_feature_14_pure_renderer_and_delete_media_services.md`
   §0 promete: *"feature 16 los va a borrar [los 4 adapters de
   `pipeline_adapters.py`] enteros de todas formas (sustituye
   `PropertyMediaPipeline` legacy por una composición moderna de los 4
   use cases en `modules/reels/application/`)"*. §6 R1 confirma el doble
   UoW como riesgo aceptado para feature 14, *"lo arregla feature 16"*.
4. `apps/worker/runtime.py` (288 LoC, leído íntegro). Bridge actual:
   - Imports `ReelPipeline`, `RenderScriptedVideoUseCase` directamente
     (`:17-20`).
   - `build_default_dispatcher` registra ambos como handlers
     (`:259-279`).
5. `apps/worker/main.py` (107 LoC). CLI `--check` invoca
   `build_default_dispatcher(settings=settings)` y reporta los kinds
   registrados (`:54-74`).
6. `apps/worker/__init__.py` y `__main__.py` (1 + 6 LoC, sólo wiring).
7. `apps/api/app_factory.py` (428 LoC, leído íntegro).
   - `_NoopDispatcher` definido en `:105-134`, instanciado en `:231`,
     start/stop en `lifespan` (`:234-240`).
   - `dispatcher_state: Callable[[], bool]` se inyecta a
     `health_router` (`:316`) y `wordpress_webhook_router` (`:423`).
   - Sin call sites externos a `_NoopDispatcher` — clase privada del
     archivo.
8. `modules/reels/application/orchestrator.py` (62 LoC). `ReelPipeline.handle`
   hace **lazy import** (`:25`) de
   `application.bootstrap.runtime.build_default_job_handler` y delega
   en él. El handler resultante invoca el legacy
   `PropertyMediaPipeline.run_job`. Wrapper que adapta `Job` →
   `PropertyMediaJob` vía `build_property_media_job` (`:34-55`).
9. Las 4 firmas `execute(...)` de los use cases reales:
   - `IngestPropertyIntoReelUseCase.execute(self, job: PropertyMediaJob, *, uow: DatabaseUnitOfWork | None = None) -> PropertyContext`
     (`ingest_property_into_reel.py:263-274`). Soporta `uow=` por
     parámetro (auto-abre uno si `None`).
   - `PrepareReelAssetsUseCase.execute(self, context: PropertyContext, *, uow: DatabaseUnitOfWork | None = None) -> PreparedMediaAssets`
     (`prepare_reel_assets.py:149-168`). Idem.
   - `PersistLocalArtifactsUseCase.execute(self, context, rendered_media, *, uow: DatabaseUnitOfWork | None = None) -> PublishedMediaArtifact`
     (`persist_local_artifacts.py:138-186`). Idem.
   - `PublishReelUseCase.execute(self, context, rendered_media, *, uow: DatabaseUnitOfWork | None = None) -> PublishedMediaArtifact`
     (`publish_reel.py:148-156`). Idem.
10. `modules/rendering/application/use_cases/enqueue_scripted_render.py`
    (154 LoC). Use case **del API** (encola un job `scripted_render`).
    Distinto del que ejecuta el worker.
11. **`RenderScriptedVideoUseCase`** definida en DOS sitios:
    - `modules/reels/application/use_cases/render_scripted_video.py:10-39`
      (42 LoC, archivo dedicado).
    - `modules/reels/application/use_cases/__init__.py:22-51` (idéntica
      copy-paste, también re-exportada en `__all__`).
    Ambas hacen lazy-import a `application.scripted_render.service.ScriptedVideoRenderService`.
    `apps/worker/runtime.py:18-20` importa de `render_scripted_video.py`
    (no del `__init__`), por lo que la clase del `__init__.py` está
    huérfana.
12. `application/bootstrap/runtime.py` y `application/bootstrap/__init__.py`
    (187 LoC cada uno, byte-iguales). El handler legacy actual:
    - `build_default_property_media_pipeline()` construye
      `PropertyMediaPipeline` con los 4 adapters legacy de
      `pipeline_adapters.py`.
    - `build_default_job_handler()` envuelve el pipeline con
      `PropertyMediaJobRunner` (file-lock + logging) y lo retorna como
      callable.
    - Esos son los símbolos que `ReelPipeline.handle` invoca lazy.
13. `application/pipeline/`:
    - `media_pipeline.py` (133 LoC): `PropertyMediaPipeline.run_job`
      orquesta los 4 pasos (ingest → prepare → render → publish) sobre
      los Protocols.
    - `interfaces.py` (112 LoC): los 4 Protocols
      (`PropertyInfoService`, `MediaPreparationService`, `MediaRenderer`,
      `MediaPublisher`) + `PhotoSelectionEngine`.
    - `job_runner.py` (70 LoC): `PropertyMediaJobRunner.run` con
      `exclusive_file_lock` + `LoggedProcess`.
    - `content_generation.py` (150 LoC): `ContentGenerator` Protocol +
      `DeterministicPropertyContentGenerator`. **Sigue vivo** — lo
      consume `IngestPropertyIntoReelUseCase` y
      `application/bootstrap/pipeline_adapters.py` (re-exports).
    - `__init__.py` (1 LoC, package marker — feature 14 lo vació).
14. `application/bootstrap/pipeline_adapters.py` (237 LoC, leído íntegro).
    Los 4 adapters thin que envuelven los use cases modernos para que
    `PropertyMediaPipeline` legacy los consuma vía Protocols. Cada uno
    abre **su propio** `DatabaseUnitOfWork` (por eso hay doble/cuádruple
    UoW hoy: cada paso del pipeline abre uno).
15. `tests/integration/`:
    - `delivery/` **NO existe**. Acceptance pide
      `tests/integration/delivery/test_worker_dispatcher_flow.py` —
      hay que crear el directorio.
    - Tests existentes con worker: `tests/integration/test_worker_runtime.py`
      (149 LoC). 2 tests, ambos registran handler **mock**
      (`lambda job: ...`); no ejercitan `ReelPipeline.handle` real.
    - `tests/integration/reels/test_publish_reel_flow.py` (304 LoC) ya
      ejercita la cadena ingest → prepare → persist → publish con
      `_LocalPublisherAdapter` y un `_FakePropertyPublisher`. Plantilla
      cercana al test nuevo; falta el envoltorio "claim → handler →
      outbox" del dispatcher.
16. `tests/integration/test_worker_runtime.py` — ver §15. La ruta `claim
    → handler → outbox` del dispatcher YA está testeada con un handler
    mock. Lo nuevo de feature 16 es ejercitar **el handler real** vía
    `ReelPipeline.handle`.
17. `docs/phase_2_operating_rules.md` (321 LoC):
    - §2 "borrar todo lo legacy a medida que se mueve" + "no hay
      bridges, no hay compat shims, no hay xfail".
    - §4 "sin commits por feature".
    - §6 baseline 116+ tests verdes (post-15: 453, ver `impl_15`).
    - §8 "blocked si las premisas cambian".
    - **§5 sobre feature 16: no hay sección dedicada** (las features
      9-18 no tienen patches específicos). El acceptance literal de
      `feature_list.json` gobierna.
18. `docs/architecture.md` y `docs/conventions.md` — patrón ya
    estabilizado: `from __future__ import annotations`, type hints,
    use cases en `modules/<bc>/application/use_cases/`, no importes
    cross-module entre `<otro>.application` y `<otro>.infrastructure`.

---

## 0. Decisión de alcance

`feature_list.json` #16 dice literalmente:

> Sustituir los bridges legacy del worker por las invocaciones reales:
> reel_publish → composición de los use cases ingest/prepare/persist/publish
> (ReelPipeline en modules/reels/application/), scripted_render →
> RenderScriptedVideoUseCase. Eliminar _NoopDispatcher de apps/api/app_factory.py.

Acceptance:

> - apps/worker/runtime.py registra ReelPipeline y RenderScriptedVideoUseCase
>   como handlers reales.
> - Bridges legacy en apps/worker/ borrados.
> - _NoopDispatcher removido de apps/api/app_factory.py.
> - tests/integration/delivery/test_worker_dispatcher_flow.py cubre
>   claim → handler → outbox end-to-end.
> - pytest -q termina verde.
> - python -m apps.api --check y python -m apps.worker --check exit 0.

### A. ¿Qué es exactamente "ReelPipeline en modules/reels/application/"?

`ReelPipeline` **ya existe** como `modules/reels/application/orchestrator.py`
(62 LoC) **pero NO hace lo que el acceptance dice**. Hoy:

- `ReelPipeline.handle(job)` lazy-importa
  `application.bootstrap.runtime.build_default_job_handler`, que devuelve
  un callable construido sobre `PropertyMediaPipeline` legacy. **No
  compone los 4 use cases directamente.**
- Es un envoltorio delgado para no acoplar `apps/worker/runtime.py` al
  módulo legacy `application.bootstrap`.

Feature 16 **reescribe el cuerpo** de `ReelPipeline.handle` para que
componga los 4 use cases modernos directamente (sin pasar por
`build_default_job_handler` ni `PropertyMediaPipeline`). El archivo y la
clase mantienen el path
(`modules/reels/application/orchestrator.py:ReelPipeline`); los call
sites externos en `apps/worker/runtime.py:17,263,272-274` no cambian.

### B. ¿Qué bridges legacy hay en `apps/worker/`?

Tras leer `apps/worker/` (5 archivos), **NO hay bridges legacy en
`apps/worker/` propiamente**:

| Archivo | LoC | Contenido |
|---------|-----|-----------|
| `apps/worker/__init__.py` | 1 | docstring placeholder |
| `apps/worker/__main__.py` | 6 | wiring `python -m apps.worker` → `main()` |
| `apps/worker/main.py` | 107 | CLI con `--check`, configura logging, instancia `WorkerSettings`, llama a `build_default_dispatcher` |
| `apps/worker/runtime.py` | 288 | `JobDispatcher`, `WorkerSettings`, `JobHandler`, `build_default_dispatcher` |

`apps/worker/runtime.py` ya importa `ReelPipeline` y
`RenderScriptedVideoUseCase` directamente (líneas `:17-20`) y los registra
como handlers (`:259-279`). **No hay archivos a borrar bajo
`apps/worker/`**. La acceptance literal "Bridges legacy en `apps/worker/`
borrados" se interpreta como:

- **(B1)** Que `ReelPipeline.handle` deje de delegar en
  `application.bootstrap.runtime.build_default_job_handler`. Hoy esa
  cadena `worker → ReelPipeline → application.bootstrap → PropertyMediaPipeline →
  pipeline_adapters → use cases` ES el bridge legacy. Tras feature 16,
  esa cadena pasa a ser `worker → ReelPipeline → use cases (directo)`.
- **(B2)** Borrado físico de los archivos legacy ya sin call sites tras
  el rewrite de `ReelPipeline.handle` (ver §6 R3 abajo): si nadie consume
  `PropertyMediaPipeline`, `PropertyMediaJobRunner`, los 4 adapters de
  `pipeline_adapters.py`, los Protocols de `interfaces.py`, ni
  `build_default_property_media_pipeline`/`build_default_job_handler`,
  esos símbolos se borran en feature 16. Es la lectura
  "acceptance + §2 phase_2_operating_rules" (borrar legacy a medida).

**Mi lectura preferida: ambas (B1 + B2)**. La feature 18 cierra Phase 2
borrando `application/` enterito; si feature 16 sólo hace (B1) sin (B2),
queda código muerto en `application/pipeline/` y `application/bootstrap/`
hasta feature 18, pero la operating-rule §2 dice "borrar a medida que
se mueve". El leader puede limitar el scope a (B1) y dejar (B2) para 18
si lo prefiere; ver §6 R3 para el desglose de archivos.

### C. ¿`RenderScriptedVideoUseCase` existe? ¿Dónde?

**SÍ existe**. De hecho duplicada:

- `modules/reels/application/use_cases/render_scripted_video.py:10-39`
  (42 LoC). Fuente canónica importada por
  `apps/worker/runtime.py:18-20`.
- `modules/reels/application/use_cases/__init__.py:22-51`. Copia
  redundante (también re-exportada en `__all__`). **Huérfana** — ningún
  caller la importa de ahí.

Ambas tienen el **mismo cuerpo**: lazy-import de
`application.bootstrap.runtime.build_runtime_unit_of_work_factory` +
`application.scripted_render.service.ScriptedVideoRenderService`,
ejecutan `render_from_manifest(payload)`. **Igual que `ReelPipeline`,
sigue dependiendo del legacy `application.bootstrap.runtime` y de
`application.scripted_render.service`** — esto último es esperado, no
se mueve en feature 16 (es una cadena distinta, ver §6 R6).

NO confundir con `EnqueueScriptedRenderUseCase`
(`modules/rendering/application/use_cases/enqueue_scripted_render.py`,
feature 8): ese es el use case del API que encola el job; el del worker
es `RenderScriptedVideoUseCase` y solo ejecuta el render.

**Cambio mínimo recomendado en feature 16**: borrar la copia duplicada
en `__init__.py` (mantener sólo el archivo dedicado y el re-export
limpio en `__init__.py`). Es housekeeping aceptable dado que feature 16
toca este archivo.

### D. ¿Qué hace `_NoopDispatcher` y qué lo reemplaza?

`_NoopDispatcher` (`apps/api/app_factory.py:105-134`):

- Clase privada del archivo (sin call sites externos).
- Métodos: `start()` (flip flag a `True`), `stop()` (flip a `False`),
  `wait_for_idle()` (siempre `True`), `is_accepting_jobs()` (devuelve
  flag), `count_active_jobs()` (siempre `0`).
- Se instancia en el `lifespan` (`:231`) cuando el caller no pasa
  `dispatcher_accepting_jobs`. En tests, los tests pasan un
  `Callable[[], bool]` directo y el `_NoopDispatcher` no se usa.
- Su único output observable es `is_accepting_jobs()`, que se inyecta
  como `dispatcher_state` a:
  - `create_health_router(... dispatcher_accepting_jobs=dispatcher_state)`
    (`:316`) — feed para `/health/ready` y `dispatcher_accepting_jobs`
    en el JSON.
  - `create_wordpress_webhook_router(... dispatcher_state=dispatcher_state)`
    (`:423`) — el webhook stampea `dispatcher_accepting_jobs` en su
    response.

**Razón histórica** (documentada en
`progress/explore_feature_9_retire_server.md:213-227`): el legacy
`WordPressWebhookServer` orquestaba el dispatcher real en el mismo
proceso. Cuando el proceso se partió (API + worker separados, cada uno
en su propio container), la API ya no orquesta dispatcher; pero el
contrato HTTP `/health/ready` y la response del webhook seguían
exponiendo `dispatcher_accepting_jobs`. `_NoopDispatcher` fue la
solución de transición: la API expone "sí, el worker está aceptando"
estáticamente.

**Reemplazo en feature 16**: el dispatcher real vive solo en
`apps/worker/`. La API ya **no** necesita exponer
`dispatcher_accepting_jobs` con un dispatcher local. Dos opciones:

- **(D1)** El campo `dispatcher_accepting_jobs` desaparece del contrato
  HTTP (de `/health/ready` y de la response del webhook).
- **(D2)** El campo se mantiene pero hardcoded a `True` (todo el tiempo
  que la API esté arriba). Equivalente al noop actual, pero sin la
  clase ni el lifespan.

**Mi lectura preferida: (D2) hardcoded a `True`**. Razones:

- Cambia menos contrato externo. Los tests
  `tests/integration/test_http_transport.py:120-151` y
  `tests/integration/apps_api/test_health_router.py:20-68` esperan el
  campo `dispatcher_accepting_jobs`. Adaptar 9 tests por cambiar de "noop
  flag" a "hardcoded True" es trivial; eliminar el campo entero requiere
  cambiar el contrato de 3 endpoints (`/health/ready`, webhook,
  `/health` JSON).
- El acceptance literal pide eliminar `_NoopDispatcher`, no eliminar
  `dispatcher_accepting_jobs`. Si el campo se elimina, hay un cambio de
  API silencioso; si se hardcodea, el cliente HTTP no nota nada.
- El usuario real del flag (decidir si encolar o esperar) era el caso
  god-class; en multi-proceso decoupled, el API no tiene visibilidad de
  si el worker está vivo.

**Concreto** en `app_factory.py`:

- Borrar la clase `_NoopDispatcher` (`:105-134`).
- Borrar el `dispatcher` local en `:231`.
- Sustituir el `dispatcher_state` de la rama
  `if dispatcher_accepting_jobs is None`: `dispatcher_state = lambda: True`
  (o similar; `lambda: True` es el patrón más limpio). El `lifespan` que
  arranca/para el dispatcher se vuelve un no-op; mantenerlo vacío
  (`async def lifespan(app): yield`).
- Actualizar la docstring del módulo (`:1-24`) para retirar la
  referencia a `_NoopDispatcher`.
- Actualizar la docstring del kwarg `dispatcher_accepting_jobs`
  (`:158-171`).

### E. Pipeline legacy: ¿se borra en 16 o sobrevive a 18?

Pre-feature-16, los archivos vivos del pipeline legacy son:

| Archivo | LoC | Consumidores actuales |
|---------|-----|----------------------|
| `application/pipeline/media_pipeline.py` | 133 | `application/bootstrap/{runtime,__init__}.py:16` |
| `application/pipeline/interfaces.py` | 112 | `application/pipeline/media_pipeline.py:5-10` |
| `application/pipeline/job_runner.py` | 70 | `application/bootstrap/{runtime,__init__}.py:15` |
| `application/pipeline/content_generation.py` | 150 | `modules/reels/application/use_cases/ingest_property_into_reel.py:35-38`, `application/bootstrap/pipeline_adapters.py:27` |
| `application/bootstrap/runtime.py` | 187 | `apps/worker/__pycache__` runtime resolución (vía `ReelPipeline.handle` lazy import + `RenderScriptedVideoUseCase.execute` lazy import). Tests `test_social_publishing.py` importa `build_default_social_property_publisher`. |
| `application/bootstrap/__init__.py` | 187 | byte-igual a `runtime.py` |
| `application/bootstrap/pipeline_adapters.py` | 237 | `application/bootstrap/{runtime,__init__}.py:7-12` |

Tras la feature 16 (sin `PropertyMediaPipeline` ni
`PropertyMediaJobRunner` en uso):

- `media_pipeline.py`, `interfaces.py`, `job_runner.py` quedan **sin
  callers externos**.
- `pipeline_adapters.py` (los 4 adapters) queda **sin callers externos**:
  los use cases modernos pasan a invocarse directamente desde
  `ReelPipeline.handle`.
- `application/bootstrap/runtime.py` y `__init__.py` quedan con varias
  funciones en uso:
  - `build_runtime_unit_of_work_factory` — usado por
    `RenderScriptedVideoUseCase.execute` (lazy) y
    `application.scripted_render.service`.
  - `build_default_social_property_publisher` — usado por
    `tests/test_social_publishing.py` y por `ReelPipeline.handle`
    nuevo (lo necesita para construir el `social_publisher` que pasa al
    `PublishReelUseCase`).
  - `build_default_unit_of_work_factory`, `build_default_property_media_pipeline`,
    `build_default_job_handler`, `build_default_job_dispatcher` quedan
    huérfanas tras feature 16.

**Recomendación**:

- **Borrar en feature 16:**
  - `application/pipeline/media_pipeline.py` (133 LoC).
  - `application/pipeline/interfaces.py` (112 LoC).
  - `application/pipeline/job_runner.py` (70 LoC).
  - `application/bootstrap/pipeline_adapters.py` (237 LoC) — los 4
    adapters ya no tienen consumidores tras (B1).
  - Funciones huérfanas en `application/bootstrap/{runtime,__init__}.py`:
    `build_default_property_media_pipeline`,
    `build_default_job_handler`, `build_default_job_dispatcher`. Y los
    imports asociados (`PropertyMediaPipeline`, `DatabaseJobDispatcher`,
    `PropertyMediaJobRunner`, `DefaultMediaRenderer`, los 4 adapters).
- **Mantener vivo (lo barre feature 18):**
  - `application/pipeline/content_generation.py` (150 LoC) — sigue
    consumido por `IngestPropertyIntoReelUseCase` y por tests. Movido a
    `modules/...` puede ser feature 17 o 18.
  - `application/bootstrap/{runtime,__init__}.py` reducidos a las
    funciones aún en uso (`build_runtime_unit_of_work_factory`,
    `build_default_social_property_publisher`,
    `build_default_unit_of_work_factory`).
  - `application/scripted_render/service.py` (677 LoC) — lo necesita
    `RenderScriptedVideoUseCase.execute` lazy.

Si el leader prefiere out-of-scope cualquiera de estos borrados, dejarlos
para feature 18. Mi default: borrar lo que feature 16 deja huérfano.

### Resumen del alcance final propuesto

| Acción | Archivos |
|--------|----------|
| **Modificar** | `modules/reels/application/orchestrator.py` — `ReelPipeline.handle` reescrito con composición real de los 4 use cases compartiendo UoW. |
| **Modificar** | `apps/api/app_factory.py` — borrar `_NoopDispatcher`, sustituir por `dispatcher_state = lambda: True` en la rama default; lifespan no-op. |
| **Modificar** | `application/bootstrap/runtime.py` y `__init__.py` (byte-iguales) — eliminar funciones legacy huérfanas y sus imports. |
| **Modificar** | `modules/reels/application/use_cases/__init__.py` — eliminar la copia duplicada de `RenderScriptedVideoUseCase`, dejar solo el re-export del archivo dedicado. |
| **Crear** | `tests/integration/delivery/__init__.py` (vacío, package marker). |
| **Crear** | `tests/integration/delivery/test_worker_dispatcher_flow.py` — claim → handler real → outbox end-to-end. |
| **Borrar** | `application/pipeline/media_pipeline.py` (133 LoC). |
| **Borrar** | `application/pipeline/interfaces.py` (112 LoC). |
| **Borrar** | `application/pipeline/job_runner.py` (70 LoC). |
| **Borrar** | `application/bootstrap/pipeline_adapters.py` (237 LoC). |
| **NO tocar** | `application/pipeline/content_generation.py` (sigue usado). |
| **NO tocar** | `application/scripted_render/service.py` (sigue usado por `RenderScriptedVideoUseCase`). |
| **NO tocar** | `apps/worker/runtime.py` — ya importa los use cases reales. |
| **NO tocar** | Los 4 use cases (`ingest`/`prepare`/`persist`/`publish`) ni `RenderScriptedVideoUseCase`. |

---

## 1. Cambios en `apps/worker/runtime.py`

### Registro actual de handlers

`apps/worker/runtime.py:259-279` (función `build_default_dispatcher`):

```python
def build_default_dispatcher(*, settings: WorkerSettings) -> JobDispatcher:
    """Build the production dispatcher with canonical Phase 2 bridge handlers."""
    dispatcher = JobDispatcher(settings=settings)
    workspace_dir = settings.base_dir or Path(__file__).resolve().parents[2]
    reel_pipeline = ReelPipeline(
        workspace_dir=workspace_dir,
        database_locator=settings.database_locator,
    )
    scripted_render = RenderScriptedVideoUseCase(
        workspace_dir=workspace_dir,
        database_locator=settings.database_locator,
    )
    dispatcher.register_handler(
        "reel_publish",
        reel_pipeline.handle,
    )
    dispatcher.register_handler(
        "scripted_render",
        scripted_render.execute,
    )
    return dispatcher
```

### Cambios en `apps/worker/runtime.py`

**Ningún cambio funcional**. La acceptance "registra ReelPipeline y
RenderScriptedVideoUseCase como handlers reales" **ya está cumplida** a
día de hoy (líneas `:271-274` y `:275-278`). Lo que cambia es lo que
`ReelPipeline.handle` hace por dentro (ver §3).

**Posible cambio cosmético** (opcional): la docstring de
`build_default_dispatcher` dice "canonical Phase 2 bridge handlers" —
tras feature 16 ya no son bridges. Cambiar a "canonical Phase 2 handlers"
o similar. Trivial; no afecta tests.

### Bridges a borrar en `apps/worker/`

**Cero**. `apps/worker/` no contiene bridges propiamente (ver §0.B).
La acceptance se cumple vacuamente: el bridge real está en
`ReelPipeline.handle` y se reemplaza ahí (no en `apps/worker/`).

---

## 2. Cambios en `apps/api/app_factory.py`

### Líneas afectadas

| Rango | Símbolo / sección | Acción |
|-------|-------------------|--------|
| `:7-12` | Docstring del módulo (mención a `_NoopDispatcher`) | Reescribir el bullet point. |
| `:105-134` | `class _NoopDispatcher` | **Borrar** entera (30 LoC). |
| `:152` | `dispatcher_accepting_jobs: Callable[[], bool] | None = None` | Mantener firma (no cambia el contrato kwargs). |
| `:158-171` | Docstring del kwarg `dispatcher_accepting_jobs` | Reescribir: ya no hay `_NoopDispatcher`. |
| `:230-246` | Rama `if dispatcher_accepting_jobs is None: ...` | Sustituir por `dispatcher_state = lambda: True` + lifespan no-op (`async def lifespan(app): yield`). |
| `:206-208` | Comentario `del webhook_auto_provision_unknown_sites_for_testing` que menciona "Once feature 16 rewires the dispatcher" | Limpiar comentario (la promesa se cumple). |

LoC delta: **−30 a −40** (borrado clase + simplificación lifespan).

### Tests a verificar / adaptar

`Grep "dispatcher_accepting_jobs"` en `tests/`:

- `tests/integration/test_http_transport.py:120,134,138,151` (4 hits) —
  inyecta `active_dispatcher.is_accepting_jobs` y verifica que
  `/health/ready` devuelve `dispatcher_accepting_jobs: True/False`. **El
  contrato de `build_api_app` no cambia** (el kwarg sigue ahí), así que
  estos tests siguen verdes sin modificación. El "active_dispatcher" del
  test es un mock local, no `_NoopDispatcher`.
- `tests/integration/apps_api/test_health_router.py:20,38,48,58,68`
  (5 hits) — idem.

**Cero adaptaciones de tests existentes** si se elige (D2). Si el
leader elige (D1), hay que adaptar los 9 hits + el cuerpo de
`create_health_router` y `create_wordpress_webhook_router`.

### `_NoopDispatcher` outside `app_factory.py`

`Grep "_NoopDispatcher"` en `tests/`: **0 hits**. No hay tests que
dependan del nombre. Sin riesgo de breakage.

---

## 3. `ReelPipeline` en `modules/reels/application/`

### Estado actual de `orchestrator.py:1-62` (62 LoC)

```python
class ReelPipeline:
    def __init__(self, *, workspace_dir, database_locator=None):
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.database_locator = database_locator
        self._handler: Callable[[object], object | None] | None = None

    def handle(self, job: Job) -> object | None:
        if self._handler is None:
            from application.bootstrap.runtime import build_default_job_handler
            self._handler = build_default_job_handler(
                self.workspace_dir,
                database_locator=self.database_locator,
            )
        return self._handler(build_property_media_job(job))
```

`build_property_media_job` (`:34-55`) sigue siendo necesario: traduce
`Job` (modelo de `modules.delivery.domain`) → `PropertyMediaJob` (modelo
de `application.types`, que aún consumen los 4 use cases modernos).

### Estado nuevo (esbozo)

```python
"""Reel pipeline orchestrator (step 0/4 of the worker handler).

Composes the 4 modern use cases (ingest / prepare / persist / publish)
sharing a single `DatabaseUnitOfWork` per job, replacing the legacy
`PropertyMediaPipeline` from `application/pipeline/media_pipeline.py`
that feature 16 retires.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from application.types import PropertyMediaJob, SocialPublishContext
from core.logging import LoggedProcess, format_detail_line
from domain.tenancy.context import TenantContext
from modules.delivery.domain import Job
from modules.reels.application.use_cases.ingest_property_into_reel import (
    IngestPropertyIntoReelUseCase,
)
from modules.reels.application.use_cases.persist_local_artifacts import (
    PersistLocalArtifactsUseCase,
)
from modules.reels.application.use_cases.prepare_reel_assets import (
    PrepareReelAssetsUseCase,
)
from modules.reels.application.use_cases.publish_reel import PublishReelUseCase
from modules.rendering.application.frame_composition import DefaultMediaRenderer
from settings import (
    DATABASE_URL,
    PROPERTY_MEDIA_DELETE_SELECTED_PHOTOS,
    PROPERTY_MEDIA_DELETE_TEMPORARY_FILES,
    SOCIAL_PUBLISHING_ENABLED,
    SOCIAL_PUBLISHING_LOCAL_ONLY,
    SOCIAL_PUBLISHING_PROPERTY_URL_TEMPLATE,
    SOCIAL_PUBLISHING_PROPERTY_URL_TRACKING_PARAMS,
)
from shared.db import DatabaseUnitOfWork


logger = logging.getLogger(__name__)


class ReelPipeline:
    def __init__(
        self,
        *,
        workspace_dir: str | Path,
        database_locator: str | Path | None = None,
    ) -> None:
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.database_locator = database_locator if database_locator is not None else DATABASE_URL
        social_active = SOCIAL_PUBLISHING_ENABLED and not SOCIAL_PUBLISHING_LOCAL_ONLY
        self._ingest = IngestPropertyIntoReelUseCase(
            workspace_dir=self.workspace_dir,
            property_url_template=SOCIAL_PUBLISHING_PROPERTY_URL_TEMPLATE,
            property_url_tracking_params=SOCIAL_PUBLISHING_PROPERTY_URL_TRACKING_PARAMS,
            social_publishing_enabled=social_active,
            database_locator=self.database_locator,
        )
        self._prepare = PrepareReelAssetsUseCase(
            workspace_dir=self.workspace_dir,
            cleanup_temporary_files=PROPERTY_MEDIA_DELETE_TEMPORARY_FILES,
            cleanup_selected_photos=PROPERTY_MEDIA_DELETE_SELECTED_PHOTOS,
            database_locator=self.database_locator,
        )
        self._renderer = DefaultMediaRenderer(self.workspace_dir)
        self._persist = PersistLocalArtifactsUseCase(
            workspace_dir=self.workspace_dir,
            cleanup_temporary_files=PROPERTY_MEDIA_DELETE_TEMPORARY_FILES,
            database_locator=self.database_locator,
        )
        self._social_publisher = (
            _build_default_social_property_publisher() if social_active else None
        )
        self._publish = PublishReelUseCase(
            local_publisher=_LocalArtifactsPublisher(self._persist),
            workspace_dir=self.workspace_dir,
            social_publisher=self._social_publisher,
            database_locator=self.database_locator,
        )

    def handle(self, job: Job) -> object | None:
        media_job = build_property_media_job(job)
        with DatabaseUnitOfWork(self.database_locator, base_dir=self.workspace_dir) as uow:
            context = self._ingest.execute(media_job, uow=uow)
            if context.is_noop:
                return None
            if not context.requires_render:
                return self._publish.execute_existing(context, uow=uow)
            prepared = self._prepare.execute(context, uow=uow)
            try:
                rendered = self._renderer.render_media(context, prepared)
                published = self._publish.execute(context, rendered, uow=uow)
            finally:
                self._prepare.cleanup(context, prepared)
            return published


class _LocalArtifactsPublisher:
    """Inline adapter binding `PersistLocalArtifactsUseCase` to the
    `PublishReelUseCase` `local_publisher` contract.

    Equivalent to the `FileSystemMediaPublisher` adapter in
    `application/bootstrap/pipeline_adapters.py` (which feature 16
    deletes), but parameterized by the same UoW the orchestrator opens.
    """
    def __init__(self, persist: PersistLocalArtifactsUseCase) -> None:
        self._persist = persist
        # The `PublishReelUseCase` only invokes `publish_media` and
        # `publish_existing_media`; bind both to the persist use case.

    def publish_media(self, context, rendered_media):
        return self._persist.execute(context, rendered_media)

    def publish_existing_media(self, context):
        return self._persist.execute_existing(context)


def _build_default_social_property_publisher():
    # Same body as `application.bootstrap.runtime.build_default_social_property_publisher`,
    # inlined here so feature 16 can retire `application/bootstrap/runtime.py`'s
    # bridge construction without breaking imports.
    ...  # imports moved from `application/bootstrap/runtime.py:51-68`
```

### Notas de diseño

- **Path único: el lugar canónico para esto es
  `modules/reels/application/orchestrator.py`** (donde ya vive
  `ReelPipeline`). NO crear `modules/reels/application/reel_pipeline.py`
  ni similar. La acceptance dice "ReelPipeline en
  modules/reels/application/", el archivo `orchestrator.py` lo cumple.
- `_LocalArtifactsPublisher` se define como inner-helper en el mismo
  archivo (≈10 LoC). Alternativa: usar `PersistLocalArtifactsUseCase`
  directamente como `local_publisher` (cambia la firma del use case
  para añadir `publish_media`/`publish_existing_media` aliases). **Mi
  preferencia: helper inline** — mantiene `PersistLocalArtifactsUseCase`
  con el contrato `execute()`/`execute_existing()` puro y no expande la
  superficie pública del use case.
- `_build_default_social_property_publisher` se inlines o se importa
  lazy de `application.bootstrap.runtime`. Inline es más limpio (corta
  la dependencia con `application/`); lazy mantiene el archivo más
  corto. **Mi preferencia: lazy import dentro de `__init__`** (es 1
  línea), y se borra el símbolo en feature 18 cuando muere
  `application/`.
- `PersistLocalArtifactsUseCase` y `PublishReelUseCase` reciben
  `workspace_dir` y `database_locator` constructor; el `uow` se inyecta
  en `execute()`. Eso es la API ya estabilizada por features 12-13. Sin
  cambios en use cases.
- Los logs de top-level pipeline (`PROPERTY MEDIA PIPELINE`, `PROPERTY
  INGESTION`, etc.) que `PropertyMediaPipeline.run_job` emitía
  (`media_pipeline.py:32-117`) **se preservan** de forma simplificada en
  `ReelPipeline.handle` con `LoggedProcess` envoltorios. Útiles para
  debugging y respeta el patrón consolidado en Phase 2. Opcionalmente
  se pueden omitir; el comportamiento funcional no cambia.
- **`PropertyMediaJobRunner` (file-lock + logging) NO se preserva**
  por defecto. El `exclusive_file_lock(lock_path)` que aplicaba
  por-`(site_id, property_id)` ya no es necesario en el nuevo modelo:
  el dispatcher hace `claim_next_ready_job` que es atómico SQL y los
  jobs `superseded` ya no se reclaman. **Si el leader necesita
  preservarlo**, se puede invocar dentro de `ReelPipeline.handle` con
  `core.locking.exclusive_file_lock` antes del `with DatabaseUnitOfWork`.
  Mi default: omitir el lock (la cola SQL ya da exclusión por
  job_id; jobs concurrentes para el mismo property_id sólo aparecen si
  alguien encola dos antes de procesar el primero, y `supersede_queued_jobs`
  en el ingest router ya impide eso).

### LoC esperado

- `orchestrator.py`: 62 → ~150-180 LoC. Aún cómodo bajo 500.

---

## 4. UoW compartido

### Las 4 firmas confirman soporte de `uow=`

Verificado en §0.6:

| Use case | Firma `execute(...)` | `uow=None` permitido |
|----------|---------------------|---------------------|
| `IngestPropertyIntoReelUseCase` | `(self, job, *, uow=None)` | sí, abre uno propio si `None` |
| `PrepareReelAssetsUseCase` | `(self, context, *, uow=None)` | sí |
| `PersistLocalArtifactsUseCase` | `(self, context, rendered, *, uow=None)` | sí |
| `PublishReelUseCase.execute` | `(self, context, rendered, *, uow=None)` | sí |
| `PublishReelUseCase.execute_existing` | `(self, context, *, uow=None)` | sí |

Tests existentes (`tests/integration/reels/test_*_flow.py`) ya
ejercitan los 4 con `uow=uow` desde un único `DatabaseUnitOfWork` en
varios escenarios (ver `test_publish_reel_flow.py:171,179,207`).

### Compartir el UoW

El esbozo de `ReelPipeline.handle` en §3 abre un único UoW:

```python
with DatabaseUnitOfWork(self.database_locator, base_dir=self.workspace_dir) as uow:
    context = self._ingest.execute(media_job, uow=uow)
    ...
    prepared = self._prepare.execute(context, uow=uow)
    ...
    published = self._publish.execute(context, rendered, uow=uow)
```

**Esto resuelve el doble UoW R1 documentado en
`explore_feature_14:6 R1`**: pre-feature-16, un job `reel_publish`
abría 4 UoWs (uno por adapter); post-feature-16, abre 1 sólo UoW
compartido y todas las escrituras (catalog.upsert + reels.save +
property_images + media_revisions + outbox_events) commit/rollback
juntas.

**Trade-off**: la transacción es más larga. Eso es estrictamente lo
que el dominio quiere — un job de reel_publish es atómico desde el
punto de vista de negocio. Si falla el `publish` paso, `prepare` no
debe dejar `properties.image_folder` actualizado. Hoy con UoWs
separados eso pasa silenciosamente.

**Render no toca DB** (verificado en `explore_feature_14:3`):
`DefaultMediaRenderer.render_media(context, prepared_assets)` es compute
puro + filesystem. No necesita pasarse el UoW.

### `requires_external_publish` y `is_noop`

`ReelPipeline.handle` decide entre 3 caminos según los flags que
`IngestPropertyIntoReelUseCase` deja en `PropertyContext`:

- `is_noop=True` → return early sin tocar prepare/render/publish.
- `requires_render=False` → invoca `_publish.execute_existing(context,
  uow=uow)` (publica artefacto pre-existente).
- otherwise → ejecuta los 4 pasos completos.

Esto reproduce la lógica de `PropertyMediaPipeline.run_job:63-118` con
los 3 caminos. `LoggedProcess` blocks opcionales (ver §3 nota).

---

## 5. Tests

### Tests existentes que tocan worker

| Archivo | LoC | Tocados por feature 16 |
|---------|-----|-----------------------|
| `tests/integration/test_worker_runtime.py` | 149 | NO. Ambos tests usan handlers mock (`lambda` / `fail_retryable`). El cuerpo del dispatcher (`claim → handler → ack`) ya está cubierto. **Sin cambios**. |
| `tests/integration/test_http_transport.py` | varies | Verificar que `dispatcher_accepting_jobs` sigue inyectado vía closure (no via `_NoopDispatcher`). Esperado: sin cambios. |
| `tests/integration/apps_api/test_health_router.py` | varies | Idem. Esperado: sin cambios. |
| `tests/integration/reels/test_*_flow.py` (4 archivos) | varies | Cubren los 4 use cases individualmente. **Sin cambios** — feature 16 solo cambia el orquestador, no los use cases. |

### Test nuevo requerido por la acceptance

`tests/integration/delivery/test_worker_dispatcher_flow.py`. **El
directorio `tests/integration/delivery/` no existe**, hay que crearlo
con `__init__.py` vacío.

### Esqueleto del test nuevo

```python
"""End-to-end dispatcher flow test for feature 16.

Exercises claim → handler (real) → outbox on a temporary Postgres
schema. Compared with `tests/integration/test_worker_runtime.py` which
uses handler mocks, this test wires the **real** `ReelPipeline.handle`
(and optionally `RenderScriptedVideoUseCase.execute`) and asserts the
job pipeline produces the right side effects:

  * `delivery.jobs.status` flips to 'completed' (or 'queued' on retry).
  * `delivery.webhook_events.status` flips to 'completed'.
  * `media_revisions` row appended with the right artifact_kind +
    workflow_state.
  * `outbox_events` row appended with `event_type='publish_completed'` (or
    'publish_skipped') and `status='completed'`.

The render step is faked: the test stubs `DefaultMediaRenderer.render_media`
to bypass ffmpeg (uses pre-built `RenderedMediaArtifact` pointing at
synthetic files). The social publisher is faked similarly to
`tests/integration/reels/test_publish_reel_flow.py:_FakePropertyPublisher`.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock
from uuid import uuid4

from apps.worker.runtime import JobDispatcher, WorkerSettings, build_default_dispatcher
from modules.delivery.domain import JobEnqueueRequest
from modules.reels.application.orchestrator import ReelPipeline
from settings import DATABASE_URL
from shared.db import DatabaseUnitOfWork
from tests.support.postgres import (
    seed_provider_connection,
    seed_tenant,
    temporary_postgres_schema,
    temporary_workspace,
)


class WorkerDispatcherFlowTests(unittest.TestCase):
    def test_reel_publish_handler_completes_job_and_writes_outbox(self) -> None:
        with temporary_workspace() as workspace_dir:
            with temporary_postgres_schema(DATABASE_URL) as database:
                tenant = seed_tenant(database.url, site_id="ckp.ie")
                seed_provider_connection(
                    database.url, agency_id=tenant.agency_id,
                    provider="gohighlevel", external_id="loc-test",
                )
                job_id, event_id = _enqueue_reel_publish_job(
                    database.url, tenant=tenant, property_id=137,
                )

                # Stub renderer + social publisher.
                with mock.patch(
                    "modules.reels.application.orchestrator.DefaultMediaRenderer.render_media",
                    side_effect=_fake_render,
                ), mock.patch(
                    "modules.reels.application.orchestrator._build_default_social_property_publisher",
                    return_value=_FakePropertyPublisher(),
                ):
                    dispatcher = JobDispatcher(
                        settings=WorkerSettings(
                            base_dir=workspace_dir,
                            database_locator=database.url,
                        )
                    )
                    pipeline = ReelPipeline(
                        workspace_dir=workspace_dir,
                        database_locator=database.url,
                    )
                    dispatcher.register_handler("reel_publish", pipeline.handle)

                    processed = dispatcher._process_next_job("worker-test")

                self.assertTrue(processed)
                with DatabaseUnitOfWork(database.url, workspace_dir) as uow:
                    job = uow.delivery.jobs.get_job(job_id)
                    event = uow.delivery.webhook_events.get_event(event_id)
                self.assertEqual(job.status, "completed")
                self.assertEqual(event.status, "completed")

                # Outbox row written.
                from sqlalchemy import create_engine, text
                engine = create_engine(database.url, future=True)
                try:
                    with engine.connect() as connection:
                        outbox_rows = connection.execute(text(
                            "SELECT event_type, status FROM outbox_events "
                            "WHERE source_property_id = :pid"
                        ), {"pid": 137}).all()
                    self.assertEqual(len(outbox_rows), 1)
                    self.assertIn(outbox_rows[0].event_type,
                                  {"publish_completed", "publish_skipped"})
                finally:
                    engine.dispose()

    def test_scripted_render_handler_processes_job(self) -> None:
        # Análogo, registra el handler `scripted_render` con un payload
        # mínimo válido y stub `ScriptedVideoRenderService.render_from_manifest`.
        ...
```

Tests requeridos: **2 mínimo** (uno por kind). Opcionalmente un 3o
de retry/failure. ~250-350 LoC esperado total.

### Notas sobre el test

- El renderer se stubbea vía `mock.patch` para evitar ffmpeg/disk
  costoso. Patrón ya usado en
  `tests/integration/reels/test_publish_reel_flow.py:200,234-242`.
- El social publisher se stubbea vía monkeypatch del helper
  `_build_default_social_property_publisher` que se inlinea en
  `orchestrator.py` (ver §3). Si el helper se importa lazy de
  `application.bootstrap.runtime`, el patch apunta ahí.
- `seed_provider_connection` ya disponible en `tests/support/postgres.py:226-269`.
- `seed_tenant` ya disponible (`:155-223`).
- `_enqueue_reel_publish_job` se puede inlinear o reutilizar el
  `_enqueue_job` de `tests/integration/test_worker_runtime.py:97-144`
  (patrón idéntico).

---

## 6. Riesgos / acoplamientos

### R1 — Doble UoW finalmente eliminado

Documentado en `explore_feature_14:6 R1`. Pre-16: 4 UoWs por job
`reel_publish`. Post-16: 1 UoW compartido. **Beneficio neto del cambio**.
Trade-off: transacción más larga, pero atómica.

### R2 — Ningún uso del `_NoopDispatcher` fuera de `app_factory.py`

Verificado con `Grep "_NoopDispatcher"` en `tests/`: 0 hits. La clase es
privada del archivo. Borrarla no rompe imports externos.

### R3 — `application/pipeline/*` y `application/bootstrap/pipeline_adapters.py`

Tras feature 16 quedan **sin callers**:

- `media_pipeline.py`, `interfaces.py`, `job_runner.py`,
  `pipeline_adapters.py`. `Grep` post-feature-16 esperado: 0 hits no-pyc.
- Decisión: borrar en feature 16 (alineado con §2 phase_2_operating_rules).

**Verificar antes de borrar**: `Grep "PropertyMediaPipeline|MediaRenderer|MediaPublisher|PropertyInfoService|MediaPreparationService|PhotoSelectionEngine|JobDispatcher|PropertyMediaJobRunner|CompositeMediaPublisher|FileSystemMediaPublisher|DefaultMediaPreparationService|DefaultPropertyInfoService" -t py` en `apps/`, `modules/`, `shared/`, `tests/` que NO sean
imports de los archivos a borrar.

### R4 — `application/bootstrap/runtime.py` y `__init__.py`

Tras feature 16 quedan parcialmente usados:

- En uso: `build_runtime_unit_of_work_factory`,
  `build_default_social_property_publisher`,
  `build_default_unit_of_work_factory` (este último: revisar callers
  con `Grep`).
- Huérfanas: `build_default_property_media_pipeline`,
  `build_default_job_handler`, `build_default_job_dispatcher`.

Decisión: limpiar funciones huérfanas + sus imports asociados, mantener
el archivo más esbelto (~80-100 LoC en lugar de 187). **Aplicar el
mismo cambio a ambos archivos** byte-iguales (patrón pre-existente).

### R5 — `RenderScriptedVideoUseCase` duplicado

Documentado en §0.C. La copia en
`modules/reels/application/use_cases/__init__.py:22-51` es huérfana
(nadie la importa). Decisión: borrarla. Mantener solo la copia
canónica en `render_scripted_video.py` y el re-export del `__init__.py`.

### R6 — `application/scripted_render/service.py` (677 LoC) sobrevive

`RenderScriptedVideoUseCase.execute` sigue lazy-importando
`ScriptedVideoRenderService`. **Feature 16 NO toca esto** — es el
camino legacy de `scripted_render`, con su propio `unit_of_work_factory`
y vida propia. Su retirada (mover el contenido a
`modules/rendering/application/`) queda para Phase 3 o features 17/18.

Si el leader prefiere consolidarlo aquí, el alcance de feature 16
crece notablemente (~677 LoC a mover). **Mi default: out-of-scope**.

### R7 — ffmpeg en tests integration

El test nuevo `test_worker_dispatcher_flow.py` debe stubbear el
renderer (`DefaultMediaRenderer.render_media`) para no requerir ffmpeg.
Patrón idéntico a `tests/integration/reels/test_publish_reel_flow.py`.
Sin esto, los tests integration en CI requerirían ffmpeg instalado.

### R8 — Logging top-level del pipeline

`PropertyMediaPipeline.run_job:32-117` emite `LoggedProcess` blocks por
fase. El nuevo `ReelPipeline.handle` puede preservarlos (recomendado
para debugging) o omitirlos. Decisión recomendada: preservar
simplificadamente (3-4 `LoggedProcess` blocks: pipeline-level +
ingestion + render + publish).

### R9 — `core/locking.exclusive_file_lock` lock-file por property

`PropertyMediaJobRunner.run` usaba un lock file `.lock` por
`(site_id, property_id)` para evitar dos workers procesando el mismo
property concurrente. Tras feature 16:

- La cola SQL atómica (`claim_next_ready_job` con `FOR UPDATE SKIP
  LOCKED`) garantiza que un job no se procesa dos veces.
- `supersede_queued_jobs` en el ingest router (feature 4) ya impide
  que dos jobs queden ready al mismo tiempo para el mismo property.

**Decisión recomendada**: omitir el file lock. Si el leader prefiere
defensa en profundidad, mantenerlo dentro de `ReelPipeline.handle` con
`with exclusive_file_lock(lock_path):` envolviendo el `with DatabaseUnitOfWork`.

### R10 — `DefaultMediaRenderer.__init__(workspace_dir)` no recibe DB

Verificado en `explore_feature_14:3` (renderer no toca DB). La
instancia por job es barata; alternativa: instanciarla una vez en
`ReelPipeline.__init__` (mi recomendación en §3).

### R11 — Tests existentes en `tests/integration/test_http_transport.py` y `apps_api/test_health_router.py`

Documentado en §2. Si se elige (D2), pasan sin cambios. Si se elige
(D1), 9 hits a adaptar. **Mi recomendación: (D2)**.

### R12 — Settings imports en `orchestrator.py`

El nuevo `ReelPipeline.__init__` necesita 5 settings (
`SOCIAL_PUBLISHING_ENABLED`, `SOCIAL_PUBLISHING_LOCAL_ONLY`,
`SOCIAL_PUBLISHING_PROPERTY_URL_TEMPLATE`,
`SOCIAL_PUBLISHING_PROPERTY_URL_TRACKING_PARAMS`,
`PROPERTY_MEDIA_DELETE_TEMPORARY_FILES`,
`PROPERTY_MEDIA_DELETE_SELECTED_PHOTOS`, `DATABASE_URL`).

`docs/architecture.md` y `docs/conventions.md` permiten esto
(`from settings import ...` es estándar). Sin riesgo.

### R13 — `application/types.PropertyMediaJob`, `SocialPublishContext`, `PropertyContext`

Aún viven en `application/types.py`. `ReelPipeline` los importa para
construir `PropertyMediaJob` desde `Job` (fonction
`build_property_media_job`). Feature 18 los retira (deja Phase 2
limpia); feature 16 los preserva tal cual. Sin cambio.

### R14 — Test `test_dispatcher_processes_ready_job_and_updates_webhook_event` (existente)

`tests/integration/test_worker_runtime.py:20` espera que el handler
mock devuelva `{"ok": True}` y que `event.status` quede `completed`.
Esto sigue verde **siempre** que se preserve la lógica del dispatcher
en `_process_next_job:191-199`: `final_event_status = "noop" if result
is None else "completed"`. **No tocar esa lógica** — la decide solo el
return value del handler.

`ReelPipeline.handle` real devuelve `None` (cuando `is_noop=True`) o
un `PublishedMediaArtifact` (otherwise). Eso casa con el contrato
`completed` / `noop`.

### R15 — `init.sh` step 4 WARN

Patrón pre-existente: `init.sh` reporta WARN si "≥ N archivos
modificados en directorios legacy en últimas 24h". Feature 16 modifica
varios bajo `application/`. **Esperado y aceptable** (alineado con
features 10-15).

---

## 7. Plan de implementación recomendado

### Archivos a crear

1. **`tests/integration/delivery/__init__.py`** (vacío, package marker).
2. **`tests/integration/delivery/test_worker_dispatcher_flow.py`**
   (~250-350 LoC). Mínimo 2 tests: uno por kind (`reel_publish` y
   `scripted_render`). Opcional un 3o para retry.

### Archivos a modificar

1. **`modules/reels/application/orchestrator.py`** (62 → ~150-180 LoC).
   - Reescribir `ReelPipeline.__init__` para construir los 4 use cases.
   - Reescribir `ReelPipeline.handle` para componerlos con UoW
     compartido.
   - Inlinear `_LocalArtifactsPublisher` helper.
   - Inlinear o lazy-importar
     `_build_default_social_property_publisher`.
   - Preservar `build_property_media_job` (`:34-55`) — sigue necesario
     para traducir `Job` → `PropertyMediaJob`.
2. **`apps/api/app_factory.py`** (428 → ~395 LoC).
   - Borrar `class _NoopDispatcher` (`:105-134`).
   - Sustituir rama default de `dispatcher_accepting_jobs is None` por
     `dispatcher_state = lambda: True` + lifespan no-op.
   - Limpiar docstrings (módulo + kwarg + comentario `:206-208`).
3. **`application/bootstrap/runtime.py`** y
   **`application/bootstrap/__init__.py`** (byte-iguales, 187 → ~80-100
   LoC).
   - Eliminar `build_default_property_media_pipeline` (`:86-128`).
   - Eliminar `build_default_job_handler` (`:131-150`).
   - Eliminar `build_default_job_dispatcher` (`:153-175`).
   - Eliminar imports asociados (`pipeline_adapters`,
     `DatabaseJobDispatcher`, `PropertyMediaPipeline`,
     `PropertyMediaJobRunner`, `DefaultMediaRenderer`,
     `PropertyMediaJob`, los 5 settings sólo usadas por las funciones
     borradas).
   - Mantener: `build_default_social_property_publisher`,
     `build_default_unit_of_work_factory`,
     `build_runtime_unit_of_work_factory`. Imports asociados.
   - Aplicar **idéntico** en ambos archivos (preservar byte-igualdad).
4. **`modules/reels/application/use_cases/__init__.py`** (60 → ~25 LoC).
   - Borrar la copia duplicada de `class RenderScriptedVideoUseCase`
     (`:22-51`).
   - Mantener los 4 imports + el `from .render_scripted_video import
     RenderScriptedVideoUseCase` + `__all__`.

### Archivos a borrar

1. **`application/pipeline/media_pipeline.py`** (133 LoC).
2. **`application/pipeline/interfaces.py`** (112 LoC).
3. **`application/pipeline/job_runner.py`** (70 LoC).
4. **`application/bootstrap/pipeline_adapters.py`** (237 LoC).

### Archivos NO modificados

- `apps/worker/runtime.py`, `apps/worker/main.py` (ya correctos).
- Los 5 use cases bajo `modules/reels/application/use_cases/` (sin
  cambios).
- `modules/rendering/application/frame_composition.py` (renderer puro,
  sin cambios).
- `modules/reels/application/use_cases/render_scripted_video.py` (sin
  cambios).
- `application/pipeline/content_generation.py` (sigue usado).
- `application/scripted_render/service.py` (sigue usado).
- `application/types.py` (feature 18 lo retira).
- `application/persistence.py` (feature 18 lo retira).
- `application/dispatch/database_dispatcher.py` (verificar callers; si
  huérfano tras feature 16, considerar borrarlo).
- Tests existentes (sin cambios; tras feature 16 las 453 verdes
  baseline siguen verdes + ~2-3 nuevas).

### Orden sugerido

1. Reescribir `modules/reels/application/orchestrator.py:ReelPipeline`
   con la nueva composición de use cases.
2. Crear `tests/integration/delivery/__init__.py` y
   `tests/integration/delivery/test_worker_dispatcher_flow.py`. Hacer
   pasar el primer test.
3. Borrar `_NoopDispatcher` de `apps/api/app_factory.py`.
4. Verificar `pytest -q tests/integration/test_http_transport.py` y
   `tests/integration/apps_api/test_health_router.py` siguen verdes.
5. Limpiar `application/bootstrap/{runtime,__init__}.py`.
6. Borrar `application/pipeline/{media_pipeline,interfaces,job_runner}.py`.
7. Borrar `application/bootstrap/pipeline_adapters.py`.
8. Limpiar duplicado de `RenderScriptedVideoUseCase` en
   `modules/reels/application/use_cases/__init__.py`.
9. Correr `pytest -q` completo. Esperado: **455-456 verdes** (453
   baseline + 2-3 nuevos).
10. `python -m apps.api --check` y `python -m apps.worker --check` →
    exit 0.

### LoC esperado

| Archivo | Pre | Post |
|---------|-----|------|
| `modules/reels/application/orchestrator.py` | 62 | ~170 |
| `apps/api/app_factory.py` | 428 | ~395 |
| `application/bootstrap/runtime.py` | 187 | ~95 |
| `application/bootstrap/__init__.py` | 187 | ~95 |
| `modules/reels/application/use_cases/__init__.py` | 60 | ~25 |
| `application/pipeline/media_pipeline.py` | 133 | **0 (borrado)** |
| `application/pipeline/interfaces.py` | 112 | **0 (borrado)** |
| `application/pipeline/job_runner.py` | 70 | **0 (borrado)** |
| `application/bootstrap/pipeline_adapters.py` | 237 | **0 (borrado)** |
| `tests/integration/delivery/__init__.py` | — | 0 |
| `tests/integration/delivery/test_worker_dispatcher_flow.py` | — | ~300 |
| **Total delta** | | **~−750 LoC netos** |

Reducción neta del repo: **−750 LoC** post-feature-16. Combinada con
features 10-15: una de las mayores reducciones de Phase 2 hasta este
punto.

---

## 8. Discrepancias detectadas

### D1 — `RenderScriptedVideoUseCase` duplicado en 2 archivos

Documentado en §0.C / §6 R5. La copia en
`modules/reels/application/use_cases/__init__.py:22-51` es huérfana.
**Recomendación**: borrarla en feature 16 como cleanup. El archivo
canónico es `render_scripted_video.py` (importado por
`apps/worker/runtime.py`).

### D2 — `ReelPipeline` ya existe pero no hace lo que el acceptance dice

Documentado en §0.A / §3. Hoy `ReelPipeline.handle` delega en
`build_default_job_handler` legacy. **Feature 16 reescribe el cuerpo**
sin cambiar el path/clase. Los call sites externos
(`apps/worker/runtime.py:17,263,272-274`) no cambian.

### D3 — "Bridges legacy en `apps/worker/` borrados" — interpretación

Documentado en §0.B. **No hay archivos físicos a borrar bajo
`apps/worker/`**. La acceptance se interpreta como (B1) "el bridge
indirecto via `application/bootstrap/runtime.py:build_default_job_handler`
desaparece" + (B2) "los archivos legacy huérfanos tras (B1) se borran".

### D4 — `_NoopDispatcher` reemplazo: borrar campo o hardcodear

Documentado en §0.D / §2. Recomendación: hardcodear
`dispatcher_state = lambda: True` (D2) en lugar de borrar el campo
`dispatcher_accepting_jobs` del contrato HTTP (D1). El leader puede
preferir D1 si quiere limpiar el contrato HTTP.

### D5 — `application/pipeline/content_generation.py` sigue vivo

Documentado en §0.E. Lo consume `IngestPropertyIntoReelUseCase` y
hasta features 17/18 no se mueve. **No es discrepancia con el
acceptance** (literal: borrar `_NoopDispatcher` y bridges; no menciona
`content_generation.py`).

### D6 — `application/scripted_render/service.py` (677 LoC) sigue vivo

Documentado en §6 R6. La cadena de scripted_render queda intacta.
Feature 16 no la consolida. **Si el leader prefiere consolidarla**, el
alcance crece notablemente (mover el servicio a `modules/rendering/
application/use_cases/render_scripted_video.py` con cuerpo real, no
lazy import). **Mi default: out-of-scope**.

### D7 — `PropertyMediaJobRunner` (file lock) eliminado sin fallback

Documentado en §6 R9. La cola SQL atómica + `supersede_queued_jobs`
hacen el lock redundante. **Si el leader quiere defensa en profundidad**,
preservarlo dentro de `ReelPipeline.handle` envolviendo el `with
DatabaseUnitOfWork`. Mi default: omitir.

### D8 — Tests existentes en `apps_api/test_health_router.py` y `test_http_transport.py`

Documentado en §2 / §6 R11. Si se elige D2 (recomendación), no se
adaptan. Si se elige D1, 9 hits a adaptar.

### D9 — `DatabaseJobDispatcher` (en `application/dispatch/`)

`grep "DatabaseJobDispatcher"` en repo: usado por
`build_default_job_dispatcher` en `application/bootstrap/runtime.py:160`.
Si se borra `build_default_job_dispatcher`, queda potencialmente
huérfano. **Verificar antes de borrarlo**: si `application/dispatch/`
no tiene otros callers tras feature 16, considerar borrar el directorio
completo. Out-of-scope si el leader prefiere defer a feature 18.

### D10 — `application/persistence.py` (UnitOfWork Protocol)

Lo consume `application/bootstrap/pipeline_adapters.py:26`. Tras borrar
`pipeline_adapters.py`, verificar otros callers. Probable que feature
17 o 18 lo barra al mover/borrar `repositories/`.

### D11 — Test count baseline

Pre-16: **453 verdes** (post-15 según `impl_15:222-243`).
Post-16: **455-456 verdes** esperado. Esperado ≥ 425. **Cumplido**.

### D12 — Naming de la clase `ReelPipeline`

El acceptance literal dice "ReelPipeline en
modules/reels/application/". El nombre actual encaja. No renombrar.

### D13 — `_LocalArtifactsPublisher` adapter inline

Documentado en §3. Se inlinea como helper de ~10 LoC en
`orchestrator.py`. Alternativa: añadir aliases `publish_media` /
`publish_existing_media` al `PersistLocalArtifactsUseCase` para que
implemente el contrato directamente. **Mi default: helper inline**
(menos invasivo).

### D14 — Logs `LoggedProcess` y observabilidad

Documentado en §3 / §6 R8. El nuevo orchestrator preserva los
`LoggedProcess` blocks simplificadamente (recomendado para debugging).
Aceptable también omitirlos.

---

**Fin del informe.**
