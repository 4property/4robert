# Implementación: Añadir Barlow Semi Condensed al catálogo de fuentes

**Fecha:** 2026-05-19
**Tipo:** Tarea acotada (no es feature de `feature_list.json`).
**Reviewer:** pendiente (esta tarea no pasa por el ciclo implementer→reviewer
porque es una extensión incremental del catálogo OFL ya existente, sin schema
afectado).

## Resumen

Se incorporó la familia tipográfica **Barlow Semi Condensed** (Regular/Bold,
OFL) al catálogo canónico `modules/configuration/domain/font_catalog.py`. Con
esto el catálogo pasa de 6 a 7 familias. El frontend recoge la nueva familia
automáticamente vía `GET /v1/admin/fonts`; el render pipeline la usa via los
mismos hooks de `resolve_font_path`.

## Archivos creados

- `assets/fonts/Barlow_Semi_Condensed/Regular.ttf` — 83 864 bytes — TrueType
  Font data (`file` lo identifica como "TrueType Font data, 17 tables").
- `assets/fonts/Barlow_Semi_Condensed/Bold.ttf` — 88 644 bytes — TrueType
  Font data (idem).
- `assets/fonts/Barlow_Semi_Condensed/OFL.txt` — 4 377 bytes — empieza con
  `Copyright 2017 The Barlow Project Authors`.

### URLs de descarga (verificadas con `curl -sSL`)

- Regular: `https://fonts.gstatic.com/s/barlowsemicondensed/v16/wlpvgxjLBV1hqnzfr-F8sEYMB0Yybp0mudRnfw.ttf`
- Bold: `https://fonts.gstatic.com/s/barlowsemicondensed/v16/wlpigxjLBV1hqnzfr-F8sEYMB0Yybp0mudRfw6-PAA.ttf`
- OFL: `https://raw.githubusercontent.com/google/fonts/main/ofl/barlowsemicondensed/OFL.txt`

## Archivos modificados

- `modules/configuration/domain/font_catalog.py`
  - Añadida nueva entrada `FontDescriptor("Barlow Semi Condensed", ...)` al
    final de `AVAILABLE_FONTS` (séptima posición, después de Roboto).
  - Docstring del módulo actualizado: "ships six families" → "ships seven
    families"; añadido bullet describiendo Barlow Semi Condensed como cuts
    estáticos Regular/Bold descargados desde la CSS2 API de Google Fonts
    (mismo patrón que Poppins).
- `tests/unit/configuration/test_font_catalog.py`
  - `test_available_fonts_contains_six_entries_in_canonical_order` renombrado
    a `test_available_fonts_contains_seven_entries_in_canonical_order`;
    actualizado lista esperada (añade `"Barlow Semi Condensed"` al final) y
    cambia `len == 6` → `len == 7`.
  - Añadido `test_resolve_barlow_semi_condensed_returns_canonical_paths` que
    valida `family`, `display_name`, `regular_path` y `bold_path`.
- `tests/integration/configuration/test_fonts_router.py`
  - `test_fonts_list_returns_six_catalogue_entries` renombrado a
    `test_fonts_list_returns_seven_catalogue_entries`; payload count y len
    actualizados a `7`; lista de families ampliada con
    `"Barlow Semi Condensed"`.

## Verificación

### Tests dirigidos

- `pytest tests/unit/configuration/test_font_catalog.py -v` → **19 passed**
  (era 17 antes, +2 nuevos: rename + barlow path test).
- `pytest tests/integration/configuration/ -q` → **125 passed** en 200.71s.
- `pytest tests/integration/reels/test_ingest_property_font_injection.py -q`
  → **3 passed**.

### Smoke check inline

```
.venv/bin/python -c "from modules.configuration.domain.font_catalog import \
  AVAILABLE_FONTS, resolve; d = resolve('Barlow Semi Condensed'); \
  print(d.family, d.available(workspace_dir=__import__('pathlib').Path.cwd()))"
# → Barlow Semi Condensed True
```

### `bash ./init.sh` — exit 0

```
3 failed, 1116 passed, 1 deselected, 14 warnings in 594.33s (0:09:54)
```

Los 3 fallos son exactamente el baseline pre-existente documentado:

- `tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes`
- `tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state`
- `tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads`

`apps.api --check` y `apps.worker --check` verdes.

## Decisiones no obvias

- **Reusar el patrón de Poppins** (true static Regular/Bold, no variable cut)
  porque la CSS2 API expone cuts independientes para esa familia, igual que
  Poppins. Esto evita la duplicación Regular→Bold que hacen Manrope/Roboto.
- **Añadir Barlow al final del array, no por orden alfabético**, para
  mantener el orden histórico (Inter, Manrope, Plus Jakarta Sans,
  Montserrat, Poppins, Roboto) intacto: el dropdown del frontend respeta el
  orden del array, y reordenar rompería la UX existente para usuarios que
  ya recuerdan posiciones.
- **No hay migración Alembic**: el catálogo es código puro, no toca DB.
  `BrandSettings.font_family` es una columna `TEXT` libre cuya validación
  se ejecuta en el payload validator vía `ALLOWED_FONT_FAMILIES` (derivado
  automáticamente de `AVAILABLE_FONTS`), así que el cambio se propaga sin
  schema migration.
