# Explore — Feature 12 `reels_use_case_persist_local_artifacts`

> Mapa de extracción del paso 3 del pipeline (render del reel + persistencia
> local de poster/manifest/frames + escritura de `media_revisions` y
> `outbox_events`) desde `application/pipeline/media_services.py`
> (807 LoC tras feature 11) hacia
> `modules/reels/application/use_cases/persist_local_artifacts.py`
> con clase `PersistLocalArtifactsUseCase`.

Contexto leído: `feature_list.json` (entry #12),
`progress/explore_feature_11_prepare_reel_assets.md`,
`progress/impl_11_prepare_reel_assets.md`,
`progress/review_11_prepare_reel_assets.md`,
`application/pipeline/media_services.py` (807 LoC actual),
`application/pipeline/media_pipeline.py`,
`application/pipeline/interfaces.py`,
`application/pipeline/default_services.py`,
`application/bootstrap/runtime.py` (= `application/bootstrap/__init__.py`,
byte-a-byte iguales en feature 10/11),
`modules/reels/application/use_cases/prepare_reel_assets.py` (patrón),
`modules/reels/application/use_cases/ingest_property_into_reel.py` (patrón
y duplicación de `_build_property_record`),
`modules/reels/infrastructure/reel_state_repository.py`
(`save_local_artifacts`, `update_workflow_state`),
`modules/reels/infrastructure/media_revision_repository.py`
(`save_revision`),
`modules/reels/domain/media_revision.py` (dataclass moderno),
`shared/db/uow.py`,
`repositories/stores/media_revision_store.py` (legacy `MediaRevisionRecord`),
`application/types.py` (PropertyContext, RenderedMediaArtifact,
PublishedMediaArtifact),
`tests/unit/reels/_uow_stubs.py`,
`tests/unit/reels/test_prepare_reel_assets.py`,
`tests/integration/reels/test_prepare_reel_assets_flow.py`,
`tests/support/postgres.py`,
`docs/phase_2_operating_rules.md`,
`services/media/reel_rendering/` (entrypoints `__init__.py`, `poster.py`,
`preparation.py`, `runtime.py`).

---

## 0. Decisión de alcance: qué es "step 3"

`media_pipeline.py` orquesta **cuatro** procesos lógicos:
`PROPERTY INGESTION` (línea 43) → `MEDIA PREPARATION` (86) →
`MEDIA RENDER` (94) → `MEDIA PUBLISH` (102). Pero la fila de DB
`save_local_artifacts` + `save_media_revision` + outbox `media_rendered`
**no la escribe el renderer**: la escribe el **local publisher**
(`FileSystemMediaPublisher.publish_media`, `media_services.py:343-438`)
en su transacción UoW (`media_services.py:365-414`). El feature_list
describe step 3 como "Persistencia de artefactos locales (poster,
manifest, frames) tras el render. Coordina rendering + storage" — esa
descripción cubre EXACTAMENTE lo que hoy hace `FileSystemMediaPublisher.publish_media`:

  1. Resuelve directorios finales (`generated_reels_root`, `generated_posters_root`).
  2. Mueve atómicamente `staging_dir/...` → `output_dir/...` (mp4, manifest,
     poster) vía `_replace_atomically`.
  3. Borra el staging si `cleanup_temporary_files`.
  4. **Persiste**: `pipeline_state_repository.save_local_artifacts` +
     `media_revision_store.save_media_revision` +
     `outbox_event_store.add_event(event_type="media_rendered")`.

Y `DefaultMediaRenderer.render_media` (`media_services.py:200-326`) es
"render puro" — no escribe DB, solo produce `RenderedMediaArtifact` en
`staging_dir`. Eso es lo que feature 14
(`rendering_pure_renderer_and_delete_media_services`) extrae a
`modules/rendering/application/`. **No es feature 12.**

**Por tanto, esta exploración asume**:
- **Feature 12 extrae `FileSystemMediaPublisher.publish_media` +
  `publish_existing_media` + helpers privados** (`_resolve_output_dir`,
  `_publish_related_poster`, `_replace_atomically`).
- `DefaultMediaRenderer` NO se mueve aquí (queda para feature 14).
- `CompositeMediaPublisher._publish_externally` (publish social) NO se
  mueve aquí (es feature 13 = `publish_reel`).
- El use case nuevo se llama `PersistLocalArtifactsUseCase` y se invoca
  desde `media_services.py` vía un adapter delgado
  `FileSystemMediaPublisher` que cumple el Protocol `MediaPublisher`.

Si el leader prefiere otra interpretación (p. ej. mover también el
renderer a este use case), **bloqueo y re-leo**. Pero el naming
(`persist_local_artifacts`) y el orden de features (12 antes que 13
"publish_reel") solo encajan con esta lectura. El acceptance literal
("persistencia tras el render") refuerza la lectura.

---

## 1. Alcance exacto a extraer (rangos línea-a-línea)

Todos los rangos refieren a `application/pipeline/media_services.py`
(807 LoC tras feature 11 + fix post-review).

### Método público entrypoint del paso 3

- **`FileSystemMediaPublisher.publish_media`** —
  `media_services.py:343-438`.
  Firma:
  ```python
  def publish_media(
      self,
      context: PropertyContext,
      rendered_media: RenderedMediaArtifact,
  ) -> PublishedMediaArtifact
  ```
  Único caller externo: `CompositeMediaPublisher.publish_media`
  (`media_services.py:528`: `self.local_publisher.publish_media(context, rendered_media)`).
  Indirectamente lo invoca también `media_pipeline.py:103` al pasar por
  el composite.

### Constructor del servicio

- **`FileSystemMediaPublisher.__init__`** — `media_services.py:333-341`.
  Recibe `unit_of_work_factory` (legacy) y `cleanup_temporary_files`. Se
  trasplanta al `__init__` del use case con la misma mutación que en
  features 10/11: `del unit_of_work_factory`, el use case abre su propio
  `DatabaseUnitOfWork` moderno.

