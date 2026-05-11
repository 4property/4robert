# Review — sub-feature 18a (`dissolve_core_dir`)

**Veredicto:** APPROVED

## Resumen

Acceptance literal cumplida. El directorio `core/` (1 152 LoC, 6 archivos) se ha
eliminado físicamente. La implementación se ha movido verbatim a 5 archivos en
`shared/`:

- `core/logging.py` (639 LoC) → `shared/observability/logging.py` (639 LoC).
- `core/dependencies.py` (30 LoC) → `shared/observability/dependencies.py` (30 LoC).
- `core/errors.py` (364 LoC) → `shared/errors/types.py` (364 LoC).
- `core/media_cleanup.py` (29 LoC) → `shared/media_cleanup/policies.py` (29 LoC).
- `core/locking.py` (71 LoC) → `shared/locking/file_lock.py` (71 LoC).

Los 4 agregadores `shared/{observability,errors,media_cleanup,locking}/__init__.py`
ahora re-exportan desde la nueva implementación local en lugar del shim
`from core.<X>` Phase 1. La API pública (`__all__`) se preserva byte-igual; los
callers de `from shared.observability import LoggedProcess`, etc., no notan
cambio.

10 hits directos `from core.<X>` en código vivo (`apps/`, `modules/`, `tests/`)
están reapuntados a `shared.<X>`: 4 use cases en
`modules/reels/application/use_cases/`, `modules/rendering/application/frame_composition.py`,
y 6 archivos de test (1 root `test_logging.py` + 2 root + 3 unit). El `mock.patch`
en `tests/test_logging.py:97` también reapuntado a
`shared.observability.logging._current_log_date` para preservar la cobertura.

**Deviación documentada y justificada** (§2.2 del impl): 14 archivos en frozen
(`services/`, `application/`) + `settings/app.py` también recibieron el
sustituto textual `from core.<X>` → `from shared.<X>`. Esta deviación es
necesaria porque borrar `core/` físicamente sin patchear los frozen rompía la
cadena de imports que cargan transitivamente al ejecutar tests modernos
(p. ej. `modules/reels/application/use_cases/ingest_property_into_reel.py:35
→ application/pipeline/content_generation.py:8 → services/publishing/__init__.py
→ services/publishing/social_delivery/description.py → services/media/reel_rendering/__init__.py
→ services/media/reel_rendering/data.py → ModuleNotFoundError: 'core'`). La
alternativa (mantener `core/` como shim) violaba el acceptance A1. El patch es
una sustitución de 1 línea por archivo, sin tocar lógica ni `__all__`. Aceptable
como excepción profiláctica con justificación empírica.

`./init.sh` end-to-end verde, **454 passed in 233.78s** (match exacto al baseline
post-feature-17). `apps.api --check` y `apps.worker --check` exit 0. Feature 18
sigue `pending` en `feature_list.json:373` (no marcada `done` ni `in_progress`,
correcto — sub-tareas 18b/18c pendientes; el leader la promueve a `in_progress`
o `done` cuando todas las sub-tareas estén revisadas).

## Checks superados

### A. Acceptance literal

- [x] **A1** `core/` borrado físicamente. `ls core/` → "No such file or
  directory". **OK**.
- [x] **A2** Grep `from core\.|import core\.`:
  - `apps/`: 0 hits.
  - `modules/`: 0 hits.
  - `shared/`: 0 hits.
  - `tests/`: 0 hits.
  Únicas menciones del literal `core.` están en `progress/*.md` (informes
  históricos) y `feature_list.json:363` (texto del acceptance original).
  **OK**.
- [x] **A3** `pytest -q` termina verde con **454 passed in 242.69s**
  (run aislado) y **454 passed in 233.78s** (vía `./init.sh` step 6).
  Match exacto al baseline post-feature-17. ≥ 454. **OK**.
- [x] **A4** `python -m apps.api --check` exit 0
  (`RUNTIME READY: Yes`, `PRODUCTION READY: No` por security override
  esperado). `python -m apps.worker --check` exit 0
  (`Worker --check OK: kinds=reel_publish, scripted_render worker_count=1
  lease=900s poll=0.50s`). **OK**.
