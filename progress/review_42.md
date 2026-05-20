# Review — feature 42 (`galaxy_render_template`)

- **Reviewer:** Claude (rol reviewer, lanzado por leader)
- **Fecha:** 2026-05-18
- **Implementer report:** `progress/impl_42.md` (3 iteraciones)
- **Explorers consultados:** `progress/explore_galaxy_arch.md`, `progress/explore_galaxy_seed.md`, `progress/explore_galaxy_preview.md`
- **Renders revisados:**
  - `progress/galaxy_iter_1.png` (base)
  - `progress/galaxy_iter_2.png` (radius + bottom anchor)
  - `progress/galaxy_iter_3.png` (footer chunky + tipografía agente) ← último

---

## Veredicto

**APROBADO_CON_OBSERVACIONES**

La feature 42 cumple scope + acceptance + verification + arquitectura. El implementer puede marcar
`feature_list.json` status `done` y mover el resumen de `progress/current.md` a `progress/history.md`.

Recomendación operativa: promover `progress/galaxy_iter_3.png` → `assets/render-templates/galaxy-template.png`
antes de cerrar la sesión. El placeholder actual es byte-for-byte una copia de `side-banner-template.png`
(md5 `d11db3c7b6f24b894963a4d8886dbed8`), lo que rompe la promesa del listado público de
`/v1/admin/agencies/{id}/render-templates`: el preview que se muestra al usuario en el selector de
templates será el del side_banner, no del galaxy.

Comando exacto:

```
cp /opt/projects/4Reels-Backend/progress/galaxy_iter_3.png \
   /opt/projects/4Reels-Backend/assets/render-templates/galaxy-template.png
```

Si el leader prefiere dejar el placeholder hasta una iteración futura (decisión válida; no es bloqueante
porque el endpoint sirve algo y la migración apunta a la URL correcta), debe quedar anotado como
follow-up en `progress/history.md`. Mi recomendación es promover ahora: el iter_3 cubre todos los
elementos de scope v1 y la divergencia visual restante respecto a `example-template-galaxy.png` es
fixture-driven (logo "CENTURY 21" real, foto de propiedad concreta) o explícitamente fuera de scope
(círculo central).

---

## Checkpoints (`CHECKPOINTS.md`)

### C1 — Arnés completo

- [x] Archivos base presentes: `AGENTS.md`, `CLAUDE.md`, `init.sh`, `feature_list.json`,
      `progress/current.md`.
- [x] 3 docs: `docs/architecture.md`, `docs/conventions.md`, `docs/verification.md` (sin modificar
      por esta feature).
- [x] `./init.sh` se reprodujo verde (exit 0) en esta sesión de review. Resultado idéntico al
      reportado por el implementer (ver §Verificación).

### C2 — Estado coherente

- [x] Una sola feature `in_progress` en `feature_list.json` (feature 42 — la otra coincidencia
      grep en línea 11 es el enum `valid_status`).
- [x] Toda feature `done` tiene tests asociados verdes (la feature 41, marcada `done` la sesión
      anterior, sigue verde en este run).
- [x] `progress/current.md` describe la feature en curso (entrada feature 42 al final del archivo).
- [x] `progress/history.md` tiene entrada por la última sesión cerrada (feature 41).

### C3 — Arquitectura respetada

- [x] Ningún archivo bajo `modules/rendering/` importa de
      `modules/<otro>/{application,infrastructure,transport}` (`grep` en
      `modules/rendering/` no devuelve violaciones).
- [x] `modules/rendering/domain/` no importa SQLAlchemy
      (`grep -rln 'sqlalchemy' modules/rendering/{domain,application}/` vacío).
- [x] La feature no introduce repositorios nuevos (cero código en `modules/rendering/infrastructure`
      llama `session.commit()`). Las migraciones SQL ejecutan a través de `op.execute(...)` del
      Alembic runtime, no de un repositorio aplicativo.
- [x] No se persisten secretos en plano (la feature no toca columnas `*_secrets_encrypted`).
- [x] No hay código nuevo en `services/`, `application/` (legacy en raíz), `repositories/`, `core/`,
      `domain/` (raíz). Todos los cambios viven en `modules/rendering/` + `alembic/versions/` + `tests/`.