### Métodos de la clase a mover (TODOS los del paso 3 que persisten artefactos)

| Rango                          | Símbolo                                      | Notas |
|--------------------------------|----------------------------------------------|-------|
| `media_services.py:333-341`    | `__init__`                                   | Mover (transformar firma; `unit_of_work_factory` se descarta). |
| `media_services.py:343-438`    | `publish_media` (entrypoint)                 | Mover. |
| `media_services.py:440-445`    | `publish_video` (alias del entrypoint)       | Mover. **Pregunta abierta**: el Protocol `MediaPublisher` (`interfaces.py:71-83`) NO declara `publish_video`. `grep publish_video` solo encuentra la definición y el alias en composite (`media_services.py:531`). **Conservar el alias** en el adapter delgado por compat con código legacy desconocido; el use case nuevo expone solo `execute()`. |
| `media_services.py:447-459`    | `publish_existing_media`                     | Mover. Es el camino "publish-only retry sin render" (cuando `context.requires_render=False`). Lo invoca `media_pipeline.py:73` vía composite. **Nota**: `publish_existing_media` NO escribe DB ni outbox — solo valida que `context.existing_published_media` no es None y lo devuelve. La persistencia equivalente la hace el composite en `_persist_workflow_transition`. **Decisión**: mover el método tal cual al use case (lo expone como `execute_existing(context)` o método auxiliar) pero sin DB-side-effects. |
| `media_services.py:461-462`    | `publish_existing_video` (alias)             | Idem `publish_video`. |
| `media_services.py:464-468`    | `_resolve_output_dir` (staticmethod)         | Único caller: `publish_media:349` y `_publish_related_poster:494`. Mover. |
| `media_services.py:470-498`    | `_publish_related_poster` (classmethod)      | Único caller: `publish_media:357`. Mover. Importante: usa `build_log_context` para construir un `ValidationError` cuando el poster no existe en un `reel_video`. |
| `media_services.py:500-504`    | `_replace_atomically` (staticmethod)         | Caller: `publish_media:360, :361` y `_publish_related_poster:497`. Mover. |
| `media_services.py:507-508`    | `class FileSystemMediaPublisher(FileSystemMediaPublisher): pass` (class shadow) | **Borrar**. Es el bug-shadow heredado de features anteriores (mismo patrón que el `DefaultMediaRenderer:329-330` redundante y los tres class-shadow extra). El revisor de feature 11 NO lo señaló pero está latente igual que en feature 10. |

### Free funcs / staticmethods que SOLO usa el step 3

Hoy en `media_services.py`, los siguientes helpers son **compartidos**
entre paso 3 (publish local) y paso 4 (publish externo, vía
`CompositeMediaPublisher._persist_workflow_transition` y
`CompositeMediaPublisher.publish_existing_media`):

- `_now_iso` (línea 67-68). **Compartido** con `_persist_workflow_transition:771`. **Conservar**.
- `_relative_path_text` (71-78). **Compartido** con `_persist_workflow_transition:765-766`. **Conservar**.
- `_build_workflow_payload` (81-112). **Compartido** con `_persist_workflow_transition:779`. **Conservar**.

Es decir, los 3 helpers de módulo se quedan en `media_services.py`
porque feature 13 los necesitará. Pero el use case nuevo
**los necesita también** — duplicar (igual que `_build_property_record`
en feature 11) o re-importar. Recomendación: **duplicar**
(`_now_iso` 2 LoC, `_relative_path_text` 8 LoC, `_build_workflow_payload`
~32 LoC) para que el use case sea independiente. Trade-off explícito
documentado en §6.

### Imports al tope de `media_services.py` que pasan al use case nuevo

Necesarios en `modules/reels/application/use_cases/persist_local_artifacts.py`:

```python
import logging
import os                         # _replace_atomically usa os.replace
import shutil                     # _replace_atomically usa shutil.copy2; publish_media usa rmtree
from pathlib import Path
from uuid import uuid4

from application.types import (
    PropertyContext,
    PublishedMediaArtifact,
    RenderedMediaArtifact,
)
from core.errors import ValidationError
from core.logging import build_log_context, format_console_block, format_detail_line
from core.media_cleanup import (
    DEFAULT_DELETE_TEMPORARY_FILES,
    should_cleanup_render_staging_dir,
)
from shared.db import DatabaseUnitOfWork
```

Imports legacy que el use case necesita por la persistencia:

- **Legacy**: `from repositories.stores.media_revision_store import MediaRevisionRecord`
  (línea `:46` actual). **Decisión clave**: el use case nuevo escribe en
  `uow.reels.revisions.save_revision(MediaRevision)` — el dataclass
  moderno `modules.reels.domain.MediaRevision` (verificado:
  `media_revision.py:9-23`, mismas columnas que el legacy
  `MediaRevisionRecord` excepto que renombra
  `wordpress_source_id`→`ingestion_source_id` y `site_id`→`external_source_id`).
  → **Reemplazar el import legacy por**:
  ```python
  from modules.reels.domain import MediaRevision
  ```

Imports en `media_services.py` que **NO necesita el use case nuevo** y
que se quedan en `media_services.py` porque los usa el paso 4 (publish
externo, feature 13):

- `format_context_line` (`core.logging`) — composite social.
- `SocialPublishingResultError`, `TransientSocialPublishingResultError`,
  `extract_error_details` (`core.errors`) — composite social.
- `services.publishing.social_delivery.GoHighLevelPropertyPublisher`,
  `MultiPlatformPublishResult` — composite social.
- `REVIEW_WORKFLOW_ENABLED` (`settings`) — composite social.
- `DEFAULT_DELETE_SELECTED_PHOTOS` (`core.media_cleanup`) — feature 11
  ya lo dejó solo como bridge en el adapter `DefaultMediaPreparationService`;
  ya no se usa en `media_services.py` cuerpo. **Verificar al final**:
  si tras feature 12 sigue sin uso, borrar.
