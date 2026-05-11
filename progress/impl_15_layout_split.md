# Impl — Feature 15 `rendering_layout_split`

> Partir `services/media/reel_rendering/layout.py` (1038 LoC) en 5 submódulos
> bajo `modules/rendering/infrastructure/layout/`, cada uno < 500 LoC,
> dejando un facade temporal de ~25 LoC en el path legacy. Conforme al plan
> del explorer (`progress/explore_feature_15_layout_split.md`).

---

## 1. Archivos creados / modificados

### Creados (5 submódulos + `__init__.py` + 5 tests + conftest)

| Archivo | LoC | Tipo |
|---------|-----|------|
| `modules/rendering/infrastructure/layout/models.py` | 148 | 5 dataclasses verbatim de `layout.py:26-151`: `LayoutWarning`, `BoxLayout`, `TextBlockLayout`, `TimedTextSegmentLayout`, `OverlayLayout`. `__all__` con los 5 nombres. |
| `modules/rendering/infrastructure/layout/text_measurement.py` | 477 | `MeasuredTextBlock` (renombrado de `_MeasuredTextBlock`, ahora público), 6 helpers privados (`_wrap_width_from_pixels`, `_estimate_line_width_pixels`, `_lines_fit_within_width`, `_candidate_font_sizes`, `_measure_text_block_with_single_line_preference`, `_build_measured_address_blocks`) y 2 funciones públicas (`measure_text_block`, `measure_address_blocks`). Cuerpos verbatim. Imports: stdlib + `services.media.reel_rendering.formatting` + `.models` (transitorio hasta feature 18). |
| `modules/rendering/infrastructure/layout/panels.py` | 412 | Constante `_SINGLE_LINE_TEXT_BLOCKS`, 3 helpers privados de panel (`_resolve_top_panel_height_range`, `_resolve_bottom_panel_height_range`, `_resolve_bottom_panel_y`), y las 2 funciones públicas `compose_top_panel` / `compose_bottom_panel`. Cuerpos verbatim de las fases A y B de `build_overlay_layout` (lines 642-763 y 765-936 del legacy) reescritos con kwargs explícitos. |
| `modules/rendering/infrastructure/layout/subtitles.py` | 134 | `_resolve_subtitle_caption` (privado) y `compose_subtitle_segments` (pública). Cuerpo verbatim de la fase C (lines 938-1006 + 1022-1028 del legacy) con kwargs explícitos. |
| `modules/rendering/infrastructure/layout/composition.py` | 107 | `build_overlay_layout` orquestador delgado. Calcula `outer_margin_x/y`, `panel_padding_x/y`, `panel_width` y delega en las 3 funciones `compose_*`. Ensambla `OverlayLayout` con concatenación de tuples (top + bottom) preservando el orden de `text_blocks`. |
| `tests/unit/rendering/conftest.py` | 106 | Helpers `build_property_data`, `build_template`, `build_slide` + 3 fixtures pytest. Reusables por los 5 archivos de test layout sin duplicar cada fixture. |
| `tests/unit/rendering/test_layout_models.py` | 176 | 7 tests sobre los 5 dataclasses. |
| `tests/unit/rendering/test_layout_text_measurement.py` | 154 | 10 tests sobre `MeasuredTextBlock`, `measure_text_block`, `measure_address_blocks`, `_candidate_font_sizes`, `_wrap_width_from_pixels`. |
| `tests/unit/rendering/test_layout_panels.py` | 164 | 6 tests sobre `compose_top_panel` y `compose_bottom_panel`. |
| `tests/unit/rendering/test_layout_subtitles.py` | 120 | 6 tests sobre `compose_subtitle_segments` y `_resolve_subtitle_caption`. |
| `tests/unit/rendering/test_layout_composition.py` | 121 | 7 tests sobre `build_overlay_layout` (orden de text_blocks, ber_badge flag, agency_logo flag, intro segment, slide count). |

### Modificados

