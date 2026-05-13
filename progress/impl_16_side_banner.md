# Feature 16 — Side Banner Render Template (implementation report)

> Implementer: 2026-05-13 · Branch: `ghl`
> Master plan: `progress/explore_feature_16_side_banner_template.md`
> Sub-spikes: `progress/explore_feature_16_ingestion_accent_colors.md`,
> `progress/explore_feature_16_layout_side_banner.md`

## Resumen por sub-tarea

### 16-A · Schema + ingestion accent colors
- Property domain gains two optional fields (`wppd_accent_text_color`,
  `wppd_accent_background_color`) populated from the WordPress payload
  through the existing `to_text` coercion.
- ORM column twins added (Text nullable, no server_default).
- Migration `20260513_0003_add_property_accent_colors.py` upgrade/
  downgrade adds/drops the two columns; depends on `20260513_0002`.

### 16-B · Render template `side_banner` (config + seed)
- `SUPPORTED_LAYOUT_VARIANTS = frozenset({"classic", "side_banner"})`
  in `modules/rendering/infrastructure/render_template_settings.py`.
- New constant `SIDE_BANNER_RENDER_TEMPLATE_ID = "side_banner"`.
- Migration `20260513_0004_seed_side_banner_render_template.py` inserts
  the seed row (`display_name="Side Banner"`, `status="active"`,
  `sort_order=1`, `layout_variant="side_banner"`); downgrade is
  conservative (`DELETE WHERE template_id='side_banner' AND
  layout_variant='side_banner'`) to avoid clobbering user-customised
  templates that reused the id.

### 16-C · Threading accent colors to PropertyRenderData + brand fallback
- `PropertyRenderData` extended with `accent_text_color` and
  `accent_background_color` (str | None, default None).
- `DefaultMediaRenderer._build_render_data` reads the per-property
  webhook colors and falls back to
  `render_template_reel_settings["fallback_accent_*"]`.