- `MediaRevisionRecord` (legacy) — el adapter post-feature-12 ya no lo
  necesita; **borrar el import** una vez extraído.

Imports que **PUEDEN** quedar huérfanos en `media_services.py` tras
feature 12 (los usa solo el paso 3 hoy):

- `os` — solo lo usa `_replace_atomically`. Tras la extracción, **se
  puede borrar** del import block de `media_services.py`. Verificar.
- `should_cleanup_render_staging_dir` — solo lo usa `publish_media:362`.
  Tras la extracción, **se puede borrar** del import block. Verificar.
- `tempfile` — lo usa `DefaultMediaRenderer:223` (staging). Conservar.
- `uuid4` — lo usa `DefaultMediaRenderer:219` y
  `_persist_workflow_transition:775`. Conservar.

---

## 2. Dependencias del servicio (`FileSystemMediaPublisher.__init__`)

Lo que recibe hoy en `__init__` (`media_services.py:333-341`):

| Parámetro                                     | Origen runtime                                  | Equivalente moderno |
|-----------------------------------------------|--------------------------------------------------|---------------------|
| `unit_of_work_factory: Callable[[], UnitOfWork]` (legacy) | `build_runtime_unit_of_work_factory(workspace_dir, database_locator=...)` que construye `repositories/postgres/uow.DatabaseUnitOfWork` | **Adaptar**. Mismo patrón que features 10/11: el adapter delgado acepta el factory legacy y lo descarta con `del unit_of_work_factory`. El use case abre su propio `shared.db.DatabaseUnitOfWork(database_locator, base_dir=workspace_dir)`. |
| `cleanup_temporary_files: bool` (kw-only)     | `PROPERTY_MEDIA_DELETE_TEMPORARY_FILES`         | Idem; lo recibe el use case en `__init__`. |

**Adicional necesario en el `__init__` del use case** (no estaba en el
servicio legacy porque dependía del factory):

- `workspace_dir: str | Path` — base_dir para el UoW moderno. Hoy
  `FileSystemMediaPublisher` no lo recibe explícitamente porque el
  factory legacy lo capturaba en su closure
  (`build_runtime_unit_of_work_factory:81-83`). **El use case sí lo
  necesita** para `DatabaseUnitOfWork(..., base_dir=workspace_dir)` — es
  obligatorio para que `ReelStateRepository.save_local_artifacts`
  funcione (línea `:297-300` lo verifica con un `RuntimeError`).
- `database_locator: str | Path | None = None` — mismo patrón que
  features 10/11.

Operaciones de DB que ejecuta hoy `publish_media` y sus métodos privados
(dentro del bloque `with self.unit_of_work_factory() as unit_of_work` de
`publish_media:365-414`):

1. `unit_of_work.pipeline_state_repository.save_local_artifacts(
   agency_id, wordpress_source_id, site_id, source_property_id,
   artifact_kind, artifact_path, metadata_path, render_profile,
   current_revision_id)` — actualiza la fila de `reels` con paths
   relativos al workspace y bumpea `workflow_state="rendered"` y
   `render_status="completed"`.
2. `unit_of_work.media_revision_store.save_media_revision(MediaRevisionRecord(...))`
   — inserta la fila append-only en `media_revisions`.
3. `unit_of_work.outbox_event_store.add_event(event_id, aggregate_type,
   aggregate_id, event_type="media_rendered", payload, agency_id,
   wordpress_source_id, site_id, source_property_id)` — encola el
   evento.

**Operaciones de filesystem** (no tocan DB):

- `final_output_dir.mkdir(parents=True, exist_ok=True)` (línea 350).
- `_replace_atomically(staging_path, final_path)` para mp4 + manifest +
  poster (línea 360, 361, 497).
- `shutil.rmtree(rendered_media.staging_dir, ignore_errors=True)` si
  `cleanup_temporary_files` (línea 363).

---

## 3. Mapeo a UoW moderno (`shared/db/uow.py`)

Repos modernos disponibles (vía `uow.<bc>.<repo>`):

| Operación legacy                                                                              | Reemplazo moderno (firma exacta) |
|------------------------------------------------------------------------------------------------|----------------------------------|
| `unit_of_work.pipeline_state_repository.save_local_artifacts(agency_id, wordpress_source_id, site_id, source_property_id, artifact_kind, artifact_path, metadata_path, render_profile, current_revision_id)` | **`uow.reels.states.save_local_artifacts(agency_id, ingestion_source_id, external_source_id, source_property_id, artifact_kind, artifact_path, metadata_path, render_profile, current_revision_id, manifest_path=None, video_path=None)`** (`reel_state_repository.py:282-350`). **Mismos kw-args**, renombrados: `wordpress_source_id`→`ingestion_source_id`, `site_id`→`external_source_id`. **Detalle importante**: requiere que el UoW se haya construido con `base_dir`, que ya lo hace `DatabaseUnitOfWork(..., base_dir=workspace_dir)`. |
| `unit_of_work.media_revision_store.save_media_revision(MediaRevisionRecord(revision_id, agency_id, wordpress_source_id, site_id, source_property_id, artifact_kind, render_profile, media_path, metadata_path, mime_type, content_fingerprint, publish_target_fingerprint, workflow_state, created_at))` | **`uow.reels.revisions.save_revision(MediaRevision(...))`** (`media_revision_repository.py:44-79`). Construir `MediaRevision` con: `revision_id, agency_id, ingestion_source_id, external_source_id, source_property_id, artifact_kind, render_profile, media_path, metadata_path, mime_type, content_fingerprint, publish_target_fingerprint, workflow_state, created_at`. Mismas 14 columnas que `MediaRevisionRecord` con los dos rename de columna. |
| `unit_of_work.outbox_event_store.add_event(event_id, aggregate_type, aggregate_id, event_type, payload, agency_id, wordpress_source_id, site_id, source_property_id)` | **`uow.delivery.outbox.add_event(...)`** — verificar la firma del repo moderno `OutboxRepository.add_event` antes de implementar (no lo leí en esta exploración). Probable rename `wordpress_source_id`→`ingestion_source_id`, `site_id`→`external_source_id`. **Si la firma moderna difiere** (p. ej. parámetros distintos), el implementer adapta el caller para construir el payload moderno. |

