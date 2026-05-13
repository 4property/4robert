# Explore — Feature 10 `agency_logo_upload` — estado actual

Mapa de referencia para el implementer. Solo lectura. Todas las rutas son
relativas a `/opt/projects/4Reels-Backend/`.

## 1. Estado actual de `PUT /v1/admin/agencies/{id}/brand`

### Router

- Archivo: `modules/configuration/transport/http/brand_router.py`
- Factory: `create_brand_router(...)` linea 32-44 — prefijo
  `admin_access_policy.base_path` (`/v1/admin`), tag `Admin · Brand`.
- Handler PUT: `update_admin_agency_brand_settings(agency_id, payload, request)`
  linea 91-144 con ruta `"/agencies/{agency_id}/brand"` (linea 82).
- Auth: usa `authorize_admin_request(request, admin_access_policy)` lineas
  96-98 — el mismo gate que el resto de `/v1/admin/*` (super-admin token o
  agency-scoped JWT cuyo `agency_id` coincide con el de la URL).
- Errores devueltos: `ValidationError → 400`, `ResourceNotFoundError →
  404`, `ApplicationError → 500 BRAND_SAVE_FAILED`.
- Respuesta 200: `{"status":"saved","agency_id":..., "brand": {...}}`.

### Payload model

- Archivo: `modules/configuration/transport/payloads/brand.py`
- Clase: `BrandSettingsUpsertPayload` linea 8-59.
- `model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, ...)`
  linea 17-30 — **rechaza con 422 cualquier campo no listado**.
- Campos actuales (todos `str | None = None`):
  - `primary_color` (linea 32-36)
  - `secondary_color` (linea 37-41)
  - `logo_position` (linea 42-46)
  - `logo_object_key` (linea 47-50) — **ya está declarado en el payload**
  - `intro_logo_object_key` (linea 51-54) — **ya está declarado en el
    payload**
  - `font_family` (linea 55-59)
- IMPORTANTE: la afirmación de la feature de que `extra="forbid"`
  rechaza hoy `logo_object_key`/`intro_logo_object_key` es **incorrecta**.
  Esos dos campos YA están aceptados en el payload, YA se pasan al use
  case (lineas 108-109 del router) y YA se persisten (ver §2 y
  `update_brand_settings.py:46-47`). El test
  `tests/integration/configuration/test_brand_router.py:115-150` solo
  cubre rechazo de `font`, `tagline`, `watermark_enabled`,
  `outro_enabled`, `outro_headline`, `outro_sub` — no son los object_key.
- El example en `json_schema_extra` linea 26-27 incluye
  `"logo_object_key": "agencies/ckp/logo.png"` y
  `"intro_logo_object_key": "agencies/ckp/intro-logo.png"`.
- Validación de extra="forbid" se prueba en
  `tests/integration/configuration/test_brand_router.py:126` (parametrizado).

### Use case

- Archivo: `modules/configuration/application/use_cases/update_brand_settings.py`
- Clase input: `UpdateBrandSettingsInput` linea 19-27 (dataclass frozen)
  con `logo_object_key: str | None = None` (linea 25) e
  `intro_logo_object_key: str | None = None` (linea 26).
- Clase: `UpdateBrandSettingsUseCase` linea 30-49.
- `execute(uow, data)`: llama `ensure_agency_exists(uow, agency_id)` y
  luego `uow.configuration.brand.upsert(...)` pasando ambos
  `logo_object_key` y `intro_logo_object_key` (lineas 46-47).
- ConsecuenciaSi se quitase `extra="forbid"`, **no haría falta tocar el
  use case**: ya acepta los dos campos.

### Repositorio

- Archivo: `modules/configuration/infrastructure/brand_repository.py`
- Clase: `BrandSettingsRepository(ModuleRepository)` linea 10-96.
- Métodos:
  - `get(agency_id)` linea 11-32 — SELECT con SQL crudo (no usa ORM).
  - `upsert(...)` linea 34-95 — INSERT ... ON CONFLICT DO UPDATE; merge
    field-by-field con valores existentes (lineas 47-66), defaults
    de strings vacíos para `logo_object_key`/`intro_logo_object_key`
    cuando el agente no tiene fila previa (lineas 59 y 62).
- Acceso: `uow.configuration.brand` (la `ConfigurationUnitOfWork`
  expone `brand` como `BrandSettingsRepository`).

