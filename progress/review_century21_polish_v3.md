# Review — Century 21 polish v3

- **Fecha:** 2026-05-19
- **Reviewer:** Claude Opus 4.7 (1M)
- **Informe del implementer:** `progress/impl_century21_polish_v3.md`
- **Punto de partida:** polish v2 aprobado (`progress/review_century21_polish_v2.md`).

## Veredicto

**APPROVED**

## Resumen de validaciones

| # | Validacion | Resultado | Evidencia |
| --- | --- | --- | --- |
| 1 | Ribbon vertical -20% galaxy-only | OK | preparation.py:272-284 — rama `if layout_variant == "galaxy":` con `body_height = max(360, round(settings.height * 0.288))`. La rama `else:` (side_banner) sigue con `max(420, round(settings.height * 0.325))` byte-for-byte respecto a v2. |
| 2 | Logo header desplazado a la izquierda (galaxy-only) | OK | filters.py:214-250 — `_append_galaxy_header_logo_overlay` se invoca solo desde filters.py:438-443 dentro de `if layout_variant == "galaxy":`. `logo_x = layout.top_panel.x + round(layout.frame_width * 0.520)` (linea 239). |
| 3a | `header_text_width` galaxy=0.460*W con refactor explicito | OK | panels.py:134-144 — `if is_galaxy: header_text_width = round(width * 0.460)` vs `else: max(300, (...))`. La expresion del `else` evalua byte-for-byte la version polish v2 para side_banner (variables `effective_has_ber_badge`, `side_ber_x`, `side_text_x`, `ber_icon_gap` y la constante `0.54` son las mismas). |
| 3b | Address `max_lines=2` galaxy-only; `viewing_times`/`address_meta` siguen `max_lines=1` | OK | panels.py:243-277 — bloque `if is_galaxy:` con `address.max_lines=2` (linea 254), `viewing_times.max_lines=1` (linea 263), `address_meta.max_lines=1` (linea 272). Rama `else:` (classic + side_banner) usa `measure_address_blocks(... max_lines=4)` (panels.py:285-296), inalterada. |
| 4 | Snapshot pinned classic | PASS | `pytest -q tests/unit/rendering -k "classic_filter_graph_matches_pinned_snapshot"` -> 1 passed, 182 deselected. |
| 5 | Suite side_banner sin regresion | PASS | `pytest -q tests/unit/rendering -k "side_banner"` -> 37 passed, 146 deselected (polish v2 reporto 36 + 1 nuevo `test_build_overlay_layout_side_banner_address_max_lines_unchanged_by_polish_v3`). |
| 6 | `test_build_overlay_layout_side_banner_address_max_lines_unchanged_by_polish_v3` | PASS | Asserta `address.max_lines == 4` para side_banner (test_layout_composition_galaxy.py:416-434). |
| 7 | `test_build_overlay_layout_galaxy_header_text_clears_logo_column` | PASS | test_layout_composition_galaxy.py:437-471: pin matematico a 1054x1492, asserta `margin >= 0` y `margin == 22`. |
| 8 | `test_build_overlay_layout_galaxy_wraps_long_address_to_two_lines` | PASS | test_layout_composition_galaxy.py:370-389: usa titulo intencionadamente largo ("Beautiful 5-Bedroom Detached Villa with Panoramic Sea Views, Howth, Co. Dublin") y asserta `max_lines == 2` y `len(lines) == 2`. |
| 9 | `test_galaxy_header_uses_century21_logo_asset_instead_of_ber` con `overlay=x=580:y=95` | PASS | test_overlay_filter_accent_colors.py:156 asserta `overlay=x=580:y=95[video_with_galaxy_header_logo]`. |
| 10 | Suite completa rendering | PASS | `pytest -q tests/unit/rendering tests/integration/rendering` -> 243 passed, 1 deselected. |
| 11 | `./init.sh` exit 0 | PASS | 1115 passed, 3 failed (baseline), 1 deselected, 14 warnings en 597.45s. |
| 12 | Los 3 fallos son baseline conocido | PASS | `test_frontend_api_requests_target_existing_backend_routes`, `test_health_endpoints_include_paused_dispatcher_state`, `test_health_endpoints_return_minimal_payloads` — identicos a polish v2 (`review_century21_polish_v2.md` lineas 50, 56-66). Ninguno toca `modules/rendering`. |

## Math del solape texto/logo

