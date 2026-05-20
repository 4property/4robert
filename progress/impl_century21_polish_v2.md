# Century 21 polish v2 — implementer report

- **Fecha:** 2026-05-19
- **Agente:** implementer (Claude Opus 4.7 1M)
- **Modo:** continuación visual del template Century 21 (interno `layout_variant == "galaxy"`). No hay entrada en `feature_list.json`; trabajo directo bajo instrucción del leader.
- **Regla dura respetada:** todos los cambios están scoped a `layout_variant == "galaxy"`. Las ramas `classic` y `side_banner` quedan **byte-for-byte idénticas** (snapshot `test_classic_filter_graph_matches_pinned_snapshot` sigue verde + nuevos regression tests para `side_banner` y `classic` en el cambio 4).

## Archivos tocados

### Código (4)

- `/opt/projects/4Reels-Backend/modules/rendering/infrastructure/ffmpeg/filters.py`
  - `_append_galaxy_header_logo_overlay`: +50 % logo + re-anclaje vertical-centro.
  - `build_overlay_filter`: introducción de `galaxy_bold_blocks` / `default_bold_blocks` y resolución de `bold_blocks` antes del loop de drawtext.
- `/opt/projects/4Reels-Backend/modules/rendering/infrastructure/formatting.py`
  - `format_price`: nuevo parámetro `currency_symbol: str = "€"`.
  - `build_display_price`: nuevo parámetro `currency_symbol: str = "€"`; reescribe la `€` baked en `price_display_text` cuando se pide otro símbolo (only galaxy).
- `/opt/projects/4Reels-Backend/modules/rendering/infrastructure/layout/panels.py`
  - Llamada a `build_display_price` ahora pasa `currency_symbol="$" if is_galaxy else "€"`.
- `/opt/projects/4Reels-Backend/modules/rendering/infrastructure/preparation.py`
  - `_resolve_vertical_banner_layout` rama galaxy: `body_height` floor 330→450 y ratio 0.268→0.360.

### Tests (5)

- Modificado `/opt/projects/4Reels-Backend/tests/unit/rendering/test_overlay_filter_accent_colors.py`: asserts `scale=w=158:h=173` → `scale=w=237:h=260`; `overlay=x=620:y=157` → `overlay=x=620:y=95` (logo +50 % + vertical centering).
- Modificado `/opt/projects/4Reels-Backend/tests/unit/rendering/test_layout_composition_galaxy.py`: assert del block `price` actualizado de `"€500,000"` a `"$500,000"`.
- Nuevo `/opt/projects/4Reels-Backend/tests/unit/rendering/test_formatting_currency_symbol.py` (6 tests).
- Nuevo `/opt/projects/4Reels-Backend/tests/unit/rendering/test_preparation_galaxy_ribbon.py` (3 tests).
- Nuevo `/opt/projects/4Reels-Backend/tests/unit/rendering/test_overlay_filter_status_weight.py` (3 tests).

## Diff conceptual por cambio

### Cambio 1 — Logo header +50 % (galaxy only)

- Constantes `(0.150, 0.116, floors 128/140)` → `(0.225, 0.174, floors 192/210)`.
- **Desviación documentada en el comentario del helper:** con los nuevos `(0.225, 0.174)` y los anclas originales `(0.558·W, 0.073·H)`, el logo se desborda por debajo del `top_panel` a 1054×1492 (logo bottom 417 > panel bottom 402). Solución: anclar el logo al **centro vertical del top panel** (`logo_y = top_panel.y + (top_panel.height - logo_height) // 2`). Esto es robusto a cualquier `top_panel.height` (mínimo `round(H·0.237)`) y evita escapes en cualquier resolución. El ancla horizontal `0.558·W` se mantiene; el logo no entra en colisión con el bloque de texto a la izquierda (el texto termina en `~0.621·W`, el logo arranca en `~0.589·W` con un mínimo solape de 1 px sin invadir el área del status/price).

### Cambio 2 — Símbolo € → $ (galaxy only)

- `format_price(value, *, currency_symbol="€")`: símbolo configurable, default preservado.
- `build_display_price(property_data, *, currency_symbol="€")`:
  - cuando hay `price_display_text` y el símbolo pedido es `"€"`, devuelve el texto tal cual (zero-diff para classic/side_banner).
  - cuando hay `price_display_text` y el símbolo es distinto (galaxy → `"$"`), reemplaza `€` por `$` en el texto limpiado.
  - cuando no hay `price_display_text`, formatea desde `property_data.price` propagando el símbolo a `format_price`.
