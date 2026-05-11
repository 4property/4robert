# Explore — Feature 13 `reels_use_case_publish_reel`

> Mapa de extracción del paso 4 del pipeline (publicación externa final:
> invocar el adapter del provider, persistir la transición de workflow en
> `reels`/`media_revisions`/`outbox_events`, marcar el reel `published`)
> desde `application/pipeline/media_services.py` (677 LoC tras feature 12)
> hacia `modules/reels/application/use_cases/publish_reel.py` con clase
> `PublishReelUseCase`.

Contexto leído:
- `feature_list.json` (entry #13, acceptance / desc).
- `progress/explore_feature_12_persist_local_artifacts.md` (especialmente
  §1 sobre clases dejadas intactas y §6 R1/R7 sobre cruce con paso 4).
- `progress/impl_12_persist_local_artifacts.md`,
  `progress/review_12_persist_local_artifacts.md` (patrón aplicado y
  R10 `created_at` outbox).
- `application/pipeline/media_services.py` (677 LoC actual, leído
  íntegramente).
- `application/pipeline/media_pipeline.py` (orquestador).
- `application/pipeline/interfaces.py` (Protocol `MediaPublisher`).
- `application/pipeline/default_services.py` (re-export de adapters).
- `application/pipeline/__init__.py` (1839 LoC, dead code que duplica el
  legacy completo; mantiene `social_publisher`/`publish_property_media`
  pero NO se importa desde `apps/`/`modules/`).
- `application/bootstrap/runtime.py` y
  `application/bootstrap/__init__.py` (byte-iguales tras feature 12).
- `services/publishing/social_delivery/__init__.py`,
  `services/publishing/social_delivery/property_publisher.py`,
  `services/publishing/social_delivery/models.py` (entrypoints provider).
- `modules/publishing/infrastructure/adapters/gohighlevel/__init__.py`,
  `modules/publishing/infrastructure/adapters/gohighlevel/publisher.py`
  (adapter moderno: solo `GoHighLevelPublisher` y normalización).
- `modules/publishing/application/use_cases/` (10 use cases CRUD/inspección
  de connections; **ninguno de ellos publica media**).
- `modules/publishing/infrastructure/provider_connection_repository.py`
  (`get_with_secrets`, `get_by_provider_external_id_with_secrets`).
- `modules/reels/application/use_cases/persist_local_artifacts.py` (351 LoC,
  patrón de feature 12 a copiar).
- `modules/reels/application/use_cases/prepare_reel_assets.py` (447 LoC).
- `modules/reels/application/use_cases/ingest_property_into_reel.py` (944 LoC).
- `modules/reels/application/use_cases/__init__.py`.
- `shared/db/uow.py` (DatabaseUnitOfWork moderno).
- `modules/reels/infrastructure/reel_state_repository.py` (
  `update_publish_status`, `update_workflow_state`, `save_local_artifacts`).
- `modules/reels/infrastructure/media_revision_repository.py` (
  `save_revision(MediaRevision)`).
- `modules/delivery/infrastructure/outbox_repository.py` (
  `add_event` con kw-args modernos, `created_at` no-vacío obligatorio).
- `tests/support/postgres.py` — `seed_provider_connection` ya existe
  (`:226-269`). Insertaba `provider_connections` con tokens cifrados via
  `encrypt_text`. NO hay que crearla.
- `tests/unit/reels/_uow_stubs.py` (stubs por convención).
- `tests/unit/reels/test_persist_local_artifacts.py` y
  `tests/integration/reels/test_persist_local_artifacts_flow.py`
  (patrón a copiar).
- `tests/test_social_publishing.py` (`FakePublisher` con
  `publish_video_to_platforms`, line 1511, 1573, 1632, 1667 — reusable
  como stub del provider en este feature).
- `apps/worker/runtime.py:259-279` (registra `reel_publish` →
  `ReelPipeline.handle` → bridge `build_default_job_handler`).
- `modules/reels/application/orchestrator.py:12-62` (`ReelPipeline.handle`).
- `docs/phase_2_operating_rules.md`, `docs/architecture.md`,
  `docs/conventions.md`.

---

## 0. Decisión de alcance: qué se mueve y qué se queda

`feature_list.json` #13 dice literalmente:

> Publicación final: invoca el adaptador de publishing correspondiente,
> escribe `outbox_event`, marca el reel `published`. Sustituye la lógica
> del `WordPressWebhookApplication.publish`.

Tres frases clave, las analizo:

1. **"Invoca el adaptador del publishing correspondiente"** — hoy lo hace
   `CompositeMediaPublisher._publish_externally` (`media_services.py:425-593`).
   Llama a `self.social_publisher.publish_property_media(...)` (línea 518)
   donde `social_publisher` es un
   `GoHighLevelPropertyPublisher` (`services/publishing/social_delivery/property_publisher.py`).
2. **"Escribe `outbox_event`, marca el reel `published`"** — lo hace
   `CompositeMediaPublisher._persist_workflow_transition` (
   `media_services.py:595-659`). Escribe en 3 tablas: `reels` (
   `update_social_publish_status` + `update_workflow_state`),
   `media_revisions` (`save_media_revision`), `outbox_events` (
   `add_event`). Cobertura del acceptance literal "outbox_events recibe
   la fila correcta con `status='completed'` cuando el provider devuelve
   2xx" — el `status='completed'` aplica al **outbox row** (la columna
   `outbox_events.status` tiene default `'pending'`; el acceptance pide
   forzar `'completed'` para esta vía cuando el provider devuelve 2xx).
   **Atención**: la firma actual de `_persist_workflow_transition` NO
   pasa `status` a `add_event` — usa el default `'pending'`. **El use
   case nuevo debe pasar `status='completed'` explícitamente cuando
   `aggregate_status in {"published","partial"}`** para satisfacer el
   acceptance literal. Documentado en §3 y §5.
