# Review — feature 12 (`reels_use_case_persist_local_artifacts`)

**Veredicto:** APPROVED

## Resumen

Se validó el acceptance literal y todas las decisiones del leader (D1, D3,
D4, R1, R3, R5, R6, R10, R11). El use case `PersistLocalArtifactsUseCase`
queda extraído en `modules/reels/application/use_cases/persist_local_artifacts.py`
(351 LoC), los tests cubren los caminos feliz/error solicitados (7 unit +
1 integration nuevos verdes), `media_services.py` baja de **807 → 677
LoC** (verificado con `wc -l`), `application/bootstrap/runtime.py` y
`application/bootstrap/__init__.py` siguen byte-a-byte iguales entre sí
(`diff` exit 0, ambos cambian al mismo tiempo para añadir
`workspace_dir=workspace_path`), `build_log_context` SIGUE importado en
`media_services.py:31` (la regresión post-review feature 11 NO se repite),
el class shadow `class FileSystemMediaPublisher(FileSystemMediaPublisher): pass`
queda eliminado, y `./init.sh` termina verde con **396 passed**.

## Checks superados

### A. Acceptance literal

- [x] **A1** Existe `modules/reels/application/use_cases/persist_local_artifacts.py:120`
  con `class PersistLocalArtifactsUseCase` y método `execute(context, rendered_media, *, uow=None)`
  (`persist_local_artifacts.py:138-206`). Adicionalmente expone
  `execute_existing(context, *, uow=None)` (`:208-234`). 351 LoC.
- [x] **A2** Existe `tests/unit/reels/test_persist_local_artifacts.py` (388 LoC)
  con 7 tests significativos:
  `test_execute_reel_video_promotes_artifacts_and_writes_db`,
  `test_execute_poster_image_targets_posters_root_without_manifest`,
  `test_execute_cleans_staging_when_cleanup_temporary_files_is_true`,
  `test_execute_keeps_staging_when_cleanup_temporary_files_is_false`,
  `test_execute_raises_poster_required_when_reel_video_has_no_poster`,
  `test_execute_existing_raises_when_no_existing_artifact`,
  `test_execute_existing_returns_existing_artifact_without_db`.
  ≥4 cumplido. Todos PASS. Usa `tempfile.TemporaryDirectory()` (líneas 176, 265).
- [x] **A3** Existe `tests/integration/reels/test_persist_local_artifacts_flow.py`
  (227 LoC) con `test_execute_writes_rendered_state_revision_and_outbox_event_on_postgres`
  que usa `temporary_postgres_schema` + `seed_tenant` + `temporary_workspace`
  y SQL directo (`text(...)` con `create_engine`) para asserts. Sin mocks de
  Postgres. 1 test PASS. Encadena ingest → prepare → persist (líneas 84-156).
- [x] **A4** `media_services.py` reduce LoC: **807 → 677** (verificado con
  `wc -l application/pipeline/media_services.py`). Reducción 130 LoC
  (~16%). < 807 cumplido.
- [x] **A5** `pytest -q` (vía `./init.sh`) termina **396 passed** en
  220 s. Baseline 388 (post-feature-11) + 7 unit + 1 integration = 396.
  Esperado ≥ 396. ✓ Cumplido al pelo.

### B. Calidad del código

- [x] **B1** Inter-módulo: `persist_local_artifacts.py` solo importa de
  `modules.reels.domain` (su propio módulo, `:54`). NO importa de
  `<otro>.application` ni `<otro>.infrastructure`. Imports legacy
  aceptados en Phase 2 (`application/types`, `core/errors`, `core/logging`,
  `core/media_cleanup`) y modernos (`shared.db`).
