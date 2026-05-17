# Implementer report — feature 31 BACK (subtitle_settings_wiring)

- Fecha: 2026-05-15
- Subagente: implementer (sobre /opt/projects/4Reels-Backend)
- Estado: implementado, pendiente de reviewer; feature NO marcada `done`.

## Decisiones

### Mapping camelCase → snake_case

El frontend persiste 10 claves bajo `agency_reel_defaults.settings`:

| camelCase del front     | snake_case en el renderer  |
|-------------------------|----------------------------|
| `subFont`               | `subtitle_font_family`     |
| `subWeight`             | `subtitle_weight`          |
| `subColor`              | `subtitle_color`           |
| `subBgStyle`            | `subtitle_bg_style`        |
| `subBgColor`            | `subtitle_bg_color`        |
| `subBgOpacity`          | `subtitle_bg_opacity`      |
| `subPosition`           | `subtitle_position`        |
| `subAlign`              | `subtitle_alignment`       |
| `subUppercase`          | `subtitle_uppercase`       |
| `subMaxChars`           | `subtitle_max_chars`       |
| `automation.autoCaptions` | `auto_captions_enabled`  |

La traducción ocurre en `ingest_property_into_reel._resolve_subtitle_settings_overrides`
y se aplica con `setdefault` sobre `render_template_reel_settings`.
Las claves snake_case figuran en `_RENDERER_INTERNAL_OVERRIDE_KEYS`
para que `normalize_property_reel_template_overrides` no las trate como
campos inválidos de `PropertyReelTemplate`. NO se stash en
`render_template_poster_settings`: el póster nunca renderiza subtítulos.

### `SubtitleStyle` (modelo ya creado por Codex en líneas 41-69)

Se añadió un campo `subtitle_style: SubtitleStyle = field(default_factory=SubtitleStyle)`
al final de `PropertyRenderData`. Defaults de la dataclass: `enabled=True`,
`font_family=None`, `weight="700"`, `color="#ffffff"`, `bg_style="outline"`,
`bg_color="#0f1729"`, `bg_opacity=82`, `position="bottom"`,
`alignment="center"`, `uppercase=False`, `max_chars=36`. Estos defaults
hacen que una agencia recién onboarded mantenga el look histórico (excepto
el color del subtítulo, que pasa de amarillo `#F4D03F` a blanco
`#ffffff` — ver más abajo).

### Comportamiento si `font_family` no está en el catálogo

`filters.py` envuelve la resolución en `try/except ValueError`. Si la
agencia persistió una familia que ya no está en
`modules.configuration.domain.font_catalog`, la llamada a
`resolve_weighted(family, weight)` lanza `ValueError` y caemos al
`subtitle_font_path` legacy del template (`REEL_SUBTITLE_FONT_PATH`,
Inter Bold). Sin warning a log (el ingest layer ya logguea
`brand.font_family` desconocido en `_resolve_brand_font_descriptor`;
para `subtitle_font_family` la versión persistida es la del front que
el usuario eligió de la lista de catálogo).

### Wrap si `max_chars` no encaja en el compose actual

El medidor de texto (`measure_text_block`) trabaja sobre anchos en
píxeles, no en chars. Se ha optado por aplicar `max_chars` como un
hard-cap previo al medidor: si la caption supera N graphemes se trunca
en la última frontera de palabra (`rfind(" ", 0, max_chars)`) y se
añade `…`. El medidor luego envuelve el texto en líneas por píxel.
Documentado como follow-up: una verdadera politicia "max chars por línea"
exigiría re-implementar el wrap. Para el MVP es suficiente porque el
front limita `subMaxChars` a 24-48 (cap razonable).

### Comportamiento de `bg_style`

- **`outline`** (default): añade `borderw=2:bordercolor=black@0.80` a la
  drawtext. Es la mecánica histórica.
- **`block`**: añade `box=1:boxcolor=<hex>@<alpha>:boxborderw=8`. El
  color y opacidad provienen de `subtitle_bg_color` / `subtitle_bg_opacity`
  (0-100 escalado a 0.0-1.0).
- **`pill`**: en el MVP colapsa a `block` (rectángulo). Un verdadero
  pill (border-radius) exigiría un segundo filtro de ffmpeg
  (`drawbox + geq`) y se deja como follow-up.
- **`none`**: ni borderw ni box. Mantiene el `shadowx/shadowy` para
  preservar legibilidad sobre fotos claras.

En todos los estilos excepto `none` el subtítulo conserva la sombra
suave (`shadowx=0:shadowy=3:shadowcolor=black@0.75`). En `none` también
se mantiene la sombra (lo dejé igual que el resto, para que no rompa
contraste sobre fotos claras).

### Posición y alineación

- `position="bottom"`: comportamiento histórico (anclado encima del
  bottom_panel).
- `position="top"`: `y = round(height * 0.10)` (10% desde arriba).
- `position="middle"`: `y = max(0, round((height - box_height) / 2))`.
- `alignment` se almacena en un nuevo campo del dataclass
  `TimedTextSegmentLayout` (`alignment: str = "center"`) y se traduce a
  expresiones ffmpeg `x=...` en `filters.py`:
  - `"center"`: `x={seg.x}+max(({seg.max_width}-text_w)/2\,0)` (legacy).
  - `"left"`: `x={seg.x}` (sin offset).
  - `"right"`: `x={seg.x}+max({seg.max_width}-text_w\,0)`.

