# Review — feature 16 (`side_banner_render_template`)

**Veredicto:** APPROVED WITH NITS

> Reviewer: 2026-05-13 · Branch: `ghl`
> Implementer report: `progress/impl_16_side_banner.md`
> Master plan: `progress/explore_feature_16_side_banner_template.md`

## Resumen ejecutivo

La feature 16 esta correctamente implementada. Los 9 acceptance criteria
estan cubiertos (8 verdes, 1 amarillo por ausencia de un snapshot
byte-for-byte explicito del filter graph classic). La regresion classic
esta cubierta a nivel de geometria (`test_layout_composition.py` +
`test_layout_composition_side_banner.py::test_build_overlay_layout_classic_outer_margins_preserved`)
y a nivel de filter graph defaults (`test_overlay_filter_accent_colors.py::test_overlay_filter_defaults_preserve_classic_panel_colors`),
suficiente en la practica.

Las 3 desviaciones documentadas por el implementer son correctas y
estan justificadas. Las 2 migraciones nuevas (0003 + 0004) tienen
downgrade que invierte limpiamente el upgrade y se verificaron en DB
viva.

## Acceptance criteria (feature_list.json id=16)

| # | Criterio | Estado | Evidencia |
|---|----------|--------|-----------|
| 1 | GET `/v1/admin/agencies/{id}/render-templates` lista `classic` + `side_banner` (sort_order=1, status=active) | VERDE | `tests/integration/configuration/test_render_templates_router.py::test_render_templates_list_includes_side_banner` PASSED; el test verifica explicitamente `display_name="Side Banner"`, `status="active"`, `sort_order=1`, `layout_variant="side_banner"`. |
| 2 | PUT `/defaults` con `render_template_id="side_banner"` round-trip persiste | VERDE | `test_render_template_select_persists_side_banner_on_defaults` PASSED; persiste en `agency_reel_defaults`. |
| 3 | Webhook con `wppd_accent_*` ingesta y persiste en `properties.wppd_accent_*` | VERDE | `tests/unit/catalog/test_property_from_api_payload_accent_colors.py` (5 casos, todos PASSED) cubre extraccion, null defaults, blank-string-to-none, db_record, dict. Migracion 0003 anade las columnas Text nullable. |
| 4 | Filter graph con `drawbox color=0x...@0.85` + overlay banner vertical cuando layout_variant=side_banner | VERDE | `test_overlay_filter_accent_colors.py::test_overlay_filter_supports_top_and_bottom_panel_color_overrides` valida `color=0xe22f8c@0.85`; `test_overlay_filter_includes_vertical_banner_overlay` valida `[vertical_banner]overlay=x=900:y=200`. |
| 5 | Property sin colores cae a `BrandSettings.primary_color` | VERDE | `test_frame_composition_accent_colors.py::test_build_render_data_falls_back_to_brand_primary_when_missing` PASSED. El fallback se inyecta en `ingest_property_into_reel.py:_resolve_brand_primary_color` (lineas 400-430). |
| 6 | Classic byte-for-byte identico al baseline (regresion cero) | AMARILLO | Cubierto en dos puntos: (a) `test_layout_composition_side_banner.py::test_build_overlay_layout_classic_outer_margins_preserved` verifica que `layout_variant="classic"` y default-arg producen mismos `top_panel.{x,y,width}`; (b) `test_overlay_filter_accent_colors.py::test_overlay_filter_defaults_preserve_classic_panel_colors` confirma que `color=black@0.38` y `color=black@0.46` siguen emitiendose con defaults. NO existe un golden-file snapshot completo del filter graph classic. Riesgo bajo: el codigo del filters.py se default-paths a los mismos string literals. |
| 7 | Alembic upgrade head + downgrade -1 verdes para 0003 y 0004 | VERDE | Verificado en vivo por el reviewer: `alembic downgrade 20260513_0002` (baja 0005, 0004, 0003) y `alembic upgrade head` ambos exit 0; `alembic check` reporta "No new upgrade operations detected". |
| 8 | `pytest -q` verde (baseline 547 → 583, +36 nuevos) | VERDE | `pytest -q --tb=no`: 583 passed, 3 failed. Los 3 failed son los pre-existentes ya conocidos (`test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes`, `test_http_transport.py::test_health_endpoints_include_paused_dispatcher_state`, `test_health_endpoints_return_minimal_payloads`) que esperan `/health` SIN `configured_worker_count`. Verificado mostrando los AssertionError: el dict actual incluye `configured_worker_count` que es un cambio externo en `apps/api/health_router.py` (modificado en git pre-existente, NO por feature 16). `pytest --collect-only` reporta 586 total, baseline era 550, delta = +36 exactamente. |
| 9 | `python -m apps.api --check` y `python -m apps.worker --check` exit 0 | VERDE | Ambos exit code 0 verificados por el reviewer. |

