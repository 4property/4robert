# Impl — Feature 12 `reels_use_case_persist_local_artifacts`

> Extracción del paso 3 del pipeline (persistencia local de artefactos +
> escritura en `reels`/`media_revisions`/`outbox_events`) desde
> `application/pipeline/media_services.py` hacia
> `modules/reels/application/use_cases/persist_local_artifacts.py` con
> clase `PersistLocalArtifactsUseCase`. Conforme al plan del explorer
> (`progress/explore_feature_12_persist_local_artifacts.md`).

---

## 1. Archivos creados / modificados / borrados

### Creados

| Archivo | LoC | Tipo |
|---------|-----|------|
| `modules/reels/application/use_cases/persist_local_artifacts.py` | 351 | Use case + helpers duplicados (`_now_iso`, `_relative_path_text`, `_build_workflow_payload`) + métodos privados (`_resolve_output_dir`, `_publish_related_poster`, `_replace_atomically`, `_persist_with_uow`). |
| `tests/unit/reels/test_persist_local_artifacts.py` | 388 | Unit (camino feliz `reel_video`, `poster_image` sin manifest, cleanup on/off, `POSTER_REQUIRED`, `execute_existing` con/sin artefacto previo). 7 tests. |
| `tests/integration/reels/test_persist_local_artifacts_flow.py` | 227 | Integration (`temporary_postgres_schema` + `seed_tenant` + `temporary_workspace`, encadena ingest → prepare → persist; valida `reels.workflow_state='rendered'`, `reels.render_status='completed'`, `media_revisions.workflow_state='rendered'`, `outbox_events.event_type='media_rendered'`, archivos en disco). 1 test. |

### Modificados

| Archivo | Cambio |
|---------|--------|
| `application/pipeline/media_services.py` | 807 → **677 LoC** (130 LoC eliminados, ~16% reducción). Borrado: `FileSystemMediaPublisher.__init__` + `publish_media` + `publish_video` + `publish_existing_media` + `publish_existing_video` + `_resolve_output_dir` + `_publish_related_poster` + `_replace_atomically` + class shadow (R5) — rangos `:333-508` del archivo de entrada de 807 LoC. Insertado adapter delgado `FileSystemMediaPublisher` (~46 LoC con docstring + 4 alias) que delega a `PersistLocalArtifactsUseCase`. Imports limpiados: `os` (solo lo usaba `_replace_atomically`), `shutil` (solo lo usaba `publish_media`), `should_cleanup_render_staging_dir` (solo lo usaba `publish_media`). Añadido import de `PersistLocalArtifactsUseCase`. Conservados (los necesita el composite paso 4): `build_log_context`, `_now_iso`, `_relative_path_text`, `_build_workflow_payload`, `MediaRevisionRecord` (R6, R3). |
| `application/bootstrap/runtime.py` | +1 LoC: `workspace_dir=workspace_path` añadido a la llamada `FileSystemMediaPublisher(...)` en `build_default_property_media_pipeline` (D3, necesario para que el use case abra `DatabaseUnitOfWork(..., base_dir=workspace_dir)`). |
| `application/bootstrap/__init__.py` | +1 LoC idéntico a `runtime.py` (siguen byte-a-byte iguales — `diff` exit 0 verificado). |
| `modules/reels/application/use_cases/__init__.py` | +1 import + +1 entrada en `__all__` para re-exportar `PersistLocalArtifactsUseCase`. |
| `feature_list.json` | Feature 12 status `pending` → `in_progress`. |
| `progress/current.md` | Bitácora actualizada (R10 verificación, status). |

### Borrados

Ninguno físicamente. Dentro de `media_services.py` se borraron el cuerpo entero de `FileSystemMediaPublisher` (publishers + helpers) y el class shadow `class FileSystemMediaPublisher(FileSystemMediaPublisher): pass` (R5).

---

## 2. Líneas eliminadas de `application/pipeline/media_services.py`

