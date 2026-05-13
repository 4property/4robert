# Feature 16 — Side Banner Render Template (master plan)

> **Owner**: leader · **Created**: 2026-05-13
> **Sub-spikes**:
> - `progress/explore_feature_16_ingestion_accent_colors.md` (catalog → ORM → migración → PropertyRenderData + fallback BrandSettings + tests)
> - `progress/explore_feature_16_layout_side_banner.md` (layout system, banner rotado, colores parametrizables, full-bleed, seed migration)

## Resumen

Añadir un segundo render template (`template_id="side_banner"`, `layout_variant="side_banner"`) además del `classic` actual. Características visuales (derivadas del análisis de `example-new-template.png`):

1. Foto **full-bleed** (sin márgenes externos).
2. Panel superior rectangular anclado arriba-izquierda, ~60-70% ancho.
3. **Banner vertical** pegado al borde derecho, texto dinámico (`build_status_ribbon_text`) rotado 90° (PIL pre-render + overlay ffmpeg).
4. Panel inferior full-width con foto agente circular + tarjeta blanca con logo agencia a la derecha.
5. Colores derivados por-propiedad de los campos webhook `wppd_accent_text_color` / `wppd_accent_background_color` con **alpha overlay** (~0.85) para "rebajar". Fallback: `BrandSettings.primary_color` de la agencia.

Aplica a **reel MP4 + poster JPG** (mismo `build_overlay_layout` se reutiliza en ambos).

## Decisiones de diseño (alineadas con el usuario)

| Eje | Decisión |
|---|---|
| Alcance | Reel + poster (mismo layout_variant) |
| Tonado color | Alpha overlay `@0.85` en drawbox |
| Banner texto | Dinámico vía `build_status_ribbon_text(property_data)` |
| Fallback color | `BrandSettings.primary_color` (con fallback secundario a `#0F172A` / `#FFFFFF` si tampoco hay brand settings) |
| Naming | `template_id="side_banner"`, `display_name="Side Banner"`, `layout_variant="side_banner"` |
| Backlog | Feature 16 en `feature_list.json` Phase 4 |

## Subtareas ordenadas (orden serial para minimizar riesgo)

### 16-A · Schema + ingestion accent colors
- Migración alembic `20260513_0003_add_property_accent_colors.py`:
  upgrade añade `properties.wppd_accent_text_color` y `properties.wppd_accent_background_color` (Text nullable); downgrade dropea ambas.