## Calidad de codigo y reglas

| Regla | Estado | Evidencia |
|-------|--------|-----------|
| Inter-module imports (no `<otro>.application/.infrastructure` desde otro modulo, salvo via domain) | VERDE | Los unicos cross-module imports en archivos feature 16 son: `reels/application/use_cases/ingest_property_into_reel.py` importa `modules.rendering.infrastructure.render_template_settings` (pre-existente, no nuevo) y `modules.catalog.domain.wordpress_property` (domain, permitido). El cross-import `reels/application -> rendering/infrastructure` ya existia antes de la feature; no se introducen nuevos. |
| `domain/` libre de SQLAlchemy | VERDE | `modules/catalog/domain/wordpress_property.py` y `_property_conversions.py` solo usan dataclasses + typing. |
| `application/` libre de Pydantic | VERDE | `ingest_property_into_reel.py` no introduce Pydantic. |
| Tests no eliminados / silenciados | VERDE | Diff de count exacto: 547 baseline + 36 = 583 passed. Total collected 586 (= 583 + 3 fallos pre-existentes). No hay tests eliminados. |
| Migrations downgrade-safe | VERDE | 0003 upgrade: `add_column wppd_accent_*` (2x). Downgrade: `drop_column wppd_accent_*` (2x, orden invertido). 0004 upgrade: `INSERT ... ON CONFLICT DO NOTHING` con template_id='side_banner'. Downgrade: `DELETE WHERE template_id='side_banner' AND layout_variant='side_banner'` (preserva customizaciones). Cycle verificado en vivo. |
| Logging y errores | VERDE | `apply_alpha_to_hex` returns None silenciosamente para HEX invalidos. `ingest_property_into_reel._resolve_brand_primary_color` es best-effort (devuelve None si UoW/brand_repo/brand faltan). No hay `print()` debug ni TODOs. |
| Docs actualizados | VERDE (con nit) | `docs/API.md` documenta `side_banner` (lines 63-71, 132+) y los dos campos webhook. `docs/http_surface.md` y `docs/openapi.json` fueron regenerados pero el implementer advierte que incluyen drift no-owned por feature 16; aceptable porque el GET `/render-templates` ya emite el contenido nuevo dinamicamente sin requerir cambios de schema HTTP estatico. |
| `progress/current.md` coherente con impl | VERDE | Las 7 sub-tareas 16-A..16-G marcadas como "completada"; el informe `impl_16_side_banner.md` documenta cada una con ficheros tocados. |

## Verificacion de las 3 desviaciones documentadas

### Desviacion 1: PIL → ffmpeg para banner vertical

**Verificado**: `requirements.txt` y `requirements-dev.txt` NO incluyen PIL/Pillow.
`grep -rn "from PIL\|import PIL"` en `modules/` y `shared/` devuelve 0 hits.
La solucion ffmpeg-pura (`drawbox+drawtext+transpose=1`) en
`preparation.py:_render_vertical_status_banner` (lineas 254-347) es
correcta y produce un PNG con texto rotado 90 grados CW. La eleccion
evita anadir una dependencia nueva y mantiene la cadena de render
homogenea.

### Desviacion 2: `uow.configuration.brand` singular (no `brands`)

**Verificado**: `shared/db/uow.py:96` define `ConfigurationNamespace.brand:
BrandSettingsRepository` (singular) y line 158 lo instancia como
`brand=BrandSettingsRepository(self.session)`. El spike A
(`explore_feature_16_ingestion_accent_colors.md` linea 214) decia
`brands` (plural), lo cual era incorrecto. El implementer uso
correctamente `getattr(configuration, "brand", None)` en
`ingest_property_into_reel.py:423`.

### Desviacion 3: `_RENDERER_INTERNAL_OVERRIDE_KEYS` whitelist

