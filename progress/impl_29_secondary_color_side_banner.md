# impl 29 — secondary_color_side_banner (BACK)

> Feature back-only — sin frontend counterpart. La UI de
> `BrandSettings.secondary_color` ya existe desde feature 6. Esta feature
> conecta ese valor al render del template `side_banner`.

## Localización del `#FECF4D` hardcoded antes del cambio

Antes de la feature 29, el color `#FECF4D` vivía como constante única en:

- `modules/rendering/infrastructure/preparation.py:236`
  → `_SIDE_BANNER_RIBBON_BACKGROUND = "#FECF4D"`

Y se consumía en un único call site:

- `modules/rendering/infrastructure/preparation.py:209`
  → `background_hex=_SIDE_BANNER_RIBBON_BACKGROUND` en la invocación
  a `_render_vertical_status_banner` desde `prepare_reel_render_assets`.

Era el "polish" introducido por feature 17 (cinta más larga, BER a la
izquierda, fondo amarillo hardcoded). Antes de feature 17 el call site
pasaba `property_data.accent_background_color`; feature 17 lo unwireó y
feature 29 lo re-parametriza con cascada `brand.secondary_color → #FECF4D`.

## Cascada implementada

Solo dos niveles (decisión documentada):

1. `BrandSettings.secondary_color` si la agencia lo configuró
   (no-blank).
2. `#FECF4D` (`preparation._SIDE_BANNER_RIBBON_BACKGROUND`).

**No hay nivel "webhook secundario"**: se exploró el contrato actual y
los únicos campos de color del WordPress webhook son
`wppd_accent_text_color` y `wppd_accent_background_color`, ambos
consumidos como par primario (text/background de los paneles top/bottom)
desde feature 16. No hay un tercer campo "secundario" en el feed WP que
pudiera aplicar a la cinta vertical. Esto se documenta en el helper
`_resolve_brand_secondary_color` y en `docs/API.md`.

## Cómo viaja el color en el render data

1. **Ingest** (`modules/reels/application/use_cases/ingest_property_into_reel.py`):
   - Nuevo helper `_resolve_brand_secondary_color` (paralelo a
     `_resolve_brand_primary_color` y `_resolve_brand_font_descriptor`).
     Lee `BrandSettings.secondary_color` o devuelve `None`.
   - El valor resuelto se stashea en `render_template_reel_settings`
     bajo la clave **renderer-internal** `side_banner_ribbon_background_color`
     (solo en reel settings; el poster no usa la cinta).
2. **render_template_settings** (`modules/rendering/infrastructure/render_template_settings.py`):
   - La clave se añade a `_RENDERER_INTERNAL_OVERRIDE_KEYS` para que
     `normalize_property_reel_template_overrides` la filtre y NO la
     pase al dataclass `PropertyReelTemplate` (evita un
     `RENDER_TEMPLATE_SETTING_UNSUPPORTED`).
3. **Frame composition** (`modules/rendering/application/frame_composition.py`):
   - `DefaultMediaRenderer._build_render_data` lee la clave del dict y
     la setea en `PropertyRenderData.side_banner_ribbon_background_color`.
4. **Render data** (`modules/rendering/infrastructure/models.py`):
   - Nuevo campo `side_banner_ribbon_background_color: str | None = None`
     en `PropertyRenderData`.
5. **Preparation** (`modules/rendering/infrastructure/preparation.py`):
   - El call site pasa
     `background_hex=property_data.side_banner_ribbon_background_color or _SIDE_BANNER_RIBBON_BACKGROUND`.

El clásico no se ve afectado porque la rama `if layout_variant ==
"side_banner":` que llama a `_render_vertical_status_banner` solo se
ejecuta para el template side_banner.

## ¿Por qué un nuevo campo y no reusar accent_*?

`accent_text_color` / `accent_background_color` ya conducen los paneles
top/bottom del reel + poster con la cascada `webhook → brand_primary`.
Reusar uno habría acoplado los paneles (que pueden depender de un color
por propiedad) con la cinta (que depende del color de la marca). Se
introduce el campo dedicado para mantener la independencia y permitir
en el futuro plumbing similar para otros assets.

