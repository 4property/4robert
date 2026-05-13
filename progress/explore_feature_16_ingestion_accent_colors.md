# Explore — Feature 16 `side_banner_render_template_with_accent_colors`

> Mapa de ingesta y threading de dos campos nuevos del webhook WordPress
> hacia el renderer FFmpeg + poster: `wppd_accent_text_color` y 
> `wppd_accent_background_color` (HEX strings). Incluye resolución de
> fallback a `BrandSettings.primary_color` y validación HEX.

Contexto: El usuario quiere soportar un nuevo render template "side_banner"
cuyos colores de acento se derivan de dos campos webhook que no existen aún
en el codebase. La cadena debe ir desde webhook → Property domain → ORM +
migración Alembic → PropertyRenderData → FFmpeg filter graph + poster.

---

## 1. Modelo Property (catalog domain)

### Fichero: `/opt/projects/4Reels-Backend/modules/catalog/domain/wordpress_property.py`

**Línea ~99** (final de dataclass fields, antes de `raw_data`):
Añadir dos campos nuevos:
```python
wppd_accent_text_color: str | None = None
wppd_accent_background_color: str | None = None
```

**Línea ~102** (en `Property.from_api_payload`):
Extraer y coercionar con `to_text()`:
```python
wppd_accent_text_color=to_text(payload.get("wppd_accent_text_color")),
wppd_accent_background_color=to_text(payload.get("wppd_accent_background_color")),
```

### Fichero: `/opt/projects/4Reels-Backend/modules/catalog/domain/_property_conversions.py`

**Línea ~186** (`build_property_db_record`):
Añadir dos entradas al dict retornado (colocadas antes de `"image_folder"`, ~línea 251):
```python
"wppd_accent_text_color": p.wppd_accent_text_color,
"wppd_accent_background_color": p.wppd_accent_background_color,
```

**Línea ~258** (`build_property_dict`):
Idem en el dict serialización:
```python
"wppd_accent_text_color": p.wppd_accent_text_color,
"wppd_accent_background_color": p.wppd_accent_background_color,
```

### Decisión: ¿Validación HEX?

**NO en Property.from_api_payload**. El coercionar con `to_text()` preserva el valor crudo
del webhook. La **validación HEX** pertenece a la capa transport/HTTP (payloads Pydantic)
si fuera un endpoint de admin, o al rendering si viene de webhook. Aquí se ingesta pasivamente.

**Discovery**: No existe validador HEX reutilizable en el codebase. Los colores
`primary_color`, `secondary_color` en BrandSettings se documentan en payloads con
`description="...Hex string."` (línea ~34-40 de `brand.py`) pero no validan regex.
Propuesta: Crear helper `is_valid_hex_color(value: str) -> bool` en 
`shared/errors/validation.py` o `modules/configuration/domain/_color_validators.py`.

---

## 2. ORM + Migración Alembic

### Fichero: `/opt/projects/4Reels-Backend/modules/catalog/infrastructure/orm.py`

**Línea ~104** (antes de `property_type_ids` o después de `wppd_parent_id`):
Añadir dos columnas en `PropertyORM`:
```python
wppd_accent_text_color: Mapped[str | None] = mapped_column(Text)
wppd_accent_background_color: Mapped[str | None] = mapped_column(Text)
```

Ambas son nullable, sin server_default. Si el webhook no las envía, quedan `NULL`.

### Fichero: `/opt/projects/4Reels-Backend/alembic/versions/` (nuevo)

**Nombrado**: `20260513_0003_add_property_accent_colors.py` (secuencial)

Patrón observado en `20260513_0002_render_templates.py`:
- Usar `op.add_column()` para cada field.
- Nullable Text columns sin defaults.
- `downgrade()` hace `op.drop_column()`.

**Contenido mínimo**:
```python
def upgrade() -> None:
    op.add_column(
        "properties",
        sa.Column("wppd_accent_text_color", sa.Text(), nullable=True),
    )
    op.add_column(
        "properties",
        sa.Column("wppd_accent_background_color", sa.Text(), nullable=True),
    )

def downgrade() -> None:
    op.drop_column("properties", "wppd_accent_background_color")
    op.drop_column("properties", "wppd_accent_text_color")
```

### Verificación: ¿Columnas "reservadas" ya?

Búsqueda: `PropertyORM` no tiene columnas `accent*` ni `color*` excepto
implícitamente en `raw_json` (JSONB que almacena el webhook completo).
**Sin conflictos.**

---

## 3. PropertyRenderData (rendering)

### Fichero: `/opt/projects/4Reels-Backend/modules/rendering/infrastructure/models.py`

