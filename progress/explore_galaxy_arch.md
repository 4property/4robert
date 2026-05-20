# Arquitectura del Template `side_banner` — Mapa para Implementer de `galaxy`

> Volcado por leader: el explorer respondió con el contenido inline en lugar de escribirlo.
> Conservado verbatim. Cualquier `:line` puede tener drift de ±5 líneas; verificar antes de editar.

## 1. Layout Variant Enum / Discriminador

**Declaración:**
- `modules/rendering/infrastructure/render_template_settings.py:23`
  ```python
  SUPPORTED_LAYOUT_VARIANTS = frozenset({"classic", "side_banner"})
  ```

**Campo en DB (ORM):**
- `modules/configuration/infrastructure/orm.py:33-35`
  ```python
  layout_variant: Mapped[str] = mapped_column(
      Text, nullable=False, server_default="classic"
  )
  ```

**Campo en Dominio (RenderTemplate):**
- `modules/rendering/infrastructure/render_template_settings.py:167-171` (resolución)
- `modules/configuration/infrastructure/render_template_repository.py:58` (carga desde DB)

**Para `galaxy`:** agregar `"galaxy"` a `SUPPORTED_LAYOUT_VARIANTS`. El campo en DB ya es genérico.

---

## 2. Pipeline de Render Condicionado por layout_variant

### `modules/rendering/infrastructure/ffmpeg/filters.py`
- **L136:** `if layout_variant == "side_banner"` → footer panel con esquina redondeada vía `_build_rounded_panel_source`.
- **L68-78:** `_resolve_side_banner_footer_radius`: `radius = min(panel_width//2, panel_height//2, max(12, round(frame_height * 0.0125)))`. Mín 12px.
- **L345-362:** ribbon vertical overlay con notch triangular, posición `vertical_banner_x/y`, label `vertical_banner_label`.
- **L213-228:** font resolution (family/weight) desde `subtitle_style` con fallback `subtitle_font_path` (feature 28).

### `modules/rendering/infrastructure/preparation.py`
- **L197-218:** si `layout_variant == "side_banner"` genera PNG del ribbon vertical vía `_render_vertical_status_banner` (rotación 90° con drawtext).
- **L210:** consume `side_banner_ribbon_background_color` de `PropertyRenderData` (feature 29). Fallback `#9CA3AF` en L248.
- **L251-277:** `_resolve_vertical_banner_layout` calcula dimensiones del ribbon.
- **L317-318:** `font_size = max(20, round(horizontal_height * 0.40))`, `text_down_shift = max(10, round(width * 0.18))`.

### `modules/rendering/infrastructure/layout/panels.py`