Archivo de entrada (post-feature-11 + fix post-review): **807 LoC**.
Archivo de salida (post-feature-12): **677 LoC**.
Reducción neta: **130 LoC eliminados** (~16%).

Rangos borrados (relativos al archivo de entrada de 807 LoC):

- `:333-341` — `FileSystemMediaPublisher.__init__` legacy (almacenaba `unit_of_work_factory`).
- `:343-438` — `FileSystemMediaPublisher.publish_media` (96 LoC, el cuerpo grande del paso 3).
- `:440-445` — `FileSystemMediaPublisher.publish_video` (alias).
- `:447-459` — `FileSystemMediaPublisher.publish_existing_media`.
- `:461-462` — `FileSystemMediaPublisher.publish_existing_video` (alias).
- `:464-468` — `_resolve_output_dir` (staticmethod).
- `:470-498` — `_publish_related_poster` (classmethod).
- `:500-504` — `_replace_atomically` (staticmethod).
- `:507-508` — `class FileSystemMediaPublisher(FileSystemMediaPublisher): pass` (class shadow R5).

Adapter delgado insertado en su lugar (~46 LoC con docstring + 4 alias `publish_media`/`publish_video`/`publish_existing_media`/`publish_existing_video` para no romper el Protocol `MediaPublisher` ni callers desconocidos). Constructor recibe `unit_of_work_factory` por compat (lo descarta con `del`) y `workspace_dir` (obligatorio ahora — D3).

Imports huérfanos limpiados (R8 análogo a feature 11):

- `import os` (solo lo usaba `_replace_atomically`, ahora extraído).
- `import shutil` (solo lo usaba `publish_media`, ahora extraído).
- `from core.media_cleanup import should_cleanup_render_staging_dir` (solo lo usaba `publish_media`, ahora extraído).

Imports añadidos:

- `from modules.reels.application.use_cases.persist_local_artifacts import PersistLocalArtifactsUseCase` (consumido por el adapter).

Imports conservados explícitamente (los necesita `CompositeMediaPublisher` paso 4):

- `build_log_context` — usado en `CompositeMediaPublisher.publish_existing_media:543` (R6).
- `_now_iso`, `_relative_path_text`, `_build_workflow_payload` — usados en `CompositeMediaPublisher._persist_workflow_transition` (R1).
- `MediaRevisionRecord` (legacy) — `_persist_workflow_transition` lo sigue usando (R3).

---

## 3. Decisiones del leader respetadas

