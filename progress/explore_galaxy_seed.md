# MAPEO: Arquitectura Render Template 4Reels Backend (Galaxy Seed)

**Fecha**: 2026-05-18
**Scope**: Cómo se registra, persiste y sirve un render template desde DB a HTTP response.
**Operativo para**: Implementación de nueva migración `galaxy_render_template` + payload seed.

---

## 1. Tabla `render_templates` - Schema ORM

**Archivo**: `/opt/projects/4Reels-Backend/modules/configuration/infrastructure/orm.py:20-48`

```python
class RenderTemplateORM(Base):
    __tablename__ = "render_templates"

    template_id: Mapped[str] = mapped_column(Text, primary_key=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    preview_images: Mapped[list[dict]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'[]'::jsonb"),
    )
    layout_variant: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="classic"
    )
    reel_settings: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    poster_settings: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
```

**Columnas**:
- `template_id` (Text, PK): identificador único del template (ej: `classic`, `side_banner`, `galaxy`)
- `display_name` (Text): nombre para la UI (ej: `Classic`, `Side Banner`)
- `description` (Text): descripción larga del layout
- `status` (Text): `active` o `disabled` (filtro de selectabilidad)
- `sort_order` (Integer): orden en la lista frontend (0=clásico, 1=side_banner, etc.)
- `preview_images` (JSONB): array de `[{"kind": "preview", "image_url": "/assets/...", "alt": "..."}]`
- `layout_variant` (Text): discriminador para el renderer (validado en `SUPPORTED_LAYOUT_VARIANTS`)
- `reel_settings` (JSONB): config específica del renderer para video (width, fps, etc.)
- `poster_settings` (JSONB): config específica para poster/thumbnail
- `created_at`, `updated_at` (DateTime timezone): auditoría

**Sin constraint de enum**: `layout_variant` es Text libre; validación en `render_template_settings.py:SUPPORTED_LAYOUT_VARIANTS`.

---

## 2. Migration Inicial: Creación de Tabla

**Archivo**: `/opt/projects/4Reels-Backend/alembic/versions/20260513_0002_render_templates.py`

**Metadata**:
- `revision = "20260513_0002"`
- `down_revision = "20260501_0001"`
- Crea tabla + seed inicial `classic`
- Agrega FK en `agency_reel_defaults.render_template_id`, `reels.render_template_id`, `media_revisions.render_template_id`

**Upgrade**:
```python
op.create_table(
    "render_templates",
    sa.Column("template_id", sa.Text(), primary_key=True),
    sa.Column("display_name", sa.Text(), nullable=False),
    sa.Column("description", sa.Text(), nullable=False, server_default=""),
    sa.Column("status", sa.Text(), nullable=False, server_default="active"),
    sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    sa.Column(
        "preview_images",
        pg.JSONB(astext_type=sa.Text()),
        nullable=False,
        server_default=sa.text("'[]'::jsonb"),
    ),
    sa.Column("layout_variant", sa.Text(), nullable=False, server_default="classic"),
    sa.Column(
        "reel_settings",
        pg.JSONB(astext_type=sa.Text()),
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    ),
    sa.Column(
        "poster_settings",
        pg.JSONB(astext_type=sa.Text()),
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    ),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
)
```

Luego: `INSERT INTO render_templates (...) VALUES ('classic', 'Classic', 'The original 4Reels renderer layout and settings.', 'active', 0, '[]'::jsonb, 'classic', '{}'::jsonb, '{}'::jsonb, timezone('utc', now()), timezone('utc', now()))`

---

## 3. Migraciones de Seed de Templates

### 3.1 Seed Inicial: Side Banner

**Archivo**: `/opt/projects/4Reels-Backend/alembic/versions/20260513_0004_seed_side_banner_render_template.py`

**Metadata**:
- `revision = "20260513_0004"`
- `down_revision = "20260513_0003"`

**Upgrade**:
```sql
INSERT INTO render_templates (
    template_id, display_name, description, status, sort_order,
    preview_images, layout_variant, reel_settings, poster_settings,
    created_at, updated_at
) VALUES (
    'side_banner',
    'Side Banner',
    'Full-bleed photo with a top-left info panel, vertical status banner anchored on the right, and full-width agent/agency footer.',
    'active',
    1,
    '[]'::jsonb,
    'side_banner',
    '{}'::jsonb,
    '{}'::jsonb,
    timezone('utc', now()),
    timezone('utc', now())
) ON CONFLICT (template_id) DO NOTHING
```

**Downgrade**: `DELETE FROM render_templates WHERE template_id = 'side_banner' AND layout_variant = 'side_banner'`

### 3.2 Preview Image: Classic

**Archivo**: `/opt/projects/4Reels-Backend/alembic/versions/20260514_0002_classic_render_template_preview.py`

