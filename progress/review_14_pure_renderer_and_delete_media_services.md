# Review — feature 14 (`rendering_pure_renderer_and_delete_media_services`)

**Veredicto:** APPROVED

## Resumen

Se validó la acceptance literal y todas las decisiones del explore (Opción C, D1-D11). El renderer puro `DefaultMediaRenderer` queda extraído en `modules/rendering/application/frame_composition.py` (184 LoC, < 500). Los 4 adapters delgados (`DefaultPropertyInfoService`, `DefaultMediaPreparationService`, `FileSystemMediaPublisher`, `CompositeMediaPublisher`) viven en `application/bootstrap/pipeline_adapters.py` (237 LoC, ≤ 250). `application/pipeline/media_services.py` y `application/pipeline/default_services.py` están borrados físicamente. `application/pipeline/__init__.py` se redujo a 1 LoC (package marker). `application/bootstrap/runtime.py` y `__init__.py` siguen byte-iguales (`diff` exit 0). 8 unit tests nuevos en `tests/unit/rendering/test_frame_composition.py` (382 LoC). `./init.sh` verde con **417 passed** en 185.16 s. `apps.api --check` y `apps.worker --check` exit 0.

## Checks superados

### A. Acceptance literal

- [x] **A1** Existe `modules/rendering/application/frame_composition.py:51-184` con `DefaultMediaRenderer`. 184 LoC < 500. Single archivo.
- [x] **A2** `application/pipeline/media_services.py` no existe en filesystem. `ls application/pipeline/` confirma: `__init__.py`, `content_generation.py`, `interfaces.py`, `job_runner.py`, `media_pipeline.py` (sin `media_services.py` ni `default_services.py`).
- [x] **A3** Bridge worker actualizado para no importarlo. `apps/worker/runtime.py` no tiene imports de `application.pipeline.media_services` ni `default_services`. La cadena indirecta worker → bootstrap pasa por `application/bootstrap/{runtime,__init__}.py:7-13` que ahora importan de `application.bootstrap.pipeline_adapters` y `modules.rendering.application.frame_composition` (verificado en runtime.py:7-13).
- [x] **A4** `tests/unit/rendering/test_frame_composition.py` (382 LoC) cubre la lógica trasladada con 8 tests significativos:
  1. `test_render_media_returns_rendered_artifact_with_uuid_revision_id`
  2. `test_render_media_creates_staging_dir_under_generated_reels_root`
  3. `test_render_media_invokes_prepare_reel_render_assets_with_workspace_and_template`
  4. `test_render_media_invokes_write_manifest_with_correct_paths`
  5. `test_render_media_invokes_generate_reel_with_correct_paths`
  6. `test_render_media_invokes_generate_poster_with_correct_paths`
  7. `test_render_video_alias_delegates_to_render_media`
  8. `test_build_render_data_maps_property_fields`
  Todos PASS. ≥ 6 cumplido.
- [x] **A5** `pytest -q` termina **417 passed** en 185.16 s (init.sh).
- [x] **A6** `python -m apps.worker --check` exit 0. Output: `Worker --check OK: kinds=reel_publish,scripted_render worker_count=1 lease=900s poll=0.50s`.
- [x] **A7** `python -m apps.api --check` exit 0. Output: `RUNTIME READY: Yes`.

### B. Calidad del código

