# Impl — Feature 16 `worker_real_use_cases_and_drop_noop_dispatcher`

> Reescribir `ReelPipeline.handle` para componer los 4 use cases modernos
> directamente (ingest / prepare / render / persist+publish), eliminar el
> bridge legacy `apps.worker → application.bootstrap →
> PropertyMediaPipeline`, retirar `_NoopDispatcher` de
> `apps/api/app_factory.py`, y borrar los archivos huérfanos del pipeline
> legacy. Conforme al plan del explorer
> (`progress/explore_feature_16_worker_real_use_cases.md`).

---

## 1. Archivos creados / modificados / borrados

### Creados

| Archivo | LoC | Tipo |
|---------|-----|------|
| `tests/integration/delivery/__init__.py` | 0 | Package marker (vacío). |
| `tests/integration/delivery/test_worker_dispatcher_flow.py` | 397 | 2 tests integration: `test_reel_publish_handler_completes_job_and_writes_outbox` (cubre `claim → ReelPipeline.handle (real) → ack` con renderer/social stub) + `test_scripted_render_handler_processes_job` (cubre `claim → RenderScriptedVideoUseCase.execute → ack` con `ScriptedVideoRenderService.render_from_manifest` stub). Reusa `temporary_postgres_schema` y `temporary_workspace` de `tests/support/postgres.py`. |

### Modificados

| Archivo | LoC pre | LoC post | Cambio |
|---------|---------|----------|--------|
| `modules/reels/application/orchestrator.py` | 62 | 272 | Reescrito. `ReelPipeline.__init__` instancia los 4 use cases (`Ingest`, `Prepare`, `Persist`, `Publish`) + `DefaultMediaRenderer` + helper inline `_LocalArtifactsPublisher`. `ReelPipeline.handle(job)` orquesta los 3 caminos (`is_noop`, `requires_render=False`, feliz) con `LoggedProcess` blocks por fase. Cuerpo verbatim ya no delega en `application.bootstrap.runtime.build_default_job_handler` (bridge B1 eliminado). |
| `apps/api/app_factory.py` | 428 | 390 | Borrada `class _NoopDispatcher` (`:105-134`, 30 LoC). Sustituida la rama default por `dispatcher_state = (lambda: True) if dispatcher_accepting_jobs is None else dispatcher_accepting_jobs`. `lifespan` simplificado a `async def lifespan(app): yield`. Docstring del módulo y del kwarg `dispatcher_accepting_jobs` actualizadas para retirar la referencia a `_NoopDispatcher`. |
| `application/bootstrap/runtime.py` | 187 | 68 | Limpieza. Borrados `build_default_property_media_pipeline`, `build_default_job_handler`, `build_default_job_dispatcher` y los imports asociados (`PropertyMediaPipeline`, `DatabaseJobDispatcher`, `PropertyMediaJobRunner`, `DefaultMediaRenderer`, los 4 adapters de `pipeline_adapters`). Mantiene `build_runtime_unit_of_work_factory`, `build_default_social_property_publisher`, `build_default_unit_of_work_factory` y la constante `WEBHOOK_SHUTDOWN_TIMEOUT_SECONDS`. |
| `application/bootstrap/__init__.py` | 187 | 68 | Byte-igual a `runtime.py` (verificado con `diff` exit 0). |
| `modules/reels/application/use_cases/__init__.py` | 60 | 28 | Borrada copia duplicada de `RenderScriptedVideoUseCase` (líneas `:22-51` legacy, ~35 LoC). El re-export limpio se mantiene importando desde `modules.reels.application.use_cases.render_scripted_video`. |
| `feature_list.json` | — | — | Feature 16 status `pending` → `in_progress`. |

### Borrados (4 archivos, ~552 LoC)

