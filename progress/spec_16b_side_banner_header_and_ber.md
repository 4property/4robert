# Spec — Side Banner refinements (header + BER position)

> Leader brief para el implementer. Scope reducido: dos ajustes visuales sobre el
> render template `side_banner` ya entregado en feature 16. Sin migraciones, sin
> tocar `classic`.

## Contexto

Feature 16 (`progress/impl_16_side_banner.md`) entregó el render template
`side_banner` con full-bleed photo, banner vertical rotado y panel colors per-
property. Tras smoke real con la agencia `f86148f7-7862-455a-8161-337b62cb1134`
(poster `generated_media/dev76.designbricks.ie/posters/1-friar-street-cork-city-centre-co-cork-poster.jpg`),
el usuario pide acercar el layout a `example-new-template.png` con dos
correcciones puntuales:

1. **Cabecera del top panel**: hoy renderiza `build_status_ribbon_text(property_data)`
   (p.ej. "FOR SALE"), redundante con el banner vertical. Debe pasar a un literal
   hardcodeado **"OFFERS OVER:"** SOLO cuando `layout_variant == "side_banner"`.
   `classic` no cambia.

2. **Posición del BER badge**: hoy queda centrado verticalmente contra el panel,
   pegado al borde derecho. Debe quedar **inline con la specs row**
   (`build_property_header_details_line`, p.ej. "108m² | 3beds | 2baths"), también
   SOLO en `side_banner`. `classic` mantiene la posición actual.

## Cambios

### 1. Header literal "OFFERS OVER:" en side_banner

**Fichero:** `modules/rendering/infrastructure/layout/panels.py`

- Añadir `layout_variant: str = "classic"` como kwarg a `compose_top_panel`
  (línea 70).
- En lugar de `text=build_status_ribbon_text(property_data)` (línea 106), pasar
  un texto resuelto por variante:
  - `side_banner` → literal `"OFFERS OVER:"`
  - `classic` → `build_status_ribbon_text(property_data)` (sin cambios)
- Mantener el `block="status"` para no inventar slots nuevos. El font size
  saldrá del bound existente (`resolve_font_size_bounds("status", ...)`).
- Si quieres bajar visualmente el tamaño del literal para que parezca un label
  pequeño (la referencia lo muestra ~40 % del precio), puedes reducir el
  `max_font_size` específico para `"OFFERS OVER:"` (no obligatorio: si la
  cabecera actual se ve aceptable en el smoke, déjalo).

**Fichero:** `modules/rendering/infrastructure/layout/composition.py`

- Reenviar `layout_variant` a `compose_top_panel` en la llamada de la línea 67.
  El kwarg ya está disponible (`composition.py:36`).

### 2. BER badge inline con la specs row en side_banner

**Fichero:** `modules/rendering/infrastructure/layout/panels.py:194-201`

- Cuando `layout_variant == "side_banner"` y existe un `TextBlockLayout` con
  `block == "details"` en `text_blocks`, calcular `ber_y` para que el badge
  quede verticalmente centrado contra esa fila:
  ```python
  details_block = next((b for b in text_blocks if b.block == "details"), None)
  if layout_variant == "side_banner" and details_block is not None:
      ber_y = details_block.y + max(0, round((details_block.box_height - ber_icon_height) / 2))
  else:
      ber_y = top_panel.y + max(0, round((top_panel.height - ber_icon_height) / 2))
  ```
- `ber_x` sigue como ahora (`top_panel.x + top_panel.width - panel_padding_x - ber_icon_width`).
- El `header_text_width` (línea 94) ya restringe el ancho del texto para dejar
  hueco al icono; **no tocar** esa lógica.

## Restricciones

- **No tocar `classic`.** Verificar con
  `tests/unit/rendering/test_overlay_filter_classic_snapshot.py` que el byte-for-byte
  sigue idéntico.
- **No nueva migración.** No es un cambio de schema.
- **No nuevos endpoints.** "OFFERS OVER:" es literal en código, no campo
  configurable (decisión del usuario).
- **No tocar banner shape, foto circular, tarjeta logo** — fuera del scope de
  esta iteración (gaps #4–#6 quedan para una segunda tanda si el usuario lo
  pide).

## Tests obligatorios

- Extender `tests/unit/rendering/test_layout_composition_side_banner.py`:
  - Verificar que con `layout_variant="side_banner"` el primer `TextBlockLayout`
    del top panel tiene `text == "OFFERS OVER:"`, y con `"classic"` mantiene
    `build_status_ribbon_text(property_data)`.
  - Verificar que con `has_ber_badge=True` + `layout_variant="side_banner"` y un
    `details` block presente, `ber_badge_box.y` ≈ `details_block.y +
    (details_block.box_height - ber_icon_height) / 2`.
  - Verificar regresión classic: misma fixture con `layout_variant="classic"`
    produce la posición vertical-centrada original del BER badge.

## Verificación final

```bash
.venv/bin/python -m pytest tests/unit/rendering/ tests/unit/reels/ -q
```

- 0 regresiones en la suite de rendering.
- El snapshot test de classic (`test_overlay_filter_classic_snapshot.py`) sigue
  passing.
- `python -m apps.api --check` y `python -m apps.worker --check` exit 0.

## Entregable

- Informe en `progress/impl_16b_side_banner_header_and_ber.md` con: ficheros
  tocados, snippets de los cambios, output de `pytest`, y confirmación de los
  3 acceptance criteria de arriba.
- **No** marcar `feature_list.json` ni commitear. El leader (o el reviewer)
  cierra.