## Filter graph del side_banner antes / después

Antes:

```
filter -vf includes:
  color=0xfecf4d@1.00:s=HxW (drawbox)  ← fijo, ignora la marca
```

Después (cuando hay brand.secondary_color="#FF00FF"):

```
filter -vf includes:
  color=0xff00ff@1.00:s=HxW (drawbox)  ← respeta la marca
```

Después (cuando NO hay brand.secondary_color):

```
filter -vf includes:
  color=0xfecf4d@1.00:s=HxW (drawbox)  ← fallback hardcoded preservado
```

El formato `0xRRGGBB@1.00` lo emite `apply_alpha_to_hex(..., alpha=1.0)`
sobre el `background_hex` recibido — el alpha=1.0 viene del hotfix
feature 17 (la cinta dejó de ser translúcida).

## Tests añadidos / actualizados

**Actualizados:**

- `tests/unit/rendering/test_preparation_side_banner_ribbon_hardcode.py`:
  - El test inspect-source `test_prepare_reel_render_assets_wires_secondary_color_cascade`
    ahora exige que el call site referencie tanto
    `side_banner_ribbon_background_color` como
    `_SIDE_BANNER_RIBBON_BACKGROUND` (cascada), y que NO haya regresado
    a `property_data.accent_background_color` (feature 17).
  - Renombrado `test_render_vertical_status_banner_uses_hardcoded_color_for_drawbox`
    → `test_render_vertical_status_banner_uses_supplied_background_for_drawbox`
    porque ahora el ribbon ya no es hardcode en el call site, solo en
    el fallback constant.
- `tests/unit/rendering/conftest.py`: `build_property_data` acepta el
  nuevo campo opcional.
- `tests/integration/rendering/test_side_banner_render.py`: las
  `_fake_prepare` y `_build_context` aceptan / capturan el nuevo campo.

**Añadidos:**

- `tests/unit/rendering/test_preparation_side_banner_ribbon_hardcode.py::test_render_vertical_status_banner_honours_brand_secondary_color`
  — `background_hex="#FF00FF"` → el filter graph contiene
  `color=0xff00ff@1.00`, no `0xfecf4d`.
- `tests/unit/rendering/test_frame_composition_accent_colors.py::test_build_render_data_threads_brand_secondary_color_from_reel_settings`
  — la clave del dict aterriza en `PropertyRenderData`.
- `tests/unit/rendering/test_frame_composition_accent_colors.py::test_build_render_data_returns_none_when_no_property_and_no_fallback`
  ampliado con assert de `side_banner_ribbon_background_color is None`.
- `tests/unit/rendering/test_render_template_settings.py::test_normalize_property_reel_template_overrides_skips_renderer_internal_keys`
  — la nueva clave junto con `fallback_accent_*` se filtra
  silenciosamente del dataclass override.
- `tests/integration/rendering/test_side_banner_render.py::test_side_banner_render_threads_brand_secondary_color_to_preparation`
  — end-to-end: el valor del dict llega a la fake `prepare`.
- `tests/integration/rendering/test_side_banner_render.py::test_side_banner_render_secondary_color_absent_uses_none`
  — sin override en el dict, el render data lleva `None` (renderer cae
  al hardcoded).
- `tests/integration/rendering/test_side_banner_render.py::test_classic_render_ignores_brand_secondary_color_for_panels`
  — regresión: con classic + brand secondary set, los accent panels
  permanecen `None`.
- `tests/integration/reels/test_ingest_property_secondary_color.py`
  (nuevo file):
  - `test_ingest_injects_brand_secondary_color_into_reel_settings` —
    BBDD con secondary `#FF00FF` → la clave aterriza en
    `render_template_reel_settings`, NO en
    `render_template_poster_settings`.
  - `test_ingest_omits_secondary_color_when_brand_has_default_white` —
    sin row de brand, el helper devuelve `None` y la clave NO se añade.

## Resultados de verificación

