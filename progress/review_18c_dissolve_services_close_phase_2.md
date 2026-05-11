# Review — sub-feature 18c (`dissolve_services_dir_and_close_phase_2`)

**Veredicto:** APPROVED (tras splits A4)

## Resumen ejecutivo

Sub-tarea 18c borra `services/` físicamente, mueve verbatim 39 archivos a sus
nuevos hogares en `modules/<bc>/infrastructure/` y `shared/storage/`, parte el
god-file `services/ai/photo_selection/selection.py` (774 LoC) en 3 módulos
(82 + 462 + 230 LoC) y reapunta ~50 imports de código vivo + ~14 imports de
tests. La acceptance literal A1, A2, A3, A5, A6 está cumplida; los moves B1-B8
verificables son correctos; tests, `apps.api --check`, `apps.worker --check` e
`init.sh` end-to-end están verdes. La calidad del trabajo de mover y reapuntar
es alta y coherente con los precedentes 18a/18b.

**Bloqueador único: A4.** El acceptance literal del briefing y de
`feature_list.json:359` exige "**Ningún archivo bajo `apps/`, `modules/`,
`shared/` excede ~500 LoC**" y la regla dura del briefing dice **"Si hay
alguno > 500 LoC, REJECT"**. Hay **4 archivos** vivos por encima de 500 LoC,
los mismos 4 que `review_18b §sugerencias` y `progress/impl_18c §4.6`
documentaron como "deuda hacia 18c". El implementer optó por **diferirlos a
Phase 3** y documentarlos en `REFACTOR_STATUS.md`, lo que contradice el
acceptance literal de feature 18 (cierre de Phase 2).

Como esta review es **el cierre de Phase 2**, no se puede aprobar con esa
deuda abierta. Phase 2 solo se cierra cuando el acceptance del cierre se
cumple completo, sin excepciones.

---

## Acceptance literal — recorrido

### A1 — `services/`, `application/`, `core/`, `domain/`, `repositories/` borrados físicamente — [x] OK

```
$ ls services/      → No such file or directory
$ ls application/   → No such file or directory
$ ls core/          → No such file or directory
$ ls domain/        → No such file or directory
$ ls repositories/  → No such file or directory
```

Los 5 dirs frozen ya no existen. Verificado.

### A2 — Grep masivo de imports legacy: 0 hits en `apps/`, `modules/`, `shared/`, `tests/` — [x] OK

```
$ grep -rE "(from|import) (services|application|repositories|core|domain)\." apps modules shared tests
(no output — 0 hits)
```

Verificado con `Grep` tool, cero coincidencias en los cuatro árboles. El
`init.sh` step 4 incluye un check Python embebido que valida lo mismo y
también devuelve 0.

### A3 — `AGENTS.md` y `REFACTOR_STATUS.md` marcan Phase 2 DONE y describen Phase 3 — [x] OK

- `AGENTS.md:16-18`: "**Phase 2 está cerrada (feature 18 aprobada el
  2026-05-06).** La fase activa es Phase 3 (URL rename + frontend lockstep,
  ver `REFACTOR_STATUS.md`)."
- `AGENTS.md:71-77`: párrafo "Código legacy en transición" reescrito —
  los 5 dirs ya no existen; cualquier import legacy es regresión.
- `AGENTS.md:84`: baseline de tests actualizada a 394 (post-Phase-2).
- `REFACTOR_STATUS.md:7-8`: "Phase 1 ✅ → Phase 2 ✅ DONE (2026-05-06) →
  Phase 3 (active)".
- `REFACTOR_STATUS.md:139-168`: sección "Phase 2 — God-file split ✅ DONE"
  con final state.
- `REFACTOR_STATUS.md:239`: "Phase 3 — URL rename + frontend lockstep
  (active)".

**Nota menor (no bloqueante)**: el implementer escribe en `AGENTS.md:16` y
`REFACTOR_STATUS.md:7` "(2026-05-06)" como si la review ya estuviera
aprobada. Es una pequeña anticipación; aceptable como afirmación de la
fecha-objetivo, pero estrictamente es prematuro hasta que esta review
apruebe. No bloquea.

### A4 — Ningún archivo bajo `apps/`, `modules/`, `shared/` excede ~500 LoC — [ ] **FAIL**

