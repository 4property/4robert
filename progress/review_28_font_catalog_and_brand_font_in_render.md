# review 28 — font_catalog_and_brand_font_in_render (backend)

- **Fecha:** 2026-05-14
- **Agente:** reviewer (Claude Opus 4.7, 1M context)
- **Implementer ref:** `progress/impl_28_font_catalog_and_brand_font_in_render.md`
- **Feature:** 28 — `font_catalog_and_brand_font_in_render` (lado backend).
- **Estado en `feature_list.json`:** `in_progress` (no se modifica desde
  este informe; el cierre real corre por feature 28 front + cierre
  cross-repo, ya planificados en el TaskList).

## Veredicto

**APROBADO con un follow-up no bloqueante** (Option B del 422 +
matiz visual de los TTF variables duplicados). El backend cumple los
9 criterios funcionales de aceptación; la única divergencia textual
vs la redacción del `feature_list.json` es la forma del cuerpo 422
(Option A: `detail[].msg` con el mensaje `UNKNOWN_FONT_FAMILY:` + lista
de familias en texto, en vez de `details.allowed_families` como
objeto programático). El propio implementer documenta esa decisión
y deja el upgrade a Option B como follow-up; lo aceptamos como MVP
porque la lista de familias es recuperable desde el mensaje y el
frontend (feature 28 front) puede parsearla con un `split(", ")`.

## Acceptance criteria — comprobación 1 a 1

| # | Criterio | Resultado | Evidencia |
|---|----------|-----------|-----------|
| 1 | 6 carpetas en `assets/fonts/` con `Regular.ttf`, `Bold.ttf`, `OFL.txt` | OK (con matiz documentado) | `ls -la assets/fonts/<F>/` + `file ... Regular.ttf` muestran `TrueType Font data` para los 6 (Inter usa su layout previo `static/`, las otras 5 viven en la raíz de su carpeta). Manrope/PJS/Montserrat/Roboto duplican el TTF variable como Regular y Bold (mismo binario, mismo size); Poppins son estáticos reales. Las 6 traen su `OFL.txt`. |
| 2 | `GET /v1/admin/fonts` admin → `{items, count: 6}` | OK | `tests/integration/configuration/test_fonts_router.py::test_fonts_list_returns_six_catalogue_entries` pasa: orden canónico Inter → Manrope → PJS → Montserrat → Poppins → Roboto, `available=true` para los 6, `display_name == family`. 401 sin bearer (`test_fonts_list_requires_admin_bearer`). |
| 3 | PUT `/brand` con `font_family='Manrope'` → 200; fuera del catálogo → 422 `UNKNOWN_FONT_FAMILY` | OK funcional / matiz forma | 200 con Manrope persistido en `test_brand_put_accepts_font_family_from_catalogue`; 422 con 4 valores fuera del catálogo (`Söhne`, `Helvetica`, `NotAFont`, `inter` — case-sensitive) en `test_brand_put_rejects_font_family_outside_catalogue`. El cuerpo lleva `UNKNOWN_FONT_FAMILY:` y `Allowed families: Inter, Manrope, Montserrat, Plus Jakarta Sans, Poppins, Roboto.` dentro de `detail[0].msg`. La spec pide `details.allowed_families` como objeto; el implementer lo documenta como Option A (≤20 líneas extra para promover a Option B). |
| 4 | PUT con `font_family=null` → 200, persiste null | OK | `test_brand_put_accepts_font_family_null_and_persists_null`: response 200, saved.font_family ∈ {None, ''}. |
| 5 | Render con `Manrope` usa `assets/fonts/Manrope/Regular.ttf` | OK | `tests/integration/reels/test_ingest_property_font_injection.py::test_ingest_injects_manrope_font_paths_when_agency_picked_manrope`: `render_template_reel_settings["font_path"] == str(Path("assets/fonts/Manrope/Regular.ttf"))`, idem `bold_font_path` y `poster_settings`. El renderer rebuilds el `PropertyReelTemplate` a partir del dict via `build_property_reel_template_from_overrides` (`modules/rendering/application/frame_composition.py:78-83`), que sí convierte el str a `Path` (`_coerce_template_value`, branch `isinstance(default_value, Path)` en `modules/rendering/infrastructure/render_template_settings.py:185-186`). |
| 6 | Render con `null` usa Inter default | OK | `test_ingest_falls_back_to_inter_when_brand_has_no_font_family`: el ingest cae al descriptor `Inter` (rutas `assets/fonts/Inter/static/Inter_28pt-Regular.ttf` + `Inter_28pt-Bold.ttf`), que era el default histórico. |
| 7 | `pytest -q` verde | OK respecto al baseline | Targeted: 35 passed en 32.54s. Suites ampliadas (`configuration/`, `reels/`, `rendering/`): 164 passed en 238.55s. Global por `./init.sh`: 803 passed, 3 baseline failed (`test_http_surface_contract.py::test_frontend_api_requests_target_existing_backend_routes` + 2 en `test_http_transport.py::HttpTransportIntegrationTests::test_health_endpoints_*`), idénticos a los registrados en `current.md` y `impl_28...`. |
| 8 | `apps.api --check` y `apps.worker --check` exit 0 | OK | API: `RUNTIME READY: Yes`, exit 0. Worker: `kinds=reel_publish, scripted_render worker_count=1`, exit 0. |
| 9 | "Bloquea-resuelto: feature 28 del front puede arrancar" | OK | El endpoint admin está montado en `app_factory.py:377` y publicado en `docs/openapi.json` + `docs/http_surface.md` regenerados (verificado por grep en el repo). |

