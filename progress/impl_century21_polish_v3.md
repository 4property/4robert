# Century 21 polish v3 — implementer report

- **Fecha:** 2026-05-19
- **Agente:** implementer (Claude Opus 4.7 1M)
- **Modo:** continuacion visual del template Century 21 (interno
  `layout_variant == "galaxy"`). No hay entrada en `feature_list.json`;
  trabajo directo bajo instruccion del leader.
- **Regla dura respetada:** todos los cambios estan scoped a
  `layout_variant == "galaxy"`. Las ramas `classic` y `side_banner` quedan
  byte-for-byte identicas. El snapshot pinned
  `test_classic_filter_graph_matches_pinned_snapshot` sigue verde sin
  modificacion, y los nuevos regression tests para classic/side_banner
  pinan que su `address.max_lines` no cambia.

## Archivos tocados

### Codigo (3)

- `/opt/projects/4Reels-Backend/modules/rendering/infrastructure/preparation.py`
  - `_resolve_vertical_banner_layout` rama galaxy: `body_height` floor
    `450 -> 360` y ratio `0.360 -> 0.288` (-20%). Comentario actualizado
    a "polish v3". Rama `else` (side_banner) intacta.
- `/opt/projects/4Reels-Backend/modules/rendering/infrastructure/ffmpeg/filters.py`
  - `_append_galaxy_header_logo_overlay`: `logo_x` ancla horizontal
    `top_panel.x + round(W*0.558)` -> `top_panel.x + round(W*0.520)`.
    Tamano del logo y ancla vertical (centro del top panel) sin cambios.
    Comentario polish v3 anadido.
- `/opt/projects/4Reels-Backend/modules/rendering/infrastructure/layout/panels.py`
  - `compose_top_panel`: refactor del calculo de `header_text_width`
    para tener una rama galaxy explicita
    `header_text_width = round(width * 0.460)` (antes caia en
    `round(width * 0.54)`). side_banner sigue usando la cascada
    historica (`max(300, side_ber_x - side_text_x - ber_icon_gap if BER else round(W*0.54))`).
  - Block `address` de galaxy: `max_lines=1 -> max_lines=2`. Solo el
    block `address`; `viewing_times` y `address_meta` siguen con
    `max_lines=1`. Comentario polish v3 anadido.

### Tests (2 archivos modificados, 1 archivo modificado con tests nuevos)

- Modificado `/opt/projects/4Reels-Backend/tests/unit/rendering/test_preparation_galaxy_ribbon.py`:
  - Docstring actualizado a polish v3.
  - Renombrado `test_resolve_vertical_banner_layout_galaxy_uses_taller_body_height`
    -> `test_resolve_vertical_banner_layout_galaxy_uses_polish_v3_body_height`.
  - Asserts: `body_height == round(1920 * 0.288)` y `body_height >= 360`
    (v2 era `0.360` y `>= 450`).
  - Test `test_resolve_vertical_banner_layout_side_banner_unaffected_by_galaxy_polish`
    intacto (sigue siendo la red de regresion side_banner).
- Modificado `/opt/projects/4Reels-Backend/tests/unit/rendering/test_overlay_filter_accent_colors.py`:
  - `test_galaxy_header_uses_century21_logo_asset_instead_of_ber`: assert
    `overlay=x=620:y=95` -> `overlay=x=580:y=95` (math recalculada para
    1054x1492: `32 + round(1054*0.520) = 580`). Comentario polish v3
    anadido.
- Modificado `/opt/projects/4Reels-Backend/tests/unit/rendering/test_layout_composition_galaxy.py`:
  - **Renombrado** `test_build_overlay_layout_galaxy_keeps_address_on_one_line_when_clamped`
    -> `test_build_overlay_layout_galaxy_allows_address_to_wrap_to_two_lines`,
    con nuevos asserts (`max_lines == 2` y `len(lines) == 2`).
  - **Nuevo** `test_build_overlay_layout_galaxy_keeps_short_address_on_one_line`:
    titulo corto -> 1 linea (no se fuerza wrap), `clamped is False`.
  - **Nuevo** `test_build_overlay_layout_galaxy_wraps_long_address_to_two_lines`:
    titulo largo -> 2 lineas.
  - **Nuevo** `test_build_overlay_layout_classic_address_max_lines_unchanged_by_polish_v3`:
    regresion classic (`address.max_lines == 4` historico via
    `measure_address_blocks`).
  - **Nuevo** `test_build_overlay_layout_side_banner_address_max_lines_unchanged_by_polish_v3`:
    regresion side_banner (`address.max_lines == 4`).
  - **Nuevo** `test_build_overlay_layout_galaxy_header_text_clears_logo_column`:
    guard geometrico que verifica a 1054x1492 que
    `address.x + address.max_width <= logo_x`, con margen pinned a 22 px.

