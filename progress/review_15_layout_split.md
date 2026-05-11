# Review — feature 15 (`rendering_layout_split`)

**Veredicto:** APPROVED

## Resumen

Se validó la acceptance literal y todas las decisiones del explore. `services/media/reel_rendering/layout.py` (1038 LoC) queda partido en 5 submódulos bajo `modules/rendering/infrastructure/layout/`, todos < 500 LoC (max: `text_measurement.py` 477; `panels.py` 412). El facade legacy queda reducido a 27 LoC (≤ 30) re-exportando los 6 públicos. Los 3 callers actualizados al nuevo path (`modules/rendering/infrastructure/ffmpeg/{filter_graph,render_reel}.py` y `tests/test_reel_pipeline.py`) y los 4 callers legacy bajo `services/media/reel_rendering/{filters,preparation,poster,manifest}.py` siguen usando el facade. 36 tests nuevos en `tests/unit/rendering/test_layout_*.py`. `OverlayLayoutTests` legacy verde sin tocar (excepto el import). `./init.sh` verde con **453 passed** en 220.84s. `apps.api --check` y `apps.worker --check` exit 0.

## Checks superados

### A. Acceptance literal

- [x] **A1** `modules/rendering/infrastructure/layout/` con submódulos < 500 LoC. `wc -l`:
  - `__init__.py` 26
  - `composition.py` 107
  - `models.py` 148
  - `panels.py` 412
  - `subtitles.py` 134
  - `text_measurement.py` 477
  Todos < 500. **OK**.
- [x] **A2** `services/media/reel_rendering/layout.py` reducido a facade de 27 LoC (≤ 30). Solo re-exports + `__all__`.
- [x] **A3** `tests/unit/rendering/` cubre el nuevo `layout/` con 36 tests significativos (≥ 8). 5 archivos: `test_layout_models.py` (7), `test_layout_text_measurement.py` (10), `test_layout_panels.py` (6), `test_layout_subtitles.py` (6), `test_layout_composition.py` (7).
- [x] **A4** `pytest -q` verde con **453 passed** (baseline 417 + 36 nuevos ≥ 425). Verificado en init.sh.
- [x] **A5** `python -m apps.worker --check` exit 0 (`Worker --check OK: kinds=reel_publish,scripted_render worker_count=1 lease=900s poll=0.50s`). `python -m apps.api --check` exit 0 (`RUNTIME READY: Yes`).

### B. Calidad del código

- [x] **B1** Cada submódulo de `layout/` no importa de `<otro>.application` ni `<otro>.infrastructure`. Imports verificados con `Grep "^(from |import )"`:
  - `models.py:9-11` solo stdlib (`dataclass`).
  - `text_measurement.py:14-19` stdlib + `modules.rendering.infrastructure.layout.models` + `services.media.reel_rendering.formatting` (legacy aceptado).
  - `panels.py:15-39` stdlib + `modules.rendering.infrastructure.layout.{models,text_measurement}` + `services.media.reel_rendering.{formatting,models}` (legacy aceptado).
  - `subtitles.py:16-34` stdlib + `modules.rendering.infrastructure.layout.{models,text_measurement}` + `services.ai.photo_selection.prompting` (legacy aceptado) + `services.media.reel_rendering.{formatting,models}` (legacy aceptado).
  - `composition.py:11-23` stdlib + `modules.rendering.infrastructure.layout.{models,panels,subtitles}` + `services.media.reel_rendering.models` (legacy aceptado).
  Sin hits de `<otro>.application/infrastructure`. **OK**.