### C4 — Verificación real

- [x] `tests/` tiene cobertura nueva: 5 archivos nuevos (3 unit, 2 integration) + 2 archivos
      extendidos (router + assets). Tests galaxy = 37 (focal), +3 baseline.
- [x] Los integration tests usan `tests/support/postgres.py` (verificado vía imports en
      `test_galaxy_render.py`, `test_render_templates_router.py`).
- [x] `pytest -q` muestra 1093 passed + 3 baseline failed + 1 deselected (visual_iter). Los 3
      fallos son los baseline históricos (`test_http_surface_contract.py` y 2 en
      `test_http_transport.py`), no han aumentado tras la feature.
- [x] `python -m apps.api --check` → `RUNTIME READY: Yes`. Exit 0.
- [x] `python -m apps.worker --check` → `Worker --check OK: kinds=email_send, reel_publish, scripted_render`.
      Exit 0.

### C5 — Schema y migraciones

- [x] No se modificó `shared/db/orm.py` para esta feature (cero cambios de data-model como prometía
      el scope). Las migraciones nuevas son data-seed only.
- [x] `alembic upgrade head` aplica limpio (cadena: …`20260517_0001` → `20260518_0001` →
      `20260518_0002`). Roundtrip `upgrade head → downgrade -2 → upgrade head` ejecutado en esta
      sesión, todos los pasos verdes. Head actual: `20260518_0002`.
- [x] `alembic downgrade -1` reversible. `20260518_0002` revierte `preview_images = '[]'::jsonb`
      idempotentemente (solo si el valor actual coincide con el payload aplicado, exactamente como
      `20260515_0001_side_banner_render_template_preview.py`). `20260518_0001` revierte
      `DELETE WHERE template_id='galaxy' AND layout_variant='galaxy'`, protección contra borrado
      destructivo si un agency lo personalizó.
- [x] Renames documentados en `ARCHITECTURE.md` siguen vigentes (no se reintroducen nombres legacy).

### C6 — Sesión cerrada bien

- [x] Solo nuevos archivos esperados sin trackear: las dos migraciones nuevas, los 5 tests nuevos,
      `progress/impl_42.md`, los 3 `progress/galaxy_iter_*.png` y `progress/explore_galaxy_*.md`.
      Cero `.tmp_debug*`, `__pycache__/` o basura.
- [x] La feature trabajada está en su estado correcto en `feature_list.json` (`in_progress`).
- [x] No hay `print()` de debug ni TODOs nuevos en `modules/rendering/`
      (grep `\bprint\(|\bTODO\b|\bFIXME\b` vacío en los 7 archivos modificados).
- [x] No se han colado credenciales en `.env.example` (ningún archivo de settings tocado).

---

## Scope vs implementación (item-a-item del `scope.back`)

1. ✅ `render_template_settings.py:23` — `"galaxy"` añadido al frozenset
   `SUPPORTED_LAYOUT_VARIANTS` (línea 24); constante `GALAXY_RENDER_TEMPLATE_ID = "galaxy"`
   (línea 23) exportada en `__all__` (línea 283).
2. ✅ `panels.py` — `is_galaxy = layout_variant == "galaxy"` en `compose_top_panel` (línea 98)
   y `compose_bottom_panel` (línea 364), con helper `is_side_banner_like = is_side_banner or
   is_galaxy`. Geometría:
   - **Top panel galaxy**: `x = round(width * 0.04)` (línea 247), `y = round(height * 0.035)`
     (línea 246), `width = round(width * 0.48)` (línea 248), `height = max(round(height * 0.18), …)`
     (línea 242-245). ✅ Match con el scope.
   - **Bottom panel galaxy**: `width = round(width * 0.94)` (línea 380), agente circular vía
     `_normalize_agent_image(..., circular_mask=use_side_banner_avatar)` en `preparation.py`,
     logo derecha vía rama `is_side_banner_like` (líneas 589-603). ✅ Match.
   - **Status text**: hardcoded `"OFFERS OVER:"` cuando `side_banner_has_price` (línea 164-165).
     ✅ Match con scope.
   - **BER badge inline**: `side_ber_x = round(width * 0.38)` para galaxy vs `0.36` para
     side_banner (líneas 109-113). ✅ Match (la justificación —panel más estrecho— está en el
     comentario).