- `modules/catalog/infrastructure/orm.py:104+`: dos `mapped_column(Text)` nullable.
- `modules/catalog/domain/wordpress_property.py:88+`: dos fields `str | None = None` en `Property` + extracción `to_text(payload.get("wppd_accent_*"))` en `from_api_payload`.
- `modules/catalog/domain/_property_conversions.py`: incluir en `build_property_db_record` y `build_property_dict`.
- Tests unit: `tests/unit/catalog/test_property_from_api_payload_accent_colors.py` (presente + nullable).
- Tests integration: extender `tests/unit/reels/test_ingest_property_into_reel.py` con payload que incluya colores.
- Verificación: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` verde en DB limpia.

### 16-B · Render template `side_banner` (config + seed)
- `modules/rendering/infrastructure/render_template_settings.py:22`: `SUPPORTED_LAYOUT_VARIANTS = frozenset({"classic", "side_banner"})`.
- Migración alembic `20260513_0004_seed_side_banner_render_template.py` con `INSERT INTO render_templates ... ON CONFLICT DO NOTHING` para fila `side_banner` (display_name="Side Banner", status="active", sort_order=1, layout_variant="side_banner", reel_settings={}, poster_settings={}). Downgrade hace `DELETE WHERE template_id='side_banner'`.
- Tests: extender `tests/unit/rendering/test_render_template_settings.py` para verificar que `"side_banner"` pasa validación.
- Tests integration: extender `tests/integration/configuration/test_render_templates_router.py` para verificar GET list incluye `side_banner` post-migración.

### 16-C · Threading accent colors hasta PropertyRenderData + fallback
- `modules/rendering/infrastructure/models.py:139`: dos fields `accent_text_color: str | None = None` y `accent_background_color: str | None = None` en `PropertyRenderData`.
- `modules/reels/application/use_cases/ingest_property_into_reel.py` (línea ~153 según spike): cargar `brand = uow.configuration.brands.get(agency_id=...)` (verificar nombre exacto del UoW; si el método no existe en UoW, hacer lookup vía `BrandRepository` directamente). Enriquecer `render_template_reel_settings` y `render_template_poster_settings` con dos claves de fallback:
  - `fallback_accent_text_color = brand.primary_color if brand else "#0F172A"`
  - `fallback_accent_background_color = brand.primary_color if brand else "#FFFFFF"`
  > Nota: el usuario eligió que ambos fallback caigan a `primary_color`. Documentar en comentario in-line.
- `modules/rendering/application/frame_composition.py:_build_render_data` (línea ~160-198): threadear `context.property.wppd_accent_*` a los campos nuevos de `PropertyRenderData`, con fallback a `render_template_reel_settings.get("fallback_accent_*")`.
- Tests unit: `tests/unit/rendering/test_frame_composition_accent_colors.py` (override property + fallback brand).

### 16-D · Rendering layout: branching por `layout_variant` + foto full-bleed
- `modules/rendering/infrastructure/layout/composition.py:26-43`: añadir kwarg `layout_variant: str = "classic"`. Si `=="side_banner"`, `outer_margin_x = outer_margin_y = 0`.
- `compose_top_panel` (panels.py): aceptar kwarg `top_panel_width_ratio: float = 1.0` (o equivalente). Cuando `layout_variant=="side_banner"`, reducir ancho del top panel a ~0.65 del usable.
- `compose_bottom_panel`: sin cambios geométricos críticos (full-width igual).
- `modules/rendering/infrastructure/layout/models.py`: opcional añadir `BoxLayout` para el banner vertical (e.g. `vertical_banner_box`) en `OverlayLayout`.
- Tests: `tests/unit/rendering/test_layout_composition_side_banner.py` (geometría con margins=0, top panel reducido, vertical banner box presente cuando layout_variant="side_banner"; sin cambios para "classic").

### 16-E · FFmpeg filters: colores parametrizables + overlay del banner
- `modules/rendering/infrastructure/ffmpeg/filters.py:36-50`: añadir kwargs `top_panel_color: str | None = None` y `bottom_panel_color: str | None = None` a `build_overlay_filter`. Defaults preservan `black@0.38` / `black@0.46` (compatibilidad classic).
- En `filters.py:73-85`: usar `top_panel_color or "black@0.38"` y `bottom_panel_color or "black@0.46"` para drawbox.
- `modules/rendering/infrastructure/formatting.py`: extender `resolve_text_color(block: str, override: str | None = None)` (default `None` → comportamiento actual). Llamar con `property_data.accent_text_color` cuando layout_variant=="side_banner" para los bloques del top/bottom panel.
- Helper nuevo en `formatting.py`: `apply_alpha_to_hex(hex_color: str, alpha: float = 0.85) -> str` que convierte `"#e22f8c"` → `"0xe22f8c@0.85"` (formato drawbox color). Tests unit con casos: hex con/sin `#`, alpha por defecto, alpha override, input None → fallback.
- Tests: `tests/unit/rendering/test_overlay_filter_accent_colors.py` — generar filter graph con `top_panel_color="0xe22f8c@0.85"` y verificar substring esperado.

### 16-F · Banner vertical rotado (PIL pre-render + overlay)
- `modules/rendering/infrastructure/preparation.py`: nueva función privada `_render_vertical_status_banner(*, text: str, height: int, width: int, background_hex: str, text_hex: str, font_path: Path) -> Path` que usa PIL para:
  1. Renderizar texto blanco sobre fondo HEX en una imagen `width × height` con padding.
  2. Rotar 90° CW vía `Image.rotate(-90, expand=True)`.
  3. Guardar como PNG en `working_dir`.
  4. Retornar la ruta.