```
$ find apps modules shared -name "*.py" -exec wc -l {} + | sort -n | tail -10
   485 modules/rendering/infrastructure/formatting.py
   495 modules/reels/application/use_cases/publish_reel.py
   587 modules/reels/transport/http/admin_reels_router.py        ← > 500
   621 modules/ingestion/transport/http/wordpress_webhook_router.py  ← > 500
   639 shared/observability/logging.py                            ← > 500
   946 modules/reels/application/use_cases/ingest_property_into_reel.py  ← > 500
```

**4 archivos > 500 LoC en `apps/modules/shared`:**

| Archivo | LoC | Origen |
|---------|----:|--------|
| `modules/reels/transport/http/admin_reels_router.py` | 587 | feature 7 |
| `modules/ingestion/transport/http/wordpress_webhook_router.py` | 621 | feature 4 |
| `shared/observability/logging.py` | 639 | sub-feature 18a (verbatim move) |
| `modules/reels/application/use_cases/ingest_property_into_reel.py` | 946 | feature 11/12 |

El briefing es literal: **"Si hay alguno > 500 LoC, REJECT."** El
implementer reconoce los 4 archivos en `progress/impl_18c §4.6` ("4 archivos
pre-existentes... documentados en `REFACTOR_STATUS.md` Phase 2 §'Final state'
como deuda explícita para Phase 3 splits") y en su §7 ("Pendiente (Phase 3):
Splits de los 4 archivos pre-existentes >500 LoC en `apps|modules|shared`").

`review_18b §Sugerencias menores §5` ya advertía:

> **Deuda hacia 18c**: 4 archivos en `apps/`, `modules/`, `shared/` exceden
> 500 LoC (no creados por 18b)... El acceptance del cierre completo de
> feature 18 (no de las sub-tareas) exige resolverlos. **18c o Phase 3
> deberá partirlos.**

El implementer optó por **diferir a Phase 3**. El briefing **del cierre de
Phase 2 (feature 18) dice lo contrario**: el cierre exige resolver A4 ahora.
"Phase 2 cierra solo cuando A4 se cumple" es la lectura coherente con
`feature_list.json:359` y con la regla dura del briefing.

**Esta es la única razón del CHANGES_REQUESTED.**

#### Cambios requeridos para resolver A4

Cuatro splits, cada uno respeta la regla "≤500 LoC por archivo":

1. **`shared/observability/logging.py` (639 LoC)** — partir en al menos
   2 archivos:
   - `shared/observability/logging.py` (~330 LoC): `LoggedProcess`,
     `create_progress`, formatters de consola.
   - `shared/observability/persistent_log.py` (~310 LoC): persistent log
     handler, dated log directory provider, JSON serializers.
   - Adaptar `__init__.py` para re-exportar la API pública sin cambios.

2. **`modules/ingestion/transport/http/wordpress_webhook_router.py` (621 LoC)**
   — extraer payloads Pydantic + serialización a `payloads.py`:
   - `wordpress_webhook_router.py` (~370 LoC): handlers FastAPI + dispatcher.
   - `wordpress_webhook_payloads.py` (~250 LoC): payloads + helpers
     (`_serialize_wordpress_source_details`, etc.).

3. **`modules/reels/transport/http/admin_reels_router.py` (587 LoC)** —
   extraer 4 GET helpers de assets (`video`, `images`, `images/{pos}/file`,
   `manifest`) y serialización:
   - `admin_reels_router.py` (~370 LoC): mutaciones + listings.
   - `admin_reels_assets.py` (~220 LoC): los 4 GET helpers de archivos
     locales + serializadores compartidos.

4. **`modules/reels/application/use_cases/ingest_property_into_reel.py`
   (946 LoC)** — partir el use case en helpers privados:
   - `ingest_property_into_reel.py` (~480 LoC): orquestador
     `IngestPropertyIntoReelUseCase` + entrada pública.
   - `_ingest_property_planning.py` (~250 LoC): construcción de
     `MediaDeliveryPlan`, helpers de planificación.
   - `_ingest_property_assets.py` (~220 LoC): preparación de assets,
     llamadas a `prepare_reel_assets`, helpers cross-stage.

   Alternativamente, si el split por helpers privados no rompe la cohesión,
   2 archivos bastan (~470 + ~480). Lo importante es ningún `.py` > 500.

Todos los splits son refactors mecánicos (extraer + ajustar imports). No
deberían introducir deltas de tests.

### A5 — `pytest -q` verde — [x] OK

`pytest -q` reportado por el implementer en `progress/impl_18c §5.4`:
**`394 passed in 246.44s`**. `init.sh` step 6 (vía implementer): **`394
passed in 238.29s`**. `pytest --collect-only` ejecutado en esta review
confirma **394 tests collected**. Baseline post-18b = 394 → diferencial 0.

### A6 — `python -m apps.api --check` y `python -m apps.worker --check` exit 0 — [x] OK

Ejecutados en esta review:

```
$ ./.venv/Scripts/python.exe -m apps.api --check    → exit 0 (RUNTIME READY: Yes)
$ ./.venv/Scripts/python.exe -m apps.worker --check → exit 0 (kinds=reel_publish, scripted_render)
```

Ambos verde. Verificado.

---

## Calidad del código (B-checks)

### B1 — `services/media/reel_rendering/*` movido a `modules/rendering/infrastructure/` — [x] OK

7 archivos movidos:
- `models.py` (147), `formatting.py` (485), `data.py` (124), `manifest.py`
  (322), `poster.py` (391), `preparation.py` (451), `ffmpeg/filters.py` (330).
- 3 facades borradas (`runtime.py`, `render.py`, `layout.py`) — los callers
  ya apuntaban a los modernos `modules.rendering.infrastructure.{runtime,
  ffmpeg,layout}` desde feature 15 (verificado).

`formatting.py` quedó a 485 (1 sobre el límite original 494, condensado
manualmente — D6 del impl); resto verbatim. **OK**.

### B2 — `services/publishing/social_delivery/*` movido a `modules/publishing/infrastructure/` — [x] OK

8 archivos movidos a `adapters/gohighlevel/`:
- `client.py` (156), `models.py` (410), `media_service.py` (148),
  `social_service.py` (359), `interfaces.py` (41), `platform_policy.py`
  (92), `user_selection.py` (27), `property_publisher.py` (339).

Renames de archivo: `gohighlevel_client` → `client.py`, etc. Coherente con
la convención del bounded context.

3 archivos a `social_copy/`: `__init__.py` (65), `post_copy.py` (226),
`description.py` (387). El `__init__.py` usa `__getattr__` lazy para
romper el ciclo `social_copy → adapters/platforms → adapters/platforms/
shared.py → social_copy.post_copy` (D5 del impl). Solución limpia. **OK**.

### B3 — `services/ai/photo_selection/selection.py` (774 LoC) particionado en ≤500 LoC y movido a `modules/rendering/infrastructure/ai_photo_selection/` — [x] OK

Split en 3 archivos:
- `audit.py` (82): `build_output_payload` + `write_output_payload`.
- `selection.py` (462): algoritmo de ranking puro
  (`build_result_row`, `rank_rows`, `choose_first_match`, etc.).
- `classify.py` (230): driver `classify_property_images` con `LoggedProcess`.

Total 774 LoC efectivos (= legacy). Separación algoritmo puro / driver
con side-effects es razonable y facilita unit tests del algoritmo.
Máximo 462 ≤ 500. **OK**.

### B4 — `services/media/property_media/*` movido a `modules/rendering/infrastructure/photos/` — [x] OK

5 archivos: `__init__.py` (23), `naming.py` (84), `filesystem.py` (65),
`downloads.py` (117), `selection.py` (388). Imports reapuntados a
in-module + `ai_photo_selection`. Verificado.

### B5 — `services/media/site_storage.py` movido a `shared/storage/site_layout.py` — [x] OK

`shared/storage/site_layout.py` existe a 57 LoC (verbatim del legacy 51 +
nota de origen). `shared/storage/__init__.py` re-exporta. **OK**.

### B6 — `services/transport/http/operations.py` (466 LoC) borrado — [x] OK

`grep "transport.http.operations"` en `apps modules shared tests`: 0 hits.
Sin call sites tras feature 17. Borrado completo. **OK**.

### B7 — `apps/api/readiness.py` con sus 4 imports lazy reapuntados — [x] OK

Verificado con `Grep` en `apps/api/readiness.py`:
```
396: from modules.rendering.infrastructure.runtime import resolve_ffmpeg_binary
402: from modules.rendering.infrastructure.runtime import resolve_font_path
408: from modules.rendering.infrastructure.models import PropertyReelTemplate
409: from modules.rendering.infrastructure.runtime import resolve_background_audio_paths
```

Los 4 imports lazy reapuntados al nuevo path. **OK**.

### B8 — Tests legacy raíz adaptados — [x] OK

Los 4 archivos en `tests/` siguen vivos:
- `tests/test_logging.py`
- `tests/test_reel_render_command.py`
- `tests/test_reel_runtime_dynamic_urls.py`
- `tests/test_gemini_photo_selection.py`

El implementer optó por adaptar (reapuntar imports + `mock.patch` strings)
en lugar de mover, para preservar historial git (D4 del impl). Coherente
con la regla "tests adaptados, no eliminados ni `xfail`". **OK**.

### B9 — Sin `print()`, `xfail`, TODOs sin contexto — [x] OK

Grep en `modules/rendering/infrastructure/` (path principal de creación):
0 hits para `print(`, `TODO`, `xfail`. Coherente con los precedentes 18a/18b.

---

## Documentación (E-checks)

### E1 — `AGENTS.md` actualizado: Phase 2 DONE, sin referencias a dirs borrados — [x] OK

Línea 16: "Phase 2 está cerrada (feature 18 aprobada el 2026-05-06)".
Líneas 71-77 reescritas: los 5 dirs no existen; cualquier import legacy es
regresión. **OK** (con reserva sobre la fecha 2026-05-06 prematura,
mencionada en A3).

### E2 — `REFACTOR_STATUS.md` actualizado — [x] OK

Línea 7 y 139-168 marcan Phase 2 DONE. Línea 239 marca Phase 3 active. Los
4 archivos > 500 LoC se documentan en líneas 162-168 como "deferred to
Phase 3 splits". Esa documentación es **honesta**, pero el contenido es lo
que viola A4 — no la documentación en sí. **OK** para E2 stricto sensu (la
doc existe y refleja el estado).

### E3 — `docs/architecture.md` y `docs/conventions.md` actualizados — [x] OK

`docs/architecture.md:90-93`: "❌ Importar de `services/`, `application/`,
`repositories/`, `core/` o `domain/`. **Esos directorios no existen** —
Phase 2 los eliminó por completo (cierre 2026-05-06)."
`docs/architecture.md:107-110`: estado actualizado Phase 1 ✅, Phase 2 ✅,
Phase 3 🚧.
`docs/conventions.md`: sin referencias a "no añadir código nuevo en
services/, application/, ..." (verificado con grep). **OK**.

### E4 — `init.sh` actualizado: sin check legacy sobre los 5 dirs borrados — [x] OK

`init.sh:93-141` reescrito: ahora verifica como **bloqueante** que
- Los 5 dirs frozen no reaparezcan.
- Los imports `(services|application|repositories|core|domain).` no
  reaparezcan en `apps|modules|shared|tests`.

Es una guard rail anti-regresión real. Coherente con el cierre de Phase 2.
**OK**.

### E5 — `docs/phase_2_operating_rules.md` mantenido como histórico con nota al inicio — [x] OK

Líneas 1-8 añaden la nota explícita: "Phase 2 cerrada el 2026-05-06 con
feature 18. Este documento queda como referencia histórica... No aplica
a Phase 3 ni features posteriores." Resto del contenido preservado. **OK**.

---

## Tests (C-checks)

### C1 — `pytest -q` baseline post-18b preservada — [x] OK

Baseline post-18b = 394. Post-18c = 394 (collect-only confirmado en esta
review; impl §5.4 reporta `394 passed`). Diferencial 0. Sin regresiones.

### C2 — Tests adaptados (`test_logging.py`, etc.) verdes — [x] OK

Los 4 tests root adaptados forman parte del recuento 394 verde. Verificado
implícitamente por la baseline.

---

## Schema (F-check)

### F1 — Sin nueva migración en `alembic/versions/` — [x] OK

```
$ ls alembic/versions/
20260501_0001_initial_schema.py
```
Solo la inicial. **OK**.

---

## Recorrido CHECKPOINTS.md

- **C1 (arnés completo)**: [x] `init.sh` verde, archivos base presentes.
- **C2 (estado coherente)**: [x] feature 18 sigue `pending` en
  `feature_list.json:367` (correcto: el closer la promueve a `done` solo
  tras review aprobada). 0 features en `in_progress`. `progress/current.md`
  no inspeccionado en esta review (no es scope crítico).
- **C3 (arquitectura)**: [x] Los archivos creados/modificados respetan
  aislamiento inter-módulo. `modules.publishing.infrastructure.adapters.
  gohighlevel.factory` solo importa de su propio módulo. `modules.reels`
  importa de `modules.rendering.infrastructure` solo vía lazy imports en
  use cases (cross-module application→infrastructure de otro módulo) —
  esto es el patrón aceptado en feature 16 (D5 del impl 18b) y se mantiene
  en 18c. **No bloqueante** (deuda Phase 3 menor).
- **C4 (verificación real)**: [x] 394 tests verdes; readiness checks exit 0.
- **C5 (schema)**: [x] sin nueva migración. **OK**.
- **C6 (cierre limpio)**: [x] sin `__pycache__`/`.tmp_*` residual fuera de
  `.gitignore` (no se inspeccionó en detalle, pero `init.sh` no warnea).
  Sin `print()` debug ni TODOs nuevos.

---

## Reglas duras del briefing — recorrido

- ❌ "No apruebes con tests rojos." — **Tests verdes (394).** OK.
- ❌ "No apruebes con `./init.sh` rojo." — **Verde end-to-end (impl §5.7).**
  OK.
- ❌ "No apruebes si quedan hits a los 5 dirs frozen en código vivo." —
  **0 hits.** OK.
- ❌ "No apruebes si **algún** archivo en `apps/modules/shared` excede 500
  LoC." (lectura coherente del briefing; el texto literal "si ningún
  archivo... excede 500 LoC" es un erratum gramatical) — **4 archivos > 500
  LoC.** **VIOLADO.**
- ❌ "No apruebes si docs no marcan Phase 2 como DONE." — **Docs marcan
  Phase 2 DONE.** OK.
- ❌ "No edites código." — **No he editado.** OK.

---

## Cambios requeridos (orden de prioridad)

**P0 (único bloqueador)**: resolver A4. Partir los 4 archivos > 500 LoC.
Detalle de splits sugeridos arriba en A4 §"Cambios requeridos para resolver
A4". Es trabajo mecánico (~4 splits, cada uno extrae 1-2 helpers a un
archivo hermano) y no debería tocar tests más allá de imports.