## 2. Columnas `agency_brand_settings.logo_object_key` y `intro_logo_object_key`

### ORM

- Archivo: `modules/configuration/infrastructure/orm.py`
- Clase: `AgencyBrandSettingsORM(Base)` linea 20-43.
- `__tablename__ = "agency_brand_settings"` (linea 21).
- Columnas (NO nullable, server_default=""):
  - `logo_object_key: Mapped[str] = mapped_column(Text, nullable=False,
    server_default="")` — **linea 37**.
  - `intro_logo_object_key: Mapped[str] = mapped_column(Text,
    nullable=False, server_default="")` — **lineas 38-40**.
- Ambas son `Text NOT NULL DEFAULT ''`. NO permiten NULL en BBDD; el
  payload del PUT puede pasar `None` (significa "no tocar") pero NUNCA
  se escribe NULL en BBDD; el repositorio convierte `None` en
  "mantener valor previo" (ver `brand_repository.py:57-62`).
- Para "borrar" un object_key habría que enviar `""` (string vacío),
  no `null`. Esto es importante para la aceptancia de la feature
  ("nullable para borrar"): el contrato actual del PUT trata `None` como
  "no cambiar"; el implementer tendrá que decidir si:
  - (a) string vacío representa "sin logo" (alineado con el estado
    actual de la tabla), o
  - (b) cambia el flujo para permitir explícitamente borrar (p.ej.
    distinguiendo `field unset` vs `field explicitly null`).
  La opción (a) requiere cero cambios de schema y es coherente con el
  resto del codebase.

### Migración

- `alembic/versions/20260501_0001_initial_schema.py` lineas 119-134
  crea `agency_brand_settings` con `logo_object_key` y
  `intro_logo_object_key` como `Text NOT NULL DEFAULT ''`. **NO hace
  falta migración** para la feature 10.

### Domain

- `modules/configuration/domain/agency_settings.py` clase
  `BrandSettings` lineas 18-28 — `logo_object_key: str` e
  `intro_logo_object_key: str` (no opcionales — strings vacíos cuando
  faltan).

### Consumidores actuales

- Lectura: `modules/configuration/application/use_cases/read_brand_settings.py`
  y `modules/configuration/application/use_cases/read_aggregated_reel_profile.py`
  (este último expone `logo_object_key`/`intro_logo_object_key` en el
  perfil agregado leído desde `/v1/admin/agencies/{id}/reel-profile`).
- Escritura: `update_brand_settings` (descrito arriba).
- **El rendering NO consume `agency_brand_settings.logo_object_key`
  todavía** — esa es precisamente la lagunas que cierra esta feature.

## 3. Rendering: dónde se elige el logo

### `branding.py`

- Archivo: `modules/rendering/infrastructure/runtime/branding.py`
- `prepare_cover_logo_image(workspace_dir, property_data, settings,
  *, suppress_if_duplicate=True)` — **lineas 45-97**.
- Decisión actual (lineas 53-54): se toma `property_data.agency_logo_url`
  como única fuente; si está vacío → retorna `None` (sin logo).
- Filtros pre-descarga:
  - Si `agency_logo_url` está vacío → `None` (linea 54).
  - Si `is_duplicate_agent_and_agency_image(property_data)` (mismo
    basename que `agent_photo_url`) y `suppress_if_duplicate=True` →
    `None` con log (lineas 56-62).
  - Si la extensión del file no está soportada → `None` con warning
    (lineas 63-70).
- Cache de destino: `resolve_cached_branding_destination(...)` linea
  72-78 produce
  `workspace_dir/generated_media/{safe_site}/_branding/{slug}-agency-logo-{sha1_12}{ext}`.
- Si el destino ya existe → se reusa; si no, descarga remota con
  `download_remote_image(agency_logo_url, destination)` (linea 83).
- Llamada a `prepare_agent_image` (lineas 100-138): si NO hay
  `agent_photo_url` Y el agency logo coincide en basename, se usa el
  agency logo como sustituto del agent panel (linea 107-114). Mismo
  comportamiento como fallback ante error de descarga del agent
  (lineas 130-137).

### `preparation.py`

