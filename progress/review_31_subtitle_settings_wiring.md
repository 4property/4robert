# Reviewer report — feature 31 BACK (subtitle_settings_wiring)

- Fecha: 2026-05-15
- Subagente: reviewer (sobre /opt/projects/4Reels-Backend)
- Veredicto: **APPROVED**

## Contexto

- Plan: `progress/current.md` § "Trabajo en paralelo — feature 31 BACK".
- Implementer: `progress/impl_31_subtitle_settings_wiring.md`.
- Feature: `feature_list.json` id 31.
- Cross-repo: feature 31 front (cleanup + switch autoCaptions) pendiente,
  se arranca tras este cierre.

## Validación punto-a-punto (decisiones del implementer)

1. **`SubtitleStyle` + `PropertyRenderData`** —
   `modules/rendering/infrastructure/models.py:41-69` define el dataclass
   frozen+slots (defaults `enabled=True`, `font_family=None`,
   `weight="700"`, `color="#ffffff"`, `bg_style="outline"`,
   `bg_color="#0f1729"`, `bg_opacity=82`, `position="bottom"`,
   `alignment="center"`, `uppercase=False`, `max_chars=36`) y línea 198
   añade `subtitle_style: SubtitleStyle = field(default_factory=SubtitleStyle)`
   al final de `PropertyRenderData` con `__all__` actualizado (línea 214).
   ✅

2. **`TimedTextSegmentLayout.alignment`** — `modules/rendering/infrastructure/layout/models.py:99`
   añade `alignment: str = "center"` con default backwards-compatible y
   `to_dict` lo incluye (línea 116). ✅

3. **Mapeo camelCase → snake_case** —
   `modules/reels/application/use_cases/ingest_property_into_reel.py:757-819`
   implementa `_resolve_subtitle_settings_overrides`: 10 keys
   `subFont/subWeight/subColor/subBgStyle/subBgColor/subBgOpacity/subPosition/subAlign/subUppercase/subMaxChars`
   → snake_case + `automation.autoCaptions` → `auto_captions_enabled`
   (booleanizado). Stash con `setdefault` en `render_template_reel_settings`
   (líneas 288-293). Defensivo en 5 axes (UoW sin configuration / sin
   defaults / agency sin defaults / settings no dict / agency_id vacío).
   NO toca `render_template_poster_settings`. ✅

4. **`_RENDERER_INTERNAL_OVERRIDE_KEYS`** —
   `modules/rendering/infrastructure/render_template_settings.py:36-62`
   añade las 11 keys nuevas (10 sub_* + auto_captions_enabled). ✅

5. **`compose_subtitle_segments`** —
   `modules/rendering/infrastructure/layout/subtitles.py`:
   - Firma sin cambios: lee `property_data.subtitle_style` (líneas 86-90).
   - `_apply_max_chars` (líneas 46-63) trunca en frontera de palabra,
     añade `…` solo si el cap dispara, fallback hard-cut si no hay
     espacio en los primeros N chars.
   - `uppercase` (línea 127): aplica `.upper()` antes del medidor.
   - `position` (líneas 157-165): top → 10% height, middle → centro
     vertical sobre `box_height`, bottom → math histórica.
   - `alignment` (línea 181): propaga al nuevo campo del segment. ✅

6. **`filters.py`** —
   `modules/rendering/infrastructure/ffmpeg/filters.py:190-287`:
   - `if subtitle_enabled:` envuelve **todo** el bloque de subtitle
     drawtext (líneas 198-287). Si `enabled=False`, 0 drawtext de
     subtítulo. ✅
   - `resolve_weighted(family, weight)` en try/except — fallback al
     `subtitle_font_path` legacy del template si `ValueError` (familia
     desconocida) (líneas 207-221).
   - `bg_style`:
     - `outline` → `borderw=2:bordercolor=black@0.80` (legacy).
     - `block` / `pill` → `box=1:boxcolor=<hex>@<alpha>:boxborderw=8`
       (pill colapsa a block, documentado como follow-up MVP).
     - `none` → ni borderw ni box; conserva `shadowx/shadowy` para
       legibilidad sobre fotos claras (líneas 266-280).
   - `alignment`: `_subtitle_x_expr(seg)` (líneas 243-249):
     `left` → `{x}`, `right` → `{x}+max({max_width}-text_w,0)`,
     `center` → `{x}+max(({max_width}-text_w)/2,0)`. ✅