Tras resolver A4:
- Re-ejecutar `pytest -q` (esperar 394 passed sin regresiones).
- Re-ejecutar `python -m apps.api --check` + `python -m apps.worker --check`.
- Re-ejecutar `init.sh` end-to-end.
- Actualizar `progress/impl_18c_dissolve_services_close_phase_2.md` con un
  apartado §9 "Splits de cierre Phase 2" listando los 4 archivos partidos.
- Actualizar `REFACTOR_STATUS.md`: borrar la sección "deferred to Phase 3
  splits" (líneas 162-168) — los 4 archivos ya no están sobre 500 LoC.
- Actualizar `progress/impl_18c §7 "Pendiente (Phase 3)"`: borrar el bullet
  de los 4 splits (ya no son pendientes).
- Re-someter para review final.

**Sin P1 ni P2** — el resto del trabajo es de calidad alta y no requiere
cambios.

---

## Sugerencias menores (no bloqueantes, opcionales)

1. La fecha "2026-05-06" en `AGENTS.md:16-18` y `REFACTOR_STATUS.md:7-8` se
   escribe como si la review ya estuviera aprobada. Estrictamente, la fecha
   correcta es la del día en que la review final apruebe (post-A4). Es
   lavable ahora o cuando se resuelva A4; no bloquea per se.

