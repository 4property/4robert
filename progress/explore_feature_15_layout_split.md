# Explore — Feature 15 `rendering_layout_split`

> Mapa de extracción de `services/media/reel_rendering/layout.py` (1038 LoC) a
> submódulos bajo `modules/rendering/infrastructure/layout/`. Mantener un
> facade temporal en `services/media/reel_rendering/layout.py` mientras
> queden 7 call sites externos al propio archivo. Mismo patrón aplicado en
> features 10-14: borrar legacy a medida que se mueve, sin compat shims más
> allá del facade necesario.

Contexto leído (en el orden exigido por la tarea):

- `feature_list.json` (entry id=15, acceptance literal). Referencias además
  a feature 18 que cierra Phase 2 borrando `services/`.
- `progress/explore_feature_14_pure_renderer_and_delete_media_services.md`
  (patrón Opción C: archivos < 500 LoC, `__init__.py` re-export, decisión
  facade vs borrar). Concreta D9 ("layout.py NO se toca en feature 14;
  acceptance feature 15 lo cubre").
- `progress/impl_14_pure_renderer_and_delete_media_services.md` (LoC reales
  de cierre, decisiones del implementer) y
  `progress/review_14_pure_renderer_and_delete_media_services.md`
  (APPROVED, 417 tests verdes).
- `services/media/reel_rendering/layout.py` (1038 LoC, leído íntegro). 5
  dataclasses públicas + 1 privada (`_MeasuredTextBlock`), 11 funciones
  privadas, 1 función pública (`build_overlay_layout`).
- `services/media/reel_rendering/__init__.py` (34 LoC, re-exports). **NO**
  re-exporta nada de `layout.py`. Los 7 call sites externos importan
  directamente de `services.media.reel_rendering.layout`.
- `modules/rendering/infrastructure/layout/__init__.py` (placeholder vacío
  con un docstring "Rendering infrastructure layer" en el `__init__.py` del
  parent — el de `layout/` solo existe como `__init__.py`).
- Call sites externos (`Grep "from services.media.reel_rendering.layout"`):
  - `services/media/reel_rendering/filters.py:13`
  - `services/media/reel_rendering/preparation.py:15`
  - `services/media/reel_rendering/poster.py:16`
  - `services/media/reel_rendering/manifest.py:16`
  - `modules/rendering/infrastructure/ffmpeg/filter_graph.py:9`
  - `modules/rendering/infrastructure/ffmpeg/render_reel.py:18`
  - `tests/test_reel_pipeline.py:20`
- Tests: `Grep "OverlayLayout|BoxLayout|TextBlockLayout|TimedTextSegmentLayout|LayoutWarning|build_overlay_layout"` en `tests/`. Todos los hits **se concentran** en `tests/test_reel_pipeline.py` (`OverlayLayoutTests`, líneas 328-525 y referencias en 625, 824, 852, 1059, 1096, 1124, 1159, 1280). NO hay tests bajo `tests/unit/rendering/` que toquen `build_overlay_layout`. `tests/unit/rendering/` actualmente contiene `test_enqueue_scripted_render.py` (feature 8) y `test_frame_composition.py` (feature 14).
- `services/media/reel_rendering/formatting.py` (494 LoC) — **dependencia
  directa**: `layout.py:7-20` importa 12 helpers (`build_agent_lines`,
  `build_display_price`, `build_property_header_details_line`,
  `build_property_header_viewing_times_line`, `build_status_ribbon_text`,
  `build_similar_required_subtitle`, `clean_text`, `fit_wrapped_lines`,
  `resolve_agency_logo_box_size`, `resolve_agent_image_size`,
  `resolve_ber_icon_size`, `resolve_font_size_bounds`).
- `services/media/reel_rendering/models.py` (146 LoC) — `PropertyReelData`,
  `PropertyReelSlide`, `PropertyReelTemplate`. Layout consume los tres.
- `services/ai/photo_selection/prompting.py` — `normalize_caption`. Único
  uso fuera del paquete `reel_rendering` (líneas 6 y 1027 de `layout.py`).
- `docs/phase_2_operating_rules.md` (sección 2 "borrar todo lo legacy a
  medida que se mueve"; sección 4 "sin commits"; sección 8 "blocked si las
  premisas cambian"). Sección 1 sobre serial estricto aplica.
- `docs/architecture.md` (`modules/<bc>/infrastructure/` para repositorios
  + adaptadores externos; "no importes `<otro>.application` ni
  `<otro>.infrastructure`"). El layout es **infrastructure de rendering**,
  no domain ni application.
- `docs/conventions.md` (estilo: stdlib → terceros → locales; module
  docstring; `from __future__ import annotations`; type hints; sin
  comentarios "qué hace").

---

## 0. Decisión de alcance

`feature_list.json` #15 dice literalmente:

> Última pieza del rendering legacy. Partir `layout.py` por
> responsabilidades (frame layout, text positioning, brand watermarking,
> …) en submódulos bajo `modules/rendering/infrastructure/layout/`.
> Mantener un facade temporal solo si algún call site externo lo necesita.

Acceptance:

> - `modules/rendering/infrastructure/layout/` con submódulos < 500 LoC cada uno.
> - `services/media/reel_rendering/layout.py` reducido a facade o eliminado.
> - `tests/unit/rendering/` cubre el nuevo `layout/`.
> - `pytest -q` termina verde.

### Análisis de responsabilidades en `layout.py:1038`

Tras leer el archivo entero, identifico **3 responsabilidades distintas
acopladas**:

1. **Modelos/value objects** (`:23-152`, ~130 LoC). 5 dataclasses públicas
   + constante `_SINGLE_LINE_TEXT_BLOCKS`. Estos son los DTOs que la
   composición exporta y que consumen filters/poster/manifest/preparation
   y los renders ffmpeg.
   - `LayoutWarning` (frozen, slots, `to_dict`).
   - `BoxLayout` (frozen, slots, `to_dict`).
   - `TextBlockLayout` (frozen, slots, `to_dict`).
   - `TimedTextSegmentLayout` (frozen, slots, `to_dict`, redondeo `start_time`/`end_time`).
   - `OverlayLayout` (frozen, slots, `to_dict` recursivo).

2. **Medición / wrapping de texto** (`:154-372`, ~218 LoC). Un dataclass
   privado + 6 funciones que convierten `(text, usable_width, font_size_bounds, max_lines)` en `_MeasuredTextBlock`. Esto es **pura matemática de tipografía**; cero conocimiento del overlay (paneles, agente, BER).
   - `_MeasuredTextBlock` (frozen, slots, privado).
   - `_wrap_width_from_pixels`.
   - `_estimate_line_width_pixels`.
   - `_lines_fit_within_width`.
   - `_candidate_font_sizes`.
   - `_measure_text_block`.
   - `_measure_text_block_with_single_line_preference`.

3. **Composición geométrica del overlay** (`:374-1028`, ~654 LoC). 4
   funciones (3 privadas) + la pública `build_overlay_layout`. Conoce los
   paneles superior/inferior, el badge BER, la imagen del agente, el logo
   de agencia, los subtítulos timed y el ensamble final.
   - `_build_measured_address_blocks` (`:375-458`, 84 LoC).
   - `_measure_address_blocks` (`:461-628`, 168 LoC). Acopla medición
     (resp. 2) con la lógica de combinar address+viewing_times+details
     en bloques de la cabecera. **Frontera difusa**: usa `fit_wrapped_lines`
     y `_wrap_width_from_pixels` (resp. 2) pero produce
     `_MeasuredTextBlock` con `block="address"`/`"viewing_times"`/`"address_meta"`
     (resp. 3).
   - `_resolve_top_panel_height_range`, `_resolve_bottom_panel_height_range`,
     `_resolve_bottom_panel_y` (`:207-230`, panel geometry helpers, 24 LoC,
     pertenecen al overlay aunque vivan al inicio del archivo entre los
     wrappers).
   - `build_overlay_layout` (`:631-1019`, 389 LoC).
   - `_resolve_subtitle_caption` (`:1022-1028`, 7 LoC, helper de
     `build_overlay_layout`).

### Mapeo a submódulos destino

Propongo **3 submódulos** bajo `modules/rendering/infrastructure/layout/`:

| Submódulo | Contenido | LoC estimado |
|-----------|-----------|--------------|
| `models.py` | 5 dataclasses públicas + constante `_SINGLE_LINE_TEXT_BLOCKS` (la constante se mueve a `composition.py` o queda interna a `composition.py`; ver §1). | ~140 |
| `text_measurement.py` | `_MeasuredTextBlock` + 6 funciones de wrapping/medición (resp. 2). | ~230 |
| `overlay_composition.py` | 5 funciones privadas + `build_overlay_layout` + `_resolve_subtitle_caption` + helpers de panel + `_measure_address_blocks`. (resp. 3). | ~700 |

**Problema crítico**: `overlay_composition.py` proyectado en ~700 LoC
**incumple el acceptance literal "submódulos < 500 LoC cada uno"**. Hay que
splittearlo.

### Subdivisión de `overlay_composition.py` (responsabilidad 3)

Tras releer `build_overlay_layout` con detalle, la función tiene 3 fases
secuenciales claramente identificables:

- **Fase A — Top panel** (líneas `:642-763`, ~120 LoC). Construye `top_blocks`
  (status + price + address+meta), calcula `top_panel: BoxLayout`, posiciona
  los `text_blocks` superiores, y coloca el `ber_badge_box: BoxLayout`.
- **Fase B — Bottom panel** (líneas `:765-936`, ~170 LoC). Calcula
  `agent_image_size`, ajusta `text_width` con `logo_box_width`, construye
  `bottom_blocks` (agent_name + phone + email + psra), calcula
  `bottom_panel: BoxLayout`, posiciona los `text_blocks` inferiores y los
  `agent_image_box`/`agency_logo_box`.
- **Fase C — Subtitle segments** (líneas `:938-1006`, ~70 LoC). Construye
  los `TimedTextSegmentLayout` por slide + intro + caption forced,
  midiendo cada uno con `_measure_text_block`.

La pieza pública (`build_overlay_layout` + return final) orquesta las 3
fases con un set compartido de `warnings: list[LayoutWarning]`.

**Plan de split** que cumple el acceptance:

| Submódulo | Contenido | LoC estimado |
|-----------|-----------|--------------|
| `models.py` | 5 dataclasses públicas. | ~140 |
| `text_measurement.py` | `_MeasuredTextBlock` + 6 funciones de wrapping/medición + `_measure_address_blocks` + `_build_measured_address_blocks` (movidos aquí porque su salida sigue siendo `_MeasuredTextBlock`). | ~480 |
| `panels.py` | `_resolve_top_panel_height_range`, `_resolve_bottom_panel_height_range`, `_resolve_bottom_panel_y`, fase A (`_compose_top_panel`), fase B (`_compose_bottom_panel`). Constante `_SINGLE_LINE_TEXT_BLOCKS` aquí (solo la usa la fase B). | ~360 |
| `subtitles.py` | Fase C (`_compose_subtitle_segments`) + `_resolve_subtitle_caption`. | ~120 |
| `composition.py` | `build_overlay_layout` (orquestación) + `__all__` público re-exportando los modelos y `build_overlay_layout`. | ~110 |
| `__init__.py` | Re-export público (`models`, `composition.build_overlay_layout`). | ~25 |

**Total**: 5 archivos no-`__init__.py`, todos < 500 LoC. Cumple acceptance.

**Trade-off**: si el leader prefiere **menos archivos**, se puede colapsar
`subtitles.py` dentro de `composition.py` (suma ~230 LoC, sigue < 500). Mi
preferencia es separar porque la lógica de timed-segments es independiente
del layout estático.

### Facade temporal en `services/media/reel_rendering/layout.py`

Hay **7 call sites externos** que importan de
`services.media.reel_rendering.layout`. Verificación exhaustiva:

| Caller | Línea | Símbolos importados |
|--------|-------|---------------------|
| `services/media/reel_rendering/filters.py` | 13 | `OverlayLayout`, `build_overlay_layout` |
| `services/media/reel_rendering/preparation.py` | 15 | `build_overlay_layout` |
| `services/media/reel_rendering/poster.py` | 16 | `BoxLayout`, `OverlayLayout`, `build_overlay_layout` |
| `services/media/reel_rendering/manifest.py` | 16 | `build_overlay_layout` |
| `modules/rendering/infrastructure/ffmpeg/filter_graph.py` | 9 | `build_overlay_layout` |
| `modules/rendering/infrastructure/ffmpeg/render_reel.py` | 18 | `build_overlay_layout` |
| `tests/test_reel_pipeline.py` | 20 | `build_overlay_layout` |

**Decisión**: mantener `services/media/reel_rendering/layout.py` como
**facade temporal de re-exports**. Razones:

- 4 de los 7 callers viven bajo `services/media/reel_rendering/*`. La
  feature 18 los retira cuando borra `services/`. Tocarlos ahora obliga a
  reapuntar a `modules.rendering.infrastructure.layout`, lo que duplica
  trabajo: feature 18 tendrá que volver a tocar las imports cuando los
  archivos cambien de path.
- 2 callers viven bajo `modules/rendering/infrastructure/ffmpeg/`. Esos sí
  se pueden actualizar al nuevo path **sin tocar deuda** (feature 18 no los
  toca; ya están en `modules/`). **Recomendación**: actualizarlos al nuevo
  path como parte de feature 15 (cambio quirúrgico de 2 líneas).
- 1 caller vive en `tests/test_reel_pipeline.py:20`. Es **legacy** (1381
  LoC, bajo `tests/` raíz, no bajo `tests/unit/rendering/`). **Recomendación**:
  actualizarlo al nuevo path para que el test deje de depender del facade.
  Es un cambio de 1 línea sin riesgo.

**Resumen de la decisión**:

- Mantener `services/media/reel_rendering/layout.py` como facade que
  re-exporta de `modules.rendering.infrastructure.layout`. ~25 LoC.
- Actualizar los 2 callers en `modules/rendering/infrastructure/ffmpeg/*` al
  nuevo path.
- Actualizar `tests/test_reel_pipeline.py:20` al nuevo path.
- Los 4 callers en `services/media/reel_rendering/*` siguen importando del
  facade (queda para feature 18).

**Alternativa rechazada**: borrar el facade y actualizar TODOS los callers
en feature 15. Razones para rechazarla:

- Los 4 callers bajo `services/media/reel_rendering/*` (`filters.py`,
  `preparation.py`, `poster.py`, `manifest.py`) son legacy y feature 18
  los borra/migra. Reapuntarlos ahora al nuevo path crea churn que
  feature 18 deshace.
- El facade es ligero (~25 LoC, `__all__` + 6 imports + `from
  modules...layout import *`). No introduce comportamiento nuevo.
- El docstring del facade explica la situación: "compat shim hasta
  feature 18".

Si el leader prefiere matar el facade, lo planteo como **bloqueo**. Mi
default es Opción facade.

### Tests existentes y nuevos

- **El acceptance literal pide**: "`tests/unit/rendering/` cubre el nuevo
  `layout/`". Hay que crear tests bajo `tests/unit/rendering/` que cubran
  el código movido, no en `tests/test_reel_pipeline.py`.
- `tests/test_reel_pipeline.py` ya tiene 14 invocaciones a
  `build_overlay_layout`, principalmente en `OverlayLayoutTests`
  (líneas 328-525) más checks indirectos en otros tests.
- **Recomendación**: crear `tests/unit/rendering/test_layout_*.py` con
  tests **focalizados** por submódulo (3-4 archivos de test, uno por
  responsabilidad). NO mover los tests de `tests/test_reel_pipeline.py`
  (forman parte del legacy y se reescriben en feature 18). Tests nuevos
  cubren cada submódulo con unit tests aislados.
- Esto mantiene los tests legacy verdes (importan vía el facade) y suma
  cobertura nueva enfocada al refactor.

### Resumen del alcance final propuesto

| Acción | Archivos |
|--------|----------|
| **Crear** | `modules/rendering/infrastructure/layout/models.py` (~140 LoC). |
| **Crear** | `modules/rendering/infrastructure/layout/text_measurement.py` (~480 LoC). |
| **Crear** | `modules/rendering/infrastructure/layout/panels.py` (~360 LoC). |
| **Crear** | `modules/rendering/infrastructure/layout/subtitles.py` (~120 LoC). |
| **Crear** | `modules/rendering/infrastructure/layout/composition.py` (~110 LoC). |
| **Modificar** | `modules/rendering/infrastructure/layout/__init__.py` (placeholder → re-exports, ~25 LoC). |
| **Modificar** | `services/media/reel_rendering/layout.py` (1038 → ~25 LoC, facade). |
| **Modificar** | `modules/rendering/infrastructure/ffmpeg/filter_graph.py` (1 línea import). |
| **Modificar** | `modules/rendering/infrastructure/ffmpeg/render_reel.py` (1 línea import). |
| **Modificar** | `tests/test_reel_pipeline.py` (1 línea import). |
| **Crear** | `tests/unit/rendering/test_layout_models.py` (~120 LoC). |
| **Crear** | `tests/unit/rendering/test_layout_text_measurement.py` (~250 LoC). |
| **Crear** | `tests/unit/rendering/test_layout_panels.py` (~180 LoC). |
| **Crear** | `tests/unit/rendering/test_layout_subtitles.py` (~150 LoC). |
| **Crear** | `tests/unit/rendering/test_layout_composition.py` (~200 LoC). |
| **NO tocar** | `services/media/reel_rendering/{filters,preparation,poster,manifest}.py` (siguen importando del facade hasta feature 18). |
| **NO tocar** | `services/media/reel_rendering/formatting.py` (helpers consumidos por layout, sin cambios). |
| **NO tocar** | `services/media/reel_rendering/models.py` (consumidos por layout, sin cambios). |
| **NO tocar** | `tests/test_reel_pipeline.py` `OverlayLayoutTests` y resto del cuerpo (mismas firmas, solo cambia el path de import). |

---

## 1. Alcance por submódulo (rangos línea-a-línea)

### 1.1 — `modules/rendering/infrastructure/layout/models.py`

**Origen**: `layout.py:1-22` (imports parciales), `:26-152` (5 dataclasses).

| Rango origen | Símbolo | LoC | Notas |
|--------------|---------|-----|-------|
| `:26-39` | `class LayoutWarning` | 14 | frozen, slots, `to_dict()`. |
| `:42-57` | `class BoxLayout` | 16 | frozen, slots, `to_dict()`. |
| `:60-89` | `class TextBlockLayout` | 30 | frozen, slots, `to_dict()` con `lines: list(...)`. |
| `:92-123` | `class TimedTextSegmentLayout` | 32 | frozen, slots, `to_dict()` con `round(..., 3)`. |
| `:126-151` | `class OverlayLayout` | 26 | frozen, slots, `to_dict()` recursivo. |

**Imports necesarios**:
```python
from __future__ import annotations
from dataclasses import dataclass
```

**`__all__`**: `["BoxLayout", "LayoutWarning", "OverlayLayout", "TextBlockLayout", "TimedTextSegmentLayout"]`.

**LoC final estimado**: ~140 (dataclasses + docstring de módulo + `__all__`).

---

### 1.2 — `modules/rendering/infrastructure/layout/text_measurement.py`

**Origen**: `layout.py:154-372` (medición pura) + `:375-628` (`_build_measured_address_blocks` + `_measure_address_blocks`, que produce `_MeasuredTextBlock`).

| Rango origen | Símbolo | LoC | Notas |
|--------------|---------|-----|-------|
| `:154-165` | `_MeasuredTextBlock` | 12 | frozen, slots, privado. **Necesario re-exportar como público para que `panels.py` y `subtitles.py` lo consuman**: renombrar a `MeasuredTextBlock` (sin underscore). |
| `:168-177` | `_wrap_width_from_pixels` | 10 | privado. |
| `:180-187` | `_estimate_line_width_pixels` | 8 | privado. |
| `:190-204` | `_lines_fit_within_width` | 15 | privado. |
| `:233-241` | `_candidate_font_sizes` | 9 | privado. |
| `:244-336` | `_measure_text_block` | 93 | **público** (renombrar a `measure_text_block` para que `panels.py` y `subtitles.py` lo importen sin acceso a privados). |
| `:339-372` | `_measure_text_block_with_single_line_preference` | 34 | público (renombrar). |
| `:375-458` | `_build_measured_address_blocks` | 84 | privado interno de este submódulo. |
| `:461-628` | `_measure_address_blocks` | 168 | público (renombrar a `measure_address_blocks`). |

**Imports necesarios**:
```python
from __future__ import annotations
from dataclasses import dataclass
from services.media.reel_rendering.formatting import clean_text, fit_wrapped_lines
```

**Decisión sobre el rename**: en el legacy, todos los nombres llevan
underscore (`_measure_text_block`). Al moverlos a un submódulo nuevo
necesitan ser públicos para los imports cross-submódulo (`panels.py`
importa `measure_text_block`). Aplico la convención clean-name:
`measure_text_block`, `measure_address_blocks`, `MeasuredTextBlock`. Los
helpers que SI son internos al submódulo (`_wrap_width_from_pixels`,
`_estimate_line_width_pixels`, `_lines_fit_within_width`,
`_candidate_font_sizes`, `_build_measured_address_blocks`,
`_measure_text_block_with_single_line_preference`) conservan el underscore.

Actualización del listado tras decidir rename:

| Origen | Nombre nuevo | Visibilidad |
|--------|--------------|-------------|
| `_MeasuredTextBlock` | `MeasuredTextBlock` | Público (export). |
| `_wrap_width_from_pixels` | `_wrap_width_from_pixels` | Privado. |
| `_estimate_line_width_pixels` | `_estimate_line_width_pixels` | Privado. |
| `_lines_fit_within_width` | `_lines_fit_within_width` | Privado. |
| `_candidate_font_sizes` | `_candidate_font_sizes` | Privado. |
| `_measure_text_block` | `measure_text_block` | Público (consumido por `panels.py` y `subtitles.py`). |
| `_measure_text_block_with_single_line_preference` | `_measure_text_block_with_single_line_preference` | Privado (solo lo usa la lógica de address dentro del mismo archivo). |
| `_build_measured_address_blocks` | `_build_measured_address_blocks` | Privado. |
| `_measure_address_blocks` | `measure_address_blocks` | Público (consumido por `panels.py`). |

**`__all__`**: `["MeasuredTextBlock", "measure_address_blocks", "measure_text_block"]`.

**LoC final estimado**: ~480. **Justo en el límite**. Si pasa de 500, alternativa: extraer `_measure_address_blocks` + `_build_measured_address_blocks` a un submódulo dedicado `address_text_layout.py` (~250 LoC) y dejar `text_measurement.py` con los wrappers/medición primaria (~230 LoC).

---

### 1.3 — `modules/rendering/infrastructure/layout/panels.py`

**Origen**: `layout.py:23` (constante `_SINGLE_LINE_TEXT_BLOCKS`), `:207-230` (panel ranges helpers), `:642-763` (fase A top panel), `:765-936` (fase B bottom panel).

| Rango origen | Símbolo | LoC | Notas |
|--------------|---------|-----|-------|
| `:23` | `_SINGLE_LINE_TEXT_BLOCKS` | 1 | privado. Solo lo usa la fase B. |
| `:207-208` | `_resolve_top_panel_height_range` | 2 | privado. |
| `:211-212` | `_resolve_bottom_panel_height_range` | 2 | privado. |
| `:215-230` | `_resolve_bottom_panel_y` | 16 | privado. |
| `:642-763` | Fase A (top panel composition) | 120 | **Refactorizar a función pública `compose_top_panel(property_data, settings, ...)` que retorna `(top_panel: BoxLayout | None, text_blocks: list[TextBlockLayout], ber_badge_box: BoxLayout | None, warnings: list[LayoutWarning])`**. |
| `:765-936` | Fase B (bottom panel composition) | 170 | **Refactorizar a función pública `compose_bottom_panel(property_data, settings, top_panel, ...)` que retorna `(bottom_panel, text_blocks, agent_image_box, agency_logo_box, warnings)`**. |

**Imports necesarios**:
```python
from __future__ import annotations
from modules.rendering.infrastructure.layout.models import (
    BoxLayout,
    LayoutWarning,
    TextBlockLayout,
)
from modules.rendering.infrastructure.layout.text_measurement import (
    MeasuredTextBlock,
    measure_address_blocks,
    measure_text_block,
)
from services.media.reel_rendering.formatting import (
    build_agent_lines,
    build_display_price,
    build_property_header_details_line,
    build_property_header_viewing_times_line,
    build_status_ribbon_text,
    resolve_agency_logo_box_size,
    resolve_agent_image_size,
    resolve_ber_icon_size,
    resolve_font_size_bounds,
)
from services.media.reel_rendering.models import PropertyReelData, PropertyReelTemplate
```

**Refactor de fase A → `compose_top_panel`**:

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
    ...
```

**Refactor de fase B → `compose_bottom_panel`**:

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
    ...
```

**`__all__`**: `["compose_bottom_panel", "compose_top_panel"]`.

**LoC final estimado**: ~360.

**Riesgo**: el refactor introduce parámetros explícitos donde el legacy
pasaba `width`/`height`/`outer_margin_*`/`panel_padding_*` calculados in-place
en `build_overlay_layout`. El cuerpo de las funciones se preserva
**verbatim**; solo cambian las firmas. La regresión se cubre en tests
unitarios + tests existentes en `tests/test_reel_pipeline.py` que pasan
verbatim.

---

### 1.4 — `modules/rendering/infrastructure/layout/subtitles.py`

**Origen**: `layout.py:938-1006` (fase C subtitle segments) + `:1022-1028` (`_resolve_subtitle_caption`).

| Rango origen | Símbolo | LoC | Notas |
|--------------|---------|-----|-------|
| `:938-1006` | Fase C | 70 | **Refactorizar a función pública `compose_subtitle_segments(property_data, settings, slides, slide_duration, cover_caption, bottom_panel, panel_width, outer_margin_x, outer_margin_y, panel_padding_x, height)` que retorna `(tuple[TimedTextSegmentLayout, ...], tuple[LayoutWarning, ...])`**. |
| `:1022-1028` | `_resolve_subtitle_caption` | 7 | privado. |

**Imports necesarios**:
```python
from __future__ import annotations
from modules.rendering.infrastructure.layout.models import (
    BoxLayout,
    LayoutWarning,
    TimedTextSegmentLayout,
)
from modules.rendering.infrastructure.layout.text_measurement import measure_text_block
from services.ai.photo_selection.prompting import normalize_caption
from services.media.reel_rendering.formatting import (
    build_similar_required_subtitle,
    clean_text,
    resolve_font_size_bounds,
)
from services.media.reel_rendering.models import (
    PropertyReelData,
    PropertyReelSlide,
    PropertyReelTemplate,
)
```

**Refactor**:

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
    ...
```

**`__all__`**: `["compose_subtitle_segments"]`.

**LoC final estimado**: ~120.

---

### 1.5 — `modules/rendering/infrastructure/layout/composition.py`

**Origen**: `layout.py:631-1019` (orquestación pública `build_overlay_layout`) reducida a un orquestador delgado que invoca `compose_top_panel`, `compose_bottom_panel`, `compose_subtitle_segments` y ensambla `OverlayLayout`.

```python
def build_overlay_layout(
    property_data: PropertyReelData,
    settings: PropertyReelTemplate,
    *,
    slides: tuple[PropertyReelSlide, ...] | list[PropertyReelSlide],
    slide_duration: float | None,
    has_ber_badge: bool,
    has_agency_logo: bool = False,
    cover_caption: str | None = None,
    single_line_contact_email: bool = False,
) -> OverlayLayout:
    width = settings.width
    height = settings.height
    outer_margin_x = max(36, round(width * 0.04))
    outer_margin_y = max(36, round(height * 0.03))
    panel_padding_x = max(26, round(width * 0.024))
    panel_padding_y = max(22, round(height * 0.018))
    panel_width = width - (outer_margin_x * 2)
    warnings: list[LayoutWarning] = []

    top_panel, top_text_blocks, ber_badge_box, top_warnings = compose_top_panel(
        property_data, settings,
        has_ber_badge=has_ber_badge,
        outer_margin_x=outer_margin_x,
        outer_margin_y=outer_margin_y,
        panel_padding_x=panel_padding_x,
        panel_padding_y=panel_padding_y,
        panel_width=panel_width,
    )
    warnings.extend(top_warnings)

    bottom_panel, bottom_text_blocks, agent_image_box, agency_logo_box, bottom_warnings = compose_bottom_panel(
        property_data, settings,
        top_panel=top_panel,
        has_agency_logo=has_agency_logo,
        single_line_contact_email=single_line_contact_email,
        outer_margin_x=outer_margin_x,
        outer_margin_y=outer_margin_y,
        panel_padding_x=panel_padding_x,
        panel_padding_y=panel_padding_y,
        panel_width=panel_width,
    )
    warnings.extend(bottom_warnings)

    subtitle_segments, subtitle_warnings = compose_subtitle_segments(
        property_data, settings,
        slides=slides,
        slide_duration=slide_duration,
        cover_caption=cover_caption,
        bottom_panel=bottom_panel,
        panel_width=panel_width,
        outer_margin_x=outer_margin_x,
        outer_margin_y=outer_margin_y,
        panel_padding_x=panel_padding_x,
    )
    warnings.extend(subtitle_warnings)

    return OverlayLayout(
        frame_width=width,
        frame_height=height,
        top_panel=top_panel,
        bottom_panel=bottom_panel,
        agent_image_box=agent_image_box,
        agency_logo_box=agency_logo_box,
        ber_badge_box=ber_badge_box,
        text_blocks=tuple(top_text_blocks) + tuple(bottom_text_blocks),
        subtitle_segments=subtitle_segments,
        warnings=tuple(warnings),
    )
```

**Imports necesarios**:
```python
from __future__ import annotations
from modules.rendering.infrastructure.layout.models import LayoutWarning, OverlayLayout
from modules.rendering.infrastructure.layout.panels import (
    compose_bottom_panel,
    compose_top_panel,
)
from modules.rendering.infrastructure.layout.subtitles import compose_subtitle_segments
from services.media.reel_rendering.models import (
    PropertyReelData,
    PropertyReelSlide,
    PropertyReelTemplate,
)
```

**`__all__`**: `["build_overlay_layout"]`.

**LoC final estimado**: ~110.

**Riesgo de orden de operaciones**: el legacy ensambla `text_blocks` con
los del top panel **primero** y los del bottom panel **después** (en el
orden en que se itera `top_blocks` y luego `bottom_blocks`). El orquestador
nuevo preserva ese orden con la concatenación
`tuple(top_text_blocks) + tuple(bottom_text_blocks)`. **Verificar en
revisión** que `OverlayLayout.text_blocks` mantiene el mismo orden que el
legacy en los tests existentes.

---

### 1.6 — `modules/rendering/infrastructure/layout/__init__.py`

```python
"""Overlay layout composition for property reels (extracted from
`services.media.reel_rendering.layout` in feature 15)."""

from __future__ import annotations

from modules.rendering.infrastructure.layout.composition import build_overlay_layout
from modules.rendering.infrastructure.layout.models import (
    BoxLayout,
    LayoutWarning,
    OverlayLayout,
    TextBlockLayout,
    TimedTextSegmentLayout,
)

__all__ = [
    "BoxLayout",
    "LayoutWarning",
    "OverlayLayout",
    "TextBlockLayout",
    "TimedTextSegmentLayout",
    "build_overlay_layout",
]
```

**LoC final**: ~25.

---

### 1.7 — `services/media/reel_rendering/layout.py` (facade)

```python
"""Compatibility facade — Phase 2 feature 15 moved layout to
`modules.rendering.infrastructure.layout`. This file is kept until
feature 18 retires `services/`."""

from __future__ import annotations

from modules.rendering.infrastructure.layout import (
    BoxLayout,
    LayoutWarning,
    OverlayLayout,
    TextBlockLayout,
    TimedTextSegmentLayout,
    build_overlay_layout,
)

__all__ = [
    "BoxLayout",
    "LayoutWarning",
    "OverlayLayout",
    "TextBlockLayout",
    "TimedTextSegmentLayout",
    "build_overlay_layout",
]
```

**LoC final**: ~24.

---

## 2. Estructura recomendada de `modules/rendering/infrastructure/layout/`

```
modules/rendering/infrastructure/layout/
├── __init__.py               (re-exports públicos, ~25 LoC)
├── models.py                 (~140 LoC, 5 dataclasses)
├── text_measurement.py       (~480 LoC, MeasuredTextBlock + measure_*)
├── panels.py                 (~360 LoC, compose_top/bottom_panel)
├── subtitles.py              (~120 LoC, compose_subtitle_segments)
└── composition.py            (~110 LoC, build_overlay_layout)
```

**Justificación arquitectónica** (`docs/architecture.md` §2):

- Está bajo `infrastructure/` porque el layout depende de helpers de
  formato (`services/media/reel_rendering/formatting.py`) y de modelos
  (`services/media/reel_rendering/models.py`) que son legacy compartido.
  No es código de `application/` (no orquesta UoW ni use cases) ni
  `domain/` (no son value objects de un aggregate). Es un cómputo puro
  específico del rendering, propio del layer "infrastructure".
- Coherente con los placeholders existentes de `modules/rendering/infrastructure/{poster,manifest,preparation,photos}/__init__.py` que feature 18 usará para mover el resto del rendering legacy.

---

## 3. Mapeo de call sites externos

7 call sites totales. Distribución tras feature 15:

| Caller actual | Acción feature 15 | Path import nuevo | Notas |
|---------------|-------------------|-------------------|-------|
| `services/media/reel_rendering/filters.py:13` | **No tocar.** Sigue importando `OverlayLayout, build_overlay_layout` del facade. | `services.media.reel_rendering.layout` (facade) | Feature 18 lo migra. |
| `services/media/reel_rendering/preparation.py:15` | **No tocar.** | `services.media.reel_rendering.layout` (facade) | Idem. |
| `services/media/reel_rendering/poster.py:16` | **No tocar.** Sigue importando `BoxLayout, OverlayLayout, build_overlay_layout` del facade. | `services.media.reel_rendering.layout` (facade) | Idem. |
| `services/media/reel_rendering/manifest.py:16` | **No tocar.** | `services.media.reel_rendering.layout` (facade) | Idem. |
| `modules/rendering/infrastructure/ffmpeg/filter_graph.py:9` | **Modificar**. Cambia 1 línea de import. | `modules.rendering.infrastructure.layout` | El módulo está bajo `modules/`, no toca legacy. |
| `modules/rendering/infrastructure/ffmpeg/render_reel.py:18` | **Modificar**. Cambia 1 línea de import. | `modules.rendering.infrastructure.layout` | Idem. |
| `tests/test_reel_pipeline.py:20` | **Modificar**. Cambia 1 línea de import. | `modules.rendering.infrastructure.layout` | Test legacy pero accesible al patron. |

**Total cambios**: 3 líneas (3 archivos), reapuntando del path legacy
`services.media.reel_rendering.layout` al path nuevo
`modules.rendering.infrastructure.layout`. **Las firmas y comportamiento
de los símbolos importados son idénticos.**

**Verificación que no se me escapa nada**: he ejecutado `Grep
"from services.media.reel_rendering.layout|from
services.media.reel_rendering import.*layout|reel_rendering.layout"` en
todo el repo. 7 hits — listados arriba. Cero hits adicionales. Confirmo
que no hay imports dinámicos (`importlib`) sobre `layout`.

---

## 4. Tests existentes y nuevos

### 4.1 — Tests existentes que tocan `layout`

**`tests/test_reel_pipeline.py`** (1381 LoC). 14 invocaciones a
`build_overlay_layout` (líneas 372, 421, 495, 504, 625, 824, 852, 1059,
1096, 1124, 1159, 1280) + clase `OverlayLayoutTests`
(líneas 328-525, 6 tests dedicados al layout).

**Tests dedicados de layout**:

1. `test_overlay_layout_keeps_extreme_text_blocks_within_estimated_widths` (`:333-401`).
2. `test_format_property_size_keeps_only_square_meters_when_square_feet_are_present` (`:402-404`) — toca `formatting`, no `layout`.
3. `test_bottom_panel_grows_and_keeps_agent_logo_and_text_within_bounds` (`:406-472`).
4. `test_bottom_panel_moves_up_when_footer_offset_is_configured` (`:474-525`).

**Otros tests que invocan `build_overlay_layout` indirectamente** dentro
de `_FFmpegTestCase` y otros (líneas 625, 824, 852, 1059+): verifican
posiciones/dimensiones/contenido del layout dentro de tests más amplios
(panel agent_image_box, drawtext expressions, etc).

**Comportamiento esperado**: estos 14 invocaciones siguen verdes con un
**solo cambio**: la línea 20 de `tests/test_reel_pipeline.py` reapunta a
`modules.rendering.infrastructure.layout`. La firma y el output de
`build_overlay_layout` se preservan byte-a-byte (refactor mecánico).

**Otros tests**:

- `tests/unit/rendering/test_enqueue_scripted_render.py`: feature 8. NO
  toca layout. Sin cambios.
- `tests/unit/rendering/test_frame_composition.py`: feature 14. NO toca
  layout (patches sobre primitivas top-level). Sin cambios.
- `tests/integration/rendering/test_scripted_router.py`: feature 8. NO
  toca layout. Sin cambios.

### 4.2 — Tests nuevos requeridos por la acceptance

> Acceptance literal: "`tests/unit/rendering/` cubre el nuevo `layout/`".

Recomiendo **5 archivos de test** bajo `tests/unit/rendering/`, uno por
submódulo nuevo:

#### `tests/unit/rendering/test_layout_models.py` (~120 LoC)

5-7 tests sobre los dataclasses (`models.py`):

1. `test_box_layout_to_dict_round_trips_all_fields`.
2. `test_text_block_layout_to_dict_renders_lines_as_list`.
3. `test_timed_text_segment_layout_to_dict_rounds_times_to_three_decimals`.
4. `test_overlay_layout_to_dict_serializes_nested_boxes_and_text_blocks`.
5. `test_overlay_layout_to_dict_handles_none_panels`.
6. `test_layout_warning_to_dict_includes_original_text`.
7. `test_dataclasses_are_frozen` (intentar `box.x = 99` levanta `FrozenInstanceError`).

#### `tests/unit/rendering/test_layout_text_measurement.py` (~250 LoC)

8-10 tests sobre `text_measurement.py`:

1. `test_measure_text_block_returns_none_for_empty_text`.
2. `test_measure_text_block_picks_largest_font_size_that_fits`.
3. `test_measure_text_block_clamps_long_text_with_warning_when_exceeding_max_lines`.
4. `test_measure_text_block_with_single_line_preference_picks_one_line_when_fits`.
5. `test_measure_text_block_with_single_line_preference_falls_back_to_multiline`.
6. `test_candidate_font_sizes_decreasing_step_includes_min_size` (helper privado vía `from .text_measurement import _candidate_font_sizes`).
7. `test_wrap_width_from_pixels_floor_at_min_chars`.
8. `test_measure_address_blocks_returns_empty_when_all_inputs_blank`.
9. `test_measure_address_blocks_combines_address_viewing_times_details`.
10. `test_measure_address_blocks_emits_warning_for_address_when_clamped`.

#### `tests/unit/rendering/test_layout_panels.py` (~180 LoC)

5-6 tests sobre `panels.py`:

1. `test_compose_top_panel_returns_none_when_no_text_blocks`.
2. `test_compose_top_panel_includes_status_price_address`.
3. `test_compose_top_panel_places_ber_badge_when_flag_true`.
4. `test_compose_bottom_panel_keeps_agent_image_logo_within_bounds`.
5. `test_compose_bottom_panel_zeroes_agent_image_when_text_too_narrow`.
6. `test_compose_bottom_panel_uses_footer_offset_to_shift_y`.

#### `tests/unit/rendering/test_layout_subtitles.py` (~150 LoC)

4-5 tests sobre `subtitles.py`:

1. `test_compose_subtitle_segments_returns_empty_when_slide_duration_is_none`.
2. `test_compose_subtitle_segments_emits_intro_segment_when_intro_enabled`.
3. `test_compose_subtitle_segments_emits_one_segment_per_slide`.
4. `test_compose_subtitle_segments_uses_forced_subtitle_for_required_status`.
5. `test_compose_subtitle_segments_y_aligns_above_bottom_panel`.

#### `tests/unit/rendering/test_layout_composition.py` (~200 LoC)

5-6 tests sobre `composition.py` (orquestador):

1. `test_build_overlay_layout_returns_overlay_with_top_and_bottom_panel`.
2. `test_build_overlay_layout_text_blocks_order_top_then_bottom`.
3. `test_build_overlay_layout_aggregates_warnings_from_all_phases`.
4. `test_build_overlay_layout_no_ber_badge_when_flag_false`.
5. `test_build_overlay_layout_no_agency_logo_when_flag_false`.
6. `test_build_overlay_layout_intro_subtitle_when_template_includes_intro`.

**Total LoC estimado nuevos tests**: ~900 LoC (5 archivos). Equivalente al
patrón de feature 14 (8 tests, 382 LoC) pero distribuido por submódulo.

**Construcción de fixtures**: usar `PropertyReelData`, `PropertyReelSlide`,
`PropertyReelTemplate` reales (NO mocks); mismos fixtures que
`tests/test_reel_pipeline.py:_FFmpegTestCase._build_property_data` (a
copiar como helper local en `tests/unit/rendering/conftest.py` o como
helper interno en cada test). Cero monkeypatching de I/O (el layout es
puro: input dataclasses → output dataclasses).

### 4.3 — Tests existentes que se mantienen verdes

- 417 verdes baseline (post-feature-14) deben quedar intactos.
- Esperado tras feature 15: 417 + 27-34 unit tests nuevos = **444-451 verdes**.
- `tests/test_reel_pipeline.py:OverlayLayoutTests` y todos los demás tests
  legacy que usan `build_overlay_layout` siguen pasando porque la firma y
  el comportamiento se preservan byte-a-byte.

---

## 5. Riesgos / acoplamientos

### R1 — Refactor mecánico vs cambio funcional

El acceptance pide split por responsabilidades, no refactor de la lógica
geométrica. **Todo movido es verbatim** salvo la introducción de las 3
funciones públicas (`compose_top_panel`, `compose_bottom_panel`,
`compose_subtitle_segments`) que extraen las fases de
`build_overlay_layout`. El cuerpo de cada fase se preserva línea a línea;
solo cambia que los parámetros antes locales (`outer_margin_x`,
`panel_width`, etc.) ahora son kwargs explícitos.

**Justificación de regresión cero**: los tests existentes
(`tests/test_reel_pipeline.py:OverlayLayoutTests`, 4 tests dedicados +
~10 tests indirectos vía `_FFmpegTestCase`) verifican el output de
`build_overlay_layout` byte-a-byte. Si el refactor mantiene el output,
esos tests pasan. Si no, fallan claramente.

**Recomendación al implementer**: ejecutar
`tests/test_reel_pipeline.py::OverlayLayoutTests` primero, antes de
añadir los nuevos unit tests. Si los legacy pasan, la regresión está
controlada.

### R2 — Orden de `text_blocks` en `OverlayLayout`

El legacy ensambla `text_blocks` con un único `list[TextBlockLayout]` que
acumula primero los del top panel y luego los del bottom panel
(`layout.py:723` declara la lista, `:739-754` añade top, `:919-935`
añade bottom). El orden importa porque consumidores como
`services/media/reel_rendering/filters.py:35-37` y
`services/media/reel_rendering/poster.py:258-...` iteran
`overlay_layout.text_blocks` para dibujarlos en orden de Z-buffer.

**Riesgo**: el orquestador nuevo concatena
`tuple(top_text_blocks) + tuple(bottom_text_blocks)`. Mientras
`compose_top_panel` retorne los bloques en el mismo orden que el legacy
itera los `top_blocks`, y `compose_bottom_panel` haga lo mismo, el orden
final es idéntico. **Cubierto por tests existentes**
(`OverlayLayoutTests`).

### R3 — Constante `_SINGLE_LINE_TEXT_BLOCKS`

Vive en `layout.py:23` y se consume **solo** en
`build_overlay_layout:826`. Cuando se mueve la fase B a `panels.py`, la
constante va con ella. Si el implementer la deja en `models.py` o
`text_measurement.py` por equivocación, la fase B no la encontrará.
**Recomendación clara**: mover a `panels.py` (privada `_SINGLE_LINE_TEXT_BLOCKS`).

### R4 — Tests legacy en `tests/test_reel_pipeline.py:20`

El cambio de import (`from
services.media.reel_rendering.layout import build_overlay_layout` →
`from modules.rendering.infrastructure.layout import build_overlay_layout`)
es **opcional**: el facade sigue exportando el símbolo idéntico. Si el
leader prefiere NO tocar `tests/test_reel_pipeline.py` para minimizar
diff, dejar la línea 20 como está y migrarla en feature 18.

**Recomendación**: actualizar al nuevo path en feature 15. Razones:

- Reduce la cuenta de "callers del facade" de 7 a 6 (luego a 4 si
  también actualizamos los 2 ffmpeg). Cuanto menos use el facade, más
  fácil será borrarlo en feature 18.
- Cambio de 1 línea sin riesgo; los demás 14 invocaciones de
  `build_overlay_layout` siguen funcionando.

Si el leader prefiere "no tocar legacy bajo `tests/`", aceptable como
override.

### R5 — Imports cíclicos

Estructura propuesta:

- `models.py` no importa de los otros submódulos (solo stdlib + `dataclass`).
- `text_measurement.py` importa de `services.media.reel_rendering.formatting`. NO importa de `models.py` ni de los otros submódulos del paquete.
  - **Excepción**: si los tests piden que `MeasuredTextBlock` referencie `LayoutWarning` (legacy `_MeasuredTextBlock.warning: LayoutWarning | None`), entonces `text_measurement.py` SÍ importa `LayoutWarning` de `models.py`. Verificado: el legacy tiene exactamente ese campo (`layout.py:165`). Por tanto `text_measurement.py` importa `from .models import LayoutWarning`.
- `panels.py` importa de `models.py` y `text_measurement.py`.
- `subtitles.py` importa de `models.py` y `text_measurement.py`.
- `composition.py` importa de `models.py`, `panels.py`, `subtitles.py`.
- `__init__.py` importa de todos para re-exportar.

DAG dirigido sin ciclos. Verificado mentalmente.

### R6 — `services/media/reel_rendering/formatting.py` se mantiene legacy

Layout consume 12 helpers de `formatting.py`. Esos helpers viven bajo
`services/` (legacy) y feature 18 los mueve. **Feature 15 NO toca
`formatting.py`**. El nuevo `modules/rendering/infrastructure/layout/*`
importa cross-frontera (`from services.media.reel_rendering.formatting
import ...`). Ese import **rompe** la regla "no importes de
`<otro>.application` ni `<otro>.infrastructure`" del
`docs/architecture.md`, pero como `services/` es legacy frozen y feature
18 lo retira, el import es **transitorio aceptado**.

**Documentar en el docstring** de cada submódulo que la dependencia a
`services.media.reel_rendering.formatting` es legacy y se elimina con
feature 18. Patrón idéntico al `frame_composition.py:25-46` de
feature 14 (también importa de `services.media.reel_rendering.*`).

### R7 — `services/ai/photo_selection/prompting.normalize_caption`

`subtitles.py` importa `normalize_caption` de
`services.ai.photo_selection.prompting`. Esto es otro import legacy.
Patrón idéntico a R6: aceptable transitoriamente; feature 18 lo retira.

### R8 — Splittear `text_measurement.py` si supera 500 LoC

LoC estimado: ~480. Ajustado. Si en la implementación supera 500,
fallback documentado en §1.2: extraer
`_measure_address_blocks`/`_build_measured_address_blocks` a un submódulo
`address_text_layout.py` (~250 LoC) y dejar `text_measurement.py` con
solo wrappers/medición (~230 LoC).

### R9 — Tests que crean `_MeasuredTextBlock` directamente

Búsqueda: `Grep "_MeasuredTextBlock"` en todo el repo →
**0 hits fuera de `layout.py:155, 165, 286, 325, 390-392, 404, 423, 444`**.
Conclusión: `MeasuredTextBlock` solo se usa internamente. Los tests
nuevos pueden referenciarlo (`from
modules.rendering.infrastructure.layout.text_measurement import
MeasuredTextBlock`) sin riesgo.

### R10 — `OverlayLayout.text_blocks: tuple[TextBlockLayout, ...]`

El legacy declara `tuple[TextBlockLayout, ...]` pero internamente
construye un `list[TextBlockLayout]` mutado en 2 lugares y lo convierte
con `tuple(text_blocks)` al return (`:1016`). El refactor sustituye eso
por concatenación de tuples. **Output idéntico**.

### R11 — `OverlayLayout.subtitle_segments: tuple[TimedTextSegmentLayout, ...]`

Igual que R10: legacy lista → tuple en el return; refactor retorna tuple
desde la fase C directamente. Output idéntico.

### R12 — `warnings: tuple[LayoutWarning, ...]`

Legacy: lista mutada en las 3 fases (`:650`, `:706`, `:720`, `:866`,
`:989`) + return tuple final. Refactor: 3 listas internas en cada fase,
concatenadas en el orquestador y convertidas a tuple. **Orden de los
warnings preservado** porque las 3 fases se ejecutan en el mismo orden
(top → bottom → subtitles).

### R13 — Encriptado / UoW / DB

`build_overlay_layout` no toca DB, no abre UoW, no tiene side effects en
filesystem. Es **pura**. Igual que feature 14, **NO hay UoW que migrar**.

### R14 — Performance

El refactor introduce 3 calls de función adicionales (orquestador →
`compose_top_panel` → `compose_bottom_panel` → `compose_subtitle_segments`)
y 3 conversiones tuple. Coste despreciable comparado con el cómputo del
layout (~389 LoC de iteración sobre fonts/wrapping). No hay regresión
medible.

### R15 — Dataclass `_MeasuredTextBlock` rename a `MeasuredTextBlock`

Hace público el dataclass para que `panels.py`/`subtitles.py` lo importen.
Ningún caller externo lo usa hoy (R9). Riesgo cero. **Convención**:
`MeasuredTextBlock` (sin underscore) en el path nuevo; el facade NO lo
re-exporta (no estaba en el `__all__` original de `layout.py`).

### R16 — Mantener byte-igualdad del `OverlayLayout.to_dict()`

Tests legacy en `tests/test_reel_pipeline.py:1280` y consumidores como
`services/media/reel_rendering/manifest.py:117-...` comparan
`overlay_layout.to_dict()` byte-a-byte contra fixtures JSON. **El
refactor preserva las 5 dataclasses con sus `to_dict()` exactos**. Si
algún test legacy compara `to_dict()` con un JSON congelado, debe seguir
verde.

### R17 — Acoplamiento con `formatting.fit_wrapped_lines.rebalance_last_line`

`_measure_address_blocks` invoca `fit_wrapped_lines(...,
rebalance_last_line=True)` en `:521-525, 599-603`. El kwarg está en
`formatting.py:fit_wrapped_lines`. Verificar en review que se preserva el
keyword en el código movido (no es default; si se omite por error,
la wrapping de address rompe).

### R18 — `tests/unit/rendering/conftest.py` no existe

Para evitar duplicar fixtures de `PropertyReelData`/`PropertyReelTemplate`
en los 5 archivos de test nuevos, recomiendo **crear**
`tests/unit/rendering/conftest.py` con helpers `_build_property_data`,
`_build_property_template`, `_build_property_slide`. Reutilizable también
si feature 18 mueve los tests de `tests/test_reel_pipeline.py` aquí.

---

## 6. Plan de implementación recomendado

### Archivos a crear

1. **`modules/rendering/infrastructure/layout/models.py`** (~140 LoC).
   - 5 dataclasses verbatim de `layout.py:26-151`.
   - `__all__` con los 5 nombres.

2. **`modules/rendering/infrastructure/layout/text_measurement.py`** (~480 LoC).
   - `MeasuredTextBlock` (renombrado, público).
   - 6 helpers privados (verbatim).
   - 3 funciones públicas: `measure_text_block`, `measure_address_blocks` (renombradas).
   - Imports: stdlib + `services.media.reel_rendering.formatting` + `.models`.

3. **`modules/rendering/infrastructure/layout/panels.py`** (~360 LoC).
   - Constante `_SINGLE_LINE_TEXT_BLOCKS`.
   - 3 helpers privados (`_resolve_top_panel_height_range`, `_resolve_bottom_panel_height_range`, `_resolve_bottom_panel_y`).
   - `compose_top_panel`, `compose_bottom_panel` (refactor mecánico de fases A y B).
   - Imports: stdlib + `services.media.reel_rendering.formatting` + `services.media.reel_rendering.models` + `.models` + `.text_measurement`.

4. **`modules/rendering/infrastructure/layout/subtitles.py`** (~120 LoC).
   - `_resolve_subtitle_caption` (privado).
   - `compose_subtitle_segments` (refactor mecánico de fase C).
   - Imports: stdlib + `services.ai.photo_selection.prompting` + `services.media.reel_rendering.formatting` + `services.media.reel_rendering.models` + `.models` + `.text_measurement`.

5. **`modules/rendering/infrastructure/layout/composition.py`** (~110 LoC).
   - `build_overlay_layout` (orquestador delgado).
   - Imports: stdlib + `services.media.reel_rendering.models` + `.models` + `.panels` + `.subtitles`.

6. **`tests/unit/rendering/conftest.py`** (~80 LoC).
   - Helpers de fixtures (`build_property_data`, `build_property_template`, `build_property_slide`).

7. **`tests/unit/rendering/test_layout_models.py`** (~120 LoC). 6-7 tests.
8. **`tests/unit/rendering/test_layout_text_measurement.py`** (~250 LoC). 9-10 tests.
9. **`tests/unit/rendering/test_layout_panels.py`** (~180 LoC). 5-6 tests.
10. **`tests/unit/rendering/test_layout_subtitles.py`** (~150 LoC). 4-5 tests.
11. **`tests/unit/rendering/test_layout_composition.py`** (~200 LoC). 5-6 tests.

### Archivos a modificar

1. **`modules/rendering/infrastructure/layout/__init__.py`** (placeholder vacío → ~25 LoC re-exports).
2. **`services/media/reel_rendering/layout.py`** (1038 → ~24 LoC facade).
3. **`modules/rendering/infrastructure/ffmpeg/filter_graph.py`**: línea 9, sustituir `from services.media.reel_rendering.layout import build_overlay_layout` por `from modules.rendering.infrastructure.layout import build_overlay_layout`.
4. **`modules/rendering/infrastructure/ffmpeg/render_reel.py`**: línea 18, idem.
5. **`tests/test_reel_pipeline.py`**: línea 20, idem.

### Archivos NO modificados

- `services/media/reel_rendering/{filters,preparation,poster,manifest}.py` — siguen importando del facade hasta feature 18.
- `services/media/reel_rendering/{formatting,models,data,render,runtime}.py` — sin cambios.
- `application/`, `apps/`, `shared/`, `settings/`, `alembic/` — sin cambios.
- `feature_list.json` (lo actualiza el closer).
- `tests/test_reel_pipeline.py` resto del cuerpo (solo cambia la línea 20 de import).
- `tests/unit/rendering/test_enqueue_scripted_render.py` y `test_frame_composition.py` — sin cambios.

### Orden sugerido

1. **Implementer crea** `modules/rendering/infrastructure/layout/models.py` (verbatim de `layout.py:26-151`).
2. **Crea** `text_measurement.py` (verbatim de `layout.py:154-372` + `375-628`, con renames).
3. **Crea** `panels.py` (verbatim de fases A y B, refactorizadas a `compose_top_panel`/`compose_bottom_panel`).
4. **Crea** `subtitles.py` (verbatim de fase C, refactorizada a `compose_subtitle_segments`).
5. **Crea** `composition.py` (orquestador delgado).
6. **Modifica** `modules/rendering/infrastructure/layout/__init__.py` (re-exports).
7. **Modifica** `services/media/reel_rendering/layout.py` (1038 → ~24 LoC facade).
8. **Verifica** `pytest -q tests/test_reel_pipeline.py::OverlayLayoutTests` → todos verdes (test legacy de regresión).
9. **Verifica** `pytest -q tests/test_reel_pipeline.py` → 1381 LoC tests todos verdes.
10. **Modifica** los 2 callers de `modules/rendering/infrastructure/ffmpeg/*` y `tests/test_reel_pipeline.py:20`.
11. **Crea** `tests/unit/rendering/conftest.py`.
12. **Crea** los 5 archivos `test_layout_*.py` y los hace pasar uno a uno.
13. **Verifica** `pytest -q tests/unit/rendering/` → todos verdes.
14. **Verifica** `pytest -q` completo → 444-451 verdes (417 baseline + 27-34 nuevos).
15. **Verifica** `python -m apps.api --check` → exit 0.
16. **Verifica** `python -m apps.worker --check` → exit 0.
17. **Verifica** `./init.sh` → verde end-to-end.

### LoC esperado

| Archivo | Pre | Post |
|---------|-----|------|
| `services/media/reel_rendering/layout.py` | 1038 | ~24 (facade) |
| `modules/rendering/infrastructure/layout/__init__.py` | placeholder | ~25 |
| `modules/rendering/infrastructure/layout/models.py` | — | ~140 |
| `modules/rendering/infrastructure/layout/text_measurement.py` | — | ~480 |
| `modules/rendering/infrastructure/layout/panels.py` | — | ~360 |
| `modules/rendering/infrastructure/layout/subtitles.py` | — | ~120 |
| `modules/rendering/infrastructure/layout/composition.py` | — | ~110 |
| `modules/rendering/infrastructure/ffmpeg/filter_graph.py` | 1 línea cambia | 1 línea cambia |
| `modules/rendering/infrastructure/ffmpeg/render_reel.py` | 1 línea cambia | 1 línea cambia |
| `tests/test_reel_pipeline.py` | 1 línea cambia | 1 línea cambia |
| `tests/unit/rendering/conftest.py` | — | ~80 |
| `tests/unit/rendering/test_layout_models.py` | — | ~120 |
| `tests/unit/rendering/test_layout_text_measurement.py` | — | ~250 |
| `tests/unit/rendering/test_layout_panels.py` | — | ~180 |
| `tests/unit/rendering/test_layout_subtitles.py` | — | ~150 |
| `tests/unit/rendering/test_layout_composition.py` | — | ~200 |
| **Δ total** | | **+1235 LoC nuevos / −1014 LoC borrados** = **+221 LoC netos** |

Reducción neta del repo: −1014 LoC del legacy + 1235 LoC nuevos
(modulares + tests) = **+221 LoC netos**. Aumento aceptable: el split por
responsabilidades + la cobertura de tests añade ~900 LoC de tests
formales que el legacy no tenía.

---

## 7. Discrepancias detectadas

### D1 — Acceptance "facade temporal solo si algún call site externo lo necesita"

Hay 7 call sites externos. 4 viven bajo `services/media/reel_rendering/*`
(legacy frozen). **Mi recomendación**: facade SÍ. Razón en §0
(detallada). Si el leader prefiere borrar el facade y reapuntar los 4
callers legacy al nuevo path, es factible pero churn-heavy y feature 18
lo deshace.

### D2 — Refactor parcial de `build_overlay_layout` (no es solo "mover")

El acceptance dice "partir layout.py por responsabilidades en submódulos".
Esto requiere extraer `compose_top_panel`/`compose_bottom_panel`/`compose_subtitle_segments` como funciones públicas, no solo mover dataclasses. **Esto es un refactor activo**, no un copy-paste verbatim como feature 14.

**Trade-off**: el acceptance no permite > 500 LoC por submódulo. Si el
implementer prefiere copy-paste verbatim, `build_overlay_layout` queda en
un único submódulo de ~700 LoC y **viola el acceptance**. La extracción
a 3 funciones de fase es la única manera de cumplir < 500 LoC por
submódulo.

**Riesgo aceptado**: el refactor introduce cambios estructurales
(nuevas firmas internas) que no son refactor mecánico al 100%. Mitigado
por:

- Tests legacy en `tests/test_reel_pipeline.py:OverlayLayoutTests` (4
  tests dedicados) verifican el output del orquestador byte-a-byte.
- Tests nuevos cubren cada fase aislada.

### D3 — Rename `_MeasuredTextBlock` → `MeasuredTextBlock`, `_measure_text_block` → `measure_text_block`

Necesario para imports cross-submódulo. Coherente con `docs/conventions.md`
(privadas con underscore, públicas sin). Cero callers externos del
nombre privado (verificado con `Grep`). Riesgo cero.

### D4 — Tests legacy importan `from services.media.reel_rendering.layout`

Los 14 invocaciones de `build_overlay_layout` en
`tests/test_reel_pipeline.py` siguen funcionando vía facade. La línea 20
de import puede actualizarse en feature 15 (recomendación) o quedar
para feature 18.

### D5 — Tests nuevos en `tests/unit/rendering/` deben crear su propia fixture

No existe `tests/unit/rendering/conftest.py`. Recomiendo crearlo (R18)
para evitar duplicar fixtures.

### D6 — `_SINGLE_LINE_TEXT_BLOCKS` solo usado por la fase B

Se mueve a `panels.py`. Riesgo cero.

### D7 — `services/media/reel_rendering/__init__.py` NO re-exporta layout

Verificado: `__init__.py:1-34` re-exporta de `data`, `manifest`, `models`,
`render`. **No** de `layout`. Por tanto los callers usan el path completo
`services.media.reel_rendering.layout` (no
`services.media.reel_rendering`). El facade preserva ese path. Cero
cambios al `__init__.py` de `reel_rendering/`.

### D8 — `formatting.py:fit_wrapped_lines` y otros helpers en legacy

12 helpers consumidos por `layout.py` viven en
`services/media/reel_rendering/formatting.py`. Feature 15 NO los toca.
Feature 18 los moverá. Hasta entonces, los submódulos nuevos importan
cross-frontera (legacy → modules), lo que es transitorio aceptado en
Phase 2.

### D9 — Splittear `text_measurement.py` en 2 si pasa de 500 LoC

LoC estimado: ~480. **Ajustado pero dentro del límite**. Si la
implementación supera 500 LoC (p. ej. por docstrings extensos),
fallback: separar `address_text_layout.py` (~250 LoC) y dejar
`text_measurement.py` con wrappers/medición (~230 LoC). **Default mío**:
mantener en un solo archivo si cabe.

### D10 — `tests/test_reel_pipeline.py:_FFmpegTestCase._build_property_data`

Es el helper compartido por los tests legacy. Su firma puede servir como
referencia para el nuevo `tests/unit/rendering/conftest.py`. **No mover
el helper**: feature 18 lo retira con el resto del archivo legacy.
Duplicar como helper local en el nuevo `conftest.py` es aceptable.

### D11 — `tests/unit/rendering/test_layout_panels.py` requiere PropertyReelData realista

El layout depende de `PropertyReelData` (146 LoC en `models.py`) con
campos de agente, agencia, BER, address, etc. Los fixtures en
`conftest.py` deben construir un `PropertyReelData` mínimamente
realístico, similar al `_build_property_data` legacy.

### D12 — `compose_top_panel` y `compose_bottom_panel` están acopladas vía `top_panel`

`compose_bottom_panel` consume `top_panel: BoxLayout | None` para
calcular el `_resolve_bottom_panel_y` (que usa
`top_panel.y + top_panel.height + vertical_gap` como mínimo). El
orquestador en `composition.py` debe pasar el `top_panel` de A a B en
ese orden. **No es un acoplamiento problemático** — refleja la
geometría real del overlay.

### D13 — Borrar el facade en feature 15 (alternativa)

Si el leader insiste en eliminar `services/media/reel_rendering/layout.py`
en feature 15:

- Reapuntar los 4 callers en `services/media/reel_rendering/*` al nuevo
  path. Cambio de 4 líneas. Feature 18 los retira igualmente.
- Reapuntar los 2 callers en `modules/rendering/infrastructure/ffmpeg/*`.
- Reapuntar `tests/test_reel_pipeline.py:20`.

LoC delta: misma reducción (1038 → 0) pero el facade ya era ~24 LoC. La
diferencia neta es **−24 LoC adicionales** y +6 callers tocados.
**Recomendación**: facade. Si el leader override, plan B documentado.

### D14 — Naming alternativo

Alternativas a los nombres propuestos:

- `compose_top_panel` / `compose_bottom_panel` → `build_top_panel` /
  `build_bottom_panel` (consistente con `build_overlay_layout`).
  **Recomendación**: usar `compose_*` para evitar confusión con
  `build_overlay_layout` (que sigue siendo el público); las 3 fases son
  internas al paquete (re-exportadas como `__all__` por consistencia,
  pero no se esperan callers externos).
- `text_measurement.py` → `measurement.py` o `text_layout.py`. Mi
  preferencia: `text_measurement.py` (más explícito sobre el cómputo).
- `subtitles.py` → `timed_segments.py` (más genérico). Mi preferencia:
  `subtitles.py` (mapea 1:1 con el dominio).
- `panels.py` → `panels_composition.py`. Innecesariamente largo.
- `composition.py` → `overlay.py`. Mi preferencia: `composition.py` (deja
  claro que es el orquestador).

### D15 — `OverlayLayout.warnings` orden de aglutinado

Triple-verificado: el legacy aglutina warnings en el orden
top → bottom → subtitles. El orquestador nuevo debe respetarlo
(`warnings.extend(top_warnings); ...extend(bottom_warnings); ...extend(subtitle_warnings)`).
**Cubierto por R12 y verificable con tests**.

### D16 — El acceptance no menciona `python -m apps.{api,worker} --check`

A diferencia de feature 14, el acceptance literal de feature 15 NO
exige los `--check`. **Aún así** recomiendo correrlos como sanity
(coste bajo, regresión potencial: si los imports se rompen en runtime,
los `--check` lo detectan). El init.sh los ejecuta de todos modos.

### D17 — No se requiere migración alembic

Feature 15 no toca schema. `alembic/` sin cambios.

---

**Fin del informe.**
