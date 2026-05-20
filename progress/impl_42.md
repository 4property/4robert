# Implementer — Feature 42 `galaxy_render_template`

- **Inicio:** 2026-05-18
- **Agente:** Claude (implementer, lanzado por leader)
- **Status feature_list.json:** `pending` -> `in_progress` (cierro el turno en `in_progress`; el reviewer la marcará `done`).
- **Toca schema?:** No (data-model intacto; cero campos nuevos en `BrandSettings`, `PropertyRenderData` ni `_RENDERER_INTERNAL_OVERRIDE_KEYS`).

## Plan operativo (aplicado)

Las decisiones del leader se respetan al pie de la letra:
- **El círculo central con el logo grande NO se implementa** (fuera de scope v1).
- **Cero cambio de data-model**. Galaxy reutiliza VERBATIM `side_banner_panel_color`, `side_banner_ribbon_background_color` y `accent_*_color` que ya existen.

## Archivos creados / modificados

### Código de producción

| Archivo | Tipo | Cambio |
|---|---|---|
| `modules/rendering/infrastructure/render_template_settings.py` | const | Añadido `"galaxy"` al frozenset `SUPPORTED_LAYOUT_VARIANTS` + nueva constante `GALAXY_RENDER_TEMPLATE_ID = "galaxy"`. Exportada en `__all__`. |
| `modules/rendering/infrastructure/layout/composition.py` | layout | Rama `layout_variant in {"side_banner", "galaxy"}` → `outer_margin_x/y = 0` (full-bleed). |
| `modules/rendering/infrastructure/layout/panels.py` | layout | Introducidas variables `is_galaxy = layout_variant == "galaxy"` y helper `is_side_banner_like = is_side_banner or is_galaxy` en `compose_top_panel` y `compose_bottom_panel`. Galaxy: top panel a `x = 4% width`, `y = 3.5% height`, `width = 48% width`, `height >= 18% height`. Bottom panel reusa la geometría side_banner verbatim (94% inset, anchored 78.1% from top). BER badge alineado al `address_meta` row con `x = round(width * 0.38)` (ligeramente más derecha que side_banner para caber en panel más estrecho). Status hardcoded "OFFERS OVER:" + price reusado verbatim. |
| `modules/rendering/infrastructure/ffmpeg/filters.py` | filter graph | En `build_overlay_filter`: cuando `layout_variant in {"side_banner", "galaxy"}` se aplica `_build_rounded_panel_source` al BOTTOM panel; cuando `layout_variant == "galaxy"` se aplica TAMBIÉN al TOP panel (side_banner solo redondea el bottom, galaxy redondea ambos). Mismo `_resolve_side_banner_footer_radius` helper para ambos. |
| `modules/rendering/infrastructure/ffmpeg/render_reel.py` | render | Cascada `panel_color` y `text_override` extendida a `layout_variant in {"side_banner", "galaxy"}`. Threading de `vertical_banner_path` igual. |
| `modules/rendering/infrastructure/preparation.py` | render | Rama `layout_variant in {"side_banner", "galaxy"}` invoca el MISMO `_render_vertical_status_banner` con los MISMOS parámetros (FOR SALE label, banner_layout, color cascades). `_normalize_agent_image` aplica la misma máscara circular y fill para ambos variants. |
| `modules/rendering/infrastructure/poster.py` | render | Cascada `poster_panel_color`/`poster_text_override` extendida a `layout_variant in {"side_banner", "galaxy"}`. Threading de `vertical_banner_path` igual. |

### `frame_composition.py`

No tocado. La propagación de `layout_variant` ya era string-based desde feature 16; el valor `"galaxy"` llega intacto a `prepare_reel_render_assets`, `build_filter_complex` y `build_overlay_layout` sin guards extra. Tests verifican el end-to-end.

### Migraciones Alembic

| Archivo | Tipo | Down revision | Acción |
|---|---|---|---|
| `alembic/versions/20260518_0001_seed_galaxy_render_template.py` | seed | `20260517_0001` | `INSERT` row `template_id='galaxy'`, `display_name='Galaxy'`, `sort_order=2`, `layout_variant='galaxy'`, `preview_images='[]'`, `reel_settings='{}'`, `poster_settings='{}'`. `ON CONFLICT (template_id) DO NOTHING`. Downgrade `DELETE` protegido por `template_id='galaxy' AND layout_variant='galaxy'`. |
| `alembic/versions/20260518_0002_galaxy_render_template_preview.py` | data | `20260518_0001` | `UPDATE preview_images` a `[{kind:"preview", image_url:"/assets/render-templates/galaxy-template.png", alt:"Galaxy template preview"}]`. Downgrade idempotente (solo revierte si el JSONB matchea el payload aplicado). |

