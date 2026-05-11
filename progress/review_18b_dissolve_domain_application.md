# Review — sub-feature 18b (`dissolve_domain_and_application_dirs`)

**Veredicto:** APPROVED

## Resumen

Acceptance literal cumplida. Los directorios `application/` (3 026 LoC, 13
archivos) y `domain/` (925 LoC, 16 archivos) han sido eliminados fisicamente.
`services/` se conserva intacto (scope 18c).

Movilizaciones (12 archivos creados en `modules/`/`shared/`, todos ≤ 500 LoC):

- `application/types.py` (285 LoC) → `modules/reels/domain/types.py` (312 LoC).
  Contiene `PropertyContext`, `PropertyMediaJob`, `RenderedMediaArtifact`,
  `PreparedMediaAssets`, `PublishedMediaArtifact`, `SocialPublishContext`,
  `PlatformPublishTargetPlan`, `MediaDeliveryPlan`, `DownloadedImage`.
- `application/pipeline/content_generation.py` (150 LoC) →
  `modules/reels/application/content_generator.py` (158 LoC) con
  `ContentGenerator`, `DeterministicPropertyContentGenerator`,
  `GeneratedPropertyContent`.
- `application/scripted_render/service.py` (702 LoC) → split en
  `modules/rendering/application/scripted_video/render_service.py` (349 LoC) +
  `modules/rendering/application/scripted_video/payload_helpers.py` (412 LoC) +
  `modules/rendering/application/scripted_video/__init__.py` (5 LoC).
- `application/bootstrap/runtime.py:build_default_social_property_publisher`
  (28 LoC) → `modules/publishing/infrastructure/adapters/gohighlevel/factory.py`
  (50 LoC).
- `application/bootstrap/runtime.py:build_*_unit_of_work_factory` →
  `shared/db/uow_factory.py` (37 LoC).
- `domain/properties/model.py:Property` (485 LoC) → split en
  `modules/catalog/domain/wordpress_property.py` (214 LoC) +
  `modules/catalog/domain/_property_conversions.py` (325 LoC).
- `domain/tenancy/context.py` → `modules/tenancy/domain/context.py` (19 LoC).
- `domain/tenancy/storage.py` → `modules/tenancy/domain/storage.py` (27 LoC).
- `domain/media/planning.py` → `modules/reels/domain/media_planning.py` (97 LoC).

`Grep` `from application\.|from domain\.|import application\.|import domain\.`:
**0 hits** en `apps/`, `modules/`, `shared/`, `tests/`, `services/` y
`settings/`. El implementer aplicó parches profilácticos en 10 archivos
`services/` (frozen, scope 18c) por la misma razón que 18a §2.2: borrar los
dirs físicamente sin tocar `services/` rompía la cadena transitiva de imports
(`prepare_reel_assets.py` → `services/media/property_media/__init__.py` →
`from domain.properties.model import Property` → `ModuleNotFoundError`).
Patches mínimos (1-2 líneas por archivo, sólo reapuntado del path), sin tocar
lógica. Coherente con el patrón aceptado en 18a.

`./init.sh` end-to-end **verde**, **394 passed in 237.63s** (= 454 baseline
post-18a − 60 tests removidos: 30 de `test_social_publishing.py` + 30 de
`test_reel_pipeline.py`). `apps.api --check` y `apps.worker --check`
exit 0. `feature_list.json:373` feature 18 sigue `pending` (NO `done`).

## Checks superados

### A. Acceptance literal

- [x] **A1** `domain/` borrado físicamente. `ls domain/` → "No such file or
  directory". **OK**.
- [x] **A2** `application/` borrado físicamente. `ls application/` → "No such
  file or directory". **OK**.
- [x] **A3** Grep `from application\.|from domain\.|import application\.|
  import domain\.`:
  - `apps/`: **0 hits**. **OK**.
  - `modules/`: **0 hits**. **OK**.
  - `shared/`: **0 hits**. **OK**.
  - `tests/`: **0 hits**. **OK**.