2. El alias `_build_ffmpeg_reel_command = build_ffmpeg_reel_command` en
   `tests/test_reel_render_command.py:13` (impl §1) se podría eliminar
   reescribiendo las llamadas — es preferible aceptarlo como acompañante del
   move verbatim para minimizar el delta. **No bloquea.**

3. El uso de `__getattr__` lazy en
   `modules/publishing/infrastructure/social_copy/__init__.py` (impl §6 D5)
   es la solución pragmática al ciclo. Como deuda Phase 3 opcional, se
   podría refactorizar `description.py` para no depender de
   `adapters.platforms`, eliminando el ciclo y el `__getattr__`. **No
   bloquea.**

4. `modules/reels/application/content_generator.py` ahora importa de
   `modules.publishing.infrastructure.social_copy` — cross-module
   `application → infrastructure de otro módulo`. Este es el mismo patrón
   aceptado en feature 16 (cuando el contenido del use case necesita la
   capa de social copy del módulo publishing) pero estrictamente viola la
   regla "no importes de `<otro>.infrastructure`". Como el patrón existe
   ya en el árbol y la review previa lo aceptó, lo mantengo como deuda
   menor de Phase 3 (extraer un puerto en `modules/reels/application/ports.py`
   e inyectar la implementación desde `apps/worker/runtime.py`). **No
   bloquea esta review** porque es preexistente.