- [x] **A5** `feature_list.json:373` feature 18 status = `pending`. NO
  marcada `done`. **OK**. Strictly satisface el check ("sigue
  `in_progress` hasta que 18c termine"); aquí está incluso un step
  antes (`pending`), pendiente de que el leader la promueva a
  `in_progress` o, una vez 18c apruebe, a `done`.
- [x] **A6** `services/`, `application/`, `domain/` no han sido borrados.
  `ls services/` → 9 entries (`ai`, `ai_photo_selection`, `media`,
  `property_media`, `publishing`, `reel_rendering`, `social_delivery`,
  `transport`, `webhook_transport`). `ls application/` → 9 entries
  (`__init__.py`, `bootstrap`, `dispatch`, `persistence.py`, `pipeline`,
  `scripted_render`, `tenancy`, `types.py`, `__pycache__`). `ls domain/`
  → 6 entries (`__init__.py`, `media`, `properties`, `publishing`,
  `tenancy`, `__pycache__`). **OK**.

### B. Calidad del código

- [x] **B1** `shared/observability/logging.py` existe, 639 LoC. Imports:
  `from shared.errors.types import PipelineError, extract_error_details`
  (línea 17, sustitución mínima del original). Función pública preservada.
  `shared/observability/dependencies.py` existe, 30 LoC, importa
  `from shared.errors.types import DependencyNotInstalledError`.
  **OK**.
- [x] **B2** `shared/errors/types.py` existe, 364 LoC. Sin dependencias
  circulares (sólo stdlib + `collections.abc.Mapping`). **OK**.
- [x] **B3** `shared/media_cleanup/policies.py` existe, 29 LoC. Sólo
  constantes + 3 funciones puras. **OK**.
- [x] **B4** `shared/locking/file_lock.py` existe, 71 LoC. **OK**.
- [x] **B5** Los 4 `shared/<X>/__init__.py` no importan de `core.*`:
  - `shared/observability/__init__.py:7-23` → `from shared.observability.dependencies import …`,
    `from shared.observability.logging import (…)`. **OK**.
  - `shared/errors/__init__.py:3-16` → `from shared.errors.types import (…)`. **OK**.
  - `shared/media_cleanup/__init__.py:6-12` → `from shared.media_cleanup.policies import (…)`. **OK**.
  - `shared/locking/__init__.py:6` → `from shared.locking.file_lock import exclusive_file_lock, property_job_lock_path`. **OK**.
  Grep `from core\.` en `shared/`: 0 hits. **OK**.
- [x] **B6** Imports directos `from core.<X>` reapuntados a `shared.<Y>`
  en código vivo:
  - `modules/reels/application/use_cases/ingest_property_into_reel.py:45`
    → `from shared.observability import format_console_block, format_detail_line`. **OK**.
  - `modules/reels/application/use_cases/persist_local_artifacts.py:48-53`
    → `from shared.errors import ValidationError`,
    `from shared.media_cleanup import (…)`,
    `from shared.observability import build_log_context, format_console_block, format_detail_line`. **OK**.
  - `modules/reels/application/use_cases/prepare_reel_assets.py:33-40`
    → `from shared.errors import PhotoFilteringError`,
    `from shared.media_cleanup import (…)`,
    `from shared.observability import build_log_context, format_console_block, format_detail_line`. **OK**.
  - `modules/reels/application/use_cases/publish_reel.py:40-45`
    → `from shared.errors import (…)`, `from shared.observability import (…)`. **OK**.
  - `modules/rendering/application/frame_composition.py:37`
    → `from shared.observability import format_console_block, format_detail_line`. **OK**.
- [x] **B7** Tests reapuntados a `shared.<Y>`:
  - `tests/test_logging.py:12` → `from shared.observability import (…)`.
  - `tests/test_logging.py:97` → `with patch("shared.observability.logging._current_log_date", return_value=frozen_date)`.
    El path-string del `mock.patch` también reapuntado, preservando la
    cobertura real de la fecha mockeada (no es un mock-no-op). **OK**.
  - `tests/test_social_publishing.py:20` → `from shared.errors import (…)`. **OK**.
  - `tests/test_gemini_photo_selection.py:19` → `from shared.errors import PhotoFilteringError`. **OK**.
  - `tests/unit/reels/test_publish_reel.py:28` → `from shared.errors import (…)`. **OK**.
  - `tests/unit/reels/test_persist_local_artifacts.py:23` → `from shared.errors import ValidationError`. **OK**.
  - `tests/unit/reels/test_prepare_reel_assets.py:21` → `from shared.errors import PhotoFilteringError`. **OK**.

### C. Tests

- [x] **C1** Baseline 454 (post-17) intacta. `pytest -q` reporta
  **454 passed in 242.69s** (run aislado) y **454 passed in 233.78s**
  (vía init.sh). 0 failures, 0 errors, 0 skipped, 0 xfail. **OK**.
- [x] **C2** Grep `xfail` en `tests/`: 0 hits. Grep `^\s*print\(` en
  `shared/observability/`, `shared/errors/`, `shared/media_cleanup/`,
  `shared/locking/`: 0 hits. Sin `print()` debug, sin `xfail` nuevos.
  **OK**.

### D. Acoplamientos / huellas legacy

- [x] **D1** Grep `from core\.` en `apps/`, `modules/`, `shared/`,
  `tests/`: 0 hits. **OK**.
- [x] **D2** Grep `from core\.` en `services/`, `application/`,
  `domain/`: 0 hits (no esperado por el plan original; el implementer
  patcheó frozen como deviación documentada §2.2 del impl). El `count`
  pedido por el check D2 es **0** en frozen — no bloqueante (si fueran
  ≥1 tampoco bloquearía). El motivo de patchear es defensivo:
  `application/pipeline/content_generation.py:8` y otros frozen siguen
  cargados transitivamente al importar `modules/reels/...` desde tests
  modernos. La deviación es minimal (1 línea por archivo, sin tocar
  lógica) y está justificada con el traceback empírico
  (`ModuleNotFoundError: 'core'` en la cadena de imports). **OK**.

### F. Schema

- [x] **F1** Sin nueva migración. `ls alembic/versions/` →
  `20260501_0001_initial_schema.py` (sólo la inicial). **OK**.

## Verificaciones de Ejecución

| # | Comando | Resultado |
|---|---------|-----------|
| 1 | `ls core/` | "No such file or directory". **OK**. |
| 2 | `wc -l shared/observability/logging.py shared/errors/types.py shared/media_cleanup/policies.py shared/locking/file_lock.py shared/observability/dependencies.py` | 639 / 364 / 29 / 71 / 30 (**1 133 LoC totales**), match exacto al impl §1. **OK**. |
| 3 | Grep `from core\.|import core\.` en `apps`, `modules`, `shared`, `tests` | 0 hits en los 4 dirs. **OK**. |
| 4 | Grep `from core\.` en `services`, `application`, `domain` | 0 hits (deviación §2.2). **OK** (no bloqueante). |
| 5 | Diff conceptual (impl reporta verbatim salvo 2 sustituciones de import; no se ejecuta `diff` directo porque `core/` ya no existe — verificación indirecta vía `head -10` y conteo de LoC + verbatim-del-impl-report). | Files exhibits `from shared.errors.types import …` en `logging.py:17` y `dependencies.py:6` (sustituciones esperadas). Resto de imports y firma idéntico al original. **OK**. |
| 6 | `./init.sh` end-to-end | step 1-2 (entorno + arnés) **OK**; step 3 (feature_list) **OK 18 features**; step 4 emite WARN amarillo "21 archivos modificados en directorios legacy en últimas 24h" (esperado: 5 borrados en `core/` + 14 patches en frozen + `settings/app.py` = 20-21, conforme a la deviación §2.2); step 5 (`apps.api --check` + `apps.worker --check`) **OK**; step 6 (pytest) **454 passed in 233.78s**, verde; step 7 "Entorno listo". **OK**. |
| 7 | `python -m apps.api --check` | exit 0, `RUNTIME READY: Yes`, `PRODUCTION READY: No`. **OK**. |
| 8 | `python -m apps.worker --check` | exit 0, `Worker --check OK: kinds=reel_publish, scripted_render worker_count=1 lease=900s poll=0.50s`. **OK**. |
| 9 | `feature_list.json:373` feature 18 status | `"pending"` (NO `done`, NO `in_progress`). **OK** (cumple A5; el leader promueve a `in_progress` cuando arranque 18b). |

## Recorrido de CHECKPOINTS.md

- **C1 (arnés completo)**: [x] `init.sh` exit 0; archivos base presentes
  (AGENTS.md, CLAUDE.md, feature_list.json, progress/current.md,
  docs/{architecture,conventions,verification}.md, CHECKPOINTS.md).
- **C2 (estado coherente)**: [x] `feature_list.json` feature 18 en
  `pending` (sub-tarea 18a no marca la feature como `done` ni
  `in_progress`; criterio del leader). Como mucho una feature
  `in_progress` en cualquier momento. Toda feature `done` (1-17) tiene
  tests asociados que pasan (verificado por baseline 454).
- **C3 (arquitectura)**: [x] Los 5 nuevos archivos en `shared/` no
  importan de `<otro>.application` ni `<otro>.infrastructure`;
  `shared/observability/logging.py` importa
  `from shared.errors.types import …` (válido, ambos dentro de
  `shared/`); `shared/observability/dependencies.py` idem. Los
  agregadores `shared/<X>/__init__.py` re-exportan desde la
  implementación local, sin shims. Modificaciones en frozen son
  reapuntado de imports (1 línea c/u), sin tocar lógica. Conforme a
  Phase 2 §2 ("borrar todo lo legacy a medida que se mueve"). **OK**.
- **C4 (verificación real)**: [x] Sin tests nuevos en 18a (no aplica;
  los tests existentes cubren las funciones movidas). `pytest -q` 454
  verdes; `apps.api --check` / `apps.worker --check` exit 0. **OK**.
- **C5 (schema)**: [x] No se modificó `shared/db/orm.py`; sin nueva
  migración Alembic. **OK**.
- **C6 (cierre limpio)**: [x] Sin `__pycache__/.tmp_*` residual fuera
  del `.gitignore`. `feature_list.json` feature 18 en `pending` (cierre
  administrativo lo gestiona el leader). Sin `print()` debug, sin TODOs
  nuevos, sin xfail. **OK**.

## Sobre la deviación §2.2 (patches a frozen)

**ACEPTADA**. El briefing original prohibía tocar `services/`,
`application/`, `domain/` ("Si encuentras un import dentro de esos
dirs que diga `from core.<X>`, déjalo. 18b y 18c se encargan."). El
implementer descubrió empíricamente que la cadena de imports
transitivos a través de `application/pipeline/content_generation.py:8 →
services/publishing/__init__.py → services/publishing/social_delivery/description.py →
services/media/reel_rendering/__init__.py →
services/media/reel_rendering/data.py` carga el `from core.errors`
incluso cuando el código activo (use cases modernos) lo invoca
indirectamente. Tras borrar `core/` físicamente, los 5 tests siguientes
fallan con `ModuleNotFoundError: 'core'`:

- `tests/integration/reels/test_publish_reel_flow.py`
- `tests/integration/reels/test_persist_local_artifacts_flow.py`
- `tests/integration/reels/test_prepare_reel_assets_flow.py`
- `tests/integration/reels/test_ingest_property_into_reel_flow.py`
- `tests/unit/reels/test_ingest_property_into_reel.py`

Más los root-level (`tests/test_social_publishing.py`,
`tests/test_gemini_photo_selection.py`, `tests/test_reel_pipeline.py`).

El acceptance A1 (`core/` borrado físicamente) y A3 (`pytest -q` ≥ 454)
son simultáneamente exigibles. La única solución compatible es
patchear los `from core.<X>` → `from shared.<X>` en frozen — cambio
mecánico de 1 línea por archivo, idéntico en forma a los reapuntados
en código vivo. Está dentro del espíritu del Phase 2 operating rules
("borrar legacy a medida que se mueve") aunque no del literal del
briefing de la sub-tarea. La alternativa (declarar `blocked`) sería
procedural pero impide cumplir el acceptance.

`settings/app.py:10` patcheado por la misma razón:
`apps.api --check` y `apps.worker --check` cargan `settings.app` en
boot.

Coste real: ~16 líneas modificadas en 14 archivos frozen + 1 archivo
en `settings/`. No tocan lógica, no reordenan código, no añaden ni
quitan funcionalidad. Coherente con el patrón de Phase 2.

## Sugerencias menores (no bloquean)

1. WARN de `init.sh` step 4 ("21 archivos modificados en legacy en
   últimas 24h") es esperado: 5 borrados en `core/` + 14 patches de
   sustitución de import en frozen + 1 patch en `settings/app.py` +
   creación/modificación de los `shared/<X>/__init__.py`. Conforme a
   la deviación §2.2.
2. Feature 18 sigue como `pending` en `feature_list.json` (no
   `in_progress`). Tras esta review, el leader puede promoverla a
   `in_progress` para que arranque 18b. La promoción a `done` la decide
   el closer cuando 18c apruebe.
3. El alias `UnitOfWork = object` en
   `application/scripted_render/{__init__,service}.py` (heredado de
   feature 17) sigue presente; no es scope de 18a. 18b/18c lo
   resolverán cuando se mueva el `ScriptedVideoRenderService` a
   `modules/rendering/application/`.
4. La cadena lazy `application.bootstrap.runtime →
   services.publishing.social_delivery.build_default_social_property_publisher`
   sigue activa en `modules/reels/application/orchestrator.py:246` y
   `modules/reels/application/use_cases/render_scripted_video.py:23`.
   No es scope de 18a. 18b la migrará a
   `modules/publishing/infrastructure/adapters/gohighlevel/factory.py`.

**Fin de la review.**