- `modules/rendering/infrastructure/models.py:PreparedReelAssets`: añadir `vertical_banner_path: Path | None = None`.
- En `preparation.prepare_reel_render_assets`: cuando `layout_variant=="side_banner"` (kwarg nuevo), generar el banner via `_render_vertical_status_banner` con texto `build_status_ribbon_text(property_data)`.
- En `filters.py` y `poster.py`: si `prepared_assets.vertical_banner_path is not None`, añadirlo como input ffmpeg adicional y overlay en `vertical_banner_box.x/y` desde el layout.
- Tests unit: mockear PIL/fontTools si hace falta, o validar que la función llama a Image.save con un path razonable. Si es costoso, validar solo el contract (que se invoca cuando layout_variant="side_banner").

### 16-G · End-to-end + docs
- Test integration nuevo: `tests/integration/rendering/test_side_banner_render.py` (smoke: render reel + poster con template `side_banner` y verifica que el filter graph contiene `drawbox color=0x...`, que `vertical_banner_path` se generó, y que poster JPG existe). Saltar test si ffmpeg no disponible (gated igual que otros tests de rendering).
- `docs/API.md`: documentar el nuevo template y los dos campos webhook `wppd_accent_*`.
- `docs/http_surface.md` y `docs/openapi.json`: regenerar (el GET `/v1/admin/agencies/{id}/render-templates` ya existe, solo cambia el contenido devuelto).
- `progress/current.md`: bitácora.

## Criterios de aceptación

1. `GET /v1/admin/agencies/{id}/render-templates` devuelve dos templates (`classic` + `side_banner`); `side_banner.status="active"`, `sort_order=1`.
2. PUT `/v1/admin/agencies/{id}/defaults` con `render_template_id="side_banner"` round-trip persiste y `/reel-profile` lo refleja.
3. Property webhook con `wppd_accent_text_color="#ffffff"` + `wppd_accent_background_color="#e22f8c"` ingesta sin error y persiste en `properties.wppd_accent_*`.
4. Render con `layout_variant="side_banner"` produce filter graph con `drawbox color=0xe22f8c@0.85` (o equivalente con alpha aplicado) y overlay del banner vertical rotado.
5. Property sin `wppd_accent_*` cae a `BrandSettings.primary_color` (verificado en test unit y log de manifest).
6. Render con `layout_variant="classic"` produce filter graph **byte-for-byte idéntico** al actual (regresión cero).
7. `alembic upgrade head` y `alembic downgrade -1` verdes en DB limpia para las dos migraciones nuevas.
8. `pytest -q` verde — baseline 547+ tests (post-render-templates), añadir los tests nuevos por encima.
9. `python -m apps.api --check` y `python -m apps.worker --check` exit 0.
10. `./init.sh` verde (o equivalente PowerShell).

## Riesgos

- **Regresión en classic**: el branching por `layout_variant` debe ser estricto. Mitigación: tests existentes de classic no se modifican; deben seguir pasando.
- **Coste ffmpeg del overlay del banner por frame**: el banner se renderiza una vez como PNG y se overlay como imagen estática en todo el video (igual que agent_image_path). No tiene impacto perceptible sobre el coste actual.
- **Validación HEX ausente**: si el webhook envía un valor inválido (`"red"`, `"#xyz"`), `drawbox` puede fallar silenciosamente o producir un color por defecto. Mitigación opcional: añadir `is_valid_hex_color()` helper en `shared/` y fallback al brand color cuando inválido + log warning. Marcar como sub-tarea opcional dentro de 16-C.
- **BrandSettings load**: si la sesión actual no expone `uow.configuration.brands`, el implementer puede tener que usar el `BrandRepository` directamente. Verificar al empezar 16-C.
- **Compatibilidad poster.py**: el poster usa el mismo `build_overlay_layout`; cualquier cambio en signature debe propagar también al `poster._build_poster_filter_script`. Mitigación: tests integration cubren ambos.

## Estimación de complejidad

- Volumen: ~12-15 ficheros modificados, ~4-6 ficheros nuevos (migraciones + tests).
- 2 migraciones alembic (cero overlap con feature 13/14/15 pending).
- Sin cambios arquitectónicos (pure feature addition).
- Compleja por el ancho de la cadena (catalog → ORM → render data → ffmpeg) pero cada eslabón es mecánico.

Recomendación: **un solo implementer**, una sola sesión (con sub-tareas serializadas 16-A → 16-G).