**Top panel — `compose_top_panel` (L90-276):**
- L96: `side_text_x = max(panel_padding_x, round(width * 0.086))`
- L97: `side_ber_x = round(width * 0.36)`
- L106-111: fontsize bounds más grandes (status 20-24, price 32-48, address 24-34).
- L144-145: status hardcoded a "OFFERS OVER:" cuando hay precio (gap #1 de feature 16).
- L206-214: `top_panel_height = max(round(height * 0.211), calc)`; `top_panel_y = round(height * 0.058)`.
- L257-261: BER badge alineado con `address_meta` (gap #3).

**Bottom panel — `compose_bottom_panel` (L279-536):**
- L306: agent image size `min(template, max(128, round(height * 0.089)))`.
- L311-312: `logo_box_width = max(220, round(width * 0.31))`, `logo_box_height = max(78, round(height * 0.062))`.
- L315: `effective_panel_width = round(width * 0.94)`.
- L317-318: paddings `max(panel_padding_x, round(width * 0.082))`, `max(18, round(height * 0.012))`.
- L366-375: font bounds (agent_name 20-26, contact 18-24).
- L442-445: `bottom_panel_height = max(round(height * 0.113), calc)`.
- L453-455: `bottom_panel.x = round(width * 0.030)`, `bottom_panel.y = round(height * 0.781)`.
- L472-474: agent_image_box anclado a `bottom_panel.x + footer_padding_x`.
- L484-489: agency_logo_box anclado a la derecha.
- L500-501: `text_x = round(width * 0.267)` si hay agent image.
- L506-508: `cursor_y = max(footer_padding_y, round(height * 0.030))`.

### `modules/rendering/infrastructure/layout/composition.py`
- **L44-60:** `outer_margin_x/y = 0` para side_banner (full-bleed) vs máximos para classic.

### `modules/rendering/application/frame_composition.py`
- **L139, L154, L177, L212:** propagación de `layout_variant` a `prepare_reel_render_assets`, `build_filter_complex`, `build_overlay_layout`.

---

## 3. Geometría side_banner (Constantes Numéricas)

### Banner vertical (Ribbon, preparation.py:251-277)
```
banner_width  = max(96,  round(width  * 0.122))     # ~12.2% ancho
notch_height  = max(28,  round(height * 0.025))     # ~2.5% alto
body_height   = max(420, round(height * 0.325))     # ~32.5% alto
banner_height = body_height + notch_height
banner_x      = min(width - banner_width, max(0, round(width * 0.778)))  # 77.8% izda
banner_y      = 0
font_size     = max(20, round(body_height * 0.40))
text_shift    = max(10, round(width * 0.18))
```

### Top panel
```
top_panel_y      = round(height * 0.058)
top_panel_height = max(round(height * 0.211), calc)
content_offset_y = max(panel_padding_y, round(height * 0.081))
```

### Bottom panel
```
bottom_panel_y      = round(height * 0.781)
bottom_panel_height = max(round(height * 0.113), calc)
bottom_panel_x      = round(width  * 0.030)
effective_width     = round(width  * 0.94)
```

### Footer radius
```
radius = min(panel_width//2, panel_height//2, max(12, round(frame_height * 0.0125)))
```

### Fonts
- status 20-24px, price 32-48px, address 24-34px (top)
- agent_name 20-26px, contact 18-24px (bottom)

---

## 4. Render Template Repository

`modules/configuration/infrastructure/render_template_repository.py` — schema `render_templates`:

```
template_id      Text PK
display_name     Text
description      Text default ""
status           Text default "active"
sort_order       Integer default 0
preview_images   JSONB default '[]'
layout_variant   Text default "classic"
reel_settings    JSONB default '{}'
poster_settings  JSONB default '{}'
created_at       DateTime
updated_at       DateTime
```

Métodos: `get(template_id)`, `list_all()`, `get_selectable(template_id)` (filtra status="active").
Conversión DB→Dominio L50-63; `layout_variant` con fallback `"classic"` L58.

---

## 5. Seeds Alembic side_banner

### `alembic/versions/20260513_0004_seed_side_banner_render_template.py`
```
revision = "20260513_0004"
down_revision = "20260513_0003"
```
INSERT con `template_id='side_banner'`, `display_name='Side Banner'`, `sort_order=1`, `layout_variant='side_banner'`, JSONs vacíos. Downgrade protegido por `WHERE layout_variant='side_banner'`.

### `alembic/versions/20260515_0001_side_banner_render_template_preview.py`
```
revision = "20260515_0001"
down_revision = "20260514_0007"
```
UPDATE de `preview_images` con `[{kind:"preview", image_url:"/assets/render-templates/side-banner-template.png", alt:"Side banner template preview"}]`.

**Para galaxy:** dos migrations análogas con `sort_order=2`.

---

## 6. Tests específicos de side_banner

- `tests/integration/rendering/test_side_banner_render.py` — propagación end-to-end (mockea ffmpeg).
- `tests/unit/rendering/test_layout_composition_side_banner.py` — geometría panels, font sizes, BER alignment, logo dcha, footer radius.
- `tests/unit/rendering/test_frame_composition_accent_colors.py` — cascada `side_banner_ribbon_background_color`, `side_banner_panel_color`, fallbacks.
- `tests/unit/rendering/test_preparation_side_banner_ribbon_hardcode.py` — banner vertical, dims, notch, color overrides.
- `tests/unit/rendering/test_side_banner_panel_color_cascade.py` — `BrandSettings.primary_color` → panels.

---

## 7. Asset Preview y Serving

Filesystem: `assets/render-templates/classic-template.png`, `side-banner-template.png`.

Mount HTTP (`apps/api/app_factory.py:270-277`):
```python
app.mount(
    "/assets/render-templates",
    StaticFiles(directory=resolved_workspace / "assets" / "render-templates", check_dir=False),
    name="render_template_assets",
)
```

Referencia en DB: `preview_images` JSONB con shape `[{kind, image_url, alt}]`.

**Para galaxy:** crear `assets/render-templates/galaxy-template.png` + migration UPDATE.

---

## 8. Compatibilidad con otras features

| Feature | Estado para galaxy |
|---|---|
| 28 font_catalog | Heredar resolución family/weight de `filters.py:213-228`. Sin cambios. |
| 29 secondary_color_side_banner | Si galaxy usa ribbon, consumir `side_banner_ribbon_background_color` (o renombrar como `accent_*`). Decisión de naming. |
| Hotfix side_banner_panel_color | Si galaxy dibuja panels, consumir `side_banner_panel_color`. Decisión de naming. |
| 35 photos_override | Heredar ORM field. Sin cambios. |
| 36 subtitles_override | Heredar `PropertyRenderData.subtitles_override`. Sin cambios. |
| 37 manifest_override | Heredar `manifest_override`. Sin cambios. |

---

## Resumen para implementer

1. Enum: `"galaxy"` a `SUPPORTED_LAYOUT_VARIANTS`.
2. Migration seed (sort_order=2) + migration preview.
3. Asset PNG `galaxy-template.png`.
4. `panels.py`: ramas `is_galaxy = layout_variant == "galaxy"` para top/bottom panel con la geometría propia.
5. `filters.py`: ramas `galaxy` si dibuja elementos especiales (footer redondeado, big logo circle, ribbon).
6. `preparation.py`: si galaxy dibuja un PNG pre-compuesto (p.ej. círculo grande o ribbon), helper análogo a `_render_vertical_status_banner`.
7. Tests: `test_layout_composition_galaxy.py`, `test_galaxy_render.py`, geometría + cascade de colores.
8. Transport: ningún cambio (el router es genérico).