- Archivo: `modules/rendering/infrastructure/preparation.py`
- La feature dice "preparation.py:168-176". Lo verifico:
  - `prepared_cover_logo_path: Path | None = None` — linea 147.
  - `cover_logo_path = prepare_cover_logo_image(workspace_dir,
    property_data, settings)` — **linea 148**.
  - `reserve_agency_logo_space = should_reserve_agency_logo_space(...)`
    — lineas 149-152.
  - Bloque condicional que solo procesa el logo si hay layout space:
    lineas 153-176.
  - Asignación final `prepared_cover_logo_path = overlays_dir /
    "agency_logo.png"` y `_normalize_agency_logo(...)` — **lineas
    168-176**, que coincide exactamente con la referencia de la feature.
- También se llama `prepare_cover_logo_image` en
  `modules/rendering/infrastructure/manifest.py:115` (sin pasar por
  preparation cuando se construye un manifest standalone).

### Procedencia del logo URL

- `property_data.agency_logo_url` se rellena en
  `modules/rendering/application/frame_composition.py:172`:
  `agency_logo_url=context.property.agency_logo_url,`.
- `context.property` es un `Property` (de
  `modules/catalog/domain/wordpress_property.py`); el campo
  `agency_logo_url: str | None = None` (linea 83) se hidrata desde el
  webhook WP en `from_api_payload` linea 172:
  `agency_logo_url=to_text(payload.get("agency_logo"))`.
- Conclusión: hoy el rendering tira **exclusivamente** del JSON crudo
  del webhook WP (campo `agency_logo`). NO consulta
  `agency_brand_settings`.

### Lógica de fallback hoy

- Si `property.agency_logo_url is None` o vacío,
  `prepare_cover_logo_image` retorna `None` (linea 54). El layout no
  reserva espacio para el logo y el reel se renderiza sin badge de
  agencia.
- Excepción: `prepare_agent_image` (linea 100-138) usa el agency logo
  como fallback del agent panel solo si NO hay `agent_photo_url`.
- NO existe fallback hacia `agency_brand_settings.logo_object_key`
  porque ese consumidor todavía no está cableado en rendering.

## 4. Storage: cómo subir un objeto

### `resolve_cached_branding_destination`

- Archivo: `modules/rendering/infrastructure/runtime/assets.py:206-220`
- Firma actual:
  ```py
  def resolve_cached_branding_destination(
      *,
      workspace_dir: Path,
      site_id: str,
      slug: str,
      image_url: str,
      label: str,
  ) -> Path
  ```
- Hace:
  1. Construye
     `workspace_dir/generated_media/{safe_site_dirname(site_id)}/_branding/`
     (linea 214-216) y lo crea con `mkdir(parents=True, exist_ok=True)`.
  2. Calcula `sha1(image_url)[:12]` y resuelve el suffix con
     `resolve_remote_image_suffix(image_url)` (lineas 218-219).
  3. Retorna `branding_dir / f"{slug}-{label}-{image_hash}{suffix}"`
     (linea 220).
- **Está diseñada para cachear logos descargados de URLs remotas
  (webhook), no para alojar uploads del admin**. La feature menciona
  que el endpoint debe usar esta función "vía runtime/assets.py" — el
  implementer probablemente necesite (a) reutilizar la lógica de path
  resolution pero con una key derivada del agency_id (no del site_id +
  slug), o (b) introducir una variante hermana
  `resolve_agency_branding_destination(workspace_dir, agency_id,
  filename)` que use un layout por agencia.

### Infra S3 / boto

- **NO existe infra de S3 ni boto3 en el repo**.
  `grep -rn "boto3\|s3\|S3_BUCKET\|AWS_" --include="*.py"` no devuelve
  ningún resultado fuera de comentarios.
- **`.env.example` NO declara `S3_BUCKET`, `AWS_*` ni variables
  similares**. Toda la persistencia de assets es filesystem en
  `workspace_dir` (ver `shared/storage/site_layout.py`).
- El término "object_key" se usa en el dominio (music tracks, brand
  logo) como **identificador opaco** (puede ser una ruta lógica como
  `agencies/ckp/logo.png`); ningún componente lo traduce a una URL real
  hoy.

### URL pública del object_key

- **NO existe helper para construir una URL pública desde un
  object_key**.
- Patrón de servir archivos locales en otros routers: ver
  `modules/reels/transport/http/admin_reels_assets.py:117-308`
  (`stream_admin_agency_reel_video`, `stream_admin_agency_reel_image`,
  etc.) — usan `StreamingResponse`/`build_range_response` sobre el path
  local y devuelven un `file_url` relativo del estilo
  `f"{admin_access_policy.base_path}/agencies/{agency_id}/reels/{site_id}/..."`
  (linea 225-228).