- [x] **B2** `FileSystemMediaPublisher` adapter delgado:
  `media_services.py:333-378` (46 LoC con docstring), docstring presente
  (`:334-343`), `__init__` ignora `unit_of_work_factory` con
  `del unit_of_work_factory` (línea 352, comentario "legacy bootstrap arg;
  the use case owns its UoW."), aliases preservados:
  `publish_media:360-365`, `publish_video:367-372`,
  `publish_existing_media:374-375`, `publish_existing_video:377-378`.
  Cumple Protocol `MediaPublisher` (`interfaces.py:71-83`). ≤ 60 LoC.
- [x] **B3** Sin `print()`, sin `xfail` nuevos, sin `TODO`/`FIXME` en
  archivos creados/modificados (verificado con grep en
  `persist_local_artifacts.py`, `test_persist_local_artifacts.py`,
  `test_persist_local_artifacts_flow.py`: 0 hits).
- [x] **B4** Logs verbatim: el title legacy del cuerpo eliminado de
  `FileSystemMediaPublisher.publish_media` era `"Local Media Publish
  Completed"` (verificado en `application/pipeline/__init__.py:1446`,
  copia íntegra del legacy). El use case nuevo lo preserva byte-a-byte
  en `persist_local_artifacts.py:186`. El title `"Curated Media Assets
  Prepared"` (`prepare_reel_assets.py:313`) queda intacto de feature 11.
  Los titles "Local Reel Artifact Published" / "Local Poster Published"
  mencionados por el leader como alternativas no existen ni en el legacy
  ni en el código nuevo — el title canónico es "Local Media Publish
  Completed", preservado.
- [x] **B5** Firmas UoW moderno verificadas:
  - `uow.reels.states.save_local_artifacts(agency_id, ingestion_source_id,
    external_source_id, source_property_id, artifact_kind, artifact_path,
    metadata_path, render_profile, current_revision_id)` con kw-args
    modernos (`persist_local_artifacts.py:297-307`).
  - `uow.reels.revisions.save_revision(MediaRevision(...))` con dataclass
    moderno `from modules.reels.domain import MediaRevision`
    (`persist_local_artifacts.py:54, :308-325`). 14 columnas con
    `ingestion_source_id` y `external_source_id` (no `wordpress_source_id`
    ni `site_id`).
  - `uow.delivery.outbox.add_event(event_id, aggregate_type, aggregate_id,
    event_type, payload, agency_id, ingestion_source_id, external_source_id,
    source_property_id, created_at)` con kw-args modernos
    (`persist_local_artifacts.py:326-346`). Verificado contra
    `modules/delivery/infrastructure/outbox_repository.py:68-113` (firma
    confirmada). El implementer documentó en bitácora y en
    `impl_12_*.md §4.1` que tuvo que añadir `created_at=_now_iso()`
    explícito porque la columna `outbox_events.created_at` rechaza
    strings vacíos.
- [x] **B6** Naming Phase 2: use case expone `execute()`
  (`persist_local_artifacts.py:138`) y `execute_existing()`
  (`persist_local_artifacts.py:208`). El adapter `FileSystemMediaPublisher`
  conserva nombres legacy `publish_media`, `publish_video`,
  `publish_existing_media`, `publish_existing_video` por contrato Protocol.

### C. Tests

- [x] **C1** Unit tests usan stubs UoW inline (`_StubReelStates`,
  `_StubMediaRevisions`, `_StubOutbox` en
  `test_persist_local_artifacts.py:49-87`); no hay DB real. Cobertura
  cumple: feliz `reel_video` (test 1), `poster_image` sin manifest (test 2),
  cleanup on/off (tests 3-4), `POSTER_REQUIRED` (test 5),
  `EXISTING_MEDIA_REQUIRED` (test 6), `execute_existing` con artefacto
  previo sin DB (test 7).
- [x] **C2** `tempfile.TemporaryDirectory()` para staging y output dirs
  (`test_persist_local_artifacts.py:176, :265`). Para los tests de
  cleanup (3-4), el staging vive como `tmp_path / "staging-cleaned"`
  para verificar el `rmtree`. Adecuado.
- [x] **C3** Integration test usa `temporary_postgres_schema` + `seed_tenant`
  + `temporary_workspace` (`test_persist_local_artifacts_flow.py:80-82`).
  SQL directo con `text(...)` y `create_engine` (`:168-225`). Sin mocks
  de Postgres. Encadena ingest → prepare → persist
  (`:84-100, :103-128, :130-156`).
- [x] **C4** Tests de features 10/11 siguen verdes sin tocarlos
  (verificado en init.sh: 396 passed; 388 previos + 8 nuevos = 396 — los
  388 previos pasan intactos). `tests/unit/reels/test_ingest_*.py`,
  `test_prepare_*.py`, `tests/integration/reels/test_ingest_*flow.py`,
  `test_prepare_*flow.py` no tienen mtimes recientes (no modificados).

### D. Bootstrap (R2/D3)

- [x] **D1** `application/bootstrap/runtime.py:122` y
  `application/bootstrap/__init__.py:122` añaden `workspace_dir=workspace_path`
  a la llamada `FileSystemMediaPublisher(...)`. `diff
  application/bootstrap/runtime.py application/bootstrap/__init__.py`
  exit 0 (sin diff entre sí). Los dos archivos cambian igual, conforme
  el patrón.

### E. Acoplamientos

- [x] **E1** `media_services.py` post-feature-12: `build_log_context`
  SIGUE en el import (línea 31, dentro del bloque multilínea
  `from core.logging import (build_log_context, format_console_block,
  format_context_line, format_detail_line)` líneas 30-35). 1 call site
  vivo en el archivo: `CompositeMediaPublisher.publish_existing_media:413`
  (paso 4, feature 13). Las otras 2 call sites (`POSTER_REQUIRED` en
  `_publish_related_poster` y `EXISTING_MEDIA_REQUIRED` en
  `FileSystemMediaPublisher.publish_existing_media`) se movieron al use
  case nuevo (`persist_local_artifacts.py:227, :258`). El total post-12
  son 1 import + 1 call site, no 1+3 como mencionaba el leader (el conteo
  esperado del leader incluía las 2 ramas movidas; mi auditoría confirma
  que las 2 movidas siguen vivas pero ahora en el use case nuevo, y la 3ª
  sigue en composite — la regresión post-review feature 11 NO se repite).
- [x] **E2** `media_services.py` importa `LocalPhotoSelectionEngine`
  (`:43`), `PrepareReelAssetsUseCase` (`:44`), `PersistLocalArtifactsUseCase`
  (`:39-41`). El `__all__` del módulo (`:670-677`) re-exporta los
  adapters legacy (`CompositeMediaPublisher`,
  `DefaultMediaPreparationService`, `DefaultMediaRenderer`,
  `DefaultPropertyInfoService`, `FileSystemMediaPublisher`,
  `LocalPhotoSelectionEngine`). El adapter consume los use cases vía
  import directo, no vía `__all__`. Correcto.
- [x] **E3** `application/pipeline/default_services.py:1-17` re-exporta
  los adapters vía `media_services.py` sin cambios funcionales.
  `apps.api --check` y `apps.worker --check` exit 0.
- [x] **E4** `application/pipeline/media_pipeline.py` no se tocó (133 LoC
  sin cambios). Sigue llamando a `media_publisher.publish_media` y
  `media_publisher.publish_existing_media` — ambos van al composite.
- [x] **E5** `application/pipeline/interfaces.py` no se tocó (112 LoC
  sin cambios). Protocol `MediaPublisher` intacto.
- [x] **E6** Class shadow `class FileSystemMediaPublisher(FileSystemMediaPublisher): pass`
  BORRADO (`grep "FileSystemMediaPublisher\(FileSystemMediaPublisher\)"
  application/pipeline/media_services.py`: 0 hits). Otros class shadows
  siguen vivos hasta features 13/14: `class DefaultMediaRenderer(DefaultMediaRenderer): pass`
  (`media_services.py:329-330`), `class CompositeMediaPublisher(CompositeMediaPublisher): pass`
  (`media_services.py:666-667`). OK, no es alcance de feature 12.

### F. Schema

- [x] Sin nueva migración en `alembic/versions/` desde feature 11
  (verificado: solo `20260501_0001_initial_schema.py` y `__pycache__/`).
  Feature 12 NO toca schema, conforme.

### G. Limpieza imports en `media_services.py`

- [x] `import os` BORRADO (solo lo usaba `_replace_atomically`, ahora extraído).
- [x] `import shutil` BORRADO (solo lo usaba `publish_media`, ahora extraído).
- [x] `should_cleanup_render_staging_dir` BORRADO del import block (solo
  lo usaba `publish_media`, ahora extraído). Verificado con grep en
  `application/pipeline/media_services.py`: 0 hits.
- [x] `MediaRevisionRecord` (legacy) CONSERVADO (`media_services.py:46`),
  lo usa `_persist_workflow_transition:627` del composite (feature 13).
- [x] `build_log_context` CONSERVADO (`media_services.py:31`), lo usa el
  composite en `:413`. R6 honrado, no se repite la regresión post-review
  feature 11.
- [x] `_now_iso`, `_relative_path_text`, `_build_workflow_payload`
  CONSERVADOS (`media_services.py:67-112`), los usa
  `_persist_workflow_transition:617-659` del composite. Duplicados
  intencionalmente en el use case nuevo (`persist_local_artifacts.py:65-112`)
  para desacoplar.

## Confirmación de checks de cierre

| Check | Resultado |
|-------|-----------|
| `wc -l modules/reels/application/use_cases/persist_local_artifacts.py` | 351 |
| `wc -l application/pipeline/media_services.py` | 677 (de 807 — reducción 130 LoC) |
| `wc -l tests/unit/reels/test_persist_local_artifacts.py` | 388 (7 tests) |
| `wc -l tests/integration/reels/test_persist_local_artifacts_flow.py` | 227 (1 test) |
| `pytest -q` (init.sh) | 396 passed in 220 s |
| `apps.api --check` / `apps.worker --check` | exit 0 ambos |
| `diff application/bootstrap/runtime.py application/bootstrap/__init__.py` | exit 0 (sin diff) |
| `grep build_log_context application/pipeline/media_services.py` | 1 import (`:31`) + 1 call site (`:413`) — ambos vivos |
| `grep "class FileSystemMediaPublisher(FileSystemMediaPublisher)" application/pipeline/media_services.py` | 0 hits (class shadow eliminado) |
| `grep "import os" application/pipeline/media_services.py` | 0 hits (limpio) |
| `grep "import shutil" application/pipeline/media_services.py` | 0 hits (limpio) |
| `grep should_cleanup_render_staging_dir application/pipeline/media_services.py` | 0 hits (limpio) |
| Nueva migración en `alembic/versions/` | NO (correcto — feature 12 no toca schema) |

## Sugerencias menores

(No bloquean; documentadas para el siguiente paso.)

1. `application/pipeline/__init__.py` (1839 LoC) sigue siendo dead code
   pre-existente con su propia copia íntegra del legacy. Ya señalado en
   reviews de features 10 y 11. Feature 12 no lo empeora ni lo arregla —
   queda para feature 13/14.
2. Los class shadows `DefaultMediaRenderer:329-330` y
   `CompositeMediaPublisher:666-667` siguen vivos. Out of scope; los
   limpiarán features 13 y 14 al reemplazar las clases originales.
3. La doble validación `EXISTING_MEDIA_REQUIRED` (en el use case nuevo
   `:223-233` y en el composite `:409-419`) es duplicación pre-existente
   documentada como R7 del explore. Feature 13 unifica al absorber el
   composite.
4. `created_at=_now_iso()` en `outbox.add_event` (R10/§4.1 del impl):
   aprendizaje útil — feature 13 (`publish_reel`) hará el mismo insert
   en outbox y debe pasar `created_at` también para no fallar contra
   Postgres.
