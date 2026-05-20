# Review — Century 21 polish v2

- **Fecha:** 2026-05-19
- **Reviewer:** Claude Opus 4.7 (1M)
- **Informe del implementer:** `progress/impl_century21_polish_v2.md`

## Veredicto

**APPROVED**

## Resumen de validacion

| Cambio | Scope galaxy-only | Test added/updated | Evidencia |
| --- | --- | --- | --- |
| 1. Logo header +50 % | OK | OK | filters.py:432-448 (gate `layout_variant == "galaxy"`); helper en filters.py:214 con math `logo_y = top_panel.y + (top_panel.height - logo_height)//2`; test actualizado `tests/unit/rendering/test_overlay_filter_accent_colors.py:163-187` con `scale=w=237:h=260` y `overlay=x=620:y=95`. |
| 2. Simbolo `€` -> `$` | OK | OK | panels.py:171-174 (`currency_symbol="$" if is_galaxy else "€"`); formatting.py:578-582 (default `"€"` devuelve cleaned text byte-for-byte); 6 tests nuevos en `tests/unit/rendering/test_formatting_currency_symbol.py`; test ya existente `tests/unit/rendering/test_layout_composition_galaxy.py:240` actualizado a `"$500,000"`. |
| 3. Cinta vertical mas larga | OK | OK | preparation.py:272-283: rama `if layout_variant == "galaxy"` con `body_height = max(450, round(H*0.360))`; rama `else` mantiene constantes historicas `max(420, round(H*0.325))` byte-for-byte; 3 tests nuevos en `tests/unit/rendering/test_preparation_galaxy_ribbon.py` incluyendo regresion para side_banner. |
| 4. "OFFERS OVER:" sin negrita | OK | OK | filters.py:455-462: `bold_blocks = galaxy_bold_blocks if layout_variant == "galaxy" else default_bold_blocks`. `galaxy_bold_blocks = {"price","agent_name"}`, `default_bold_blocks = {"status","price","agent_name"}`; 3 tests nuevos en `tests/unit/rendering/test_overlay_filter_status_weight.py` con regresion para classic y side_banner. |

## Verificacion matematica del logo (cambio 1)

Para frame 1054x1492:

- `top_panel_height = max(192, round(1492*0.237)) = max(192, 354) = 354`
- `top_panel_y = round(1492*0.032) = 48`
- `top_panel_x = round(1054*0.030) = 32`
- `logo_width = max(192, round(1054*0.225)) = 237`
- `logo_height = max(210, round(1492*0.174)) = 260`
- `logo_x = top_panel_x + round(1054*0.558) = 32 + 588 = 620`
- `logo_y = top_panel_y + (354 - 260)//2 = 48 + 47 = 95`

Coincide con el test `scale=w=237:h=260[galaxy_header_logo_source]` y `overlay=x=620:y=95`. OK.

El logo cabe siempre dentro del panel: `logo_y + logo_height = 95 + 260 = 355 <= top_panel.y + top_panel.height = 48 + 354 = 402`. OK con 47 px de holgura.

## No-regression checks

### Classic
- `tests/unit/rendering/test_overlay_filter_classic_snapshot.py::test_classic_filter_graph_matches_pinned_snapshot` -> PASS.
- `pytest -q tests/unit/rendering -k "classic"` -> 11 passed, 167 deselected.
- Nuevo `test_classic_status_block_keeps_bold_weight` -> PASS.

### Side_banner
- `pytest -q tests/unit/rendering -k "side_banner"` -> 36 passed, 142 deselected.
- Nuevo `test_side_banner_status_block_keeps_bold_weight` -> PASS.
- Nuevo `test_resolve_vertical_banner_layout_side_banner_unaffected_by_galaxy_polish` -> PASS (verifica que side_banner `body_height == round(1920*0.325)` no cambia).
- Verificacion manual del diff: rama `else` en `_resolve_vertical_banner_layout` mantiene constantes historicas. El unico cambio en la salida es el calculo de `x`, que para `side_banner` sigue siendo `round(W*0.778)` (= valor historico).

### Suite completa
- `bash ./init.sh` exit 0; resumen: `3 failed, 1110 passed, 1 deselected, 14 warnings in 592.59s`.
- `pytest -q tests/unit/rendering` -> 178 passed.
- `pytest -q tests/integration/rendering` -> 60 passed, 1 deselected.