3. ✅ `composition.py` — rama `layout_variant in {"side_banner", "galaxy"}` →
   `outer_margin_x = outer_margin_y = 0` (línea 49-51). ✅ Match con scope.
4. ✅ `filters.py` — `build_overlay_filter`:
   - **Bottom panel** rounded para `layout_variant in {"side_banner", "galaxy"}` (línea 157);
     resolver de radius dinámico `_resolve_galaxy_panel_radius` vs
     `_resolve_side_banner_footer_radius` (líneas 173-177).
   - **Top panel** rounded SOLO para galaxy (línea 208); usa `_resolve_galaxy_panel_radius`
     (líneas 216-228).
   - `_build_rounded_panel_source` helper reutilizado (líneas 43-65). Cero código duplicado.
   - ✅ Decisión explícita del scope ("aplicar el radio TANTO al top como al bottom").
5. ✅ `preparation.py` — `layout_variant in {"side_banner", "galaxy"}` invoca
   `_render_vertical_status_banner` con mismos parámetros (líneas 202-223). Cascade de
   `side_banner_ribbon_background_color` + `accent_text_color` verbatim.
   `_normalize_agent_image(circular_mask=True, fill=True)` para galaxy y side_banner (líneas
   573-583). Cero código duplicado.
6. ✅ `frame_composition.py` — no tocado para esta feature; la propagación de `layout_variant`
   ya era string-based desde feature 16. El valor `"galaxy"` llega intacto.
7. ✅ `alembic/versions/20260518_0001_seed_galaxy_render_template.py` —
   `down_revision='20260517_0001'`, `INSERT … ON CONFLICT (template_id) DO NOTHING`, sort_order=2,
   layout_variant='galaxy', `preview_images='[]'::jsonb`. Downgrade `DELETE` protegido por
   `template_id='galaxy' AND layout_variant='galaxy'`. ✅ Match scope.
8. ✅ `alembic/versions/20260518_0002_galaxy_render_template_preview.py` —
   `down_revision='20260518_0001'`, `UPDATE preview_images` con `image_url='/assets/render-templates/galaxy-template.png'`.
   Downgrade idempotente (matchea el payload exacto). ✅ Match scope.
9. ⚠️ `assets/render-templates/galaxy-template.png` — **placeholder byte-for-byte de
   `side-banner-template.png`** (mismo md5 `d11db3c7b6f24b894963a4d8886dbed8`). El implementer
   eligió la opción B documentada (placeholder) en lugar de promover el `galaxy_iter_3.png`.
   No bloqueante (el endpoint sirve algo y la migración apunta a la URL correcta), pero
   recomiendo promover `galaxy_iter_3.png` antes de cerrar (ver §Veredicto).
10. ✅ `tests/unit/rendering/test_layout_composition_galaxy.py` — 14+ tests (iter 1) + 1 assert
    actualizado y 3 tests nuevos en iter 3. Geometría, OFFERS OVER price, BER inline, anchors,
    footer chunky vs side_banner, agent text bigger, low-res floor.
11. ✅ `tests/unit/rendering/test_frame_composition_accent_colors_galaxy.py` — 4 tests, cascada
    de `side_banner_panel_color` + `side_banner_ribbon_background_color` end-to-end vía
    `_build_render_data`.
12. ✅ `tests/integration/rendering/test_galaxy_render.py` — 4 tests con mock
    prepare/manifest/reel/poster.
13. ✅ `tests/integration/configuration/test_render_templates_router.py` — extendido con
    `test_render_templates_list_includes_galaxy` (línea 83): sort_order=2, display_name='Galaxy',
    layout_variant='galaxy', preview_images poblado.
14. ✅ `tests/integration/apps_api/test_render_template_assets.py` — extendido con
    `test_api_serves_galaxy_render_template_preview_asset` (línea 39); content-type image/png.
15. ✅ `tests/integration/rendering/test_galaxy_iter.py` — nuevo, marker `@pytest.mark.visual_iter`
    registrado y excluido por default en `pytest.ini:2,5`.

