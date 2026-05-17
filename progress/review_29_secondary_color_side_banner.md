# review 29 — secondary_color_side_banner (BACK)

- **Veredicto:** APPROVED.
- **Fecha:** 2026-05-14
- **Reviewer:** Claude (subagente reviewer).
- **Informe del implementer:** `progress/impl_29_secondary_color_side_banner.md`.
- **Diseño:** `progress/design_email_notifications_and_brand_customisation.md` §B.5.

## Resumen del veredicto

Feature 29 cablea `BrandSettings.secondary_color` al render del template
`side_banner`, sustituyendo el `#FECF4D` hardcoded de feature 17 por una
cascada de 2 niveles (brand → fallback). El campo dedicado
`PropertyRenderData.side_banner_ribbon_background_color` mantiene la
independencia respecto a `accent_*` (paneles top/bottom). El render del
template `classic` no se ve afectado. Los hotfixes Codex en
`filters.py` y `panels.py` quedan intactos. La cobertura de tests
(8 nuevos + 1 actualizado) cubre los 3 escenarios del rubric: brand
configurado, brand ausente (fallback), classic no afectado.

## Verificaciones ejecutadas

```
bash ./init.sh
  → exit 0; 811 passed, 3 baseline failed (test_http_surface_contract +
    2 test_http_transport — preexistentes y documentados).

.venv/bin/python -m alembic heads
  → 20260514_0006 (head). Sin cambio (feature 29 no toca BBDD).

.venv/bin/python -m pytest tests/integration/rendering/ \
  tests/unit/rendering/ tests/integration/reels/ tests/unit/reels/ -q
  → 294 passed in 88.70s.

grep -rn 'FECF4D\|#fecf4d' modules/
  → solo comentarios + la constante fallback en
    preparation.py:245 (_SIDE_BANNER_RIBBON_BACKGROUND = "#FECF4D").

grep -rn 'side_banner_ribbon_background_color' modules/
  → propagación end-to-end: ingest_property_into_reel.py:292 →
    render_template_settings.py:37 (frozenset) →
    frame_composition.py:217/221/257 (build_render_data lifte) →
    models.py:150 (campo PropertyRenderData) →
    preparation.py:210 (call site cascada).

grep -rn '_resolve_brand_secondary_color' modules/
  → 2 hits, ambos en ingest_property_into_reel.py (definición + call),
    paralelos a _resolve_brand_primary_color.

grep -n 'side_banner_ribbon_background_color\|secondary_color' \
  modules/rendering/infrastructure/ffmpeg/filters.py \
  modules/rendering/infrastructure/layout/panels.py
  → vacío. Los hotfixes Codex no fueron tocados por feature 29.
```

## Decisiones del implementer — validación

### 1. Cascada de 2 niveles (brand → `#FECF4D`)

VERIFICADO. El webhook WordPress solo expone
`wppd_accent_text_color` + `wppd_accent_background_color`
(`modules/catalog/domain/wordpress_property.py:89-90`, parseados en
`_property_conversions.py:242-243` y consumidos como par primario por
feature 16 en `frame_composition.py:200-204` y por el publisher GHL).
`_sanitize_property_accent_colors` (líneas 629-647 de
`ingest_property_into_reel.py`) confirma que solo hay 2 colores
WordPress. La decisión de cascada-de-2 es correcta y queda documentada
tanto en el helper como en `docs/API.md`. El acceptance criteria #2
del `feature_list.json` original (3 niveles) queda actualizado al
hallazgo y reflejado en el informe del implementer.

### 2. Hardcoded preservado como fallback

VERIFICADO. `_SIDE_BANNER_RIBBON_BACKGROUND = "#FECF4D"` sigue en
`preparation.py:245`. Único call site en
`prepare_reel_render_assets` (línea 209-212) hace:

```python
background_hex=(
    property_data.side_banner_ribbon_background_color
    or _SIDE_BANNER_RIBBON_BACKGROUND
),
```

No hay otros lugares que referencien la constante sin override.

### 3. Campo dedicado `side_banner_ribbon_background_color`

VERIFICADO. Pipeline completo:

- `ingest_property_into_reel.py:253` resuelve el valor.
- `ingest_property_into_reel.py:290-294` lo añade a
  `render_template_reel_settings` (NO al poster — el poster no usa la
  cinta rotada).
- `render_template_settings.py:37` lo incluye en
  `_RENDERER_INTERNAL_OVERRIDE_KEYS` (frozenset) → el normalizador no
  intenta coercerlo en un campo de `PropertyReelTemplate`, así que no
  rompe el dataclass ni invalida `settings_hash`.