**Verificado en `render_template_settings.py:31-36`**: La whitelist
contiene SOLO `fallback_accent_text_color` y `fallback_accent_background_color`.
El test `test_render_template_settings.py::test_normalize_property_reel_template_overrides_rejects_unknown_keys`
(linea 34-38) confirma que claves desconocidas (e.g. `"unsupported"`)
siguen lanzando `ValidationError` con codigo
`RENDER_TEMPLATE_SETTING_UNSUPPORTED`. La whitelist hace `continue`
(salta validacion silenciosamente) solo para los dos keys carved-out,
sin propagarlos al `PropertyReelTemplate` dataclass (estos se leen
directamente desde `context.render_template_reel_settings` en
`frame_composition._build_render_data`, no via
`build_property_reel_template_from_overrides`).

## Nits (sugerencias, no blockers)

1. **Import function-scoped en `poster.py:381`**: `from modules.rendering.infrastructure.formatting import apply_alpha_to_hex` esta dentro del cuerpo de `_build_poster_filter_script` en lugar de al top del modulo. El modulo ya importa `formatting` (lineas 23-27); seria mas limpio incluir `apply_alpha_to_hex` en ese bloque de imports del top. Sin impacto funcional.
2. **Validacion HEX explicita (deferred)**: El spike sugirio un helper `is_valid_hex_color()`. El implementer no lo anadio, pero `apply_alpha_to_hex` y `_normalize_drawtext_color` ambos retornan `None`/fallback ante HEX invalido — la sanitizacion es implicita. Mejora futura: log warning explicito cuando el webhook envia un valor invalido (`"red"`, `"#xyz"`) para facilitar debugging.
3. **Snapshot byte-for-byte explicito del filter graph classic**: La regresion zero esta cubierta a nivel de defaults y geometria, pero no hay un golden-file snapshot completo del filter graph classic. Riesgo bajo (el codigo se default-paths a las mismas strings), pero un snapshot test reforzaria la garantia. Sugerencia para futuro.
4. **`docs/openapi.json` / `docs/http_surface.md` regen drift**: El implementer noto que la regeneracion incluyo cambios no owned por feature 16. Aceptable porque consolida un drift previo; alternativamente podria revertirse y dejar la regen para una pasada de limpieza separada.

## Siguiente paso para el leader

Marcar la feature 16 como `status: "done"` en `feature_list.json`. Las
nits son enhancements para features futuras, no bloqueos.

---

## Pass 2 — Verificacion de nits

> Reviewer pass-2: 2026-05-13 · Implementer pass-2 report:
> `progress/impl_16_side_banner.md` seccion "Pass 2 — Nits resolvidos".

Verifique los 4 nits originales contra la implementacion pass-2. Resumen
en una linea: **APPROVED** — los 3 nits con criterio objetivo (1, 2, 3)
estan VERDES; el nit 4 (drift en docs) queda AMARILLO documentado tal
como permitia la guia original.

### Nit 1 — Import function-scoped en `poster.py:381` (VERDE)

- **Evidencia**: `grep -n "apply_alpha_to_hex" modules/rendering/infrastructure/poster.py` →
  match en linea 24 (dentro del bloque `from modules.rendering.infrastructure.formatting import (...)` lineas 23-28) y un solo uso en linea 383 (cuerpo de `_build_poster_filter_script`).
- **Comprobacion adicional**: `grep -n "^\s\+from\|^\s\+import "` sobre el
  fichero entero → 0 matches, no quedan imports function-scoped.
- **Resultado**: el import esta correctamente al top, junto a los otros
  imports de `formatting`. Sin impacto funcional, mejora limpieza.

### Nit 2 — Validacion HEX explicita + warning (VERDE)

- **Helper**: `shared/errors/validation.py:21-40` define
  `is_valid_hex_color(value: str | None) -> bool`. Acepta `None` como
  valido (early return en linea 36-37), rechaza no-string (38-39), regex
  `^#?(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$` cubre 3/4/6/8
  digitos con o sin `#`. Tolera whitespace via `.strip()`. CSS keywords
  como `"red"` correctamente rechazados.
- **Tests unitarios**: `tests/unit/shared/test_hex_color_validation.py`,
  33 tests parametrizados (collect-only confirmado: 33 items). Cubren
  6-digit, shorthand 3-digit, alpha-aware 4/8-digit, `None`, invalidos
  (`""`, `"red"`, `"#xyz"`, `"rgb(...)"`, `"0xffffff"`), no-string
  (`int`, `float`, `list`, `dict`, `bytes`), y whitespace.