**Línea ~139** (antes de cierre de `PropertyRenderData` dataclass):
Añadir dos fields (nullable):
```python
accent_text_color: str | None = None
accent_background_color: str | None = None
```

Ubicación exacta: después de `viewing_times` (línea ~138), antes del cierre.

---

## 4. PropertyContext → PropertyRenderData (frame_composition bridge)

### Fichero: `/opt/projects/4Reels-Backend/modules/rendering/application/frame_composition.py`

**Línea ~100-198** (`DefaultMediaRenderer._build_render_data`):

Actual retorna:
```python
return PropertyRenderData(
    site_id=...,
    property_id=...,
    # ... otros fields
    viewing_times=tuple(selected_slides),
)
```

Hay que threadear los dos campos nuevos de `context.property`:
```python
accent_text_color=context.property.wppd_accent_text_color or _resolve_fallback_accent_text_color(
    context=context,
),
accent_background_color=context.property.wppd_accent_background_color or _resolve_fallback_accent_background_color(
    context=context,
),
```

Helper privado (nueva función static al final del fichero, ~línea 200):
```python
@staticmethod
def _resolve_fallback_accent_text_color(context: PropertyContext) -> str | None:
    # Si viene del webhook, usar ese. Si no, usar BrandSettings.primary_color.
    # Ver §5 para carga de BrandSettings.
    ...

@staticmethod
def _resolve_fallback_accent_background_color(context: PropertyContext) -> str | None:
    ...
```

**PROBLEMA ACTUAL**: `DefaultMediaRenderer` NO tiene acceso a `BrandSettings` en su
constructor ni a través de `context`. Necesita inyección o lookup en frame_composition.

---

## 5. Resolución del fallback (BrandSettings)

### Descubrimiento: ¿Dónde se carga BrandSettings durante render?

**Búsqueda exhaustiva**:
- `DefaultMediaRenderer` se construye en `apps/worker/runtime.py` o in-flight.
  No recibe `BrandSettings` explícitamente.
- `PropertyContext` (línea ~262 de `reels/domain/types.py`) incluye:
  - `workspace_dir`
  - `storage_paths`
  - `tenant` (TenantContext)
  - `property` (Property)
  - Render template settings (`render_template_reel_settings`, `render_template_poster_settings`)
  - **NO incluye `BrandSettings`**.