### Mapping de paths para `save_local_artifacts`

`save_local_artifacts` espera `artifact_path` y `metadata_path` como
`Path` absolutos. El repo moderno (`reel_state_repository.py:312-317`)
los relativiza al `base_dir` con `_relative_to_base`. Esto reemplaza la
llamada manual a `_relative_path_text(context.workspace_dir, ...)` que
hace el legacy en `MediaRevisionRecord` (líneas 386-387). **Para el
`MediaRevision` moderno**, los paths SÍ se construyen como strings
relativos manualmente con un helper `_relative_path_text` duplicado en
el use case nuevo (mantener semántica byte-a-byte).

### Mapping del `outbox_event` payload

El payload se construye con `_build_workflow_payload(context,
workflow_state="rendered", revision_id=..., extra={"media_path": ...,
"metadata_path": ..., "mime_type": ...})` (líneas 400-408). **El use
case nuevo duplica `_build_workflow_payload` localmente** (igual que
features 10/11 duplicaron sus helpers). Trade-off documentado en §6.

---

## 4. Call sites externos y bridge worker

### Call sites de `FileSystemMediaPublisher`

| Archivo                                                | Líneas         | Acción tras feature 12 |
|--------------------------------------------------------|----------------|-------------------------|
| `application/bootstrap/runtime.py`                     | `:9` (import vía `default_services`), `:118-122` (instanciación dentro de `build_default_property_media_pipeline`) | **Cambia idéntico al patrón features 10/11**: `FileSystemMediaPublisher` queda como adapter delgado en `media_services.py` que delega al `PersistLocalArtifactsUseCase`. Bootstrap **no cambia**. |
| `application/bootstrap/__init__.py`                    | `:9, :118-122` | Idéntico (byte-a-byte iguales según diffs features 10/11). |
| `application/pipeline/default_services.py`             | `:6, :15`      | Solo re-exporta. Sin cambio funcional. |
| `application/pipeline/__init__.py`                     | re-export      | Sin cambio funcional (es dead code 1839 LoC ya pre-existente). |
| `application/pipeline/media_services.py`               | `:333-508`     | **Hay que reducir LoC** — clase queda como adapter delgado (~30-40 LoC + alias `publish_video`/`publish_existing_video`). |
| `application/pipeline/media_pipeline.py`               | `:73, :103`    | Llama a `media_publisher.publish_existing_media(context)` y `media_publisher.publish_media(context, rendered_media)` — ambos van a `CompositeMediaPublisher`. Sin cambios en feature 12 (el composite sigue intacto, solo cambia el `local_publisher` que recibe). |
| `application/pipeline/interfaces.py`                   | `:71-83`       | Protocol `MediaPublisher` (`publish_media`, `publish_existing_media`). **Sin cambios** — el adapter cumple el Protocol. |
| `CompositeMediaPublisher.__init__`                     | `media_services.py:512-521` | Recibe `local_publisher: FileSystemMediaPublisher`. **Sin cambios estructurales** — sigue recibiendo una instancia que cumple el contrato (el adapter delgado tras feature 12 sigue siendo `FileSystemMediaPublisher` con la misma firma pública). |

### Llamadas externas a `publish_media` / `publish_existing_media`

- `application/pipeline/media_services.py:528` —
  `CompositeMediaPublisher.publish_media` llama
  `self.local_publisher.publish_media(context, rendered_media)`.
- `application/pipeline/media_services.py:550` —
  `CompositeMediaPublisher.publish_existing_media` NO llama al
  `local_publisher` directamente; valida `context.existing_published_media`
  inline y llama a `_publish_externally`. **Esto es redundante con
  `FileSystemMediaPublisher.publish_existing_media`**: ambos hacen el
  mismo check de `existing_published_media is None` y el mismo
  `ValidationError`. Es duplicación pre-existente; feature 12 no lo
  arregla (queda para feature 13 cuando el composite se mueva).

### Bridge worker

`apps/worker/runtime.py:262-274` registra el handler `reel_publish` con
`reel_pipeline.handle` (`modules/reels/application/orchestrator.py`),
que hace lazy-import de `application.bootstrap.runtime.build_default_job_handler`.
**Sin cambios** en feature 12 — sigue intacto, igual que en features
10/11.

### Materialización del adapter delgado en `media_services.py`

Patrón exacto de features 10/11 (verificado en `media_services.py:115-194`).
Tras feature 12:

```python
class FileSystemMediaPublisher:
    """Bridge adapter — delegates `publish_media` to the modern use case.

    Constructor signature stays stable so `application/bootstrap/runtime.py`
    keeps working without changes during Phase 2. The `unit_of_work_factory`
    parameter is accepted for backwards compatibility but is **not** stored
    or consulted: the use case opens its own modern `DatabaseUnitOfWork`.
    Feature 14 collapses this adapter together with `media_pipeline.py`.
    """

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        cleanup_temporary_files: bool = DEFAULT_DELETE_TEMPORARY_FILES,
        workspace_dir: str | Path | None = None,
    ) -> None:
        del unit_of_work_factory  # legacy bootstrap arg.
        # FALLBACK: si bootstrap no pasa workspace_dir, derivarlo del
        # factory descartado o pedirlo explícitamente. Ver §6 R2.
        self.cleanup_temporary_files = bool(cleanup_temporary_files)
        self._use_case = PersistLocalArtifactsUseCase(
            workspace_dir=workspace_dir,
            cleanup_temporary_files=cleanup_temporary_files,
        )

    def publish_media(self, context, rendered_media):
        return self._use_case.execute(context, rendered_media)

    def publish_video(self, context, rendered_video):
        return self.publish_media(context, rendered_video)

    def publish_existing_media(self, context):
        return self._use_case.execute_existing(context)

    def publish_existing_video(self, context):
        return self.publish_existing_media(context)
```