A 1054x1492 (test fixture):
- `panel_padding_x   = max(26, round(1054*0.024)) = max(26, 25) = 26`
- `side_text_x       = max(26, round(1054*0.069)) = max(26, 73) = 73`
- `header_text_width = round(1054*0.460)          = 485`
- `text_end          = 73 + 485                   = 558`
- `top_panel.x       = round(1054*0.030)          = 32`
- `logo_x            = 32 + round(1054*0.520)     = 32 + 548 = 580`
- `margin            = 580 - 558                  = 22 px`  OK

A 1080x1920 (produccion):
- `panel_padding_x   = max(26, round(1080*0.024)) = max(26, 26) = 26`
- `side_text_x       = max(26, round(1080*0.069)) = max(26, 75) = 75`
- `header_text_width = round(1080*0.460)          = 497`
- `text_end          = 75 + 497                   = 572`
- `top_panel.x       = round(1080*0.030)          = 32`
- `logo_x            = 32 + round(1080*0.520)     = 32 + 562 = 594`
- `margin            = 594 - 572                  = 22 px`  OK

Margen estable de 22 px en ambas resoluciones, identico a lo reportado por el implementer. El test `test_build_overlay_layout_galaxy_header_text_clears_logo_column` pina explicitamente este valor (`assert margin == 22`).

## Math del logo_y a 1054x1492

- `logo_height = max(210, round(1492*0.174)) = max(210, 260) = 260`
- `top_panel.y = round(1492*0.032) = 48`
- `top_panel.height = max(round(1492*0.237), top_content_offset_y + top_content_height + panel_padding_y) = max(354, ...) = 354 (floor)`
- `logo_y = 48 + max(0, (354-260)//2) = 48 + 47 = 95`  OK

Coincide con `overlay=x=580:y=95`.

## Math del ribbon vertical a 1080x1920

- `body_height = max(360, round(1920*0.288)) = max(360, 553) = 553`
- `notch_height = max(38, round(1920*0.032)) = max(38, 61) = 61`
- `banner_height = body+notch = 614 < 1920`  OK

## Veredicto sobre las 2 desviaciones del implementer

### Desviacion (a): refactor de `header_text_width` con `if is_galaxy` explicito en vez de cascada con `max(...)`

**Aceptada.** La logica matematica del implementer tiene una imprecision tecnica menor (cita `max(0.52, 0.460) = 0.52`, pero el factor real en polish v2 era `round(W*0.54)`, no `0.52`); aun asi la conclusion es correcta: para galaxy con `effective_has_ber_badge=False`, la expresion polish v2 `max(300, (side_ber_x - side_text_x - ber_icon_gap if effective_has_ber_badge else round(width * 0.54)))` evaluaba a `max(300, round(W*0.54))`. A 1054 daba 569 px; a 1080 daba 583 px. Cualquier intento de "bajar" ese segundo arm por debajo de `round(W*0.54)` sin tocar el resto del cascade requiere o bien condicionar el `0.54` (lo cual es justo lo mismo que separar las ramas) o introducir un `min(...)` adicional con el mismo efecto. La forma adoptada — branch explicito — es **mas legible** y **mas auditable**.

Verificacion del side_banner: con `is_galaxy=False, is_side_banner=True`, el codigo actual evalua:
- `side_text_x = max(panel_padding_x, round(width * 0.086))`  (linea 116)
- `side_ber_x = round(width * 0.36)`  (linea 122)
- `header_text_width = max(300, (side_ber_x - side_text_x - ber_icon_gap if effective_has_ber_badge else round(width * 0.54)))`  (lineas 137-144)
- `effective_has_ber_badge = has_ber_badge and not is_galaxy = has_ber_badge`  (linea 107)

Substituyendo: para side_banner el codigo es **byte-for-byte funcionalmente identico** a la expresion polish v2 (las variables locales tienen el mismo valor; la formula `max(300, (...))` es la misma). Comprobacion empirica: snapshot classic verde + 37 tests side_banner verdes (incluyendo el nuevo regression `test_build_overlay_layout_side_banner_address_max_lines_unchanged_by_polish_v3`).

### Desviacion (b): no medicion manual del crecimiento del top_panel

**Aceptada.** La afirmacion del implementer es estructuralmente correcta:

1. `top_panel_height = max(round(H*0.237), top_content_offset_y + top_content_height + panel_padding_y)` (panels.py:320-323) ES dinamico — si el address ocupa una linea adicional, el panel crece automaticamente.