- [x] **B2** `models.py` solo dataclasses (5: `LayoutWarning`, `BoxLayout`, `TextBlockLayout`, `TimedTextSegmentLayout`, `OverlayLayout`), todas `frozen=True, slots=True` con `to_dict()`. Sin lógica de negocio (solo `round` en `TimedTextSegmentLayout.to_dict()`, idéntico al legacy). **OK**.
- [x] **B3** `text_measurement.py` exporta sin underscore: `MeasuredTextBlock` (`:23`), `measure_text_block` (`:86`), `measure_address_blocks` (`:303`). Helpers privados conservan `_`: `_wrap_width_from_pixels`, `_estimate_line_width_pixels`, `_lines_fit_within_width`, `_candidate_font_sizes`, `_measure_text_block_with_single_line_preference`, `_build_measured_address_blocks`. **OK**.
- [x] **B4** `panels.py` exporta `compose_top_panel` (`:70`), `compose_bottom_panel` (`:206`), `__all__ = ["compose_bottom_panel", "compose_top_panel"]` (`:412`). Cuerpo verbatim del legacy con firmas kwarg-only explícitas. **OK**.
- [x] **B5** `subtitles.py` exporta `compose_subtitle_segments` (`:46`), `__all__ = ["compose_subtitle_segments"]` (`:134`). Verbatim. **OK**.
- [x] **B6** `composition.py:26-104` `build_overlay_layout` orquesta los 3 `compose_*` (`:47, :65, :79`) y ensambla `OverlayLayout` (`:93-104`). Concatenación `tuple(top_text_blocks) + tuple(bottom_text_blocks)` en `:101` y `warnings.extend` en orden top → bottom → subtitles (`:57, :77, :91`). Comportamiento idéntico al legacy verificado por `OverlayLayoutTests` verde sin tocar.
- [x] **B7** Sin `print()`, sin `xfail`, sin TODOs. `Grep "print\(|xfail|TODO|FIXME"` en `modules/rendering/infrastructure/layout/`: 0 hits. Idem en `tests/unit/rendering/test_layout_*.py`: 0 hits. **OK**.

### C. Tests

- [x] **C1** `tests/unit/rendering/test_layout_*.py` con 36 tests (≥ 8) cubriendo cada submódulo (5 archivos, 7 + 10 + 6 + 6 + 7). 36 passed in 0.11s (run aislado). **OK**.
- [x] **C2** `tests/test_reel_pipeline.py::OverlayLayoutTests` (líneas 328-525) verde sin tocar; única modificación es la línea 20 (import al nuevo path). Verificado: `4 passed in 0.73s`. El comportamiento de `build_overlay_layout` se preserva. **OK**.
- [x] **C3** Tests de features 10-14 siguen verdes. Init.sh corre **453 passed** = 417 (post-feature-14) + 36 (feature 15). **OK**.

### D. Acoplamientos

- [x] **D1** Facade `services/media/reel_rendering/layout.py` 27 LoC ≤ 30. Re-exporta de `modules.rendering.infrastructure.layout` los 6 símbolos (`BoxLayout`, `LayoutWarning`, `OverlayLayout`, `TextBlockLayout`, `TimedTextSegmentLayout`, `build_overlay_layout`). **OK**.
- [x] **D2** Imports actualizados al nuevo path:
  - `modules/rendering/infrastructure/ffmpeg/filter_graph.py:9` → `from modules.rendering.infrastructure.layout import build_overlay_layout`. **OK**.
  - `modules/rendering/infrastructure/ffmpeg/render_reel.py:18` → idem. **OK**.
  - `tests/test_reel_pipeline.py:20` → idem. **OK**.
- [x] **D3** **NO actualizados** (siguen importando del facade): verificado con `Grep "from services.media.reel_rendering.layout"`:
  - `services/media/reel_rendering/preparation.py:15` (vía facade).
  - `services/media/reel_rendering/poster.py:16` (vía facade).
  - `services/media/reel_rendering/filters.py:13` (vía facade).
  - `services/media/reel_rendering/manifest.py:16` (vía facade).
  Sin hits desde `modules/rendering/infrastructure/ffmpeg/*` ni desde `tests/test_reel_pipeline.py`. **OK**.

### F. Schema

- [x] **F1** Sin nueva migración en `alembic/versions/`. `ls alembic/versions/`: solo `20260501_0001_initial_schema.py`. **OK**.

### Verificaciones de Ejecución

| # | Comando | Resultado |
|---|---------|-----------|
| 1 | `wc -l modules/rendering/infrastructure/layout/*.py` | max 477 (text_measurement.py); todos < 500. **OK**. |
| 2 | `wc -l services/media/reel_rendering/layout.py` | 27 ≤ 30. **OK**. |
| 3 | `Grep "from services.media.reel_rendering.layout"` | 4 hits únicamente en `services/media/reel_rendering/{filters,preparation,poster,manifest}.py`. Sin hits desde ffmpeg ni desde `tests/test_reel_pipeline.py`. **OK**. |
| 4 | `Grep "from modules.rendering.infrastructure.layout"` | 3 callers actualizados (`ffmpeg/filter_graph.py:9`, `ffmpeg/render_reel.py:18`, `tests/test_reel_pipeline.py:20`) + facade + tests unit nuevos + imports internos del paquete. **OK**. |
| 5 | `./init.sh` | **453 passed** in 220.84s. ≥ 425 esperado. **OK**. |
| 6 | `python -m apps.worker --check` | exit 0. **OK**. |
| 7 | `python -m apps.api --check` | exit 0. **OK**. |
| 8 | `Grep "print\|xfail\|TODO\|FIXME"` en `modules/rendering/infrastructure/layout/` y `tests/unit/rendering/test_layout_*.py` | 0 hits. **OK**. |