**Metadata**:
- `revision = "20260514_0002"`
- `down_revision = "20260514_0001"`

**Upgrade**: UPDATE `preview_images` de `classic` a:
```json
[{
  "kind": "preview",
  "image_url": "/assets/render-templates/classic-template.png",
  "alt": "Classic template preview"
}]
```

### 3.3 Preview Image: Side Banner

**Archivo**: `/opt/projects/4Reels-Backend/alembic/versions/20260515_0001_side_banner_render_template_preview.py`

**Metadata**:
- `revision = "20260515_0001"`
- `down_revision = "20260514_0007"`

**Upgrade**: UPDATE `preview_images` de `side_banner` a:
```json
[{
  "kind": "preview",
  "image_url": "/assets/render-templates/side-banner-template.png",
  "alt": "Side banner template preview"
}]
```

---

## 4. Repository: `RenderTemplateRepository`

**Archivo**: `/opt/projects/4Reels-Backend/modules/configuration/infrastructure/render_template_repository.py`

**Métodos**:

```python
class RenderTemplateRepository(ModuleRepository):
    def get(self, template_id: str) -> RenderTemplate | None:
        # SELECT columnas FROM render_templates WHERE template_id = :template_id
        # Retorna RenderTemplate domain object o None

    def list_all(self) -> tuple[RenderTemplate, ...]:
        # SELECT columnas FROM render_templates ORDER BY sort_order ASC, display_name ASC, template_id ASC
        # Retorna tuple ordenada de RenderTemplate

    def get_selectable(self, template_id: str) -> RenderTemplate | None:
        # Wrapper de get() que retorna None si status != "active"
```

**Mapeo de filas a domain**:
```python
def _row_to_template(row) -> RenderTemplate:
    return RenderTemplate(
        template_id=str(row.template_id or ""),
        display_name=str(row.display_name or ""),
        description=str(row.description or ""),
        status=str(row.status or ""),
        sort_order=int(row.sort_order or 0),
        preview_images=_preview_images(row.preview_images),  # JSONB -> tuple[RenderTemplatePreviewImage]
        layout_variant=str(row.layout_variant or "classic"),
        reel_settings=jsonb_to_mapping(row.reel_settings),  # JSONB -> dict
        poster_settings=jsonb_to_mapping(row.poster_settings),  # JSONB -> dict
        created_at=isoformat(row.created_at) or "",
        updated_at=isoformat(row.updated_at) or "",
    )
```

**Columnas mapeadas**: Todas las 11 del ORM.

---

## 5. Domain Value Objects

**Archivo**: `/opt/projects/4Reels-Backend/modules/configuration/domain/agency_settings.py:119-142`

```python
@dataclass(frozen=True, slots=True)
class RenderTemplatePreviewImage:
    kind: str
    image_url: str
    alt: str


@dataclass(frozen=True, slots=True)
class RenderTemplate:
    template_id: str
    display_name: str
    description: str
    status: str
    sort_order: int
    preview_images: tuple[RenderTemplatePreviewImage, ...]
    layout_variant: str
    reel_settings: Mapping[str, Any] = field(default_factory=dict)
    poster_settings: Mapping[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    @property
    def is_selectable(self) -> bool:
        return self.status == "active"
```

**Exportado en**: `/opt/projects/4Reels-Backend/modules/configuration/domain/__init__.py:1-75`

---

## 6. Transport HTTP: Router y Endpoints

**Archivo**: `/opt/projects/4Reels-Backend/modules/configuration/transport/http/render_templates_router.py`

**Endpoints**:

### 6.1 GET `/v1/admin/agencies/{agency_id}/render-templates`

**Líneas**: 44-79
**Retorna**:
```json
{
  "agency_id": "uuid",
  "current_template_id": "classic",
  "items": [
    {
      "template_id": "classic",
      "display_name": "Classic",
      "description": "...",
      "status": "active",
      "sort_order": 0,
      "preview_images": [
        {
          "kind": "preview",
          "image_url": "/assets/render-templates/classic-template.png",
          "alt": "Classic template preview"
        }
      ],
      "layout_variant": "classic",
      "selected": true
    },
    { /* side_banner */ },
    { /* galaxy */ }
  ]
}
```

**Use case**: `ListRenderTemplatesUseCase` → `uow.configuration.render_templates.list_all()` + resuelve `current_template_id` de `agency_reel_defaults.render_template_id`

**Filtrado**: `preview_images` se serializa como está (JSONB JSON array de objetos), sin filtración adicional.

### 6.2 PUT `/v1/admin/agencies/{agency_id}/render-template`

**Líneas**: 81-133
**Payload**: `{"template_id": "classic"}`
**Retorna**: 
```json
{
  "status": "saved",
  "agency_id": "uuid",
  "render_template": { /* RenderTemplate serializado */ }
}
```