**Atención** (R2): hoy `bootstrap` instancia
`FileSystemMediaPublisher(unit_of_work_factory=..., cleanup_temporary_files=...)`
SIN `workspace_dir` — porque el factory legacy ya capturaba el
`workspace_path` en su closure. **Hay que cambiar el bootstrap para
pasar `workspace_dir=workspace_path` explícitamente**, o derivarlo del
adapter (no es trivial). Lo más limpio: **modificar
`application/bootstrap/runtime.py:118-122` y `__init__.py:118-122`
para pasar `workspace_dir=workspace_path`** a
`FileSystemMediaPublisher(...)`. Es un cambio de 1 LoC en cada archivo.

Esto rompe la "byte-a-byte iguales" de bootstrap pero es necesario y
mínimo. Documentar en el `impl_12_*.md`.

---

## 5. Tests existentes

### `grep render_artifacts|persist_local_artifacts|FileSystemMediaPublisher|publish_media` en `tests/`

Verificado:
- `grep DefaultMediaRenderer|render_media|render_video` en `tests/`: **0 hits**.
- `grep persist_local_artifacts|render_artifacts` en código real: **0 hits**.
- `grep FileSystemMediaPublisher` en `tests/`: presumiblemente 0 también
  (mismo patrón que features 10/11; no había test que ejercitara el step
  3 directamente).

Tests "de cerca":

- `tests/integration/test_worker_runtime.py:32-94` — registra un handler
  `reel_publish` mock; **no** ejerce el pipeline real.
- `tests/integration/ingestion/test_wordpress_webhook_flow.py` — cubre
  el endpoint webhook que **encola** el job; nunca ejecuta el handler.
- `tests/test_reel_pipeline.py` — verificar (no leído en esta
  exploración) si toca render/publish. Probable que sí mockee servicios
  enteros.

**Conclusión**: feature 12 **suma** los dos tests nuevos del acceptance
sin migrar/adaptar nada existente, idéntico a features 10/11.

### Crear (acceptance feature 12)

- `tests/unit/reels/test_persist_local_artifacts.py` — con
  `tempfile.TemporaryDirectory()`. Tests sugeridos:
  1. **Camino feliz `reel_video`**: contexto con render completo;
     `RenderedMediaArtifact` apuntando a un staging temp con mp4 +
     manifest + poster sintéticos (escribir bytes con `.write_bytes(b"x")`);
     stubs `_StubReelStates.save_local_artifacts`,
     `_StubMediaRevisions.save_revision`, `_StubOutbox.add_event`;
     verifica que tras `execute` el mp4 + manifest + poster aparecen en
     los directorios finales (`generated_reels_root`,
     `generated_posters_root`) y que las 3 llamadas DB recibieron
     argumentos correctos (paths relativos al workspace,
     `workflow_state="rendered"`, etc.).
  2. **Camino `poster_image` (sin manifest)**: `RenderedMediaArtifact`
     sin metadata_path; `_resolve_output_dir` devuelve
     `generated_posters_root`; sin manifest move; mp4 (o jpg) sí move.
  3. **Cleanup staging**: con `cleanup_temporary_files=True`, el
     `staging_dir` se borra tras el move; con `False`, persiste.
  4. **Poster faltante en `reel_video`**: el staging no contiene
     `<slug>-poster.jpg` → `ValidationError(code="POSTER_REQUIRED")` con
     `build_log_context` correcto.
  5. **Poster faltante en `poster_image`**: NO eleva (el branch
     `if rendered_media.artifact_kind == "reel_video"` lo evita).
  6. **`execute_existing` (publish-only retry) sin
     `existing_published_media`**: → `ValidationError(code="EXISTING_MEDIA_REQUIRED")`.
  7. **`execute_existing` con `existing_published_media`**: devuelve el
     mismo `PublishedMediaArtifact` sin escribir DB ni mover archivos.

  Stubs UoW: `_StubReelStates` (con `save_local_artifacts` —
  **AÑADIR al `_uow_stubs.py` global**, hoy el stub solo tiene `get`,
  `update_workflow_state`, `update_publish_status`),
  `_StubMediaRevisions` (con `save_revision` — **NUEVO**, no existe en
  `_uow_stubs.py`), `_StubOutbox` (con `add_event` — **NUEVO**, no
  existe en `_uow_stubs.py`). Como en feature 11, el implementer puede
  optar por stubs inline en el archivo de test (decisión documentada
  en review feature 11 como aceptable).

- `tests/integration/reels/test_persist_local_artifacts_flow.py` —
  `temporary_postgres_schema` + `seed_tenant` + `temporary_workspace`,
  ejecuta secuencialmente:
  1. Use case ingest (para crear las filas de `properties` y `reels`).
  2. Use case prepare (con monkeypatch de `LocalPhotoSelectionEngine.select_photos`).
  3. **Use case persist_local_artifacts**: construir un
     `RenderedMediaArtifact` artificial apuntando a un `staging_dir`
     dentro del workspace con bytes sintéticos en mp4 + manifest +
     poster; ejecutar `execute(context, rendered_media)`.

  Asserts:
  - Fila en `reels` con `workflow_state='rendered'`,
    `render_status='completed'`, `local_artifact_path` (relativo) no
    vacío, `local_metadata_path` no vacío, `current_revision_id` no
    vacío.
  - Fila en `media_revisions` con `revision_id` esperado,
    `workflow_state='rendered'`.
  - Fila en `outbox_events` con `event_type='media_rendered'`,
    payload JSON conteniendo `workflow_state='rendered'`,
    `media_path`, `metadata_path`.
  - Los archivos físicos:
    `<workspace>/site_storage/<site>/generated_reels/<slug>-reel.mp4`
    (verificar paths exactos — el `_resolve_output_dir` usa
    `context.storage_paths.generated_reels_root`),
    `<...>-reel.json` (manifest), y
    `.../generated_posters/<slug>-poster.jpg` existen.