- **Integracion**: `modules/reels/application/use_cases/ingest_property_into_reel.py:75`
  importa el helper; metodo estatico `_sanitize_property_accent_colors`
  (lineas 411-442) emite `logger.warning(...)` con `property_id` + nombre
  del campo + valor crudo, luego setea el campo a `None`. La llamada se
  hace en linea 140 — JUSTO DESPUES de `Property.from_api_payload` y
  ANTES de `build_media_delivery_plan` (linea 141), de modo que cualquier
  consumidor downstream (`_resolve_brand_primary_color`, `frame_composition._build_render_data`)
  lee el valor sanitizado.
- **Tests integracion**: `tests/unit/reels/test_ingest_property_accent_color_sanitization.py`
  con 6 tests (round-trip validos, `None` pass-through, `"red"` nulled +
  warning, `"#xyz"` nulled + warning, ambos invalidos → 2 warnings,
  string vacio/whitespace invalido).
- **Run combinado**: `.venv/bin/python -m pytest tests/unit/shared/test_hex_color_validation.py tests/unit/reels/test_ingest_property_accent_color_sanitization.py -v` → 39 passed in 0.96s.
- **Patron**: `logger.warning` (no `print`), warning-but-continue (no
  bloqueo del render), fallback implicito a `BrandSettings.primary_color`
  via `_resolve_brand_primary_color`.

### Nit 3 — Golden snapshot del filter graph classic (VERDE)

- **Fichero**: `tests/unit/rendering/test_overlay_filter_classic_snapshot.py`,
  2 tests.
- **Determinismo**:
  - Fixture canonica de `tests/unit/rendering/conftest.py` (`build_property_data` +
    `build_template(width=1080, height=1920)`).
  - Unico token no-deterministico es la ruta absoluta del font;
    normalizada via regex `_FONT_PATH_PATTERN` a `<FONT_Bold>` /
    `<FONT_Regular>` antes de comparar (lineas 27-29, 67-69).
  - Sin timestamps, sin paths absolutos del sistema (mas alla del font
    normalizado), sin valores aleatorios.
- **Coverage del filter graph**:
  - Top panel (`drawbox=x=43:y=58:w=994:h=374:color=black@0.38:t=fill`),
  - Bottom panel (`drawbox=x=43:y=1584:w=994:h=278:color=black@0.46:t=fill`),
  - Text blocks (status ribbon, price, address, beds/baths, agent info,
    caption con border/shadow),
  - Overlay chain completo (ber_icon, agent_panel_image, logo_image, null
    → vout).
- **Sensibilidad a cambios**: si alguien modifica literal `"black@0.38"`
  → `"black@0.40"` en `filters.py`, el primer test FALLA con un
  `AssertionError` cuyo mensaje incluye el `EXPECTED_CLASSIC_FILTER_GRAPH`
  completo y el `actual_normalized` completo (lineas 82-85), diff
  legible en consola pytest.
- **Belt-and-braces**: segundo test verifica que pasar
  `layout_variant="classic"` explicito produce el mismo output que
  omitir el kwarg (regression guard adicional).
- **Run**: `.venv/bin/python -m pytest tests/unit/rendering/test_overlay_filter_classic_snapshot.py -v` → 2 passed in 0.21s.

### Nit 4 — Drift en `docs/openapi.json` + `docs/http_surface.md` (AMARILLO documentado, ACEPTABLE)

- **Diff vs HEAD** (no vs main, porque ambos ficheros ya existian en
  HEAD): `git diff HEAD -- docs/http_surface.md` → +4 routes (2 de
  feature 16/15: `render-template{,s}`; 2 de feature 10: `brand/logo{,/file/{filename}}`). `git diff HEAD -- docs/openapi.json` → 405 lineas con paths/schemas correspondientes mas drift trivial en payloads (`pinterest` en enum, `render_template_id` field, `hold_window_seconds`/`quiet_hours_enabled`/`skip_weekends` de features 13-14, `configured_worker_count` en `/health`).
