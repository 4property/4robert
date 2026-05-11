# Review — feature 13 (`reels_use_case_publish_reel`)

**Veredicto:** APPROVED

## Resumen

Se validó el acceptance literal y todas las decisiones del leader (D1, D5,
D6, D7, R1, R4, R8, R9, R13). El use case `PublishReelUseCase` queda
extraído en `modules/reels/application/use_cases/publish_reel.py`
(495 LoC). Tests cubren todos los caminos solicitados (12 unit + 1
integration nuevos verdes; el integration valida `outbox_events.status =
'completed'` con SQL directo). `application/pipeline/media_services.py`
baja de **677 → 377 LoC** (verificado con `wc -l`). El adapter delgado
`CompositeMediaPublisher` mide exactamente 50 LoC, cumple Protocol
`MediaPublisher` y conserva los aliases legacy
`publish_video`/`publish_existing_video`. El class shadow
`class CompositeMediaPublisher(CompositeMediaPublisher): pass` quedó
eliminado. Los helpers de módulo `_now_iso`, `_relative_path_text`,
`_build_workflow_payload` ya no aparecen en `media_services.py` (R9). Los
imports huérfanos (R8) están limpios. `application/bootstrap/runtime.py`
y `application/bootstrap/__init__.py` siguen byte-iguales entre sí (`diff`
exit 0). `./init.sh` termina verde con **409 passed** en 192.75s.

## Checks superados

### A. Acceptance literal

- [x] **A1** Existe `modules/reels/application/use_cases/publish_reel.py:117`
  con `class PublishReelUseCase` y método `execute(context, rendered_media,
  *, uow=None)` (`publish_reel.py:148-156`). Adicionalmente expone
  `execute_existing(context, *, uow=None)` (`:158-165`). 495 LoC totales.
- [x] **A2** Existe `tests/unit/reels/test_publish_reel.py` (623 LoC) con
  **12 tests** significativos:
  `test_execute_publish_completed_writes_outbox_with_status_completed`,
  `test_execute_partial_aggregate_writes_publish_completed_with_status_completed`,
  `test_execute_skipped_when_social_publisher_is_none`,
  `test_execute_skipped_when_requires_external_publish_is_false`,
  `test_execute_skipped_when_publish_context_is_none`,
  `test_execute_skipped_when_provider_returns_none`,
  `test_execute_awaiting_review_when_agency_approval_required`,
  `test_execute_awaiting_review_when_env_flag_enabled`,
  `test_execute_failed_persists_failed_state_and_reraises`,
  `test_execute_transient_failed_persists_failed_state_and_reraises`,
  `test_execute_existing_raises_when_no_existing_artifact`,
  `test_execute_existing_publishes_with_existing_artifact`. Todos PASS.
  ≥8 cumplido. Cubre `published`, `partial`, 4 `skipped`, 2
  `awaiting_review`, 2 `failed`, 2 `execute_existing`.
- [x] **A3** Existe `tests/integration/reels/test_publish_reel_flow.py`
  (304 LoC) con `test_execute_writes_published_state_revision_and_outbox_completed_on_postgres`
  que usa `temporary_postgres_schema` + `seed_tenant` +
  `seed_provider_connection` + `temporary_workspace`
  (`test_publish_reel_flow.py:152-160`). SQL directo (`text(...)` con
  `create_engine`) para asserts (`:249-303`). Sin mocks de Postgres. 1
  test PASS. Encadena ingest → prepare → persist → publish
  (`:163-244`).
- [x] **A4** `media_services.py` reduce LoC: **677 → 377** (`wc -l
  application/pipeline/media_services.py` = 377; objetivo < 677). Reducción
  300 LoC (~44%).
- [x] **A5** `pytest -q` (vía `./init.sh`) termina **409 passed** en
  192.75 s. Baseline 396 (post-feature-12) + 12 unit + 1 integration =
  409. Esperado ≥ 408. Cumplido (1 test extra).