### Adaptar / migrar

- **`tests/unit/reels/_uow_stubs.py`**: añadir `save_local_artifacts`,
  `save_revision`, `add_event` (o `StubMediaRevisions` y `StubOutbox`
  nuevos). Cambio aditivo, no rompe tests existentes.

---

## 6. Riesgos / acoplamientos

### R1 — Cruce con paso 4 (publish externo, feature 13)

`CompositeMediaPublisher._persist_workflow_transition`
(`media_services.py:725-789`) ESCRIBE el mismo conjunto de tablas
(`reels`, `media_revisions`, `outbox_events`) usando los **mismos 3
helpers** (`_now_iso`, `_relative_path_text`, `_build_workflow_payload`)
y los mismos call patterns:
- `unit_of_work.pipeline_state_repository.update_social_publish_status`
- `unit_of_work.pipeline_state_repository.update_workflow_state`
- `unit_of_work.media_revision_store.save_media_revision`
- `unit_of_work.outbox_event_store.add_event`

**Acción para feature 12**: NO tocar `_persist_workflow_transition`,
queda intacto en `media_services.py`. Feature 13 lo absorbe.

**Implicación de duplicación de helpers**: feature 12 duplica
`_now_iso`, `_relative_path_text`, `_build_workflow_payload` en
`persist_local_artifacts.py`. Feature 13 los duplicará otra vez en
`publish_reel.py`. Feature 14 los unifica. Es coste documentado, no
bloqueante.

### R2 — Bootstrap pasa `workspace_dir` (cambio mínimo en bootstrap)

Documentado en §4. Hoy `FileSystemMediaPublisher.__init__` no recibe
`workspace_dir` — el factory legacy lo capturaba. El use case nuevo lo
NECESITA para construir `DatabaseUnitOfWork(..., base_dir=workspace_dir)`,
que es requisito de `ReelStateRepository.save_local_artifacts`
(verificado: `reel_state_repository.py:297-300` eleva `RuntimeError` si
`base_dir is None`).

**Cambio**: añadir `workspace_dir=workspace_path` en la llamada de
`bootstrap.runtime.build_default_property_media_pipeline:118-122` y en
el `__init__.py` byte-igual. Esto rompe la propiedad "bootstrap
byte-a-byte iguales features 10/11". Es necesario.

Alternativa (más fea, no recomendada): el adapter delgado deduce
`workspace_dir` del `_StubXxx` o lo recibe via classvar global. **NO**.

### R3 — `MediaRevisionRecord` (legacy) vs `MediaRevision` (moderno)

Documentado en §3. El use case nuevo importa
`from modules.reels.domain import MediaRevision` y NO usa el dataclass
legacy `repositories.stores.media_revision_store.MediaRevisionRecord`.
Una vez extraído, el import legacy en `media_services.py:46` queda
huérfano. **Borrar**.

Verificar tras la edición que `_persist_workflow_transition`
(feature 13) sigue usando `MediaRevisionRecord` — sí lo usa
(`:757-772`). Por tanto el import sigue vivo en `media_services.py`
hasta feature 13. **Conservar** el import en `media_services.py` post-12.

### R4 — Doble UoW durante el bridge

Mismo issue documentado en feature 10/11. Sin acción — feature 14 lo
elimina.

### R5 — `class FileSystemMediaPublisher(FileSystemMediaPublisher): pass`
(class shadow vacío, `:507-508`)

Es el patrón de class-shadow visto antes (`DefaultMediaRenderer:329-330`,
`CompositeMediaPublisher:796-797`). Feature 11 NO los limpió (review
feature 11 no lo señaló). **Acción para feature 12**: borrar el shadow
de `FileSystemMediaPublisher` al introducir el adapter delgado
(automáticamente desaparece porque la clase original se reemplaza). El
shadow de `DefaultMediaRenderer` y `CompositeMediaPublisher` queda
vivo hasta features 14 y 13 respectivamente.

### R6 — `_publish_related_poster` necesita `build_log_context`

`build_log_context` se importa y se usa en el método movido
(`media_services.py:482`). El use case nuevo lo importa también. **Tras
feature 12, `build_log_context` SIGUE necesitándose en
`media_services.py`** porque `CompositeMediaPublisher.publish_existing_media`
(`:543`) lo usa. **Conservar el import en `media_services.py`**. Igual
que el fix post-review de feature 11.

### R7 — `ValidationError(code="EXISTING_MEDIA_REQUIRED")` duplicado

Documentado en §4 last paragraph. `FileSystemMediaPublisher.publish_existing_media`
(`:447-459`) y `CompositeMediaPublisher.publish_existing_media`
(`:538-550`) hacen el mismo check + raise. Esto es duplicación
pre-existente. Feature 12 mueve el primero al use case. El segundo (en
composite) queda intacto hasta feature 13.

**No es un bug** — la duplicación tiene una razón histórica: los dos
methods se invocan en paths distintos del pipeline (`media_pipeline.py:73`
va al composite directamente; el composite no delega `publish_existing_media`
al local; ambos fallarían igual ante el mismo input). El use case nuevo
solo expone `execute_existing` sin DB; el composite sigue duplicando
la lógica.

### R8 — `tempfile` y `staging_dir`

