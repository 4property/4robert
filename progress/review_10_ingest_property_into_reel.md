# Review — feature 10 `reels_use_case_ingest_property_into_reel`

**Veredicto:** APPROVED

## Resumen

Se validó el cumplimiento literal del acceptance de la feature 10, el plan
del explorer y las decisiones del leader (D1, R1, R2, R3, R5, D3 y la
opción A). El use case `IngestPropertyIntoReelUseCase` queda extraído en
`modules/reels/application/use_cases/ingest_property_into_reel.py`, los
tests unit + integration cubren camino feliz, noop y error, el adapter
`DefaultPropertyInfoService` queda como bridge delgado (~33 LoC) y
`media_services.py` baja de **1839 → 1034 LoC** (verificado con `wc -l`).
La suite completa termina verde con **380 passed**, y `python -m apps.{api,worker} --check`
ambos terminan exit 0. La modificación a `tests/support/postgres.py`
(disposal del engine cacheado) es defensiva y consistente con el ciclo de
vida del schema temporal — aceptada. Sin issues bloqueantes.

## Checks superados

### A. Acceptance literal

- [x] **A1** Existe `modules/reels/application/use_cases/ingest_property_into_reel.py:243`
  con `class IngestPropertyIntoReelUseCase` y método `execute(job, *, uow=None)`
  (líneas 243-274).
- [x] **A2** Existe `tests/unit/reels/test_ingest_property_into_reel.py`
  con 3 tests: `test_execute_persists_state_and_returns_context_for_fresh_property`
  (camino feliz), `test_execute_is_noop_when_state_unchanged_and_artifacts_present`
  (noop), `test_execute_propagates_when_payload_is_not_a_mapping` (error,
  `Property.from_api_payload` lanza `TypeError`). Todos PASS.
- [x] **A3** Existe `tests/integration/reels/test_ingest_property_into_reel_flow.py`
  con `test_execute_persists_reel_state_and_property_on_postgres` que usa
  `temporary_postgres_schema` + `seed_tenant`, valida `reels` (workflow_state,
  render_status, publish_status, agency_id, ingestion_source_id,
  content_snapshot dict) y `properties`, y opcionalmente asserta que
  `media_revisions` está vacía (consistente con D1).
- [x] **A4** `media_services.py` LoC verificado: **1034** vs reportado 1034
  (`wc -l application/pipeline/media_services.py`). Reducción 1839 → 1034
  = **805 LoC eliminados**.
- [x] **A5** `pytest -q` termina con **380 passed** en 226 s. Esperado 380. ✓

### B. Calidad del código

- [x] **B1** Inter-módulo: el use case importa de `modules.reels.domain`
  (mismo módulo), `modules.publishing.infrastructure.adapters.platforms`
  (registry estático cross-module documentado por el explorer §1 como
  aceptable y usado en otros 10+ archivos del repo) y `shared.db`. Resto
  son legacy `application/`, `core/`, `domain/`, `services/`, `settings`
  — todo aceptado en Phase 2.
- [x] **B2** `DefaultPropertyInfoService` adapter (`media_services.py:141-172`)
  es delgado (32 LoC con docstring; ~10 LoC de lógica real). `__init__`
  ignora explícitamente `unit_of_work_factory` con `del unit_of_work_factory`
  y delega al use case. `ingest_property` es una sola línea de delegación.
- [x] **B3** Sin `print()`, sin `xfail` nuevos, sin `TODO`/`FIXME` sin
  contexto. Verificado con grep en los 4 archivos creados/modificados.
- [x] **B4** Logs verbatim (R5):
  - `"Property Ingest Decision"` — `ingest_property_into_reel.py:408`
  - `"Property Content Generation Started"` — `ingest_property_into_reel.py:497`
  - `"Property Content Generation Completed"` — `ingest_property_into_reel.py:524`
  Mismos detail lines que la versión original (Site ID, Property ID,
  Content changed, Has local artifacts, Requires asset preparation,
  Requires render, Pending publish platforms, Publish targets, Noop).
- [x] **B5** Firmas de UoW moderno casan:
  - `uow.catalog.properties.upsert_property(record: dict)` →
    `property_repository.py:118` ✓
  - `uow.reels.states.get(*, external_source_id, source_property_id)` →
    `reel_state_repository.py:100` ✓
  - `uow.reels.states.save(state: ReelState)` →
    `reel_state_repository.py:116` ✓
- [x] **B6** Naming: `IngestPropertyIntoReelUseCase.execute(job)` cumple
  Phase 2; el adapter conserva `ingest_property` para no romper el
  Protocol legacy y bootstrap.

### C. Tests

- [x] **C1** El unit test ejercita `IngestPropertyIntoReelUseCase.execute(...)`
  directamente, no el adapter. Stubs `_StubProperties` y `_StubReelStates`
  con UoW como `SimpleNamespace`. Patrón consistente con
  `tests/unit/reels/_uow_stubs.py`.