**Use case**: `SelectRenderTemplateUseCase` → valida que existe y `is_selectable` → `upsert` en `agency_reel_defaults.render_template_id`

**Validaciones**:
- Template debe existir (404 si no)
- Template debe tener `status = "active"` (400 si no)

---

## 7. App Factory: Montura de Activos Estáticos

**Archivo**: `/opt/projects/4Reels-Backend/apps/api/app_factory.py:270-277`

```python
app.mount(
    "/assets/render-templates",
    StaticFiles(
        directory=resolved_workspace / "assets" / "render-templates",
        check_dir=False,
    ),
    name="render_template_assets",
)
```

**Ruta**: `/assets/render-templates/` apunta a `{workspace}/assets/render-templates/`

**Archivos esperados**:
- `classic-template.png` (referenciado en preview)
- `side-banner-template.png` (referenciado en preview)
- `galaxy-template.png` (para nueva migración preview)

**Incluido en router**: Línea 434-437, dentro de `_include_module_routers()`.

---

## 8. Cadena de Migraciones Alembic (HEAD ACTUAL)

**Comando**: `ls -1 /opt/projects/4Reels-Backend/alembic/versions/ | sort | tail -15`

```
20260501_0001_initial_schema.py
20260513_0002_render_templates.py
20260513_0003_add_property_accent_colors.py
20260513_0004_seed_side_banner_render_template.py
20260513_0005_automation_hold_quiet_skip.py
20260514_0001_include_pinterest_in_reel_defaults.py
20260514_0002_classic_render_template_preview.py
20260514_0003_reels_descriptions_override.py
20260514_0004_seed_default_social_templates.py
20260514_0005_seed_existing_agencies_with_ncs_music_tracks.py
20260514_0006_reels_music_id_override.py
20260514_0007_email_notifications.py
20260515_0001_side_banner_render_template_preview.py
20260515_0002_agency_outro_assets.py
20260515_0003_reels_photos_override.py
20260515_0004_reels_subtitles_override.py
20260515_0005_reels_manifest_override.py
20260517_0001_reels_auto_subtitles_snapshot.py
```

**HEAD ACTUAL** (sin descendientes): `20260517_0001_reels_auto_subtitles_snapshot.py`

**Metadatos**:
- `revision = "20260517_0001"`
- `down_revision = "20260515_0005"`

**Nueva migración `galaxy_render_template` debe tener**:
- `revision = "20260517_0002"` (o similar, según convenio de 4Reels)
- `down_revision = "20260517_0001"` (apunta al HEAD actual)

---

## 9. Archivo Untracked: Auto-Subtitles Snapshot

**Archivo**: `/opt/projects/4Reels-Backend/alembic/versions/20260517_0001_reels_auto_subtitles_snapshot.py`

**Estado**: YA COMMITEADO (no aparece en `git status` como untracked)

**Propósito**: Feature 41 — snapshot JSONB de subtítulos autogenerados

---

## 10. Tests de Templates

### 10.1 `test_render_templates_router.py`

**Archivo**: `/opt/projects/4Reels-Backend/tests/integration/configuration/test_render_templates_router.py`

**Tests clave**:

**Líneas 22-50**: `test_render_templates_list_returns_seeded_classic`
- Aserta: respuesta 200 con `current_template_id == "classic"`
- Aserta: `items[0]` es Classic con `template_id`, `display_name`, `preview_images`, `layout_variant`, `selected=True`

**Líneas 53-80**: `test_render_templates_list_includes_side_banner`
- Aserta: 2+ items en response
- Aserta: `items` incluyen `side_banner` con `display_name == "Side Banner"`, `sort_order == 1`, `layout_variant == "side_banner"`

**Líneas 110-131**: `test_render_template_select_persists_on_defaults`
- Prueba PUT `/agencies/{id}/render-template` con `template_id`
- Aserta: payload se persiste en `agency_reel_defaults.render_template_id`

**Líneas 134-157**: `test_render_template_select_rejects_unknown_or_disabled_template`
- Unknown → 404 `RENDER_TEMPLATE_NOT_FOUND`
- Disabled → 400 `RENDER_TEMPLATE_NOT_SELECTABLE`

**Helper**: `_insert_template()` (líneas 200-240) — inserta template custom en DB para tests

### 10.2 `test_render_template_assets.py`

**Archivo**: `/opt/projects/4Reels-Backend/tests/integration/apps_api/test_render_template_assets.py`

**Test**: `test_api_serves_classic_render_template_preview_asset` (líneas 13-36)
- GET `/assets/render-templates/classic-template.png`
- Aserta: 200, `content-type: image/png`

---

## 11. SUPPORTED_LAYOUT_VARIANTS (Constraint Validación)

**Archivo**: `/opt/projects/4Reels-Backend/modules/rendering/infrastructure/render_template_settings.py:23`

