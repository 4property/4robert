# Impl — Feature 11 `reels_use_case_prepare_reel_assets`

> Extracción del paso 2 del pipeline (preparación de assets) desde
> `application/pipeline/media_services.py` hacia
> `modules/reels/application/use_cases/prepare_reel_assets.py` con clase
> `PrepareReelAssetsUseCase`. Conforme al plan del explorer.

---

## 1. Archivos creados / modificados / borrados

### Creados

| Archivo | LoC | Tipo |
|---------|-----|------|
| `modules/reels/application/use_cases/prepare_reel_assets.py` | 447 | Use case + `LocalPhotoSelectionEngine` + helpers privados (mover el contenido del paso 2 del legacy). |
| `tests/unit/reels/test_prepare_reel_assets.py` | 399 | Unit (curated path, primary-only path, short-circuit por `requires_asset_preparation=False`, errores `CURATED_ASSET_PREPARATION_FAILED` y `PRIMARY_IMAGE_MISSING`, cleanup on/off). 7 tests. |
| `tests/integration/reels/test_prepare_reel_assets_flow.py` | 169 | Integration (`temporary_postgres_schema` + `seed_tenant`, ingest → prepare con monkeypatch del engine; valida `reels.workflow_state='assets_prepared'`, `property_images` rows, directorio físico). 1 test. |

### Modificados

| Archivo | Cambio |
|---------|--------|
| `application/pipeline/media_services.py` | 1034 → **802 LoC** (232 LoC eliminados). Borrado: `LocalPhotoSelectionEngine` (115-138, 24 LoC), cuerpo de `DefaultMediaPreparationService` (175-412, 238 LoC), `DefaultPhotoSelectionService` (415-416, 2 LoC). Insertado adapter delgado nuevo (~46 LoC con docstring) que delega a `PrepareReelAssetsUseCase`. Imports limpiados (`SELECTED_PHOTOS_DIRNAME`, `DEFAULT_PHOTOS_TO_SELECT`, `should_cleanup_raw_property_dir`, `should_cleanup_selected_assets`, `PhotoFilteringError`, `build_log_context`, `PropertyPipelineState`, `Property`, `download_image`, `download_and_filter_property_images`, `download_images_to_directory`, `list_image_files`, `prepare_property_directories`, `PRIMARY_IMAGE_STEM`, `build_primary_image_filename`). Re-export de `LocalPhotoSelectionEngine` desde el módulo nuevo (R9). `__all__` limpiado: drop dupes y `DefaultPhotoSelectionService`. |
| `application/pipeline/default_services.py` | Re-export ajustado: drop `DefaultPhotoSelectionService` (D4) y dupes. Re-exporta `LocalPhotoSelectionEngine` vía `media_services.py` (donde se re-exporta del módulo nuevo). |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | Cierra R1: `_should_prepare_assets` ahora importa `PrepareReelAssetsUseCase` de `modules.reels.application.use_cases.prepare_reel_assets` (lazy import dentro del método para evitar ciclo, mismo patrón que el bridge anterior). Borrado el comentario "feature 11 absorbs ...". El staticmethod `resolve_selected_dir` del nuevo módulo acepta `state: Any | None` con `getattr(state, "selected_image_folder", "")`, así que se le pasa el `ReelState` moderno directamente. **Eliminado el helper `_state_for_legacy_helpers`** que ya no es necesario (R1 opcional aplicado). |
| `modules/reels/application/use_cases/__init__.py` | Re-export de `PrepareReelAssetsUseCase`. |
| `feature_list.json` | Feature 11 status `pending` → `in_progress`. |
| `progress/current.md` | Bitácora actualizada. |

### Borrados

Ninguno físicamente. Dentro de `media_services.py` se borraron 3 clases (LocalPhotoSelectionEngine + DefaultMediaPreparationService cuerpo + DefaultPhotoSelectionService) y `default_services.py` perdió su re-export de `DefaultPhotoSelectionService` — no eran archivos separados.

---

## 2. Líneas eliminadas de `application/pipeline/media_services.py`

Archivo de entrada (post-feature-10): **1034 LoC**.
Archivo de salida (post-feature-11): **802 LoC**.
Reducción neta: **232 LoC eliminados** (~22%).

Rangos borrados (relativos al archivo de entrada de 1034 LoC):