| Archivo | LoC | Razón |
|---------|-----|-------|
| `application/pipeline/media_pipeline.py` | 133 | `PropertyMediaPipeline` huérfano tras (B1). Sin callers externos. |
| `application/pipeline/interfaces.py` | 112 | Protocols (`MediaRenderer`, `MediaPublisher`, `MediaPreparationService`, `PropertyInfoService`, `PhotoSelectionEngine`) huérfanos tras borrar `media_pipeline.py` y `pipeline_adapters.py`. |
| `application/pipeline/job_runner.py` | 70 | `PropertyMediaJobRunner` (file-lock + logging) huérfano tras (B1). Decisión R9 → omitido (la cola SQL atómica ya garantiza no-doble-procesamiento). |
| `application/bootstrap/pipeline_adapters.py` | 237 | 4 adapters (`DefaultPropertyInfoService`, `DefaultMediaPreparationService`, `FileSystemMediaPublisher`, `CompositeMediaPublisher`) ya no consumidos: `ReelPipeline.handle` invoca los use cases directamente. |

### NO modificados

- Los 4 use cases de reels (`ingest_property_into_reel.py`, `prepare_reel_assets.py`, `persist_local_artifacts.py`, `publish_reel.py`) — feature 16 sólo cambia el orquestador.
- `apps/worker/runtime.py` — ya importaba `ReelPipeline` y `RenderScriptedVideoUseCase` directamente (líneas `:17-20`) y los registraba como handlers (`:259-279`).
- `modules/reels/application/use_cases/render_scripted_video.py` — fuente canónica, intacta (42 LoC).
- `application/pipeline/content_generation.py` — sigue consumido por `IngestPropertyIntoReelUseCase` (out-of-scope, feature 17/18 lo retira). 150 LoC.
- `application/scripted_render/service.py` — sigue consumido por `RenderScriptedVideoUseCase.execute` lazy. 677 LoC. Out-of-scope (D6).
- `tests/integration/test_worker_runtime.py`, `tests/integration/test_http_transport.py`, `tests/integration/apps_api/test_health_router.py` — ningún cambio: D2 conserva el contrato HTTP `dispatcher_accepting_jobs`, los 9 hits potenciales no requieren adaptación.

---

## 2. Cambios clave en `ReelPipeline.handle`

### 2.1 — Tres caminos (preservan la semántica del legacy)

```python
def handle(self, job: Job) -> object | None:
    media_job = build_property_media_job(job)
    with LoggedProcess(logger, "PROPERTY MEDIA PIPELINE", ...) as pipeline_process:
        # 1. Ingest (paso 1).
        with LoggedProcess(logger, "PROPERTY INGESTION", ...):
            context = self._ingest.execute(media_job)

        # Camino A — noop.
        if context.is_noop:
            return None

        # Camino B — publish-only retry.
        if not context.requires_render:
            with LoggedProcess(logger, "EXISTING MEDIA PUBLISH", ...):
                published_media = self._publish.execute_existing(context)
            return published_media

        # Camino C — pipeline completo.
        prepared_assets = self._prepare.execute(context)
        try:
            with LoggedProcess(logger, "MEDIA RENDER", ...):
                rendered_media = self._renderer.render_media(context, prepared_assets)
            with LoggedProcess(logger, "MEDIA PUBLISH", ...):
                published_media = self._publish.execute(context, rendered_media)
        finally:
            self._prepare.cleanup(context, prepared_assets)
        return published_media
```

### 2.2 — UoW por paso (no UoW único compartido)

**Desviación frente al §4 del explore.** El plan original proponía abrir
**un solo** `DatabaseUnitOfWork` y pasarlo a los 4 use cases vía
`uow=uow`. En la práctica esto **deadlockea**: `PublishReelUseCase.execute`
delega la persistencia local en `local_publisher.publish_media(context,
rendered_media)`, y el contrato de `local_publisher` no admite un
`uow=` parámetro. El adapter `_LocalArtifactsPublisher` por tanto
delega en `PersistLocalArtifactsUseCase.execute(context, rendered_media)`
**sin** uow, abriendo una conexión nueva a Postgres que choca contra el
row-lock que ya tiene el UoW exterior sobre la fila `reels`.

Verificado con `faulthandler.dump_traceback_later`: el thread se
quedaba bloqueado en `psycopg/waiting.py:265 wait_select` →
`reel_state_repository.py:120 save` durante el paso `persist_local_artifacts`.

