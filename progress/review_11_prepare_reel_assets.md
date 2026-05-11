# Review — feature 11 (`reels_use_case_prepare_reel_assets`)

**Veredicto:** APPROVED (tras fix #1)

## Resumen

Se validó el acceptance literal y las decisiones del leader (D1, D3, D4,
R1, R6, R8, R9, R10). El use case `PrepareReelAssetsUseCase` queda
extraído en `modules/reels/application/use_cases/prepare_reel_assets.py`
(447 LoC), los tests unit + integration cubren los caminos feliz/error
solicitados (8 nuevos tests verdes), `media_services.py` baja de **1034
→ 802 LoC** (verificado con `wc -l`), el bridge R1 con feature 10 queda
cerrado (`_state_for_legacy_helpers` eliminado, comentario "feature 11
absorbs ..." borrado, import lazy de `PrepareReelAssetsUseCase`),
`application/bootstrap/{runtime.py,__init__.py}` siguen byte-a-byte
iguales (`diff` exit 0), y `./init.sh` termina verde con **388 passed**.

**Sin embargo**, la limpieza de imports en `media_services.py` se pasó
de la raya: el implementer borró `build_log_context` del import
(`core.logging`) pero el símbolo se sigue usando en **3 call sites**
dentro de los pasos render/publish que NO migran en feature 11. Es un
`NameError` latente en branches de error legítimas (`publish_existing_media`
sin `existing_published_media`; `_publish_related_poster` sin poster en
un reel render). El test suite no exercita esos branches, así que
init.sh pasa, pero la regresión rompe el contrato de Phase 2 ("borrar lo
que no se usa, no lo que sí se usa"). Bloqueante.

## Checks superados

### A. Acceptance literal

- [x] **A1** Existe `modules/reels/application/use_cases/prepare_reel_assets.py:125`
  con `class PrepareReelAssetsUseCase` y método `execute(context, *, uow=None)`
  (`prepare_reel_assets.py:149-168`). 447 LoC.
- [x] **A2** Existe `tests/unit/reels/test_prepare_reel_assets.py` con 7 tests:
  `test_execute_curated_path_persists_property_images_and_workflow_state`,
  `test_execute_primary_only_path_downloads_featured_image`,
  `test_execute_returns_existing_assets_without_persisting_when_not_required`,
  `test_execute_curated_path_wraps_unexpected_engine_error_as_photo_filtering_error`,
  `test_execute_primary_only_path_raises_when_no_image_url_is_available`,
  `test_cleanup_removes_selected_dir_when_cleanup_selected_photos_is_true`,
  `test_cleanup_keeps_selected_dir_when_cleanup_selected_photos_is_false`.
  ≥4 cumplido. Todos PASS.
- [x] **A3** Existe `tests/integration/reels/test_prepare_reel_assets_flow.py`
  (169 LoC) con `test_execute_writes_assets_prepared_state_and_property_images_on_postgres`
  que usa `temporary_postgres_schema` + `seed_tenant` + `temporary_workspace`
  y SQL directo (`text(...)` con `create_engine`) para asserts. Sin mocks de
  Postgres. 1 test PASS.
- [x] **A4** `media_services.py` reduce LoC: **1034 → 802** (verificado
  con `wc -l application/pipeline/media_services.py`). Reducción 232 LoC
  (~22%). < 1034 cumplido.
- [x] **A5** `pytest -q` (vía `./init.sh`) termina **388 passed** en
  197 s. Baseline 380 (post-feature-10) + 8 nuevos = 388. Esperado ≥ 384. ✓

### B. Calidad del código

- [x] **B1** Inter-módulo: `prepare_reel_assets.py` no importa de
  `<otro>.application` ni `<otro>.infrastructure`. Imports legacy
  aceptados en Phase 2 (`application/`, `core/`, `domain/`, `services/`,
  `settings`) y modernos (`shared.db`).
- [x] **B2** `DefaultMediaPreparationService` adapter delgado:
  `media_services.py:144-188` (~46 LoC con docstring), docstring presente,
  `__init__` ignora `unit_of_work_factory` con `del unit_of_work_factory`
  (línea 163), `prepare_assets`/`select_photos`/`cleanup_prepared_assets`
  delegan al use case (`prepare_reel_assets.py`). Cumple Protocols
  `MediaPreparationService` y `PhotoSelectionService`.
- [x] **B3** Sin `print()`, sin `xfail` nuevos, sin `TODO`/`FIXME` en
  archivos creados/modificados (verificado con grep).
- [x] **B4** Logs verbatim: titles `"Curated Media Assets Prepared"`,
  `"Primary Status Reel Asset Prepared"`, `"Prepared Media Assets Cleaned"`
  en `prepare_reel_assets.py:312, 395, 181` preservados byte-a-byte
  respecto al legacy.
- [x] **B5** Firmas UoW moderno verificadas:
  `uow.catalog.properties.upsert_property(record)` (`prepare_reel_assets.py:431`),
  `uow.catalog.images.replace_images(record_id, list(...))` (`:432`),
  `uow.reels.states.update_workflow_state(agency_id, ingestion_source_id,
  external_source_id, source_property_id, workflow_state, current_revision_id)`
  (`:433-440`). Coinciden con
  `modules/catalog/infrastructure/property_repository.py` y
  `modules/reels/infrastructure/reel_state_repository.py`.
- [x] **B6** Naming Phase 2: use case expone `execute()` y `cleanup()`;
  adapter conserva nombres legacy (`prepare_assets`, `select_photos`,
  `cleanup_prepared_assets`) por contrato Protocol.

### C. Tests

- [x] **C1** Unit tests (`tests/unit/reels/test_prepare_reel_assets.py`)
  ejercitan el use case con stubs UoW (`_StubProperties`, `_StubImages`,
  `_StubReelStates`); no hay DB real.
- [x] **C2** Stubs HTTP: `download_image` se monkeypatchea en el módulo
  nuevo (`tests/unit/reels/test_prepare_reel_assets.py:230-233`); la
  selección curated se simula vía `monkeypatch.setattr(LocalPhotoSelectionEngine,
  "select_photos", _fake_select_photos)`. Sin tráfico de red.
- [x] **C3** Integration test usa `temporary_postgres_schema`, `seed_tenant`,
  `temporary_workspace`; SQL directo con `text(...)` para asserts; sin
  mocks de Postgres. Stubea sólo el engine de selección.
- [x] **C4** Stubs coherentes con el patrón de `_uow_stubs.py` (no se
  amplió ese fichero — los stubs viven inline en
  `test_prepare_reel_assets.py:48-75`, decisión razonable porque amplían
  la API que `_uow_stubs.py` no exponía aún).

### D. Cierre del bridge feature 10 (R1)

- [x] **D1** `modules/reels/application/use_cases/ingest_property_into_reel.py:762-764`
  importa `PrepareReelAssetsUseCase` (lazy, dentro de
  `_should_prepare_assets`) desde
  `modules.reels.application.use_cases.prepare_reel_assets`. Ya NO
  importa `DefaultMediaPreparationService` desde
  `application.pipeline.media_services` (verificado con grep).
- [x] **D2** Comentario "feature 11 absorbs ..." borrado del archivo
  (`grep "feature 11 absorbs"` solo devuelve archivos en `progress/`).
- [x] **D3** `_state_for_legacy_helpers` eliminado por completo
  (`grep` solo devuelve archivos en `progress/`). El staticmethod
  `resolve_selected_dir` acepta `state: Any | None` con
  `getattr(state, "selected_image_folder", "")`, así que se le pasa el
  `ReelState` moderno directamente. Limpieza correcta.
- [x] **D4** Tests de feature 10 (`tests/unit/reels/test_ingest_property_into_reel.py`
  y `tests/integration/reels/test_ingest_property_into_reel_flow.py`)
  pasan en init.sh sin haber sido tocados.

### E. Acoplamientos / huellas legacy

- [x] **E1** `application/pipeline/media_services.py:37-40` re-exporta
  `LocalPhotoSelectionEngine` y `PrepareReelAssetsUseCase` del módulo
  nuevo. `default_services.py:1-17` re-exporta vía `media_services.py`,
  cumpliendo R9. `DefaultPhotoSelectionService` borrado en ambos sitios
  (D4).
- [x] **E2** `application/bootstrap/runtime.py` y
  `application/bootstrap/__init__.py` byte-a-byte iguales (`diff` exit
  code 0, sin output). Sin cambios entre features 10 y 11.
- [x] **E3** `application/pipeline/media_pipeline.py` no se tocó (sigue
  llamando a `prepare_assets`/`cleanup_prepared_assets` del adapter).
- [x] **E4** `application/pipeline/interfaces.py` no se tocó (Protocols
  `MediaPreparationService`, `PhotoSelectionService` y
  `PhotoSelectionEngine` intactos).

### F. Schema

- [x] Sin nueva migración en `alembic/versions/` desde feature 10
  (verificado: solo `20260501_0001_initial_schema.py` y `__pycache__/`).
  Feature 11 NO toca schema, conforme.

### G. Limpieza imports

- [x] `SELECTED_PHOTOS_DIRNAME`, `DEFAULT_PHOTOS_TO_SELECT` borrados de
  `media_services.py` (verificado con grep).
- [x] `should_cleanup_raw_property_dir`, `should_cleanup_selected_assets`
  borrados (`media_services.py:22-26` solo conserva
  `DEFAULT_DELETE_SELECTED_PHOTOS`, `DEFAULT_DELETE_TEMPORARY_FILES`,
  `should_cleanup_render_staging_dir`).
- [x] `PhotoFilteringError` borrado (`media_services.py:27-32` solo
  conserva `SocialPublishingResultError`,
  `TransientSocialPublishingResultError`, `ValidationError`,
  `extract_error_details`).
- [x] `Property` borrado (no hay `from domain.properties.model import
  Property` en `media_services.py`).
- [x] `PropertyPipelineState` borrado (D5 cumplido).
- [x] `download_and_filter_property_images`, `download_image`,
  `download_images_to_directory` borrados.
- [x] `list_image_files`, `prepare_property_directories`,
  `PRIMARY_IMAGE_STEM`, `build_primary_image_filename` borrados.
- [ ] **`build_log_context` borrado del import (`core.logging`) pero
  AÚN se usa en 3 call sites de `media_services.py`** — ver Issues
  críticos #1.

## Issues críticos

### #1 — `build_log_context` borrado del import pero todavía se usa (3 call sites)

**Severidad:** bloqueante (`NameError` latente en branches de error reales).

`application/pipeline/media_services.py:33` ahora importa solo:

```python
from core.logging import format_console_block, format_context_line, format_detail_line
```

Pero `build_log_context` se sigue invocando en **3 lugares** que NO se
movieron a feature 11 (siguen en los pasos publish):

- `application/pipeline/media_services.py:447` — `FileSystemMediaPublisher.publish_existing_media`,
  rama `if context.existing_published_media is None` → `ValidationError(..., context=build_log_context(...))`.
- `application/pipeline/media_services.py:477` — `FileSystemMediaPublisher._publish_related_poster`,
  rama `if not poster_source_path.exists() or stat.st_size == 0` y
  `artifact_kind == "reel_video"` → `ValidationError(..., context=build_log_context(...))`.
- `application/pipeline/media_services.py:538` — `CompositeMediaPublisher.publish_existing_media`,
  misma rama `existing_published_media is None`.

Verificado:

```
$ python -c "import application.pipeline.media_services as m; print('build_log_context' in dir(m))"
False
```

Las 3 ramas son rutas de error legítimas (publish-only retry sin
artefacto previo, render de reel sin poster generado). El test suite
actual no las exercita, por eso `init.sh` termina verde con 388, pero
ejecutarlas en producción dispararía `NameError: name 'build_log_context'
is not defined` antes incluso de construir el `ValidationError`,
ocultando la causa real del fallo y rompiendo el handler.

El plan del explorer (§R8) ya advertía explícitamente: "`build_log_context`
lo usan los pasos render/publish también (`media_services.py:271, :302,
:345, :369, :676` — verificar después de la edición qué queda)." La
verificación post-edición no se hizo.

**Fix requerido:** restaurar `build_log_context` en el import de
`core.logging` en `media_services.py:33`:

```python
from core.logging import (
    build_log_context,
    format_console_block,
    format_context_line,
    format_detail_line,
)
```

(Y opcionalmente añadir un test que ejercite uno de los branches —
p.ej. un unit test sobre `FileSystemMediaPublisher.publish_existing_media`
con `context.existing_published_media=None` que valide que el
`ValidationError` se construye correctamente — pero el fix mínimo es
restaurar el import.)

## Sugerencias menores

(No bloquean; documentadas para el siguiente paso.)

1. `application/pipeline/__init__.py` (1839 LoC) sigue siendo dead code
   pre-existente con su propia copia íntegra del legacy y `__all__` con
   duplicados (e.g. `"CompositeMediaPublisher"` listado dos veces,
   `"DefaultPhotoSelectionService"` aún listado a pesar de haber sido
   borrado del módulo `media_services.py`/`default_services.py`). Ya lo
   marcó la review de feature 10. Feature 11 no lo empeora ni lo arregla
   — queda para feature 13/14.
2. El helper `_build_property_record` se duplica entre
   `prepare_reel_assets.py:64-89` e
   `ingest_property_into_reel.py:219-241`. Decisión documentada en
   `impl_11_prepare_reel_assets.md §4` con trade-off explícito (≈14 LoC
   por el desacoplo). Aceptable; si en el futuro evoluciona la columna,
   recordar actualizar ambos.
3. El use case unit test stub `_StubReelStates.update_workflow_state`
   acepta `**kwargs` y no valida el orden/firma; está bien, pero si en
   feature 14 se cambia la firma del repo moderno los tests no caerían.
   Para Phase 2 es suficiente.

## Confirmación de checks de cierre

| Check | Resultado |
|-------|-----------|
| `wc -l modules/reels/application/use_cases/prepare_reel_assets.py` | 447 |
| `wc -l application/pipeline/media_services.py` | 802 (de 1034 — reducción 232 LoC) |
| `wc -l tests/unit/reels/test_prepare_reel_assets.py` | 399 (7 tests) |
| `wc -l tests/integration/reels/test_prepare_reel_assets_flow.py` | 169 (1 test) |
| `pytest -q` (init.sh) | 388 passed in 197 s |
| `apps.api --check` / `apps.worker --check` | exit 0 ambos |
| `diff application/bootstrap/runtime.py application/bootstrap/__init__.py` | exit 0 (sin diff) |
| `grep DefaultPhotoSelectionService` (excluye progress/) | solo `application/pipeline/__init__.py` (dead code pre-existente) |
| `grep "feature 11 absorbs"` | sin hits en código (solo `progress/`) |
| `grep _state_for_legacy_helpers` | sin hits en código (solo `progress/`) |
| Nueva migración en `alembic/versions/` | NO (correcto — feature 11 no toca schema) |
| `build_log_context` import en `media_services.py` | **AUSENTE pese a 3 usos en líneas 447, 477, 538** ← bloqueante |

## Re-review tras fix post-review (2026-05-05)

**Veredicto actualizado:** APPROVED

Issue crítico #1 resuelto: `application/pipeline/media_services.py` ahora importa `build_log_context` de `core.logging` (línea 34, dentro del bloque multilínea `from core.logging import (...)` en líneas 33-38) y los 3 call sites (452, 482, 543) resuelven el símbolo correctamente. `init.sh` exit 0 con 388 passed in 193.50s. Sin otros cambios (solo `media_services.py` y la sección §7 de `impl_11_prepare_reel_assets.md` se modificaron tras la review previa). LoC final de `media_services.py`: 807 (+5 vs los 802 previos por el formato multilínea con el símbolo restaurado). La feature queda lista para cierre.
