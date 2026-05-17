# Explore: brand colors + fonts customisation — 2026-05-14

## TL;DR

El frontend `/brand` ya tiene UI funcional para `primary_color`,
`secondary_color` y `font_family` (los 2 hotfixes recientes solo
quitaron `LivePreview` y `LogoPlacementCard`; los 3 selectores siguen
ahí). El backend acepta los 3 campos en
`BrandSettingsUpsertPayload` (`extra='forbid'`) y los persiste, pero
**`font_family` es dead-end**: nunca llega al renderer — el render
usa `DEFAULT_REEL_FONT_PATH = "assets/fonts/Inter/static/Inter_28pt-Regular.ttf"`
hardcodeado. **Solo Inter está en disco**; las otras 4 opciones del
dropdown (Söhne, Manrope, Plus Jakarta Sans, Helvetica) son ficticias.
La precedencia de colores hoy es: webhook (`wppd_accent_*`) → brand-agency
fallback (solo `primary_color`, no `secondary_color` aún) → ninguno.
Ya existe `_sanitize_property_accent_colors` y `_resolve_brand_primary_color`
en `ingest_property_into_reel.py:570-625+`.

## 1. Frontend `/brand` actual (post-hotfixes)

- **Componente principal**: `src/features/brand/BrandConfig.jsx:10+`.
- **Inputs visibles**:
  - `LogoUploader` (línea 174).
  - `ColorInput` primary (`<input type="color">` + hex text, `BrandConfig.jsx:188`).
  - `ColorInput` secondary (línea 192).
  - Font dropdown nativo con array hardcodeado `FONTS = ['Inter',
    'Söhne', 'Manrope', 'Plus Jakarta Sans', 'Helvetica']` (líneas
    197-203).
- **`buildBrandBody`** (líneas 44-54): envía SIEMPRE los 6 campos del
  contrato, incluido `logo_position` (preservado del HOTFIX 2 aunque
  ya no hay UI para él).
- **Color picker**: `ColorInput.jsx` es un wrapper de `<input type="color">`
  nativo + input texto hex sincronizado. No es libcomponent — vive en
  el feature.

## 2. Backend contrato `/brand`

**Payload**: `modules/configuration/transport/payloads/brand.py`.

- `primary_color: str | None` (hex, líneas 32-36).
- `secondary_color: str | None` (hex, líneas 37-41).
- `font_family: str | None` (**string libre, sin enum, sin default**,
  líneas 55-59).
- `logo_position`, `logo_object_key`, `intro_logo_object_key`.
- `extra='forbid'` activo.

**Use case**: `update_brand_settings.py:41-49` llama
`uow.configuration.brand.upsert(...)` pasando todo crudo. Sin
validación enum sobre `font_family`.

**Catálogo de fuentes en back**: **NO EXISTE**. Solo hay constantes
hardcodeadas en `models.py:37-38`:
```
DEFAULT_REEL_FONT_PATH      = assets/fonts/Inter/static/Inter_28pt-Regular.ttf
DEFAULT_REEL_FONT_BOLD_PATH = assets/fonts/Inter/static/Inter_28pt-Bold.ttf
```

## 3. Fallback de colores (webhook → agencia → nada)

**Extracción del JSON WP**: el property carga `wppd_accent_text_color`
y `wppd_accent_background_color` del payload del webhook. Se sanitizan
en `ingest_property_into_reel.py:570-599` (`_sanitize_property_accent_colors`):
validan hex, si no son válidos → `None` (caen al fallback de agencia).

**Precedencia actual**:
1. Webhook trae `wppd_accent_*_color` → si válidos, gana.
2. Si webhook NO los trae → `BrandSettings.primary_color` de la agencia
   (`_resolve_brand_primary_color` línea 625+).
3. Si tampoco hay agencia → ffmpeg renderiza sin color explícito o
   con el default del template (depende del filter graph).

**Importante**:
- `secondary_color` de la agencia HOY NO se usa en el pipeline (solo
  `primary_color`). Confirmar si el render lo necesita o queda como
  metadatos.
- La inyección está en `PropertyRenderData.accent_text_color` y
  `accent_background_color` (`models.py:142-143`).

## 4. Fuentes en disco

`assets/fonts/`:
- `Inter/` (variable + estáticas regular/bold).
- **NADA MÁS**: Söhne, Manrope, Plus Jakarta Sans, Helvetica que el
  frontend lista están **mintiéndole al usuario** (acepta seleccionarlas,
  el back las guarda, el render las ignora y usa Inter).

