# Explore — Feature 10 `reels_use_case_ingest_property_into_reel`

> Mapa de extracción del paso 1 del pipeline (ingest) desde
> `application/pipeline/media_services.py` (1839 LoC, legacy) hacia
> `modules/reels/application/use_cases/ingest_property_into_reel.py`
> con clase `IngestPropertyIntoReelUseCase`.

Contexto leído: `.claude/agents/leader.md`, `docs/phase_2_operating_rules.md`,
`docs/architecture.md`, `docs/conventions.md`, `feature_list.json` (entry #10),
`progress/current.md`.

---

## 1. Alcance exacto a extraer (rangos línea-a-línea)

### Método público entrypoint

- **`DefaultPropertyInfoService.ingest_property`** —
  `application/pipeline/media_services.py:360-518`.
  - Firma actual:
    ```
    def ingest_property(self, job: PropertyMediaJob) -> PropertyContext
    ```
  - Llamado desde `PropertyMediaPipeline.run_job` en
    `application/pipeline/media_pipeline.py:44`.

### Constructor del servicio (incluye dependencias)

- **`DefaultPropertyInfoService.__init__`** — `media_services.py:342-358`.
  Lo absorbe el constructor del nuevo use case; ver §2.

### Helpers privados que SOLO usa el step ingest (mover al use case)

| Rango                               | Símbolo                                          | Uso |
|-------------------------------------|---------------------------------------------------|-----|
| `media_services.py:602-674`         | `_build_ingested_pipeline_state` (staticmethod)   | Único caller: `ingest_property` (`:453`). Mover. |
| `media_services.py:676-689`         | `_build_content_snapshot` (staticmethod)          | Único caller: `ingest_property` (`:377`). Mover. |
| `media_services.py:691-724`         | `_build_publish_target_snapshot` (staticmethod)   | Único caller: `ingest_property` (`:383`). Mover. |
| `media_services.py:726-767`         | `_build_publish_targets` (staticmethod)           | Único caller: `_resolve_publish_inputs` (`:574`). Mover. |
| `media_services.py:769-874`         | `_determine_pending_publish_platforms` (staticmethod) | Único caller: `ingest_property` (`:429`). Mover. |
| `media_services.py:520-600`         | `_resolve_publish_inputs` (instance)              | Único caller: `ingest_property` (`:372`). Mover. |
| `media_services.py:961-977`         | `_should_reset_publish_history` (staticmethod)    | Único caller: `ingest_property` (`:448`). Mover. |
| `media_services.py:937-959`         | `_build_existing_published_media` (staticmethod)  | Único caller: `ingest_property` (`:442`). Mover. |
| `media_services.py:896-935`         | `_has_local_artifacts` (staticmethod)             | Único caller: `ingest_property` (`:410`). Mover. |
| `media_services.py:876-894`         | `_should_prepare_assets` (staticmethod)           | Único caller: `ingest_property` (`:422`). **Acoplado a `DefaultMediaPreparationService.resolve_selected_dir` y `.resolve_primary_image_from_dir`** (ver §6). Mover el método pero conservar el import al servicio legacy hasta feature 11. |

### Helpers de módulo (free functions) que SOLO usa ingest (mover)

| Rango                          | Símbolo                                  | Otros callers? |
|--------------------------------|-------------------------------------------|----------------|
| `media_services.py:76-101`     | `_default_pipeline_state`                 | Solo `ingest_property` (`:407`). Mover. |
| `media_services.py:104-107`    | `_json_hash`                              | Solo helpers ingest (`:382, :392`). Mover. |
| `media_services.py:110-111`    | `_json_text`                              | Solo helpers ingest (`:381, :391`). Mover. |
| `media_services.py:114-121`    | `_parse_json_object`                      | Usado por `_parse_publish_target_snapshot` y `_extract_successful_platforms`. Mover. |
| `media_services.py:178-195`    | `_normalise_platforms`                    | Usado por `_parse_publish_target_snapshot`. Mover. |
| `media_services.py:198-265`    | `_parse_publish_target_snapshot`          | Usado por `ingest_property` (`:408`) y `_determine_pending_publish_platforms` (`:787`). Mover. |
| `media_services.py:268-282`    | `_extract_platform_results`               | Usado por `_extract_successful_platforms`. Mover. |
| `media_services.py:285-291`    | `_is_successful_platform_result`          | Usado por `_extract_successful_platforms`. Mover. |
| `media_services.py:294-313`    | `_extract_successful_platforms`           | Usado por `_determine_pending_publish_platforms`. Mover. |
| `media_services.py:73`         | `_SUCCESSFUL_SOCIAL_STATUSES`             | Usado por `_is_successful_platform_result`. Mover. |
| `media_services.py:124-127`    | `_resolve_absolute_path`                  | Usado por `_has_local_artifacts` y `_build_existing_published_media`. Mover. |

### Helpers compartidos con otros pasos (NO se mueven en feature 10)

Quedan en `media_services.py` para ser tocados por features 11/12/14:

- `media_services.py:130-131` `_now_iso` — usado por `FileSystemMediaPublisher`
  (paso publish). **Conservar.**
- `media_services.py:134-141` `_relative_path_text` — usado por
  `FileSystemMediaPublisher` (paso publish). **Conservar.**
- `media_services.py:144-175` `_build_workflow_payload` — usado por
  `FileSystemMediaPublisher` (paso publish). **Conservar.**
- `media_services.py:316-339` `LocalPhotoSelectionEngine` — paso
  prepare_assets (feature 11). **Conservar.**
- `media_services.py:980-1217` `DefaultMediaPreparationService` — paso
  prepare_assets (feature 11). **Conservar.** (Sus dos staticmethods
  `resolve_selected_dir` y `resolve_primary_image_from_dir` los necesita el
  helper `_should_prepare_assets` extraído; el use case los importa de
  `media_services.py` hasta feature 11.)
- `media_services.py:1220-1359` `DefaultPhotoSelectionService`,
  `DefaultMediaRenderer` — features 11/12. **Conservar.**
- `media_services.py:1361-1839` `FileSystemMediaPublisher`,
  `CompositeMediaPublisher` — feature 13. **Conservar.**

### Imports al tope de `media_services.py` que pasan al use case nuevo

Necesarios en `modules/reels/application/use_cases/ingest_property_into_reel.py`:

```
hashlib, json, logging                                       (stdlib)
from datetime import datetime, timezone                      (no lo necesita el use case nuevo si reusa shared helpers)
from pathlib import Path
```

De módulos `domain`/`shared`/otros:

- `from application.pipeline.content_generation import ContentGenerator,
  DeterministicPropertyContentGenerator` → mantener path absoluto al
  legacy (Phase 2 todavía no movió `content_generation`).
- `from domain.media.planning import build_media_delivery_plan` →
  legacy domain, sigue ahí.
- `from domain.properties.model import Property` → legacy domain, sigue ahí.
- `from application.types import (PlatformPublishTargetPlan,
  PropertyContext, PropertyMediaJob, SocialPublishContext)` → legacy
  types, sigue ahí.
- `from services.publishing.social_delivery import build_property_public_url`
  (solo el helper; **no** los publishers, esos son del step publish).
- `from modules.publishing.infrastructure.adapters.platforms import
  get_platform_config` → ya en módulo moderno.
- `from services.publishing.social_delivery.platform_policy import
  normalize_platform_name`.
- `from services.media.site_storage import resolve_site_storage_layout`.
- `from settings import REVIEW_WORKFLOW_ENABLED` (no usado realmente; descartar).
- `from core.logging import build_log_context, format_console_block,
  format_context_line, format_detail_line` → solo `format_console_block`
  y `format_detail_line` para los `logger.info` que migran. (El resto los
  usan los pasos posteriores y se quedan en `media_services.py`.)

Imports que SOLO el ingest necesita y dejarán de ser referenciados en
`media_services.py` tras la extracción (no se borran del archivo legacy
porque otros pasos siguen vivos, pero verificar):

- `from repositories.stores.pipeline_state_store import PropertyPipelineState`
  → lo siguen usando los pasos prepare/render/publish (vía `state` que
  carga `_load_existing_assets`). **Conservar el import.**

---

## 2. Dependencias actuales de `DefaultPropertyInfoService`

Lo que recibe hoy en `__init__` (`media_services.py:342-358`):

| Parámetro                              | Origen runtime                                | Equivalente moderno |
|----------------------------------------|------------------------------------------------|---------------------|
| `workspace_dir`                        | `WORKSPACE_DIR` en bootstrap                   | Igual; lo recibe el use case en `__init__`. |
| `unit_of_work_factory: Callable[[], UnitOfWork]` (legacy `application.persistence.UnitOfWork`) | `build_runtime_unit_of_work_factory(workspace_dir, database_locator=...)` que construye `repositories/postgres/uow.DatabaseUnitOfWork` | **Adaptar.** El use case nuevo recibe directamente un `shared.db.DatabaseUnitOfWork` (UoW moderno) por parámetro al `execute(...)`, **no** un factory. Patrón consistente con `RegenerateReelUseCase`. La construcción del UoW pasa al `__init__` del use case si necesita abrirlo (ver §3 — preferimos el patrón "use case recibe `uow` por parámetro" del `regenerate_reel`, pero el ingest se invoca desde el bridge worker que hoy gestiona el UoW legacy → habrá que ajustar el adapter, ver §4). |
| `property_url_template: str`           | `SOCIAL_PUBLISHING_PROPERTY_URL_TEMPLATE`      | Igual; lo recibe el use case en `__init__`. |
| `property_url_tracking_params: dict`   | `SOCIAL_PUBLISHING_PROPERTY_URL_TRACKING_PARAMS`| Igual. |
| `social_publishing_enabled: bool`      | `SOCIAL_PUBLISHING_ENABLED and not SOCIAL_PUBLISHING_LOCAL_ONLY` | Igual. |
| `content_generator: ContentGenerator`  | `DeterministicPropertyContentGenerator()`       | Igual; sigue importándose del legacy `application/pipeline/content_generation`. |

Operaciones de DB que el método ejecuta hoy (todas dentro del bloque
`with self.unit_of_work_factory() as unit_of_work` `media_services.py:394-468`):

1. `unit_of_work.property_repository.save_property_data(property_item, agency_id, wordpress_source_id, site_id)` (`:395`).
2. `unit_of_work.pipeline_state_repository.get_property_pipeline_state(site_id, source_property_id)` (`:401`).
3. `unit_of_work.pipeline_state_repository.save_property_pipeline_state(next_state)` (`:468`), solo cuando `not is_noop`.

Ningún `media_revision` se guarda aquí — eso ocurre en el paso publish
(`media_services.py:1405, :1784`). Ver "Discrepancias detectadas".

---

## 3. Mapeo a UoW moderno (`shared/db/uow.py`)

Repos modernos disponibles para el use case nuevo (todos via
`uow.<bc>.<repo>` siguiendo el patrón de `regenerate_reel`):

| Operación legacy                                                                  | Reemplazo moderno (firma exacta) |
|------------------------------------------------------------------------------------|----------------------------------|
| `unit_of_work.property_repository.save_property_data(property_item, agency_id=..., wordpress_source_id=..., site_id=...)` | **No existe** un `save_property_data` 1:1 en `modules/catalog/infrastructure/property_repository.PropertyRepository`. El moderno expone `upsert_property(record: dict[str, Any]) -> int` (`property_repository.py:118-153`) y `replace_images(record_id, downloaded_images)` (`PropertyImageRepository.replace_images`, `:190-222`). El use case debe convertir `Property` → `record dict` con las columnas canónicas (`agency_id`, `ingestion_source_id`, `external_source_id`, `source_property_id`, `slug`, `title`, `link`, `featured_image_url`, etc., `raw_json`, `fetched_at`, `modified_gmt`) y llamar `uow.catalog.properties.upsert_property(record)`. La construcción del dict puede tomarse del legacy `repositories/stores/property_store.py:_save_property_record` (no migra a feature 10 — el implementer la convierte en helper privado del nuevo use case o del repo moderno). **Riesgo medio**: ese mapeo es prosaico pero largo. Ver §6. |
| `unit_of_work.pipeline_state_repository.get_property_pipeline_state(site_id=..., source_property_id=...) -> PropertyPipelineState \| None` | `uow.reels.states.get(external_source_id=site_id, source_property_id=...) -> ReelState \| None` (`reel_state_repository.py:100-114`). **Cambio de tipo:** `ReelState` (dataclass moderno) tiene `content_snapshot` y `publish_target_snapshot` como `Mapping[str, Any]` (JSONB), no como `*_json: str`. El use case debe operar con dicts, no con strings JSON. |
| `unit_of_work.pipeline_state_repository.save_property_pipeline_state(state)` | `uow.reels.states.save(state: ReelState) -> None` (`reel_state_repository.py:116-181`). |
| (no usado en ingest) Lookup `IngestionSource` para resolver `ingestion_source_id` a partir del `site_id` que llega en el job | `uow.ingestion.sources.get_by_kind_external_id(kind="wordpress", external_id=site_id) -> IngestionSource \| None` (`ingestion_source_repository.py:79-92`). En el flujo actual el `wordpress_source_id` ya viene en `job.tenant.wordpress_source_id` (que el bridge worker llena desde `job.ingestion_source_id`); el use case puede usarlo directamente sin re-resolverlo, pero **debe persistirlo en `reels.ingestion_source_id`** (la columna ahora es `ingestion_source_id`, no `wordpress_source_id`). |
| (no usado en ingest hoy; ver Discrepancia D1) Persistir `MediaRevision` "inicial" | `uow.reels.revisions.save_revision(record: MediaRevision)` (`media_revision_repository.py:43-79`). **No se invoca en feature 10** — feature_list dice "persistir media revision inicial" pero la implementación legacy no lo hace; ver §6. |
| Lookup de `Agency` (no usado por ingest hoy) | `uow.tenancy.agencies.get_by_id(agency_id)` — innecesario aquí. |

### Diferencias de modelo (`PropertyPipelineState` legacy → `ReelState` moderno)

| Legacy `PropertyPipelineState`                     | Moderno `ReelState`                              |
|----------------------------------------------------|---------------------------------------------------|
| `wordpress_source_id`                              | `ingestion_source_id`                            |
| `site_id`                                          | `external_source_id`                             |
| `content_snapshot_json: str`                       | `content_snapshot: Mapping[str, Any]`            |
| `publish_target_snapshot_json: str`                | `publish_target_snapshot: Mapping[str, Any]`     |
| `publish_details_json: str`                        | `publish_details: Mapping[str, Any]`             |
| `last_published_location_id: str`                  | `last_published_provider_external_id: str`      |
| `current_revision_id`, `selected_image_folder`, `artifact_kind`, `local_artifact_path`, `local_metadata_path`, `render_profile`, `local_manifest_path`, `local_video_path`, `render_status`, `publish_status`, `workflow_state`, `created_at`, `updated_at` | Idénticos. |

El `PropertyContext` de salida sigue siendo el dataclass legacy
(`application/types.py:225-265`) que aún espera `content_snapshot_json` y
`publish_target_snapshot_json` como `str` (los pasos 2/3/4 los leen).
**El use case devolverá un `PropertyContext` legacy** con los strings JSON
(consistente con el bridge: pipeline 2/3/4 todavía los necesitan) pero
internamente persistirá en `reels` el snapshot como dict.

---

## 4. Call sites externos y bridge worker

### Call sites de `DefaultPropertyInfoService`

| Archivo                                                | Líneas         | Acción tras feature 10 |
|--------------------------------------------------------|----------------|-------------------------|
| `application/bootstrap/runtime.py`                     | `:11` (import), `:103-110` (instanciación dentro de `build_default_property_media_pipeline`) | **Cambia.** Ver opciones abajo. |
| `application/bootstrap/__init__.py`                    | `:11` (import), `:103-110` (instanciación) | **Cambia idéntico** (los dos archivos son **byte-a-byte idénticos** según `diff` — son duplicados; nota para futuras features: 14 puede colapsarlos). |
| `application/pipeline/default_services.py`             | `:7, :20`       | Solo re-exporta; sin cambio funcional. Si tras feature 10 nadie más importa `DefaultPropertyInfoService` desde aquí, el implementer puede eliminar la entrada (depende de si se conserva el adapter delgado, ver abajo). |
| `application/pipeline/__init__.py`                     | `:342, :1834`   | Re-export del símbolo. Mismo criterio que `default_services.py`. |
| `application/pipeline/media_services.py`               | `:342, :1834`   | Aquí vive la clase. **Hay que reducir LoC** — ver opciones. |

### Llamadas a `.ingest_property` (verbo)

Solo una llamada externa real, además de la invocación interna del propio servicio:

- `application/pipeline/media_pipeline.py:44`:
  `context = self.property_info_service.ingest_property(job)`.
- `application/pipeline/interfaces.py:18-20`: `Protocol PropertyInfoService`
  con `def ingest_property(self, job) -> PropertyContext`.

### Bridge worker (delegación temporal — feature_list dice "intacto")

`apps/worker/runtime.py:262-274` registra el handler `reel_publish` con
`reel_pipeline.handle`, donde `ReelPipeline` está en
`modules/reels/application/orchestrator.py`. Ese `handle()` (líneas 23-31)
hace **lazy-import** de `application.bootstrap.runtime.build_default_job_handler`
y delega al `PropertyMediaPipeline` legacy. Es decir: **el bridge worker
hoy entra al pipeline legacy como caja negra**.

### Materialización de la "delegación temporal" — recomendación

La feature_list dice: *"El bridge worker sigue intacto temporalmente y
delega en este use case."* Hay dos formas de materializarlo:

**Opción A (preferida, recomendado):** `DefaultPropertyInfoService` queda
como **adapter delgado** dentro de `media_services.py`. Su `__init__`
sigue aceptando los mismos parámetros (para no romper bootstrap), y su
`ingest_property` simplemente construye un `IngestPropertyIntoReelUseCase`
con los mismos parámetros y delega:

```python
class DefaultPropertyInfoService:
    def __init__(self, workspace_dir, *, unit_of_work_factory,
                 property_url_template, property_url_tracking_params,
                 social_publishing_enabled, content_generator=None):
        self._use_case = IngestPropertyIntoReelUseCase(
            workspace_dir=workspace_dir,
            unit_of_work_factory=unit_of_work_factory,
            property_url_template=property_url_template,
            property_url_tracking_params=property_url_tracking_params,
            social_publishing_enabled=social_publishing_enabled,
            content_generator=content_generator,
        )

    def ingest_property(self, job: PropertyMediaJob) -> PropertyContext:
        return self._use_case.execute(job)
```

Todos los helpers privados que listamos en §1 se MUEVEN al use case;
en `media_services.py` el adapter pierde ~870 LoC y queda en ~10 LoC.
El bridge worker, `application/bootstrap/{runtime.py,__init__.py}` y
`PropertyMediaPipeline` siguen funcionando sin cambios.

**Opción B (más invasiva, no recomendada para feature 10):** borrar
`DefaultPropertyInfoService` y `PropertyInfoService` Protocol, y reescribir
`PropertyMediaPipeline` para que llame directamente al use case nuevo.
Esto cruza el alcance de feature 10 (toca el orchestrator legacy) y
debería ir en feature 14. **No tomar este camino aquí.**

### Para que el use case use UoW moderno desde el bridge legacy

El use case nuevo necesita un `DatabaseUnitOfWork` moderno (`shared.db.uow`),
pero el constructor histórico recibe un `unit_of_work_factory` que produce el
UoW **legacy** (`repositories/postgres/uow.DatabaseUnitOfWork`).
**Recomendación**: el use case acepta en su `__init__` el `unit_of_work_factory`
**legacy** (mismo nombre, misma firma) y **adicionalmente** construye dentro
de `execute(...)` su propio `shared.db.DatabaseUnitOfWork` con
`workspace_dir` y `database_locator` para las operaciones que migran a
namespaces modernos (`uow.reels.states`, `uow.catalog.properties`).
Mientras dure el bridge se abren **dos UoW** anidados (legacy + moderno)
porque pasos 2/3/4 todavía leen/escriben con el UoW legacy. Es feo pero es
lo que feature 14 elimina.

Alternativa más limpia (también aceptable): pasar al use case sólo el
`workspace_dir`, `database_locator` y dependencias funcionales; ignorar el
`unit_of_work_factory` legacy. La migración del adapter
`DefaultPropertyInfoService` reconstruye el `database_locator` desde el
factory si es necesario. Pero implica leakage del `database_locator` desde
runtime; el implementer decide.

---

## 5. Tests existentes

### `grep ingest_property|DefaultPropertyInfoService|_build_ingested_pipeline_state` en `tests/`

Resultado: **0 hits.** No hay test directo del paso ingest (ni unit ni
integration). Los tests "de cerca" tocan el dispatcher y el webhook, pero
montan el handler con fakes:

- `tests/integration/test_worker_runtime.py:32-94` — registra un handler
  `reel_publish` mock (`lambda job: ...`); **no** ejerce el pipeline real.
- `tests/integration/ingestion/test_wordpress_webhook_flow.py:31-159` —
  cubre el endpoint webhook que **encola** el job; nunca ejecuta el
  handler. El bridge no se toca.
- `tests/unit/reels/test_regenerate_reel.py`, `test_reject_reel.py`,
  `test_inspect_reel.py`, `test_list_reels.py` — todos sobre admin
  use cases, no sobre el pipeline.

**Conclusión**: feature 10 **suma** los dos tests nuevos del acceptance
sin migrar/adaptar nada existente.

### Crear (acceptance feature 10)

- `tests/unit/reels/test_ingest_property_into_reel.py` — camino feliz +
  camino de error.
  - **Camino feliz**: `IngestPropertyIntoReelUseCase.execute(job)` con un
    `job` mínimo y mocks de `uow.catalog.properties.upsert_property`,
    `uow.reels.states.get`/`.save`. Verifica `PropertyContext` devuelto
    (workflow_state="ingested", content_fingerprint coherente,
    `is_noop=False`, etc.).
  - **Camino de error**: `Property.from_api_payload(invalid_payload)`
    levanta `ValidationError` (legacy `core/errors.py`); el use case lo
    propaga.
  - Patrón a copiar: `tests/unit/reels/_uow_stubs.py` (Stub para
    `agencies`, `states`, etc. ya hay; añadir `StubProperties` con
    `upsert_property` si no existe).

- `tests/integration/reels/test_ingest_property_into_reel_flow.py` —
  verifica que tras `execute(job)` la fila correspondiente en `reels`
  existe con `workflow_state='ingested'` y, si feature_list lo exige,
  la(s) fila(s) en `media_revisions` (ver Discrepancia D1).
  - Usar `temporary_postgres_schema` + `seed_tenant` (ya en
    `tests/support/postgres.py`).
  - No mockear DB; SQL directo sobre `reels` y `media_revisions` para
    aserciones.

### Adaptar / migrar

Ninguno. El paso ingest no estaba directamente cubierto por tests. (Si
algo se mueve es indirectamente — por ejemplo `tests/unit/test_architecture_cleanup.py`
podría tener una assertion sobre número de clases en `media_services.py`;
verificar al final del implement.)

---

## 6. Riesgos / acoplamientos

### R1 — `_should_prepare_assets` cruza al step 2

`media_services.py:876-894` (`_should_prepare_assets`, paso ingest) llama
a dos staticmethods de `DefaultMediaPreparationService` (paso prepare):
`resolve_selected_dir` (`:1034`) y `resolve_primary_image_from_dir`
(`:1040`). Esos métodos **se quedan en `media_services.py`** hasta
feature 11. El use case nuevo importará desde `application/pipeline/media_services.py`
mientras dure el bridge — **ese import temporal es aceptable porque la
clase legacy sigue viva**.

### R2 — `PropertyContext` sigue usando snapshots como `str` JSON

El `PropertyContext` dataclass (legacy, `application/types.py:225-265`)
expone `content_snapshot_json: str` y `publish_target_snapshot_json: str`.
Los pasos 2/3/4 los leen como string. El use case nuevo deberá
**mantener ambos formatos** dentro del dominio del bridge: serializar a
str para `PropertyContext` y a dict para `uow.reels.states.save`. Helper
sugerido: el mismo `_json_text` que ya extraemos.

### R3 — Doble UoW durante el bridge

`PropertyMediaPipeline.run_job` (`media_pipeline.py:31-118`) abre 4
servicios secuencialmente, cada uno con `self.unit_of_work_factory()`
(UoW legacy). Si el use case nuevo además abre un `DatabaseUnitOfWork`
moderno por su cuenta, hay un commit moderno durante la ejecución del
ingest **antes** de que prepare/render/publish hagan los suyos. Esto NO
rompe nada porque cada UoW commitea su propio ámbito y el flujo legacy
ya commitea por servicio (no es transacción E2E). Pero es importante
documentarlo: la atomicidad por-step se conserva, no la atomicidad
end-to-end.

### R4 — Lookup `ingestion_source_id` por mapping

El job legacy trae `job.tenant.wordpress_source_id` que el bridge worker
(`orchestrator.py:46-48`) llena con `job.ingestion_source_id`. El nombre
de la propiedad cambia; el valor es el mismo. El use case persiste eso en
`reels.ingestion_source_id`. **Verificar** en el test de integración que
ese valor llega correcto (no vacío) cuando el job se construye desde un
`Job` de `delivery`.

### R5 — Logs grandes / observability

`ingest_property` produce dos `logger.info(format_console_block(...))` 
densos (`media_services.py:470-495` y `media_services.py:554-563`).
**Mantener verbatim** en el use case nuevo — el operador del worker los
busca por substring en los logs. No reformatear.

### R6 — `Property.from_api_payload` puede lanzar

`media_services.py:362` llama `Property.from_api_payload(job.payload)`.
Si el payload es inválido, `domain/properties/model.py` levanta
`ValidationError`. El test de error debe cubrirlo. El use case **no** lo
captura — propaga al worker dispatcher, que lo marca como `failed`
(retryable=False).

### R7 — Path absolutos del workspace

`workspace_dir` se resuelve con `Path(workspace_dir).expanduser().resolve()`.
Los tests usan `temporary_workspace()` que ya lo hace bien. No hay path
relativo escondido en el código del paso 1.

### R8 — La extracción atómica del step 1 ES viable

Tras releer el código completo no encontré state interno compartido entre
los 4 steps fuera de `PropertyContext` (que es dataclass `frozen=True`,
no se muta). Las dependencias del step 1 hacia los otros steps son
exactamente dos staticmethods de `DefaultMediaPreparationService` (R1).
El paso 1 **puede** salir del archivo en este PR sin tocar steps 2-4.

---

## 7. Plan de implementación recomendado

### Archivos a crear

1. `modules/reels/application/use_cases/ingest_property_into_reel.py`
   (~600-700 LoC). Contiene:
   - Free funcs privadas migradas: `_default_pipeline_state`, `_json_hash`,
     `_json_text`, `_parse_json_object`, `_normalise_platforms`,
     `_parse_publish_target_snapshot`, `_extract_platform_results`,
     `_is_successful_platform_result`, `_extract_successful_platforms`,
     `_resolve_absolute_path`, constante `_SUCCESSFUL_SOCIAL_STATUSES`.
   - Clase `IngestPropertyIntoReelUseCase` con:
     - `__init__(workspace_dir, *, unit_of_work_factory,
       property_url_template, property_url_tracking_params,
       social_publishing_enabled, content_generator=None,
       database_locator=None)`. (Decide implementer si `database_locator`
       sale del factory o se pasa explícito.)
     - `execute(job: PropertyMediaJob) -> PropertyContext` con la lógica
       íntegra de `ingest_property` (`media_services.py:360-518`).
     - Métodos privados migrados: `_resolve_publish_inputs`,
       `_build_publish_targets`, `_build_content_snapshot`,
       `_build_publish_target_snapshot`,
       `_determine_pending_publish_platforms`, `_should_prepare_assets`,
       `_has_local_artifacts`, `_build_existing_published_media`,
       `_should_reset_publish_history`, `_build_ingested_pipeline_state`.
   - **Persistencia**: dentro de `execute`, abrir
     `with DatabaseUnitOfWork(database_locator, workspace_dir) as uow:`
     y usar `uow.catalog.properties.upsert_property(record)` +
     `uow.reels.states.get(...)` / `.save(state)`. La construcción de
     `record` (Property → dict de columnas para la tabla `properties`)
     se replica del legacy `repositories/stores/property_store.py:_save_property_record`
     como helper privado del use case (NO se mueve a `PropertyRepository`
     moderno en feature 10 — eso es trabajo de feature 11/12 cuando se
     decida si `save_property_data` sube a `modules/catalog`).
   - Re-export en `modules/reels/application/use_cases/__init__.py`.

2. `tests/unit/reels/test_ingest_property_into_reel.py` — 2+ tests
   (camino feliz, camino de error). Stubs de UoW moderno; no DB real.

3. `tests/integration/reels/test_ingest_property_into_reel_flow.py` —
   1+ tests (`temporary_postgres_schema` + `seed_tenant`, ejecuta
   `IngestPropertyIntoReelUseCase.execute(job)` con UoW real, valida
   filas en `reels` y, si la discrepancia D1 se resuelve a favor de
   `feature_list`, también en `media_revisions`).

### Archivos a modificar

1. `application/pipeline/media_services.py`:
   - **Borrar** los rangos identificados en §1 (helpers privados ingest +
     free funcs ingest + cuerpo de `ingest_property` + `_build_ingested_pipeline_state`).
   - **Conservar**: clase `DefaultPropertyInfoService` reducida a adapter
     delgado (~10-15 LoC) que delega a `IngestPropertyIntoReelUseCase`.
   - Mantener `__init__` con los mismos parámetros (firma estable para
     bootstrap).
   - El método `ingest_property` queda como `return
     self._use_case.execute(job)`.
   - Resultado esperado: `media_services.py` baja de **1839 → ~960 LoC**
     (~870 LoC borrados; estimación basada en rangos `360-518`, `520-600`,
     `602-674`, `676-689`, `691-724`, `726-767`, `769-874`, `876-894`,
     `896-935`, `937-959`, `961-977` más helpers de módulo `73-127`,
     `178-313`).

2. `application/pipeline/__init__.py` y `application/pipeline/default_services.py`:
   - Sin cambios funcionales (siguen re-exportando el adapter
     `DefaultPropertyInfoService`).

3. `application/bootstrap/runtime.py` y `application/bootstrap/__init__.py`:
   - **Sin cambios**. Los dos archivos son byte-a-byte idénticos —
     verificado con `diff`. Siguen instanciando `DefaultPropertyInfoService`
     con los mismos parámetros.

4. `application/pipeline/media_pipeline.py`:
   - **Sin cambios** en feature 10. Sigue llamando a
     `self.property_info_service.ingest_property(job)`. Feature 14 lo
     reemplaza.

5. `application/pipeline/interfaces.py`:
   - **Sin cambios**. Protocol `PropertyInfoService` sigue vigente para
     el adapter.

### Archivos a borrar

Ninguno en este alcance. (Las features 11-14 borran progresivamente
`media_services.py` completo y `application/persistence.py`.)

### Orden sugerido

1. Implementer crea `modules/reels/application/use_cases/ingest_property_into_reel.py`
   con la lógica íntegra (copiar/pegar y adaptar).
2. Crea `tests/unit/reels/test_ingest_property_into_reel.py` y los hace
   pasar (`pytest -q tests/unit/reels/test_ingest_property_into_reel.py`).
3. Crea `tests/integration/reels/test_ingest_property_into_reel_flow.py`
   y lo hace pasar.
4. Modifica `media_services.py` para reducir `DefaultPropertyInfoService` a
   adapter y borrar los helpers movidos.
5. Corre suite completa (`./init.sh`). Baseline 376 + ≥3 tests nuevos =
   **≥ 379 verdes**.

### LoC reducido aproximado en `media_services.py`

- Movido al use case nuevo: **~880 LoC** (rangos identificados en §1).
- Adapter delgado introducido: **~15 LoC**.
- Reducción neta: **~865 LoC**.
- `media_services.py` post-feature: **~960 LoC** (de 1839).

---

## Discrepancias detectadas

### D1 — "persistir media revision inicial" no existe en el código legacy

- `feature_list.json` #10 description y acceptance dicen:
  *"persistir media revision inicial, marcar estado ingested"* y
  *"verifica estado en `reels` y `media_revisions`"*.
- En realidad `ingest_property` (`media_services.py:360-518`) **no toca
  `media_revisions`**. Las dos llamadas a `save_media_revision`
  (`media_services.py:1405, :1784`) están en `FileSystemMediaPublisher` y
  `CompositeMediaPublisher` (paso publish, feature 13).
- **Recomendación**: el implementer NO inventa una escritura a
  `media_revisions` en feature 10 — el flujo legacy no la tiene y
  añadirla cambia semántica del pipeline. El test de integración del
  acceptance se ajusta a verificar **solo `reels`** y, opcionalmente,
  asserta que `media_revisions` está **vacía** después del ingest (para
  documentar el comportamiento real). Esto no contradice el acceptance
  literal "verifica estado en `reels` y `media_revisions`" si se entiende
  como "consulta ambas tablas".
- Si el leader prefiere mover una porción de la persistencia del paso
  publish al ingest (revision_id "pendiente"), eso debería ser una
  decisión explícita y documentada — está fuera del alcance literal de
  feature 10. No hacerlo por defecto.

### D2 — "`docs/phase_2_operating_rules.md` cubre features 2-8"

El documento de Phase 2 explícitamente lista features 2-8. Features 10-14
no están en él, aunque la prompt del leader dice "los principios son
también aplicables a 10-14". Lo asumo y aplico:
- "Borrar todo lo legacy a medida que se mueve" se modula con la nota:
  legacy aún consumido por otras features 10-14 se conserva. En feature
  10 → conservar `DefaultPropertyInfoService` como adapter delgado, NO
  borrarlo (lo borra feature 14).
- "Naming descriptivo": el verbo `ingest_property_into_reel` ya es
  descriptivo. ✅
- "Sin commits intermedios": el implementer no commitea. ✅

### D3 — `application/bootstrap/{runtime.py,__init__.py}` son duplicados literales

`diff` devuelve sin output. Son byte-a-byte idénticos. La prompt del
leader habla de "parecen casi idénticos" — confirmado: son **idénticos**.
No es bug de feature 10, pero el leader puede querer colapsar uno de los
dos en feature 14 (cuando se borre `media_services.py`).

### D4 — `_should_prepare_assets` (paso 1) llama a métodos del paso 2

Documentado en R1. No es bug; es el único punto de cruce entre step 1 y
step 2. Aceptable porque feature 11 lo resolverá moviendo
`DefaultMediaPreparationService` a `modules/reels` también.

---

**Fin del informe.**
