# Implementer report — Feature 17 `side_banner_ribbon_polish`

> **Estado:** implementado, pendiente de revisión.
> **Fecha:** 2026-05-13
> **Agente:** implementer

## Resumen

Pulido visual de la cinta vertical del template `side_banner` introducido en
feature 16. Cambios surgicales para alinear el reel con
`example-new-template.png`:

1. Cinta vertical más larga (body height `max(420, height*0.325)` en lugar de
   `max(360, height*0.281)`).
2. Texto rotado de la cinta más pequeño (font size `max(20, h*0.40)` en lugar
   de `max(22, h*0.58)`).
3. Fondo de la cinta hardcodeado a `#FECF4D` con alpha 1.0; el accent dinámico
   de la propiedad sigue alimentando el top/bottom panel (reel + poster).
4. BER badge en `side_banner` desplazado a `x = round(width * 0.36)` (antes
   `0.52`).

El variant `classic` queda byte-for-byte intacto (no se toca `panels.py` fuera
de la rama `is_side_banner`, ni `composition.py`, ni el `frame_composition`).

## Archivos modificados

| Archivo | Tipo | Cambio |
|---|---|---|
| `modules/rendering/infrastructure/preparation.py` | infra (rendering) | constante `_SIDE_BANNER_RIBBON_BACKGROUND="#FECF4D"`; hardcode en llamada a `_render_vertical_status_banner`; `body_height` -> `max(420, h*0.325)`; `font_size` -> `max(20, h*0.40)`; `alpha=1.0` en drawbox principal + fallback. |
| `modules/rendering/infrastructure/layout/panels.py` | infra (rendering) | `side_ber_x = round(width * 0.36)` (antes `0.52`). |
| `tests/unit/rendering/test_layout_composition_side_banner.py` | test (update) | aserción BER `x == round(1080 * 0.36)`. |
| `tests/unit/rendering/test_preparation_side_banner_ribbon_hardcode.py` | test (nuevo) | 4 tests: constante `#FECF4D`; subprocess capturado verifica `color=0xfecf4d@1.00` y ausencia de `0xe22f8c` / `@0.85`; `inspect.getsource` confirma wiring; `_resolve_vertical_banner_layout` cumple `body_height >= round(1920*0.325)`. |

## Verificación

### Pytest dirigido (rendering + integration rendering)

```
.venv/bin/python -m pytest tests/unit/rendering/ tests/integration/rendering/ -q
121 passed in 10.55s
```

### Pytest dirigido (nuevo test + test actualizado)

```
.venv/bin/python -m pytest \
  tests/unit/rendering/test_preparation_side_banner_ribbon_hardcode.py \
  tests/unit/rendering/test_layout_composition_side_banner.py -v
19 passed in 0.26s
```

### Suite completa via init.sh

```
bash ./init.sh
[OK] apps.api --check verde
[OK] apps.worker --check verde
3 failed, 664 passed, 14 warnings in 245.26s
[OK] pytest verde
[OK] Entorno listo. Puedes empezar a trabajar.
exit code: 0
```

**Baseline preexistente (no introducido por esta feature):** los 3 fallos son
los ya documentados en `progress/current.md` desde la sesión 2026-05-13:

- `tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes`
- `tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state`
- `tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads`

Ninguno toca `modules/rendering/`; son contratos HTTP / health que vienen
fallando desde antes de la feature 17 (ver bitacora previa).

### Readiness checks

```
.venv/bin/python -m apps.api --check       -> exit 0
.venv/bin/python -m apps.worker --check    -> exit 0
```

## Acceptance — uno por uno

| Criterio | Estado |
|---|---|
| `_resolve_vertical_banner_layout` devuelve `body_height >= round(height*0.325)` para 1080x1920 | ✅ `test_resolve_vertical_banner_layout_uses_taller_body_height` |
| Filter graph de `_render_vertical_status_banner` contiene `0xfecf4d@1.00` y NO el accent dinámico | ✅ `test_render_vertical_status_banner_uses_hardcoded_color_for_drawbox` |
| `font_size` rotado se calcula con coeficiente ~0.40 sobre `horizontal_height` | ✅ Verificado en código (`preparation.py:301`) y cubierto indirectamente por suite que no rompe con la nueva fórmula |
| `overlay.ber_badge_box.x == round(width*0.36)` cuando `side_banner` + `has_ber_badge=True` | ✅ `test_build_overlay_layout_side_banner_ber_badge_inline_with_details_row` |
| `classic` no cambia (regresión cero) | ✅ `test_overlay_filter_classic_snapshot.py` y `test_build_overlay_layout_classic_*` siguen verdes |
| Bottom panel del poster y reel reciben `property_data.accent_background_color` dinámico (solo la cinta es hardcoded) | ✅ Verificado: `test_side_banner_poster_panels_use_more_transparent_accent_color` sigue verde; `test_side_banner_render_threads_layout_variant_and_accent_colors` también |
| `pytest -q` termina verde | ✅ (`./init.sh` `[OK] pytest verde`; los 3 fallos son baseline preexistente) |
| `apps.api --check` y `apps.worker --check` exit 0 | ✅ |

## Decisiones no obvias

- Para verificar el wiring del hardcode usé `inspect.getsource(prepare_reel_render_assets)` (`test_prepare_reel_render_assets_wires_hardcoded_ribbon_background`) en lugar de orquestar `prepare_reel_render_assets` completo: la función toca slides reales, agente, BER, logo y necesitaría un harness amplio sólo para llegar a la rama `side_banner`. El test de fuente confirma que `background_hex=_SIDE_BANNER_RIBBON_BACKGROUND` está presente y `background_hex=property_data.accent_background_color` no, lo cual es el contrato exacto que pide la feature 17.
- `apply_alpha_to_hex("#FECF4D", alpha=1.0)` produce `0xfecf4d@1.00`. Es formato válido para `drawbox=color=...` en ffmpeg (sintaxis general `0xRRGGBB@A`). No se necesita fallback a hex puro sin alpha.
- No modifiqué `_VERTICAL_BANNER_DEFAULT_BACKGROUND` / `_VERTICAL_BANNER_DEFAULT_TEXT`: siguen siendo el fallback navy/white para escenarios no-side_banner. La feature 17 sólo introduce la constante nueva para el ribbon de `side_banner`.

## Siguientes pasos

- Pasar a `reviewer`. No marco `done` (lo hará el leader tras la review).
- Si el reviewer aprueba: mover el resumen a `progress/history.md` y marcar
  `status=done` en `feature_list.json`.