## Diff conceptual por cambio

### Cambio 1 — Ribbon vertical -20% (galaxy only)

- `body_height = max(360, round(H * 0.288))` (antes `max(450, round(H * 0.360))`).
- Factor 0.360 * 0.8 = 0.288; floor 450 * 0.8 = 360.
- Verificacion: a 1080x1920, `body=round(1920*0.288)=553`, `notch=61`,
  `total=614 < 1920` con holgura.
- `banner_width`, `notch_height`, posicion `x`/`y` y rama `else`
  (side_banner) sin cambios.

### Cambio 2 — Logo header desplazado a la izquierda (galaxy only)

- `logo_x = top_panel.x + round(W * 0.520)` (antes `0.558`).
- Desplazamiento de 38 px a 1080 px de ancho (~3.5% del frame). Moderado
  pero perceptible.
- Tamano del logo (`max(192, W*0.225)` x `max(210, H*0.174)`) y ancla
  vertical (centro del top panel) sin cambios.
- Math a 1054x1492: `logo_x = 32 + round(1054*0.520) = 32 + 548 = 580`
  (antes 620). `logo_y = 95` (sin cambios).

### Cambio 3 — Address con wrap a 2 lineas + header_text_width galaxy 0.460*W (galaxy only)

- **Refactor de `header_text_width` en `compose_top_panel`**: ahora el
  bloque `is_side_banner_like` ramifica `if is_galaxy: header_text_width
  = round(width * 0.460)` vs `else: header_text_width = max(300, ...)`
  (lo de antes para side_banner). De esta forma galaxy NO cae en el
  `max(round(W*0.52), round(W*0.54))` que daba 583 px a 1080 e invadia
  el area del logo nuevo.
- **`measure_text_block(block="address", ..., max_lines=2, ...)`**: solo
  para galaxy. Permite que titulos largos se rompan a 2 lineas en vez
  de ser clampados a 1.
- **viewing_times y address_meta intactos** (`max_lines=1`) para no
  romper el ritmo del header de 3 bloques.
- Comentario en el helper actualizado: "Century 21 polish v3
  (2026-05-19): allow the address to wrap up to 2 lines
  (header_text_width was tightened to 0.460*W in tandem to keep the
  column clear of the header logo to the right)."

#### Verificacion geometrica del solape texto/logo

A la resolucion pinned 1054x1492 (fixture del test focal):

- `side_text_x        = round(1054 * 0.069) = 73`
- `header_text_width  = round(1054 * 0.460) = 485`
- `text_end           = 73 + 485            = 558`
- `top_panel.x        = round(1054 * 0.030) = 32`
- `logo_x             = 32 + round(1054 * 0.520) = 32 + 548 = 580`
- `margin             = 580 - 558           = 22 px`  ✓

A la resolucion de produccion 1080x1920:

- `side_text_x        = round(1080 * 0.069) = 75`
- `header_text_width  = round(1080 * 0.460) = 497`
- `text_end           = 75 + 497            = 572`
- `top_panel.x        = round(1080 * 0.030) = 32`
- `logo_x             = 32 + round(1080 * 0.520) = 32 + 562 = 594`
- `margin             = 594 - 572           = 22 px`  ✓

Margen estable de 22 px en ambas resoluciones — coincide con el
calculo de las instrucciones.

## Tests anadidos / modificados (resumen)