- [x] **B1** `modules/rendering/application/frame_composition.py:25-46` solo importa de `application.types` (legacy, aceptado en Phase 2), `core.logging` (legacy, aceptado), `services.media.reel_rendering.*` (servicios compartidos, aceptado). NO importa de `<otro>.application` ni `<otro>.infrastructure`.
- [x] **B2** `application/bootstrap/pipeline_adapters.py` 237 LoC ≤ 250. Contiene los 4 adapters legacy (`DefaultPropertyInfoService:52-83`, `DefaultMediaPreparationService:86-130`, `FileSystemMediaPublisher:133-178`, `CompositeMediaPublisher:181-229`) con `__init__` que ignora `unit_of_work_factory` con `del` (verificado líneas 72, 105, 152, 201). El re-export de `LocalPhotoSelectionEngine` se omite del `__all__` (decisión consciente, §6 R5: cero callers externos). Razonable: el símbolo se usa internamente vía import directo de `modules.reels.application.use_cases.prepare_reel_assets` (line 45-48).
- [x] **B3** Sin `print()`, sin `xfail`, sin `TODO`/`FIXME` en archivos creados/modificados (verificado con grep en `frame_composition.py`, `pipeline_adapters.py`, `test_frame_composition.py`: 0 hits).
- [x] **B4** Logs verbatim — title preservado: `frame_composition.py:125` "Reel Render Completed" coincide con el title legacy del cuerpo eliminado (`media_services.py:185` original).
- [x] **B5** `DefaultMediaRenderer` mantiene firma legacy: `__init__(self, workspace_dir: str | Path)` (`frame_composition.py:52`), `render_media(context, prepared_assets)` (`:55-60`), `render_video(context, selected_photos)` (`:62-67`). Sin DB, sin `unit_of_work_factory`. Verificado con grep `unit_of_work|DatabaseUnitOfWork` en `frame_composition.py`: 0 hits.
- [x] **B6** Bootstrap byte-igualdad: `diff application/bootstrap/runtime.py application/bootstrap/__init__.py` exit 0 (verificado).

### C. Tests

- [x] **C1** Unit tests usan `monkeypatch.setattr(fc_module, "<primitive>", _fake)` sobre las primitivas top-level del módulo nuevo (`prepare_reel_render_assets`, `write_property_reel_manifest_from_data`, `generate_property_reel_from_data`, `generate_property_poster_from_data`, plus `build_reel_template_for_render_profile` y `build_local_selected_slides`). Verificado en `test_frame_composition.py:91-145` (helper `_patch_primitives`). NO ejecutan ffmpeg real.
- [x] **C2** Tests de features 10-13 siguen verdes sin tocarlos. Baseline 409 + 8 nuevos = 417 (verificado en init.sh).
- [x] **C3** `tests/test_reel_pipeline.py` (1381 LoC, legacy) verde sin tocar. Verificado en init.sh suite verde.

### D. Acoplamientos / borrados

- [x] **D1** `application/pipeline/media_services.py` borrado físicamente. `ls application/pipeline/` confirma: solo 5 archivos no borrados.
- [x] **D2** `application/pipeline/default_services.py` borrado físicamente. `ls application/pipeline/` confirma.
- [x] **D3** `application/pipeline/__init__.py` reducido a 1 LoC (`# Empty package marker for application.pipeline`). ≤ 5 LoC. Verificado con `wc -l`.
- [x] **D4** `application/pipeline/media_pipeline.py`, `interfaces.py`, `job_runner.py`, `content_generation.py` siguen presentes (`ls application/pipeline/`).
- [x] **D5** `apps/worker/runtime.py` no se tocó. La acceptance "Bridge worker actualizado para no importarlo" se satisface vacuamente (worker ya no importaba `media_services.py` directamente; la cadena indirecta vía bootstrap quedó actualizada).
- [x] **D6** `apps/api/app_factory.py` no se tocó.

### F. Schema

- [x] **F1** Sin nueva migración en `alembic/versions/`. `ls alembic/versions/`: solo `20260501_0001_initial_schema.py` y `__pycache__/`. Conforme: feature 14 no toca schema.

### Verificaciones de Ejecución

| # | Comando | Resultado |
|---|---------|-----------|
| 1 | `ls application/pipeline/` | Solo `__init__.py`, `content_generation.py`, `interfaces.py`, `job_runner.py`, `media_pipeline.py`. **OK**. |
| 2 | `wc -l` archivos nuevos | `frame_composition.py` 184, `pipeline_adapters.py` 237, `test_frame_composition.py` 382. Todos < 500. **OK**. |
| 3 | `Grep "from application.pipeline.media_services\|from application.pipeline.default_services\|import application.pipeline.media_services\|import application.pipeline.default_services"` excluyendo `progress/` y `__pycache__/` | **0 hits**. **OK**. |
| 4 | `Grep "DefaultMediaRenderer"` en `apps/`, `modules/`, `services/`, `tests/`, `application/` | Definición en `modules/rendering/application/frame_composition.py:51`, imports en `application/bootstrap/runtime.py:13` y `__init__.py:13`, uso en líneas 117 de cada bootstrap. Otros hits están en tests (`tests/unit/rendering/test_frame_composition.py`) y docs. **OK**. |
| 5 | `diff application/bootstrap/runtime.py application/bootstrap/__init__.py` | exit 0. **OK**. |
| 6 | `./init.sh` | **417 passed** in 185.16s. ≥ 415 esperado. **OK**. |
| 7 | `python -m apps.worker --check` | exit 0. **OK**. |
| 8 | `python -m apps.api --check` | exit 0. **OK**. |

