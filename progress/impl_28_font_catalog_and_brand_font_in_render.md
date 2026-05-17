# impl 28 — font_catalog_and_brand_font_in_render (backend)

- **Inicio:** 2026-05-14
- **Agente:** implementer (Claude Opus 4.7)
- **Feature:** 28 — `font_catalog_and_brand_font_in_render` (sólo backend; el frontend irá en una sesión separada).
- **Estado:** Implementación completa, `pytest -q` global verde respecto al baseline (3 fallos preexistentes). `feature_list.json` **NO** marcado como `done` — pendiente del reviewer + frontend.

## 1. Inventario de fuentes bajadas

Estructura final bajo `assets/fonts/`:

| Family | Carpeta | Regular.ttf | Bold.ttf | OFL.txt | Tipo |
|--------|---------|------------:|---------:|--------:|------|
| Inter | `Inter/static/` | 1.0 MB (preexistente) | 1.0 MB (preexistente) | sí (preexistente) | TTF estático (peso fijo) |
| Manrope | `Manrope/` | 165 420 B | 165 420 B | 4 384 B | TTF variable (regular+bold = mismo archivo) |
| Plus Jakarta Sans | `Plus_Jakarta_Sans/` | 176 288 B | 176 288 B | 4 402 B | TTF variable (regular+bold = mismo archivo) |
| Montserrat | `Montserrat/` | 744 936 B | 744 936 B | 4 400 B | TTF variable (regular+bold = mismo archivo) |
| Poppins | `Poppins/` | 160 316 B | 155 996 B | 4 385 B | TTF estáticos reales |
| Roboto | `Roboto/` | 488 584 B | 488 584 B | 4 394 B | TTF variable (wdth+wght, regular+bold = mismo archivo) |

Todas son OFL: cada carpeta incluye su `OFL.txt` bajado desde el repo
oficial `google/fonts` (ramo `main`).

### Detalle por URL real usada

```
https://github.com/google/fonts/raw/main/ofl/manrope/Manrope%5Bwght%5D.ttf
https://github.com/google/fonts/raw/main/ofl/manrope/OFL.txt
https://github.com/google/fonts/raw/main/ofl/plusjakartasans/PlusJakartaSans%5Bwght%5D.ttf
https://github.com/google/fonts/raw/main/ofl/plusjakartasans/OFL.txt
https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf
https://github.com/google/fonts/raw/main/ofl/montserrat/OFL.txt
https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Regular.ttf
https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf
https://github.com/google/fonts/raw/main/ofl/poppins/OFL.txt
https://github.com/google/fonts/raw/main/ofl/roboto/Roboto%5Bwdth%2Cwght%5D.ttf
https://github.com/google/fonts/raw/main/ofl/roboto/OFL.txt
```

### Decisión: variable vs estática

`google/fonts` sólo publica Manrope, Plus Jakarta Sans, Montserrat y
Roboto como **TTF variable** (los archivos `Family[wght].ttf`). Poppins
sí ships static por peso. Para mantener el contrato del catálogo
(`regular_path` + `bold_path`) sin instalar `fontTools` para extraer
pesos individuales se opta por **duplicar el TTF variable** como
regular y bold (mismo binario): ffmpeg `drawtext` no consume el axis
`wght` de un variable font de forma automática, así que el "bold" se
renderiza con el peso por defecto del archivo. El renderer no falla y
la familia se distingue visualmente del resto del catálogo; el matiz
regular/bold se pierde para esas 4 familias hasta que decidamos bajar
estáticos manualmente (FontFreedom, FontSquirrel, etc.) o instalar
`fontTools`. Está documentado en el docstring del helper.

`./init.sh` mide ~3 MB extra en `assets/fonts/` (50 MB → ~53 MB,
sigue muy por debajo de cualquier umbral que requiera Git LFS).

## 2. Decisión sobre el error 422 (Option A)

El task recomendaba Option A; se siguió.

