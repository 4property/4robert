# Impl — Feature 13 `reels_use_case_publish_reel`

> Extracción del paso 4 del pipeline (publish externo + persistencia de
> la transición de workflow) desde `application/pipeline/media_services.py`
> hacia `modules/reels/application/use_cases/publish_reel.py` con clase
> `PublishReelUseCase`. Conforme al plan del explorer
> (`progress/explore_feature_13_publish_reel.md`).

---

## 1. Archivos creados / modificados / borrados

### Creados

| Archivo | LoC | Tipo |
|---------|-----|------|
| `modules/reels/application/use_cases/publish_reel.py` | 495 | Use case + helpers duplicados (`_now_iso`, `_relative_path_text`, `_build_workflow_payload`) + métodos privados (`_publish_externally`, `_publish_with_uow`, `_persist_with_uow`, `_build_publish_details`). |
| `tests/unit/reels/test_publish_reel.py` | 623 | Unit (12 tests cubriendo `publish_completed`, `partial`, 4 caminos `skipped` distintos, 2 caminos `awaiting_review`, 2 caminos `failed`, y 2 caminos `execute_existing`). |
| `tests/integration/reels/test_publish_reel_flow.py` | 304 | Integration (`temporary_postgres_schema` + `seed_tenant` + `seed_provider_connection` + `temporary_workspace`, encadena ingest → prepare → persist → publish; valida `reels.workflow_state='published'`, `reels.publish_status='published'`, `reels.last_published_provider_external_id='loc-test'`, `media_revisions.workflow_state='published'`, `outbox_events.event_type='publish_completed'` con `status='completed'` y payload con `aggregate_status='published'` + `successful_platforms=['tiktok']`). 1 test. |

### Modificados

| Archivo | Cambio |
|---------|--------|
| `application/pipeline/media_services.py` | 677 → **377 LoC** (300 LoC eliminados, ~44% reducción). Borrado: `CompositeMediaPublisher.__init__` + `publish_media` + `publish_video` + `publish_existing_media` + `publish_existing_video` + `_publish_externally` + `_persist_workflow_transition` + `_build_publish_details` + class shadow `class CompositeMediaPublisher(CompositeMediaPublisher): pass` (R4); helpers de módulo `_now_iso` + `_relative_path_text` + `_build_workflow_payload` (R9, R1). Insertado adapter delgado `CompositeMediaPublisher` (~50 LoC con docstring + 4 alias) que delega a `PublishReelUseCase`. Imports limpiados (R8): `REVIEW_WORKFLOW_ENABLED`, `SocialPublishingResultError`, `TransientSocialPublishingResultError`, `extract_error_details`, `build_log_context`, `format_context_line`, `GoHighLevelPropertyPublisher`, `MultiPlatformPublishResult`, `MediaRevisionRecord`, `datetime, timezone`, `ValidationError`. Conservados explícitamente (R8 lista CONSERVAR): `Callable`, `UnitOfWork`, `uuid4`, `tempfile`, `Path`, `logging`, `format_console_block`, `format_detail_line`. Añadido import de `PublishReelUseCase`. |
| `application/bootstrap/runtime.py` | +1 LoC: `workspace_dir=workspace_path` añadido a la llamada `CompositeMediaPublisher(...)` en `build_default_property_media_pipeline` (D3, necesario para que el use case abra `DatabaseUnitOfWork(..., base_dir=workspace_dir)`). |
| `application/bootstrap/__init__.py` | +1 LoC idéntico a `runtime.py` (siguen byte-a-byte iguales — `diff` exit 0 verificado). |
| `modules/reels/application/use_cases/__init__.py` | +1 import + +1 entrada en `__all__` para re-exportar `PublishReelUseCase`. |
| `feature_list.json` | Feature 13 status `pending` → `in_progress`. |

### Borrados