### Asset

| Archivo | Origen |
|---|---|
| `assets/render-templates/galaxy-template.png` | **Opción B (placeholder)** — copia byte-for-byte de `side-banner-template.png` (959 567 bytes). Decisión por iteración 1: el rig visual produce `progress/galaxy_iter_1.png` que aproxima la referencia pero todavía no es pixel-perfect (anchorado del bottom panel ligeramente por encima del reference; falta el círculo central que es out-of-scope v1). El leader puede promover `progress/galaxy_iter_N.png` (de la siguiente iteración aprobada) sobreescribiendo el placeholder con `cp progress/galaxy_iter_<N>.png assets/render-templates/galaxy-template.png` antes de cerrar el review. |

### Tests

| Archivo | Tipo | Coverage |
|---|---|---|
| `tests/unit/rendering/test_layout_composition_galaxy.py` | unit | 14 tests. Geometría top/bottom, posiciones %, OFFERS OVER price logic, BER inline, anchors izquierda/derecha del footer, regression guard classic. |
| `tests/unit/rendering/test_frame_composition_accent_colors_galaxy.py` | unit | 4 tests. Cascada `side_banner_panel_color` + `side_banner_ribbon_background_color` end-to-end vía `_build_render_data` con layout_variant="galaxy". Fallback to None. |
| `tests/integration/rendering/test_galaxy_render.py` | integration | 4 tests. Mock prepare/manifest/reel/poster + assert que `layout_variant="galaxy"` propaga end-to-end; brand panel color + ribbon color travel correctly. |
| `tests/integration/configuration/test_render_templates_router.py` | integration | +1 test `test_render_templates_list_includes_galaxy` — sort_order=2, display_name='Galaxy', layout_variant='galaxy', preview_images populated tras migration 0002. |
| `tests/integration/apps_api/test_render_template_assets.py` | integration | +1 test `test_api_serves_galaxy_render_template_preview_asset`. |
| `tests/integration/rendering/test_galaxy_iter.py` | visual_iter | 1 test `test_galaxy_visual_iter_renders_progress_png`. Marca `@pytest.mark.visual_iter`. Renderiza real frame (no mock) con `generate_property_poster_from_data(..., layout_variant="galaxy")` a 1054×1492 a partir de una foto real de `property_media/`. Escribe `progress/galaxy_iter_<N>.png` (siguiente índice libre). |

### Config

| Archivo | Cambio |
|---|---|
| `pytest.ini` | Añadido `addopts = -p no:cacheprovider -m "not visual_iter"` (excluye el marker por default; init.sh no corre el test pesado de ~3s). Registrado el marker `visual_iter` en `markers =` para evitar warnings. |
| `feature_list.json` | Feature 42 status `pending` → `in_progress`. Status final lo pone el reviewer. |

## Decisiones no obvias