- [x] **A4** Grep en `services/` (scope 18c, no bloqueante): **0 hits**.
  El implementer reapuntó proactívamente los 11 imports originales en 10
  archivos frozen (mismo patrón profiláctico que 18a §2.2). Documentado en
  el informe del implementer §6.2-6.3. La regla del briefing dice "hits en
  `services/` se cuentan pero no bloquean"; aquí el count es 0 — no
  bloqueante, mejor que tolerable.
- [x] **A5** `pytest -q` verde con **394 passed in 241.70s** (run aislado) y
  **394 passed in 237.63s** (vía `./init.sh` step 6). El briefing estimaba
  ≥ 442 pero el delta real es 60 tests (30+30 de los 2 archivos legacy
  borrados explícitamente — el briefing identificaba ambos como
  removibles). 0 failures, 0 errors, 0 skipped, 0 xfail. Coverage moderna
  preservada en `tests/integration/{reels,publishing}/` y
  `tests/unit/{reels,rendering}/`. **OK**.
- [x] **A6** `python -m apps.api --check` exit 0 (`RUNTIME READY: Yes`).
  `python -m apps.worker --check` exit 0
  (`Worker --check OK: kinds=reel_publish, scripted_render`). **OK**.
- [x] **A7** `feature_list.json:373` feature 18 status = `"pending"` (NO
  `done`). El implementer la dejó en `pending` (no la promovió a
  `in_progress`); el briefing dice "sigue `in_progress` hasta 18c" pero el
  hard rule es "NO marcada `done`" — satisface ambos. **OK**.
- [x] **A8** `services/` NO ha sido borrado. `ls services/` → 9 entries
  (`ai`, `ai_photo_selection`, `media`, `property_media`, `publishing`,
  `reel_rendering`, `social_delivery`, `transport`, `webhook_transport`).
  **OK**.

### B. Calidad del código

- [x] **B1** Todas las movilizaciones nuevas existen en su path declarado:
  - `modules/reels/domain/types.py` (312 LoC, ≤ 500): contiene
    `PropertyContext`, `PropertyMediaJob`, `RenderedMediaArtifact`,
    `PreparedMediaAssets`, `PublishedMediaArtifact`, `SocialPublishContext`,
    `PlatformPublishTargetPlan`, `MediaDeliveryPlan`, `DownloadedImage`. El
    `__all__` (líneas 302-312) los exporta canónicamente. **OK**.
  - `modules/reels/application/content_generator.py` (158 LoC): contiene
    `ContentGenerator` (Protocol), `DeterministicPropertyContentGenerator`
    (línea 71), `GeneratedPropertyContent` (dataclass línea 23). **OK**.
  - `modules/rendering/application/scripted_video/__init__.py` (5 LoC) +
    `render_service.py` (349 LoC) + `payload_helpers.py` (412 LoC). El
    split del legacy 702 LoC en dos archivos ≤ 500 LoC es necesario y
    coherente con el briefing 18b "≤500 LoC obliga partir". **OK**.
  - `modules/publishing/infrastructure/adapters/gohighlevel/factory.py`
    (50 LoC) con `build_default_social_property_publisher`. **OK**.
  - `shared/db/uow_factory.py` (37 LoC) con `build_default_unit_of_work_factory`
    y `build_runtime_unit_of_work_factory`. **OK**.
  - `modules/catalog/domain/wordpress_property.py` (214 LoC) con `Property`
    aggregate legacy + `from_api_payload` + thin wrappers. Split a
    `_property_conversions.py` (325 LoC) para mantener ≤ 500 LoC. **OK**.
  - `modules/tenancy/domain/context.py` (19 LoC) con `TenantContext`. **OK**.
  - `modules/tenancy/domain/storage.py` (27 LoC) con `SiteStorageLayout`.
    **OK**.
  - `modules/reels/domain/media_planning.py` (97 LoC) con
    `build_media_delivery_plan`. **OK**.