- `frame_composition.py:216-223,257` lifte la clave del dict y la
  setea en `PropertyRenderData`.
- `models.py:150` declara el campo `side_banner_ribbon_background_color:
  str | None = None`.
- `preparation.py:209-212` lo consume con OR-fallback.

La decisión de no reusar `accent_*` mantiene la independencia entre
paneles top/bottom (per-property o brand-primary) y la cinta (brand-secondary).

### 4. Hotfixes Codex intactos

VERIFICADO. `grep` de las keys de feature 29 en
`filters.py` y `panels.py` da vacío. El implementer no introdujo
cambios en esos archivos; los diffs vs HEAD que se ven en `git status`
son los previos de Codex (HOTFIX `side_banner_footer_radius` y HOTFIX
`classic_template_preview`), no de feature 29.

### 5. Tests añadidos / actualizados

VERIFICADO. 8 tests nuevos cubren los 3 escenarios del rubric y más:

| Test | Escenario |
|------|-----------|
| `test_render_vertical_status_banner_honours_brand_secondary_color` | brand `#FF00FF` → filter contiene `0xff00ff@1.00`, no `0xfecf4d`. |
| `test_render_vertical_status_banner_uses_supplied_background_for_drawbox` (renombrado) | brand ausente → filter contiene `0xfecf4d@1.00` (fallback). |
| `test_prepare_reel_render_assets_wires_secondary_color_cascade` (inspect-source) | exige cascada; impide regresión a hardcode-only o a `accent_background_color`. |
| `test_build_render_data_threads_brand_secondary_color_from_reel_settings` | la clave del dict aterriza en `PropertyRenderData`. |
| `test_normalize_property_reel_template_overrides_skips_renderer_internal_keys` | la nueva clave + `fallback_accent_*` se filtran silenciosamente del dataclass override. |
| `test_side_banner_render_threads_brand_secondary_color_to_preparation` | end-to-end: dict → render data → preparation fake. |
| `test_side_banner_render_secondary_color_absent_uses_none` | sin override en dict, render data lleva `None`. |
| `test_classic_render_ignores_brand_secondary_color_for_panels` | **regresión classic**: con brand secondary set, accent panels permanecen `None` y layout sigue `classic`. |
| `test_ingest_injects_brand_secondary_color_into_reel_settings` | BBDD con secondary `#FF00FF` → la clave aterriza en `render_template_reel_settings`, NO en poster. |
| `test_ingest_omits_secondary_color_when_brand_has_default_white` | sin row de brand, helper devuelve `None`. |

## Acceptance criteria — validación

| AC | Estado | Notas |
|----|--------|-------|
| 1. Brand configurado → filter contiene ese color | OK | `test_render_vertical_status_banner_honours_brand_secondary_color`. |
| 2. Brand null + webhook con secundario → usa webhook | N/A (revisado) | Webhook no expone secundario; cascada colapsa a 2 niveles. Documentado en informe + helper + docs/API.md. |
| 3. Ambos null → fallback `#FECF4D` | OK | Test renombrado + `test_ingest_omits_secondary_color_when_brand_has_default_white`. |
| 4. Render classic no afectado | OK | `test_classic_render_ignores_brand_secondary_color_for_panels`. |
| 5. pytest verde + sin regresiones 16/17 | OK | 811 passed (era 803 + 8 nuevos); 3 baseline failed preexistentes. |
| 6. `apps.api --check` + `apps.worker --check` exit 0 | OK | Ambos READY en init.sh. |

## Observaciones (no bloqueantes)

- **Default white**: si una agencia tiene el default `#FFFFFF` heredado
  de `BrandSettingsRepository.upsert`, la cinta sale blanca. El test
  `test_ingest_omits_secondary_color_when_brand_has_default_white`
  cubre el caso "sin row de brand" pero NO el caso "row con
  `#FFFFFF` literal". Es consistente con `primary_color` (mismo
  comportamiento) y documentado en el informe del implementer; sin
  cambio requerido.
- **`content_fingerprint`**: el campo nuevo vive en `PropertyRenderData`
  (runtime-only, no se persiste). El fingerprint se computa sobre
  `PropertyReelTemplate` (donde NO está la clave nueva), así que
  feature 29 no invalida snapshots existentes.

## Cierre

Aprobada. Aplico el cierre del back en el siguiente paso:

- `feature_list.json` id 29 → `status: "done"`, sin `started_at`,
  añade `review: "progress/review_29_secondary_color_side_banner.md"`.
- `progress/history.md` → append bloque siguiendo el patrón cronológico.
- `progress/current.md` → eliminar la sección de feature 29 (conservar
  HOTFIXes Codex + sesión paralela música).