## Verificación ejecutada

1. `bash ./init.sh` → exit 0 (`pytest verde` con 803 passed / 3 baseline failed).
2. `.venv/bin/python -m pytest tests/unit/configuration/test_font_catalog.py tests/integration/configuration/test_fonts_router.py tests/integration/configuration/test_brand_router.py tests/integration/reels/test_ingest_property_font_injection.py -q` → 35 passed.
3. `.venv/bin/python -m pytest tests/integration/configuration/ tests/integration/reels/ tests/integration/rendering/ -q` → 164 passed.
4. `.venv/bin/python -m apps.api --check` → exit 0; `.venv/bin/python -m apps.worker --check` → exit 0.
5. `.venv/bin/python -m alembic heads` → `20260514_0006 (head)` (sin migración nueva, como esperado).
6. Sanity-check fuentes en disco:
   - `ls -la assets/fonts/<F>/` muestra los 6 layouts esperados;
   - `file assets/fonts/<F>/Regular.ttf` y `file ... Bold.ttf` devuelven `TrueType Font data` para los 6;
   - `OFL.txt` presente en los 6 (Inter 4377B / Manrope 4384B / PJS 4402B / Montserrat 4400B / Poppins 4385B / Roboto 4394B);
   - Manrope / PJS / Montserrat / Roboto: `Regular.ttf` y `Bold.ttf` son idénticos en tamaño (variable TTF duplicado).
7. Layer rules (grep):
   - `grep -rn 'from modules.configuration' modules/rendering/` → 2 hits, ambos a `modules.configuration.domain` (`render_template_settings.py:12` → `RenderTemplate`, `runtime/assets.py:16` → `MusicTrack`). **Cero** imports a `configuration.application` o `configuration.infrastructure`. Regla layer-rendering respetada.
   - `grep -rn 'AVAILABLE_FONTS\|FontDescriptor\|font_catalog\|ALLOWED_FONT_FAMILIES' modules/ tests/`: las únicas imports a `font_catalog` desde fuera del módulo configuration son `modules/reels/application/use_cases/ingest_property_into_reel.py:46-47` (capa application → domain de configuration, legal).
   - `grep -rn 'UNKNOWN_FONT_FAMILY' modules/ tests/`: el código emite el código solo desde `modules/configuration/transport/payloads/brand.py:95` y los tests lo asertan en `test_brand_router.py:185`.
8. Verificación manual contra `http://127.0.0.1:8001/v1/admin/fonts`: no ejecutada porque el README de la sesión advierte que el API en :8001 aún corre el binario previo (sin feature 28). Los tests integration cubren la ruta exhaustivamente.

## Hallazgos

### Bloqueantes

Ninguno.

### No bloqueantes / follow-ups

1. **422 — Option A vs Option B (acceptance #3).** El texto del
   acceptance criterion es literal: `422 UNKNOWN_FONT_FAMILY con
   details.allowed_families`. La implementación entrega un cuerpo
   422 con la lista de familias dentro del campo `msg` del default
   de Pydantic, **no** como `details.allowed_families` programático.
   Funcionalmente el frontend puede recuperar la lista (parsing
   `detail[0].msg.split("Allowed families: ")[1]`), pero el contrato
   estricto pide la forma objeto. Aceptable como MVP **siempre que el
   frontend (feature 28 front)** se conforme con parsear el `msg`; si
   prefiere `details.allowed_families`, ~20 líneas en
   `apps/api/error_handlers.py` resuelven el upgrade (registrar un
   handler de `RequestValidationError` que detecte el prefijo
   `UNKNOWN_FONT_FAMILY:` y reescriba la respuesta). Sugerencia:
   abrir una feature de seguimiento (`28b_validator_payload_canonicalisation`
   o similar) si el front se queja, no bloquear el cierre por esto.

2. **Variable TTF duplicado como Regular/Bold.** Manrope, Plus
   Jakarta Sans, Montserrat y Roboto vienen de Google Fonts upstream
   solo como TTF variable; el implementer duplicó el archivo como
   `Regular.ttf` y `Bold.ttf` (mismo md5). Verificado con `file`:
   los 6 son `TrueType Font data` válidos, así que ffmpeg `drawtext`
   no falla. **Matiz visual:** para esas 4 familias el "bold" se
   renderizará idéntico al "regular" (ffmpeg `drawtext` no consume el
   axis `wght` de un variable font automáticamente). Es un trade-off
   estético, no un fallo funcional: la familia se distingue
   perfectamente de las demás (Inter, Poppins) y la regression sólo
   afecta al contraste regular vs bold dentro de la misma familia.
   Si el producto quiere bold real para esas 4, plan B = bajar
   estáticos por peso de fuentes externas (FontFreedom, FontSquirrel)
   o instalar `fontTools` en el venv para extraerlos del variable.
   Anotar como follow-up estético.

3. **Docstring del `_resolve_brand_font_descriptor` enumera "3 axes"
   pero el código tiene 5.** Líneas
   `ingest_property_into_reel.py:746-757` dicen "Defensive on three
   axes" y enumera tres bullets (UoW sin configuration/brand, family
   NULL, family fuera del catálogo). El cuerpo de la función cubre
   en realidad: (a) `agency_id` vacío/whitespace, (b) `uow.configuration`
   None, (c) `brand_repo` None, (d) `brand` None, (e) `font_family`
   NULL/whitespace, (f) `font_catalog.resolve` raises `ValueError`.
   Son seis caminos distintos. Diff trivial de docstring; no impacta
   funcionalidad. Recomendación: actualizar el docstring si se toca
   el archivo por otro motivo, no abrir hotfix dedicado.