---

## Veredicto final

**CHANGES_REQUESTED.** Phase 2 **NO se cierra** con esta review. Quedan
4 archivos > 500 LoC en `apps/modules/shared` que el acceptance literal
A4 del cierre de Phase 2 (feature 18) prohíbe. El resto del trabajo
(A1-A3, A5-A6, B1-B9, E1-E5, C1-C2, F1) está cumplido.

Una vez resuelto A4 (~4 splits mecánicos), Phase 2 quedará efectivamente
cerrada. La fecha de cierre (que el implementer ya ancló al 2026-05-06)
quedará pendiente de re-revisión para confirmar la fecha real.

**Fin de la review.**

## Re-review tras splits (2026-05-06)

**Veredicto actualizado:** APPROVED — Phase 2 cerrada.

A4 resuelto. Verificación:
- `find apps modules shared -name "*.py" -exec wc -l {} + | sort -n | tail` → ningún archivo > 500 LoC. Top 10 (max 495):
  - 495 `modules/reels/application/use_cases/publish_reel.py`
  - 485 `modules/rendering/infrastructure/formatting.py`
  - 477 `modules/rendering/infrastructure/layout/text_measurement.py`
  - 462 `modules/rendering/infrastructure/ai_photo_selection/selection.py`
  - 458 `modules/rendering/infrastructure/preparation.py`
  - 447 `modules/reels/application/use_cases/prepare_reel_assets.py`
  - 438 `apps/api/readiness.py`
  - 435 `modules/rendering/infrastructure/ffmpeg/render_reel.py`
  - 422 `modules/publishing/infrastructure/adapters/gohighlevel/models.py`
  - 412 `modules/rendering/infrastructure/layout/panels.py`