- **Galaxy comparte el "OFFERS OVER:" hardcode con side_banner**, aunque la referencia visual no muestra el texto literal (muestra `$599,900` directamente). Decisión: el ribbon vertical ya dice "FOR SALE", así que el panel debe decir "OFFERS OVER:" + price (no es redundante; misma lógica de feature 16b gap #1). Es coherente con el cascade compartido.
- **El radio del top panel galaxy se calcula con `_resolve_side_banner_footer_radius`** (mismo helper que el bottom). El nombre tiene "footer" por legacy, pero el cómputo es genérico (`min(panel_w//2, panel_h//2, max(12, round(frame_h * 0.0125)))`). No renombré el helper para no introducir un refactor cross-cutting.
- **BER badge x para galaxy = `round(width * 0.38)`** (vs `0.36` de side_banner). El panel galaxy es más estrecho (~48% width vs 100%), así que el BER necesita ligero shift a la derecha para no chocar con el bloque de address_meta. Verificado en `test_build_overlay_layout_galaxy_ber_badge_inline_with_details_row`.
- **El asset preview** (`assets/render-templates/galaxy-template.png`) usa opción B (placeholder = copy de side-banner-template.png) en lugar de promover directamente `galaxy_iter_1.png`. El leader puede comparar la iteración con `example-template-galaxy.png` y decidir si pide otra iteración antes de canonizar el asset.

## Verificación

### Tests focales (galaxy + extensiones)

```
$ .venv/bin/python -m pytest tests/unit/rendering/test_layout_composition_galaxy.py tests/unit/rendering/test_frame_composition_accent_colors_galaxy.py tests/integration/rendering/test_galaxy_render.py tests/integration/configuration/test_render_templates_router.py tests/integration/apps_api/test_render_template_assets.py -q -v
...
============================= 31 passed in 12.24s ==============================
```

### Alembic roundtrip

```
$ .venv/bin/python -m alembic upgrade head
... Running upgrade 20260517_0001 -> 20260518_0001 ...
... Running upgrade 20260518_0001 -> 20260518_0002 ...

$ .venv/bin/python -m alembic downgrade -2
... Running downgrade 20260518_0002 -> 20260518_0001 ...
... Running downgrade 20260518_0001 -> 20260517_0001 ...

$ .venv/bin/python -m alembic upgrade head
... Running upgrade 20260517_0001 -> 20260518_0001 ...
... Running upgrade 20260518_0001 -> 20260518_0002 ...
```
Limpio en ambos sentidos.

### Readiness

```
$ .venv/bin/python -m apps.api --check
... RUNTIME READY: Yes ...
$ .venv/bin/python -m apps.worker --check
... Worker --check OK: kinds=email_send, reel_publish, scripted_render ...
```

### init.sh

```
$ bash ./init.sh
...
3 failed, 1087 passed, 1 deselected, 14 warnings in 579.37s (0:09:39)
[OK]    pytest verde
...
[OK]    Entorno listo. Puedes empezar a trabajar.
```

**1087 passed** (baseline previo 1063 + 24 nuevos = 1087). **3 failed** exactamente los baseline históricos (`test_http_surface_contract.py` + 2 en `test_http_transport.py`) — no he tocado ese código. **1 deselected** = el `test_galaxy_iter.py` excluido por el marker `visual_iter`. Exit code 0.

### Rig de iteración visual

```
$ .venv/bin/python -m pytest tests/integration/rendering/test_galaxy_iter.py -m visual_iter -q -s
[galaxy_iter] wrote /opt/projects/4Reels-Backend/progress/galaxy_iter_1.png
.
1 passed in 3.04s
```

`progress/galaxy_iter_1.png` (1054×1492, PNG RGB) generado en 3s con FFmpeg vía `generate_property_poster_from_data(..., layout_variant="galaxy")`.

#### Comparación cualitativa contra `example-template-galaxy.png`

| Elemento | Referencia | Iteración 1 | Estado |
|---|---|---|---|
| Top panel rounded info card | Sí, anchored top-left, ancho ~48% | Sí, anchored top-left, ancho 48% | OK |
| "OFFERS OVER:" + price + address + specs | Sí | Sí | OK |
| BER badge alineado al address_meta | n/a en referencia | Sí | OK (regression-tested) |
| Vertical FOR SALE ribbon arriba-derecha | Sí, dorado | Sí, dorado (`#C9A24B`) | OK |
| Bottom panel rounded card | Sí, ~94% width inset abajo | Sí, ~94% width inset | OK |
| Agent photo circular | Sí | Sí | OK |
| Agent contact + agency logo placeholder | Sí | Sí (logo placeholder porque la fixture no proporciona uno) | OK |
| Círculo central con logo agencia | Sí | NO (out-of-scope v1) | Confirmado scope |
| Full-bleed photo | Sí | Sí | OK |
| Posición vertical del bottom panel | Anchored cerca del borde inferior | A ~78.1% Y (un poco más arriba que en la referencia) | Aceptable; mejorable en iter 2 si el leader lo pide |

La iteración 1 cubre todos los elementos de scope. El bottom panel queda ~3-5% más alto que en la referencia, pero está dentro del rango "se aproxima razonablemente" del acceptance criterion. El leader decide.

## Bitácora

- 2026-05-18 14:35 — Implementer arranca. Lee scope feature 42 + 3 explorers (`progress/explore_galaxy_*`) + reference image. Marca `feature_list.json` status `in_progress`.
- 2026-05-18 14:36 — Cambio mínimo a `render_template_settings.py` (`SUPPORTED_LAYOUT_VARIANTS` + constante).
- 2026-05-18 14:38 — `composition.py` extiende rama full-bleed a galaxy. `panels.py` introduce `is_galaxy` + `is_side_banner_like` helpers, reusa cascades de typography/BER/footer pero introduce geometría propia para top panel galaxy (48% width, 3.5% y, 18% min height).
- 2026-05-18 14:40 — `filters.py` redondea AMBOS top y bottom para galaxy (side_banner solo redondea bottom). `preparation.py` widens condición vertical_banner + circular agent mask. `render_reel.py` y `poster.py` extienden cascade panel_color/text_override.
- 2026-05-18 14:42 — Suite side_banner + classic verde (35 passed) tras los cambios — no hay regresiones.
- 2026-05-18 14:43 — Migraciones `20260518_0001` y `20260518_0002` escritas. `alembic upgrade head` + `downgrade -2` + `upgrade head` roundtrip OK.
- 2026-05-18 14:44 — Tests: 4 archivos nuevos + 2 extensiones. Marca `visual_iter` registrada en `pytest.ini` + excluida por addopts.
- 2026-05-18 14:45 — Asset placeholder copiado (opción B). Rig visual produce `progress/galaxy_iter_1.png` en 3s.
- 2026-05-18 14:46 — Verificación focal verde (31 passed). `apps.api --check` + `apps.worker --check` verdes.
- 2026-05-18 14:56 — `bash ./init.sh` exit 0: 1087 passed, 3 baseline failed, 1 deselected. Suite completa verde.

## Próximo paso

Reviewer toma el control: validar la implementación, comparar `progress/galaxy_iter_2.png` con `example-template-galaxy.png`, decidir si:
- (a) **Aprobar** la iteración 2 y promover `progress/galaxy_iter_2.png` → `assets/render-templates/galaxy-template.png` antes de marcar feature `done`.
- (b) **Pedir iteración 3** (otro turno del implementer) si todavía hay un gap visual no aceptable.
- (c) **Aprobar tal cual** dejando el placeholder side-banner como preview hasta una iteración futura.

Cuando el reviewer apruebe, marcar `status: "done"` en `feature_list.json` y mover el resumen de `progress/current.md` a `progress/history.md`.

---

## Iter 2

- **Inicio:** 2026-05-18 15:00 (segundo turno del implementer, requested por el leader tras revisar `progress/galaxy_iter_1.png`).
- **Scope acotado:** dos gaps cuantitativos vs `example-template-galaxy.png`:
  1. **Footer panel no llegaba al borde inferior.** Iter 1 anclaba `bottom_panel.y = round(height * 0.781)` (heredado verbatim de side_banner) lo que dejaba ~10 % en blanco bajo la card en la resolución 1054×1492 de la referencia. Iter 2 introduce una rama galaxy en `compose_bottom_panel` que ancla `y = frame_height - bottom_panel_height - bottom_margin` donde `bottom_margin = max(20, round(height * 0.018))`, dejando ~1.8 % de margen inferior. Side_banner sigue intacto en el `else if is_side_banner` branch (test side_banner verde, sin cambios).
  2. **Top panel rounded radius poco pronunciado.** Iter 1 reutilizaba `_resolve_side_banner_footer_radius` (`max(12, round(frame_h * 0.0125))` ≈ 19 px @ 1492 alto) — demasiado tímido vs la referencia. Iter 2 introduce un helper dedicado `_resolve_galaxy_panel_radius` en `modules/rendering/infrastructure/ffmpeg/filters.py` con floor `max(24, round(frame_h * 0.020))` ≈ 30 px @ 1492 alto. Se aplica TANTO al top como al bottom panel galaxy. Side_banner no se toca: su footer sigue llamando `_resolve_side_banner_footer_radius` con la fórmula histórica.

### Archivos modificados (Iter 2)

| Archivo | Cambio |
|---|---|
| `modules/rendering/infrastructure/layout/panels.py` | En `compose_bottom_panel`, el cómputo de `bottom_panel.y` se desdobla en tres ramas (`is_galaxy` / `is_side_banner` / classic) en vez del condicional ternario doble previo. Galaxy: `y = height - bottom_panel_height - max(20, round(height * 0.018))`. Side_banner y classic sin cambios funcionales (mismo valor por rama). |
| `modules/rendering/infrastructure/ffmpeg/filters.py` | Nuevo helper `_resolve_galaxy_panel_radius` (floor `max(24, round(frame_h * 0.020))`, mismo `min(panel_w//2, panel_h//2, …)` clamp que side_banner). `build_overlay_filter`: la rama del footer galaxy ahora resuelve el radius vía un local `footer_radius_resolver` que elige galaxy vs side_banner según `layout_variant`; la rama del top galaxy llama directamente al helper galaxy. Side_banner footer sigue llamando `_resolve_side_banner_footer_radius`. |
| `tests/unit/rendering/test_layout_composition_galaxy.py` | `test_build_overlay_layout_galaxy_uses_zero_outer_margins` y `test_build_overlay_layout_galaxy_bottom_panel_reuses_side_banner_card` actualizan el assert del `bottom_panel.y` a la nueva fórmula con un comentario `# iter 2: anchored a frame_bottom - bottom_margin`. El segundo test añade un sanity-check de que el bottom edge queda dentro de ~2.2 % del borde inferior del frame. |
| `tests/unit/rendering/test_filters_galaxy_radius.py` | **Nuevo** — 3 unit tests del helper `_resolve_galaxy_panel_radius`: caso típico 1080×1920 (galaxy > side_banner), floor en frame corto (`frame_height=600` → 24 px), y cap por panel_height (`panel_height=20` → 10 px). |

### Decisiones (Iter 2)

- **Helper dedicado para el radius galaxy** (en lugar de multiplicar el helper side_banner por un factor) — el leader sugería ambas opciones; opté por el helper dedicado porque el nombre `_resolve_side_banner_footer_radius` ya tiene "footer" hardcoded y aplicar un factor multiplicador desde fuera oculta la intención. Coste: 12 líneas más en `filters.py`, pero refleja literal qué queremos para galaxy. Side_banner sigue tal cual.
- **`bottom_margin = max(20, round(height * 0.018))`** sigue la sugerencia del leader literalmente. A 1492 px → 27 px de margen (1.8 %); a 1920 px → 35 px (1.8 %). El floor de 20 px protege resoluciones bajas (test radius cap @ 600 px).
- **Desdoblamiento de la rama `bottom_panel.y`** en tres bloques `if`/`elif`/`else` en vez de ternarios anidados. Más legible y evita meter aún más condicional anidado al añadir el caso galaxy.

### Verificación (Iter 2)

#### Focal tests verdes

```
$ .venv/bin/python -m pytest tests/unit/rendering/test_layout_composition_galaxy.py \
    tests/unit/rendering/test_frame_composition_accent_colors_galaxy.py \
    tests/unit/rendering/test_filters_galaxy_radius.py \
    tests/integration/rendering/test_galaxy_render.py \
    tests/integration/configuration/test_render_templates_router.py \
    tests/integration/apps_api/test_render_template_assets.py -q -v
...
============================= 34 passed in 11.91s ==============================
```

34 passed (iter 1: 31; iter 2 añade los 3 tests del nuevo helper).

#### Regression side_banner / classic

```
$ .venv/bin/python -m pytest tests/unit/rendering/test_layout_composition_side_banner.py \
    tests/unit/rendering/test_overlay_filter_accent_colors.py \
    tests/unit/rendering/test_layout_panels.py \
    tests/unit/rendering/test_layout_composition.py \
    tests/unit/rendering/test_overlay_filter_classic_snapshot.py -q
38 passed in 0.34s
```

Cero regresiones en side_banner ni classic.

#### Rig visual

```
$ .venv/bin/python -m pytest tests/integration/rendering/test_galaxy_iter.py -m visual_iter -q -s
[galaxy_iter] wrote /opt/projects/4Reels-Backend/progress/galaxy_iter_2.png
.
1 passed in 3.01s
```

`progress/galaxy_iter_2.png` generado (1054×1492 PNG, 1.81 MB).

#### init.sh full suite

```
$ bash ./init.sh
...
3 failed, 1090 passed, 1 deselected, 14 warnings in 580.95s (0:09:40)
[OK]    pytest verde
[OK]    Entorno listo. Puedes empezar a trabajar.
```

**1090 passed** (iter 1: 1087; +3 del nuevo `test_filters_galaxy_radius.py`). **3 failed** = baseline histórico (`test_http_surface_contract.py` + 2 en `test_http_transport.py` — no he tocado ese código). **1 deselected** = `test_galaxy_iter.py` (marker `visual_iter`). Exit 0.

### Gap residual contra `example-template-galaxy.png`

Comparación cualitativa de `progress/galaxy_iter_2.png` vs la referencia:

| Elemento | Referencia | iter_2 | Estado |
|---|---|---|---|
| Footer bottom edge near frame bottom | ~1.5 % margen | ~1.8 % margen | **Match** (delta acotado por el floor de 20 px). |
| Top panel corner radius visible | Sí, claramente | Sí, claramente (30 px @ 1492 alto) | **Match**. |
| Bottom panel corner radius visible | Sí | Sí (consistente con top) | **Match**. |
| Top panel anchor (top-left, ~48 % width) | Sí | Sí (sin cambio iter 1) | **Match**. |
| Vertical FOR SALE ribbon arriba-derecha | Sí, dorado | Sí, dorado | **Match**. |
| Agent photo circular | Sí | Sí | **Match**. |
| Círculo central con logo agencia | Sí | NO (out-of-scope v1) | Confirmado fuera de scope. |
| Tipografía / pesos exactos | Bold heavy | Bold (mismo cascade que side_banner) | Aceptable v1 — fixture-driven, no scope. |
| Logo "CENTURY 21" | Sí, dos líneas | Logo placeholder text "Agency" | Fixture-driven (la prop test no inyecta logo real). |
| Texto exacto del banner FOR SALE / OFFERS OVER | Sí | Sí | **Match**. |

**Veredicto:** los dos gaps cuantitativos identificados por el leader (footer no llega al borde + radius poco pronunciado) están cerrados. Diferencias remanentes son explícitamente fixture-driven (logo, foto de la propiedad, exact font weights) o fuera de scope v1 (círculo central). Listo para review.

### Bitácora (Iter 2)

- 2026-05-18 15:00 — Implementer iter 2 arranca. Lee `progress/impl_42.md` + scope del leader.
- 2026-05-18 15:01 — `panels.py`: desdobla la rama de `bottom_panel.y` en `is_galaxy`/`is_side_banner`/classic. Galaxy ancla `frame_bottom - bottom_margin`.
- 2026-05-18 15:02 — `filters.py`: nuevo helper `_resolve_galaxy_panel_radius`. Top panel galaxy llama directo; bottom panel galaxy/side_banner usa local `footer_radius_resolver` para elegir.
- 2026-05-18 15:02 — Tests: dos asserts actualizados en `test_layout_composition_galaxy.py`. Nuevo archivo `test_filters_galaxy_radius.py` (3 tests).
- 2026-05-18 15:03 — Focal verdes (34 passed). Side_banner / classic regression verde (38 passed).
- 2026-05-18 15:03 — `pytest -m visual_iter` produce `progress/galaxy_iter_2.png` en 3 s.
- 2026-05-18 15:14 — `bash ./init.sh` exit 0: 1090 passed, 3 baseline failed, 1 deselected. Listo para review.

---

## Iter 3

- **Inicio:** 2026-05-18 15:30 (tercer turno del implementer, requested por el leader tras revisar `progress/galaxy_iter_2.png`).
- **Scope acotado:** dos gaps proporcionales restantes vs `example-template-galaxy.png` (no fixture-driven, no out-of-scope):
  1. **Footer panel demasiado bajo / delgado.** Iter 2 mantenía el floor side_banner `max(round(h*0.113), …)` ≈ 168 px @ 1492. La referencia muestra un footer notablemente más chunky (~15-17 % del alto). Iter 3 eleva el floor galaxy a `max(round(h*0.150), …)` ≈ 224 px @ 1492. Side_banner conserva 0.113 sin tocar.
  2. **Tipografía del bloque de contacto demasiado pequeña.** Iter 2 usaba los bounds side_banner (agent_name max 26, contact max 24); la referencia muestra el nombre del agente claramente más grande/bolder que el contacto. Iter 3 bumpea bounds galaxy: agent_name a `max(32, round(h*0.022))` (≈ 33 px @ 1492, floor 32 px) y contact rows (phone, email, agency psra) a `max(26, round(h*0.017))` (≈ 25-26 px @ 1492, floor 26 px). Floors 32/26 protegen resoluciones bajas. Side_banner conserva sus bounds sin tocar.

### Archivos modificados (Iter 3)

| Archivo | Cambio |
|---|---|
| `modules/rendering/infrastructure/layout/panels.py` | **`bottom_font_bounds(block_name)`** desdobla la rama `is_side_banner_like` en `is_galaxy` (nuevos bounds 32/26 y 26/22) y `is_side_banner` (bounds heredados intactos 26/20 y 24/18). **`bottom_panel_height`** desdobla `is_side_banner_like` en `is_galaxy` (floor `round(h*0.150)`) y `is_side_banner` (floor `round(h*0.113)`). Classic sigue por su rama existente. Side_banner sin cambios funcionales (mismas constantes que iter 2). |
| `tests/unit/rendering/test_layout_composition_galaxy.py` | (a) Añadido `assert overlay.bottom_panel.height >= round(1920 * 0.150)` en `test_build_overlay_layout_galaxy_bottom_panel_reuses_side_banner_card` con comentario `# iter 3: chunky footer + bigger agent text`. (b) Nuevo test `test_build_overlay_layout_galaxy_footer_height_floor_is_chunkier_than_side_banner` compara altura galaxy vs side_banner en la MISMA fixture (galaxy > side_banner). (c) Nuevo test `test_build_overlay_layout_galaxy_agent_text_is_bigger_than_side_banner` compara `font_size` de `agent_name` (galaxy > side_banner) y verifica el floor 26 px de `agent_phone`. (d) Nuevo test `test_build_overlay_layout_galaxy_font_bounds_floor_at_low_resolution` cubre el floor a 540×900 (round(900*0.022)=20 px → floor 26 px por min_font_size). |

### Decisiones (Iter 3)

- **Diferenciación por rama explícita (`is_galaxy` vs `is_side_banner`)** en lugar de un parámetro multiplicador desde fuera de `bottom_font_bounds` — esto sigue la pista que ya marcó iter 2 cuando se desdobló `bottom_panel.y` y `bottom_panel_height` (parcialmente). El precio es 6 líneas extra y un comentario explicativo en la función; el beneficio es que el lector ve sin ambigüedad qué cascade aplica a cada variant. **No introduje helper nuevo** — la lógica vive completa dentro de la closure `bottom_font_bounds`.
- **Floors 32/26 px protegen resoluciones bajas.** El test `test_build_overlay_layout_galaxy_font_bounds_floor_at_low_resolution` ejecuta el cómputo a 540×900 (resolución bottom-shelf) y verifica que `agent_name.font_size >= 26` (min_font_size floor). El `round(900*0.022)=20 px` sería claramente legible-en-el-límite; el floor 26 px de `min_font_size` y 32 px de `max_font_size` asegura legibilidad en cualquier portrait razonable.
- **No tocar `is_side_banner_like`.** El alias se conserva porque otras ramas del `compose_bottom_panel` (por ejemplo `effective_panel_width = round(width * 0.94) if is_side_banner_like else panel_width`, `footer_padding_x`, etc.) sí comparten geometría galaxy↔side_banner. Solo se desdobló donde galaxy y side_banner divergen (typography + altura del footer).
- **`bottom_panel.y` se recalcula automáticamente** porque la fórmula iter 2 (`y = height - bottom_panel_height - max(20, round(h*0.018))`) ya consume `bottom_panel_height` por referencia; sin tocar la rama de anclaje, el footer rides cerca del bottom edge con la nueva altura.

### Verificación (Iter 3)

#### Focal tests verdes

```
$ .venv/bin/python -m pytest tests/unit/rendering/test_layout_composition_galaxy.py \
    tests/unit/rendering/test_frame_composition_accent_colors_galaxy.py \
    tests/unit/rendering/test_filters_galaxy_radius.py \
    tests/integration/rendering/test_galaxy_render.py \
    tests/integration/configuration/test_render_templates_router.py \
    tests/integration/apps_api/test_render_template_assets.py -q -v
...
============================= 37 passed in 12.11s ==============================
```

37 passed (iter 2: 34, +3 en `test_layout_composition_galaxy.py`).

#### Regression side_banner / classic

```
$ .venv/bin/python -m pytest tests/unit/rendering/test_layout_composition_side_banner.py \
    tests/unit/rendering/test_overlay_filter_accent_colors.py \
    tests/unit/rendering/test_layout_panels.py \
    tests/unit/rendering/test_layout_composition.py \
    tests/unit/rendering/test_overlay_filter_classic_snapshot.py -q
38 passed in 0.34s
```

Cero regresiones. Side_banner conserva su `bottom_panel_height` floor 11.3 % y sus bounds 26/20 + 24/18 idénticos a iter 2.

#### Rig visual

```
$ .venv/bin/python -m pytest tests/integration/rendering/test_galaxy_iter.py -m visual_iter -q -s
[galaxy_iter] wrote /opt/projects/4Reels-Backend/progress/galaxy_iter_3.png
.
1 passed in 3.03s
```

`progress/galaxy_iter_3.png` generado (1054×1492 PNG RGB, 1.81 MB).

#### init.sh full suite

```
$ bash ./init.sh
...
3 failed, 1093 passed, 1 deselected, 14 warnings in 586.67s (0:09:46)
[OK]    pytest verde
[OK]    Entorno listo. Puedes empezar a trabajar.
```

**1093 passed** (iter 2: 1090; +3 de los nuevos asserts/tests en `test_layout_composition_galaxy.py`). **3 failed** = baseline histórico (`test_http_surface_contract.py` + 2 en `test_http_transport.py` — no he tocado ese código). **1 deselected** = `test_galaxy_iter.py` (marker `visual_iter`). Exit 0.

### Gap residual contra `example-template-galaxy.png`

Comparación cualitativa de `progress/galaxy_iter_3.png` vs la referencia:

| Elemento | Referencia | iter_3 | Estado |
|---|---|---|---|
| Footer height proporción | ~15-17 % del alto | ~15 % del alto (floor `round(h*0.150)`) | **Match**. |
| Footer bottom edge near frame bottom | ~1.5 % margen | ~1.8 % margen (iter 2, sin tocar) | **Match**. |
| Agent name size / weight | Claramente bolder que el contacto | font_size galaxy 32+ px, agent_phone 26+ px (visualmente diferenciado) | **Match**. |
| Contact rows readable | Sí | Sí (floor 26 px vs side_banner 24 px) | **Match**. |
| Top panel corner radius visible | Sí | Sí (sin cambio iter 2) | **Match**. |
| Top panel anchor (top-left, ~48 % width) | Sí | Sí (sin cambio iter 1) | **Match**. |
| Vertical FOR SALE ribbon arriba-derecha | Sí, dorado | Sí, dorado | **Match**. |
| Agent photo circular | Sí | Sí | **Match**. |
| Círculo central con logo agencia | Sí | NO (out-of-scope v1) | Confirmado fuera de scope. |
| Logo "CENTURY 21" (dos líneas) | Sí, dos líneas | Logo placeholder text "Agency" | Fixture-driven (no scope). |
| Tipografía exacta / pesos exactos | Bold heavy | Bold (mismo cascade font de side_banner) | Aceptable v1 — fixture-driven. |

**Veredicto:** los dos gaps proporcionales identificados por el leader (footer demasiado bajo/delgado + agent text apretado) están cerrados. El frame iter_3 se aproxima razonablemente a la referencia para todos los elementos de scope v1. Diferencias remanentes son explícitamente fixture-driven (logo "CENTURY 21" exacto, foto de la propiedad, exact font weights) o fuera de scope v1 (círculo central). Listo para review.

### Bitácora (Iter 3)

- 2026-05-18 15:30 — Implementer iter 3 arranca. Lee `progress/impl_42.md` + scope del leader.
- 2026-05-18 15:31 — `panels.py`: desdobla `bottom_font_bounds` (galaxy vs side_banner bounds) y `bottom_panel_height` (galaxy floor 0.150 vs side_banner floor 0.113). Sin helper nuevo (lógica completa dentro de la closure).
- 2026-05-18 15:32 — Tests: 1 assert nuevo + 3 tests nuevos en `test_layout_composition_galaxy.py` (chunky footer + bigger agent text + low-res floor).
- 2026-05-18 15:33 — Focal verdes (37 passed). Side_banner / classic regression verde (38 passed).
- 2026-05-18 15:34 — `pytest -m visual_iter` produce `progress/galaxy_iter_3.png` en 3 s. Inspección visual: footer chunky + agent_name claramente más grande que contact rows; proporciones cierran el gap vs referencia.
- 2026-05-18 15:44 — `bash ./init.sh` exit 0: 1093 passed, 3 baseline failed, 1 deselected. Listo para review.

## Cierre

- **Fecha:** 2026-05-18 (post-review APROBADO_CON_OBSERVACIONES, ver `progress/review_42.md`).
- **Comandos ejecutados (orden):**
  1. `md5sum assets/render-templates/side-banner-template.png assets/render-templates/galaxy-template.png progress/galaxy_iter_3.png` → confirmó que galaxy-template.png estaba duplicado de side-banner (md5 `d11db3c7b6f24b894963a4d8886dbed8`) y que el preview iter 3 tenía md5 distinto (`aec282b92ea0a488341e15a734ee1dea`).
  2. `cp progress/galaxy_iter_3.png assets/render-templates/galaxy-template.png` + `md5sum` post-copia.
  3. `.venv/bin/python -m pytest tests/integration/apps_api/test_render_template_assets.py -q -v` → 2 passed (incluye `test_api_serves_galaxy_render_template_preview_asset`).
  4. Edit en `feature_list.json` → línea 1453 `"status": "in_progress"` → `"status": "done"` (solo feature id=42).
  5. `python -c "...status==done, count==39..."` → confirmado.
  6. Extracción de la sección "Feature 42 — galaxy_render_template (Claude leader, en curso)" de `progress/current.md` (líneas 8-41) → apéndice a `progress/history.md` bajo cabecera `## 2026-05-18 — feature 42 galaxy_render_template`.
  7. Edit en `progress/current.md` removiendo el bloque de Feature 42 más su separador `---` trailing. Header `# Sesion actual` + nota plantilla + entradas siguientes intactos.
  8. Re-verificación: `pytest test_render_template_assets.py` verde, `status= done`, `count= 39`, `grep -c "feature 42 galaxy" history.md` = 1.
- **md5 del preview asset galaxy:**
  - Antes (duplicado de side-banner): `d11db3c7b6f24b894963a4d8886dbed8`.
  - Después (iter 3 promovido): `aec282b92ea0a488341e15a734ee1dea`.
  - Side-banner sin cambios: `d11db3c7b6f24b894963a4d8886dbed8` (verificado distinto).
- **Conteo final de features:** 39 (sin variación; sólo cambio de estado de id=42 a `done`).
- **Ubicación en history.md:** entrada nueva al final del archivo bajo cabecera `## 2026-05-18 — feature 42 galaxy_render_template`. El bloque persiste el `# Feature 42 — galaxy_render_template (Claude leader, en curso)` + Plan + Bitacora completos copiados verbatim desde `progress/current.md`.
- **No se tocó:** código de producción, migraciones, otros tests, otras features de `feature_list.json`. No se reinició servicio (no aplica).