- **Implementación:** `@field_validator('font_family')` clásico en
  `BrandSettingsUpsertPayload`. Lanza `ValueError` con un mensaje que
  empieza por `UNKNOWN_FONT_FAMILY:` y enumera la lista completa de
  familias aceptadas:

  ```
  UNKNOWN_FONT_FAMILY: 'Söhne' is not in the catalogue. Allowed families: Inter, Manrope, Montserrat, Plus Jakarta Sans, Poppins, Roboto.
  ```

- **Forma exacta del response 422** (default de FastAPI):

  ```json
  {
    "detail": [
      {
        "type": "value_error",
        "loc": ["body", "font_family"],
        "msg": "Value error, UNKNOWN_FONT_FAMILY: 'Söhne' is not in the catalogue. Allowed families: Inter, Manrope, ...",
        "input": "Söhne"
      }
    ]
  }
  ```

- **Trade-off vs Option B:** la lista `allowed_families` no aparece
  como `details.allowed_families` programático (sólo dentro del texto
  del `msg`). Si el reviewer prefiere serialización programática, la
  ruta es registrar un `RequestValidationError` handler en
  `apps/api/error_handlers.py` que detecte el prefix `UNKNOWN_FONT_FAMILY:`
  y reescriba la respuesta a la forma canónica
  `{error, code, hint, details: {allowed_families: [...]}}` — son ~20
  líneas extra. Hoy el frontend puede parsear el `detail[0].msg` para
  recuperar la lista.

## 3. Cambios por capa

### Domain (`modules/configuration/domain/`)

- **`font_catalog.py`** (nuevo): `FontDescriptor` (dataclass frozen +
  slots con `family`, `display_name`, `regular_path`, `bold_path` y
  `available(workspace_dir=...)`), tupla `AVAILABLE_FONTS` con las 6
  familias en orden canónico, `ALLOWED_FONT_FAMILIES` (frozenset),
  `DEFAULT_FONT_FAMILY = "Inter"`, `resolve(family)`.
- **`__init__.py`**: re-exporta `font_catalog`, `FontDescriptor`,
  `AVAILABLE_FONTS`, `ALLOWED_FONT_FAMILIES`, `DEFAULT_FONT_FAMILY`.

### Application (`modules/configuration/application/use_cases/`)

- **`list_available_fonts.py`** (nuevo): `ListAvailableFontsUseCase`.
  Wrapper puro sobre `font_catalog.AVAILABLE_FONTS` — sin DB, sin
  UoW. Existe para que la capa transport no importe `domain.font_catalog`
  directamente (mismo patrón que `ListMusicTracksUseCase`).

### Transport (`modules/configuration/transport/`)

- **`http/fonts_router.py`** (nuevo): router admin con
  `GET /v1/admin/fonts`. Auth vía `authorize_admin_request`. Acepta
  un `workspace_dir` opcional (usado por los tests para apuntar al
  workspace temporal). Devuelve `{items: [{family, display_name,
  available}], count}`.
- **`payloads/brand.py`**: añadido `@field_validator('font_family')`
  que rechaza familias fuera de `ALLOWED_FONT_FAMILIES` con el mensaje
  `UNKNOWN_FONT_FAMILY` descrito en §2. Importa `ALLOWED_FONT_FAMILIES`
  del domain (capa permitida).

### Bootstrap

- **`apps/api/app_factory.py`**: import del `create_fonts_router` y
  `include_router` después de defaults_router; le pasa el
  `resolved_workspace` para el flag `available`.
- **`tests/integration/configuration/_client.py`**: añadido el
  fonts_router al builder para que los demás tests de configuration
  que ya estaban no rompan y para soportar el nuevo
  `test_fonts_router.py`.

### Render injection (`modules/reels/application/use_cases/`)

- **`ingest_property_into_reel.py`**: nuevo método
  `_resolve_brand_font_descriptor(uow, agency_id)` (defensivo en 4
  axes: agency vacío, sin `uow.configuration`, sin `brand` repo,
  brand row null o `font_family` no en catálogo → fallback a Inter
  con `logger.warning`).
  - El descriptor resuelto se inyecta como `font_path` y
    `bold_font_path` (str de `Path`) tanto en
    `render_template_reel_settings` como en
    `render_template_poster_settings`, **sobrescribiendo** los
    defaults heredados de `ResolvedRenderTemplateSettings`. El downstream
    `frame_composition._render_reel`
    (`modules/rendering/application/frame_composition.py:78-83`) rebuilds
    el `PropertyReelTemplate` a partir del dict vía
    `build_property_reel_template_from_overrides`, que ya sabe
    convertir `str → Path` (`_coerce_template_value`, branch `isinstance(default_value, Path)`).