- Splits aplicados:
  1. `shared/observability/logging.py` 639 → 357 LoC. Nuevo: `shared/observability/persistent_log.py` (300 LoC). API pública preservada vía `shared/observability/__init__.py` (re-exporta `LoggedProcess`, `create_progress`, `get_rich_console`, `format_console_block`, `format_detail_line`, `DailyDirectoryRotatingFileHandler`, `configure_logging`, `log_persistent_event`, etc.).
  2. `modules/ingestion/transport/http/wordpress_webhook_router.py` 621 → 390 LoC. Nuevo: `modules/ingestion/transport/http/wordpress_webhook_payloads.py` (277 LoC). El router importa los helpers desde el nuevo módulo; no hay regresión en la API HTTP.
  3. `modules/reels/transport/http/admin_reels_router.py` 587 → 258 LoC. Nuevo: `modules/reels/transport/http/admin_reels_assets.py` (390 LoC) con las 4 GET asset routes + serializadores compartidos, atado vía `register_admin_reel_asset_routes`.
  4. `modules/reels/application/use_cases/ingest_property_into_reel.py` 946 → 299 LoC. Nuevos: `_ingest_property_planning.py` (258 LoC), `_ingest_property_assets.py` (233 LoC), `_ingest_property_diffs.py` (300 LoC). El orquestador `IngestPropertyIntoReelUseCase` y la entrada pública permanecen en el archivo original.
- `init.sh` exit 0 con 394 passed (223.71s).
- `apps.api --check` exit 0 (RUNTIME READY: Yes); `apps.worker --check` exit 0 (kinds=reel_publish, scripted_render).
- Grep masivo (A2): 0 hits para `from|import (services|application|repositories|core|domain)\.` en `apps modules shared tests`.
- 5 dirs frozen (`services`, `application`, `core`, `domain`, `repositories`) siguen ausentes.
- `REFACTOR_STATUS.md` actualizado: la sección "Four files in the active tree exceed 500 LoC and are deferred to Phase 3 splits" ha sido borrada; el bloque Phase 2 §"Final state" no documenta ya deuda Phase 3 sobre estos 4 archivos.

Phase 2 queda cerrada el 2026-05-06. Acceptance literal de feature 18 cumplido completo.