- `:115-138` — `class LocalPhotoSelectionEngine` (movido a `prepare_reel_assets.py`).
- `:175-412` — cuerpo entero de `DefaultMediaPreparationService` (`__init__`, `prepare_assets`, `select_photos`, `cleanup_prepared_assets`, `resolve_selected_dir`, `resolve_primary_image_from_dir`, `_load_existing_assets`, `_prepare_curated_assets`, `_prepare_primary_only_assets`).
- `:415-416` — `class DefaultPhotoSelectionService(DefaultMediaPreparationService): pass` (D4).

Nuevo adapter delgado insertado en su lugar (~46 LoC con docstring), que cumple los Protocols `MediaPreparationService` y `PhotoSelectionService` (`interfaces.py:34-48`) sin cambios en `media_pipeline.py` ni `bootstrap`.

Imports huérfanos limpiados (R8 + D5):
- `from settings import DEFAULT_PHOTOS_TO_SELECT, SELECTED_PHOTOS_DIRNAME` (sólo `REVIEW_WORKFLOW_ENABLED` queda).
- `from core.media_cleanup import should_cleanup_raw_property_dir, should_cleanup_selected_assets` (sólo `should_cleanup_render_staging_dir` queda).
- `from core.errors import PhotoFilteringError` (los 4 restantes siguen).
- `from core.logging import build_log_context` (los 3 restantes siguen).
- `from domain.properties.model import Property`.
- `from repositories.stores.pipeline_state_store import PropertyPipelineState` (D5).
- `from services.media.property_media import download_and_filter_property_images`.
- `from services.media.property_media.downloads import download_image, download_images_to_directory`.
- `from services.media.property_media.filesystem import list_image_files, prepare_property_directories`.
- `from services.media.property_media.naming import PRIMARY_IMAGE_STEM, build_primary_image_filename`.

Imports añadidos:
- `from modules.reels.application.use_cases.prepare_reel_assets import LocalPhotoSelectionEngine, PrepareReelAssetsUseCase` (uso por el adapter + re-export).

---

## 3. Decisiones del leader respetadas

- **D1 (lógica AI no migra)**: NO se tocó `modules/rendering/infrastructure/ai_photo_selection/`. El use case orquesta sobre `LocalPhotoSelectionEngine` legacy (movido al módulo nuevo) que sigue invocando `services/media/property_media/selection.py:download_and_filter_property_images`. La carpeta `ai_photo_selection/` queda igual de vacía hasta feature 14/15.
- **D3 (naming)**: el use case expone `execute(context, *, uow=None)` y `cleanup(context, prepared_assets)`. El adapter `DefaultMediaPreparationService` mantiene `prepare_assets`/`select_photos`/`cleanup_prepared_assets` para no romper el Protocol `MediaPreparationService`/`PhotoSelectionService`.
- **D4 (`DefaultPhotoSelectionService` borrado)**: borrada la subclase `class DefaultPhotoSelectionService(DefaultMediaPreparationService): pass` de `media_services.py:415-416`, y borrado el re-export en `default_services.py:5,18`. `grep DefaultPhotoSelectionService` no devuelve resultados tras la edición — sin call sites perdidos.
- **R1 (cierre cruce con feature 10)**: `ingest_property_into_reel.py:_should_prepare_assets` ahora importa `PrepareReelAssetsUseCase` (lazy) y llama a sus staticmethods. Comentario "feature 11 absorbs ..." borrado. Helper `_state_for_legacy_helpers` eliminado por completo (los staticmethods aceptan ahora cualquier objeto con `selected_image_folder`, no solo el legacy `PropertyPipelineState`).
- **R6 (doble upsert en `properties`)**: el use case prepare hace `uow.catalog.properties.upsert_property(record)` + `uow.catalog.images.replace_images(record_id, ...)` (idempotente, ON CONFLICT lo hace seguro). Comportamiento equivalente al legacy `save_property_images`. Sin acción extra.
- **R8 (limpieza imports huérfanos)**: lista completa al final del §2.
- **R9 (re-export `LocalPhotoSelectionEngine`)**: `media_services.py:37-40` importa `LocalPhotoSelectionEngine` del módulo nuevo y lo deja al alcance del módulo (queda en `__all__`). `default_services.py:6,16` re-exporta vía `media_services.py`. Sin cambios en consumidores.
- **R-doble UoW**: el use case prepare abre su propio `DatabaseUnitOfWork` cuando se llama desde el adapter legacy (sin pasar `uow=`); cuando los tests pasan un `uow=stub`, lo usa directamente. Mismo patrón que `IngestPropertyIntoReelUseCase`.