- [x] **C2** El test de error es legítimo: pasa `payload="not-a-mapping"`,
  `Property.from_api_payload` (`domain/properties/model.py:249`) levanta
  `TypeError("Property payload must be a mapping.")`, el use case lo
  propaga sin capturarlo. Asserta que no hubo writes (`upserts == []`,
  `saved == []`).
- [x] **C3** El test de integración usa `temporary_postgres_schema` +
  `seed_tenant` + `temporary_workspace`. SQL directo con `text(...)` para
  aserciones; nada de mocks de Postgres.
- [x] **C4** Stubs siguen el patrón existente (SimpleNamespace de
  catalog/reels con repos stub que registran upserts/saves).

### D. Desviación en `tests/support/postgres.py`

- [x] **D-defensivo** El cambio (`postgres.py:136-149`) hace
  `_ENGINE_CACHE.pop(scoped_url).dispose()` en el `finally` del
  `temporary_postgres_schema`. Es defensivo: el schema se dropea
  inmediatamente después, así que las pooled connections del engine
  cacheado quedarían inválidas. Sin esta limpieza, cada test que abre un
  schema deja un engine con pool conectado a un schema inexistente, lo
  que efectivamente agota el pool de Postgres tras N tests.
- [x] **D-pattern** Sigue el patrón del helper (`try/except Exception:
  pass` para no romper si el módulo aún no fue importado, `if scoped_url
  is not None` guard, ejecución dentro del `finally` original). No
  introduce nuevos side effects: el `DROP SCHEMA` y `admin_engine.dispose()`
  ya existían.
- [x] **D-race** Sin riesgo de doble dispose: `pop(scoped_url, None)`
  saca del cache antes de disponer; un segundo intento devolvería `None`.
  Sin riesgo de race con otros tests porque cada `scoped_url` es
  `f"test_{uuid4().hex}"` único — no hay otro test que comparta el
  cache key.

### E. Acoplamientos / huellas legacy

- [x] **E1** El use case **no** importa de `repositories/stores/` ni de
  `application/persistence`. Los imports son `application.pipeline.content_generation`
  (legacy aceptado), `application.types`, `core.logging`, `domain.media.planning`,
  `domain.properties.model`, `modules.publishing.infrastructure.adapters.platforms`
  (registry), `modules.reels.domain`, `services.media.site_storage`,
  `services.publishing.social_delivery` (helpers), `settings.DATABASE_URL`,
  `shared.db.DatabaseUnitOfWork`. Todo coincide con lo previsto por el
  explorer §1.
- [x] **E2** `application/bootstrap/{runtime.py,__init__.py}` confirmado
  byte-a-byte iguales (`diff` sin output). Sin tocar (D3 cumplido).

## Issues críticos

(Ninguno bloqueante.)

## Sugerencias menores

1. **`application/pipeline/__init__.py` huérfano (1839 LoC)**: el archivo
   contiene una copia completa del legacy media_services.py pre-Phase 2.
   No es responsabilidad de feature 10 (la modificación es del
   2026-04-30, anterior a esta feature; el implementer no lo tocó). El
   archivo es dead code: `grep "from application.pipeline import"` no
   devuelve nada, todos los imports apuntan a submódulos. Sugerencia
   para el leader: agendar su borrado en feature 14 o 18 cuando se
   colapse `application/pipeline/`.
2. **Bridge import dentro de `_should_prepare_assets`** (`ingest_property_into_reel.py:765`):
   `from application.pipeline.media_services import DefaultMediaPreparationService`
   queda dentro del método para evitar import circular (el adapter
   `DefaultPropertyInfoService` vive en ese mismo `media_services.py`
   importando el use case). Está bien comentado como "feature 11 lo
   absorbe". OK como sale, no requiere cambio.
3. **`_state_for_legacy_helpers`**: el `SimpleNamespace` con un único
   atributo es un workaround pragmático y razonable mientras dure el
   bridge. Documentado.

## Confirmación de checks de cierre

| Check | Resultado |
|-------|-----------|
| `wc -l application/pipeline/media_services.py` | **1034** (vs 1839 baseline; 805 LoC eliminados) |
| `wc -l modules/reels/application/use_cases/ingest_property_into_reel.py` | 958 |
| `wc -l tests/unit/reels/test_ingest_property_into_reel.py` | 226 |
| `wc -l tests/integration/reels/test_ingest_property_into_reel_flow.py` | 118 |
| `pytest -q tests/unit/reels/test_ingest_property_into_reel.py tests/integration/reels/test_ingest_property_into_reel_flow.py` | **4 passed in 3.07s** |
| `pytest -q` (suite completa) | **380 passed in 226.00s** |
| `python -m apps.api --check` | exit 0 (RUNTIME READY: Yes) |
| `python -m apps.worker --check` | exit 0 (kinds=reel_publish, scripted_render) |
| `diff application/bootstrap/runtime.py application/bootstrap/__init__.py` | sin output (byte-a-byte iguales) |

**Veredicto: APPROVED.**
