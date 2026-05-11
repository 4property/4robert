# Explore — Feature 11 `reels_use_case_prepare_reel_assets`

> Mapa de extracción del paso 2 del pipeline (preparación de assets:
> selección de fotos, descarga, normalización) desde
> `application/pipeline/media_services.py` (1034 LoC tras feature 10) hacia
> `modules/reels/application/use_cases/prepare_reel_assets.py`
> con clase `PrepareReelAssetsUseCase`.

Contexto leído: `feature_list.json` (entry #11),
`progress/explore_feature_10_ingest_property_into_reel.md` (R1, plan, D4),
`progress/impl_10_ingest_property_into_reel.md` (decisiones bridge),
`progress/review_10_ingest_property_into_reel.md` (sugerencias 2 y 3),
`application/pipeline/media_services.py` (1034 LoC actual),
`application/pipeline/media_pipeline.py`,
`application/pipeline/interfaces.py`,
`application/bootstrap/runtime.py` (= `application/bootstrap/__init__.py`,
byte-a-byte iguales según diff de feature 10),
`modules/reels/application/use_cases/ingest_property_into_reel.py` (patrón),
`modules/rendering/infrastructure/ai_photo_selection/__init__.py`
(carpeta vacía, solo docstring "AI photo-selection adapter."),
`shared/db/uow.py`, `modules/catalog/infrastructure/property_repository.py`
(`upsert_property`, `replace_images`),
`modules/reels/infrastructure/reel_state_repository.py`
(no expone `update_workflow_state` con la firma legacy del paso 2),
`tests/support/postgres.py`, `tests/unit/reels/_uow_stubs.py`,
`tests/unit/reels/test_ingest_property_into_reel.py`,
`tests/integration/reels/test_ingest_property_into_reel_flow.py`,
`docs/phase_2_operating_rules.md`, `repositories/stores/property_store.py`
(`save_property_images`, `_save_property_record`, `_replace_property_images`),
`services/media/property_media/{filesystem,downloads,selection}.py`,
`services/ai/photo_selection/__init__.py`,
`tests/test_gemini_photo_selection.py`.

---

## 1. Alcance exacto a extraer (rangos línea-a-línea)

Todos los rangos refieren a `application/pipeline/media_services.py`
(1034 LoC tras feature 10).

### Método público entrypoint del paso 2

- **`DefaultMediaPreparationService.prepare_assets`** —
  `media_services.py:193-201`.
  Firma:
  ```python
  def prepare_assets(self, context: PropertyContext) -> PreparedMediaAssets
  ```
  Único caller externo: `PropertyMediaPipeline.run_job`
  (`media_pipeline.py:87`: `self.media_preparation_service.prepare_assets(context)`).

### Constructor del servicio

- **`DefaultMediaPreparationService.__init__`** —
  `media_services.py:176-191`.
  Recibe: `workspace_dir`, `unit_of_work_factory` (legacy), `engine`
  (`LocalPhotoSelectionEngine | None`), `cleanup_temporary_files`,
  `cleanup_selected_photos`. Esto se traslada al `__init__` del use case
  con la mutación documentada en §2.

### Métodos de la clase a mover (TODOS los del paso 2)

| Rango                          | Símbolo                                      | Notas |
|--------------------------------|----------------------------------------------|-------|
| `media_services.py:193-201`    | `prepare_assets` (entrypoint)                | Mover. |
| `media_services.py:203-204`    | `select_photos` (alias del entrypoint)       | Mover (lo expone `PhotoSelectionService` Protocol). |
| `media_services.py:206-227`    | `cleanup_prepared_assets`                    | Llamado desde `media_pipeline.py:104,126`. Mover. |
| `media_services.py:229-233`    | `resolve_selected_dir` (staticmethod)        | **Crítico — bridge feature 10 lo importa** (`ingest_property_into_reel.py:765-771`). Ver §6 R1. Mover, exportar desde el nuevo módulo, y actualizar el import del use case ingest. |
| `media_services.py:235-243`    | `resolve_primary_image_from_dir` (staticmethod) | Idem R1. Mover, actualizar import. |
| `media_services.py:245-256`    | `_load_existing_assets`                      | Único caller: `prepare_assets:195`. Mover. |
| `media_services.py:258-324`    | `_prepare_curated_assets`                    | Único caller: `prepare_assets:201`. Mover. |
| `media_services.py:326-412`    | `_prepare_primary_only_assets`               | Único caller: `prepare_assets:200`. Mover. |

### Subclase trivial

- **`DefaultPhotoSelectionService(DefaultMediaPreparationService)`** —
  `media_services.py:415-416`. Subclase vacía (`pass`). Hoy nadie la
  instancia (`grep DefaultPhotoSelectionService` solo devuelve `media_services.py`
  y `default_services.py:5,18`). **Recomendación**: borrarla en feature 11.
  Verificar antes con `grep DefaultPhotoSelectionService` global; si solo
  aparece en re-exports de `default_services.py` y `__init__.py`, borrar.

### Engine de selección legacy

- **`LocalPhotoSelectionEngine`** — `media_services.py:115-138`.
  Wrapper delgado sobre `download_and_filter_property_images`. **Mover** al
  módulo nuevo del use case (o convertirlo en helper/adapter dentro del use
  case). El `feature_list` dice "el use case orquesta" → la lógica AI
  (`services/ai/photo_selection/`) ya está en sitio; el engine es la cola
  legacy que el use case puede consumir directamente o vía el wrapper.

### Helpers de módulo (free functions / constantes) que SOLO usa el step prepare

Hoy en `media_services.py`:

- **Imports** que usa SOLO el paso 2 (revisar la sección "Imports" abajo):
  `os`, `shutil`, `tempfile` (`tempfile` también lo usa
  `DefaultMediaPreparationService` indirectamente vía
  `_prepare_primary_only_assets` no — lo usa `DefaultMediaRenderer:447`,
  conservar). Tras la extracción, `shutil` y `os` siguen siendo necesarios
  por `FileSystemMediaPublisher` (paso 4) que sigue en `media_services.py`.

No hay free funcs de módulo exclusivas del step prepare (todos los helpers
están como métodos de clase o vienen de `services/media/property_media/`).

### Helpers compartidos con otros pasos (NO se mueven en feature 11)

Quedan en `media_services.py` para features 12/13/14:

- `media_services.py:67-68` `_now_iso` — usado por `FileSystemMediaPublisher`
  (paso 4, líneas `:615`, `:994`). **Conservar.**
- `media_services.py:71-78` `_relative_path_text` — usado por
  `FileSystemMediaPublisher` (paso 4). **Conservar.**
- `media_services.py:81-112` `_build_workflow_payload` — usado por
  `FileSystemMediaPublisher` y `CompositeMediaPublisher` (paso 4).
  **Conservar.**
- `media_services.py:141-172` `DefaultPropertyInfoService` (adapter
  delgado de feature 10). **Conservar.**
- `media_services.py:419-553` `DefaultMediaRenderer` + bug class shadow
  `DefaultMediaRenderer` redefinida vacía en `:552-553`. **Conservar**
  (feature 14 lo absorbe).
- `media_services.py:556-731` `FileSystemMediaPublisher` (+ class shadow
  `:730-731`). **Conservar** (feature 13).
- `media_services.py:734-1020` `CompositeMediaPublisher` (+ class shadow
  `:1019-1020`). **Conservar** (feature 13).

### Imports al tope de `media_services.py` que pasan al use case nuevo

Necesarios en `modules/reels/application/use_cases/prepare_reel_assets.py`:

```python
import logging
import os                                               # _prepare_primary_only_assets:357 (build_primary_image_filename usa Path)
import shutil                                           # rmtree, copy2 — varias rutas
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4                                  # NO — uuid4 lo usa solo el renderer; verificar antes
```

Imports de proyecto que migran:

- `from application.persistence import UnitOfWork` — usado por la firma del
  `unit_of_work_factory` legacy. Mantener mientras dure el bridge (ver §4).
- `from application.types import (PreparedMediaAssets, PropertyContext)` — el
  use case devuelve `PreparedMediaAssets` y recibe `PropertyContext`.
  Conservar el import; ambos siguen siendo legacy types.
- `from settings import DEFAULT_PHOTOS_TO_SELECT, SELECTED_PHOTOS_DIRNAME`
  (línea `:21`). `SELECTED_PHOTOS_DIRNAME` lo usa `resolve_selected_dir`;
  `DEFAULT_PHOTOS_TO_SELECT` lo usa `LocalPhotoSelectionEngine`. Mover ambos.
- `from core.media_cleanup import (DEFAULT_DELETE_SELECTED_PHOTOS,
  DEFAULT_DELETE_TEMPORARY_FILES, should_cleanup_raw_property_dir,
  should_cleanup_render_staging_dir, should_cleanup_selected_assets)`
  (`:22-28`). De estos, el step prepare usa: `DEFAULT_DELETE_SELECTED_PHOTOS`,
  `DEFAULT_DELETE_TEMPORARY_FILES`, `should_cleanup_raw_property_dir`,
  `should_cleanup_selected_assets`. `should_cleanup_render_staging_dir` lo
  usa `FileSystemMediaPublisher` (`:585`) — **conservar en
  `media_services.py`**.
- `from core.errors import PhotoFilteringError` (`:30`). Lo usa el step
  prepare (`:265, :268, :299, :341, :365`). El step publish también lo
  importa (`:33-34`: `SocialPublishingResultError`,
  `TransientSocialPublishingResultError`, `ValidationError`,
  `extract_error_details`); pero `PhotoFilteringError` solo lo usa prepare
  → **mover el símbolo, conservar el resto del import en `media_services.py`**.
- `from core.logging import build_log_context, format_console_block,
  format_context_line, format_detail_line` (`:36`). El step prepare usa:
  `build_log_context`, `format_console_block`, `format_detail_line`.
  `format_context_line` lo usa `CompositeMediaPublisher:888` — conservar
  en `media_services.py`. Mover los tres restantes.
- `from domain.properties.model import Property` (`:37`). Step prepare:
  parámetro de tipo en `resolve_selected_dir`, `LocalPhotoSelectionEngine.select_photos`.
  Step publish (`FileSystemMediaPublisher`, `CompositeMediaPublisher`) NO
  lo usa directamente (lee `context.property`). **Mover, conservar en
  `media_services.py` solo si feature 13 lo necesita** (tras la extracción
  `media_services.py` deja de tener `Property` directo — verificar al
  final).
- `from services.media.property_media import download_and_filter_property_images`
  (`:43`). Solo lo usa `LocalPhotoSelectionEngine.select_photos:132`. **Mover.**
- `from services.media.property_media.downloads import download_image,
  download_images_to_directory` (`:44`). `download_image` lo usa
  `_prepare_primary_only_assets:358`; `download_images_to_directory` no se
  invoca desde `media_services.py` (lo usa `selection.py` internamente).
  **Mover ambos** (consolidar cuáles usa el use case).
- `from services.media.property_media.filesystem import list_image_files,
  prepare_property_directories` (`:45`). `list_image_files` lo usan
  `resolve_primary_image_from_dir`, `_load_existing_assets`,
  `_prepare_curated_assets`. `prepare_property_directories` lo usa
  `_prepare_primary_only_assets`. **Mover ambos.**
- `from services.media.property_media.naming import PRIMARY_IMAGE_STEM,
  build_primary_image_filename` (`:46`). Los usan
  `resolve_primary_image_from_dir` y `_prepare_primary_only_assets`. **Mover.**

Imports que NO usa el step prepare (siguen en `media_services.py` para los
otros pasos):

- `from datetime import datetime, timezone` — `_now_iso`.
- `from application.pipeline.content_generation import ContentGenerator` —
  lo recibe `DefaultPropertyInfoService` (adapter feature 10). Conservar.
- `from services.media.reel_rendering import (...)` — paso render.
- `from services.media.reel_rendering.poster import (...)` — pasos
  render/publish.
- `from services.media.reel_rendering.preparation import
  prepare_reel_render_assets` — paso render.
- `from services.media.reel_rendering.runtime import build_local_selected_slides`
  — paso render.
- `from services.publishing.social_delivery import (...)` — paso publish.
- `from settings import REVIEW_WORKFLOW_ENABLED` — `CompositeMediaPublisher`.
- `from repositories.stores.media_revision_store import MediaRevisionRecord`
  — paso publish.
- `from repositories.stores.pipeline_state_store import PropertyPipelineState`
  — feature 10 lo eliminó; verificar `media_services.py:42` — sigue ahí
  porque... revisar. **Si tras feature 10 nadie lo usa en `media_services.py`,
  feature 11 puede borrar la línea** (low risk). Tras revisar el archivo
  actual: el import sigue (`media_services.py:42`) pero ya no hay uso del
  símbolo en este archivo (feature 10 lo movió). **Borrar import en feature 11.**
- `from modules.reels.application.use_cases.ingest_property_into_reel import
  IngestPropertyIntoReelUseCase` (`:38-40`) — lo usa
  `DefaultPropertyInfoService`. Conservar.

---

## 2. Dependencias del servicio (`DefaultMediaPreparationService.__init__`)

Lo que recibe hoy en `__init__` (`media_services.py:176-191`):

| Parámetro                          | Origen runtime                                  | Equivalente moderno |
|------------------------------------|--------------------------------------------------|---------------------|
| `workspace_dir`                    | `WORKSPACE_DIR` en bootstrap                     | Igual; lo recibe el use case en `__init__`. |
| `unit_of_work_factory: Callable[[], UnitOfWork]` (legacy) | `build_runtime_unit_of_work_factory(workspace_dir, database_locator=...)` que construye `repositories/postgres/uow.DatabaseUnitOfWork` | **Adaptar**. El use case nuevo abre su propio `shared.db.DatabaseUnitOfWork(database_locator, base_dir=workspace_dir)` para escribir en `uow.catalog.properties.upsert_property` + `uow.catalog.images.replace_images` + `uow.reels.states.update_workflow_state`. El `unit_of_work_factory` legacy se acepta en el adapter (firma estable para `application/bootstrap/runtime.py`) y se ignora con `del unit_of_work_factory` (mismo patrón que feature 10). |
| `engine: LocalPhotoSelectionEngine | None` | bootstrap no lo pasa (default `None`) → se construye uno con `cleanup_temporary_files` | El use case construye su engine internamente; el parámetro `engine` se conserva como inyectable para tests. |
| `cleanup_temporary_files: bool`    | `PROPERTY_MEDIA_DELETE_TEMPORARY_FILES`         | Igual. |
| `cleanup_selected_photos: bool`    | `PROPERTY_MEDIA_DELETE_SELECTED_PHOTOS`         | Igual. |

Operaciones de DB que ejecuta hoy `prepare_assets` y sus métodos privados
(dentro del bloque `with self.unit_of_work_factory() as unit_of_work` de
`_prepare_curated_assets:279-294` y `_prepare_primary_only_assets:380-395`):

1. `unit_of_work.property_repository.save_property_images(property_item,
   selected_dir, downloaded_images, agency_id=..., wordpress_source_id=...,
   site_id=...)` — actualiza la fila de `properties` y reemplaza las filas
   en `property_images`. Implementación legacy en
   `repositories/stores/property_store.py:413-434` que delega en
   `_save_property_record:206-229` (upsert + `_replace_property_images`).
2. `unit_of_work.pipeline_state_repository.update_workflow_state(
   agency_id=..., wordpress_source_id=..., site_id=..., source_property_id=...,
   workflow_state="assets_prepared")`.

---

## 3. Mapeo a UoW moderno (`shared/db/uow.py`)

Repos modernos disponibles (vía `uow.<bc>.<repo>`):

| Operación legacy                                                                              | Reemplazo moderno (firma exacta) |
|------------------------------------------------------------------------------------------------|----------------------------------|
| `unit_of_work.property_repository.save_property_images(property_item, selected_dir, downloaded_images, agency_id=..., wordpress_source_id=..., site_id=...)` | **Combinar dos repos modernos**: `uow.catalog.properties.upsert_property(record: dict) -> int` (`property_repository.py:118-153`) + `uow.catalog.images.replace_images(record_id, downloaded_images: Iterable[tuple[int, str, Path \| str \| None]])` (`property_repository.py:190-222`). El `record` se construye igual que en feature 10 (`_build_property_record` helper en `ingest_property_into_reel.py:219-240`) — **el implementer puede importar/reusar ese helper o duplicarlo según prefiera**. Ojo: feature 10 ya hizo el upsert del `Property` durante el ingest, así que **puede que `prepare_assets` solo necesite la parte de `replace_images`**. Verificar (ver §6 R-doble-upsert). |
| `unit_of_work.pipeline_state_repository.update_workflow_state(agency_id=..., wordpress_source_id=..., site_id=..., source_property_id=..., workflow_state="assets_prepared")` | `uow.reels.states.update_workflow_state(agency_id=..., ingestion_source_id=..., external_source_id=..., source_property_id=..., workflow_state="assets_prepared", current_revision_id=None)` (`reel_state_repository.py:233-280`). **Mismos parámetros**, renombrados: `wordpress_source_id` → `ingestion_source_id`, `site_id` → `external_source_id`. |

### Mapping `record_id` para `replace_images`

`replace_images` necesita un `record_id: int` (PK de `properties`). Dos opciones:

1. **Idempotente**: el use case llama `uow.catalog.properties.upsert_property(record)`
   primero (que devuelve `record_id`) y luego `uow.catalog.images.replace_images(record_id, ...)`.
   Esto re-upserta lo que feature 10 ya escribió, pero el ON CONFLICT lo
   hace seguro. Es lo que hace el legacy `save_property_images`.
2. **Lookup**: añadir un método al moderno `PropertyRepository`,
   `get_record_id(*, external_source_id, source_property_id) -> int`. **No
   existe hoy**; introducirlo cruza el alcance del feature 11.

**Recomendación**: opción 1 (idempotent re-upsert) — replica la semántica
del legacy y no requiere nuevos métodos en el repo moderno. El implementer
puede reusar `_build_property_record` del use case feature 10.

---

## 4. Call sites externos y bridge worker

### Call sites de `DefaultMediaPreparationService`

| Archivo                                                | Líneas         | Acción tras feature 11 |
|--------------------------------------------------------|----------------|-------------------------|
| `application/bootstrap/runtime.py`                     | `:9` (import), `:111-116` (instanciación dentro de `build_default_property_media_pipeline`) | **Cambia idéntico al patrón feature 10**: `DefaultMediaPreparationService` queda como adapter delgado en `media_services.py` que delega al `PrepareReelAssetsUseCase`. Bootstrap **no cambia**. |
| `application/bootstrap/__init__.py`                    | `:9` (import), `:111-116` | Idéntico al anterior (byte-a-byte iguales según diff feature 10; sigue siéndolo). |
| `application/pipeline/default_services.py`             | `:4, :17`       | Solo re-exporta. Sin cambio funcional. |
| `application/pipeline/__init__.py`                     | re-export       | Sin cambio funcional. |
| `application/pipeline/media_services.py`               | `:175-412`      | **Hay que reducir LoC** — clase queda como adapter delgado (~30 LoC). |
| `application/pipeline/media_pipeline.py`               | `:87, :126`     | Llama a `media_preparation_service.prepare_assets(context)` y `.cleanup_prepared_assets(...)`. **Sin cambios** en feature 11. |
| `application/pipeline/interfaces.py`                   | `:34-43, :46-48` | Protocols `MediaPreparationService` y `PhotoSelectionService`. **Sin cambios** — el adapter cumple ambos protocolos. |

### Llamadas externas a `prepare_assets` / `select_photos`

- `application/pipeline/media_pipeline.py:87`:
  `prepared_assets = self.media_preparation_service.prepare_assets(context)`.
- `application/pipeline/media_pipeline.py:126`:
  `self.media_preparation_service.cleanup_prepared_assets(context, prepared_assets)`.
- `select_photos` (alias) — `grep` solo lo encuentra como definición y en
  el Protocol (`interfaces.py:47`); ningún caller real. Conservar el
  alias por compatibilidad con `PhotoSelectionService` Protocol o borrarlo
  si feature 11 quiere limpiar (recomendación: **borrarlo**, junto con la
  subclase `DefaultPhotoSelectionService`, ver §1).

### Cierre del cruce con feature 10 (R1)

`modules/reels/application/use_cases/ingest_property_into_reel.py:765-772`
hace `from application.pipeline.media_services import DefaultMediaPreparationService`
para llamar a `resolve_selected_dir` y `resolve_primary_image_from_dir`
(staticmethods).

Tras feature 11, esos staticmethods viven en
`modules/reels/application/use_cases/prepare_reel_assets.py` (clase
`PrepareReelAssetsUseCase` o como helpers de módulo del mismo archivo).
**Acción concreta**: el implementer cambia el import en
`ingest_property_into_reel.py:765` por:

```python
from modules.reels.application.use_cases.prepare_reel_assets import (
    PrepareReelAssetsUseCase,
)
```

y la llamada por `PrepareReelAssetsUseCase.resolve_selected_dir(...)` /
`PrepareReelAssetsUseCase.resolve_primary_image_from_dir(...)`.

**Nota**: el comentario "Bridge import: feature 11 absorbs ..." en
`ingest_property_into_reel.py:762-764` debe borrarse (la deuda se cancela).
El helper `_state_for_legacy_helpers` (`ingest_property_into_reel.py:939-949`)
puede simplificarse: `resolve_selected_dir` solo lee `state.selected_image_folder`
del argumento `state`, y `state` ahora puede ser directamente el `ReelState`
moderno si la signatura del staticmethod se generaliza para aceptar
`state.selected_image_folder` o un objeto con ese attribute. Como el atributo
es idéntico en `ReelState` y en el `SimpleNamespace`, **el implementer
puede pasar el `ReelState` directamente** y eliminar el helper
`_state_for_legacy_helpers`. Recomendado.

### Bridge worker

`apps/worker/runtime.py:262-274` registra el handler `reel_publish` con
`reel_pipeline.handle` (`modules/reels/application/orchestrator.py`),
que hace lazy-import de `application.bootstrap.runtime.build_default_job_handler`.
**Sin cambios** en feature 11 — sigue intacto, igual que en feature 10.

### Materialización del adapter delgado en `media_services.py`

Patrón exacto del feature 10 (verificado en `media_services.py:141-172`).
Tras feature 11:

```python
class DefaultMediaPreparationService:
    """Bridge adapter — delegates prepare_assets to the modern use case."""

    def __init__(
        self,
        workspace_dir: str | Path,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        engine: LocalPhotoSelectionEngine | None = None,
        cleanup_temporary_files: bool = DEFAULT_DELETE_TEMPORARY_FILES,
        cleanup_selected_photos: bool = DEFAULT_DELETE_SELECTED_PHOTOS,
    ) -> None:
        del unit_of_work_factory  # legacy bootstrap arg.
        self._use_case = PrepareReelAssetsUseCase(
            workspace_dir=workspace_dir,
            engine=engine,
            cleanup_temporary_files=cleanup_temporary_files,
            cleanup_selected_photos=cleanup_selected_photos,
        )

    def prepare_assets(self, context):
        return self._use_case.execute(context)

    def cleanup_prepared_assets(self, context, prepared_assets):
        return self._use_case.cleanup(context, prepared_assets)
```

`LocalPhotoSelectionEngine` y los staticmethods `resolve_selected_dir` /
`resolve_primary_image_from_dir` se exportan **desde el módulo nuevo**;
si algún consumidor externo los importa de `media_services.py`, ese path
debe seguir resolviendo — la opción más limpia es re-exportarlos en
`media_services.py` (`from modules.reels.application.use_cases.prepare_reel_assets
import LocalPhotoSelectionEngine` etc.).

---

## 5. Tests existentes

### `grep prepare_assets|DefaultMediaPreparationService|LocalPhotoSelectionEngine` en `tests/`

Resultado: **0 hits** (verificado: `Grep` global devuelve solo
`progress/`, `application/pipeline/media_services.py`, los archivos
`bootstrap`, `default_services.py`, `media_pipeline.py`, `interfaces.py`,
y los reportes de feature 10).

Tests "de cerca":

- `tests/test_gemini_photo_selection.py` — cubre `download_and_filter_property_images`
  (la función legacy que envuelve `LocalPhotoSelectionEngine`). No cubre
  `prepare_assets` ni el step prepare en su conjunto. **Conservar; no se
  toca**.
- `tests/integration/test_worker_runtime.py:32-94` — registra un handler
  `reel_publish` mock (`lambda job: ...`); **no** ejerce el pipeline real.
- `tests/integration/ingestion/test_wordpress_webhook_flow.py:31-159` —
  cubre el endpoint webhook que **encola** el job; nunca ejecuta el handler.
- Otros tests de reels (`tests/unit/reels/`) son sobre admin use cases.

**Conclusión**: feature 11 **suma** los dos tests nuevos del acceptance
sin migrar/adaptar nada existente.

### Crear (acceptance feature 11)

- `tests/unit/reels/test_prepare_reel_assets.py` — con stubs del cliente
  HTTP (descarga de imágenes).
  Tests sugeridos:
  1. **Camino feliz curated**: contexto con `delivery_plan.uses_primary_image_only=False`
     y `requires_asset_preparation=True`, monkeypatch
     `download_and_filter_property_images` para devolver
     `(selected_dir, downloaded_images)` simulados; verifica que
     `uow.catalog.properties.upsert_property` y
     `uow.catalog.images.replace_images` reciben los argumentos esperados,
     y que `uow.reels.states.update_workflow_state` se llama con
     `workflow_state="assets_prepared"`.
  2. **Camino feliz primary-only**: contexto con `delivery_plan.uses_primary_image_only=True`
     y `requires_asset_preparation=True`, monkeypatch `download_image` para
     escribir bytes en la ruta esperada; verifica que se descarga el
     featured image, se copia a `selected_dir`, y los upserts ocurren.
  3. **No requiere preparación**: `requires_asset_preparation=False` y
     directorio de selected con archivos previos → devuelve
     `_load_existing_assets` sin descargar.
  4. **Error de descarga curated**: monkeypatch
     `download_and_filter_property_images` para lanzar `Exception` →
     se eleva como `PhotoFilteringError(code="CURATED_ASSET_PREPARATION_FAILED")`.
  5. **Primary image faltante**: `property_item.featured_image_url=""`
     y `image_urls=()` → `PhotoFilteringError(code="PRIMARY_IMAGE_MISSING")`.
  6. **`cleanup_prepared_assets`**: con `cleanup_selected_photos=True`,
     verifica que el directorio se borra; con `False`, verifica que se
     conserva.

  Stubs UoW: `_StubProperties` (con `upsert_property`),
  `_StubImages` (con `replace_images`), `_StubReelStates` (con
  `update_workflow_state`). Patrón consistente con
  `tests/unit/reels/_uow_stubs.py` — **añadir `replace_images` al
  `StubImages` existente** (`_uow_stubs.py:58-66` solo expone
  `list_for_property`).

- `tests/integration/reels/test_prepare_reel_assets_flow.py` —
  `temporary_postgres_schema` + `seed_tenant` + `temporary_workspace`,
  ejecuta primero el use case ingest (para que la fila en `reels` y
  `properties` exista) y luego el use case prepare (con monkeypatch del
  cliente HTTP / `download_image` para no salir a internet). Asserta:
  - Fila en `reels` con `workflow_state='assets_prepared'`.
  - Filas en `property_images` con las imágenes downloaded (al menos 1).
  - El directorio físico `<workspace>/property_media/<site>/<slug>/selected_photos/`
    existe y contiene el primary o el set curated.

### Adaptar / migrar

Probablemente ninguno. Si feature 10 modificó `tests/unit/reels/_uow_stubs.py`
para `_StubProperties` con `upsert_property`, feature 11 añade
`replace_images` a `_StubImages` (cambio aditivo, no rompe los tests
existentes).

---

## 6. Riesgos / acoplamientos

### R1 — Cierre del cruce con feature 10 (`_should_prepare_assets`)

Documentado en §4. **Acción del implementer**: tras crear
`PrepareReelAssetsUseCase` con los staticmethods `resolve_selected_dir` y
`resolve_primary_image_from_dir`, actualizar
`modules/reels/application/use_cases/ingest_property_into_reel.py:765-772`
para importar del módulo nuevo y, opcionalmente, eliminar el helper
`_state_for_legacy_helpers` (`:939-949`). Esto **es código fuera del
alcance estricto de feature 11** (toca un archivo del módulo reels que ya
fue creado por feature 10), pero es la única forma de cerrar la deuda
limpiamente. **Sí está dentro del alcance**: feature 10 lo dejó
explícitamente como deuda para feature 11.

### R2 — Cliente HTTP / descargas

El step prepare descarga imágenes vía:

- `services.media.property_media.downloads.download_image(url, destination)`
  (`downloads.py:18-22`) — `urlopen(build_request(url), timeout=...)`.
- `services.media.property_media.downloads.download_images_to_directory(...)`
  (idem) — bucle sobre `property_item.image_urls`.
- `services.media.property_media.selection.download_and_filter_property_images(...)`
  (envoltorio que también llama a Gemini).

**No hay abstracción HTTP inyectable hoy** — los tests existentes
(`tests/test_gemini_photo_selection.py`) monkeypatchean
`urllib.request.urlopen` o usan `httpx.MockTransport`. Para feature 11:

- En el unit test, **monkeypatchear `download_image` y
  `download_and_filter_property_images`** en el módulo nuevo:
  ```python
  monkeypatch.setattr(
      "modules.reels.application.use_cases.prepare_reel_assets.download_image",
      fake_download,
  )
  ```
  Esto evita salir a la red sin requerir un nuevo Protocol.
- En el integration test, **monkeypatch idem** + verificar la fila DB.

**Recomendación**: NO introducir un `HttpClient` Protocol en feature 11 —
sería un cambio de diseño cruzado. Mantener el patrón de monkeypatch.
El acceptance dice "con stubs del cliente HTTP" → se interpreta como
"stubs de las funciones de descarga".

### R3 — Filesystem y normalización

`prepare_assets` escribe a `workspace_dir` (raíz del tenant), específicamente
a:

- `<workspace>/property_media_raw/<site>/<slug>/raw_photos/` (descarga raw).
- `<workspace>/property_media/<site>/<slug>/selected_photos/` (post-selección).
- `<workspace>/property_media/<site>/<slug>/_seltmp_<hex>/` (temporal).
- Featured image: `<workspace>/property_media/<site>/<slug>/_tmp_<...>` →
  movido a `selected_photos/featured_*`.

No hay resize ni transformación de bitmap (lo hace `services/media/reel_rendering/`
en el step render). La "normalización" del paso 2 es organizativa
(filename canónico vía `build_primary_image_filename` y `build_selected_image_filename`).

### R4 — Photo selection: ¿`LocalPhotoSelectionEngine` legacy o nuevo `modules/rendering/infrastructure/ai_photo_selection/`?

El directorio `modules/rendering/infrastructure/ai_photo_selection/` solo
contiene `__init__.py` con docstring `"AI photo-selection adapter."` —
**está vacío**. La lógica AI real vive en `services/ai/photo_selection/`
(legacy) y se invoca desde `services/media/property_media/selection.py:_select_photo_paths:244`
(`classify_property_images(...)`).

El feature_list dice "La lógica pura de selección AI ya vive en
`modules/rendering/infrastructure/ai_photo_selection/` — el use case
orquesta." → **Discrepancia D1**: la carpeta existe pero está vacía. Ver
§8.

**Acción recomendada**: el use case `PrepareReelAssetsUseCase` **orquesta
sobre el engine legacy `LocalPhotoSelectionEngine`** que envuelve
`download_and_filter_property_images` (que internamente llama a Gemini vía
`services/ai/photo_selection`). NO introducir un wrapper nuevo en
`modules/rendering/infrastructure/ai_photo_selection/` en feature 11 —
eso es trabajo de feature 14/15. La carpeta vacía se queda vacía hasta
entonces.

### R5 — Doble UoW durante el bridge

Mismo issue documentado en feature 10 (R3). El use case nuevo abre un
`shared.db.DatabaseUnitOfWork` propio en `execute(...)`; el legacy
`PropertyMediaPipeline.run_job` ya commitea por servicio. Atomicidad
por-step se conserva, no la atomicidad end-to-end. **Sin acción** —
feature 14 lo elimina.

### R6 — Doble upsert en `properties` (feature 10 + feature 11)

Feature 10 ya hace `uow.catalog.properties.upsert_property(record)` durante
el ingest. Feature 11 hoy (legacy) hace `save_property_images` que
internamente hace **otro upsert** + `replace_images`. Tras feature 11,
sería un doble upsert dentro del mismo job (ingest + prepare).

**Acción recomendada**: el use case prepare hace solo `upsert_property` +
`replace_images` (idempotente; el ON CONFLICT no rompe nada). Ya es lo que
hace el legacy. **Sin acción extra** salvo documentar.

Una optimización futura (feature 14) sería que prepare solo haga
`replace_images` y use un nuevo `PropertyRepository.get_record_id(...)`,
pero eso queda fuera del alcance estricto.

### R7 — `Path` import en `media_services.py` post-feature-11

Tras eliminar el step prepare, el archivo todavía necesita `Path` (lo usa
`_now_iso`? no — solo `DefaultMediaRenderer:421`, `FileSystemMediaPublisher:572`
etc.). **Conservar el import**.

### R8 — Settings y constantes que quedan huérfanas en `media_services.py`

Tras feature 11, en `media_services.py`:
- `SELECTED_PHOTOS_DIRNAME` ya no se usa → quitar del import.
- `DEFAULT_PHOTOS_TO_SELECT` ya no se usa → quitar.
- `PROPERTY_MEDIA_DELETE_SELECTED_PHOTOS` (no se importa hoy en
  `media_services.py`; se pasa al `__init__` desde bootstrap) — sin acción.
- `should_cleanup_raw_property_dir`, `should_cleanup_selected_assets` →
  ya no se usan → quitar.
- `PhotoFilteringError` ya no se usa → quitar (solo step prepare).
- `format_console_block`, `format_detail_line` siguen usándose por los
  loggers de los pasos render/publish. Conservar.
- `build_log_context` lo usan los pasos render/publish también
  (`media_services.py:271, :302, :345, :369, :676` — verificar después de
  la edición qué queda).

El implementer hace un `pyflakes` o equivalente al final para limpiar.

### R9 — `LocalPhotoSelectionEngine` exportada desde `media_services.py`

`application/pipeline/default_services.py:11, :24` re-exporta
`LocalPhotoSelectionEngine`. Si feature 11 la mueve a
`modules/reels/application/use_cases/prepare_reel_assets.py`, el re-export
debe cambiar a:

```python
from modules.reels.application.use_cases.prepare_reel_assets import (
    LocalPhotoSelectionEngine,
)
```

o se conserva un re-export desde `media_services.py` por compatibilidad
(para no tocar `default_services.py`). **Recomendación**: re-exportar
desde `media_services.py` (`from modules.reels.application.use_cases.prepare_reel_assets
import LocalPhotoSelectionEngine`) para no propagar cambios.

### R10 — `SiteStorageLayout.workspace_dir` vs `context.workspace_dir`

`PropertyContext` tiene `workspace_dir` (top-level) y
`storage_paths.workspace_dir` (vía `SiteStorageLayout`). Los métodos
extraídos usan ambos: `context.storage_paths.raw_images_root`,
`context.storage_paths.filtered_images_root`,
`context.storage_paths.workspace_dir`. La extracción no cambia esa
semántica.

---

## 7. Plan de implementación recomendado

### Archivos a crear

1. **`modules/reels/application/use_cases/prepare_reel_assets.py`**
   (~400-500 LoC estimado). Contiene:
   - Clase **`LocalPhotoSelectionEngine`** (ex `media_services.py:115-138`)
     o un wrapper simplificado.
   - Clase **`PrepareReelAssetsUseCase`** con:
     - `__init__(workspace_dir, *, engine=None, cleanup_temporary_files=...,
       cleanup_selected_photos=..., database_locator=None)`. (Decisión:
       sin `unit_of_work_factory` legacy — coherente con el cambio del
       implementer feature 10.)
     - `execute(context: PropertyContext, *, uow: DatabaseUnitOfWork | None = None)
       -> PreparedMediaAssets` (renombrado del entrypoint
       `prepare_assets`; el adapter en `media_services.py` mantiene el
       nombre histórico).
     - `cleanup(context, prepared_assets) -> None` (ex `cleanup_prepared_assets`).
     - Staticmethods públicos `resolve_selected_dir` y
       `resolve_primary_image_from_dir` (los necesita feature 10).
     - Métodos privados migrados: `_load_existing_assets`,
       `_prepare_curated_assets`, `_prepare_primary_only_assets`.
   - Re-export en `modules/reels/application/use_cases/__init__.py`.

2. **`tests/unit/reels/test_prepare_reel_assets.py`** — tests listados en §5.

3. **`tests/integration/reels/test_prepare_reel_assets_flow.py`** —
   integration con `temporary_postgres_schema` + `seed_tenant` +
   `temporary_workspace` + monkeypatch HTTP.

### Archivos a modificar

1. **`application/pipeline/media_services.py`**:
   - Borrar rangos del paso 2 listados en §1: `:115-138`
     (`LocalPhotoSelectionEngine` se mueve), `:175-412`
     (`DefaultMediaPreparationService` cuerpo) y `:415-416`
     (`DefaultPhotoSelectionService`).
   - Insertar adapter delgado `DefaultMediaPreparationService` (~30-35
     LoC, patrón feature 10).
   - Re-exportar `LocalPhotoSelectionEngine` (para compat con
     `default_services.py`).
   - Limpiar imports huérfanos (§R8).
   - Resultado esperado: `media_services.py` baja de **1034 → ~770-800 LoC**
     (~250-260 LoC borrados; los rangos 115-138 = 24 + 175-412 = 238 +
     415-416 = 2 → ~264 LoC, pero el adapter añade ~35 → neto ~230).

2. **`modules/reels/application/use_cases/ingest_property_into_reel.py`**:
   - Cambiar el import de `:765` para usar
     `modules.reels.application.use_cases.prepare_reel_assets` (cierra R1).
   - Borrar el comentario `:762-764` ("feature 11 absorbs ...").
   - Opcionalmente, eliminar `_state_for_legacy_helpers` (`:939-949`) si
     se simplifica `_should_prepare_assets` para pasar el `ReelState`
     directamente (`resolve_selected_dir` solo lee
     `state.selected_image_folder`).

3. **`modules/reels/application/use_cases/__init__.py`**:
   - Añadir re-export de `PrepareReelAssetsUseCase`.

4. **`tests/unit/reels/_uow_stubs.py`**:
   - Añadir método `replace_images(record_id, downloaded_images)` a
     `StubImages` y método `update_workflow_state(...)` ya existe en
     `StubReelStates` (`:40-41`); verificar firma.

### Archivos a borrar

Ninguno en este alcance. (`DefaultPhotoSelectionService` se borra dentro
de `media_services.py` como parte de la edición, no es un archivo
separado.)

### Archivos NO modificados

- `application/bootstrap/runtime.py` y `__init__.py`: la firma del
  adapter `DefaultMediaPreparationService.__init__` se mantiene exacta.
- `application/pipeline/media_pipeline.py`: sigue llamando a
  `prepare_assets`/`cleanup_prepared_assets` del adapter.
- `application/pipeline/interfaces.py`: Protocols intactos.
- `application/pipeline/default_services.py` y `__init__.py`: re-exports
  válidos vía el adapter.

### Orden sugerido

1. Implementer crea `modules/reels/application/use_cases/prepare_reel_assets.py`
   con `LocalPhotoSelectionEngine`, `PrepareReelAssetsUseCase` y los
   staticmethods públicos.
2. Re-export en `modules/reels/application/use_cases/__init__.py`.
3. Modifica `ingest_property_into_reel.py` para importar del módulo nuevo
   (cierra R1).
4. Crea `tests/unit/reels/test_prepare_reel_assets.py` y los hace pasar
   (`pytest -q tests/unit/reels/test_prepare_reel_assets.py`).
5. Crea `tests/integration/reels/test_prepare_reel_assets_flow.py` y lo
   hace pasar.
6. Modifica `application/pipeline/media_services.py`: borra el cuerpo del
   paso 2, inserta el adapter delgado, limpia imports.
7. Verifica que `tests/unit/reels/test_ingest_property_into_reel.py` y
   `tests/integration/reels/test_ingest_property_into_reel_flow.py`
   siguen verdes (el cambio del import en `_should_prepare_assets` no
   rompe nada porque las firmas de los staticmethods son idénticas).
8. Corre suite completa (`./init.sh`). Baseline 380 (post-feature-10) +
   ≥4 tests nuevos = **≥ 384 verdes**.

### LoC esperado de `media_services.py` post-feature-11

- Movido al use case nuevo: **~264 LoC** (115-138 + 175-412 + 415-416).
- Adapter delgado introducido: **~35 LoC**.
- Imports/limpieza: **-5 LoC** (líneas que dejan de necesitarse).
- Reducción neta: **~230 LoC**.
- `media_services.py` post-feature: **~800-810 LoC** (de 1034). Bajará
  más en features 13/14.

---

## 8. Discrepancias detectadas

### D1 — `modules/rendering/infrastructure/ai_photo_selection/` está vacío

`feature_list.json` #11 dice "La lógica pura de selección AI ya vive en
`modules/rendering/infrastructure/ai_photo_selection/`". En realidad ese
directorio **solo contiene `__init__.py` con docstring "AI photo-selection
adapter."** y nada más. La lógica AI vive en `services/ai/photo_selection/`
(legacy).

**Recomendación**: el use case orquesta sobre el engine legacy
`LocalPhotoSelectionEngine` (ahora en el módulo nuevo) que internamente
usa `services/media/property_media/selection.py:download_and_filter_property_images`,
que invoca Gemini vía `services/ai/photo_selection`. **No mover la lógica
AI** en feature 11 — eso es alcance de feature 14/15. La carpeta vacía
sigue vacía.

### D2 — "Stubs del cliente HTTP" no implica un Protocol nuevo

El acceptance dice "tests/unit/reels/test_prepare_reel_assets.py (con
stubs del cliente HTTP)". El código legacy NO tiene un `HttpClient`
Protocol — usa `urllib.request.urlopen` directamente vía
`services/media/property_media/downloads.download_image`. **El "stub del
cliente HTTP" se materializa como `monkeypatch` de `download_image` y
`download_and_filter_property_images`** dentro del módulo del use case
(donde se importan), no como Protocol nuevo.