- Implicación para feature 10: el endpoint upload necesitará tanto (a)
  persistir el archivo localmente (con un object_key estable) como (b)
  decidir qué `url` devuelve en el response — probablemente un path
  servido por el back (similar a `file_url` en admin_reels_assets) o
  una URL absoluta si en el futuro se enchufa S3. La feature acepta
  "fallback FS" → la implementación FS-only es válida por ahora,
  dejando la abstracción S3 como TODO.

### Patrones multipart existentes

- **NO existe ningún endpoint multipart/UploadFile en el repo**.
  - `grep -rn "UploadFile\|multipart\|File("` sobre `modules/` y
    `apps/` retorna solo referencias a "multipart/byteranges" (response
    para Range requests en `apps/api/range_response.py`) y a
    `UploadFileNameBuilder` que es **un nombre de tipo no relacionado**
    en `modules/publishing/infrastructure/adapters/platforms/models.py:21`
    (es un Callable para generar nombres de archivo en el publish a
    redes sociales, no un upload).
- El router de music tracks acepta `object_key` opaco vía JSON
  (`modules/configuration/transport/http/music_router.py:67-126`) — el
  admin envía un object_key ya existente; **no hay endpoint para subir
  el archivo de música tampoco**. Esto será el primer endpoint
  multipart del proyecto.
- Convención FastAPI sugerida: `agency_id: str` como path param,
  `file: UploadFile = File(...)` (multipart/form-data), validación
  manual de content_type/size, escritura a disco vía path resuelto en
  `runtime/assets.py`.

## 5. Validación / seguridad esperada

### Límites de tamaño/formato

- **NO existe convención de tamaño máximo de upload en el codebase**.
  - `WEBHOOK_MAX_PAYLOAD_BYTES=1000000` (1 MB) está fijado pero aplica
    solo al webhook WP (`settings/webhook.py:20`, usado únicamente en
    `modules/ingestion/transport/http/wordpress_webhook_router.py`). NO
    se reutiliza para uploads admin.
  - Sugerencia pragmática (sin convención previa): 5-10 MB para logos
    PNG/JPG (suficiente para vectores rasterizados a 4K). El implementer
    debe documentar la decisión en `docs/API.md`.
- **Formato**: las extensiones de imagen aceptadas globalmente están en
  `settings/images.py:14`:
  `IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff",
  ".webp"}`. La acceptance de la feature ("JPG/PNG") es más estricta —
  el implementer debe validar a `image/jpeg` + `image/png` por
  content_type Y por extensión.

### Helper de validación de uploads

- **NO existe `validate_image_upload` ni similar**.
  - `modules/rendering/infrastructure/runtime/assets.py:236-242`
    expone `has_explicit_unsupported_image_suffix(image_url)` pero
    opera sobre URLs remotas (texto), no sobre `UploadFile`.
  - El implementer puede:
    - (a) Crear un helper nuevo
      `modules/configuration/application/validators.py:validate_logo_upload(file)`
      o
    - (b) Implementar la validación inline en el handler (4-6 líneas).
- **Content-Type vs extensión**: ningún módulo cruza estos dos hoy;
  hay precedente puramente de extensión
  (`has_explicit_unsupported_image_suffix`). Se recomienda validar
  ambos para defender contra clientes maliciosos.

### Token de auth

- El router heredará `authorize_admin_request(request,
  admin_access_policy)` igual que el resto de `/v1/admin/*`. Esto
  acepta:
  - Super-admin token (ADMIN_API_TOKEN) en cualquier ruta admin.
  - Agency-scoped JWT (HS256) si el path matchea
    `/v1/admin/agencies/{agency_id}/...` y el claim `agency_id` del
    token coincide con el de la URL — exactamente el caso del nuevo
    endpoint `POST /v1/admin/agencies/{id}/brand/logo`.
- Implementación: 3 líneas idénticas a las del PUT existente
  (`brand_router.py:96-98`).
- Detalle FastAPI: `UploadFile` y `authorize_admin_request(request,
  ...)` conviven sin problemas; el handler sigue declarando `request:
  Request` como parámetro adicional al `file: UploadFile`.