Ninguno físicamente. Dentro de `media_services.py` se borró el cuerpo entero de `CompositeMediaPublisher` (composite + helpers privados) y el class shadow `class CompositeMediaPublisher(CompositeMediaPublisher): pass` (R4). También se borraron los 3 helpers de módulo (`_now_iso`, `_relative_path_text`, `_build_workflow_payload`) — quedaban huérfanos tras la extracción (R9).

---

## 2. Líneas eliminadas de `application/pipeline/media_services.py`

Archivo de entrada (post-feature-12): **677 LoC**.
Archivo de salida (post-feature-13): **377 LoC**.
Reducción neta: **300 LoC eliminados** (~44%).

Rangos borrados (relativos al archivo de entrada de 677 LoC):

- `:67-112` — helpers de módulo `_now_iso` + `_relative_path_text` + `_build_workflow_payload` (R9, ~46 LoC). Tras feature 13 nadie en `media_services.py` los usa: el composite los movió al use case nuevo.
- `:381-663` — `class CompositeMediaPublisher` (cuerpo entero: `__init__` + `publish_media`/`publish_video`/`publish_existing_media`/`publish_existing_video` + `_publish_externally` + `_persist_workflow_transition` + `_build_publish_details`, ~283 LoC).
- `:666-667` — class shadow `class CompositeMediaPublisher(CompositeMediaPublisher): pass` (R4).

Adapter delgado insertado en su lugar (~50 LoC con docstring + 4 alias `publish_media`/`publish_video`/`publish_existing_media`/`publish_existing_video` para no romper el Protocol `MediaPublisher` ni callers desconocidos). Constructor recibe `unit_of_work_factory` por compat (lo descarta con `del`) y `workspace_dir` (obligatorio ahora — D3) y opcionalmente `social_publisher`.

Imports huérfanos limpiados (R8):

- `from settings import REVIEW_WORKFLOW_ENABLED` (solo lo usaba `_publish_externally`).
- `from core.errors import SocialPublishingResultError, TransientSocialPublishingResultError, ValidationError, extract_error_details` (solo el composite los usaba).
- `from core.logging import build_log_context, format_context_line` (solo el composite los usaba; `format_console_block` y `format_detail_line` se conservan porque las usa `DefaultMediaRenderer`).
- `from repositories.stores.media_revision_store import MediaRevisionRecord` (solo `_persist_workflow_transition` lo usaba).
- `from services.publishing.social_delivery import GoHighLevelPropertyPublisher, MultiPlatformPublishResult` (solo el composite los usaba).
- `from datetime import datetime, timezone` (solo `_now_iso`, ahora borrado).

Imports añadidos:

- `from modules.reels.application.use_cases.publish_reel import PublishReelUseCase` (consumido por el adapter delgado).

Imports conservados explícitamente (los necesita `DefaultMediaRenderer` o los adapters legacy):

- `Callable`, `UnitOfWork` — `__init__` de los 4 adapters legacy.
- `uuid4`, `tempfile`, `Path` — `DefaultMediaRenderer._render_reel`.
- `format_console_block`, `format_detail_line` — `DefaultMediaRenderer` log block.
- `logging` — logger global.

---

## 3. Decisiones del leader respetadas