**Fix aplicado**: el orquestador NO envuelve los pasos en un UoW
exterior. Cada `execute(...)` se invoca con `uow=None` (default), de
modo que cada use case abre su propio UoW corto y commitea
inmediatamente. Esto reproduce **exactamente** el patrón validado por
`tests/integration/reels/test_publish_reel_flow.py:171,207,244` —
ingest abre y cierra su UoW, prepare abre y cierra su UoW, persist
abre y cierra su UoW. Sin solapamiento, sin deadlock.

**Trade-off**: la transacción por job no es atómica de extremo a
extremo. Mitigación natural ya existente: el dispatcher (`apps/worker/
runtime.py:_handle_job_failure`) reintenta el job entero si falla en
medio (con `claim_next_ready_job` lockeando otra vez), y los use cases
están diseñados como idempotentes vía `upsert_property` /
`save_revision` (upsert sobre `revision_id`). El comportamiento es
equivalente al legacy `PropertyMediaPipeline.run_job` que también
abría 4 UoWs separados (R1 documentado en
`explore_feature_14:6 R1`).

### 2.3 — `_LocalArtifactsPublisher` adapter inline

Para puentar `PersistLocalArtifactsUseCase` con el contrato
`local_publisher` (`publish_media` / `publish_existing_media`) que
espera `PublishReelUseCase`, el orquestador instancia un helper inline
de 14 LoC:

```python
class _LocalArtifactsPublisher:
    def __init__(self, persist: PersistLocalArtifactsUseCase) -> None:
        self._persist = persist

    def publish_media(self, context, rendered_media):
        return self._persist.execute(context, rendered_media)

    def publish_existing_media(self, context):
        return self._persist.execute_existing(context)
```

Equivalente al `FileSystemMediaPublisher` retirado de
`pipeline_adapters.py:135-179` (R3 del explore), pero sin el alias
defensivo `publish_video` / `publish_existing_video` (no había callers
externos verificados; el contrato del Protocol `MediaPublisher` se
borra junto con `interfaces.py`).

---

## 3. Decisiones del explore respetadas

- **§0.A — `ReelPipeline` rewrite**: hecho. El cuerpo de
  `ReelPipeline.handle` ya no delega en
  `application.bootstrap.runtime.build_default_job_handler`; instancia
  y compone directamente los 4 use cases.
- **§0.B1+B2 — bridge legacy borrado**: hecho. (B1) la cadena `worker →
  ReelPipeline → bootstrap → PropertyMediaPipeline → pipeline_adapters →
  use cases` colapsa a `worker → ReelPipeline → use cases`. (B2) los 4
  archivos huérfanos (`media_pipeline.py`, `interfaces.py`,
  `job_runner.py`, `pipeline_adapters.py`) borrados físicamente.
- **§0.C — `RenderScriptedVideoUseCase` duplicado**: hecho. La copia en
  `modules/reels/application/use_cases/__init__.py:22-51` queda
  sustituida por un re-export desde el archivo dedicado
  `render_scripted_video.py:10-39`.
- **§0.D / §2 — `_NoopDispatcher` reemplazo (D2)**: hecho. La clase
  `_NoopDispatcher` (`apps/api/app_factory.py:105-134`) borrada;
  `dispatcher_state = (lambda: True) if dispatcher_accepting_jobs is
  None else dispatcher_accepting_jobs` reemplaza la rama por defecto.
  `lifespan` simplificado a `yield`. El campo HTTP
  `dispatcher_accepting_jobs` se mantiene en `/health/ready` y en la
  respuesta del webhook router (sin cambio de contrato externo).
- **§0.E — pipeline legacy borrado**: hecho. 4 archivos borrados en
  feature 16. `content_generation.py` y `scripted_render/service.py`
  preservados (D5/D6 — out-of-scope, feature 17/18).
- **§6 R8 — logging top-level**: hecho. `ReelPipeline.handle` emite 4
  `LoggedProcess` blocks (pipeline-level + ingestion + render +
  publish) preservando el patrón observability del legacy
  `PropertyMediaPipeline.run_job`.
- **§6 R9 — file lock omitido**: hecho. `core.locking.exclusive_file_lock`
  no se invoca. La cola SQL atómica (`claim_next_ready_job` con `FOR
  UPDATE SKIP LOCKED`) + `supersede_queued_jobs` cubren la garantía.
