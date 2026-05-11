# Review — feature 17 (`retire_property_store_and_repositories_stores`)

**Veredicto:** APPROVED

## Resumen

Acceptance literal cumplida. El directorio `repositories/` (3 610 LoC, 8
archivos en `postgres/` + 11 stores + `__init__.py` + 12 ORM models legacy) se
ha eliminado por completo, junto con la fachada
`modules/catalog/infrastructure/property_store_compat.py` (278 LoC). La cadena
legacy `apps.api → services.transport.http.operations → repositories` se ha
sustituido por un módulo moderno `apps/api/readiness.py` (438 LoC) que
reimplementa `build_readiness_report`, `cleanup_stale_staging_directories` y
`ensure_runtime_is_supported` sobre `shared.db.{uow,engine}` y preserva la
forma del dict de retorno. `apps/api/main.py:82` y `apps/api/health_router.py`
(docstrings 13/50 + lazy import en :112) reapuntan al nuevo módulo.
`application/bootstrap/{runtime,__init__}.py` cambian 1 LoC cada uno (`from
shared.db.uow import DatabaseUnitOfWork`) y siguen byte-iguales (`diff` exit
0). R7 aplicada: `services/media/reel_rendering/data.py` y
`services/publishing/social_delivery/description.py` redefinen
`PropertyReelRecord` inline (la dataclass legacy con sus 31 fields). R8
ampliada: `application/scripted_render/{__init__,service}.py` inlinean
`ScriptedVideoArtifactRecord` y degradan `UnitOfWork` a alias `object` para
no romper la carga del módulo cuando los tests del worker dispatcher hacen
`mock.patch` sobre `application.scripted_render.service`. Los 2 tests legacy
(`test_architecture_cleanup.py` 78 LoC + `test_tenancy.py` 73 LoC) borrados.
Nuevos: `tests/unit/apps_api/test_readiness.py` (202 LoC, 5 tests).
**`./init.sh` verde con 454 passed** en 235.88s (baseline post-feature-16 era
**455**, no 461 como recoge la consigna del review; pre-condición real:
455 - 6 tests de los 2 archivos borrados + 5 tests nuevos = 454, match
exacto). `apps.api --check` y `apps.worker --check` exit 0.

Ningún archivo bajo `apps/`, `modules/`, `shared/`, `tests/` importa de
`repositories/` (Grep `from repositories\.|import repositories\.`: 0 hits en
los 4 dirs activos). Los símbolos legacy `_NoopDispatcher`,
`PropertyMediaPipeline`, `PipelineStateStore`, `PropertyStore`,
`GoHighLevelConnectionStore` solo aparecen en `progress/*.md` y en docstrings
históricos (`modules/rendering/application/frame_composition.py:22`,
`modules/reels/application/orchestrator.py:6`,
`modules/reels/application/use_cases/ingest_property_into_reel.py:227`),
nunca como import vivo.

## Checks superados

### A. Acceptance literal

- [x] **A1** `repositories/` borrado físicamente. `ls repositories/` →
  "No such file or directory". **OK**.
- [x] **A2** `modules/catalog/infrastructure/property_store_compat.py`
  borrado. `ls modules/catalog/infrastructure/`: solo `__init__.py`,
  `__pycache__/`, `orm.py`, `property_repository.py`. **OK**.
- [x] **A3** Grep `from repositories\.|import repositories\.`:
  - `apps/`: 0 hits.
  - `modules/`: 0 hits.
  - `shared/`: 0 hits.
  - `tests/`: 0 hits.
  Únicas menciones del literal `repositories.` están en `progress/*.md`
  (informes históricos). **OK**.
- [x] **A4** `pytest -q` termina verde con **454 passed** (init.sh step 6,
  235.88s). Ver nota en §Sobre el target ≥459 passed; se entiende como
  "match exacto" del baseline real post-feature-16 (455) menos los 6 tests
  de los 2 archivos legacy borrados más los 5 nuevos en
  `test_readiness.py`. Threshold real: ≥454. **OK**.
- [x] **A5** `python -m apps.api --check` exit 0 (`RUNTIME READY: Yes`,
  `PRODUCTION READY: No` por `WEBHOOK_DISABLE_SECURITY=true`, esperado).
  `python -m apps.worker --check` exit 0 (`Worker --check OK:
  kinds=reel_publish, scripted_render worker_count=1 lease=900s
  poll=0.50s`). **OK**.

### B. Calidad del código