`ffmpeg drawtext` necesita el path absoluto al `.ttf`/`.otf` en disco
para renderizar texto.

## 5. Cadena font_family back→render (HOY ROTA)

1. Frontend manda `font_family` en PUT → `BrandConfig.jsx:49`.
2. Pydantic acepta → `brand.py:55`.
3. Use case persiste → `BrandSettings.font_family` en BBDD.
4. **HIATO**: en `ingest_property_into_reel.py:206-256` se carga
   `brand = uow.configuration.brand.get(...)` pero **solo se extrae
   `brand.primary_color`** (línea 237). `font_family` no se usa.
5. `PropertyReelTemplate.font_path` y `bold_font_path` (`models.py:57-58`)
   siguen siendo `DEFAULT_REEL_FONT_PATH` (Inter) en todos los renders.
6. Renderer ffmpeg `drawtext` → Inter siempre.

## 6. Decisiones pendientes (a confirmar con el usuario)

1. **Qué fuentes meter en el catálogo del back**: el dropdown del front
   hoy lista 5 (Inter, Söhne, Manrope, Plus Jakarta Sans, Helvetica).
   Solo Inter está en disco. ¿Bajamos esas 4 fuentes (licencia OK?)
   o cambiamos el catálogo a fuentes libres (Roboto, Open Sans, Lato,
   Montserrat, Poppins)?
2. **Endpoint del catálogo**: nuevo `GET /v1/admin/fonts` que devuelve
   `{items: [{family, display_name, weight_paths: {regular, bold},
   available: true}]}`. El front popula el dropdown desde ahí (no hardcoded).
3. **Validación enum**: tras tener catálogo, hacer `font_family`
   validar contra esa lista en el payload (422 si no está).
4. **Inyección en render**: añadir `font_family` a `PropertyReelTemplate`,
   resolver path del `.ttf` por la API y cablear el ffmpeg drawtext.
5. **`secondary_color` en el render**: ¿hoy no se usa? Confirmar si
   el rediseño debe usarlo (p. ej. para el panel inferior del template
   classic) o queda como metadatos para el frontend.
6. **Política "borrar para volver al default"**: ¿el front manda
   `null` cuando el usuario limpia el color/fuente? El payload Pydantic
   lo acepta (`str | None`). Hay que asegurar que el use case persiste
   `NULL` (no string vacío) y que el resolver del render lo trata como
   "no override".
7. **Default global cuando ni agencia ni webhook tienen color**: hoy
   queda `None` y el ffmpeg cae a su default. ¿Hardcodear un fallback
   global (p. ej. `#0F172A` que ya es el seed default de
   `BrandSettings`)?

## 7. Gaps identificados

| # | Gap | Impacto | Mitigación |
|---|-----|---------|------------|
| 1 | Solo Inter en disco; dropdown ofrece 4 más ficticias | Misleading | Bajar las 4 fuentes (o cambiar catálogo) y servirlas en `assets/fonts/` |
| 2 | Sin catálogo programático (`GET /fonts`) | Front hardcodea | Nuevo endpoint que liste fuentes con paths |
| 3 | `font_family` no llega al render | Selector decorativo | Cablear en `PropertyReelTemplate` + ingest use case |
| 4 | Sin validación enum en payload | Garbage acepted | Validator contra catálogo |
| 5 | `secondary_color` persistido pero inerte | Confusión | Decisión de scope (usar o documentar como metadatos) |
| 6 | Sin tests del fallback completo (agencia → webhook → default) | Regresiones silenciosas | Suite integración nueva |

## 8. Archivos clave referenciados

**Frontend**:
- `src/features/brand/BrandConfig.jsx:10,44-54,188-203` (UI + body).
- `src/features/brand/api.js`, `hooks.js`, `brand.css`.
- `src/features/brand/ColorInput.jsx` (color picker compuesto).

**Backend**:
- `modules/configuration/transport/payloads/brand.py:18-59`.
- `modules/configuration/application/use_cases/update_brand_settings.py:27-49`.
- `modules/configuration/application/use_cases/read_brand_settings.py`.
- `modules/configuration/infrastructure/brand_repository.py`.
- `modules/reels/application/use_cases/ingest_property_into_reel.py:206-256,570-625` (resolver de colores).
- `modules/rendering/application/scripted_video/models.py:37-38,57-58,142-143` (paths hardcoded + PropertyRenderData).
- `modules/rendering/application/scripted_video/render_reel.py` (consumer ffmpeg).
- `assets/fonts/Inter/` (único asset disponible).