---

## 4. Decisión de implementación: helper `_build_property_record` duplicado

El plan dejaba abierto reusar `_build_property_record` del use case feature 10 o duplicarlo. **Elegí duplicarlo** (~14 LoC, en `prepare_reel_assets.py:64-89`) por dos razones:

1. **Independencia de tests**: feature 11 no debe romper si feature 10 evoluciona el helper (futuras columnas, otra serialización). Cada use case posee su payload de upsert.
2. **Coherencia inter-módulo**: ambos use cases viven en `modules/reels/application/use_cases/`, así que importar entre ellos es legal, pero un helper privado con `_` prefix idealmente no es API. Duplicar es coste de 14 LoC y compra el desacoplo. Documentado en el docstring del helper.

---

## 5. Resultado de los checks de cierre

### Tests

```
$ pytest -q tests/unit/reels/test_prepare_reel_assets.py
7 passed in 1.18s

$ pytest -q tests/integration/reels/test_prepare_reel_assets_flow.py
1 passed in 2.75s

$ pytest -q tests/unit/reels/ tests/integration/reels/
45 passed in 37.11s

$ ./init.sh
...
388 passed in 198.03s (0:03:18)
[OK]    pytest verde
```

Baseline pre-feature: **380 tests** (post-feature-10).
Post-feature 11: **388 tests** (380 + 7 unit + 1 integration). Esperado ≥ 384 — cumplido.

### Readiness

```
$ python -m apps.api --check
RUNTIME READY: Yes (PRODUCTION READY: No, esperado en dev)

$ python -m apps.worker --check
Worker --check OK: kinds=reel_publish, scripted_render worker_count=1 lease=900s poll=0.50s
```

Ambos exit 0. `init.sh` verde end-to-end (incluye lint legacy WARN sobre 2 archivos en directorios legacy modificados — son `media_services.py` y `default_services.py`, modificación quirúrgica permitida por las reglas de Phase 2).

### Repo limpio

- Sin `xfail`, sin `print()` debug, sin `TODO`/`FIXME` en archivos creados/modificados.
- `__pycache__/.tmp_*` no añadidos.

---

## 6. Desviaciones frente al plan del explorer

1. **LoC final 802 vs ~770-810 estimado**: dentro del rango previsto (~22% reducción). Ajuste fino entre el adapter (~46 LoC con docstring) y los imports limpiados.
2. **`_state_for_legacy_helpers` ya no existe**: el plan ofrecía como opcional eliminarlo. Lo hice porque el nuevo `resolve_selected_dir` acepta `Any | None` y usa `getattr`, así que pasarle el `ReelState` directamente es trivial. El método del use case ingest queda 5 LoC más corto y sin un workaround temporal.
3. **`_build_property_record` duplicado en lugar de importado**: documentado en §4. Trade-off explícito.
4. **Adapter constructor mantiene engine inyectable**: el adapter delgado expone `engine=` para que el constructor del use case lo respete (el bootstrap actual no lo usa, pero es una superficie estable para tests futuros). Coherente con la firma legacy del Protocol.

---

**Fin del informe.**

## 7. Fix post-review (build_log_context import restaurado)

El reviewer detectó como issue crítico #1 en `progress/review_11_prepare_reel_assets.md` que el commit anterior eliminó `build_log_context` del import de `core.logging` en `application/pipeline/media_services.py:33`, pero el símbolo seguía usándose en tres call sites (`FileSystemMediaPublisher.publish_existing_media`, `FileSystemMediaPublisher._publish_related_poster` y `CompositeMediaPublisher.publish_existing_media`), provocando `NameError` en runtime. Se restauró el import en formato multilínea, ahora incluyendo `build_log_context` junto a `format_console_block`, `format_context_line` y `format_detail_line`. `Grep` confirma 4 ocurrencias del símbolo en el archivo (línea 34 del import + tres call sites en 452, 482, 543). `./init.sh` vuelve a terminar verde con **388 passed in 196.81s**. LoC final de `media_services.py`: **807** (se sumaron 4 LoC al import por el formato multilínea con el símbolo extra).