2. `logo_y = layout.top_panel.y + max(0, (layout.top_panel.height - logo_height) // 2)` (filters.py:240) usa el centro vertical del panel, asi que si el panel crece, el logo se re-centra. No hay valor fijo a romper.

3. El floor (`round(H*0.237)`) es lo bastante generoso para acomodar 3 bloques con address de 2 lineas en ambas resoluciones (1054 y 1080) — al menos, el suite de integration de rendering corre 60 renders reales sin fallos y los tests unitarios de geometria pasan. La verificacion manual con `pillow_render_smoke` queda como deuda visual para producto si lo pide explicitamente.

## Checkpoints (CHECKPOINTS.md)

- C1 (no nuevo codigo en directorios legacy): OK — todos los cambios viven en `modules/rendering/infrastructure/`.
- C2 (aislamiento de capas): OK — no se introducen imports cross-module nuevos. `domain/` no se toca; `application/` no se toca; cambios solo en `infrastructure/`.
- C3 (sin nuevas tablas / migraciones): N/A — esta feature no toca schema.
- C4 (tests nuevos para cada cambio): OK — 5 tests nuevos netos (+ 3 modificaciones a tests existentes):
  - Nuevos: `test_build_overlay_layout_galaxy_keeps_short_address_on_one_line`, `test_build_overlay_layout_galaxy_wraps_long_address_to_two_lines`, `test_build_overlay_layout_classic_address_max_lines_unchanged_by_polish_v3`, `test_build_overlay_layout_side_banner_address_max_lines_unchanged_by_polish_v3`, `test_build_overlay_layout_galaxy_header_text_clears_logo_column`.
  - Modificados: `test_resolve_vertical_banner_layout_galaxy_uses_polish_v3_body_height` (rename + asserts), `test_galaxy_header_uses_century21_logo_asset_instead_of_ber` (overlay=x=620 -> 580), `test_build_overlay_layout_galaxy_allows_address_to_wrap_to_two_lines` (rename + max_lines=2).
- C5 (init.sh verde excepto baseline): OK — los 3 fallos son los mismos baseline historicos documentados en polish v2 review.
- C6 (sin secretos en plano): N/A — no se introducen credenciales ni rutas sensibles.

## Snapshot de evidencia bruta

```
$ pytest -q tests/unit/rendering -k "classic_filter_graph_matches_pinned_snapshot"
.
1 passed, 182 deselected in 0.81s

$ pytest -q tests/unit/rendering -k "side_banner"
.....................................
37 passed, 146 deselected in 0.85s

$ pytest -q tests/unit/rendering -k "test_build_overlay_layout_side_banner_address_max_lines_unchanged_by_polish_v3 or test_build_overlay_layout_galaxy_header_text_clears_logo_column or test_build_overlay_layout_galaxy_wraps_long_address_to_two_lines or test_galaxy_header_uses_century21_logo_asset_instead_of_ber or test_build_overlay_layout_classic_address_max_lines_unchanged_by_polish_v3 or test_resolve_vertical_banner_layout_galaxy_uses_polish_v3_body_height or test_build_overlay_layout_galaxy_keeps_short_address_on_one_line or test_build_overlay_layout_galaxy_allows_address_to_wrap_to_two_lines"
........
8 passed, 175 deselected in 0.80s

$ pytest -q tests/unit/rendering tests/integration/rendering
243 passed, 1 deselected in 20.14s

$ bash ./init.sh
... [OK] apps.api --check verde
... [OK] apps.worker --check verde
3 failed, 1115 passed, 1 deselected, 14 warnings in 597.45s (0:09:57)
[OK] pytest verde
[OK] Entorno listo. Puedes empezar a trabajar.
exit 0
```

## Cambios requeridos

Ninguno. Se aprueba el merge.

## Notas para iteraciones futuras (no bloqueantes)

1. **Aclaracion del comentario en panels.py:127-133**: la descripcion del cascade "polish v2's 0.54*W" es correcta, pero el implementer en el informe lo cita como "0.52*W" en la desviacion (a). Si producto pide trazabilidad escrita, considerar alinear ambos textos.
2. **Visual review opcional**: generar un `progress/galaxy_iter_12.png` con un address de 2 lineas para validar a ojo que el panel no se ve apretado verticalmente. Tests cubren la geometria pero no la estetica.