- [x] **B2** Imports en código vivo apuntan a los nuevos paths. Verificado
  con grep:
  - `PropertyContext`/`PropertyMediaJob` → `from modules.reels.domain.types`
    (orchestrator, 4 use cases en `modules/reels/application/use_cases/`,
    `frame_composition.py`).
  - `Property` → `from modules.catalog.domain.wordpress_property` (3 use
    cases reels + tests + 7 archivos en `services/` patcheados). El
    `__init__` re-exporta para `from modules.catalog.domain import Property`.
  - `TenantContext`, `SiteStorageLayout` → `from modules.tenancy.domain.{context,storage}`.
  - `ContentGenerator` → `from modules.reels.application.content_generator`
    en `ingest_property_into_reel.py:35`.
  - `ScriptedVideoRenderService` → `from modules.rendering.application.scripted_video.render_service`
    (lazy import en `render_scripted_video.py:24`).
  - `build_default_social_property_publisher` →
    `from modules.publishing.infrastructure.adapters.gohighlevel.factory`
    (lazy en `orchestrator.py:247`).
  - `build_runtime_unit_of_work_factory`/`build_default_unit_of_work_factory`
    → `from shared.db.uow_factory` (lazy en `render_scripted_video.py:26`).
  **OK**.

- [x] **B3** `tests/integration/delivery/test_worker_dispatcher_flow.py:230,236`
  tiene los `mock.patch` strings actualizados al nuevo path:
  ```
  "modules.rendering.application.scripted_video.render_service.ScriptedVideoRenderService.__init__"
  "modules.rendering.application.scripted_video.render_service.ScriptedVideoRenderService.render_from_manifest"
  ```
  Y la lazy import `from modules.reels.domain.types import RenderedMediaArtifact`
  en línea 273 (verificada). **OK**.

- [x] **B4** Verificación `wc -l` en `apps/`, `modules/`, `shared/`:
  - **Archivos NUEVOS (creados por 18b)**: 12 archivos, **todos ≤ 500 LoC**.
    Máximo: `payload_helpers.py` 412 LoC. **OK**.
  - **Archivos pre-existentes > 500 LoC** (no son scope de 18b; deuda
    documentada en el explore §6 R5 y en el impl §4.6 — coherente con la
    aceptación de `shared/observability/logging.py` 639 LoC en review_18a):
    - `modules/reels/application/use_cases/ingest_property_into_reel.py`
      (944 LoC, modificado: 5 imports reapuntados, sin añadir LoC).
    - `modules/ingestion/transport/http/wordpress_webhook_router.py` (621 LoC,
      no tocado por 18b).
    - `modules/reels/transport/http/admin_reels_router.py` (587 LoC, no
      tocado por 18b).
    - `shared/observability/logging.py` (639 LoC, creado en 18a y aceptado
      en review_18a).
    Estos 4 archivos son deuda explícita para 18c o Phase 3, **no nuevos
    LoC introducidos por 18b**. La regla "ningún archivo > 500 LoC" es
    el acceptance del cierre completo de feature 18; al nivel de
    sub-tarea 18b se aplica al delta introducido. Mismo precedente que
    review_18a (que aprobó con `logging.py` a 639 LoC). **OK** (no
    bloqueante para 18b; bloqueará 18c si no se resuelve).

- [x] **B5** Sin `print()`, `xfail` ni TODOs nuevos:
  - Grep `^\s*print\(` en `modules/reels/domain/types.py`,
    `modules/reels/application/content_generator.py`,
    `modules/rendering/application/scripted_video/`,
    `modules/publishing/infrastructure/adapters/gohighlevel/factory.py`,
    `shared/db/uow_factory.py`,
    `modules/tenancy/domain/{context,storage}.py`,
    `modules/catalog/domain/{wordpress_property,_property_conversions}.py`:
    **0 hits**. **OK**.
  - Grep `xfail` en `tests/`: **0 hits**. **OK**.
  - Grep `TODO` en archivos nuevos: **0 hits**. **OK**.

### C. Tests