Item bonus no listado en el scope original pero útil:

16. ✅ `tests/unit/rendering/test_filters_galaxy_radius.py` (iter 2) — 3 tests del helper
    `_resolve_galaxy_panel_radius`: caso típico 1080×1920 (galaxy > side_banner), floor en
    frame corto (`frame_height=600` → 24 px), cap por panel_height. Útil; cubre el nuevo helper
    a unit level.

---

## Acceptance (criterio-a-criterio del array `acceptance`)

1. ✅ `SUPPORTED_LAYOUT_VARIANTS == frozenset({'classic', 'side_banner', 'galaxy'})` — verificado en
   `modules/rendering/infrastructure/render_template_settings.py:24`.
2. ✅ `alembic upgrade head` crea la fila template_id='galaxy', sort_order=2,
   layout_variant='galaxy' con preview_images poblado tras 20260518_0002.
   `alembic downgrade -1/-2` limpian sin residuo. Roundtrip reproducido en esta sesión.
3. ✅ `GET /v1/admin/agencies/{id}/render-templates` incluye 'galaxy' como tercer item con
   preview_images apuntando a `/assets/render-templates/galaxy-template.png` — verificado por
   `test_render_templates_list_includes_galaxy`.
4. ✅ `GET /assets/render-templates/galaxy-template.png` devuelve 200 con content-type image/png
   — verificado por `test_api_serves_galaxy_render_template_preview_asset`.
5. ✅ Rendering con `layout_variant='galaxy'` + BrandSettings primary/secondary se cascadean a
   panel + ribbon. Cubierto por `test_frame_composition_accent_colors_galaxy.py` (4 tests).
6. ✅ Frame galaxy muestra: panel superior-izquierdo redondeado con OFFERS OVER + price + address
   + specs, cinta vertical FOR SALE arriba-derecha, footer inferior redondeado con agent photo
   + contacto + agency logo. Sin círculo central (out-of-scope v1 confirmado). Verificado
   visualmente en `progress/galaxy_iter_3.png` y por tests unit/integration.
7. ✅ `progress/galaxy_iter_3.png` se aproxima razonablemente a `example-template-galaxy.png`:
   layout, proporciones (top panel ~48%, bottom panel ~94% inset chunky, ribbon dorado a la
   derecha), colores cascadeados desde brand. Diferencias remanentes son fixture-driven (logo
   real "CENTURY 21" vs placeholder "Agency"; foto de propiedad concreta) o explícitamente fuera
   de scope (círculo central con logo agencia). ✅ Cualitativamente match.
8. ✅ Baseline pytest: 1093 passed = 1063 (baseline previo feature 41) + 30 nuevos galaxy +
   regresiones existentes intactas. 3 fails históricos (`test_http_surface_contract.py` +
   2 en `test_http_transport.py`) **se mantienen igual** (no aumentan, no se cuentan como
   regresión introducida por esta feature). 1 deselected = `test_galaxy_iter.py` (marker
   `visual_iter`).
9. ✅ `bash ./init.sh` exit 0 (reproducido en esta sesión; ver §Verificación).

---

## Verificación (re-ejecutada en review)

### Focal tests (incluyendo el helper de iter 2)

```
$ .venv/bin/python -m pytest tests/unit/rendering/test_layout_composition_galaxy.py \
    tests/unit/rendering/test_frame_composition_accent_colors_galaxy.py \
    tests/integration/rendering/test_galaxy_render.py \
    tests/integration/configuration/test_render_templates_router.py \
    tests/integration/apps_api/test_render_template_assets.py \
    tests/unit/rendering/test_filters_galaxy_radius.py -q
.....................................                                   [100%]
37 passed in 12.27s
```

### Regression side_banner / classic

```
$ .venv/bin/python -m pytest tests/unit/rendering/test_layout_composition_side_banner.py \
    tests/unit/rendering/test_overlay_filter_accent_colors.py \
    tests/unit/rendering/test_layout_panels.py \
    tests/unit/rendering/test_layout_composition.py \
    tests/unit/rendering/test_overlay_filter_classic_snapshot.py -q
......................................                                   [100%]
38 passed in 0.35s
```