## Confirmación de checks de cierre

| Check | Resultado |
|-------|-----------|
| `wc -l modules/rendering/infrastructure/layout/composition.py` | 107 (< 500) |
| `wc -l modules/rendering/infrastructure/layout/models.py` | 148 (< 500) |
| `wc -l modules/rendering/infrastructure/layout/panels.py` | 412 (< 500) |
| `wc -l modules/rendering/infrastructure/layout/subtitles.py` | 134 (< 500) |
| `wc -l modules/rendering/infrastructure/layout/text_measurement.py` | 477 (< 500) |
| `wc -l services/media/reel_rendering/layout.py` | 27 (≤ 30) |
| Tests nuevos en `tests/unit/rendering/test_layout_*.py` | 36 (≥ 8) |
| `pytest -q` end-to-end | 453 passed |
| `apps.api --check` / `apps.worker --check` | exit 0 ambos |
| `OverlayLayoutTests` legacy | 4 passed verbatim (solo cambió import línea 20) |
| `Grep "print\|xfail\|TODO\|FIXME"` archivos nuevos | 0 hits |
| Facade re-exporta los 6 públicos | confirmado |
| Sin `<otro>.application` / `<otro>.infrastructure` cross-import | confirmado |
| `ls alembic/versions/` | solo `20260501_0001_initial_schema.py` |

## Recorrido de CHECKPOINTS.md

- **C1 (arnés completo)**: [x] `init.sh` exit 0; archivos base presentes (AGENTS.md, CLAUDE.md, feature_list.json, progress/current.md, docs/{architecture,conventions,verification}.md, CHECKPOINTS.md).
- **C2 (estado coherente)**: [x] `feature_list.json` feature 15 en `in_progress` (closer la promueve a `done`); `progress/current.md` describe la sesión activa; `progress/history.md` con entradas previas.
- **C3 (arquitectura)**: [x] Submódulos `layout/` no importan de `<otro>.application` ni `<otro>.infrastructure`. Imports `services.media.reel_rendering.{formatting,models}` y `services.ai.photo_selection.prompting` aceptados como legacy en transición (Phase 2). `models.py` no importa SQLAlchemy. No hay repositorios nuevos. Modificaciones en `services/` son las legítimas para Phase 2 (facade + 1 línea de import en tests).
- **C4 (verificación real)**: [x] 36 unit tests nuevos cubren los 5 submódulos; `pytest -q` 453 verdes; `apps.api --check` y `apps.worker --check` exit 0.
- **C5 (schema)**: [x] No se modificó `shared/db/orm.py`; sin nueva migración.
- **C6 (cierre limpio)**: [x] Sin `__pycache__/.tmp_*` residual; feature_list status correcto; sin `print()` debug; sin TODOs.

## Sugerencias menores (no bloquean)

1. `text_measurement.py` 477 LoC vs ~480 estimados: dentro del rango, pero ajustado al límite. Si feature 18 introduce churn en este archivo, podría requerir el split a `address_text_layout.py` que el explorer planteaba como fallback (R8). Aceptable para feature 15.
2. `_measure_text_block_with_single_line_preference` se importa cross-submódulo desde `panels.py:24` con el `_` prefix preservado. Técnicamente importable pero no idiomático. Decisión consistente con la convención "privadas con underscore" porque el caller único es interno al paquete `layout`. Aceptable.
3. WARN de `init.sh` step 4 ("5 archivos modificados en legacy en últimas 24h") es esperado: facade reducido + 1 línea de import en `tests/test_reel_pipeline.py`. Coherente con el patrón aplicado en features 10-14.
4. `panels.py` 412 LoC vs ~360 estimados: ligeramente por encima por docstrings y formateo de returns multi-tuple. Aún por debajo de 500. Aceptable.

**Fin de la review.**