`DefaultMediaRenderer._render_reel:223` crea el `staging_dir` con
`tempfile.mkdtemp(prefix=..., dir=staging_root)` antes de pasarlo a
`publish_media` vía `RenderedMediaArtifact.staging_dir`. **Feature 12
NO toca el renderer**. El use case nuevo recibe el `staging_dir` ya
hecho dentro del `RenderedMediaArtifact` y se limita a:
- mover los artefactos a final via `_replace_atomically`,
- borrar el `staging_dir` con `shutil.rmtree(..., ignore_errors=True)`
  si `cleanup_temporary_files` (vía `should_cleanup_render_staging_dir`).

Para los tests unit, basta con `tempfile.TemporaryDirectory()` que
simule el `staging_dir` ya generado.

### R9 — ffmpeg / ffprobe binaries

**No aplica al step 3 extraído**. ffmpeg/ffprobe los invoca el step
RENDER (`DefaultMediaRenderer._render_reel:255-262, :263-267` →
`generate_property_reel_from_data`, `generate_property_poster_from_data`),
NO el step persist local. Ya están escritos por el renderer. El use
case `persist_local_artifacts` solo mueve archivos y escribe DB. **Sin
necesidad de stubbing ffmpeg en los tests**.

### R10 — `outbox.add_event` firma moderna

Documentado en §3. **No verificada** en esta exploración. El implementer
debe leer `modules/delivery/infrastructure/outbox_repository.py` antes
de implementar y adaptar el caller. Si la firma renombra columnas
(`wordpress_source_id`→`ingestion_source_id`, `site_id`→`external_source_id`),
ajustar.

### R11 — Storage paths del feature_list ("usa storage paths de shared/storage/")

El acceptance dice "usa storage paths de `shared/storage/`". `grep`
sobre `shared/storage/` en el repo: **no leí esta exploración**. El
servicio actual usa `context.storage_paths.generated_reels_root` y
`generated_posters_root`, que provienen de
`services.media.site_storage.resolve_site_storage_layout` (`SiteStorageLayout`).
**No existe** un módulo `shared/storage/` con storage paths
funcionales — `SiteStorageLayout` está en `domain/tenancy/storage.py`.
Verificar antes de implementar.

**Recomendación**: el use case sigue usando
`context.storage_paths.generated_reels_root` y
`generated_posters_root` directamente (no introducir indirección
nueva). Si feature_list quiere algo distinto, marcar como discrepancia
(§8) y pedir al leader que aclare.

---

## 7. Plan de implementación recomendado

### Archivos a crear

1. **`modules/reels/application/use_cases/persist_local_artifacts.py`**
   (~250-320 LoC estimado). Contiene:
   - 3 helpers de módulo duplicados: `_now_iso` (~2 LoC),
     `_relative_path_text` (~8 LoC), `_build_workflow_payload`
     (~32 LoC). Trade-off explícito (mismo patrón que
     `_build_property_record` en feature 11).
   - Clase **`PersistLocalArtifactsUseCase`** con:
     - `__init__(workspace_dir, *, cleanup_temporary_files=DEFAULT_DELETE_TEMPORARY_FILES, database_locator=None)`.
     - `execute(context: PropertyContext, rendered_media: RenderedMediaArtifact, *, uow: DatabaseUnitOfWork | None = None) -> PublishedMediaArtifact`
       (cuerpo ex `publish_media`).
     - `execute_existing(context) -> PublishedMediaArtifact` (cuerpo ex
       `publish_existing_media`).
     - Staticmethods privados `_resolve_output_dir`, `_replace_atomically`.
     - Classmethod privado `_publish_related_poster`.
     - Método privado `_persist_with_uow(...)` con la transacción DB
       (mismo patrón `_prepare_with_uow` de feature 11).
   - Re-export en `modules/reels/application/use_cases/__init__.py`.

2. **`tests/unit/reels/test_persist_local_artifacts.py`** (~350-420
   LoC estimado): 7 tests listados en §5. Usa
   `tempfile.TemporaryDirectory()` para simular el staging y los output
   dirs.

3. **`tests/integration/reels/test_persist_local_artifacts_flow.py`**
   (~180-220 LoC estimado): 1 test listado en §5. Encadena ingest →
   prepare → persist con `temporary_postgres_schema` + `seed_tenant`
   + `temporary_workspace`.

### Archivos a modificar

1. **`application/pipeline/media_services.py`** (807 LoC actual):
   - Borrar rangos del paso 3 listados en §1: `:333-508` (=176 LoC).
     Eso incluye: `__init__` + `publish_media` + `publish_video` +
     `publish_existing_media` + `publish_existing_video` +
     `_resolve_output_dir` + `_publish_related_poster` +
     `_replace_atomically` + class shadow.
   - Insertar adapter delgado `FileSystemMediaPublisher` (~40-50 LoC
     con docstring + 4 alias).
   - Limpiar imports huérfanos: `MediaRevisionRecord` (legacy) — verificar
     si se queda por composite (sí, lo usa `_persist_workflow_transition:757-772`,
     CONSERVAR), `os` (verificar — solo usaba en `_replace_atomically`,
     BORRAR si nadie más), `should_cleanup_render_staging_dir`
     (BORRAR si nadie más). `tempfile`, `uuid4`, `datetime`,
     `_relative_path_text`, `_build_workflow_payload`, `_now_iso`,
     `build_log_context` SE QUEDAN (los necesita el composite).
   - Resultado esperado: `media_services.py` baja de **807 → ~660-690
     LoC** (~120-140 LoC borrados; los rangos 333-508 = 176 LoC, pero
     el adapter añade ~45 → neto ~130).

2. **`application/bootstrap/runtime.py`** y
   **`application/bootstrap/__init__.py`** (byte-iguales):
   - Pasar `workspace_dir=workspace_path` a `FileSystemMediaPublisher(...)`
     en `build_default_property_media_pipeline` (línea 118-122 en
     ambos). Cambio de 1 LoC en cada archivo.

3. **`modules/reels/application/use_cases/__init__.py`**:
   - Añadir re-export de `PersistLocalArtifactsUseCase`.