## 6. Heads-up working tree

`git status --short` muestra 49 archivos modificados/untracked. Filtrando
por el scope de la feature 10:

### Archivos del scope con cambios PENDIENTES (M = modified, ?? = untracked)

- **NINGUNO**. Los archivos directamente tocados por la feature 10
  están limpios:
  - `modules/configuration/transport/http/brand_router.py` — limpio.
  - `modules/configuration/transport/payloads/brand.py` — limpio.
  - `modules/configuration/application/use_cases/update_brand_settings.py`
    — limpio.
  - `modules/configuration/infrastructure/brand_repository.py` —
    limpio.
  - `modules/configuration/infrastructure/orm.py` — limpio.
  - `modules/rendering/infrastructure/runtime/branding.py` — limpio.
  - `modules/rendering/infrastructure/preparation.py` — limpio.
  - `modules/rendering/infrastructure/runtime/assets.py` — limpio.
  - `apps/api/app_factory.py` — **modificado** (registro de routers,
    el implementer tendrá que añadir `create_logo_upload_router` o
    extender `create_brand_router` aquí). El diff actual probablemente
    sea de otra feature en curso (history feature 12 o 9); el
    implementer debe reconciliar añadiendo su línea sin pisar las
    existentes.
  - `tests/integration/configuration/test_brand_router.py` — limpio.
- **Otros mods relevantes** (no rompen feature 10, pero hay que
  saberlo):
  - `feature_list.json` — modified (probablemente el listado de
    features ya está en estado actualizado por trabajos previos;
    revisar antes de marcar como `done`).
  - `modules/configuration/domain/__init__.py` — modified: añade
    exports de `social_templates_variables` (feature 9). NO afecta a
    `BrandSettings`, pero el implementer NO debe revertir esos
    exports.
  - `progress/current.md` y `progress/history.md` — modified
    (housekeeping; el implementer escribirá en `progress/impl_10_*.md`
    nuevo).

### Untracked notables

- `progress/explore_feature_9_social_templates_state.md` — explorer
  report de feature 9.
- `progress/impl_12_unescape_html_entities_everywhere.md` — implementer
  report de feature 12.
- `modules/publishing/infrastructure/adapters/platforms/pinterest.py` —
  parte de feature 8 (no toca feature 10).

### Conclusión heads-up

El working tree contiene cambios de varias features previas
(probablemente sin commits intermedios — patrón de Phase 2). El
implementer de feature 10 puede operar sobre los archivos del scope
**sin conflictos**, pero al final del trabajo el commit incluirá tanto
los nuevos cambios como el remanente acumulado de las features
anteriores. Si la regla "una feature por commit" se reactiva en Phase
4, hay riesgo de mezclar diffs — revisar con el leader antes de
cerrar.

## Resumen ejecutivo para el implementer

1. El payload Pydantic YA acepta `logo_object_key` e
   `intro_logo_object_key`. La afirmación de la feature de que están
   "rechazados por `extra='forbid'`" es incorrecta. La ampliación del
   PUT requiere CERO cambios — ya está hecho.
2. Lo que falta es:
   - **Nuevo endpoint multipart** `POST
     /v1/admin/agencies/{agency_id}/brand/logo` (primer endpoint
     multipart del proyecto, sin patrón previo a copiar).
   - **Cableado en rendering**: hacer que `prepare_cover_logo_image`
     prefiera `agency_brand_settings.logo_object_key` sobre
     `property.agency_logo_url`. Requiere:
     - Cargar el `BrandSettings` del agency en el path
       `frame_composition.py:_build_render_data` o pasarlo via
       `PropertyRenderData`.
     - Resolver el `object_key` a un Path local (sin S3 hoy, todo es
       filesystem).
     - Mantener fallback a `property.agency_logo_url` cuando
       `logo_object_key` es string vacío.
3. **NO existe S3** — la "subida a S3 con fallback FS" del acceptance
   se interpreta como "diseñar la firma para que en el futuro pueda
   conectarse a S3, pero implementar solo FS hoy".
4. **NO hay validación de uploads existente** — el implementer crea el
   primer helper (content_type + extensión + size).
5. Schema **no requiere migración**: las columnas existen como `Text
   NOT NULL DEFAULT ''`. Para "borrar" un logo se sobreescribe con
   string vacío vía PUT existente.