| Archivo | Cambio |
|---------|--------|
| `modules/rendering/infrastructure/layout/__init__.py` | Placeholder vacío → 26 LoC re-exportando `BoxLayout`, `LayoutWarning`, `OverlayLayout`, `TextBlockLayout`, `TimedTextSegmentLayout`, `build_overlay_layout`. |
| `services/media/reel_rendering/layout.py` | 1038 → 27 LoC. Facade que re-exporta los 6 públicos del nuevo path. Preserva los 4 callers legacy bajo `services/media/reel_rendering/{filters,preparation,poster,manifest}.py`. |
| `modules/rendering/infrastructure/ffmpeg/filter_graph.py` | 1 línea. `from services.media.reel_rendering.layout import build_overlay_layout` → `from modules.rendering.infrastructure.layout import build_overlay_layout`. |
| `modules/rendering/infrastructure/ffmpeg/render_reel.py` | 1 línea. Idem. |
| `tests/test_reel_pipeline.py` | 1 línea (línea 20). Idem. |
| `feature_list.json` | Feature 15 status `pending` → `in_progress`. |

### NO modificados

- `services/media/reel_rendering/{filters,preparation,poster,manifest}.py` — siguen importando del facade hasta feature 18.
- `services/media/reel_rendering/{formatting,models,data,render,runtime}.py` — sin cambios. Layout consume 12 helpers de `formatting.py` cross-frontera.
- `tests/test_reel_pipeline.py` — solo cambia la línea 20 del import. El cuerpo de `OverlayLayoutTests` (tests 333-525) y los 14 invocaciones indirectas a `build_overlay_layout` quedan verbatim.
- `application/`, `apps/`, `shared/`, `settings/`, `alembic/`, `progress/` — sin cambios.

---

## 2. Refactor aplicado: firmas `compose_*`

El acceptance pide submódulos < 500 LoC. La función `build_overlay_layout`
legacy tenía ~389 LoC monolíticos; copiada verbatim sumaría ~700 LoC con
helpers, violando el límite. Solución del explore (§1.3-1.5): extraer las 3
fases secuenciales como funciones públicas con parámetros explícitos.

**Fase A → `compose_top_panel`** (panels.py)
```python
def compose_top_panel(
    property_data: PropertyReelData,
    settings: PropertyReelTemplate,
    *,
    has_ber_badge: bool,
    outer_margin_x: int,
    outer_margin_y: int,
    panel_padding_x: int,
    panel_padding_y: int,
    panel_width: int,
) -> tuple[
    BoxLayout | None,
    tuple[TextBlockLayout, ...],
    BoxLayout | None,
    tuple[LayoutWarning, ...],
]:
```

**Fase B → `compose_bottom_panel`** (panels.py)
```python
def compose_bottom_panel(
    property_data: PropertyReelData,
    settings: PropertyReelTemplate,
    *,
    top_panel: BoxLayout | None,
    has_agency_logo: bool,
    single_line_contact_email: bool,
    outer_margin_x: int,
    outer_margin_y: int,
    panel_padding_x: int,
    panel_padding_y: int,
    panel_width: int,
) -> tuple[
    BoxLayout | None,
    tuple[TextBlockLayout, ...],
    BoxLayout | None,
    BoxLayout | None,
    tuple[LayoutWarning, ...],
]:
```

**Fase C → `compose_subtitle_segments`** (subtitles.py)
```python
def compose_subtitle_segments(
    property_data: PropertyReelData,
    settings: PropertyReelTemplate,
    *,
    slides: tuple[PropertyReelSlide, ...] | list[PropertyReelSlide],
    slide_duration: float | None,
    cover_caption: str | None,
    bottom_panel: BoxLayout | None,
    panel_width: int,
    outer_margin_x: int,
    outer_margin_y: int,
    panel_padding_x: int,
) -> tuple[tuple[TimedTextSegmentLayout, ...], tuple[LayoutWarning, ...]]:
```

El cuerpo de cada función se preserva **verbatim** del legacy. Solo cambia
la firma: lo que antes eran locales calculados al inicio de
`build_overlay_layout` ahora son kwargs. El orquestador
(`composition.build_overlay_layout`) calcula esos valores una vez y los
pasa a las 3 fases en el orden correcto (top → bottom → subtitles).

**Renames a público**: `_MeasuredTextBlock` → `MeasuredTextBlock`,
`_measure_text_block` → `measure_text_block`, `_measure_address_blocks` →
`measure_address_blocks` (los 3 son consumidos cross-submódulo). Los
helpers que solo se usan dentro de `text_measurement.py` conservan el
underscore (`_wrap_width_from_pixels`, `_estimate_line_width_pixels`,
`_lines_fit_within_width`, `_candidate_font_sizes`,
`_build_measured_address_blocks`,
`_measure_text_block_with_single_line_preference`).