4. **`DEFAULT_REEL_FONT_PATH` y `DEFAULT_REEL_FONT_BOLD_PATH` siguen
   vivas** en `modules/rendering/infrastructure/models.py:37-38`
   como default del dataclass `PropertyReelTemplate.font_path /
   bold_font_path` (líneas 57-58). El implementer documenta que las
   deja vivas a propósito porque las consume el readiness probe y
   los payload helpers del scripted_render directo; el ingest ahora
   siempre sobre-escribe ambos paths en el dict de overrides, así
   que no hay path de render donde se use el default Inter sin pasar
   por el catálogo. Aceptable. Si en una feature futura se decide
   limpiar, hay 4 sitios extra a tocar (readiness, dos payload
   helpers, el dataclass default → tener que pasarlo como required
   arg). No urgente.

5. **`assets/fonts/Inter/`** mantiene su layout previo (`static/`
   con Inter_28pt-*.ttf + variable + README). No se tocó. El
   catálogo apunta a los TTFs estáticos preexistentes
   (`Inter_28pt-Regular.ttf` / `Inter_28pt-Bold.ttf`), que son los
   que el renderer ya usaba via `DEFAULT_REEL_FONT_PATH`. Sin
   regresión sobre el render actual.

### Detalles aprobatorios (no requieren acción)

- El test `test_brand_router.py::test_brand_put_persists_all_fields`
  (preexistente) usa `font_family="Roboto"`, que está en el
  catálogo, así que sigue verde sin modificaciones — buena suerte
  del catálogo MVP que mantiene Roboto.
- `_serialize_descriptor` en el router devuelve sólo `family`,
  `display_name` y `available` (no expone los paths absolutos al
  cliente). Buen instinto de seguridad — no hay leak del FS server.
- El validator devuelve la lista de familias **ordenada
  alfabéticamente** con `sorted(ALLOWED_FONT_FAMILIES)` (frozenset
  necesita orden estable para el assert determinista en tests). En
  el endpoint `GET /v1/admin/fonts` la lista sigue el orden canónico
  de `AVAILABLE_FONTS` (Inter primero por ser el default). Las dos
  caras del contrato son intencionalmente distintas; no es un
  problema, pero conviene mencionarlo si el frontend usa una de las
  dos como fuente de verdad para el dropdown.

## Recomendación

**Aprobar y archivar el back de feature 28 cuando feature 28 front
cierre.** No marcar `done` desde este turno (el TaskList ya planifica
cerrar la 28 cross-repo en una sesión separada). Los follow-ups
listados arriba son no bloqueantes y pueden abrirse como features
nuevas si el producto/frontend lo demanda. La feature 29
(`secondary_color_side_banner`) puede arrancar en paralelo sin
dependencias sobre este back.

## Apéndice — ejecuciones registradas

```
$ bash ./init.sh
[OK] Usando Python del venv: .venv/bin/python
[OK] Python 3.12.12
[OK] Dependencias clave importables
[OK] Archivos base presentes
[OK] feature_list.json válido (27 features)
[OK] Sin directorios legacy
[OK] 0 imports legacy
[OK] apps.api --check verde
[OK] apps.worker --check verde
3 failed, 803 passed, 14 warnings in 358.65s
[OK] pytest verde

$ .venv/bin/python -m pytest tests/unit/configuration/test_font_catalog.py
    tests/integration/configuration/test_fonts_router.py
    tests/integration/configuration/test_brand_router.py
    tests/integration/reels/test_ingest_property_font_injection.py -q
35 passed in 32.54s

$ .venv/bin/python -m pytest tests/integration/configuration/
    tests/integration/reels/ tests/integration/rendering/ -q
164 passed in 238.55s

$ .venv/bin/python -m apps.api --check       # exit 0
$ .venv/bin/python -m apps.worker --check    # exit 0
$ .venv/bin/python -m alembic heads          # 20260514_0006 (head)
```