7. **Snapshot pinned** —
   `tests/unit/rendering/test_overlay_filter_classic_snapshot.py:53-56`
   actualizado con comentario explicativo. Color default subtítulo:
   `0xF4D03F` → `0xffffff` alineado con el preview del front. La línea
   56 emite `fontcolor=0xffffff` para el caption por defecto. El test
   pinned pasa. ✅

8. **NO toca poster_settings** — confirmado: el ingest stash solo en
   `render_template_reel_settings`; los pósters nunca consultan
   `subtitle_style`. ✅

## Layer rules

- `grep -rn 'from modules.configuration' modules/rendering/` →
  todos los imports apuntan a `modules.configuration.domain.*`
  (RenderTemplate, MusicTrack, font_catalog). El nuevo import de
  `resolve_weighted` en `filters.py:209` es lazy (dentro del try) y
  también respeta la regla. ✅

## Acceptance criteria

| # | AC | Estado |
|---|----|--------|
| 1 | Settings sub*/auto_captions llegan al filter graph | ✅ end-to-end |
| 2 | `auto_captions=false` → 0 subtitle drawtext | ✅ `if subtitle_enabled:` envuelve todo el bloque |
| 3 | `bg_style='none'/'outline'/'block'/'pill'` | ✅ pill colapsa a block (MVP follow-up) |
| 4 | `uppercase=true` → uppercase en drawtext | ✅ `.upper()` antes del medidor |
| 5 | `position='top'/'middle'/'bottom'` → segment.y | ✅ 10% / centro vertical / legacy |
| 6 | `alignment='left'/'center'/'right'` → x calc | ✅ helper `_subtitle_x_expr` |
| 7 | `subFont` via font_catalog; fallback Inter | ✅ try/except con fallback al `subtitle_font_path` legacy |
| 8 | Tests 11 escenarios | ✅ 5 font_catalog + 7 unit subtitle_style + 9 integration wiring = 21 nuevos |
| 9 | pytest verde | ✅ 842 passed, 3 fallos baseline preexistentes (`test_http_surface_contract` + 2 `test_http_transport`) |
| 10 | apps.api/apps.worker --check exit 0 | ✅ ambos green vía `./init.sh` |

## Verificación local

| Comando | Resultado |
|---------|-----------|
| `bash ./init.sh` | OK (RUNTIME READY: Yes, apps.api/apps.worker --check verdes, pytest 842 passed / 3 baseline failed). |
| `pytest tests/integration/rendering/test_subtitle_settings_wiring.py tests/unit/rendering/test_subtitle_style.py tests/unit/configuration/test_font_catalog.py -q` | 34 passed. |
| `pytest tests/integration/rendering/ tests/unit/rendering/ tests/integration/reels/ -q` | 216 passed. |

Baseline: 3 fallos preexistentes (`test_http_surface_contract` y 2
`test_http_transport`), invariantes en main; no relacionados con la
feature.

## Riesgos / follow-ups (no bloqueantes)

- `pill` colapsa a `block` en MVP. Esquinas redondeadas reales
  requieren un filtro extra de ffmpeg (`drawbox + geq`); documentado
  por el implementer.
- `max_chars` actúa como hard-cap previo al wrap pixel-aware. Agencias
  con captions densas pueden bajar `subMaxChars` para forzar lineas
  cortas.
- Color default visible: el cambio `0xF4D03F` → `0xffffff` afecta a
  **toda agencia** que renderice sin haber abierto la pestaña
  `/defaults > Subtitles`. Alineado con el preview del front; sin
  regresión visual a ojo (blanco sobre el overlay funciona en todos
  los slides).

## Cierre

Aplicado en este turno:

- `feature_list.json` id 31 → `done`, eliminado `started_at`, añadido
  `review`.
- `progress/history.md` → bloque cierre back con counts y siguiente
  paso cross-repo.
- `progress/current.md` → eliminada la sección de trabajo en paralelo
  de feature 31 (preservados HOTFIX side_banner, HOTFIX
  classic_template_preview, sesión paralela música).