- [x] **B1** `apps/api/readiness.py` 438 LoC (algo por encima de la
  estimación 250-300 del plan, pero la implementación replica con
  fidelidad las 8 capabilities + checks + secrets validation del legacy
  + cleanup helpers). Imports verificados: `settings`, `shared.db.engine`
  (`describe_database_binding`, `verify_required_tables`),
  `shared.db.uow.DatabaseUnitOfWork`, `shared.errors.ApplicationError`.
  Sin `from repositories.` ni `import repositories`. El dict de retorno
  expone las 8 claves legacy (`ready`, `production_ready`, `checks`,
  `capabilities`, `errors`, `warnings`, `failures`, `environment`,
  verificadas con Grep en :287-294). **OK**.
- [x] **B2** `apps/api/main.py:82` — `from apps.api.readiness import
  build_readiness_report` (lazy dentro de `_check`). **OK**.
  `apps/api/health_router.py`:
  - Línea 13: docstring referencia
    `:func:`apps.api.readiness.build_readiness_report``. **OK**.
  - Línea 49 (en lugar del 50 del plan, equivalente): docstring
    "production callers leave it unset and the router runs the canonical
    `apps.api.readiness.build_readiness_report`". **OK**.
  - Línea 112 (en lugar del 115 del plan, off-by-3): lazy `from
    apps.api.readiness import build_readiness_report`. **OK**.
  Discrepancia menor en numeración (el plan apuntaba a línea 115; la real
  es 112). No afecta el contenido ni el comportamiento.
- [x] **B3** `application/bootstrap/runtime.py:5` →
  `from shared.db.uow import DatabaseUnitOfWork`. **OK**.
  `application/bootstrap/__init__.py:5` → idem. **OK**.
  `diff application/bootstrap/runtime.py application/bootstrap/__init__.py`
  exit 0 (byte-iguales).
- [x] **B4** Sin `print()`, sin `xfail`, sin TODOs sin contexto en
  `apps/api/readiness.py` ni en `tests/unit/apps_api/test_readiness.py`
  (Grep: 0 hits). **OK**.

### C. Tests

- [x] **C1** `tests/unit/apps_api/test_readiness.py` existe, 202 LoC, 5
  tests:
  - `test_report_marks_ready_when_database_and_storage_pass` (`:44`).
  - `test_report_flags_database_failure` (`:87`).
  - `test_report_flags_storage_failure_when_workspace_unwritable`
    (`:122`).
  - `test_report_flags_missing_site_secrets_unless_security_disabled`
    (`:153`).
  - `test_report_warns_when_security_disabled` (`:176`).
  ≥3, **OK**.
- [x] **C2** `tests/unit/test_architecture_cleanup.py` borrado. **OK**.
  `tests/unit/test_tenancy.py` borrado. **OK**.
- [x] **C3** Resto de tests legacy verdes sin tocar (init.sh step 6 verde,
  454 passed). **OK**.

### D. Borrados

- [x] **D1** `repositories/postgres/` (8 archivos: `__init__.py`,
  `base.py`, `engine.py`, `repository.py`, `security.py`, `session.py`,
  `uow.py`, `models/__init__.py`) borrado. **OK**.
- [x] **D2** `repositories/stores/` (11 archivos: `__init__.py` +
  `agency_store.py`, `ghl_connection_store.py`, `job_queue_store.py`,
  `media_revision_store.py`, `outbox_event_store.py`,
  `pipeline_state_store.py`, `property_store.py`,
  `reel_profile_store.py`, `scripted_video_artifact_store.py`,
  `webhook_event_store.py`, `wordpress_source_store.py`) borrado. **OK**.
- [x] **D3** `modules/catalog/infrastructure/property_store_compat.py`
  (278 LoC) borrado. **OK**.
- [x] **D4** 2 tests legacy borrados:
  - `tests/unit/test_architecture_cleanup.py` (78 LoC).
  - `tests/unit/test_tenancy.py` (73 LoC).
  **OK**.

### E. R7 verificación