Cero regresiones en side_banner ni classic. ✅

### Alembic roundtrip

```
$ .venv/bin/python -m alembic current
20260518_0002 (head)

$ .venv/bin/python -m alembic downgrade -2
... Running downgrade 20260518_0002 -> 20260518_0001 ...
... Running downgrade 20260518_0001 -> 20260517_0001 ...

$ .venv/bin/python -m alembic upgrade head
... Running upgrade 20260517_0001 -> 20260518_0001 ...
... Running upgrade 20260518_0001 -> 20260518_0002 ...
20260518_0002 (head)
```

Roundtrip clean. ✅

### Readiness checks

```
$ .venv/bin/python -m apps.api --check
... RUNTIME READY: Yes ...

$ .venv/bin/python -m apps.worker --check
... Worker --check OK: kinds=email_send, reel_publish, scripted_render ...
```

Exit 0 en ambos. ✅

### Full pytest (suite completa, equivalente a `init.sh` salvo cleanups)

```
$ .venv/bin/python -m pytest -q
...
3 failed, 1093 passed, 1 deselected, 14 warnings in 588.09s (0:09:48)

FAILED tests/integration/test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_include_paused_dispatcher_state
FAILED tests/integration/test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_return_minimal_payloads
```

1093 passed = exactamente el número que el implementer reportó en iter 3 (`bash ./init.sh`).
3 fails = baseline histórico (mismo conjunto), no regresión introducida por la feature.
1 deselected = `test_galaxy_iter.py` (marker `visual_iter`). ✅

---

## Observaciones (no bloqueantes)

1. **Placeholder asset.** `assets/render-templates/galaxy-template.png` es byte-for-byte idéntico
   a `side-banner-template.png` (md5 `d11db3c7b6f24b894963a4d8886dbed8`). El selector de templates
   del frontend mostrará el preview del side_banner en lugar del galaxy. **Recomendación:**
   ejecutar `cp progress/galaxy_iter_3.png assets/render-templates/galaxy-template.png` antes de
   cerrar la sesión. Si se difiere, anotar como follow-up en `progress/history.md`. No bloqueante
   porque la migración y el endpoint funcionan; es un asset visual que el implementer dejó como
   stub deliberado, con el path correcto apuntando al PNG.

2. **`is_side_banner_like` alias.** El nombre del helper en `panels.py:99,365` ya incluye galaxy y
   side_banner. Si en el futuro entra un cuarto layout_variant que comparta geometría con galaxy
   pero no con side_banner, el nombre quedará semánticamente arrastrado. No bloqueante; refactor
   nominal cuando aplique.

3. **Helper `_resolve_side_banner_footer_radius` arrastra "footer" en el nombre aunque se aplica
   ahora también al top panel galaxy.** El implementer documentó la decisión en `impl_42.md`
   (línea 66): no renombrar para evitar refactor cross-cutting. Aceptable; follow-up nominal si
   se prioriza limpieza.

4. **Iter 3 vs referencia — diferencias remanentes:**
   - Logo agencia "CENTURY 21" (referencia) vs placeholder "Agency" (iter_3): fixture-driven,
     no scope. Cuando una agencia real suba su logo via `agency_logo` el render se materializa.
   - Foto de propiedad concreta de la referencia (casa con tejado, suburbano US) vs foto fixture
     (Cois Skona, Irlanda): fixture-driven, no scope.
   - Pesos tipográficos exactos: cascade de fuentes side_banner verbatim, aceptable v1.
   - Círculo central con logo agencia: explícitamente fuera de scope v1 (decisión del usuario).
   Todas anotadas en `impl_42.md` §Gap residual.

---

## Próximo paso

El implementer en su siguiente turno:

1. (Opcional pero recomendado) Promover el iter_3 al asset canónico:
   `cp progress/galaxy_iter_3.png assets/render-templates/galaxy-template.png`.
2. Marcar `feature_list.json` feature 42 status `in_progress` → `done`.
3. Mover el resumen de `progress/current.md` (entrada feature 42) a `progress/history.md` con
   prefijo `2026-05-18 — feature 42 galaxy_render_template`.