3. **"Sustituye la lógica del `WordPressWebhookApplication.publish`"** —
   `WordPressWebhookApplication` **YA NO EXISTE** en el repo. Feature 9
   (`retire_wordpress_webhook_server`, status `done`) borró
   `services/transport/http/server.py` y disolvió toda la god-class. Único
   rastro vivo: un comentario doc-string en `apps/api/admin_auth.py:45`
   ("`WordPressWebhookApplication.__init__` when feature 9 dissolved that
   class"). El acceptance es **inerte** en este punto; en la práctica
   feature 13 solo extrae la composite. Documentado como discrepancia
   D1 en §8.

### Qué se mueve a `publish_reel.py` (use case nuevo)

Todo el cuerpo de `CompositeMediaPublisher`:

- `__init__` (`media_services.py:382-391`): recibe `local_publisher`,
  `unit_of_work_factory` (legacy), `social_publisher`. **Adaptar al
  patrón features 10/11/12**: `del unit_of_work_factory`, el use case
  abre su propio `DatabaseUnitOfWork` moderno; `local_publisher` se
  reemplaza por `PersistLocalArtifactsUseCase` directo (DI explícito); el
  `social_publisher` (Protocol-like, hoy `GoHighLevelPropertyPublisher`)
  sigue siendo inyectable para que tests pasen un fake.
- `publish_media` (`:393-399`) → `execute(context, rendered_media)` del
  use case nuevo.
- `publish_video` (`:401-406`) — alias legacy. **Mover al adapter** que
  reemplaza `CompositeMediaPublisher` en `media_services.py`.
- `publish_existing_media` (`:408-420`) → `execute_existing(context)` del
  use case nuevo.
- `publish_existing_video` (`:422-423`) — alias. Idem `publish_video`.
- `_publish_externally` (`:425-593`) — privado del use case (~169 LoC).
  Es el cuerpo grande: gating REVIEW_WORKFLOW + try/except sobre
  `social_publisher.publish_property_media` + dispatch del
  `_persist_workflow_transition` con distintos `workflow_state` según
  resultado.
- `_persist_workflow_transition` (`:595-659`) — privado del use case
  (`_persist_with_uow` siguiendo la nomenclatura features 11/12). Escribe
  4 inserts/updates en una sola transacción.
- `_build_publish_details` (`:661-663`) — staticmethod helper.

### Qué se queda

- `DefaultMediaRenderer` (`:196-326`) y su class shadow `:329-330` — sale
  con feature 14.
- `DefaultPropertyInfoService` (`:115-146`) — adapter feature 10. Intacto.
- `DefaultMediaPreparationService` (`:149-193`) — adapter feature 11. Intacto.
- `FileSystemMediaPublisher` (`:333-378`) — adapter feature 12. Intacto.
- Helpers `_now_iso`, `_relative_path_text`, `_build_workflow_payload`
  (`:67-112`) — **TRAS FEATURE 13 quedan huérfanos en `media_services.py`**
  porque `_persist_workflow_transition` se mueve. **Acción**: borrar de
  `media_services.py` cuando ya nadie los use ahí (verificar con grep).
  Posible call site residual: `DefaultMediaRenderer` los usa? — `grep`
  rápido: `_now_iso` solo en `_persist_workflow_transition`,
  `_relative_path_text` solo idem, `_build_workflow_payload` solo idem.
  → **TODOS borrables tras la extracción**. Quedará una reducción
  adicional de ~46 LoC (líneas 67-112).
- Imports al tope que quedarán huérfanos tras feature 13:
  - `MediaRevisionRecord` (legacy, `:46`) — solo lo usa
    `_persist_workflow_transition`. **BORRAR tras la extracción**.
  - `format_console_block`, `format_context_line`, `format_detail_line`
    de `core.logging` (`:30-35`) — los usa `DefaultMediaRenderer` (
    `:269`), también `_publish_externally` (línea 451-468, 487-494, 497-515,
    526-541, 580-592). Tras mover `_publish_externally` → solo
    `DefaultMediaRenderer` usa estos formatters. **CONSERVAR** (los
    necesita el renderer hasta feature 14).
  - `build_log_context` (`:31`) — único call site post-feature-13:
    ningún call site queda en `media_services.py` (lo usaban
    `_publish_related_poster` movido en feature 12 y
    `publish_existing_media` movido en feature 13). **BORRAR**.
  - `SocialPublishingResultError`, `TransientSocialPublishingResultError`,
    `extract_error_details` (`:24-29`) — solo `_publish_externally` los
    usa. **BORRAR**.
  - `REVIEW_WORKFLOW_ENABLED` (`:19`) — solo `_publish_externally`. **BORRAR**.
  - `GoHighLevelPropertyPublisher`, `MultiPlatformPublishResult`
    (`:59-62`) — solo `_publish_externally` y type hint del composite
    `__init__`. **BORRAR**.
  - `Callable`, `UnitOfWork` (`:5, :11`) — los usan los `__init__` legacy
    de `DefaultPropertyInfoService`/`DefaultMediaPreparationService`/
    `FileSystemMediaPublisher` (todos los adapters legacy). **CONSERVAR**.
  - `uuid4` (`:8`) — lo usa `DefaultMediaRenderer:219` Y
    `_persist_workflow_transition:645`. Tras feature 13, solo el
    renderer. **CONSERVAR**.
  - `tempfile` (`:4`) — `DefaultMediaRenderer:223`. **CONSERVAR**.
  - `datetime, timezone` (`:6`) — solo `_now_iso`. **BORRAR**
    (cuando se borre el helper).

### Qué se queda como adapter delgado

`media_services.py` post-feature-13 contiene un adapter
`CompositeMediaPublisher` que cumple el Protocol `MediaPublisher`
(`interfaces.py:71-83`) y delega al use case:

```python
class CompositeMediaPublisher:
    def __init__(
        self,
        *,
        local_publisher: FileSystemMediaPublisher,
        unit_of_work_factory: Callable[[], UnitOfWork],
        social_publisher: GoHighLevelPropertyPublisher | None = None,
        workspace_dir: str | Path | None = None,
    ) -> None:
        del unit_of_work_factory  # legacy bootstrap arg.
        self.local_publisher = local_publisher
        self._use_case = PublishReelUseCase(
            workspace_dir=workspace_dir,
            local_publisher=local_publisher,
            social_publisher=social_publisher,
        )

    def publish_media(self, context, rendered_media):
        return self._use_case.execute(context, rendered_media)

    def publish_video(self, context, rendered_video):
        return self.publish_media(context, rendered_video)

    def publish_existing_media(self, context):
        return self._use_case.execute_existing(context)

    def publish_existing_video(self, context):
        return self.publish_existing_media(context)
```

LoC adapter estimado: ~30-40 (similar a `FileSystemMediaPublisher`
post-feature-12). El class shadow `class CompositeMediaPublisher(...): pass`
(`:666-667`) **se elimina al reescribir la clase**.

### Decisión: ¿el use case absorbe el `local_publisher` también?

**No.** El use case nuevo recibe `local_publisher` por DI (Protocol-like)
y lo invoca igual que hoy hace el composite. La razón:

- El acceptance habla solo del paso 4 ("invoca adaptador, escribe outbox,
  marca published"); fusionar pasos 3+4 acoplaría features 12 y 13
  innecesariamente y rompería el Protocol del pipeline.
- `media_pipeline.py:73` invoca `media_publisher.publish_existing_media(context)`
  (no pasa por el local), lo que asume composiciones distintas: el use
  case puede orquestar local→external solo en `execute(...)`, no en
  `execute_existing(...)`.

**La ortogonalidad mantiene el patrón de Phase 2.** El `local_publisher`
inyectado puede ser `FileSystemMediaPublisher` (en bootstrap) o
`PersistLocalArtifactsUseCase` directo (en tests integration con UoW
compartido). Ambas opciones funcionan porque el adapter delgado de
feature 12 ya delega al use case.

Si el leader prefiere otra interpretación (fusionar pasos 3+4 en un solo
use case `ReelPipeline.publish` o renombrar a `PublishReelUseCase` que
absorbe local+external), lo planteo como bloqueo. **Mi lectura es:
extraer solo el composite, conservar el local como dependencia
inyectable**, idéntico al pattern actual.

---

## 1. Alcance exacto a extraer (rangos línea-a-línea)

Todos los rangos refieren a `application/pipeline/media_services.py`
(677 LoC actual tras feature 12).

### Métodos públicos del paso 4 a mover

| Rango              | Símbolo                                              | Acción |
|--------------------|------------------------------------------------------|--------|
| `:382-391`         | `CompositeMediaPublisher.__init__`                   | Mover (transformar firma; `unit_of_work_factory` se descarta; el use case abre su propio UoW). |
| `:393-399`         | `CompositeMediaPublisher.publish_media`              | Mover (entrypoint feliz). |
| `:401-406`         | `CompositeMediaPublisher.publish_video` (alias)      | **Quedarse en el adapter delgado** (compat Protocol). |
| `:408-420`         | `CompositeMediaPublisher.publish_existing_media`     | Mover (entrypoint publish-only retry). Mantiene la duplicación con el use case feature 12 (`EXISTING_MEDIA_REQUIRED`). |
| `:422-423`         | `CompositeMediaPublisher.publish_existing_video` (alias) | **Quedarse en el adapter delgado**. |

### Métodos privados del paso 4 a mover

| Rango        | Símbolo                                                          | Notas |
|--------------|------------------------------------------------------------------|-------|
| `:425-593`   | `_publish_externally` (cuerpo grande, ~169 LoC)                   | Mover. Contiene la decisión `social_publisher is None or not requires_external_publish` + gating REVIEW_WORKFLOW_ENABLED + try/except sobre `social_publisher.publish_property_media` + dispatch a `_persist_workflow_transition`. |
| `:595-659`   | `_persist_workflow_transition`                                   | Mover. **AÑADIR `status='completed'`** al `add_event` cuando `outbox_event_type='publish_completed'` (cumple acceptance literal "outbox_events recibe la fila correcta con `status='completed'` cuando el provider devuelve 2xx"). |
| `:661-663`   | `_build_publish_details(staticmethod)`                           | Mover. Trivial: `return publish_result.to_dict()`. |
| `:666-667`   | `class CompositeMediaPublisher(CompositeMediaPublisher): pass`   | **Borrar** al reescribir la clase como adapter delgado (mismo patrón R5 feature 12). |

### Free funcs / staticmethods compartidas con paso 4

Tras feature 12, los 3 helpers de módulo `_now_iso` (`:67-68`),
`_relative_path_text` (`:71-78`) y `_build_workflow_payload` (`:81-112`)
solo los usa `_persist_workflow_transition` (línea 641, 635-636, 649). Tras
mover el composite **TODOS quedan huérfanos**. **Acción**: duplicarlos en
`publish_reel.py` (~46 LoC) y borrarlos de `media_services.py`. Es la
misma decisión de feature 12 (R1 explore/impl): trade-off de duplicación
intencional para que cada use case sea independiente; feature 14 unifica.

### Imports al tope que pasan al use case nuevo

```python
import logging
import os                       # NO. _persist_workflow_transition no usa os.
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol     # opcional para SocialPublisher Protocol DI
from uuid import uuid4

from application.types import (
    PropertyContext,
    PublishedMediaArtifact,
    RenderedMediaArtifact,
)
from core.errors import (
    SocialPublishingResultError,
    TransientSocialPublishingResultError,
    ValidationError,
    extract_error_details,
)
from core.logging import (
    build_log_context,
    format_console_block,
    format_context_line,
    format_detail_line,
)
from modules.reels.domain import MediaRevision
from settings import REVIEW_WORKFLOW_ENABLED
from shared.db import DatabaseUnitOfWork

# Type-only / DI:
from application.pipeline.interfaces import MediaPublisher  # opcional, para tipar local_publisher
from services.publishing.social_delivery import (
    GoHighLevelPropertyPublisher,  # type hint del social_publisher
    MultiPlatformPublishResult,    # type hint del result
)
```

### Imports legacy NO usados por el use case nuevo (siguen en `media_services.py` o se borran)

- `MediaRevisionRecord` (legacy, `media_services.py:46`) — el use case
  nuevo importa `MediaRevision` moderno. **BORRAR de `media_services.py`**
  tras la extracción (era el único call site post-feature-12).

### Imports en `media_services.py` que QUEDAN huérfanos tras feature 13

Tras feature 13 (composite movido) `media_services.py` se reduce. Análisis
de imports huérfanos a borrar (verificación final con grep):

| Import                                  | Líneas hoy | ¿Quién lo usa post-13?                  | Acción |
|-----------------------------------------|------------|------------------------------------------|--------|
| `REVIEW_WORKFLOW_ENABLED` (`settings`)  | `:19`      | nadie                                    | **BORRAR** |
| `SocialPublishingResultError`           | `:25`      | nadie                                    | **BORRAR** |
| `TransientSocialPublishingResultError`  | `:26`      | nadie                                    | **BORRAR** |
| `extract_error_details`                 | `:28`      | nadie                                    | **BORRAR** |
| `build_log_context`                     | `:31`      | nadie                                    | **BORRAR** |
| `format_console_block`                  | `:32`      | `DefaultMediaRenderer:269`               | CONSERVAR |
| `format_context_line`                   | `:33`      | nadie (solo `_publish_externally`)       | **BORRAR** |
| `format_detail_line`                    | `:34`      | `DefaultMediaRenderer:271-278`           | CONSERVAR |
| `GoHighLevelPropertyPublisher`          | `:60`      | nadie                                    | **BORRAR** |
| `MultiPlatformPublishResult`            | `:61`      | nadie                                    | **BORRAR** |
| `MediaRevisionRecord`                   | `:46`      | nadie                                    | **BORRAR** |
| `datetime, timezone`                    | `:6`       | helper `_now_iso` que también se borra   | **BORRAR** |
| `Callable`, `UnitOfWork`                | `:5, :11`  | adapters legacy de features 10/11/12     | CONSERVAR |
| `uuid4`                                 | `:8`       | `DefaultMediaRenderer:219`               | CONSERVAR |
| `tempfile`                              | `:4`       | `DefaultMediaRenderer:223`               | CONSERVAR |
| `Path`                                  | `:7`       | adapters/renderer                        | CONSERVAR |
| `logging`                               | `:3`       | logger global                            | CONSERVAR |
| `ValidationError`                       | `:27`      | nadie (solo `publish_existing_media` movido) | **BORRAR** |

**Total imports a borrar**: ~12 imports huérfanos. Reducción adicional
de ~12-15 LoC en el import block.

### El "WordPressWebhookApplication.publish" legacy

**No existe** en el repo. Feature 9 (`done`) eliminó la clase entera y su
archivo `services/transport/http/server.py`. Búsqueda exhaustiva
confirmó: solo aparece en docstrings de `apps/api/admin_auth.py:45` (
referencia histórica) y en docs/progreso. La acceptance literal de
feature 13 menciona esa función como contexto histórico, no como código
vivo. **Discrepancia D1**.

---

## 2. Dependencias del servicio (`CompositeMediaPublisher.__init__`)

Lo que recibe hoy en `__init__` (`media_services.py:382-391`):

| Parámetro                                                     | Origen runtime                                            | Equivalente moderno |
|---------------------------------------------------------------|------------------------------------------------------------|---------------------|
| `local_publisher: FileSystemMediaPublisher`                    | construido en bootstrap `:119-123`                         | **CONSERVAR como DI**. El use case lo invoca cuando `requires_render=True` (camino `publish_media`). |
| `unit_of_work_factory: Callable[[], UnitOfWork]` (legacy)     | `build_runtime_unit_of_work_factory` (closure sobre `workspace_path` + `DATABASE_URL`) | **Adaptar**. `del unit_of_work_factory` y el use case abre su `shared.db.DatabaseUnitOfWork(database_locator, base_dir=workspace_dir)` para `_persist_workflow_transition`. |
| `social_publisher: GoHighLevelPropertyPublisher \| None = None` | `build_default_social_property_publisher()` o `None` si `SOCIAL_PUBLISHING_ENABLED=False` o `SOCIAL_PUBLISHING_LOCAL_ONLY=True` | **CONSERVAR como DI**. Type-hint del use case nuevo: `social_publisher: SocialPublisherProtocol \| None`. Hoy es la clase concreta `GoHighLevelPropertyPublisher`. |

**Adicional necesario en el `__init__` del use case** (no estaba en
composite legacy):

- `workspace_dir: str | Path` — base_dir para el UoW moderno (mismo que
  feature 12, ver R2). `_persist_workflow_transition` escribe en
  `update_social_publish_status`/`update_workflow_state` (NO requieren
  base_dir) y `save_revision` (NO requiere base_dir) y
  `outbox.add_event` (NO requiere base_dir). **Atención**: re-leer
  `reel_state_repository.py:233-280` y `:183-230`: ni
  `update_publish_status` ni `update_workflow_state` requieren
  `base_dir` (no hay `RuntimeError` raíseado como en
  `save_local_artifacts`). Por tanto el use case nuevo PODRÍA construir
  el UoW sin `base_dir` — pero por consistencia con feature 12 y
  bootstrap, se pasa de todos modos. Documentado en §6 R2.
- `database_locator: str | Path | None = None` — patrón features 10/11/12.

### Operaciones de DB que ejecuta `_publish_externally` + `_persist_workflow_transition`

Dentro del bloque `with self.unit_of_work_factory() as unit_of_work` de
`_persist_workflow_transition:606`:

1. `unit_of_work.pipeline_state_repository.update_social_publish_status(
   agency_id, wordpress_source_id, site_id, source_property_id, status,
   details, last_published_location_id)` (líneas 608-616) — actualiza
   `reels.publish_status` + `publish_details` + `last_published_provider_external_id`.
   **NOTA**: solo se llama si `publish_status is not None` (gating en
   `:607`).
2. `unit_of_work.pipeline_state_repository.update_workflow_state(
   agency_id, wordpress_source_id, site_id, source_property_id,
   workflow_state, current_revision_id)` (líneas 617-624) — bumpea
   `reels.workflow_state` y `current_revision_id`.
3. `unit_of_work.media_revision_store.save_media_revision(MediaRevisionRecord(...))` (líneas 625-643) —
   inserta la fila append-only. **NOTA**: solo se llama si
   `published_media.revision_id` no es vacío (gating en `:625`).
4. `unit_of_work.outbox_event_store.add_event(event_id, aggregate_type,
   aggregate_id, event_type, payload, agency_id, wordpress_source_id,
   site_id, source_property_id)` (líneas 644-659) — encola el evento.
   **TRAS FEATURE 13: añadir `status='completed'`** cuando
   `event_type='publish_completed'` (acceptance literal); ver §3.

### Operaciones de filesystem

**Ninguna en paso 4.** El composite NO toca disco — solo lee
`published_media.media_path` (escrito por paso 3) y delega al
`social_publisher` que sí toca HTTP+disco para el poster opcional.

### Llamada externa (HTTP)

`self.social_publisher.publish_property_media(context, published_media)`
(línea 518). Eleva `SocialPublishingResultError` /
`TransientSocialPublishingResultError` o devuelve
`MultiPlatformPublishResult | None`. El use case nuevo expone `social_publisher`
como Protocol DI para que tests usen `FakePublisher`.

---

## 3. Mapeo a UoW moderno (`shared/db/uow.py`)

### `update_social_publish_status` → `uow.reels.states.update_publish_status`

Verificado: `reel_state_repository.py:183-231` — firma:

```python
def update_publish_status(
    self,
    *,
    agency_id: str,
    ingestion_source_id: str,
    external_source_id: str,
    source_property_id: int,
    status: str,
    details: Mapping[str, Any] | None = None,
    last_published_provider_external_id: str = "",
) -> None
```

**Renames de columna** (igual que feature 12):
- `wordpress_source_id` → `ingestion_source_id`.
- `site_id` → `external_source_id`.
- `last_published_location_id` → **renombrado a
  `last_published_provider_external_id`** (verificado leyendo el repo).
  El composite legacy pasa `last_published_location_id=context.publish_context.location_id`
  (`:484, :549, :577`); el use case nuevo debe pasar
  `last_published_provider_external_id=context.publish_context.location_id`.

**Decisión**: el use case nuevo normaliza `external_source_id` a
lowercase con `str(context.site_id or "").strip().lower()` (mismo patrón
feature 12, `persist_local_artifacts.py:294`).

### `update_workflow_state` → `uow.reels.states.update_workflow_state`

Verificado: `reel_state_repository.py:233-280` — firma:

```python
def update_workflow_state(
    self,
    *,
    agency_id: str,
    ingestion_source_id: str,
    external_source_id: str,
    source_property_id: int,
    workflow_state: str,
    current_revision_id: str | None = None,
) -> None
```

Renames idénticos. `current_revision_id` puede ser `None` para no tocar.

### `save_media_revision` → `uow.reels.revisions.save_revision(MediaRevision)`

Verificado: `media_revision_repository.py:44-79`. **Idéntico** al feature
12: dataclass `MediaRevision` (`modules.reels.domain.MediaRevision`) con
14 campos (`revision_id`, `agency_id`, `ingestion_source_id`,
`external_source_id`, `source_property_id`, `artifact_kind`,
`render_profile`, `media_path`, `metadata_path`, `mime_type`,
`content_fingerprint`, `publish_target_fingerprint`, `workflow_state`,
`created_at`).

**`workflow_state` distinto al feature 12**: aquí puede ser `'published'`,
`'partial'`, `'awaiting_review'`, `'skipped'`, `'failed'` según el
camino (no solo `'rendered'`). El use case construye
`workflow_state=workflow_state_pasado_al_helper`.

### `outbox.add_event` → `uow.delivery.outbox.add_event`

Verificado: `outbox_repository.py:68-113`. Firma:

```python
def add_event(
    self,
    *,
    event_id: str,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    payload: Mapping[str, Any] | None = None,
    agency_id: str = "",
    ingestion_source_id: str = "",
    external_source_id: str = "",
    source_property_id: int | None = None,
    status: str = "pending",
    created_at: str | None = None,
    available_at: str | None = None,
) -> None
```

**Renames** idénticos a feature 12. `created_at` no-vacío obligatorio (
ver impl_12 §4.1; el repo Postgres rechaza string vacío en columnas
timestamp; pasar `created_at=_now_iso()`).

**Acceptance literal**: "outbox_events recibe la fila correcta con
`status='completed'` cuando el provider devuelve 2xx". Trazabilidad:

| Camino                                                          | `event_type`            | Outbox `status` |
|------------------------------------------------------------------|--------------------------|------------------|
| `social_publisher is None` o `not requires_external_publish`     | `publish_skipped`        | `'pending'` (default — el outbox relay lo procesará) |
| `agency_review_required or REVIEW_WORKFLOW_ENABLED`              | `review_requested`       | `'pending'` |
| Excepción del provider                                           | `publish_failed`         | `'pending'` |
| `publish_result is None`                                         | `publish_skipped`        | `'pending'` |
| `aggregate_status in {"published","partial"}` (provider 2xx)     | `publish_completed`      | **`'completed'`** ← acceptance literal |
| `aggregate_status not in {...}` (provider falla por plataforma)  | `publish_failed`         | `'pending'` |

**Decisión**: el use case pasa `status='completed'` solo en el camino
"publish_completed". Los demás caminos usan el default `'pending'` para
que el outbox relay los recoja y dispatchee.

**Atención**: el composite legacy NO pasa `status` a `add_event`
(`:644-659`). El acceptance pide cambiar la semántica para alinearla con
el dominio del relay. **Documentar en `impl_13_*.md` como cambio
intencional vs el legacy**.

---

## 4. Call sites externos y bridge worker

### Call sites de `CompositeMediaPublisher`

| Archivo                                                | Líneas         | Acción tras feature 13 |
|--------------------------------------------------------|----------------|-------------------------|
| `application/bootstrap/runtime.py`                     | `:8` (import via `default_services`), `:118-126` (instanciación en `build_default_property_media_pipeline`) | **Sin cambios estructurales**: `CompositeMediaPublisher` sigue siendo un adapter delgado en `media_services.py` con la misma firma legacy (acepta `local_publisher`, `unit_of_work_factory`, `social_publisher`). **Cambio mínimo**: pasar `workspace_dir=workspace_path` a `CompositeMediaPublisher(...)` (idéntico al fix R2 feature 12). |
| `application/bootstrap/__init__.py`                    | `:8, :118-126` | Idéntico (siguen byte-iguales). |
| `application/pipeline/default_services.py`             | `:2, :11`      | Solo re-exporta `CompositeMediaPublisher`. **Sin cambios** funcionales. |
| `application/pipeline/__init__.py`                     | dead code 1839 LoC pre-existente | Sin cambios. Ya señalado en reviews features 10/11/12. |
| `application/pipeline/media_services.py`               | `:381-667`     | **Reducir LoC**: clase queda como adapter delgado (~30-40 LoC con docstring + 4 alias). Borrar `_publish_externally`, `_persist_workflow_transition`, `_build_publish_details`, class shadow. |
| `application/pipeline/media_pipeline.py`               | `:73, :103`    | Llama a `media_publisher.publish_existing_media(context)` y `media_publisher.publish_media(context, rendered_media)`. **Sin cambios** — el adapter delgado mantiene la API. |
| `application/pipeline/interfaces.py`                   | `:71-83`       | Protocol `MediaPublisher` intacto. |

### Bridge worker

`apps/worker/runtime.py:262-273` registra `reel_publish` →
`ReelPipeline.handle` → `modules/reels/application/orchestrator.py:25-30`
→ lazy import de `application.bootstrap.runtime.build_default_job_handler`.

**Sin cambios** en feature 13. Sigue intacto, igual que en features
10/11/12. Feature 16 lo sustituye.

### Bootstrap (`build_default_property_media_pipeline`)

Hoy (post-feature-12, `runtime.py:118-126`):

```python
media_publisher=CompositeMediaPublisher(
    local_publisher=FileSystemMediaPublisher(
        unit_of_work_factory=unit_of_work_factory,
        cleanup_temporary_files=PROPERTY_MEDIA_DELETE_TEMPORARY_FILES,
        workspace_dir=workspace_path,
    ),
    unit_of_work_factory=unit_of_work_factory,
    social_publisher=social_property_publisher,
),
```

Tras feature 13: añadir `workspace_dir=workspace_path` a
`CompositeMediaPublisher(...)`:

```python
media_publisher=CompositeMediaPublisher(
    local_publisher=FileSystemMediaPublisher(...),  # sin cambios
    unit_of_work_factory=unit_of_work_factory,
    social_publisher=social_property_publisher,
    workspace_dir=workspace_path,                    # ← nuevo
),
```

Cambio de **+1 LoC** en cada archivo (`runtime.py` y `__init__.py`,
siguen byte-iguales).

---

## 5. Tests existentes

### `grep CompositeMediaPublisher|publish_externally|_persist_workflow_transition|_published_existing` en `tests/`

Resultado: **0 hits no-pyc** (verificado con `grep -rln CompositeMediaPublisher tests/`).
Ningún test ejercita el composite directamente.

Tests "de cerca":

- `tests/test_social_publishing.py` (~1900 LoC) — cubre el provider
  adapter completo: `GoHighLevelPropertyPublisher`,
  `GoHighLevelPublisher`, `GoHighLevelMediaService`,
  `GoHighLevelSocialService`. Múltiples `FakePublisher` con
  `publish_video_to_platforms` (líneas 1511, 1573, 1632, 1667).
  **Reusable como patrón** para los tests del use case nuevo (FakePublisher
  con `publish_property_media` que devuelve un `MultiPlatformPublishResult`
  pre-construido o eleva).
- `tests/integration/test_worker_runtime.py` — registra `reel_publish`
  mock; no ejerce el pipeline real.

### Tests del provider adapter (`tests/test_*ghl*` o similar)

`tests/test_social_publishing.py` ya cubre el adapter; no hay tests
fuera de él para GHL. **No se tocan en feature 13** (out of scope).

### Crear (acceptance feature 13)

#### `tests/unit/reels/test_publish_reel.py`

Tests sugeridos (~8-12 tests, ~500-600 LoC esperado siguiendo el patrón
feature 12):

1. **Camino `publish_completed` con todas las plataformas**: provider
   devuelve `MultiPlatformPublishResult` con `aggregate_status='published'`;
   verifica que las 4 calls UoW ocurren con
   `workflow_state='published'`, `publish_status='published'`,
   `outbox_event_type='publish_completed'`, `outbox_status='completed'`.
2. **Camino `partial`**: provider devuelve `aggregate_status='partial'`;
   verifica `workflow_state='partial'`, `outbox_event_type='publish_completed'`,
   `outbox_status='completed'`.
3. **Camino `publish_skipped` (`social_publisher=None`)**: ausencia de
   provider → no se llama HTTP, escribe `workflow_state='skipped'`,
   `outbox_event_type='publish_skipped'`, `outbox_status='pending'` (no
   `completed`).
4. **Camino `publish_skipped` (`requires_external_publish=False`)**: misma
   asserción del camino 3.
5. **Camino `publish_skipped` (`publish_context=None`)**: misma asserción.
6. **Camino `publish_skipped` (provider devuelve `None`)**:
   verifica que el outbox row tiene `event_type='publish_skipped'`.
7. **Camino `awaiting_review` (`agency_review_required=True`)**:
   `publish_context.approval_required=True` → no llama provider, escribe
   `workflow_state='awaiting_review'`, `outbox_event_type='review_requested'`.
8. **Camino `awaiting_review` (`REVIEW_WORKFLOW_ENABLED=True`, env)**:
   monkeypatch `settings.REVIEW_WORKFLOW_ENABLED` o module-level constante
   en el use case → escribe `workflow_state='awaiting_review'`.
9. **Camino `failed` (provider eleva `SocialPublishingResultError`)**:
   verifica que se escribe `workflow_state='failed'`,
   `outbox_event_type='publish_failed'`, `publish_status='failed'`,
   y se re-eleva la excepción.
10. **Camino `failed` (provider eleva `TransientSocialPublishingResultError`)**:
    idem 9.
11. **`execute_existing` con `existing_published_media=None`**: eleva
    `ValidationError(code="EXISTING_MEDIA_REQUIRED")` (R7 unificación
    documentada).
12. **`execute_existing` con `existing_published_media`**: invoca
    `_publish_externally` con el artifact existente (mismo flujo que el
    feliz pero sin pasar por `local_publisher`).

Stubs UoW: `_StubReelStates` (con `update_publish_status`,
`update_workflow_state`), `_StubMediaRevisions` (con `save_revision`),
`_StubOutbox` (con `add_event`). Patrón inline igual que feature 12 (ver
`tests/unit/reels/test_persist_local_artifacts.py:49-87`). **Decisión**:
mantener stubs inline en el archivo de test (review feature 11 y 12 lo
aceptaron).

`FakePublisher` inline:

```python
class _FakePublisher:
    def __init__(self, *, result: MultiPlatformPublishResult | None = None,
                 raises: Exception | None = None) -> None:
        self.result = result
        self.raises = raises
        self.calls: list[tuple] = []

    def publish_property_media(self, context, published_media):
        self.calls.append((context, published_media))
        if self.raises is not None:
            raise self.raises
        return self.result
```

Stub `_StubLocalPublisher` con `publish_media` y `publish_existing_media`
para las 2 ramas.

#### `tests/integration/reels/test_publish_reel_flow.py`

`temporary_postgres_schema` + `seed_tenant` + **`seed_provider_connection`**
+ `temporary_workspace`. Encadena ingest → prepare → persist → publish:

1. Use case ingest (seed_tenant + execute).
2. Use case prepare (monkeypatch `LocalPhotoSelectionEngine.select_photos`).
3. Use case persist (con `RenderedMediaArtifact` sintético).
4. **Use case publish_reel** con un `_FakePublisher` que devuelve
   `MultiPlatformPublishResult(aggregate_status='published')` y
   `seed_provider_connection(...)` para tener una fila válida en
   `provider_connections`.

Asserts SQL directo (`text(...)` con `create_engine`):
- `reels.workflow_state='published'`, `publish_status='published'`,
  `last_published_provider_external_id` no vacío.
- `media_revisions` row con `workflow_state='published'`.
- `outbox_events` row con `event_type='publish_completed'`,
  **`status='completed'`** ← acceptance literal.
- payload JSON contiene `workflow_state='published'`,
  `successful_platforms`, `aggregate_status='published'`.

**Atención sobre `seed_provider_connection`**: actualmente el use case
NO consulta `provider_connections` (el `social_publisher` se inyecta con
sus credenciales pre-resueltas via `context.publish_context.access_token`).
La fila de `provider_connections` la usan otros use cases (
`attach_provider_connection`, `decode_session_context`). **¿Por qué la
acceptance pide `seed_provider_connection`?**

Hipótesis (re-leyendo acceptance literal):
> tests/integration/reels/test_publish_reel_flow.py con seed_provider_connection

La integración pide tener una fila válida de `provider_connections` en
la BD para validar que **el flujo end-to-end pasa por la consulta de
credenciales** o bien para validar que la `agency_id` tiene un provider
connection asociado. Hoy el composite NO consulta esa tabla — el
`SocialPublishContext` viene pre-resuelto desde el upstream
(probablemente del `IngestPropertyIntoReelUseCase` o del job payload).

**Recomendación**: el integration test usa `seed_provider_connection`
porque:
- (a) construye el `SocialPublishContext` leyendo
  `provider_connections.secrets_encrypted` via
  `uow.publishing.connections.get_with_secrets(...)` (decryption con
  Fernet), y/o
- (b) deja la fila para que algún paso futuro (feature 16, worker real)
  la consulte.

**Decisión**: el use case `PublishReelUseCase` NO consulta
`provider_connections` en feature 13 (out of scope), pero el integration
test SÍ siembra la fila para satisfacer el acceptance literal y para
preparar el terreno de feature 16. Documentado en §6 R5.

#### Adaptar / migrar

- **`tests/unit/reels/_uow_stubs.py`** ya tiene `StubReelStates` con
  `update_publish_status` y `update_workflow_state` (`:31-45`). **Falta
  `update_workflow_state` para feature 13 — verificar**: sí está
  (`:40`). **Falta**: el stub no tiene `save_local_artifacts` ni
  `save_revision` ni `add_event`. Decisión idéntica a feature 12: stubs
  inline en el archivo de test.

- **No se tocan** los tests existentes de features 10/11/12 ni los del
  provider (`tests/test_social_publishing.py`).

---

## 6. Riesgos / acoplamientos

### R1 — `WordPressWebhookApplication.publish` legacy

Documentado en §0 / §1 / §8. **No existe**. La acceptance literal
("Sustituye la lógica de WordPressWebhookApplication.publish") es
inerte. Sin acción.

### R2 — Bootstrap pasa `workspace_dir` a `CompositeMediaPublisher(...)`

Idéntico al fix de feature 12. Hoy `CompositeMediaPublisher.__init__`
no recibe `workspace_dir` — lo derivaba del `unit_of_work_factory`
(closure). El use case nuevo lo necesita para construir el UoW moderno.

**Cambio**: `+1 LoC` en `application/bootstrap/runtime.py:122-126` y en
`application/bootstrap/__init__.py:122-126`. Los dos archivos siguen
byte-iguales entre sí. Es necesario y mínimo.

**Atención**: `update_publish_status`/`update_workflow_state` NO requieren
`base_dir` en el repo (verificado: no hay `RuntimeError`). Por
consistencia con feature 12 y simetría del UoW, se pasa de todos modos.

### R3 — Doble validación `EXISTING_MEDIA_REQUIRED` (R7 explore feature 12)

**Acción de unificación recomendada**:

Hoy hay 2 implementaciones idénticas:
- `PersistLocalArtifactsUseCase.execute_existing` (use case feature 12,
  `persist_local_artifacts.py:208-234`).
- `CompositeMediaPublisher.publish_existing_media` (legacy,
  `media_services.py:408-420`).

Cuando el composite se mueva al use case nuevo (feature 13), la
duplicación se puede eliminar haciendo que `PublishReelUseCase.execute_existing`:

- (Opción A) llame `local_publisher.publish_existing_media(context)`
  (que internamente llama al feature 12 use case que ya valida y
  retorna). Luego pasa el resultado a `_publish_externally`.
- (Opción B) duplica el check inline (igual que el legacy hoy).

**Recomendación**: **Opción A**. Mantiene single-source-of-truth de la
validación en `PersistLocalArtifactsUseCase.execute_existing`. El use
case feature 13 solo orquesta. Documentado.

### R4 — Class shadow `CompositeMediaPublisher:666-667`

Mismo patrón R5 feature 12. Se elimina al reescribir la clase como
adapter delgado. `DefaultMediaRenderer:329-330` queda vivo hasta feature
14.

### R5 — `seed_provider_connection` aceptado por la acceptance pero no consultado por el use case

Documentado en §5. El use case NO consulta `provider_connections` en
feature 13 (el `SocialPublishContext` viene pre-resuelto upstream); la
fila se siembra en el integration test por:
- alineación literal con la acceptance,
- preparación de feature 16 (worker real consultará credentials),
- defensa en profundidad (la BD post-test refleja un estado realista).

Si el leader prefiere que el use case TAMBIÉN lea
`provider_connections` (vía `uow.publishing.connections.get_with_secrets(
agency_id, provider="gohighlevel")`) y construya el `SocialPublishContext`
él mismo, eso es un refactor adicional que cae fuera del alcance
estrecho de feature 13 (paso 4 del pipeline). **Mi lectura**: solo
seed en el integration test, sin lookup en el use case.

### R6 — Cifrado de tokens (Fernet)

`shared/db/security.py` (verificado, líneas 19-32) expone `encrypt_text`
/ `decrypt_text`. `seed_provider_connection` ya cifra en `tests/support/postgres.py:262`.
**Si R5 Opción A — el use case consulta `provider_connections`**, el
decryption es transparente: `ProviderConnectionRepository.get_with_secrets`
lo hace inline (`provider_connection_repository.py:65-73`). **Ningún
cambio adicional**.

### R7 — `_persist_workflow_transition` escribe en hasta 4 tablas en una transacción

Tablas afectadas:
- `reels` (vía `update_social_publish_status` y `update_workflow_state`).
- `media_revisions` (vía `save_revision`, condicional).
- `outbox_events` (vía `add_event`).

**Atomicidad crítica**. `DatabaseUnitOfWork` commits en `__exit__` si no
hay excepción; rollback si la hay. El use case nuevo abre el UoW dentro
de `_publish_with_uow(...)` (mismo patrón `_persist_with_uow` feature
12) **DESPUÉS** de que el provider HTTP devuelva éxito o falle. La
secuencia es:

1. (opcional) `local_publisher.publish_media(context, rendered_media)`
   abre/cierra su propio UoW (paso 3).
2. Llamada HTTP al provider (sin UoW).
3. `_publish_with_uow` abre UoW nuevo, hace los 3-4 inserts, commitea.

→ **Doble UoW** documentado como R4 en feature 10. Feature 14 lo
elimina; mientras tanto, dos commits separados son tolerables.

### R8 — `MediaRevisionRecord` legacy se borra completamente

Tras feature 13, `MediaRevisionRecord` (legacy
`repositories/stores/media_revision_store.py`) NO tiene call sites en
`media_services.py` (era el último). Otros call sites verificar:
`grep MediaRevisionRecord` en `apps/`, `modules/`, `shared/`, `tests/`:

```
grep -rln "MediaRevisionRecord" apps modules shared tests
```

Si **0 hits no-pyc**, el dataclass legacy queda dead code. **Decisión**:
NO se borra el archivo legacy en feature 13 (out of scope; queda para
feature 17 o feature 18 al barrer `repositories/`). Solo se borra el
import en `media_services.py`.

### R9 — Helpers `_now_iso`, `_relative_path_text`, `_build_workflow_payload`
en `media_services.py`

Documentado en §1. Tras feature 13 quedan huérfanos en
`media_services.py`. **Acción**: borrarlos junto con la extracción del
composite. Reduce ~46 LoC adicionales. Duplicar en `publish_reel.py`.

### R10 — Tras feature 13, `media_services.py` queda muy reducido

Estimación post-feature-13:
- Hoy 677 LoC.
- Movido al use case: lineas 382-667 = ~286 LoC.
- Adapter delgado introducido: ~35 LoC.
- Helpers movidos (`_now_iso`, `_relative_path_text`,
  `_build_workflow_payload`): ~46 LoC borradas.
- Imports limpiados: ~12-15 LoC.
- Reducción neta: ~309 LoC.
- Resultado: **`media_services.py` post-feature-13: ~340-370 LoC**.

Solo queda `DefaultPropertyInfoService` (32 LoC),
`DefaultMediaPreparationService` (45 LoC), `DefaultMediaRenderer` (130
LoC con su class shadow), `FileSystemMediaPublisher` (45 LoC), y el nuevo
adapter `CompositeMediaPublisher` (35 LoC). **Feature 14 elimina todo el
archivo** y mueve `DefaultMediaRenderer` a `modules/rendering/application/`.

### R11 — Outbox `status='completed'` en el camino feliz

Documentado en §3. **Cambio semántico vs legacy**: el composite legacy
no pasa `status` (default `'pending'`). El use case nuevo pasa
`status='completed'` cuando `event_type='publish_completed'`. Esto
significa que el outbox relay **NO procesará** ese evento (porque
filtra por `status='pending'`). El consumidor del outbox debe manejar
ambos estados.

**Verificar**: `modules/delivery/infrastructure/outbox_repository.py`
**no** filtra por status en `list_events` (`:125-156` lo lista todo).
El relay (no leído en esta exploración) sí debería filtrar. Si el relay
asume `pending`, marcar `completed` directo aquí significa el evento
queda pre-marcado como entregado, lo que **simplifica** el flujo:
"reel published, sin necesidad de relay outbound" porque la
publicación ya ocurrió en este transacción. Esa es la semántica
inferible del acceptance.

**Documentar como cambio intencional** en `impl_13_*.md`. Si feature 16
(worker real) descubre que el relay rompe, ajustar entonces.

### R12 — `last_published_location_id` rename

Documentado en §3. La API legacy usa `last_published_location_id`
(`media_services.py:484, :549, :577, :615`); la moderna lo renombra a
`last_published_provider_external_id`. El use case nuevo debe usar el
nombre moderno.

### R13 — Re-eleva la excepción en el camino `failed`

`_publish_externally:551` re-raisea con `raise` desnudo después de
persistir el `failed`. **Conservar el comportamiento** en el use case
nuevo. El bridge worker (`apps/worker/`) debe ver la excepción para
poder retry o marcar el job como failed.

---

## 7. Plan de implementación recomendado

### Archivos a crear

1. **`modules/reels/application/use_cases/publish_reel.py`**
   (~400-480 LoC estimado). Estructura sugerida:

   ```python
   """Publish a rendered reel to social platforms (step 4 of the pipeline).

   This use case takes a rendered + locally-persisted reel artifact and
   delivers it to the configured social provider (today: GoHighLevel).
   It owns the publish-side workflow transition: bumps `reels` to
   `workflow_state='published'/'partial'/'awaiting_review'/'skipped'/'failed'`,
   appends a `media_revisions` row mirroring the new state, and emits an
   outbox event whose `event_type` ('publish_completed' / 'publish_skipped'
   / 'publish_failed' / 'review_requested') reflects the final decision.

   Replaces the body of `CompositeMediaPublisher` from
   `application/pipeline/media_services.py`. The legacy class survives as a
   thin adapter for bootstrap compat (deleted by feature 14).

   Helpers `_now_iso`, `_relative_path_text`, `_build_workflow_payload`
   are duplicated here from features 11/12 — same trade-off documented
   there. Feature 14 unifies.
   """

   # imports...

   def _now_iso(): ...
   def _relative_path_text(...): ...
   def _build_workflow_payload(...): ...

   class PublishReelUseCase:
       def __init__(self, *, workspace_dir, local_publisher,
                    social_publisher=None, database_locator=None): ...

       def execute(self, context, rendered_media, *, uow=None) -> PublishedMediaArtifact:
           # 1) delegate to local publisher (paso 3).
           # 2) call _publish_externally(context, published_media, uow=uow).

       def execute_existing(self, context, *, uow=None) -> PublishedMediaArtifact:
           # 1) delegate to local_publisher.publish_existing_media (R3 Opción A).
           # 2) call _publish_externally(context, published_media, uow=uow).

       def _publish_externally(self, context, published_media, *, uow): ...

       @staticmethod
       def _publish_with_uow(*, context, published_media, workflow_state,
                              outbox_event_type, publish_status=None,
                              details=None, last_published_location_id="",
                              outbox_status="pending", uow): ...

       @staticmethod
       def _build_publish_details(publish_result): ...
   ```

2. **`tests/unit/reels/test_publish_reel.py`** (~500-600 LoC estimado): 12
   tests listados en §5. Stubs UoW + `_FakePublisher` inline (no DB).

3. **`tests/integration/reels/test_publish_reel_flow.py`** (~250-320 LoC
   estimado): 1 test feliz encadenando ingest → prepare → persist →
   publish con `seed_provider_connection`. Provider stub que devuelve
   `MultiPlatformPublishResult(aggregate_status='published')`. SQL
   directo.

### Archivos a modificar

1. **`application/pipeline/media_services.py`** (677 LoC actual):
   - **Borrar** `:381-667` (composite + class shadow + helpers privados =
     ~286 LoC).
   - **Borrar** helpers `:67-112` (`_now_iso`, `_relative_path_text`,
     `_build_workflow_payload` = ~46 LoC).
   - **Insertar** adapter delgado `CompositeMediaPublisher` (~35 LoC con
     docstring + 4 alias).
   - **Limpiar imports huérfanos** (~12-15 LoC):
     `REVIEW_WORKFLOW_ENABLED`, `SocialPublishingResultError`,
     `TransientSocialPublishingResultError`, `extract_error_details`,
     `build_log_context`, `format_context_line`,
     `GoHighLevelPropertyPublisher`, `MultiPlatformPublishResult`,
     `MediaRevisionRecord`, `datetime, timezone`, `ValidationError`.
   - **Añadir import** de `PublishReelUseCase`.
   - Resultado esperado: **~340-370 LoC** post-feature-13.

2. **`application/bootstrap/runtime.py`** y
   **`application/bootstrap/__init__.py`** (byte-iguales):
   - Pasar `workspace_dir=workspace_path` a `CompositeMediaPublisher(...)`
     en `build_default_property_media_pipeline:118-126`.
   - **+1 LoC en cada uno**.

3. **`modules/reels/application/use_cases/__init__.py`**:
   - Añadir re-export de `PublishReelUseCase`.

4. **`tests/unit/reels/_uow_stubs.py`** (opcional):
   - Decisión: stubs inline en el test file (mismo patrón feature 12).

### Archivos a borrar

Ninguno físicamente. (Class shadow `CompositeMediaPublisher` se elimina
dentro de `media_services.py` al reescribir.)

### Archivos NO modificados

- `application/pipeline/media_pipeline.py` — orquestador intacto.
- `application/pipeline/interfaces.py` — Protocol `MediaPublisher` intacto.
- `application/pipeline/default_services.py` — solo re-exporta, sin
  cambios.
- `apps/worker/runtime.py` — bridge intacto (feature 16).
- `services/publishing/social_delivery/property_publisher.py` y
  resto del provider adapter — intactos.
- `modules/publishing/infrastructure/adapters/gohighlevel/` — intacto.
- `tests/test_social_publishing.py` — intacto.

### Orden sugerido

1. Implementer crea `modules/reels/application/use_cases/publish_reel.py`
   con `PublishReelUseCase` (helpers duplicados + `execute` +
   `execute_existing` + `_publish_externally` + `_publish_with_uow` +
   `_build_publish_details`).
2. Re-export en `modules/reels/application/use_cases/__init__.py`.
3. Crea `tests/unit/reels/test_publish_reel.py` y los hace pasar
   (`pytest -q tests/unit/reels/test_publish_reel.py`).
4. Crea `tests/integration/reels/test_publish_reel_flow.py` y lo hace
   pasar.
5. Modifica `application/pipeline/media_services.py`: borra cuerpo viejo
   del composite + helpers de módulo + class shadow, inserta adapter
   delgado, limpia imports.
6. Modifica `application/bootstrap/runtime.py` y `__init__.py`: pasa
   `workspace_dir=workspace_path` a `CompositeMediaPublisher(...)`.
7. Verifica que los 396 tests previos siguen verdes (features 10/11/12
   intactos).
8. Corre suite completa (`./init.sh`). Baseline post-feature-12: **396
   verdes**. Esperado: ≥ **408 verdes** (396 + 12 unit + 1 integration).

### LoC esperado de `media_services.py` post-feature-13

| Componente                                                | LoC actual | LoC tras feature 13 |
|------------------------------------------------------------|------------|----------------------|
| Imports                                                    | ~63        | ~50 (–13)            |
| Helpers `_now_iso/_relative_path_text/_build_workflow_payload` | ~46        | 0 (–46)              |
| `DefaultPropertyInfoService`                               | ~32        | ~32                  |
| `DefaultMediaPreparationService`                           | ~45        | ~45                  |
| `DefaultMediaRenderer` + class shadow                      | ~135       | ~135                 |
| `FileSystemMediaPublisher`                                 | ~46        | ~46                  |
| `CompositeMediaPublisher` + class shadow                   | ~290       | ~35 (–255)            |
| `__all__`                                                  | ~8         | ~8                   |
| **Total**                                                  | **677**    | **~351**             |

Reducción neta esperada: **~326 LoC** (~48%). Bajará a ~340-370 según
el detalle final del adapter y limpieza de imports. Coherente con la
trayectoria features 10/11/12 (10: 1075→956; 11: 956→807; 12: 807→677;
**13: 677→~340-370**).

---

## 8. Discrepancias detectadas

### D1 — `WordPressWebhookApplication.publish` no existe

Documentado en §0/§1/§6 R1. El acceptance literal lo menciona como
contexto histórico; feature 9 (`done`) lo eliminó entero. Sin acción.

### D2 — `seed_provider_connection` aceptance vs use case que no consulta `provider_connections`

Documentado en §5 / §6 R5. El integration test siembra la fila por
alineación con el acceptance literal y preparación de feature 16, pero
el use case NO la consulta hoy. **Plantear al leader**: ¿se quiere
también que `PublishReelUseCase` lea `provider_connections.secrets`
para construir el `SocialPublishContext` en este feature? Mi lectura es
que no — out of scope feature 13.

### D3 — `application/bootstrap/{runtime.py,__init__.py}` cambian +1 LoC más

Documentado en §6 R2. La byte-igualdad entre los dos archivos se
mantiene; la byte-igualdad con el código pre-feature-12 (que ya estaba
rota) se rompe en otra línea. Mismo patrón de feature 12.

### D4 — Naming del entrypoint del use case

`feature_list.json` #13 no especifica el nombre del método público. El
patrón Phase 2 establece `execute(...)` y `execute_existing(...)`. El
adapter `CompositeMediaPublisher` mantiene `publish_media` /
`publish_existing_media` / aliases para no romper Protocol
`MediaPublisher` ni callers desconocidos.

### D5 — Outbox `status='completed'` cambio semántico vs legacy

Documentado en §3 / §6 R11. Cambio intencional: el composite legacy
nunca pasaba `status` (default `'pending'`); el use case nuevo lo pasa
`'completed'` SOLO en el camino `publish_completed`. Acceptance literal
("recibe la fila correcta con `status=completed` cuando el provider
devuelve 2xx") lo justifica.

### D6 — `last_published_location_id` rename a `last_published_provider_external_id`

Documentado en §3 / §6 R12. El repo moderno renombra el kw-arg.

### D7 — Doble validación `EXISTING_MEDIA_REQUIRED` (R7 explore feature 12)

Documentado en §6 R3. **Feature 13 unifica via Opción A**:
`PublishReelUseCase.execute_existing` delega a
`local_publisher.publish_existing_media(context)` que ya valida y
retorna. Single source of truth en el use case feature 12.

### D8 — Class shadow `DefaultMediaRenderer:329-330` sigue vivo

Out of scope feature 13. Lo limpia feature 14 al mover el renderer.

### D9 — `application/pipeline/__init__.py` (1839 LoC) sigue siendo dead code

Pre-existente. Documentado en reviews features 10/11/12. Feature 13 no
lo empeora ni lo arregla. Queda para feature 14 o 18.

### D10 — `social_publisher` Protocol vs clase concreta

El use case nuevo TYPE-HINTea `social_publisher` como
`GoHighLevelPropertyPublisher | None` (igual que el composite legacy)
**O** define un `Protocol SocialPublisher` interno con
`publish_property_media(context, published_media) -> MultiPlatformPublishResult | None`.

Decisión: **usar duck-typing** (sin Protocol explícito), igual que el
legacy y que `tests/test_social_publishing.py` (que usa
`FakePublisher` sin Protocol). Mantiene Phase 2 simple. Si feature 16
necesita más rigor, refactoriza entonces.

---

**Fin del informe.**