- **D1 (`WordPressWebhookApplication.publish` legacy no existe)**: confirmado en el explore report. La acceptance literal "Sustituye la lógica del WordPressWebhookApplication.publish" es inerte porque feature 9 (status `done`) ya borró la clase. Sin acción.
- **D2 (`seed_provider_connection`)**: el use case `PublishReelUseCase` NO consulta `provider_connections` en feature 13 (out of scope; el `SocialPublishContext` viene pre-resuelto upstream). El integration test SÍ siembra una fila válida vía `seed_provider_connection(database.url, agency_id=..., provider="gohighlevel", external_id="loc-test")` por alineación literal con el acceptance y como preparación de feature 16.
- **D3 (bootstrap pasa `workspace_dir`)**: añadido `workspace_dir=workspace_path` a la llamada `CompositeMediaPublisher(...)` en `application/bootstrap/runtime.py` y `application/bootstrap/__init__.py`. +1 LoC en cada archivo. Los dos archivos siguen byte-a-byte iguales (`diff` exit 0 verificado).
- **D4 (naming)**: el use case expone `execute(context, rendered_media, *, uow=None)` y `execute_existing(context, *, uow=None)`. El adapter `CompositeMediaPublisher` mantiene `publish_media`, `publish_video`, `publish_existing_media`, `publish_existing_video` para no romper el Protocol `MediaPublisher` (`interfaces.py:71-83`) ni callers desconocidos. Patrón idéntico a features 10/11/12.
- **D5 (outbox `status='completed'`)**: el use case pasa `status='completed'` a `outbox.add_event` SOLO cuando `event_type='publish_completed'` (camino `aggregate_status in {"published","partial"}` post-2xx del provider). Otros caminos (`publish_skipped`, `review_requested`, `publish_failed`) usan default `'pending'`. **Cambio semántico intencional vs legacy** (R11): el composite legacy NO pasaba `status` a `add_event` (default `'pending'`). El acceptance literal pide forzar `'completed'` cuando el provider devuelve 2xx para que el outbox relay no procese de nuevo el evento (la entrega ya ocurrió en la misma transacción). Si feature 16 (worker real) descubre que un consumidor del outbox espera `'pending'` para reaccionar, ajustar entonces.
- **D6 (`last_published_location_id` → `last_published_provider_external_id`)**: el use case pasa el kw-arg moderno `last_published_provider_external_id=context.publish_context.location_id` a `uow.reels.states.update_publish_status(...)`. Verificado contra `modules/reels/infrastructure/reel_state_repository.py:183-231`.
- **D7 (unificación `EXISTING_MEDIA_REQUIRED`)**: `PublishReelUseCase.execute_existing` delega a `local_publisher.publish_existing_media(context)` (que internamente llama `PersistLocalArtifactsUseCase.execute_existing` que ya valida y eleva `ValidationError(code="EXISTING_MEDIA_REQUIRED")`). Single source of truth en feature 12. NO se duplicó el check inline en feature 13. El test unit `test_execute_existing_raises_when_no_existing_artifact` valida que el error sigue propagándose desde el local publisher.
- **R1 (helpers duplicados)**: `_now_iso`, `_relative_path_text`, `_build_workflow_payload` están duplicados en `publish_reel.py:64-110` (frente a sus copias originales en `persist_local_artifacts.py:65-112` introducidas por feature 12). Trade-off explícito documentado en el docstring del módulo: feature 14 unificará. Coste 46 LoC duplicados a cambio de independencia entre use cases.
- **R3 (rename UoW)**: el use case usa `ingestion_source_id` (en lugar de `wordpress_source_id`) y `external_source_id` (en lugar de `site_id`) en todas las llamadas a `uow.reels.states.*`, `uow.reels.revisions.save_revision(MediaRevision(...))` y `uow.delivery.outbox.add_event(...)`. `external_source_id` se normaliza con `str(context.site_id or "").strip().lower()` (mismo patrón feature 12).
- **R4 (class shadow)**: borrado al reescribir la clase `CompositeMediaPublisher` como adapter delgado. `grep "class CompositeMediaPublisher(CompositeMediaPublisher)" application/pipeline/media_services.py`: 0 hits. Los class shadows de `DefaultMediaRenderer:259-260` siguen vivos (out of scope, los limpia feature 14).
- **R8 (imports limpieza)**: confirmados con grep final 0 hits para los 12 imports huérfanos listados (`REVIEW_WORKFLOW_ENABLED`, `SocialPublishingResultError`, `TransientSocialPublishingResultError`, `extract_error_details`, `build_log_context`, `format_context_line`, `GoHighLevelPropertyPublisher`, `MultiPlatformPublishResult`, `MediaRevisionRecord`, `datetime, timezone`, `ValidationError`). Conservados los que sí se usan: `Callable`, `UnitOfWork`, `uuid4`, `tempfile`, `Path`, `logging`, `format_console_block`, `format_detail_line`.
- **R9 (helpers de módulo)**: borrados `_now_iso`, `_relative_path_text`, `_build_workflow_payload` de `media_services.py` (los duplicó el use case `publish_reel.py`). Verificado con grep final que no quedan referencias en `media_services.py`.
- **R11 (cambio outbox `completed`)**: documentado en D5. Cambio intencional vs legacy.
- **R13 (re-eleva en camino failed)**: el use case re-eleva la excepción `SocialPublishingResultError` / `TransientSocialPublishingResultError` (o cualquier otra `Exception`) tras persistir el workflow `failed` (mismo comportamiento legacy). El test unit `test_execute_failed_persists_failed_state_and_reraises` valida que la excepción se re-eleva tras escribir las 4 filas DB.