- **Atribucion**: la tabla de clasificacion en `progress/impl_16_side_banner.md`
  lineas 360-369 es honesta y verificable. Cada item es trivialmente
  correcto: refleja codigo existente que el script de generacion
  `scripts/generate_http_surface.py` simplemente no habia vuelto a
  escribir.
- **Estabilidad**: el implementer reporta que dos runs consecutivos del
  script convergen (segundo run = 0 cambios). Bueno.
- **Decision**: (a) consolidacion es trivialmente correcta y mejora la
  precision de `docs/openapi.json` frente al codigo real. Revertir
  dejaria el siguiente desarrollador con un diff mas grande. La nit 4
  original explicitamente permitia "Aceptable porque consolida un drift
  previo". APROBADO como deuda menor; ningun item del drift es atribuible
  a una feature futura ni introduce informacion incorrecta. No es
  BLOCKER.
- **Deuda pendiente** (no para feature 16): alinear los 3 tests
  pre-existentes que esperan `/health` sin `configured_worker_count`
  (fix-it sweep separado o feature 17).

### Counts pytest finales

- `.venv/bin/python -m pytest -q --tb=no` → **3 failed, 640 passed, 14
  warnings in 246.89s**.
- `.venv/bin/python -m pytest --collect-only -q` → **643 tests collected**
  (= 640 passed + 3 failed pre-existentes).
- Delta vs pass-1 (583 passed → 640 passed): **+57**.
  - 41 tests nuevos pass-2 (verificado via `pytest --collect-only` sobre
    los 3 ficheros nuevos: 33 hex + 2 snapshot + 6 sanitize = 41).
  - 16 tests delta restante: corresponden a ficheros untracked
    (`tests/integration/configuration/test_brand_logo_router.py`,
    `tests/unit/configuration/test_compute_next_publish_slot.py`,
    `tests/unit/publishing/test_*`, etc.) introducidos entre pass-1 y
    pass-2 por cambios externos no atribuibles a feature 16. El
    implementer documenta esto en su informe. Verificado que ninguno es
    una regresion encubierta (todos verdes, no hay test que pase de
    rojo a verde de forma sospechosa).
- Coincide exactamente con lo reportado por el implementer.

### Readiness

- `.venv/bin/python -m apps.api --check` → EXIT 0 (API READINESS REPORT
  — RUNTIME READY).
- `.venv/bin/python -m apps.worker --check` → EXIT 0 ("Worker --check
  OK: kinds=reel_publish, scripted_render worker_count=1 lease=900s
  poll=0.50s").

### Regresiones

- **Cero regresiones detectadas**. Los 3 tests rojos son IDENTICOS a los
  reportados en pass-1 (`test_http_surface_contract::test_frontend_api_requests_target_existing_backend_routes`,
  `test_http_transport::test_health_endpoints_include_paused_dispatcher_state`,
  `test_http_transport::test_health_endpoints_return_minimal_payloads`).
  Pre-existentes, no atribuibles a feature 16 ni a pass-2.
- Suite unit completa (`tests/unit/`) → verde.
- Suite integracion completa (`tests/integration/`) → verde salvo los 3
  pre-existentes.

### Veredicto final

**APPROVED**. Los 4 nits del reviewer pass-1 estan resueltos:
- Nit 1 (import top): VERDE objetivo.
- Nit 2 (validacion HEX + warning): VERDE objetivo, 39 tests nuevos
  verdes.
- Nit 3 (snapshot classic): VERDE objetivo, 2 tests nuevos verdes con
  diff legible ante drift.
- Nit 4 (docs drift): AMARILLO documentado correctamente, aceptable
  como consolidacion segun guia original.

**El leader puede marcar `feature_list.json` id=16 como `status: "done"`
sin riesgo.** No quedan blockers ni cambios requeridos.

### Sugerencias menores (NO blockers para feature 16)

1. En una sesion futura de limpieza, alinear los 3 tests pre-existentes
   que esperan `/health` sin `configured_worker_count` — el shape actual
   del endpoint es correcto, los tests son los desactualizados.
2. El paquete `shared/errors/validation.py` semanticamente no es de
   "errores" (es validacion de inputs sin levantar excepciones). En una
   futura iteracion del modulo `shared/`, valorar moverlo a un namespace
   mas descriptivo (`shared/validators/colors.py` o `shared/types/colors.py`)
   ahora que el implementer documento por que `shared/types/` no era
   viable inicialmente. No urgente.