**Ubicación actual de BrandSettings**:
- Domain: `/opt/projects/4Reels-Backend/modules/configuration/domain/agency_settings.py` (línea ~18).
- Carga: `/opt/projects/4Reels-Backend/modules/configuration/infrastructure/brand_repository.py`.
- Uso típico: `/opt/projects/4Reels-Backend/modules/configuration/application/use_cases/read_aggregated_reel_profile.py`
  (línea ~27: "brand_primary = brand.primary_color if brand is not None else "#0F172A"").

### Decisión arquitectónica:

**Opción A** (Clean): Extender `PropertyContext.render_template_reel_settings` para incluir
`"fallback_accent_text_color"` y `"fallback_accent_background_color"`, poblados desde
`BrandSettings` **en el sitio donde se construye PropertyContext**
(`modules/reels/application/use_cases/ingest_property_into_reel.py`, línea ~130).

**Opción B** (Simple): En `frame_composition._build_render_data()`, hacer lookup directo
de `BrandSettings` usando `agency_id` desde `context.tenant.agency_id`. Requiere acceso
a UoW o repository inyectado.

**Recomendación**: **Opción A** es más limpia y sigue el patrón ya establecido de pasar
settings pre-resueltos en render_template_reel_settings. Ver §4.1 abajo.

### Fichero: `/opt/projects/4Reels-Backend/modules/reels/application/use_cases/ingest_property_into_reel.py`

**Línea ~153-157** (donde se resuelve render_template_settings):

Tras `_resolve_render_template_settings()`, enriquecer `render_template_reel_settings`
con los fallbacks:
```python
render_template_settings = self._resolve_render_template_settings(...)

# Enrich with brand fallback colors
brand = uow.configuration.brands.get(agency_id=job.tenant.agency_id)
fallback_accent_text_color = brand.primary_color if brand else "#0F172A"
fallback_accent_background_color = brand.primary_color if brand else "#FFFFFF"

render_template_reel_settings = dict(render_template_settings.reel_template_dict)
render_template_reel_settings.setdefault("fallback_accent_text_color", fallback_accent_text_color)
render_template_reel_settings.setdefault("fallback_accent_background_color", fallback_accent_background_color)
```

Luego usar estos en `PropertyContext(..., render_template_reel_settings=render_template_reel_settings)`.

### Verificación: ¿Existe `uow.configuration.brands`?

**Búsqueda**: `/opt/projects/4Reels-Backend/shared/db/uow.py` + 
`/opt/projects/4Reels-Backend/modules/configuration/infrastructure/` →
Sí existe `brand_repository.py` con método `get(agency_id)`.
Necesita verificar que el UoW lo exponga. (Típicamente lo hace como `uow.configuration.brands`.)

---

## 6. Validación HEX (helpers)

### Fichero: Nuevo o existente `/opt/projects/4Reels-Backend/shared/errors/validation.py` (o módulo configuration.domain)

No hay validador HEX actual. Propuesta:

```python
import re

def is_valid_hex_color(value: str | None) -> bool:
    """True if value is a 3/4/6/8-digit hex color (with optional #)."""
    if value is None:
        return True  # nullable = valid
    clean = value.lstrip("#")
    return bool(re.match(r"^[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?$|^[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$", clean))
```

**Ubicación de uso** (3 sitios):
1. **Transport/Pydantic** (si se añade endpoint para editar colores de propiedad):
   Validador de campo en payload Pydantic. Ejemplo: 
   `/opt/projects/4Reels-Backend/modules/configuration/transport/payloads/brand.py` (línea ~32-35).

2. **Rendering** (opcional): Antes de construir PropertyRenderData, log warning si inválido.

3. **Tests**: Casos de validación HEX con colores inválidos.

---

## 7. Tests

### Tests existentes que necesitan extensión:

1. **`/opt/projects/4Reels-Backend/tests/unit/ingestion/test_ingest_wordpress_property.py`**
   (línea ~18 en adelante):
   - Extender `test_ingest_wordpress_property_enqueues_job_with_provider_secret_bundle()`
     para incluir `"wppd_accent_text_color": "#e22f8c"` en el payload.
   - Verificar que se roundtrips en Property.from_api_payload y build_property_db_record.

2. **`/opt/projects/4Reels-Backend/tests/unit/rendering/test_render_template_settings.py`**
   (línea ~40 en adelante):
   - Extender para probar que fallback_accent_* se inyectan en render_template_reel_settings.

3. **`/opt/projects/4Reels-Backend/tests/integration/reels/test_ingest_property_into_reel_flow.py`**
   (si existe):
   - End-to-end: webhook con colores → Property → PropertyContext.render_template_reel_settings.

### Tests nuevos:

1. **`tests/unit/catalog/test_property_from_api_payload_accent_colors.py`**:
   ```python
   def test_property_from_api_payload_extracts_accent_colors():
       payload = {
           "id": 123,
           "wppd_accent_text_color": "#e22f8c",
           "wppd_accent_background_color": "#ffffff",
           ...
       }
       prop = Property.from_api_payload(payload)
       assert prop.wppd_accent_text_color == "#e22f8c"
       assert prop.wppd_accent_background_color == "#ffffff"

   def test_property_from_api_payload_accent_colors_nullable():
       payload = {"id": 123}  # no accent colors
       prop = Property.from_api_payload(payload)
       assert prop.wppd_accent_text_color is None
       assert prop.wppd_accent_background_color is None
   ```

2. **`tests/unit/rendering/test_frame_composition_accent_colors.py`**:
   ```python
   def test_build_render_data_uses_property_accent_colors():
       context = _context_with_property(
           wppd_accent_text_color="#e22f8c",
           wppd_accent_background_color="#ffffff"
       )
       render_data = DefaultMediaRenderer._build_render_data(
           context=context,
           prepared_assets=...,
           selected_slides=...
       )
       assert render_data.accent_text_color == "#e22f8c"
       assert render_data.accent_background_color == "#ffffff"

   def test_build_render_data_falls_back_to_brand_primary_when_missing():
       context = _context_with_property(
           wppd_accent_text_color=None,
           wppd_accent_background_color=None
       )
       context.render_template_reel_settings = {
           "fallback_accent_text_color": "#0F172A",
           "fallback_accent_background_color": "#FFFFFF"
       }
       render_data = DefaultMediaRenderer._build_render_data(...)
       assert render_data.accent_text_color == "#0F172A"
       assert render_data.accent_background_color == "#FFFFFF"
   ```

3. **`tests/unit/shared/test_hex_color_validation.py`**:
   ```python
   def test_is_valid_hex_color():
       assert is_valid_hex_color("#e22f8c") is True
       assert is_valid_hex_color("#fff") is True
       assert is_valid_hex_color("e22f8c") is True
       assert is_valid_hex_color("#xyz") is False
       assert is_valid_hex_color(None) is True
   ```

---

## Tabla de cambios necesarios

| Fichero | Línea aprox. | Naturaleza del cambio | 
|---------|--------------|----------------------|
| `modules/catalog/domain/wordpress_property.py` | 99 | Añadir 2 fields: `wppd_accent_text_color`, `wppd_accent_background_color` (str \| None) |
| `modules/catalog/domain/wordpress_property.py` | 102 | Población en `from_api_payload()` con `to_text(payload.get(...))` |
| `modules/catalog/domain/_property_conversions.py` | 186 (build_property_db_record) | Incluir 2 fields en dict retornado |
| `modules/catalog/domain/_property_conversions.py` | 258 (build_property_dict) | Incluir 2 fields en dict retornado |
| `modules/catalog/infrastructure/orm.py` | 104-110 | Añadir 2 mapped_column: `wppd_accent_text_color`, `wppd_accent_background_color` (Text, nullable) |
| `alembic/versions/20260513_0003_add_property_accent_colors.py` | NEW | Migración upgrade/downgrade para 2 columnas nuevas |
| `modules/rendering/infrastructure/models.py` | 139 | Añadir 2 fields a `PropertyRenderData`: `accent_text_color`, `accent_background_color` (str \| None = None) |
| `modules/rendering/application/frame_composition.py` | 160-198 (_build_render_data) | Thread 2 fields desde `context.property` y fallback lookup |
| `modules/rendering/application/frame_composition.py` | 200+ | Nuevos helpers: `_resolve_fallback_accent_text_color()`, `_resolve_fallback_accent_background_color()` |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | 153-157 | Enriquecer `render_template_reel_settings` con `fallback_accent_*` desde BrandSettings |
| `shared/errors/validation.py` (o new) | NEW | Añadir `is_valid_hex_color(value: str \| None) -> bool` |

---

## Riesgos y sorpresas encontradas

### 1. **Property.raw_data preserva TODO el payload** 
Ya existe un campo `raw_json` (JSONB) en `properties` que almacena la copia del webhook completo.
Los dos campos nuevos van a viajar automáticamente en `raw_json` sin necesidad de 
migración de schema adicional. **PERO** el usuario quiere acceso **directo** a estos
campos en frame_composition, no vía JSON parsing de raw_json, por lo que sí necesita
columnas explícitas para eficiencia.

### 2. **BrandSettings no está en PropertyContext**
El fallback a `BrandSettings.primary_color` requiere un lookup explícito o pre-carga
en el contexto de render. Propuesta: enriquecer `render_template_reel_settings` en
`ingest_property_into_reel.py` ya que es donde se resuelven los settings globales
(ver §5).

### 3. **No existe validador HEX reutilizable**
El codebase documenta que colores son "Hex string" pero no valida. Propuesta: crear
helper `is_valid_hex_color()` en `shared/` y usarlo en tests + warnings de logging.
La entrada/validación en HTTP payloads (si aplica) vendría después.

### 4. **Fallback: ¿primary_color o secondary_color?**
Usuario especificó: fallback = `BrandSettings.primary_color` para ambos colores.
Alternativa observada en codebase: text=`primary_color` (#0F172A dark blue), 
background=`secondary_color` (#FFFFFF white). Usar la decisión del usuario (primary
para ambos) pero documentar en comentarios del código.

---

## Flujo end-to-end (resumen)

```
1. Webhook WordPress llega con:
   {
     "id": 42,
     "wppd_accent_text_color": "#e22f8c",
     "wppd_accent_background_color": "#ffffff",
     ...
   }

2. ingestion.ingest_wordpress_property.py → 
   Property.from_api_payload(payload)
   → Property.wppd_accent_text_color = "#e22f8c" ✓
   
3. ingest_property_into_reel.py →
   _build_property_record() →
   property_repository.upsert_property() →
   PropertyORM.wppd_accent_text_color = "#e22f8c" ✓

4. ingest_property_into_reel.py (enrichment) →
   render_template_reel_settings["fallback_accent_text_color"] = BrandSettings.primary_color ✓

5. PropertyContext(
     property=Property(...),
     render_template_reel_settings={...with fallback...}
   ) ✓

6. frame_composition.DefaultMediaRenderer._build_render_data() →
   PropertyRenderData(
     accent_text_color=context.property.wppd_accent_text_color or fallback,
     accent_background_color=context.property.wppd_accent_background_color or fallback,
   ) ✓

7. FFmpeg filter graph + poster generador usa:
   PropertyRenderData.accent_text_color (#e22f8c)
   PropertyRenderData.accent_background_color (#ffffff)
```