4. **`tests/unit/reels/_uow_stubs.py`** (opcional):
   - Añadir `save_local_artifacts(...)` a `StubReelStates`.
   - Añadir `StubMediaRevisions` con `save_revision(...)`.
   - Añadir `StubOutbox` con `add_event(...)`.
   - O dejarlos inline en el archivo de test (decisión del implementer,
     review feature 11 lo aceptó).

### Archivos a borrar

Ninguno físicamente. (Class shadow `FileSystemMediaPublisher` se elimina
dentro de `media_services.py` al reescribir la clase.)

### Archivos NO modificados

- `application/pipeline/media_pipeline.py`: sigue llamando a
  `media_publisher.publish_media` y `media_publisher.publish_existing_media`
  — ambos van al composite, no al adapter directo.
- `application/pipeline/interfaces.py`: Protocol `MediaPublisher`
  intacto.
- `application/pipeline/default_services.py`: solo re-exporta el
  adapter, sin cambios.
- `apps/worker/runtime.py`: lazy import via bootstrap, intacto.
- `modules/reels/application/use_cases/ingest_property_into_reel.py`:
  no toca el step 3.
- `modules/reels/application/use_cases/prepare_reel_assets.py`: no toca
  el step 3.

### Orden sugerido

1. Implementer crea `modules/reels/application/use_cases/persist_local_artifacts.py`
   con `PersistLocalArtifactsUseCase` (helpers duplicados + execute +
   execute_existing + privados).
2. Re-export en `modules/reels/application/use_cases/__init__.py`.
3. Crea `tests/unit/reels/test_persist_local_artifacts.py` y los hace
   pasar (`pytest -q tests/unit/reels/test_persist_local_artifacts.py`).
4. Crea `tests/integration/reels/test_persist_local_artifacts_flow.py`
   y lo hace pasar.
5. Modifica `application/pipeline/media_services.py`: borra
   `FileSystemMediaPublisher` cuerpo viejo + class shadow, inserta
   adapter delgado, limpia imports huérfanos.
6. Modifica `application/bootstrap/runtime.py` y `__init__.py`: pasa
   `workspace_dir=workspace_path` a `FileSystemMediaPublisher(...)`.
7. Verifica que `tests/unit/reels/test_*` y `tests/integration/reels/test_*`
   siguen verdes (los de features 10/11).
8. Corre suite completa (`./init.sh`). Baseline post-feature-11:
   **388 verdes**. Esperado: ≥ **396 verdes** (388 + 7 unit + 1
   integration).

### LoC esperado de `media_services.py` post-feature-12

- Movido al use case nuevo: **176 LoC** (333-508).
- Adapter delgado introducido: **~45 LoC**.
- Imports/limpieza: **~ -3 LoC** (borrar `os`,
  `should_cleanup_render_staging_dir` si no quedan callers; conservar
  el resto).
- Reducción neta: **~134 LoC**.
- `media_services.py` post-feature-12: **~670-690 LoC** (de 807). Bajará
  más en features 13/14.

---

## 8. Discrepancias detectadas

### D1 — Acceptance dice "Persistencia tras el render"; el código tiene mezcla render+persist

`feature_list.json` #12 describe el step como "Persistencia de
artefactos locales (poster, manifest, frames) tras el render. Coordina
rendering + storage". Esa frase encaja con `FileSystemMediaPublisher.publish_media`
(persistencia local atómica + DB), NO con `DefaultMediaRenderer.render_media`
(genera bytes en staging, sin DB).

**Recomendación**: extraer `FileSystemMediaPublisher.publish_media` y
helpers (mi lectura). Si el leader prefiere otra interpretación, el
implementer pide aclaración antes de tocar.

### D2 — Acceptance dice "usa storage paths de `shared/storage/`"

No existe un módulo `shared/storage/` con storage paths funcionales
(no verificado al 100% pero `grep` sobre el repo no devuelve algo
prometedor). Los storage paths actuales viven en
`domain/tenancy/storage.py:SiteStorageLayout` y se construyen vía
`services/media/site_storage.resolve_site_storage_layout`.

**Recomendación**: el use case sigue accediendo a
`context.storage_paths.generated_reels_root` /
`generated_posters_root` directamente (mismo patrón que el legacy). Si
feature_list quiere introducir `shared/storage/`, eso es un refactor
adicional que cae fuera del alcance de feature 12. **Plantear al
leader**.

### D3 — `application/bootstrap/{runtime.py,__init__.py}` ya NO seguirán
byte-a-byte iguales tras feature 12

Documentado en R2/§4. El cambio es necesario porque el use case nuevo
necesita `workspace_dir` explícito para abrir el UoW moderno con
`base_dir`. La propiedad "byte-iguales" rota se restaura en feature 14
cuando bootstrap se reescribe.

### D4 — Naming del entrypoint del use case (`execute` vs `publish_media`)

`feature_list.json` #12 no especifica el nombre del método público del
use case. Phase 2 operating rules + features 10/11 establecen el patrón
`execute(...)`. El adapter `FileSystemMediaPublisher` mantiene
`publish_media`/`publish_existing_media`/aliases para no romper el
Protocol `MediaPublisher` (`interfaces.py:71-83`).

**Recomendación**: el use case expone `execute(context, rendered_media)`
y `execute_existing(context)`; el adapter delega.

### D5 — `outbox.add_event` firma moderna no verificada

Documentado en R10. El implementer la verifica antes de codear.

### D6 — Class shadows pre-existentes no limpiados en feature 11

Quedan `DefaultMediaRenderer:329-330`, `CompositeMediaPublisher:796-797`.
Feature 12 limpia el de `FileSystemMediaPublisher:507-508` (porque la
clase se reemplaza). Los otros dos siguen vivos hasta feature 13/14.

### D7 — Doble validación `EXISTING_MEDIA_REQUIRED`

Pre-existente. Documentado en §4 last paragraph y R7. Feature 12 no lo
arregla; queda para feature 13.

---

**Fin del informe.**