```
.venv/bin/python -m pytest tests/unit/rendering/ tests/integration/rendering/ -q
140 passed in 11.21s

.venv/bin/python -m pytest tests/unit/reels/ tests/integration/reels/ -q
154 passed in 79.10s

.venv/bin/python -m pytest -q
3 failed, 811 passed, 14 warnings in 363.83s
   ↑ los 3 fallos son la baseline preexistente
     (test_http_surface_contract, 2x test_http_transport).
     811 = 803 baseline + 8 tests nuevos.

.venv/bin/python -m apps.api --check     → READY
.venv/bin/python -m apps.worker --check  → READY
```

Sanity:

```
grep -rn 'FECF4D\|#fecf4d' modules/
  → solo en comentarios + el fallback constant en preparation.py:245.

grep -rn '_resolve_brand_secondary_color' modules/
  → 2 hits, ambos en ingest_property_into_reel.py (definición + call).
```

## Archivos modificados

- `modules/rendering/infrastructure/models.py` — campo nuevo en `PropertyRenderData`.
- `modules/rendering/infrastructure/preparation.py` — call site cascada
  brand → hardcoded; comentario actualizado en la constant.
- `modules/rendering/infrastructure/render_template_settings.py` —
  `_RENDERER_INTERNAL_OVERRIDE_KEYS` incluye la nueva clave.
- `modules/rendering/application/frame_composition.py` —
  `_build_render_data` propaga la clave.
- `modules/reels/application/use_cases/ingest_property_into_reel.py` —
  helper `_resolve_brand_secondary_color` + wiring en `execute`.
- `tests/unit/rendering/conftest.py` — fixture builder ampliado.
- `tests/unit/rendering/test_preparation_side_banner_ribbon_hardcode.py`
  — tests actualizados + uno nuevo.
- `tests/unit/rendering/test_frame_composition_accent_colors.py` — un
  test ampliado + uno nuevo.
- `tests/unit/rendering/test_render_template_settings.py` — test nuevo
  para la frozenset.
- `tests/integration/rendering/test_side_banner_render.py` — utilidades
  ampliadas + 3 tests nuevos.
- `tests/integration/reels/test_ingest_property_secondary_color.py` —
  archivo nuevo.
- `docs/API.md` — sección Brand + nueva subsección sobre la cinta.

## Coexistencia con hotfixes Codex

- `modules/rendering/infrastructure/ffmpeg/filters.py` y
  `modules/rendering/infrastructure/layout/panels.py` permanecen sin
  tocar; el hotfix del footer radius y panel sigue intacto
  (`git diff` antes vs después no cambia).
- `modules/rendering/infrastructure/preparation.py` ya tenía el hotfix
  de feature 17 (la constante, body_height más alto, alpha=1.0); mi
  cambio en este archivo se limita al call site (línea ~209) y al
  comentario sobre la constante. El resto del archivo es idéntico.

## Notas para reviewer

- No toca BBDD: `secondary_color` ya existía en
  `agency_brand_settings.secondary_color` con default `#FFFFFF`.
- No toca capa de configuración: el resolver vive en reels (helper
  paralelo al de feature 28). El acceso a `BrandSettings` es por el
  mismo `uow.configuration.brand.get` que ya usa el resolver primario.
- Si una agencia mantiene el default `#FFFFFF` la cinta saldrá
  blanca (no hay special-case). Esto es consistente con `primary_color`
  (un brand muy claro también se respeta tal cual). Para volver al
  amarillo legacy hay que borrar el row de brand (improbable) o cambiar
  el valor a `#FECF4D` explícitamente.
- El campo en `PropertyRenderData` se serializa al manifest? — Se
  verificó que `PropertyRenderData` se usa runtime-only (no se
  persiste); solo `property_reel_template_to_dict` sobre
  `PropertyReelTemplate` se snapshottea para `content_fingerprint`, y
  el field nuevo está en `PropertyRenderData` (no en `PropertyReelTemplate`),
  así que no afecta al fingerprint ni invalida snapshots existentes.

— implementer