- **D1 (alcance)**: extraído **únicamente** `FileSystemMediaPublisher.publish_media` + `publish_existing_media` + helpers privados. NO se tocó `DefaultMediaRenderer` (paso render puro = feature 14). NO se tocó `CompositeMediaPublisher` (publish externo = feature 13). El adapter `FileSystemMediaPublisher` queda delgado y cumple el Protocol `MediaPublisher` sin cambios estructurales en `media_pipeline.py` ni en `interfaces.py`.
- **D3 (bootstrap pasa `workspace_dir`)**: añadido `workspace_dir=workspace_path` en la llamada a `FileSystemMediaPublisher(...)` en `application/bootstrap/runtime.py:122` y `application/bootstrap/__init__.py:122`. Cambio mínimo (1 LoC en cada archivo). Rompe la byte-igualdad bootstrap pre-feature-12 vs el código legacy original, pero los dos archivos siguen byte-a-byte iguales entre sí (`diff` exit 0 verificado). Necesario porque el use case abre su propio `DatabaseUnitOfWork(..., base_dir=workspace_dir)` y `ReelStateRepository.save_local_artifacts` requiere `base_dir`. Feature 14 lo restaurará al colapsar el bridge.
- **D4 (naming)**: el use case expone `execute(context, rendered_media, *, uow=None)` y `execute_existing(context, *, uow=None)`. El adapter `FileSystemMediaPublisher` mantiene `publish_media`, `publish_video`, `publish_existing_media`, `publish_existing_video` para no romper el Protocol `MediaPublisher` (`interfaces.py:71-83`) ni callers desconocidos. Patrón idéntico a features 10/11.
- **R1 (helpers compartidos duplicados)**: `_now_iso`, `_relative_path_text`, `_build_workflow_payload` están duplicados en `persist_local_artifacts.py:67-112` (frente a `media_services.py:67-112` originales). Trade-off explícito documentado en el docstring del módulo: feature 13 los moverá también a `publish_reel.py` (otra duplicación), feature 14 los unificará. Coste 42 LoC duplicados a cambio de independencia entre use cases.
- **R3 (`MediaRevision` moderno)**: el use case nuevo importa `from modules.reels.domain import MediaRevision` y construye el dataclass moderno (con `ingestion_source_id` y `external_source_id` en lugar de `wordpress_source_id` y `site_id`) para `uow.reels.revisions.save_revision(...)`. El import legacy `from repositories.stores.media_revision_store import MediaRevisionRecord` queda en `media_services.py:46` porque `_persist_workflow_transition` (composite, feature 13) sigue usándolo en `:627-643`.
- **R5 (class shadow `:507-508`)**: borrado al reescribir la clase `FileSystemMediaPublisher` como adapter delgado. `grep "class FileSystemMediaPublisher(FileSystemMediaPublisher)"` en el archivo: 0 hits. Los class shadows de `DefaultMediaRenderer` y `CompositeMediaPublisher` siguen vivos (out of scope).
- **R6 (`build_log_context`)**: conservado en el import de `core.logging` en `media_services.py:31`. Tres call sites siguen vivos en el archivo: `CompositeMediaPublisher.publish_existing_media:413` (la línea actual tras la reducción). El use case nuevo lo importa también para sus propios call sites (`POSTER_REQUIRED` y `EXISTING_MEDIA_REQUIRED`). No se repite el bug post-review feature 11.
- **R10 (firma `outbox.add_event` moderna)**: verificado leyendo `modules/delivery/infrastructure/outbox_repository.py:68-113`. La firma moderna usa kw-args modernos: `event_id`, `aggregate_type`, `aggregate_id`, `event_type`, `payload`, `agency_id`, `ingestion_source_id`, `external_source_id`, `source_property_id`, `status`, `created_at`, `available_at`. **Detalle clave**: el repositorio Postgres requiere `created_at` no vacío (la columna es `timestamp with time zone`), por lo que el use case pasa `created_at=_now_iso()`. El test integration confirmó esto (un primer run sin `created_at` falló con `psycopg.errors.InvalidDatetimeFormat: invalid input syntax for type timestamp with time zone: ""`). Adaptado y documentado.
- **R11 / D2 (`shared/storage/`)**: confirmado que `shared/storage/` no existe con storage paths funcionales. El use case sigue usando `context.storage_paths.generated_reels_root` y `generated_posters_root` directamente (mismo patrón que el legacy y que las features 10/11). Discrepancia documentada en el explore report §8 (D2); no se introduce indirección nueva. El acceptance literal de `feature_list.json` ("usa storage paths de `shared/storage/`") queda como deuda para el cierre de Phase 2 (feature 18) si el leader decide materializarla.

---

## 4. Decisiones de implementación adicionales

### 4.1 — `created_at=_now_iso()` añadido a `outbox.add_event`

El `OutboxRepository` moderno (`modules/delivery/infrastructure/outbox_repository.py:84-86`) usa `created_at or ""` y deja que Postgres rechace el string vacío en columnas timestamp. El legacy `outbox_event_store.add_event` aparentemente confiaba en defaults de DB que el schema moderno no expone. **Decisión**: pasar `created_at=_now_iso()` explícito desde el use case. Esto es coherente con el resto de inserts modernos (p. ej. `seed_tenant` en `tests/support/postgres.py` también pasa timestamps explícitos). Documentado en este reporte como aprendizaje para feature 13 (publish_reel hará el mismo insert en outbox y debe pasar `created_at` también).

### 4.2 — `external_source_id` normalizado en lowercase