## Veredicto sobre los 3 fallos baseline

Los 3 fallos son **baseline historico documentado**, no regresiones:

1. `tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes` — falla por `FRONTEND_REPO_ROOT` apuntando a una ruta Windows que no existe en este host.
2. `tests/integration/test_http_transport.py::test_health_endpoints_include_paused_dispatcher_state` — shape del payload de `/health` (`configured_worker_count`).
3. `tests/integration/test_http_transport.py::test_health_endpoints_return_minimal_payloads` — mismo shape del payload de `/health`.

Confirmacion empirica: `git stash && pytest -q tests/integration/test_http_transport.py tests/integration/test_http_surface_contract.py && git stash pop` produce exactamente los **mismos 3 fallos** con identicos mensajes. Por tanto NO son regresiones introducidas por polish v2.

Adicionalmente, `progress/current.md` los documenta como baseline desde 2026-05-14 (HOTFIX side_banner_footer_radius y posteriores).

Ninguno de los 3 fallos es de `modules/rendering`, `tests/unit/rendering` ni `tests/integration/rendering`.

## Veredicto sobre las 2 desviaciones del implementer

### Desviacion 1: ancla vertical del logo centrada respecto al `top_panel`

**Aceptada.** El implementer documenta que los nuevos `(0.225, 0.174)` con el ancla original `0.073*H` desbordan el panel por abajo (15 px overflow a 1492 px). La solucion adoptada — anclar al centro vertical del `top_panel` — es:

- Robusta a cualquier `top_panel.height` (incluso si el contenido hace crecer la card por encima del floor `0.237*H`).
- Mejor que un offset fijo magico (`0.040`, etc.) porque sigue centrando el logo aunque el panel cambie de tamano dinamicamente segun el contenido medido.
- Documentada en el comentario del helper (`filters.py:214`).
- Validada matematicamente (ver seccion arriba).
- Pinned por el test `test_galaxy_header_uses_century21_logo_asset_instead_of_ber` que ya pasa.

### Desviacion 2: `manifest.build_display_price` no parametrizado (sigue con `€`)

**Aceptada como riesgo bajo a documentar (no FAIL).**

- El manifest se escribe a `<staging>/resolved-manifest.json` como sidecar JSON de QA/auditoria; **no** se renderiza al frame.
- No hay ningun transport handler que exponga este manifest al frontend publico (`grep` sobre `modules/reels/transport` y `modules/rendering/transport` para `resolved-manifest`, `resolved_manifest_path`, `build_display_price` -> 0 matches).
- La instrucciones del leader acotaban el cambio al overlay visual (panels.py), no al manifest.
- Para una iteracion futura, basta con propagar `layout_variant` al manifest builder y llamar `build_display_price(property_data, currency_symbol="$" if layout_variant=="galaxy" else "€")` en `manifest.py:242`.

Documentado en este review como deuda menor para iteracion futura.

## Checkpoints (CHECKPOINTS.md)

- C1 (no nuevo codigo en directorios legacy): OK — todos los cambios viven en `modules/rendering/...`.
- C2 (aislamiento de capas): OK — no hay imports cross-module nuevos. `domain/` no se toca; `application/` no se toca; cambios solo en `infrastructure/`.
- C3 (sin nuevas tablas / migraciones): N/A — esta feature no toca schema.
- C4 (tests nuevos para cada cambio): OK — 12 tests nuevos (6 currency + 3 ribbon + 3 status weight) + 1 test existente actualizado para el cambio de logo.
- C5 (init.sh verde excepto baseline): OK.
- C6 (sin secretos en plano): N/A — no se introducen credenciales ni rutas sensibles.

## Cambios requeridos

Ninguno. Se aprueba el merge.

## Notas para iteraciones futuras (no bloqueantes)

1. **Consistencia manifest <-> overlay (deuda menor):** propagar `layout_variant` a `manifest.write_property_reel_manifest_from_data` para que `"price"` en el JSON refleje el simbolo `$` cuando `layout_variant == "galaxy"`.
2. **Convertir el comentario del helper `_append_galaxy_header_logo_overlay` en un docstring** para que el reasoning quede capturado en `help()`/IDE. Cosmetico.