- [x] **A6** `outbox_events` tiene una fila con `status='completed'`
  cuando provider devuelve 2xx. Verificado en
  `tests/integration/reels/test_publish_reel_flow.py:282-293`:
  `SELECT event_type, status, payload FROM outbox_events ... AND
  event_type = 'publish_completed'` → `assert completed_event.status ==
  "completed"`. Y en unit
  `test_publish_reel.py:307-308`: `assert event["event_type"] ==
  "publish_completed"; assert event["status"] == "completed"`.

### B. Calidad del código

- [x] **B1** Inter-módulo: `publish_reel.py` solo importa de
  `modules.reels.domain` (su propio módulo, `:50`). NO importa de
  `<otro>.application` ni `<otro>.infrastructure`. Imports legacy
  aceptados en Phase 2 (`application/types`, `core/errors`,
  `core/logging`, `settings`) y modernos (`shared.db`).
- [x] **B2** `CompositeMediaPublisher` adapter delgado:
  `media_services.py:319-368` (50 LoC con docstring + 4 alias),
  docstring presente (`:320-329`), `__init__` ignora
  `unit_of_work_factory` con `del unit_of_work_factory` (`:339`,
  comentario "legacy bootstrap arg; the use case owns its UoW."), aliases
  preservados: `publish_media:349-354`, `publish_video:356-361`,
  `publish_existing_media:363-364`, `publish_existing_video:366-367`.
  Cumple Protocol `MediaPublisher` (`interfaces.py:71-83`). ≤ 50 LoC
  (exactamente 50).
- [x] **B3** Sin `print()`, sin `xfail` nuevos, sin `TODO`/`FIXME` en
  archivos creados/modificados (verificado con grep:
  `publish_reel.py`, `test_publish_reel.py`, `test_publish_reel_flow.py`:
  0 hits).
- [x] **B4** Logs verbatim respecto al cuerpo eliminado: titles
  preservados byte-a-byte vs el composite legacy: "Publish Gating
  Decision" (`publish_reel.py:202`), "Review Requested" (`:238`),
  "Social Media Publish Started" (`:251`), "Social Media Publish
  Failed" (`:290`), "Social Media Publish Completed" (`:351`).
- [x] **B5** Firmas UoW moderno verificadas:
  - `uow.reels.states.update_publish_status(agency_id,
    ingestion_source_id, external_source_id, source_property_id, status,
    details, last_published_provider_external_id)`
    (`publish_reel.py:429-437`). Kw-arg moderno
    `last_published_provider_external_id` usado (NO
    `last_published_location_id`).
  - `uow.reels.states.update_workflow_state(... current_revision_id=...)`
    (`publish_reel.py:438-445`). `current_revision_id` opcional pasado
    como `published_media.revision_id or None`.
  - `uow.reels.revisions.save_revision(MediaRevision(...))` con dataclass
    moderno (`publish_reel.py:447-468`). 14 campos con
    `ingestion_source_id` y `external_source_id` (no
    `wordpress_source_id` ni `site_id`).
  - `uow.delivery.outbox.add_event(... status='completed' ...)` en camino
    `publish_completed` (`publish_reel.py:336, 469-486`). `created_at`
    no-vacío (`_now_iso()`) — aprende del aprendizaje R10 feature 12.
- [x] **B6** Naming Phase 2: use case expone `execute()`
  (`publish_reel.py:148`) y `execute_existing()`
  (`publish_reel.py:158`). El adapter `CompositeMediaPublisher` conserva
  nombres legacy `publish_media`, `publish_video`, `publish_existing_media`,
  `publish_existing_video` por contrato Protocol.

### Decisiones a verificar (del explore)

- [x] **D5 (outbox `completed`)**: `publish_reel.py:332-336`:
  `is_completed_path = aggregate_status in {"published","partial"}`;
  `outbox_status = "completed" if is_completed_path else "pending"`. El
  use case pasa `status='completed'` solo en camino `publish_completed`
  (verificado vía `Grep "completed"`: hit en línea 336 + línea de
  docstring 12). Otros caminos (`publish_skipped`, `review_requested`,
  `publish_failed`) usan default `'pending'` (verificado en los unit
  tests 3-7, 9-10).
- [x] **D6 (rename)**: `last_published_provider_external_id` usado en
  `publish_reel.py:233, 313, 344, 380, 395, 407, 421, 436`. Búsqueda
  `Grep "last_published_location_id" publish_reel.py`: 0 hits.