## Confirmación de checks de cierre

| Check | Resultado |
|-------|-----------|
| `wc -l modules/rendering/application/frame_composition.py` | 184 (< 500) |
| `wc -l application/bootstrap/pipeline_adapters.py` | 237 (≤ 250) |
| `wc -l tests/unit/rendering/test_frame_composition.py` | 382 (8 tests) |
| `wc -l application/pipeline/__init__.py` | 1 (≤ 5) |
| `ls application/pipeline/media_services.py` | no existe (borrado) |
| `ls application/pipeline/default_services.py` | no existe (borrado) |
| `ls alembic/versions/` | solo migración inicial (sin nueva migración) |
| `./init.sh` | 417 passed in 185.16s |
| `apps.api --check` / `apps.worker --check` | exit 0 ambos |
| `diff bootstrap/runtime.py bootstrap/__init__.py` | exit 0 |
| `grep "from application.pipeline.media_services\|default_services"` en código vivo | 0 hits |
| `grep "DefaultMediaRenderer"` en código vivo | 1 definición en frame_composition.py + 2 imports en bootstrap (correcto) |
| `grep "print\|xfail\|TODO\|FIXME"` en archivos nuevos | 0 hits |
| `grep "unit_of_work\|DatabaseUnitOfWork"` en frame_composition.py | 0 hits (renderer puro, sin DB) |
| Class shadow `DefaultMediaRenderer` | borrado (no se reescribe en frame_composition.py) |

## Recorrido de CHECKPOINTS.md

- **C1 (arnés completo)**: [x] `init.sh` exit 0; archivos base presentes.
- **C2 (estado coherente)**: [x] `feature_list.json` feature 14 en `in_progress` (closer la promueve a `done`); `progress/current.md` describe la sesión activa; `progress/history.md` con entradas previas.
- **C3 (arquitectura)**: [x] `frame_composition.py` no importa de `<otro>.application` ni `<otro>.infrastructure`; ningún módulo nuevo importa SQLAlchemy en `domain/`; los repos no commitean. Modificaciones en `application/` son las legítimas para Phase 2 (compat shims, conforme a `phase_2_operating_rules.md` §2).
- **C4 (verificación real)**: [x] 8 unit tests + 0 integration (la acceptance solo pide unit, conforme); `pytest -q` 417 verdes; `apps.api --check` y `apps.worker --check` exit 0.
- **C5 (schema)**: [x] No se modificó `shared/db/orm.py`; sin nueva migración. No aplica `upgrade head`/`downgrade -1`.
- **C6 (cierre limpio)**: [x] Sin `__pycache__/.tmp_*` residual; feature_list status correcto; sin `print()` debug; sin TODOs.

## Sugerencias menores (no bloquean)

1. `application/bootstrap/pipeline_adapters.py` 237 LoC vs 165-180 estimados: ligeramente por encima por docstrings extensos. Aún por debajo del límite. Aceptable.
2. `frame_composition.py` 184 LoC vs 140 estimados: ligeramente por encima por docstring + `__all__`. Aceptable.
3. `test_frame_composition.py` 382 LoC vs 250-350 estimados: ligeramente por encima por helper `_patch_primitives` exhaustivo. Aceptable.
4. `__init__.py` reducido a 1 LoC con comentario marker en lugar de borrar el archivo: decisión defensiva del implementer (bajo Windows + paquete con submódulos vivos). No afecta ningún test. Aceptable.
5. Re-export de `LocalPhotoSelectionEngine` omitido en `pipeline_adapters.__all__`: confirmado por grep que ningún caller externo lo importa de bootstrap; tests y otros consumidores van directo a `modules.reels.application.use_cases.prepare_reel_assets`. Decisión consistente con la directriz del explore §6 R5 / §8 D7. Aceptable.

**Fin de la review.**