```python
SUPPORTED_LAYOUT_VARIANTS = frozenset({"classic", "side_banner"})
```

**Uso**: En `_resolve_render_template_settings()` valida que `layout_variant` está en el set. Si no:
- Log error
- Fall back a `layout_variant = "classic"`

**Para Galaxy**: necesitará agregar `"galaxy"` al frozenset.

---

## 12. Resumen Operativo: Cómo Crear Nueva Migración `galaxy_render_template`

### Paso 1: Migration Seed (20260517_0002)

**Archivo**: `alembic/versions/20260517_0002_seed_galaxy_render_template.py`

```python
revision = "20260517_0002"
down_revision = "20260517_0001"

def upgrade() -> None:
    op.execute("""
        INSERT INTO render_templates (
            template_id, display_name, description, status, sort_order,
            preview_images, layout_variant, reel_settings, poster_settings,
            created_at, updated_at
        ) VALUES (
            'galaxy',
            'Galaxy',
            '<description del layout galaxy>',
            'active',
            2,  # sort_order después de side_banner
            '[]'::jsonb,
            'galaxy',
            '{}'::jsonb,
            '{}'::jsonb,
            timezone('utc', now()),
            timezone('utc', now())
        ) ON CONFLICT (template_id) DO NOTHING
    """)

def downgrade() -> None:
    op.execute("""
        DELETE FROM render_templates
        WHERE template_id = 'galaxy'
          AND layout_variant = 'galaxy'
    """)
```

### Paso 2: Migration Preview (20260517_0003)

**Archivo**: `alembic/versions/20260517_0003_galaxy_render_template_preview.py`

```python
revision = "20260517_0003"
down_revision = "20260517_0002"

_GALAXY_PREVIEW_IMAGES = [
    {
        "kind": "preview",
        "image_url": "/assets/render-templates/galaxy-template.png",
        "alt": "Galaxy template preview",
    }
]

def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE render_templates "
            "SET preview_images = CAST(:preview_images AS jsonb), "
            "updated_at = timezone('utc', now()) "
            "WHERE template_id = 'galaxy'"
        ).bindparams(preview_images=json.dumps(_GALAXY_PREVIEW_IMAGES))
    )

def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE render_templates "
            "SET preview_images = '[]'::jsonb, "
            "updated_at = timezone('utc', now()) "
            "WHERE template_id = 'galaxy' "
            "AND preview_images = CAST(:preview_images AS jsonb)"
        ).bindparams(preview_images=json.dumps(_GALAXY_PREVIEW_IMAGES))
    )
```

### Paso 3: Asset File

**Archivo**: `assets/render-templates/galaxy-template.png`
- PNG 300x300 px (mismo tamaño que classic/side_banner)

### Paso 4: Actualizar SUPPORTED_LAYOUT_VARIANTS

**Archivo**: `modules/rendering/infrastructure/render_template_settings.py:23`

```python
SUPPORTED_LAYOUT_VARIANTS = frozenset({"classic", "side_banner", "galaxy"})
```

### Paso 5: Tests

Extender `test_render_templates_router.py`:
```python
def test_render_templates_list_includes_galaxy() -> None:
    # Similar a side_banner test
    # Aserta: "galaxy" en items, sort_order=2, layout_variant="galaxy"
```

---

## RESUMEN FINAL

| Componente | Path | Notas |
|-----------|------|-------|
| ORM Table | `modules/configuration/infrastructure/orm.py:20` | RenderTemplateORM, 11 columnas, no constraint enum |
| Initial Migration | `alembic/versions/20260513_0002_render_templates.py` | Crea tabla + seed classic |
| Side Banner Seed | `alembic/versions/20260513_0004_seed_side_banner_render_template.py` | Template row 2, sort_order=1 |
| Preview Images | `20260514_0002`, `20260515_0001` | UPDATE preview_images JSONB con arrays de objetos |
| Repository | `modules/configuration/infrastructure/render_template_repository.py` | get(), list_all(), get_selectable() |
| Domain | `modules/configuration/domain/agency_settings.py:119-142` | RenderTemplate + RenderTemplatePreviewImage dataclass |
| Router | `modules/configuration/transport/http/render_templates_router.py` | GET/PUT endpoints, serialización con `_serialize_template()` |
| App Factory | `apps/api/app_factory.py:270-277` | StaticFiles mount `/assets/render-templates/` |
| HEAD Migration | `20260517_0001_reels_auto_subtitles_snapshot.py` | Nueva galaxy debe apuntar `down_revision="20260517_0001"` |
| Layout Validation | `modules/rendering/infrastructure/render_template_settings.py:23` | SUPPORTED_LAYOUT_VARIANTS frozenset (agregar "galaxy") |
| Tests | `test_render_templates_router.py`, `test_render_template_assets.py` | Asertos de count, fields, slug, preview_images |