---

## 3. Decisiones del explore respetadas

- **§0 facade vs borrar**: facade SÍ. Razón: 4 de los 7 callers viven bajo
  `services/media/reel_rendering/*` (legacy frozen, feature 18 los retira).
  Reapuntarlos ahora crea churn que feature 18 deshace.
- **§1.1-1.5 estructura de 5 submódulos**: implementada tal cual. Todos los
  submódulos < 500 LoC (max: `text_measurement.py` 477 LoC, `panels.py`
  412 LoC).
- **§1.6 `__init__.py`**: re-exports públicos según el listado del explore.
- **§1.7 facade**: 27 LoC con docstring que apunta a feature 18 como
  retirada futura.
- **§3 — actualizar 3 callers** y dejar 4 callers legacy en el facade:
  hecho. `modules/rendering/infrastructure/ffmpeg/filter_graph.py:9`,
  `modules/rendering/infrastructure/ffmpeg/render_reel.py:18` y
  `tests/test_reel_pipeline.py:20` ahora apuntan al nuevo path.
- **§4.2 5 archivos de test bajo `tests/unit/rendering/`**: implementado.
  36 tests nuevos sumados (7 + 10 + 6 + 6 + 7) — superan el "≥ 8" del
  prompt.
- **R8 alternativa en `text_measurement.py`**: NO se aplicó. El archivo
  cabe en 477 LoC, holgadamente bajo 500. No se splitteó a
  `address_text_layout.py`.
- **R10/R11/R12 orden de aglutinado**: el orquestador concatena
  `tuple(top_text_blocks) + tuple(bottom_text_blocks)` y `warnings.extend`
  en orden top → bottom → subtitles. Verificado por tests legacy
  `OverlayLayoutTests` y por el unit test
  `test_build_overlay_layout_text_blocks_order_top_then_bottom`.
- **R15 `MeasuredTextBlock` rename**: público en el path nuevo, NO
  re-exportado en el facade (no estaba en `__all__` original).
- **R16 byte-igualdad de `to_dict()`**: las 5 dataclasses se mueven con sus
  `to_dict()` exactos. Tests legacy verdes.
- **R18 conftest compartido**: creado
  `tests/unit/rendering/conftest.py` con helpers reusables.

---

## 4. Decisiones de implementación adicionales

### 4.1 — `_measure_text_block_with_single_line_preference` queda en `text_measurement.py`

El explore lo marcaba como privado del submódulo. Sin embargo, lo consume
`compose_top_panel` (fase A) cross-submódulo para el bloque "status".
Solución: lo dejo en `text_measurement.py` como privado (`_` prefix
preservado del legacy) y `panels.py` lo importa explícitamente desde el
módulo. Esto es coherente con la convención "privadas con underscore" pero
permite el cruce de import necesario. Alternativa rechazada: renombrar a
público — innecesario ya que tiene **un solo caller cross-submódulo**.

### 4.2 — `panels.py` 412 LoC vs ~360 estimados

Ligeramente por encima del estimado por docstring del módulo + dos
docstrings de funciones + formateo con paréntesis explícitos en los
returns tipados (`tuple[..., tuple[...], ...]`). Aún por debajo del límite
de 500 LoC.

### 4.3 — `text_measurement.py` 477 LoC vs ~480 estimados

Justo dentro del rango previsto. El fallback de §1.2 (extraer
`address_text_layout.py`) NO se aplicó.

### 4.4 — Tests floats con `pytest.approx`