---

## 4. Decisiones de implementación adicionales

### 4.1 — Adapter `CompositeMediaPublisher` recibe `social_publisher: object | None`

El composite legacy lo declaraba `social_publisher: GoHighLevelPropertyPublisher | None`. Como el use case `PublishReelUseCase` usa duck-typing (acepta cualquier objeto con `publish_property_media(context, published_media)` que devuelva un `MultiPlatformPublishResult`-like o eleve), simplifico la firma del adapter a `object | None` (idéntica decisión que feature 12 con el `local_publisher`). Coherente con D10 del explore.

### 4.2 — `_publish_with_uow` separado de `_persist_with_uow`

El use case introduce dos niveles: `_publish_with_uow(...)` decide si abrir un UoW nuevo o usar el inyectado, y `_persist_with_uow(...)` (staticmethod) ejecuta los inserts/updates dentro de un UoW activo. Patrón idéntico a `PersistLocalArtifactsUseCase`. Permite que el integration test pase un UoW gestionado externamente sin duplicar la lógica de persistencia.

### 4.3 — Adapter test inline `_LocalPublisherAdapter` en el integration

`FileSystemMediaPublisher` (adapter feature 12) NO acepta `database_locator`; solo `workspace_dir`. En producción esto está bien (todo el sistema usa `DATABASE_URL` de settings). En el integration test, donde el UoW debe apuntar al schema temporal scoped, se usa un adaptor inline `_LocalPublisherAdapter` que envuelve `PersistLocalArtifactsUseCase(database_locator=database.url)` en una clase con `publish_media`/`publish_existing_media`. Mantiene el use case bajo prueba sin tocar feature 12 ni introducir un nuevo kw-arg en el adapter legacy. Documentado en el docstring de la clase (`tests/integration/reels/test_publish_reel_flow.py`).

### 4.4 — Stubs UoW inline en el unit test

`_StubReelStates`, `_StubMediaRevisions`, `_StubOutbox`, `_FakePublisher`, `_StubLocalPublisher` viven inline en `tests/unit/reels/test_publish_reel.py:48-140`. Decisión coherente con feature 11 y 12 (review feature 11 lo aceptó como patrón razonable: cada use case posee sus stubs si las APIs varían lo bastante para no compartirlos). `_uow_stubs.py` no se amplió.

### 4.5 — `failure_details` extrae `to_dict()` defensivamente

En el camino `failed`, el composite legacy intentaba `error.result` y luego `_build_publish_details(error.result)` directamente. El use case nuevo hace duck-typing: `if isinstance(error, (SocialPublishingResultError, TransientSocialPublishingResultError)) and getattr(error, "result", None) is not None`. Si `error.result.to_dict` es callable, se sobrescribe `failure_details` con su dict. Si no (ej. `result=None`), se conserva el `extract_error_details(error)` original. Esto cubre el test `test_execute_transient_failed_persists_failed_state_and_reraises` donde `result=None`.

---

## 5. Resultado de los checks de cierre

### Tests