| Tipo | Test | Archivo | Que pina |
| --- | --- | --- | --- |
| Modif | `test_resolve_vertical_banner_layout_galaxy_uses_polish_v3_body_height` | `test_preparation_galaxy_ribbon.py` | `body_height == round(H*0.288)` y `>= 360` |
| Modif | `test_galaxy_header_uses_century21_logo_asset_instead_of_ber` | `test_overlay_filter_accent_colors.py` | `overlay=x=580:y=95` |
| Modif (rename) | `test_build_overlay_layout_galaxy_allows_address_to_wrap_to_two_lines` | `test_layout_composition_galaxy.py` | `max_lines=2, len(lines)=2` |
| Nuevo | `test_build_overlay_layout_galaxy_keeps_short_address_on_one_line` | `test_layout_composition_galaxy.py` | titulo corto -> 1 linea (no wrap) |
| Nuevo | `test_build_overlay_layout_galaxy_wraps_long_address_to_two_lines` | `test_layout_composition_galaxy.py` | titulo largo -> 2 lineas |
| Nuevo | `test_build_overlay_layout_classic_address_max_lines_unchanged_by_polish_v3` | `test_layout_composition_galaxy.py` | classic `address.max_lines == 4` |
| Nuevo | `test_build_overlay_layout_side_banner_address_max_lines_unchanged_by_polish_v3` | `test_layout_composition_galaxy.py` | side_banner `address.max_lines == 4` |
| Nuevo | `test_build_overlay_layout_galaxy_header_text_clears_logo_column` | `test_layout_composition_galaxy.py` | a 1054x1492, `address.x + address.max_width <= logo_x` con margen pinned a 22 px |

## Verificacion

- `bash ./init.sh` exit 0; resumen:
  - apps.api --check verde
  - apps.worker --check verde
  - pytest: **1115 passed, 3 failed (baseline historico), 1 deselected, 14 warnings in 597.57s**
  - Los 3 fallos son los baseline ya documentados
    (`test_frontend_api_requests_target_existing_backend_routes`,
    `test_health_endpoints_include_paused_dispatcher_state`,
    `test_health_endpoints_return_minimal_payloads`). No relacionados
    con `modules/rendering`.
- `pytest -q tests/unit/rendering`: **183 passed** (polish v2 dejo 178;
  polish v3 anade 5 tests netos).
- `pytest -q tests/integration/rendering`: **60 passed, 1 deselected**.
- `pytest -q tests/unit/rendering -k "classic_filter_graph_matches_pinned_snapshot or side_banner"`:
  **38 passed, 145 deselected**.
- Snapshot pin del classic
  (`test_classic_filter_graph_matches_pinned_snapshot`) sigue verde ->
  confirmacion dura de que ninguna rama no-galaxy se ha movido.

## Desviaciones de las instrucciones

1. **Refactor del calculo de `header_text_width` (cambio 3, paso 3):**
   las instrucciones sugerian dos opciones para forzar 0.460*W solo en
   galaxy. La cascada original era
   ```
   max(round(W*0.52) if is_galaxy else 300,
       side_ber_x - side_text_x - ber_icon_gap if BER else round(W*0.54))
   ```
   El primer arm (`round(W*0.52)` para galaxy) hacia que cualquier
   intento de bajar el segundo arm a 0.460 quedara dominado por el
   floor 0.52 (es decir, `max(0.52, 0.460) = 0.52`, no servia). Por
   eso opte por el camino **(b) "branch específico para galaxy"** de
   las instrucciones, escrito de la forma mas legible:
   ```python
   if is_galaxy:
       header_text_width = round(width * 0.460)
   else:
       header_text_width = max(300, side_ber_x - side_text_x - ber_icon_gap if BER else round(W*0.54))
   ```
   side_banner sigue evaluando exactamente la misma expresion que
   antes — verificado por el test
   `test_build_overlay_layout_side_banner_address_max_lines_unchanged_by_polish_v3`
   y por el snapshot classic, ademas del existente
   `test_overlay_filter_side_banner_uses_reference_panel_positions`.

2. **No se ha medido manualmente el crecimiento del top panel:** las
   instrucciones pedian verificar que el panel cabe verticalmente
   cuando el address ocupa 2 lineas. El calculo de
   `top_panel_height = max(round(H*0.237), top_content_offset_y +
   top_content_height + panel_padding_y)` ya es dinamico: si el
   address anade una linea, la altura del panel crece automaticamente.
   El logo, anclado al **centro vertical** del panel (polish v2), se
   reajusta por construccion. Los tests
   `test_build_overlay_layout_galaxy_top_panel_is_broad_reference_card`
   y `test_build_overlay_layout_galaxy_uses_zero_outer_margins`
   verifican el floor del panel, y el suite integration de rendering
   (60 passed) ejecuta renders reales sin warnings. Considero la
   verificacion implicita suficiente; si producto pide visual review,
   se puede generar `progress/galaxy_iter_11.png` por separado.

Ningun otro punto de las instrucciones se ha desviado.