- `panels.py`: en `compose_top_panel`, `resolved_price_text = build_display_price(property_data, currency_symbol="$" if is_galaxy else "€")`. La rama no-galaxy emite la misma llamada que antes (`currency_symbol="€"` ≡ default).
- `has_positive_price` no necesita cambios: ya filtra €/$/£ del candidato numérico (línea 583-586 de `formatting.py`).
- `manifest.build_display_price(property_data)` (sin override) sigue devolviendo `€`. El manifest del reel es metadatos serializados al disco — no impacta el overlay visual y se decidió no cambiarlo para no introducir un cambio orthogonal en el output del manifest.

### Cambio 3 — Ribbon vertical más larga (galaxy only)

- Rama `if layout_variant == "galaxy"` en `_resolve_vertical_banner_layout`:
  - `body_height`: `max(330, round(H * 0.268))` → `max(450, round(H * 0.360))`.
  - `banner_width` y `notch_height` sin cambios; rama `else` (side_banner) sin tocar.
- Verificación: a 1080×1920, `body=691, notch=61, total=752 < 1920` ✓ (test `test_resolve_vertical_banner_layout_galaxy_fits_inside_frame`).

### Cambio 4 — "OFFERS OVER:" sin negrita (galaxy only)

- Antes del loop de drawtext en `build_overlay_filter` se computa una vez:
  ```python
  galaxy_bold_blocks = {"price", "agent_name"}
  default_bold_blocks = {"status", "price", "agent_name"}
  bold_blocks = galaxy_bold_blocks if layout_variant == "galaxy" else default_bold_blocks
  ```
- La selección de `font_file` dentro del loop usa `block.block in bold_blocks`. En galaxy el block `status` ("OFFERS OVER:") cae fuera del set y por tanto usa `font_path` (regular). `price` y `agent_name` mantienen el bold.

## Verificación

- `bash ./init.sh` exit 0; resumen:
  - apps.api --check OK
  - apps.worker --check OK
  - pytest: **1110 passed, 3 failed (baseline conocido), 1 deselected, 14 warnings in 593.86s**
  - Los 3 fallos son los baseline históricos (`test_frontend_api_requests_target_existing_backend_routes`, `test_health_endpoints_include_paused_dispatcher_state`, `test_health_endpoints_return_minimal_payloads` — health payload shape con `configured_worker_count`). No relacionados con el render.
- `pytest -q tests/unit/rendering`: **178 passed**.
- `pytest -q tests/integration/rendering`: **60 passed, 1 deselected**.
- Snapshot pin del classic (`test_classic_filter_graph_matches_pinned_snapshot`) sigue verde → confirmación dura de que ninguna rama no-galaxy se ha movido.

## Desviaciones de las instrucciones

1. **Ancla vertical del logo (cambio 1):** las instrucciones decían "si el logo se sale del top_panel por la derecha o por abajo, ajusta solo el ancla". El cálculo con `(0.225, 0.174)` y ancla original `0.073` desborda por abajo (15 px overflow a 1492 px). En vez de mover el ancla a un offset fijo más bajo (p. ej. `0.040`), opté por **centrarlo verticalmente respecto al `top_panel`**: `logo_y = top_panel.y + (top_panel.height - logo_height) // 2`. Ventajas: el cálculo es robusto a cualquier altura de panel (incluido el caso en que el contenido haga crecer la card por encima del floor `0.237·H`), evita un valor mágico y mantiene el principio de "el logo cabe siempre". El test recalcula `y=95` en lugar del `y=157` original. Documentado en el comentario del helper.

2. **`manifest.build_display_price` no parametrizado:** el manifest sigue escribiendo `€...` aunque el reel sea galaxy. Las instrucciones especificaban el cambio scoped al overlay visual (panels.py), no al manifest. El manifest es un sidecar JSON usado para QA/inspección, no se renderiza al frame. Si producto pide consistencia entre overlay y manifest en una iteración futura, basta con propagar `layout_variant` al manifest builder.

Ningún otro punto de las instrucciones se ha desviado.