R7 aplicada (no skipable, como confirmaba el plan):
- `services/media/reel_rendering/data.py:13-50` redefine inline
  `PropertyReelRecord` con 31 fields (`site_id`, `property_id`, `slug`,
  `title`, `link`, `selected_image_folder`, `local_manifest_path`,
  `local_video_path`, `featured_image_url`, `bedrooms`, `bathrooms`,
  `ber_rating`, `property_status`, `agent_name`, `agent_photo_url`,
  `agent_email`, `agent_mobile`, `agent_number`, `agency_psra`,
  `agency_logo_url`, `price`, `price_term`, `property_type_label`,
  `property_area_label`, `property_county_label`, `property_size`,
  `eircode`, `viewing_times`, `artifact_kind`, `local_artifact_path`,
  `local_metadata_path`, `render_profile`).
  - El consumidor real es `record_to_property_reel_data` (`:53-96`) que
    usa `site_id`, `property_id`, `slug`, `title`, `link`,
    `property_status`, `selected_image_folder`, `featured_image_url`,
    `bedrooms`, `bathrooms`, `ber_rating`, `agent_*`, `agency_*`,
    `price`, `property_*_label`, `eircode`, `property_size`,
    `viewing_times` — **todos presentes**. Funcionalmente equivalente al
    legacy.
  - `load_property_reel_data` (`:99-114`) reescrita para `raise
    PropertyReelError(...)` con hint hacia el flujo moderno
    (`uow.catalog.properties + uow.reels.queries`); el legacy entry
    point queda retirado pero importable hasta feature 18 (sin callers
    vivos verificados).
- `services/publishing/social_delivery/description.py:7` reapunta a
  `from services.media.reel_rendering.data import PropertyReelRecord`.
  El único uso real está en `build_tiktok_description_for_record`
  (`:251-280`) que accede a `record.{site_id, slug, link, title, price,
  property_status, agent_name, agent_email, agent_mobile, agent_number,
  agency_psra}` — todos presentes en la inline.

### F. Schema

- [x] **F1** Sin nueva migración. `ls alembic/versions/`: solo
  `20260501_0001_initial_schema.py`. **OK**.

## Verificaciones de Ejecución

| # | Comando | Resultado |
|---|---------|-----------|
| 1 | `ls repositories/` | "No such file or directory". **OK**. |
| 2 | `ls modules/catalog/infrastructure/property_store_compat.py` | "No such file or directory". **OK**. |
| 3 | `wc -l apps/api/readiness.py` | 438 LoC (>250-300 estimado, aceptable). **OK**. |
| 4 | `wc -l tests/unit/apps_api/test_readiness.py` | 202 LoC. **OK**. |
| 5 | Grep `from repositories\.|import repositories\.` en `apps,modules,shared,tests` | 0 hits. **OK**. |
| 6 | Grep `_NoopDispatcher\|PropertyMediaPipeline\|PipelineStateStore\|PropertyStore\|GoHighLevelConnectionStore` en `apps,modules`,sólo docstrings históricos | `frame_composition.py:22`, `orchestrator.py:6`, `ingest_property_into_reel.py:227`. 0 imports vivos. **OK**. |
| 7 | `diff application/bootstrap/runtime.py application/bootstrap/__init__.py` | exit 0 (byte-iguales). **OK**. |
| 8 | `./init.sh` end-to-end | step 5 (`apps.api --check` + `apps.worker --check`) **OK**; step 6 (pytest) **454 passed in 235.88s**, verde. **OK**. |
| 9 | `python -m apps.api --check` | exit 0, `RUNTIME READY: Yes`. **OK**. |
| 10 | `python -m apps.worker --check` | exit 0, `Worker --check OK`. **OK**. |

## Recorrido de CHECKPOINTS.md

- **C1 (arnés completo)**: [x] `init.sh` exit 0; archivos base presentes
  (AGENTS.md, CLAUDE.md, feature_list.json, progress/current.md,
  docs/{architecture,conventions,verification}.md, CHECKPOINTS.md).
- **C2 (estado coherente)**: [x] `feature_list.json` feature 17 en
  `in_progress` (closer la promueve a `done`). Como mucho una feature
  `in_progress`. Todas las anteriores `done`.