### Cambios en firmas

- `compose_subtitle_segments`: **sin cambios en firma** — el style se lee
  de `property_data.subtitle_style` que es un atributo nuevo en
  `PropertyRenderData`. Esto evita romper a los 4 callers de
  `build_overlay_layout` (composition.py, filters.py, render_reel.py,
  filter_graph.py, poster.py).
- `TimedTextSegmentLayout`: ganó campo opcional `alignment: str = "center"`
  con default backwards-compatible. Su `to_dict` incluye la clave nueva.
- `_build_subtitle_style(reel_settings: dict) -> SubtitleStyle`: función
  módulo-nivel nueva en `frame_composition.py` (pública dentro del módulo,
  el test la importa directamente).
- `_resolve_subtitle_settings_overrides`: método nuevo en
  `IngestPropertyIntoReelUseCase` que devuelve un `dict` snake_case-keyed.

### Renderer color default

El default de subtitle color cambia de `0xF4D03F` (amarillo histórico
hard-codeado en `formatting.OVERLAY_TEXT_COLOR_SUBTITLE`) a `0xffffff`
(blanco, el default que persiste el front). El test pinned
`tests/unit/rendering/test_overlay_filter_classic_snapshot.py` se
actualizó con un comentario explicativo. **Esto es un cambio visible**
en cualquier render que no tuviera per-agency settings: pasa de amarillo
a blanco. Está alineado con el diseño que el front muestra en preview.
`resolve_text_color("subtitle_caption")` aún devuelve `0xF4D03F` pero ya
no se consulta para el subtítulo (sólo para los otros bloques de texto
que no usan `SubtitleStyle`).

## Archivos tocados

| Archivo | Cambio |
|---------|--------|
| `modules/rendering/infrastructure/models.py` | añadido campo `subtitle_style` a `PropertyRenderData` + exportado `SubtitleStyle` |
| `modules/rendering/infrastructure/layout/models.py` | añadido `alignment: str = "center"` a `TimedTextSegmentLayout` |
| `modules/rendering/infrastructure/render_template_settings.py` | añadidas 11 claves nuevas a `_RENDERER_INTERNAL_OVERRIDE_KEYS` |
| `modules/rendering/application/frame_composition.py` | `_build_render_data` construye `SubtitleStyle` vía nueva helper `_build_subtitle_style` |
| `modules/rendering/infrastructure/layout/subtitles.py` | aplica `max_chars` + `uppercase` antes del wrap, anclaje Y según `position`, propaga `alignment` al segment |
| `modules/rendering/infrastructure/ffmpeg/filters.py` | drawtext usa font catalog weight-aware, color/bg_style/bg_color/bg_opacity per-agency, alignment per-segment, salta totalmente si `enabled=False` |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | nuevo helper `_resolve_subtitle_settings_overrides` + bloque que stash en `render_template_reel_settings` |
| `tests/unit/configuration/test_font_catalog.py` | 5 tests añadidos sobre `resolve_weighted` (bold/regular/None/unknown/invalid weight) |
| `tests/unit/rendering/test_subtitle_style.py` | NUEVO — 7 tests sobre `SubtitleStyle` + `_build_subtitle_style` |
| `tests/integration/rendering/test_subtitle_settings_wiring.py` | NUEVO — 9 tests sobre la cascada al filter graph |
| `tests/unit/rendering/test_overlay_filter_classic_snapshot.py` | snapshot actualizado: fontcolor `0xF4D03F` → `0xffffff` |

`resolve_weighted` y la exportación desde `modules.configuration.domain`
ya estaban presentes (hotfix de Codex previo); se reutiliza tal cual.

## Tests añadidos + counts

- `tests/unit/configuration/test_font_catalog.py`: +5 tests (`test_resolve_weighted_*`).
- `tests/unit/rendering/test_subtitle_style.py`: +7 tests (NUEVO archivo).
- `tests/integration/rendering/test_subtitle_settings_wiring.py`: +9 tests (NUEVO archivo).

## Verificación

| Comando | Resultado |
|---------|-----------|
| `pytest tests/integration/rendering/ tests/unit/rendering/ tests/integration/reels/ tests/unit/configuration/` | 351 passed |
| `pytest tests/unit/configuration/test_font_catalog.py tests/unit/rendering/test_subtitle_style.py tests/integration/rendering/test_subtitle_settings_wiring.py` | 34 passed |
| `python -m apps.api --check` | RUNTIME READY: Yes |
| `python -m apps.worker --check` | OK: kinds=reel_publish, scripted_render |
| `pytest -q` (full suite) | 842 passed, 3 failed (baseline conocido: `test_http_surface_contract` + 2 `test_http_transport`), 14 warnings, 370s |

Baseline: 3 fallos preexistentes (`test_http_surface_contract.py` y
2 en `test_http_transport.py`) — no se tocan.

## Pendientes para reviewer / siguientes pasos

- **NO** marcar feature 31 `done`: el reviewer la valida y luego el
  implementer front cablea la limpieza UI (quitar karaoke + LivePreview,
  añadir switch `automation.autoCaptions`).
- Comportamiento de `pill` documentado como follow-up: el MVP lo
  colapsa a `block`.
- El cap por `max_chars` corta en frontera de palabra; agencias que
  necesiten control fino pueden bajar `subMaxChars`.