- **Renderer / models**: NO se tocan `DEFAULT_REEL_FONT_PATH`,
  `DEFAULT_REEL_FONT_BOLD_PATH` ni `PropertyReelTemplate`. Las
  constantes siguen siendo el último-recurso para rutas técnicas
  (`readiness.py`, payloads del scripted_render directo) — eliminarlas
  hoy obligaría a tocar 4 sitios más y no es necesario para satisfacer
  la feature.

### Docs

- **`docs/API.md`**: añadida sección **Font catalogue (feature 28)**
  con la nueva entrada `GET /v1/admin/fonts`, su shape de respuesta y
  el render-time wiring. La sección de Brand ahora documenta el
  validator `font_family` (422 con código en el `msg`).
- **`docs/http_surface.md`** y **`docs/openapi.json`**: regenerados
  con `scripts/generate_http_surface.py --write` para incluir
  `GET /v1/admin/fonts`.

## 4. Tests añadidos

| Suite | Archivo | Cuenta | Cubre |
|-------|---------|------:|-------|
| Unit | `tests/unit/configuration/test_font_catalog.py` | 13 | `AVAILABLE_FONTS` orden canónico + len 6, `ALLOWED_FONT_FAMILIES` coincide, `DEFAULT_FONT_FAMILY=Inter`, `resolve(Inter/Manrope)`, `resolve(None/''/whitespace)` → Inter, `resolve('NotAFont')` → ValueError, case-sensitive (`'inter'` rechazada), `available()` (true / false con tmp_path), `available()` real contra workspace del repo (las 6 TTFs existen). |
| Integration | `tests/integration/configuration/test_fonts_router.py` | 3 | GET `/v1/admin/fonts` con admin bearer → 6 entradas en orden canónico, `available=true`; 401 sin bearer; `available=false` cuando el workspace temporal no tiene los TTFs. |
| Integration | `tests/integration/configuration/test_brand_router.py` | +4 nuevos (12 totales) | PUT con `font_family='Manrope'` → 200 y persistencia; PUT con `font_family=None` → 200 y persiste null/''; PUT con `'Söhne'`, `'Helvetica'`, `'NotAFont'`, `'inter'` → 422 conteniendo `UNKNOWN_FONT_FAMILY` y `Allowed families`. |
| Integration | `tests/integration/reels/test_ingest_property_font_injection.py` (nuevo) | 3 | Ingest con `font_family='Manrope'` → `render_template_reel_settings.font_path` apunta a `Manrope/Regular.ttf`, mismo para `bold_font_path` y para `poster_settings`; ingest con `font_family=null` → cae a Inter; ingest con `font_family='Söhne'` persistido por bypass → logs warning y cae a Inter sin crash. |

Los 4 tests preexistentes de `test_brand_router.py` no fueron
modificados; uno de ellos ya usa `font_family='Roboto'` que está en
el catálogo (sigue verde).

## 5. Resultados de verificación

```bash
# Targeted
.venv/bin/python -m pytest \
  tests/unit/configuration/test_font_catalog.py \
  tests/integration/configuration/test_fonts_router.py \
  tests/integration/configuration/test_brand_router.py \
  tests/integration/reels/test_ingest_property_font_injection.py -q
=> 35 passed in 21.10s
```

```bash
# Suite completa de las capas tocadas
.venv/bin/python -m pytest \
  tests/integration/configuration/ \
  tests/integration/reels/ \
  tests/unit/configuration/ -q
=> 281 passed in 229.50s
```

```bash
# Global
.venv/bin/python -m pytest -q
=> 803 passed, 3 failed, 14 warnings in 358.30s
```

Los 3 fallos coinciden con la baseline documentada:

- `tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes`
  → no encuentra el repo del frontend (`FRONTEND_REPO_ROOT` no
  configurado en este host); preexistente.
- `tests/integration/test_http_transport.py::test_health_endpoints_*` (2)
  → diferencia en el shape de `/health` (preexistente; el endpoint
  ahora devuelve `configured_worker_count` extra que estos asserts no
  contemplan).

```bash
.venv/bin/python -m apps.api --check    # EXIT=0
.venv/bin/python -m apps.worker --check # EXIT=0
```

Sanity-check fuentes:

```
for f in Inter Manrope Plus_Jakarta_Sans Montserrat Poppins Roboto; do
    ls -la assets/fonts/$f/
done
```

- Inter (preexistente): variable + static + OFL.txt + README.txt.
- Manrope/PJS/Montserrat/Roboto: `Regular.ttf`, `Bold.ttf` (variable
  duplicado), `OFL.txt`.
- Poppins: `Regular.ttf`, `Bold.ttf` (estáticos reales), `OFL.txt`.

`file assets/fonts/<F>/Regular.ttf` confirma `TrueType Font data`
para los 6.

## 6. Archivos modificados / añadidos

Nuevos:

- `assets/fonts/Manrope/{Regular.ttf, Bold.ttf, OFL.txt}`
- `assets/fonts/Plus_Jakarta_Sans/{Regular.ttf, Bold.ttf, OFL.txt}`
- `assets/fonts/Montserrat/{Regular.ttf, Bold.ttf, OFL.txt}`
- `assets/fonts/Poppins/{Regular.ttf, Bold.ttf, OFL.txt}`
- `assets/fonts/Roboto/{Regular.ttf, Bold.ttf, OFL.txt}`
- `modules/configuration/domain/font_catalog.py`
- `modules/configuration/application/use_cases/list_available_fonts.py`
- `modules/configuration/transport/http/fonts_router.py`
- `tests/unit/configuration/test_font_catalog.py`
- `tests/integration/configuration/test_fonts_router.py`
- `tests/integration/reels/test_ingest_property_font_injection.py`

Modificados:

- `modules/configuration/domain/__init__.py` — re-exports.
- `modules/configuration/transport/payloads/brand.py` — validator.
- `modules/reels/application/use_cases/ingest_property_into_reel.py`
  — imports + inyección de font_path/bold_font_path + método
  `_resolve_brand_font_descriptor`.
- `apps/api/app_factory.py` — mount del fonts_router.
- `tests/integration/configuration/_client.py` — mount del
  fonts_router en el test client.
- `tests/integration/configuration/test_brand_router.py` — 4 tests
  nuevos del validator.
- `docs/API.md` — sección de Font catalogue.
- `docs/http_surface.md`, `docs/openapi.json` — regenerados.
- `progress/current.md` — bitácora de cierre (sección feature 28
  back).

## 7. Notas para el reviewer

1. La feature **no** marca `done` en `feature_list.json`; el reviewer
   debe validar antes de hacerlo. Front (feature 28) sigue `pending`.
2. La forma del 422 (Option A) está enunciada en §2: confirmar que
   el frontend aceptará parsear `detail[0].msg` para extraer la lista
   de familias. Si no, conviene cambiar a Option B (handler
   `RequestValidationError` dedicado).
3. La duplicación del TTF variable como regular+bold (Manrope, PJS,
   Montserrat, Roboto) está documentada pero deja un matiz visual:
   regular y bold se renderizan idénticos para esas 4 familias. Si el
   producto exige bold real, plan B = bajar fuentes estáticas
   alternativas (no todas están publicadas por Google upstream en
   formato estático).
4. La constante `DEFAULT_REEL_FONT_PATH` sigue viva como último
   recurso (readiness probe, payload helpers del scripted render
   directo). No causa harm porque ahora el ingest siempre sobre-escribe
   `font_path`/`bold_font_path` en el dict de overrides.
5. No hay cambios de schema ni alembic.
6. Layer rule: rendering NO importa configuration application/infra.
   Sólo el ingest (`modules/reels/application`) importa el catálogo
   desde `modules/configuration/domain`, que es legal.