Los tests de `subtitles` que comparan `start_time`/`end_time` usan
`pytest.approx(...)` para satisfacer el linter (S1244 "do not perform
equality checks with floating point values").

### 4.5 — Tests con cleanup de captions

`normalize_caption` agrega punto final si falta (`"Caption A"` →
`"Caption A."`). Los tests de `subtitles` usan `.startswith(...)` para no
acoplar el assert a esa transformación.

### 4.6 — Imports en `panels.py`

El módulo necesita 7 helpers de `services.media.reel_rendering.formatting`
(`build_agent_lines`, `build_display_price`,
`build_property_header_details_line`,
`build_property_header_viewing_times_line`, `build_status_ribbon_text`,
`resolve_agency_logo_box_size`, `resolve_agent_image_size`,
`resolve_ber_icon_size`, `resolve_font_size_bounds`) más
`PropertyReelData`/`PropertyReelTemplate` de
`services.media.reel_rendering.models`. Todos transitorios hasta feature
18.

---

## 5. Resultado de los checks de cierre

### Tests

```
$ ./.venv/Scripts/python.exe -m pytest -q tests/test_reel_pipeline.py::OverlayLayoutTests
....                                                                     [100%]
4 passed in 0.93s

$ ./.venv/Scripts/python.exe -m pytest -q tests/test_reel_pipeline.py
..............................                                           [100%]
30 passed in 8.84s

$ ./.venv/Scripts/python.exe -m pytest -q tests/unit/rendering/
.................................................                       [100%]
49 passed in 0.49s

$ ./.venv/Scripts/python.exe -m pytest -q
........................................................................ [ 15%]
........................................................................ [ 31%]
........................................................................ [ 47%]
........................................................................ [ 63%]
........................................................................ [ 79%]
........................................................................ [ 95%]
.....................                                                    [100%]
453 passed in 207.54s (0:03:27)
```

Baseline pre-feature-15: **417 tests** (post-feature-14).
Post-feature-15: **453 tests** (417 + 36 unit nuevos). Esperado ≥ 425 — cumplido (+36 nuevos).

### Readiness

```
$ ./.venv/Scripts/python.exe -m apps.api --check
... apps.api --check verde
EXIT_API: 0

$ ./.venv/Scripts/python.exe -m apps.worker --check
Worker --check OK: kinds=reel_publish, scripted_render worker_count=1 lease=900s poll=0.50s
EXIT_WORKER: 0
```

Ambos exit 0.

### `init.sh`

```
── 5. Ejecutando readiness checks ──────────────────────
[OK]    apps.api --check verde
[OK]    apps.worker --check verde

── 6. Ejecutando tests ─────────────────────────────────
453 passed in 194.79s (0:03:14)
[OK]    pytest verde

── 7. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

`init.sh` reporta WARN en step 4 ("5 archivos modificados en directorios
legacy en últimas 24h"): es la modificación esperada en
`services/media/reel_rendering/layout.py` (reducido a facade) y en
`tests/test_reel_pipeline.py` (1 línea de import). Coherente con el
patrón aplicado en features 10-14.

### Repo limpio

- Sin `xfail`, sin `print()` debug, sin `TODO`/`FIXME` en archivos
  creados/modificados (`grep -nE "print\(|xfail|TODO|FIXME"` en
  `modules/rendering/infrastructure/layout/` y
  `tests/unit/rendering/test_layout_*.py`: 0 hits).
- Sin `__pycache__/.tmp_*` residual fuera de los gestionados por pytest.
- `services/media/reel_rendering/layout.py` es ahora un facade de 27 LoC.
- `tests/test_reel_pipeline.py` cambió 1 sola línea (la 20).
- `OverlayLayoutTests` (4 tests) verde verbatim.
- `feature_list.json` feature 15 status `in_progress` (closer la promueve a
  `done`).

---

## 6. Desviaciones frente al plan del explorer

1. **`models.py` 148 LoC vs ~140 estimados**: ligero exceso por docstring
   de módulo. Sin impacto.
2. **`panels.py` 412 LoC vs ~360 estimados**: ~52 LoC por encima por
   docstrings y formateo de returns multi-tuple. Aún por debajo de 500.
3. **`subtitles.py` 134 LoC vs ~120 estimados**: ~14 LoC más por
   docstring de módulo. Sin impacto.
4. **`composition.py` 107 LoC vs ~110 estimados**: dentro del rango.
5. **Test count: 36 vs 27-34 estimados (§4.3 del explore)**: ligeramente
   por encima por dividir algunos casos relevantes (p. ej. el flag
   `has_ber_badge` se cubre con dos tests separados — uno True y uno
   False — para mejor diagnostico de fallo).
6. **`_measure_text_block_with_single_line_preference` import
   cross-submódulo (4.1)**: el explore lo planteaba como privado
   exclusivo de `text_measurement.py`; en la práctica `compose_top_panel`
   lo necesita. Se importa con el `_` prefix preservado, lo cual es
   técnicamente importable aunque no idiomático. Alternativa simétrica:
   renombrar a público. Decisión: preservar underscore por consistencia
   con el legacy y porque el caller único es interno al paquete `layout`.
7. **`MusicTrackPayload`/etc**: no aplica (feature 6).

---

**Fin del informe.**