- **C3 (arquitectura)**: [x] `apps/api/readiness.py` no importa de
  `<otro>.application` ni `<otro>.infrastructure`; usa
  `shared.db.{engine,uow}` + `settings` + `shared.errors`. Modificaciones
  en `application/bootstrap/` y `services/media/reel_rendering/data.py` +
  `services/publishing/social_delivery/description.py` son cleanup de
  legacy a medida que se mueve, conforme a Phase 2 §2 ("borrar todo lo
  legacy a medida que se mueve, sin compat shims"). Ningún caller activo
  en `apps/`, `modules/`, `shared/`, `tests/` importa de `repositories/`.
  **OK**.
- **C4 (verificación real)**: [x] 5 unit tests nuevos en
  `tests/unit/apps_api/test_readiness.py` cubren ready=true / DB failure
  / storage failure / missing site secrets / security disabled warning.
  `pytest -q` 454 verdes; `apps.api --check` / `apps.worker --check` exit
  0.
- **C5 (schema)**: [x] No se modificó `shared/db/orm.py`; sin nueva
  migración Alembic.
- **C6 (cierre limpio)**: [x] Sin `__pycache__/.tmp_*` residual
  (`.gitignore` cubre el area). `feature_list.json` feature 17
  `in_progress` (closer promueve a `done`). Sin `print()` debug, sin
  TODOs nuevos, sin xfail.

## Sobre el target ≥459 passed (consigna del review)

La consigna del review pedía "≥ 459 passed". El total real es **454
passed**. La discrepancia se explica así:

1. El baseline real **post-feature-16** era **455** (review_16 §3.1
   confirma "455 passed in 191.76s"; el número 461 que circulaba en
   notas anteriores es un over-count: combinaba conteos pre-decision-de-explore-16
   antes de los stubs y los borrados de `application/pipeline/*`).
2. Feature 17 elimina 2 archivos legacy con 3 tests cada uno (6 tests
   borrados, todos sobre infraestructura legacy: `DatabaseUnitOfWork`
   legacy, `PropertyStore`, `PipelineStateStore`, `TenantResolver`
   legacy, Grep de `repositories/`). Cobertura moderna ya en
   `tests/integration/delivery/test_worker_dispatcher_flow.py` (feature
   16) y `tests/integration/ingestion/test_wordpress_webhook_flow.py`
   (feature 4).
3. Feature 17 añade 5 tests nuevos (`test_readiness.py`).
4. Aritmética: 455 - 6 + 5 = **454**. Match exacto con el run real.

Por tanto, el "≥459" de la consigna es un over-count basado en un
baseline pre-stubbing erróneo. La sustancia del check —`pytest -q`
verde— se cumple sin regresiones. La acceptance literal en
`feature_list.json:346` exige sólo "pytest -q termina verde", sin
piso numérico, y eso se cumple.

## Sobre la desviación del plan §R8

**ACEPTADA**. El plan §R8 decía "no tocar `application/scripted_render/`
en feature 17". El implementer descubrió en runtime que
`tests/integration/delivery/test_worker_dispatcher_flow.py:229` aplica
`mock.patch("application.scripted_render.service.ScriptedVideoRenderService.__init__",
...)` y la resolución del path **carga el módulo**, lo que dispara la
cadena `application.scripted_render.__init__:14 → from
application.persistence import UnitOfWork →
repositories.stores.agency_store import AgencyRecord →
ModuleNotFoundError: 'repositories'`. La solución mínima (24 LoC en
cada uno de los 2 archivos: borrar 2 imports + inline
`ScriptedVideoArtifactRecord` + alias `UnitOfWork = object`) cumple §2
del Phase 2 operating rules ("legacy sin call sites se borra → el
import legacy se reemplaza"). La dataclass inlineada es funcionalmente
equivalente al legacy. El alias `UnitOfWork = object` es seguro porque
el código sólo usa el símbolo como type hint (no como tipo concreto en
runtime; verificado por Grep: ningún `isinstance(_, UnitOfWork)` ni
`runtime_checkable` en el repo).

## Sugerencias menores (no bloquean)

1. `apps/api/readiness.py` 438 LoC (vs estimación plan 250-300). La
   diferencia se justifica por replicar las 8 capabilities + secrets
   validation + storage check + cleanup helpers del legacy con
   fidelidad. Aceptable.
2. Discrepancia de numeración en `health_router.py`: el plan apunta a
   líneas 13/50/115, las reales son 13/49/112. Off-by-3 sin impacto
   semántico (el contenido y el reapuntado al nuevo módulo son
   correctos).
3. WARN de `init.sh` step 4 ("8 archivos modificados en legacy en
   últimas 24h") es esperado: 2 modificaciones en
   `application/bootstrap/{runtime,__init__}.py`, 2 modificaciones en
   `application/scripted_render/{__init__,service}.py`, 2 modificaciones
   en `services/media/reel_rendering/data.py` y
   `services/publishing/social_delivery/description.py` (R7+R8). Las
   demás (24+ archivos en `repositories/`, 1 en `modules/catalog/`, 2
   en `tests/unit/`) son borrados, no modificaciones. Coherente con el
   patrón de Phase 2.
4. `application/persistence.py` queda como código importable pero
   muerto (sin callers activos tras R5+R6+R8). Feature 18 lo borra
   junto con el resto de `application/`.
5. La cadena lazy `_build_default_social_property_publisher` en
   `modules/reels/application/orchestrator.py:246` sigue importando
   `application.bootstrap.runtime`. Tras feature 17 funciona porque
   `runtime.py` ya importa `shared.db.uow.DatabaseUnitOfWork`. Feature
   18 cerrará el ciclo moviendo la fábrica a `modules/publishing/`.

**Fin de la review.**