- [x] **D7 (unificación EXISTING_MEDIA_REQUIRED)**: `execute_existing`
  delega a `local_publisher.publish_existing_media(context)`
  (`publish_reel.py:164`), NO duplica check inline. Single source of
  truth en `PersistLocalArtifactsUseCase.execute_existing` (feature 12).
  El test unit `test_execute_existing_raises_when_no_existing_artifact`
  (`test_publish_reel.py:580-594`) valida que el error se propaga desde
  el local publisher.
- [x] **R1 (helpers duplicados)**: `_now_iso`, `_relative_path_text`,
  `_build_workflow_payload` están en `publish_reel.py:62-109` Y
  BORRADOS de `media_services.py` (`Grep
  "_now_iso\|_relative_path_text\|_build_workflow_payload"`: 0 hits).
- [x] **R4 (class shadow)**: `class
  CompositeMediaPublisher(CompositeMediaPublisher): pass` BORRADO
  (`Grep "class CompositeMediaPublisher\(CompositeMediaPublisher\)"
  application/pipeline/media_services.py`: 0 hits).
- [x] **R8 (imports limpieza)**: `media_services.py` NO tiene los
  imports huérfanos esperados. Verificado con `Grep
  "REVIEW_WORKFLOW_ENABLED|SocialPublishingResultError|TransientSocialPublishingResultError|extract_error_details|build_log_context|format_context_line|GoHighLevelPropertyPublisher|MultiPlatformPublishResult|MediaRevisionRecord|ValidationError"`:
  0 hits. `Grep "datetime|timezone"`: 0 hits. CONSERVADOS según R8 list:
  `format_console_block` (`:23`), `format_detail_line` (`:24`), `Path`
  (`:6`), `logging` (`:3`), `Callable` (`:5`), `UnitOfWork` (`:10`),
  `uuid4` (`:7`), `tempfile` (`:4`).
- [x] **R13 (re-eleva failed)**: el camino `failed` re-eleva la
  excepción tras persistir (`publish_reel.py:316`: `raise` desnudo
  después de `_publish_with_uow` con `workflow_state="failed"`). Tests
  unit 9 y 10 (`pytest.raises(SocialPublishingResultError)`,
  `pytest.raises(TransientSocialPublishingResultError)`) lo validan.

### C. Tests

- [x] **C1** Unit tests usan stubs UoW + `_FakePublisher` +
  `_StubLocalPublisher` inline (`test_publish_reel.py:56-154`); no DB
  real. Patrón consistente con feature 12.
- [x] **C2** Cobertura de los 12 tests cumple el mínimo de 8: feliz
  `published` (test 1), `partial` (test 2), 4 `skipped` distintos
  (tests 3-6: `social_publisher=None`, `requires_external_publish=False`,
  `publish_context=None`, provider returns `None`), 2 `awaiting_review`
  (tests 7-8: agency `approval_required` y env flag), 2 `failed`
  (tests 9-10: `SocialPublishingResultError` con `result`,
  `TransientSocialPublishingResultError` con `result=None`),
  `EXISTING_MEDIA_REQUIRED` (test 11), `execute_existing` con artefacto
  (test 12).
- [x] **C3** Integration test usa `temporary_postgres_schema` +
  `seed_tenant` + `seed_provider_connection` + `temporary_workspace`
  (`test_publish_reel_flow.py:152-160`). SQL directo con `text(...)` y
  `create_engine` (`:249-303`). Sin mocks de Postgres. Encadena
  ingest → prepare → persist → publish con provider stub
  (`:163-244`).
- [x] **C4** Tests de features 10/11/12 siguen verdes sin tocarlos.
  Verificado en init.sh: 396 previos pasan intactos + 13 nuevos = 409.

### Bootstrap

- [x] **Bootstrap1** `application/bootstrap/runtime.py` y
  `application/bootstrap/__init__.py` modificados con
  `workspace_dir=workspace_path` añadido a la llamada
  `CompositeMediaPublisher(...)` (línea 126 en runtime.py). `diff
  application/bootstrap/runtime.py application/bootstrap/__init__.py`
  exit 0 (sin diff entre sí).