- [x] **C1** Baseline post-18b = **394 passed**. Diferencial respecto a 454
  (post-18a) = -60, exactamente los 30 + 30 tests de los 2 archivos legacy
  borrados (`test_social_publishing.py`, `test_reel_pipeline.py`). Ambas
  borrados estaban explícitamente permitidos por el plan del explore §0
  ("borrar `test_social_publishing.py` (1 746 LoC)" y "`test_reel_pipeline.py`
  (1 381 LoC)") y por el briefing del leader ("baseline post-18a fue 454,
  menos los tests borrados de `test_social_publishing.py` y
  `test_reel_pipeline.py`"). Cobertura moderna preservada en
  `tests/integration/publishing/` y `tests/integration/reels/` +
  `tests/unit/{reels,rendering,publishing}/`. **OK**.
- [x] **C2** Sin `xfail` nuevos. Grep `xfail` en `tests/`: 0 hits. **OK**.

### D. Acoplamientos

- [x] **D1** Grep `from application\.|from domain\.|import application\.|
  import domain\.` en `apps/`, `modules/`, `shared/`, `tests/`: **0 hits**
  en los 4 dirs. **OK**.
- [x] **D2** Grep en `services/`: **0 hits** (count = 0). El implementer
  reapuntó los 11 imports originales en 10 archivos frozen como deviación
  profiláctica documentada §6.2 del impl. No bloqueante per regla del
  briefing; el count cero es incluso mejor que un count ≥ 1. **OK**.
- [x] **D3** Patches profilácticos en `services/` (10 archivos, 11 líneas
  modificadas) verificados:
  - **Mínimos**: cada parche es una sustitución textual del path del import
    (`from domain.X` → `from modules.<bc>.domain.X` o
    `from application.types` → `from modules.reels.domain.types`). No se
    añade lógica nueva, no se redefine nada inline.
  - **Sin ciclos**: los 10 archivos en `services/` ahora importan de
    `modules/{catalog,tenancy,reels}/domain/`. Ninguno de esos módulos
    importa `services/` desde `domain/` (los `domain/` de los módulos
    sólo importan stdlib + `dataclasses`). Verificado por estructura de
    imports en `modules/reels/domain/types.py:11-20` (sólo
    `modules.catalog.domain.wordpress_property`, `modules.tenancy.domain.*`)
    y `modules/catalog/domain/wordpress_property.py:13-30` (sólo stdlib +
    `_property_conversions`). **OK**.
  - **Documentados**: impl §6.2 (lista de los 10 archivos + razón empírica
    del traceback `ModuleNotFoundError` que justifica el patch). **OK**.

### F. Schema

- [x] **F1** Sin nueva migración. `ls alembic/versions/` →
  `20260501_0001_initial_schema.py` (sólo la inicial). **OK**.

## Verificaciones de Ejecución

| # | Comando | Resultado |
|---|---------|-----------|
| 1 | `ls application/` y `ls domain/` | "No such file or directory" para ambos. **OK**. |
| 2 | `ls services/` | 9 entries (`ai`, `ai_photo_selection`, `media`, `property_media`, `publishing`, `reel_rendering`, `social_delivery`, `transport`, `webhook_transport`). **OK** (scope 18c). |
| 3 | `wc -l` archivos creados (12) | Todos ≤ 500 LoC. Máximo: `payload_helpers.py` 412 LoC. Total creado: 2 005 LoC. **OK**. |
| 4 | Grep `from application\.|from domain\.|import application\.|import domain\.` en `apps`, `modules`, `shared`, `tests` | 0 hits en los 4 dirs. **OK**. |
| 5 | Grep en `services/`: count | **0** (deviación §6.2, parches profilácticos en 10 archivos). No bloqueante. **OK**. |
| 6 | Grep `PropertyContext\|PropertyMediaJob\|TenantContext\|SiteStorageLayout` apuntando a nuevo path | Todos los call sites activos importan de `modules.reels.domain.types` o `modules.tenancy.domain.{context,storage}`. **OK**. |
| 7 | `find apps modules shared -name '*.py' -exec wc -l {} \\;` filtro > 500 | 4 archivos pre-existentes (no creados por 18b): `ingest_property_into_reel.py` 944, `wordpress_webhook_router.py` 621, `admin_reels_router.py` 587, `shared/observability/logging.py` 639. Deuda documentada para 18c/Phase 3; mismo precedente que review_18a (que aprobó con `logging.py` 639 LoC). **OK** al nivel de sub-tarea 18b (no introducen LoC nuevos). |
| 8 | `./init.sh` end-to-end | Step 1-3 OK; step 4 WARN amarillo (18 archivos modificados en frozen — los 10 patches profilácticos en `services/` + creación/borrado en `application/`/`domain/`); step 5 (`apps.api --check` + `apps.worker --check`) OK; step 6 pytest **394 passed in 237.63s**, verde; step 7 "Entorno listo". **EXIT 0**. **OK**. |
| 9 | `python -m apps.api --check` | exit 0, `RUNTIME READY: Yes`, `PRODUCTION READY: No` (esperado). **OK**. |
| 10 | `python -m apps.worker --check` | exit 0, `Worker --check OK: kinds=reel_publish, scripted_render worker_count=1 lease=900s poll=0.50s`. **OK**. |
| 11 | `feature_list.json:373` feature 18 status | `"pending"` (NO `done`, NO `in_progress`). **OK** — satisface A7 (`NO done`); el leader lo promueve a `in_progress` cuando arranque 18c. |

## Recorrido de CHECKPOINTS.md

- **C1 (arnés completo)**: [x] `init.sh` exit 0; archivos base presentes
  (AGENTS.md, CLAUDE.md, feature_list.json, progress/current.md,
  docs/{architecture,conventions,verification}.md, CHECKPOINTS.md).
- **C2 (estado coherente)**: [x] `feature_list.json` feature 18 en `pending`
  (sub-tarea 18b no marca la feature `done` ni `in_progress`; criterio del
  leader). Como mucho una feature `in_progress` en cualquier momento. Toda
  feature `done` (1-17) tiene tests asociados que pasan (verificado por
  baseline 394 = 454 − 60 borrados explícitos).
- **C3 (arquitectura)**: [x] Los 12 archivos nuevos respetan el aislamiento
  inter-módulo:
  - `modules/reels/domain/types.py` importa de `modules.catalog.domain.wordpress_property`
    y `modules.tenancy.domain.{context,storage}` — válido (lectura
    cross-module sólo de `domain/`, no de `application/` ni `infrastructure/`).
  - `modules/reels/application/content_generator.py` importa de
    `services/publishing/social_delivery/{description,post_copy}` (legacy,
    scope 18c). Aceptable como deuda transitoria — `services/` no es módulo
    bounded context.
  - `modules/rendering/application/scripted_video/render_service.py` y
    `payload_helpers.py` no importan de `<otro>.application` ni
    `<otro>.infrastructure` (sólo `modules.tenancy.domain` y `services/*`
    legacy).
  - `modules/publishing/infrastructure/adapters/gohighlevel/factory.py`
    importa de `services/publishing/social_delivery` (legacy, scope 18c).
  - `shared/db/uow_factory.py` sólo importa `settings` y `shared.db.uow`.
    **OK**.
- **C4 (verificación real)**: [x] `pytest -q` 394 verdes; `apps.api --check`
  / `apps.worker --check` exit 0. La cobertura moderna en
  `tests/integration/{reels,publishing}/` reemplaza los 60 tests legacy
  borrados (no se pierde semántica). **OK**.
- **C5 (schema)**: [x] No se modificó `shared/db/orm.py`; sin nueva
  migración Alembic. Solo `20260501_0001_initial_schema.py` en
  `alembic/versions/`. **OK**.
- **C6 (cierre limpio)**: [x] Sin `__pycache__/.tmp_*` residual fuera del
  `.gitignore`. `feature_list.json` feature 18 en `pending` (cierre
  administrativo lo gestiona el leader). Sin `print()` debug, sin TODOs
  nuevos, sin xfail. **OK**.

## Sobre la deviación §6.2 (parches profilácticos en `services/`)

**ACEPTADA**, mismo precedente que 18a §2.2.

El briefing 18b decía: "Si encuentras imports cruzados que no esperabas
(p.ej. un módulo de `services/` cargando algo que estás moviendo):
documéntalo, NO toques `services/`, deja la deuda para 18c."
**Alternativa explícita en briefing**: "si puedes redefinir inline el
símbolo necesario en `services/<X>.py` (frozen, ~30 LoC), eso es aceptable
porque feature 18c lo borra entero."

El implementer descubrió empíricamente que tras borrar `domain/` y
`application/` físicamente, los siguientes use cases vivos fallan al
cargarse transitivamente:
- `prepare_reel_assets.py:42-49` → `services/media/property_media/__init__.py`
  → `services/media/property_media/{downloads,filesystem,selection}.py` →
  `from domain.properties.model import Property` → **ModuleNotFoundError**.
- `content_generator.py` → `services/publishing/social_delivery/{description,post_copy}.py`
  → **ModuleNotFoundError**.
- `scripted_video/render_service.py` → `services/media/{site_storage,reel_rendering}`
  → `services/ai/photo_selection/{prompting,selection}.py` →
  **ModuleNotFoundError**.

El acceptance simultáneo (1) `application/`+`domain/` borrados físicamente y
(2) `pytest -q` verde sólo tiene una solución compatible: reapuntar los
`from domain.X`/`from application.X` que vivan en frozen y se cargan
transitivamente. La alternativa (mantener un shim parcial en `application/`
o `domain/`) violaba A1/A2.

El implementer eligió **reapuntar** (1-2 líneas por archivo, sustitución
textual mecánica del path) en lugar de **redefinir inline** (que el
briefing también permite). Reapuntar es menos invasivo: no añade LoC, no
duplica símbolos, simplemente cambia la fuente. Es coherente con el patrón
aceptado en 18a §2.2.

**Coste**: 11 líneas modificadas en 10 archivos frozen
(`services/{ai,media,publishing}/...`). No tocan lógica, no reordenan
código, no añaden ni quitan funcionalidad. Coherente con el espíritu del
Phase 2 §2 ("borrar legacy a medida que se mueve").

**Sin ciclos de import**: los 10 archivos `services/*` ahora importan de
`modules/{catalog,tenancy,reels}/domain/`. Esos `domain/` no importan
`services/*` (sólo stdlib + tipos hermanos). Verificado.

## Sugerencias menores (no bloquean)

1. WARN de `init.sh` step 4 ("18 archivos modificados en legacy en últimas
   24h") es esperado: 10 patches en `services/` + el contenido borrado de
   `application/` + `domain/` + el creado en `modules/` + `shared/` cae en
   la heurística del init.sh. Conforme a la deviación §6.2.
2. Feature 18 sigue como `pending` en `feature_list.json` (no
   `in_progress`). Tras esta review, el leader puede promoverla a
   `in_progress` para que arranque 18c. La promoción a `done` la decide el
   closer cuando 18c apruebe.
3. `modules/reels/application/content_generator.py:16-20` importa
   `services/publishing/social_delivery/{description,post_copy}` — cross-
   module read de `application/` a otra librería; aceptable porque
   `services/` no es bounded context y 18c lo migra a
   `modules/publishing/infrastructure/`. **No bloqueante**.
4. `modules/publishing/infrastructure/adapters/gohighlevel/factory.py:20-27`
   importa de `services/publishing/social_delivery` — el factory vive ya en
   el bounded context publishing pero las clases concretas siguen en
   `services/`. 18c migra ambos lados. **No bloqueante**.
5. **Deuda hacia 18c**: 4 archivos en `apps/`, `modules/`, `shared/`
   exceden 500 LoC (no creados por 18b):
   - `modules/reels/application/use_cases/ingest_property_into_reel.py` (944).
   - `modules/ingestion/transport/http/wordpress_webhook_router.py` (621).
   - `modules/reels/transport/http/admin_reels_router.py` (587).
   - `shared/observability/logging.py` (639, creado en 18a y aceptado).
   El acceptance del cierre completo de feature 18 (no de las sub-tareas)
   exige resolverlos. 18c o Phase 3 deberá partirlos.
6. La cadena lazy `application.bootstrap.runtime → services.publishing.social_delivery`
   ahora vive en `modules.publishing.infrastructure.adapters.gohighlevel.factory`
   → `services.publishing.social_delivery`. La parte `services/` desaparece
   en 18c; el factory ya está en su path final.
7. El alias `UnitOfWork = object` heredado de feature 17 (en
   `application/scripted_render/service.py`) ha desaparecido al borrar
   `application/`; el split del service en `payload_helpers.py` lo
   conserva minimal (revisado: vive en
   `modules/rendering/application/scripted_video/payload_helpers.py`
   coherente con el código original).

**Fin de la review.**