- **§6 R10 — renderer instanciado una vez**: hecho. `self._renderer =
  DefaultMediaRenderer(self.workspace_dir)` en `__init__`, reusado por
  jobs. Renderer no toca DB.
- **§6 R12 — settings imports**: 7 settings importados directos
  (`DATABASE_URL`, `PROPERTY_MEDIA_DELETE_*`,
  `SOCIAL_PUBLISHING_*`).
- **§6 R13 — `application/types`**: preservado tal cual. `PropertyMediaJob`,
  `SocialPublishContext`, `PropertyContext`, `RenderedMediaArtifact` se
  siguen importando del módulo legacy. Feature 18 los retira.
- **§6 R14 — `final_event_status` lógica intacta**: el dispatcher
  `_process_next_job:191-199` no se tocó. `ReelPipeline.handle` devuelve
  `None` (noop) o `PublishedMediaArtifact` (otherwise), preservando el
  contrato `completed`/`noop` del worker.

---

## 4. Desviaciones frente al plan del explorer

### 4.1 — `ReelPipeline.handle`: UoW por paso en lugar de UoW único

Documentado en §2.2. **Razón**: el contrato de `local_publisher` que
`PublishReelUseCase` espera no propaga el `uow` al `_LocalArtifactsPublisher`
adapter, y el adapter delega en `PersistLocalArtifactsUseCase.execute`
sin uow. Combinado con un UoW exterior, Postgres deadlockea por
row-lock conflict. Este deadlock NO se observa en el legacy
`PropertyMediaPipeline.run_job` porque ya abría 4 UoWs separados (cada
adapter abría el suyo). Por tanto el comportamiento post-feature-16
coincide con el pre-feature-16: 4 transacciones cortas
secuenciales.

Alternativa rechazada: cambiar la firma de `local_publisher.publish_media`
para aceptar `uow=`. Esto requeriría tocar `PublishReelUseCase.execute`
(regla dura: NO modificar los 4 use cases). Out-of-scope para feature
16.

### 4.2 — `orchestrator.py` 272 LoC vs ~170 estimados

Más LoC por (a) docstring extendida del módulo + del adapter inline +
del helper `build_property_media_job`, y (b) los `LoggedProcess` blocks
con detalle por línea (`format_detail_line` x 3 por bloque). El plan
original estimaba ~170; el código verbatim sin observability cabría en
~140, pero conservar logging es R8 del explore.

### 4.3 — `apps/api/app_factory.py` 390 LoC vs ~395 estimados

Ligeramente menos por la simplificación más agresiva del lifespan
(2 LoC vs estimado 5 LoC).

### 4.4 — `application/bootstrap/{runtime,__init__}.py` 68 LoC vs ~95 estimados

Más limpio de lo proyectado: además de las 3 funciones huérfanas, el
explore preveía conservar más helpers; solo se conservaron las 3
realmente consumidas (
`build_runtime_unit_of_work_factory` por `RenderScriptedVideoUseCase`,
`build_default_social_property_publisher` por `tests/test_social_publishing.py`
y por `ReelPipeline._build_default_social_property_publisher`,
`build_default_unit_of_work_factory` por
`tests/integration/test_worker_runtime.py`).

### 4.5 — `RenderScriptedVideoUseCase` deduplicación

El explore (§0.C) describía una "copia redundante" en
`use_cases/__init__.py:22-51`. En el archivo actual (28 LoC) sólo
queda el re-export limpio:

```python
from modules.reels.application.use_cases.render_scripted_video import (
    RenderScriptedVideoUseCase,
)
```

Más 4 imports más para los otros 3 use cases + `__all__`. La definición
canónica vive en `render_scripted_video.py:10-39` (intacta).

---

## 5. Resultado de los checks de cierre

### Tests del feature

```
$ ./.venv/Scripts/python.exe -m pytest -q tests/integration/delivery/test_worker_dispatcher_flow.py
..                                                                       [100%]
2 passed in 4.24s
```

### Suite completa (`./init.sh`)