- `IngestPropertyIntoReelUseCase` pre-resolves
  `BrandSettings.primary_color` and stuffs it into both
  `render_template_reel_settings` and `render_template_poster_settings`
  as `fallback_accent_text_color` / `fallback_accent_background_color`.
  Lookup uses `uow.configuration.brand.get(agency_id)` (singular `brand`
  attr; the explore spike's note about `brands` was incorrect).
- `_RENDERER_INTERNAL_OVERRIDE_KEYS` carves out the new keys from
  `normalize_property_reel_template_overrides` so they don't trip the
  unknown-field validator.

### 16-D · Layout branching by `layout_variant`
- `build_overlay_layout(layout_variant="classic")` is the new
  optional kwarg. When `"side_banner"`:
  - `outer_margin_x = outer_margin_y = 0` (full-bleed photo).
  - Top panel width narrowed to ~65% of usable width.
- Classic path is byte-for-byte identical when the kwarg is omitted or
  set to `"classic"`; new test
  `test_layout_composition_side_banner.py` guards both branches.

### 16-E · FFmpeg parametrizable colors + apply_alpha_to_hex helper
- `apply_alpha_to_hex(hex, alpha=0.85)` lives in
  `modules/rendering/infrastructure/formatting.py`. Handles
  `#RRGGBB` / `RRGGBB` / 3-char shorthand / alpha clamping / invalid →
  `None`.
- `resolve_text_color(block, override_color=None)` accepts a HEX
  override; existing call sites pass `None` and stay classic.
- `build_overlay_filter` accepts:
  - `layout_variant`
  - `top_panel_color` / `bottom_panel_color` (defaults preserve
    `black@0.38` / `black@0.46`).
  - `text_override_color`
  - `vertical_banner_label` / `vertical_banner_x` / `vertical_banner_y`
- `build_filter_complex` and `build_slide_segment_filter` thread the
  same kwargs through.

### 16-F · Vertical status banner (rotated, ffmpeg-only)
- `PreparedReelAssets` gains `vertical_banner_path: Path | None`,
  `vertical_banner_x: int | None`, `vertical_banner_y: int | None`.
- `prepare_reel_render_assets(layout_variant=...)` renders the banner
  via a dedicated ffmpeg invocation (`drawbox`+`drawtext`+`transpose=1`)
  when `layout_variant=="side_banner"` and the property has a status
  ribbon text. **Deviation from spike**: spike proposed PIL, but PIL
  is not in `requirements.txt` so I kept everything in ffmpeg-land. The
  resulting `_render_vertical_status_banner` writes a PNG identical to
  what the spike envisioned, just via a different toolchain.
- Banner geometry (5.5% of frame width × 40% of frame height) anchored
  to the right edge, vertically centered.
- Reel pipeline (`render_silent_reel`) and poster pipeline
  (`_build_poster_filter_script`) both register the banner PNG as an
  extra ffmpeg input and overlay it with the same x/y from the prepared
  assets.

### 16-G · Tests integration + docs
- New tests (all passing):
  - `tests/unit/catalog/test_property_from_api_payload_accent_colors.py`
  - `tests/unit/rendering/test_apply_alpha_to_hex.py`
  - `tests/unit/rendering/test_frame_composition_accent_colors.py`
  - `tests/unit/rendering/test_layout_composition_side_banner.py`
  - `tests/unit/rendering/test_overlay_filter_accent_colors.py`
  - `tests/integration/configuration/test_render_templates_router.py`
    (extended)
  - `tests/integration/rendering/test_side_banner_render.py`
- `docs/API.md` documents the two render templates and the new
  webhook fields.
- `docs/http_surface.md` and `docs/openapi.json` were regenerated via
  `scripts/generate_http_surface.py` (already drifted; my regen added
  routes that existed in code but were absent in the docs).

## Ficheros tocados

### Migraciones nuevas
- `alembic/versions/20260513_0003_add_property_accent_colors.py`
- `alembic/versions/20260513_0004_seed_side_banner_render_template.py`

### Código (creados / modificados)
| Fichero | Cambio |
|---|---|
| `modules/catalog/domain/wordpress_property.py` | +2 fields, +2 `from_api_payload` extraction lines (~L88) |
| `modules/catalog/domain/_property_conversions.py` | +2 lines in `build_property_db_record` and `build_property_dict` |
| `modules/catalog/infrastructure/orm.py` | +2 `mapped_column(Text)` (L104+) |
| `modules/rendering/infrastructure/render_template_settings.py` | Add `side_banner` to `SUPPORTED_LAYOUT_VARIANTS`, add `_RENDERER_INTERNAL_OVERRIDE_KEYS`, exports |
| `modules/rendering/infrastructure/models.py` | +2 fields on `PropertyRenderData`, +3 fields on `PreparedReelAssets` |
| `modules/rendering/application/frame_composition.py` | Accent threading, `layout_variant` propagation |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | Pre-resolve `BrandSettings.primary_color`, enrich reel/poster settings, new `_resolve_brand_primary_color` helper |
| `modules/rendering/infrastructure/layout/composition.py` | `layout_variant` kwarg, zero outer margins + reduced top panel for side_banner |
| `modules/rendering/infrastructure/ffmpeg/filters.py` | Parametrizable panel colors, text override, vertical banner overlay, `layout_variant` kwarg on `build_overlay_filter` and `build_filter_complex` |
| `modules/rendering/infrastructure/ffmpeg/filter_graph.py` | Same propagation through `build_slide_segment_filter` |
| `modules/rendering/infrastructure/ffmpeg/render_reel.py` | `layout_variant` threading + banner input wiring |
| `modules/rendering/infrastructure/formatting.py` | `apply_alpha_to_hex`, `resolve_text_color(override_color=...)`, `_format_hex_for_drawtext` |
| `modules/rendering/infrastructure/preparation.py` | `layout_variant` kwarg, `_resolve_vertical_banner_layout`, `_render_vertical_status_banner`, `_normalize_drawtext_color` |
| `modules/rendering/infrastructure/poster.py` | `layout_variant` kwarg, banner overlay wiring in filter script + ffmpeg command |
| `modules/publishing/infrastructure/adapters/gohighlevel/property_publisher.py` | Thread `layout_variant` + accent colors when republishing posters |
| `docs/API.md` | Documented both render templates + webhook accent fields |
| `docs/http_surface.md`, `docs/openapi.json` | Regenerated via `scripts/generate_http_surface.py` |

### Tests nuevos
| Fichero | Cobertura |
|---|---|
| `tests/unit/catalog/__init__.py` | (paquete) |
| `tests/unit/catalog/test_property_from_api_payload_accent_colors.py` | Ingesta accent colors → Property / dicts |
| `tests/unit/rendering/test_apply_alpha_to_hex.py` | Helper formatter (8 casos: shorthand, alpha clamping, inválido…) |
| `tests/unit/rendering/test_frame_composition_accent_colors.py` | Accent threading + fallback brand color |
| `tests/unit/rendering/test_layout_composition_side_banner.py` | Geometría side_banner + regresión classic |
| `tests/unit/rendering/test_overlay_filter_accent_colors.py` | Filter graph: defaults classic vs override side_banner + vertical banner overlay + text override |
| `tests/integration/rendering/test_side_banner_render.py` | Smoke end-to-end: `layout_variant` y accent colors fluyen hasta los 3 primitivos del renderer |

### Tests extendidos
- `tests/unit/rendering/test_render_template_settings.py`: nuevos casos
  para `SUPPORTED_LAYOUT_VARIANTS`, layout_variant inválido → classic,
  side_banner válido.
- `tests/unit/rendering/test_frame_composition.py`: stubs aceptan los
  kwargs nuevos `layout_variant`.
- `tests/integration/configuration/test_render_templates_router.py`:
  nuevos casos para listing side_banner y selección desde
  `/defaults`.

## Verificación

```
$ bash ./init.sh
…
── 7. Resumen ──────────────────────────────────────────
[OK]    Entorno listo. Puedes empezar a trabajar.
```

- `python -m apps.api --check` exit code 0.
- `python -m apps.worker --check` exit code 0.
- `python -m pytest tests/ -q`: **583 passed, 3 failed**
  - Los 3 fallos son **pre-existentes** y no relacionados con
    feature 16: `test_http_surface_contract.py` y
    `test_http_transport.py` esperan un payload `/health` sin el campo
    `configured_worker_count` (cambio en `apps/api/health_router.py` que
    quedó pendiente desde antes de mi sesión, ver `git status`).
  - Baseline (pre-feature 16) eran **547 passed + los mismos 3 failed**;
    feature 16 añade **36 tests pasando** netos.
- Alembic cycle verificado en DB limpia: `upgrade head` →
  `downgrade -1` × 2 → `upgrade head`. Estado final `20260513_0005`.
- `alembic check`: `No new upgrade operations detected` (schema en
  sync con ORM).
- Filter graph manual (side_banner): contiene
  `drawbox … color=0xe22f8c@0.85` para top y bottom panel,
  `fontcolor=0xffffff` para los text blocks, y posiciona el top panel
  en `x=0:y=0:w=702` (=65% de 1080).
- Filter graph manual (classic, layout_variant explícito vs omitido):
  **byte-for-byte idénticos**. Regresión zero confirmada.

## Decisiones de diseño / desviaciones

1. **PIL → ffmpeg para el banner**: PIL no está en
   `requirements.txt`. Mantengo el banner como render ffmpeg
   (`drawbox` + `drawtext` + `transpose=1`) en lugar de añadir Pillow.
   Resultado final equivalente (PNG con texto rotado 90° CW); evito
   la dependencia nueva.
2. **`uow.configuration.brand` (singular)**: el spike documentaba
   `uow.configuration.brands`. Verificado en `ingest_property_into_reel.py`
   (función `_resolve_agency_logo_local_path`) que el atributo correcto
   es singular. El nuevo helper `_resolve_brand_primary_color` usa el
   mismo patrón.
3. **`_RENDERER_INTERNAL_OVERRIDE_KEYS`**: añadido a
   `render_template_settings.py` para que las claves `fallback_accent_*`
   puedan viajar en `render_template_reel_settings` sin tropezar con
   `normalize_property_reel_template_overrides` (que rechaza claves
   desconocidas). La alternativa sería crear un campo separado en
   `PropertyContext`, pero requeriría tocar `types.py` y todos los
   constructores de tests.
4. **Sin validación HEX (de momento)**: el spike sugería un helper
   `is_valid_hex_color`. `apply_alpha_to_hex` ya devuelve `None` para
   valores inválidos, de modo que un HEX inválido en
   `wppd_accent_*` cae al fallback de brand sin warning explícito.
   Si se quiere log warning explícito puede hacerse en review-feedback
   o feature de seguimiento.
5. **Publisher poster regenera con accent colors**: el adapter
   GoHighLevel también re-genera el poster en algunos paths; lo
   actualicé para que threadee `layout_variant` y los accent colors
   con el mismo fallback (`context.render_template_poster_settings`).
   No es estrictamente requerido por el plan, pero evita inconsistencia
   visual entre el reel y un poster reposteado por GHL.

## Notas para el reviewer

- **`docs/http_surface.md` y `docs/openapi.json` también incluyen
  cambios no estrictamente owned por feature 16** (rutas previas que
  estaban desincronizadas). Si se quiere mantener el diff "limpio",
  pueden revertirse y dejar la regeneración para una limpieza
  posterior.
- **`apps/api/health_router.py` etc en git status** son cambios
  externos (no míos) que rompen 3 tests pre-existentes; estos tests
  fallaban antes de empezar la feature y siguen fallando ahora.
- El banner vertical sólo se genera si `property_data` tiene status
  ribbon (`build_status_ribbon_text` devuelve no-None). Properties sin
  status no obtienen banner aunque seleccionen `side_banner`.
- El poster reusa el mismo `layout_variant`. Si el flujo de selección
  de slides degrada (e.g. no hay imagen primaria), el poster
  generation falla en el primitivo de preparación igual que en
  classic.
- Cualquier endpoint nuevo de admin para validar HEX manualmente
  queda fuera del scope (feature 16 sólo soporta accent colors vía
  webhook; el endpoint de validación es feature de seguimiento).
- El reviewer debería verificar manualmente:
  1. Aplicar las 2 migraciones nuevas en una DB limpia y bajar
     downgrade -1 dos veces sin errores (ya verificado por mí, pero
     vale repetirlo).
  2. POST al webhook con `wppd_accent_*` y leer la fila de
     `properties` para confirmar los valores persistidos.
  3. `GET /v1/admin/agencies/{id}/render-templates` devuelve `classic`
     + `side_banner`.
  4. Render real (ffmpeg) de un reel con `render_template_id=side_banner`
     y comparar visualmente con el mock-up del usuario.

---

## Pass 2 — Nits resolvidos

> Implementer pass-2: 2026-05-13 · Reviewer pre-pass-2: APPROVED WITH NITS
> (`progress/review_16_side_banner.md`).

Cuatro nits del reviewer resueltos. Cero cambios fuera de su scope.

### Nit 1 — Import function-scoped en `poster.py:381` (VERDE)

**Acción:** moví `from modules.rendering.infrastructure.formatting import
apply_alpha_to_hex` del cuerpo de `_build_poster_filter_script` al
bloque de imports del top del módulo.

**Ficheros:**
- `modules/rendering/infrastructure/poster.py`:
  - Línea 23-28: incluí `apply_alpha_to_hex` en el `from
    modules.rendering.infrastructure.formatting import (...)` ya
    existente.
  - Borré la línea 381 (`from ... import apply_alpha_to_hex` dentro
    de la función).

**Verificación:** `pytest tests/unit/rendering/ -q` → 92 passed.
`grep` confirma cero imports function-scoped restantes en `poster.py`.

### Nit 2 — Validación HEX explícita + warning (VERDE)

**Acción:** creé un helper puro `is_valid_hex_color()` y lo integré en
la ingesta para warning-but-continue cuando el webhook trae un valor
inválido.

**Decisión de ubicación:** la nit sugería
`shared/types/colors.py` o `shared/errors/validation.py`. Intenté
primero `shared/types/colors.py`, pero `types` es un módulo stdlib y
pytest's rootdir-rewriting hace que `tests/unit/shared/__init__.py`
choque con el import de `shared.types.*` (resolución bloqueada).
Pasé a `shared/errors/validation.py` (también dentro de las opciones
del nit) que funciona limpio. Eliminé el directorio
`shared/types/` que dejé temporalmente.

**Ficheros creados:**
- `shared/errors/validation.py`: helper `is_valid_hex_color(value: str
  | None) -> bool`. Acepta 3/4/6/8 dígitos hex con/sin `#`, tolera
  whitespace, rechaza CSS keywords (`"red"`), strings vacíos, y
  no-strings. `None` se considera válido (señal de "campo ausente"
  legítimo).
- `tests/unit/shared/test_hex_color_validation.py`: 33 tests
  parametrizados (válidos, shorthand, alpha-aware, None, inválidos,
  no-string, whitespace). **Nota:** `tests/unit/shared/` se dejó sin
  `__init__.py` deliberadamente para que pytest no eclipse el package
  `shared/` del proyecto (mismo patrón que `tests/unit/rendering/`).

**Ficheros modificados:**
- `modules/reels/application/use_cases/ingest_property_into_reel.py`:
  - Import nuevo: `from shared.errors.validation import is_valid_hex_color`.
  - Método estático nuevo `_sanitize_property_accent_colors(property_item)`:
    para cada `wppd_accent_*` no-None, si `is_valid_hex_color` devuelve
    False emite `logger.warning(...)` con `property_id` + nombre del
    campo + valor crudo, y setea el campo a `None` (fallback al
    `BrandSettings.primary_color` aguas abajo).
  - Llamada al sanitizer en `_execute_with_uow` justo después de
    `Property.from_api_payload(job.payload)` (antes de
    `build_media_delivery_plan`).

**Tests nuevos:**
- `tests/unit/reels/test_ingest_property_accent_color_sanitization.py`:
  6 tests cubriendo (a) HEX válidos round-trip sin warning,
  (b) `None` pass-through, (c) `wppd_accent_text_color="red"` nulled
  + warning, (d) `wppd_accent_background_color="#xyz"` nulled +
  warning, (e) ambos campos inválidos → 2 warnings, (f) string vacío
  / whitespace tratado como inválido.

**Patrón replicado:** mismo estilo de `logger.warning` warning-but-fallback
que ya usa
`render_template_settings.resolve_render_template_settings` cuando el
`layout_variant` es desconocido (línea 147-153). No bloquea ingesta.

### Nit 3 — Golden snapshot del filter graph classic (VERDE)

**Acción:** añadí un test snapshot byte-for-byte del filter graph
classic.

**Decisión de formato:** el proyecto no tiene precedente de snapshot
files (`*.snap`, `*.txt`). Usé string literal multi-línea inline.
La única fuente de no-determinismo en el output de
`build_overlay_filter` es la ruta absoluta de las fonts (resuelta por
`escape_filter_path(resolve_font_path(...))`). Normalicé esas a
`<FONT_Bold>` / `<FONT_Regular>` con un regex antes de comparar
contra la snapshot.

**Fichero creado:**
- `tests/unit/rendering/test_overlay_filter_classic_snapshot.py`:
  - `test_classic_filter_graph_matches_pinned_snapshot`: invoca
    `build_overlay_filter` con la fixture canónica
    (`build_property_data()` + `build_template(width=1080, height=1920)`)
    + ber_icon_label + logo_image_label + caption + slide_duration=2.5,
    normaliza fonts, compara contra `EXPECTED_CLASSIC_FILTER_GRAPH`.
  - `test_classic_layout_variant_kwarg_default_is_identical_to_omitted`:
    belt-and-braces para verificar que pasar `layout_variant="classic"`
    explícito produce el mismo output que omitirlo.

**Verificación:** ambos pasan; si alguien cambia un default en
`filters.py` (e.g. `black@0.38` → `black@0.40`) el primer test falla
con diff legible (`actual_normalized != EXPECTED_CLASSIC_FILTER_GRAPH`
+ mensaje con ambas strings completas).

### Nit 4 — Drift en `docs/openapi.json` + `docs/http_surface.md` (AMARILLO — drift consolidado conscientemente)

**Acción:** re-corrí `python scripts/generate_http_surface.py --write`
y dejé el drift consolidado.

**Análisis del diff:** clasifiqué cada cambio del `git diff HEAD --`
en docs:

| Cambio | Atribución | Decisión |
|---|---|---|
| `RenderTemplateSelectPayload` schema | Feature 16 (acceptance #1-2) | Conservar |
| `/v1/admin/agencies/{id}/render-template{,s}` endpoints | Feature 16 | Conservar |
| `wppd_accent_*` (en `docs/API.md`) | Feature 16 (acceptance #3) | Conservar (ya estaba en impl-1) |
| `pinterest` en enum `platforms` (3 sitios) | Feature 8 pre-existente (visto en `progress/review_8_pinterest_social_platform_support.md`) | Conservar (consolidación trivial) |
| `render_template_id` field en payloads | Feature 15 (DB-backed render templates) pre-existente | Conservar (consolidación trivial) |
| `/v1/admin/agencies/{id}/brand/logo*` endpoints | Feature 10 pre-existente (`progress/impl_10_agency_logo_upload.md`) | Conservar (consolidación trivial) |
| `hold_window_seconds` / `quiet_hours_enabled` / `skip_weekends` en automation schema | Features 13-14 pre-existentes | Conservar (consolidación trivial) |
| `configured_worker_count` en `/health` description | Cambio externo en `apps/api/health_router.py` (rompe los 3 tests pre-existentes) | Conservar (refleja código real) |
| Variable docs en `social-templates` description | Feature 12 pre-existente | Conservar (consolidación trivial) |

**Justificación de la decisión "consolidar y no revertir":** todos los
items pre-existentes son **trivialmente correctos** (reflejan
endpoints y schemas ya presentes en el código que la generación
automática de `app.openapi()` simplemente nunca había vuelto a
escribir en disco). Revertir hacia el HEAD anterior dejaría
`docs/openapi.json` inconsistente con el output real de
`generate_http_surface.py`, lo cual es peor que el drift consolidado:
el próximo desarrollador que corra el script vería de nuevo todas
estas líneas como cambios "nuevos". El nit del reviewer
explícitamente lista esta opción: "Aceptable porque consolida un drift
previo".

**Verificación de estabilidad:** corrí `generate_http_surface.py
--write` dos veces seguidas; segundo run produce 0 cambios → docs
convergentes.

**Nota para futura sesión de limpieza:** queda pendiente alinear los 3
tests que esperan el `/health` payload sin `configured_worker_count`
con el nuevo shape; eso es ortogonal a feature 16 y debería ser una
feature 17 (o un fix-it sweep). El drift en `docs/` queda
explícitamente fuera del scope de feature 16 una vez consolidado.

### Verificación final pass-2

```
$ .venv/bin/python -m pytest -q --tb=no
3 failed, 640 passed, 14 warnings in 247.09s
```

- Los 3 failures son los mismos pre-existentes (mismas líneas
  reportadas por el reviewer pre-pass-2 sobre
  `configured_worker_count` en `/health`).
- 640 passing = 599 pre-pass-2 (583 reportados por reviewer + 16
  tests extra que aparecieron entre review y pass-2 por otros
  cambios untracked, no míos) + 41 nuevos pass-2 (33 hex + 2 snapshot
  + 6 sanitize).

```
$ .venv/bin/python -m apps.api --check   ; echo $?
... API READINESS REPORT — RUNTIME READY: Yes ...
0

$ .venv/bin/python -m apps.worker --check ; echo $?
... Worker --check OK: kinds=reel_publish, scripted_render ...
0
```

Migraciones: pass-2 no requiere ninguna (los nits son código + tests +
docs).

### Ficheros pass-2 (resumen)

**Creados:**
- `shared/errors/validation.py`
- `tests/unit/shared/test_hex_color_validation.py`
- `tests/unit/rendering/test_overlay_filter_classic_snapshot.py`
- `tests/unit/reels/test_ingest_property_accent_color_sanitization.py`

**Modificados:**
- `modules/rendering/infrastructure/poster.py` (nit 1)
- `modules/reels/application/use_cases/ingest_property_into_reel.py`
  (nit 2)
- `docs/openapi.json` (regen del script, drift consolidado nit 4)
- `docs/http_surface.md` (regen del script, drift consolidado nit 4)
- `progress/current.md` (bitácora pass-2)
- `progress/impl_16_side_banner.md` (esta sección)