### D3 — Naming del entrypoint del use case (`execute` vs `prepare_assets`)

`feature_list.json` #11 no especifica el nombre del método público del use
case. Phase 2 operating rules + feature 10 establecen el patrón
`execute(...)`. El adapter `DefaultMediaPreparationService` mantiene
`prepare_assets` y `cleanup_prepared_assets` para no romper el Protocol
`MediaPreparationService` (`interfaces.py:34-43`). **Recomendación**: use
case usa `execute(context)` y `cleanup(context, prepared_assets)`; adapter
delegan al use case con los nombres del Protocol.

### D4 — `DefaultPhotoSelectionService` no tiene callers

Subclase vacía en `media_services.py:415-416`. **Sin call sites** (verificar
con `grep DefaultPhotoSelectionService` global — solo aparece en re-exports
de `default_services.py:5,18` y `__init__.py`). El `PhotoSelectionService`
Protocol (`interfaces.py:46-48`) tampoco tiene call sites reales (solo es
un Protocol genérico).

**Recomendación**: borrar la subclase y los re-exports. Si feature_list lo
exige (no lo hace explícitamente), conservar como `pass` adapter.

### D5 — Imports legacy huérfanos en `media_services.py` post-feature-10

El archivo actual aún importa
`from repositories.stores.pipeline_state_store import PropertyPipelineState`
(`media_services.py:42`) que feature 10 dejó de usar (movido al use case).
Y `from application.persistence import UnitOfWork` (`:13`) sigue siendo
usado por las firmas de `unit_of_work_factory` de los pasos 2/3/4 —
conservar.

`PropertyPipelineState` ya no se usa en `media_services.py` (feature 10 lo
movió al use case ingest). **Acción para feature 11**: borrar también ese
import en la limpieza.

### D6 — `application/bootstrap/{runtime.py,__init__.py}` siguen byte-a-byte iguales

Documentado en feature 10 D3. Feature 11 mantiene la firma del adapter
`DefaultMediaPreparationService` exacta, así que ambos archivos siguen
funcionando sin cambios.

---

**Fin del informe.**