```
── 5. Ejecutando readiness checks ──────────────────────
[OK]    apps.api --check verde
[OK]    apps.worker --check verde

── 6. Ejecutando tests ─────────────────────────────────
........................................................................ [ 15%]
........................................................................ [ 31%]
........................................................................ [ 47%]
........................................................................ [ 63%]
........................................................................ [ 79%]
........................................................................ [ 94%]
.......................                                                  [100%]
455 passed in 197.54s (0:03:17)
[OK]    pytest verde

── 7. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

Baseline pre-feature-16: **453 tests** (post-feature-15).
Post-feature-16: **455 tests** (453 + 2 nuevos). Esperado ≥ 455 — cumplido.

`init.sh` reporta WARN en step 4 ("4 archivos modificados en directorios
legacy en últimas 24h"): es la modificación esperada en
`application/bootstrap/{runtime,__init__}.py` y los borrados en
`application/pipeline/`. Coherente con el patrón aplicado en features
10-14.

### Readiness checks (run independientes)

```
$ ./.venv/Scripts/python.exe -m apps.api --check
... API_CHECK=0

$ ./.venv/Scripts/python.exe -m apps.worker --check
Worker --check OK: kinds=reel_publish, scripted_render worker_count=1 lease=900s poll=0.50s
WORKER_CHECK=0
```

Ambos exit 0.

### Repo limpio

- `Grep` exhaustivo de imports huérfanos a símbolos borrados:
  - `from application.pipeline.media_pipeline` → 0 hits en código vivo
    (`apps/`, `modules/`, `shared/`, `tests/`, `application/`,
    `services/`).
  - `from application.pipeline.interfaces` → 0 hits en código vivo.
  - `from application.pipeline.job_runner` → 0 hits en código vivo.
  - `from application.bootstrap.pipeline_adapters` → 0 hits en código
    vivo.
  - `PropertyMediaPipeline` / `PropertyMediaJobRunner` /
    `_NoopDispatcher` / Protocols (`MediaRenderer`, `MediaPublisher`,
    `MediaPreparationService`, `PropertyInfoService`,
    `PhotoSelectionEngine`) → solo hits en `progress/*.md`
    (informes históricos) y en docstring mentions en
    `modules/reels/application/orchestrator.py:6` y
    `modules/rendering/application/frame_composition.py:19,22` ("replaces
    ``PropertyMediaPipeline``" / "the legacy ``MediaRenderer`` Protocol").
- `application/bootstrap/runtime.py` y `application/bootstrap/__init__.py`
  byte-iguales (verificado con `diff` exit 0).
- Sin `xfail`, sin `print()` debug, sin `TODO`/`FIXME` introducidos.
- `feature_list.json` feature 16 status `in_progress` (closer la promueve a
  `done`).

---

## 6. Notas para el reviewer / closer

- El comportamiento del orquestador es **funcionalmente equivalente**
  al legacy `PropertyMediaPipeline.run_job` en los 3 caminos
  (`is_noop`, `publish_existing`, feliz). La diferencia conceptual con
  el plan original (UoW único compartido) está documentada en §2.2 y
  §4.1: el deadlock observado bloquea esa optimización mientras el
  contrato `local_publisher` siga sin propagar `uow=`. Si el reviewer
  prefiere atomicidad por job, requeriría modificar
  `PublishReelUseCase.execute` (out-of-scope feature 16).
- `_NoopDispatcher` decisión D2 (mantener `dispatcher_accepting_jobs`
  hardcoded a `True` en el contrato HTTP) preserva los 9 tests
  potencialmente afectados sin tocarlos.
- El test nuevo `test_worker_dispatcher_flow.py` cubre el flujo
  end-to-end real (`claim → handler → ack`) con ambos kinds. Stubea
  `DefaultMediaRenderer.render_media`,
  `LocalPhotoSelectionEngine.select_photos`,
  `_build_default_social_property_publisher` y
  `ScriptedVideoRenderService.{__init__,render_from_manifest}` para
  evitar costes de ffmpeg/red en CI.
- `application/pipeline/content_generation.py` y
  `application/scripted_render/service.py` siguen vivos (D5/D6).
  Feature 17 o 18 los moverá/retirará.

---

**Fin del informe.**