El use case normaliza `context.site_id` con `str(context.site_id or "").strip().lower()` antes de pasarlo a los repos modernos (línea `:286`). Mismo patrón que `prepare_reel_assets.py:423`. Necesario para que el JOIN con `reels` (cuya PK es `(external_source_id, source_property_id)`) encuentre la fila previamente insertada por `ingest`/`prepare`.

### 4.3 — `del uow` en `execute_existing`

El método acepta `uow=None` por simetría con `execute(...)`, pero NO escribe DB (la persistencia de la transición workflow para el camino publish-only retry vive en el composite paso 4, feature 13). Se documenta inline con `del uow` y comentario en el método. Si feature 13 decide unificar, podrá hacerlo.

### 4.4 — Helpers `_persist_with_uow` extraído como staticmethod

El método de persistencia DB es un staticmethod (no necesita acceso a `self`). Recibe todo por kwargs explícitos. Patrón idéntico a `_persist_assets` en `prepare_reel_assets.py:413`.

---

## 5. Resultado de los checks de cierre

### Tests

```
$ pytest -q tests/unit/reels/test_persist_local_artifacts.py
7 passed in 1.09s

$ pytest -q tests/integration/reels/test_persist_local_artifacts_flow.py
1 passed in 2.86s

$ pytest -q tests/unit/reels/ tests/integration/reels/
53 passed in 46.06s

$ ./init.sh
...
396 passed in 223.31s (0:03:43)
[OK]    pytest verde
```

Baseline pre-feature-12: **388 tests** (post-feature-11 + fix post-review).
Post-feature-12: **396 tests** (388 + 7 unit + 1 integration). Esperado ≥ 396 — cumplido al pelo.

### Readiness

```
$ python -m apps.api --check
RUNTIME READY: Yes (sin warnings nuevos)

$ python -m apps.worker --check
Worker --check OK: kinds=reel_publish,scripted_render worker_count=1 lease=900s poll=0.50s
```

Ambos exit 0. `init.sh` verde end-to-end (incluye lint legacy WARN sobre 4 archivos en directorios legacy modificados — `media_services.py` + bootstrap `runtime.py`/`__init__.py` + uno extra del exporter de `default_services.py` por la cadena de re-exports; modificación quirúrgica permitida por las reglas de Phase 2).

### Repo limpio

- Sin `xfail`, sin `print()` debug, sin `TODO`/`FIXME` en archivos creados/modificados.
- `__pycache__` regenerado por pytest pero `.tmp_*` limpio (pytest borra la TEST_TEMP_ROOT al cerrar el contextmanager).
- `bootstrap/runtime.py` y `bootstrap/__init__.py` siguen byte-a-byte iguales entre sí (`diff` exit 0).

---

## 6. Desviaciones frente al plan del explorer

1. **LoC final 677 vs estimado ~670-690**: dentro del rango previsto. Ajuste fino.
2. **`created_at` añadido a `outbox.add_event`**: el explorer en R10 dejaba abierta la firma moderna. Tras verificarla, era obligatorio pasar `created_at` no vacío. Documentado en §4.1.
3. **`shutil` también borrado del import block**: el explorer mencionaba solo `os` y `should_cleanup_render_staging_dir`. Verificado con `grep "shutil\\."` que no quedan callers en `media_services.py`, así que se borró también. Resultado: import block 3 LoC más limpio.
4. **`resolve_property_poster_output_path` no se borró del import**: era un import muerto pre-existente del legacy (sin call sites). Out of scope (no introducido por esta feature). Queda para feature 13/14.
5. **No se amplió `_uow_stubs.py`**: los stubs UoW (`_StubReelStates` con `save_local_artifacts`, `_StubMediaRevisions` con `save_revision`, `_StubOutbox` con `add_event`) viven inline en `tests/unit/reels/test_persist_local_artifacts.py:50-82`. Decisión coherente con feature 11 (review feature 11 lo aceptó como patrón razonable: cada use case posee su Stubs si la API no se va a reusar). Si feature 13 va a reusar `add_event`, podrá ampliar `_uow_stubs.py` entonces.

---

**Fin del informe.**