### E. Acoplamientos

- [x] **E1** `media_services.py` post-13 NO contiene `_now_iso`,
  `_relative_path_text`, `_build_workflow_payload` (R9). `Grep`: 0 hits.
- [x] **E2** NO contiene `_publish_externally`,
  `_persist_workflow_transition`, `_build_publish_details` (`Grep`: 0
  hits).
- [x] **E3** `application/pipeline/media_pipeline.py` no se tocó (133
  LoC sin cambios).
- [x] **E4** `application/pipeline/interfaces.py` no se tocó (112 LoC
  sin cambios). Protocol `MediaPublisher` intacto.
- [x] **E5** `application/pipeline/default_services.py` sigue
  funcionando (re-export de `CompositeMediaPublisher` + 5 más sin
  cambios funcionales). `apps.api --check` y `apps.worker --check`
  exit 0.
- [x] **E6** Class shadow `CompositeMediaPublisher` BORRADO. Otros class
  shadows (`DefaultMediaRenderer:267-268`) siguen vivos hasta feature 14
  (out of scope).

### F. Schema

- [x] **F1** Sin nueva migración en `alembic/versions/` desde feature
  12 (verificado: solo `20260501_0001_initial_schema.py` y
  `__pycache__/`). Feature 13 NO toca schema, conforme.

## Confirmación de checks de cierre

| Check | Resultado |
|-------|-----------|
| `wc -l modules/reels/application/use_cases/publish_reel.py` | 495 |
| `wc -l application/pipeline/media_services.py` | 377 (de 677 — reducción 300 LoC) |
| `wc -l tests/unit/reels/test_publish_reel.py` | 623 (12 tests) |
| `wc -l tests/integration/reels/test_publish_reel_flow.py` | 304 (1 test) |
| `pytest -q` (init.sh) | 409 passed in 192.75 s |
| `apps.api --check` / `apps.worker --check` | exit 0 ambos |
| `diff application/bootstrap/runtime.py application/bootstrap/__init__.py` | exit 0 (sin diff) |
| `grep build_log_context application/pipeline/media_services.py` | 0 hits |
| `grep _now_iso\|_relative_path_text\|_build_workflow_payload application/pipeline/media_services.py` | 0 hits |
| `grep MediaRevisionRecord application/pipeline/media_services.py` | 0 hits |
| `grep last_published_location_id modules/reels/application/use_cases/publish_reel.py` | 0 hits |
| `grep "completed" modules/reels/application/use_cases/publish_reel.py` | 1 hit en línea 336 (`outbox_status = "completed" if is_completed_path else "pending"`) + 1 hit docstring |
| `grep "class CompositeMediaPublisher(CompositeMediaPublisher)" application/pipeline/media_services.py` | 0 hits (class shadow eliminado) |
| Nueva migración en `alembic/versions/` | NO (correcto — feature 13 no toca schema) |
| Tests nuevos | 12 unit (≥ 8 requerido) + 1 integration |
| Adapter `CompositeMediaPublisher` LoC | 50 (≤ 50 requerido) |

## Sugerencias menores

(No bloquean; documentadas para el siguiente paso.)

1. `application/pipeline/__init__.py` (1839 LoC) sigue siendo dead code
   pre-existente. Ya señalado en reviews features 10/11/12. Feature 13 no
   lo empeora ni lo arregla — queda para feature 14 o 18.
2. El class shadow `class DefaultMediaRenderer(DefaultMediaRenderer):
   pass` (`media_services.py:267-268`) sigue vivo. Out of scope; lo
   limpiará feature 14.
3. `media_services.py` post-feature-13 queda en 377 LoC, ligeramente por
   encima del rango 340-370 estimado por el explorer. Diferencia debido
   a las firmas multi-línea del adapter. No bloquea.
4. El cambio semántico `outbox.status='completed'` en camino
   `publish_completed` (vs default `'pending'` legacy) está documentado
   y verificado en tests. Si feature 16 (worker real) descubre que un
   consumidor del outbox espera `'pending'` para reaccionar, ajustar
   entonces.