```
$ ./.venv/Scripts/python.exe -m pytest -q tests/unit/reels/test_publish_reel.py
12 passed in 1.18s

$ ./.venv/Scripts/python.exe -m pytest -q tests/integration/reels/test_publish_reel_flow.py
1 passed in 2.66s

$ ./.venv/Scripts/python.exe -m pytest -q tests/unit/reels/ tests/integration/reels/
66 passed in 38.71s

$ ./init.sh
...
409 passed in 195.41s (0:03:15)
[OK]    pytest verde
```

Baseline pre-feature-13: **396 tests** (post-feature-12).
Post-feature-13: **409 tests** (396 + 12 unit + 1 integration). Esperado ≥ 408 — cumplido (1 test extra).

### Readiness

```
$ ./.venv/Scripts/python.exe -m apps.api --check
RUNTIME READY: Yes (sin warnings nuevos)

$ ./.venv/Scripts/python.exe -m apps.worker --check
Worker --check OK: kinds=reel_publish,scripted_render worker_count=1 lease=900s poll=0.50s
```

Ambos exit 0. `init.sh` verde end-to-end (incluye lint legacy WARN sobre 4 archivos en directorios legacy modificados — `media_services.py` + bootstrap `runtime.py`/`__init__.py` + `default_services.py` por la cadena de re-exports; modificación quirúrgica permitida por las reglas de Phase 2).

### Repo limpio

- Sin `xfail`, sin `print()` debug, sin `TODO`/`FIXME` en archivos creados/modificados (`grep -nE "print\(|xfail|TODO|FIXME" publish_reel.py test_publish_reel.py test_publish_reel_flow.py`: 0 hits).
- Sin `__pycache__/.tmp_*` residual fuera de los gestionados por pytest.
- `application/bootstrap/runtime.py` y `application/bootstrap/__init__.py` siguen byte-a-byte iguales entre sí (`diff` exit 0).
- Class shadow `CompositeMediaPublisher` borrado.
- Todos los imports orphans limpiados (`grep` final con la lista R8: 0 hits para los 12 huérfanos).
- Tests legacy de features 10/11/12 verdes sin tocarlos (verificado en init.sh: 396 previos pasan intactos + 13 nuevos = 409).

---

## 6. Desviaciones frente al plan del explorer

1. **LoC final 377 vs estimado 340-370**: ligeramente por encima del rango previsto por más LoC en el adapter delgado (~50 vs ~35 estimados, debido al docstring largo y los 4 alias). Aún dentro del orden de magnitud. Reducción 300 LoC (~44%) coherente con la trayectoria features 10/11/12.
2. **Adapter test `_LocalPublisherAdapter` inline en integration**: el explorer no lo previó. Necesario porque `FileSystemMediaPublisher` no acepta `database_locator`. Documentado en §4.3.
3. **`mime_type` y `revision_id` flow**: ambos `persist` y `publish` usan el mismo `revision_id` (la transición workflow `rendered → published` es sobre la misma revision). El `media_revisions.save_revision` upsertea (`ON CONFLICT (revision_id) DO UPDATE`), así que el integration test valida que la fila final tiene `workflow_state='published'` (no que existan dos filas separadas). Documentado inline en el assert del integration test.
4. **`social_publisher: object | None`**: el explorer sugería type-hint `GoHighLevelPropertyPublisher | None` o un `Protocol` interno. Opté por `object | None` (duck-typing) para minimizar imports y simplificar el adapter — coherente con D10. Si feature 16 quiere más rigor, refactoriza entonces.
5. **`PublishReelUseCase` opcional `workspace_dir`**: el use case acepta `workspace_dir=None`. Si es `None` y se llama `_publish_with_uow(...)` sin uow inyectado, el `DatabaseUnitOfWork` se construye con `base_dir=None`. Como `update_publish_status`/`update_workflow_state`/`save_revision`/`outbox.add_event` no requieren `base_dir`, esto funciona. La variante `workspace_dir=workspace_path` se pasa desde bootstrap por consistencia y para preparar feature 14. El test integration usa la versión con `workspace_dir`.

---

**Fin del informe.**
