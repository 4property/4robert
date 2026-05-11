# Explore — Feature 17 `retire_property_store_and_repositories_stores`

> Última feature antes de la 18 (cierre Phase 2). Acceptance literal:
>
> > Migrar los call sites restantes de `repositories/stores/` a
> > `uow.catalog.*` y `uow.reels.*`. Borrar el directorio `repositories/`
> > completo y la fachada
> > `modules/catalog/infrastructure/property_store_compat.py`.
>
> Acceptance:
>
> - `repositories/` borrado por completo.
> - `modules/catalog/infrastructure/property_store_compat.py` borrado.
> - Ningún archivo bajo `apps/`, `modules/`, `shared/`, `tests/` importa
>   de `repositories/`.
> - `pytest -q` termina verde.
> - `python -m apps.api --check` y `python -m apps.worker --check` exit 0.

Contexto leído (en orden):

1. `feature_list.json` (entry id=17 + ordering_notes; legacy_dirs_frozen
   incluye `repositories/`). La feature 18 borra
   `services/`/`application/`/`core/`/`domain/`.
2. `progress/explore_feature_16_worker_real_use_cases.md` §0 promete que
   las features 17/18 cierran Phase 2 borrando `repositories/`,
   `application/`, `services/`, `core/`, `domain/`.
3. `progress/impl_16_worker_real_use_cases.md` confirma que
   `application/bootstrap/runtime.py` quedó reducido a 68 LoC (sólo
   `build_default_social_property_publisher`,
   `build_default_unit_of_work_factory`,
   `build_runtime_unit_of_work_factory`, constante
   `WEBHOOK_SHUTDOWN_TIMEOUT_SECONDS`) — **pero su `from
   repositories.postgres.uow import DatabaseUnitOfWork` (`:5`) sigue
   vivo** porque `RenderScriptedVideoUseCase.execute` (worker) llama
   lazy a `build_runtime_unit_of_work_factory`. Ese único hook bloquea
   borrar `repositories/`.
4. `progress/review_16_worker_real_use_cases.md` APPROVED 461 tests
   verdes; lista 4 archivos/legacy borrados. Confirma que feature 17 es
   la siguiente en pipeline.
5. **Estructura de `repositories/`**: `ls -la repositories/` + `wc -l`.
   13 archivos `.py` activos, 3610 LoC totales:

   | Archivo | LoC | Función |
   |---------|----:|---------|
   | `repositories/postgres/__init__.py` | 3 | Re-export `Base`. |
   | `repositories/postgres/base.py` | 10 | `class Base(DeclarativeBase)`. |
   | `repositories/postgres/engine.py` | 97 | `get_engine`, `resolve_database_binding`, `verify_required_tables`, `describe_database_binding` (cache de Engines + masking de URL). |
   | `repositories/postgres/repository.py` | 41 | `PostgresRepositoryBase` (ctx-mgr con `CompatConnection`) + `now_iso()`. |
   | `repositories/postgres/security.py` | 25 | Fernet `encrypt_text`/`decrypt_text` (lee `DATABASE_ENCRYPTION_KEY`). Hay copia idéntica en `shared/db/security.py` (ya importada por `tests/support/postgres.py:17`). |
   | `repositories/postgres/session.py` | 130 | `create_session`, `create_session_factory`, `CompatConnection`, `CompatRow`, `CompatResult` (capa SQLite-compat sobre SQLAlchemy `Session`). |
   | `repositories/postgres/uow.py` | 140 | `DatabaseUnitOfWork` legacy (compone los 11 stores listados abajo bajo atributos planos `property_repository`, `pipeline_state_repository`, `media_revision_store`, `outbox_event_store`, `webhook_event_store`, `job_queue_store`, `scripted_video_store`, `wordpress_source_store`, `agency_store`, `ghl_connection_store`, `reel_profile_store`). |
   | `repositories/postgres/models/__init__.py` | 366 | 12 ORM Models declarativos (`AgencyModel`, `WordPressSourceModel`, `PropertyModel`, `PropertyImageModel`, `PropertyPipelineStateModel`, `WebhookEventModel`, `JobQueueModel`, `MediaRevisionModel`, `OutboxEventModel`, `ScriptedVideoArtifactModel`, `GoHighLevelConnectionModel`, `ReelProfileModel`). **Schema legacy** (con `wordpress_source_id`, `site_id`, columnas TEXT-JSON, tabla `property_pipeline_state`, etc.). El schema vivo lo declara `shared/db/orm.py` (Alembic source of truth). |
   | `repositories/stores/__init__.py` | 0 | Placeholder. |
   | `repositories/stores/agency_store.py` | 215 | `AgencyRecord` + `AgencyStore(PostgresRepositoryBase)`. |
   | `repositories/stores/ghl_connection_store.py` | 278 | `GoHighLevelConnectionRecord` + `GoHighLevelConnectionStore` (cifra access/refresh tokens vía `repositories.postgres.security`). |
   | `repositories/stores/job_queue_store.py` | 412 | `PropertyJobEnqueueRequest` + `QueuedPropertyJobRecord` + `PropertyJobRepository` (claim_next_ready_job + lease + retry + supersede). |
   | `repositories/stores/media_revision_store.py` | 183 | `MediaRevisionRecord` + `MediaRevisionRepository`. |
   | `repositories/stores/outbox_event_store.py` | 217 | `OutboxEventRecord` + `OutboxEventRepository`. |
   | `repositories/stores/pipeline_state_store.py` | 431 | `PropertyPipelineState` + `PipelineStateStore` (escribe contra tabla `reels` ya — feature 16 confirmó migration; los métodos modernos son `update_publish_status`, `update_workflow_state`, `save_local_artifacts`). |
   | `repositories/stores/property_store.py` | 464 | `PropertyStore` (delega columns/SQL helpers a `modules/catalog/infrastructure/property_store_compat`). |
   | `repositories/stores/reel_profile_store.py` | 347 | `ReelProfileRecord` + `ReelProfileStore`. **Sin call sites externos vivos** (feature 6 lo retiró del flujo principal — verificado abajo §0.B). |
   | `repositories/stores/scripted_video_artifact_store.py` | 195 | `ScriptedVideoArtifactRecord` + `ScriptedVideoArtifactRepository`. |
   | `repositories/stores/webhook_event_store.py` | 143 | `WebhookDeliveryRecord` + `WebhookDeliveryRepository`. |
   | `repositories/stores/wordpress_source_store.py` | 279 | `WordPressSourceRecord` + `WordPressSourceDetailsRecord` + `WordPressSourceStore`. |
6. **Modern repos under `modules/<bc>/infrastructure/`** — todas existen
   ya (creadas por features 2-16):

   | Repo | LoC | Path |
   |------|----:|------|
   | `PropertyRepository` + `PropertyImageRepository` | 225 | `modules/catalog/infrastructure/property_repository.py` |
   | `ReelStateRepository` | 353 | `modules/reels/infrastructure/reel_state_repository.py` |
   | `MediaRevisionRepository` | 119 | `modules/reels/infrastructure/media_revision_repository.py` |
   | `ScriptedVideoArtifactRepository` | 124 | `modules/reels/infrastructure/scripted_video_artifact_repository.py` |
   | `ReelQuery` | 336 | `modules/reels/infrastructure/reel_query.py` |
   | `JobRepository` | 365 | `modules/delivery/infrastructure/job_repository.py` |
   | `OutboxRepository` | 160 | `modules/delivery/infrastructure/outbox_repository.py` |
   | `WebhookEventRepository` | 113 | `modules/delivery/infrastructure/webhook_event_repository.py` |
   | `AgencyRepository` | 136 | `modules/tenancy/infrastructure/agency_repository.py` |
   | `IngestionSourceRepository` | 241 | `modules/ingestion/infrastructure/ingestion_source_repository.py` |
   | `ProviderConnectionRepository` | 277 | `modules/publishing/infrastructure/provider_connection_repository.py` |
   | 5 configuration repos | — | `modules/configuration/infrastructure/{automation,brand,defaults,music_track,social_template}_repository.py` |
7. `shared/db/uow.py` (193 LoC, leído íntegro). Namespaces:
   - `uow.tenancy.agencies` → `AgencyRepository`.
   - `uow.ingestion.sources` → `IngestionSourceRepository`.
   - `uow.publishing.connections` → `ProviderConnectionRepository`.
   - `uow.catalog.properties` → `PropertyRepository`.
   - `uow.catalog.images` → `PropertyImageRepository`.
   - `uow.reels.states` → `ReelStateRepository`.
   - `uow.reels.revisions` → `MediaRevisionRepository`.
   - `uow.reels.scripted_artifacts` → `ScriptedVideoArtifactRepository`.
   - `uow.reels.queries` → `ReelQuery`.
   - `uow.configuration.{brand,defaults,automation,social_templates,music}` → 5 repos.
   - `uow.delivery.jobs` → `JobRepository`.
   - `uow.delivery.outbox` → `OutboxRepository`.
   - `uow.delivery.webhook_events` → `WebhookEventRepository`.

   Constructor: `DatabaseUnitOfWork(database_locator=None,
   base_dir=None)`. Owns `Session` y commit en `__exit__`.
8. `modules/catalog/infrastructure/property_store_compat.py` (278 LoC,
   leído íntegro). Símbolos exportados:
   - 3 constantes (`PIPELINE_STATE_TABLE_NAME = "reels"`,
     `PROPERTY_IMAGES_TABLE_NAME = "property_images"`,
     `PROPERTY_TABLE_NAME = "properties"`) y la tupla
     `PROPERTY_REEL_SELECT_FIELDS` (32 columnas con alias `AS site_id`,
     `AS source_property_id`, etc., para preservar la API legacy).
   - 3 dataclasses (`PropertySyncState`, `AgencyReelSummary`,
     `PropertyReelRecord`).
   - 4 helpers (`deserialize_text_tuple`, `relative_to_base`,
     `build_property_reel_select_sql`,
     `list_recent_reels_for_agency(connection, *, agency_id, limit)`,
     `now_iso`).
   - **Único consumidor:** `repositories/stores/property_store.py:9-21`
     (Grep `from modules.catalog.infrastructure.property_store_compat`
     → 1 sola línea). Cuando `property_store.py` se borre, este facade
     queda huérfano y se borra trivialmente.
9. **Call sites de `repositories/`** (Grep exhaustivo `from
   repositories\.|import repositories` en todo el repo):
   - **`apps/`**: 0 hits.
   - **`modules/`**: 0 hits.
   - **`shared/`**: 0 hits.
   - **`tests/`**: 2 hits (`tests/unit/test_architecture_cleanup.py` +
     `tests/unit/test_tenancy.py`).
   - **`services/` (legacy frozen)**: 4 archivos lo importan
     transitivamente:
     - `services/transport/http/operations.py:23-33` — 6 imports
       (`PropertyStore`, `PipelineStateStore`, `MediaRevisionRepository`,
       `OutboxEventRepository`, `WebhookDeliveryRepository`,
       `PropertyJobRepository`, `describe_database_binding`,
       `resolve_database_binding`, `verify_required_tables`).
     - `services/publishing/social_delivery/description.py:7` —
       `PropertyReelRecord`.
     - `services/media/reel_rendering/data.py:7` — `PropertyReelRecord`,
       `PropertyStore`.
   - **`application/` (legacy frozen)**: 6 archivos:
     - `application/bootstrap/runtime.py:5` — `DatabaseUnitOfWork`
       (legacy). Consumidor real: el lazy import de
       `RenderScriptedVideoUseCase.execute` y `_build_default_social_property_publisher`
       en `modules/reels/application/orchestrator.py:246`.
     - `application/bootstrap/__init__.py:5` — byte-igual al anterior.
     - `application/persistence.py:6-16` — 11 imports de
       `repositories.stores.*` (los `*Record` dataclasses + `Property…Repository`).
       Define `class UnitOfWork(Protocol)` con los 11 atributos planos
       (legacy shape). Consumido sólo por otros archivos en
       `application/`: `tenancy/resolver.py`, `scripted_render/{__init__,service}.py`,
       `dispatch/database_dispatcher.py` (4 hits).
     - `application/scripted_render/__init__.py:18` y
       `application/scripted_render/service.py:18` — `ScriptedVideoArtifactRecord`.
     - `application/dispatch/database_dispatcher.py:385` — lazy
       `from repositories.stores.job_queue_store import PropertyJobEnqueueRequest`.
   - **`repositories/` interno**: 11 imports cruzados (stores ↔
     postgres) + 1 import de `application.persistence.UnitOfWork` en
     `repositories/postgres/uow.py:5`.
10. **Tests específicos a `repositories/`**: 2 archivos.
    - `tests/unit/test_architecture_cleanup.py:13-15` —
      `DatabaseUnitOfWork` (legacy), `PipelineStateStore`, `PropertyStore`.
      3 tests:
      1. `test_canonical_runtime_symbol_names_are_active` — comprueba
         `DatabaseJobDispatcher.__name__` y `DatabaseUnitOfWork.__name__`.
         Apunta a clases legacy.
      2. `test_database_unit_of_work_uses_split_stores` — asserts
         `unit_of_work.property_repository is PropertyStore` y
         `pipeline_state_repository is PipelineStateStore` sobre el
         **legacy** UoW. Test específicamente diseñado para validar la
         API legacy. **Borrarlo** (cubierto por la mera existencia de
         `shared/db/uow.py` y los tests integration que usan los
         namespaces modernos).
      3. `test_source_tree_contains_no_sqlite_or_config_legacy_symbols`
         — Grep en `application/`, `domain/`, `repositories/`,
         `services/`, `settings/`, `main.py` buscando 9 patrones
         legacy. **Sigue siendo útil**, pero las roots cambian: tras
         feature 17 `repositories/` ya no existe; tras feature 18
         tampoco `application/`/`services/`/`domain/`. La feature 17
         puede actualizar la lista de roots (quitar `repositories`) o
         dejarlo a feature 18. **Decisión recomendada (R5)**: borrar el
         test entero — su valor (detectar regresiones SQLite) ya no
         compensa el churn que tendrá feature 18 al borrar las otras
         roots.
    - `tests/unit/test_tenancy.py:14` — `from repositories.postgres.uow
      import DatabaseUnitOfWork`. 3 tests. Construyen
      `TenantResolver(unit_of_work_factory=lambda:
      DatabaseUnitOfWork(database.url, workspace_dir))`. Como
      `TenantResolver` vive en `application/tenancy/resolver.py` (legacy)
      y consume `application.persistence.UnitOfWork` Protocol, **el
      test entero pertenece al stack legacy**. Tras feature 16, la
      resolución de tenant moderna está dentro de `IngestionSourceRepository`
      (`uow.ingestion.sources.get_by_kind_external_id(kind="wordpress",
      external_id=...)`); ya hay tests modernos sobre esa ruta en
      `tests/integration/ingestion/test_wordpress_webhook_flow.py` (de
      feature 4). **Decisión recomendada (R6)**: borrar
      `test_tenancy.py` entero (la API legacy `TenantResolver`
      muere con el directorio `application/` en feature 18 de todas
      formas).
11. `docs/phase_2_operating_rules.md` — leído íntegro:
    - §1 modo serial. §2 borrar legacy a medida (sin compat shims).
      Cita explícita: *"Cuando una feature deja un store legacy en
      `repositories/stores/` sin call sites, se borra en esa misma
      feature. La feature 17 deja de tener trabajo conforme las
      features 2-8 limpian a su paso."* — pero **el trabajo restante
      de feature 17 NO es cero**: features 2-16 dejaron consumidores
      sólo en `application/`/`services/` (frozen) + 2 tests legacy +
      1 chain crítico vía `_check`. §4 sin commits. §6 baseline 461
      tests verdes (post-16, ver `impl_16:393`). §8 bloquear si
      premisas cambian.
12. `docs/architecture.md:88-92` — *"❌ Añadir código nuevo en
    `services/`, `application/`, `repositories/`, `core/`, `domain/`.
    Son la capa de compatibilidad de Phase 1; cualquier feature nueva
    entra en `modules/<bc>/`."* — coherente: feature 17 sólo borra,
    feature 18 acaba de retirar.

---

## 0. Decisión de alcance

### A. ¿Cuántos archivos hay en `repositories/`? ¿LoC totales?

13 archivos `.py` activos + 2 `__init__.py` + un `__pycache__/`. **3 610
LoC totales** (medido con `wc -l` — ver §5 arriba). Distribución:

- `repositories/postgres/`: 7 archivos, 812 LoC (engine, base, session,
  repository, security, uow, models).
- `repositories/stores/`: 11 archivos, 2 798 LoC (10 stores + `__init__.py`
  vacío).

### B. ¿Cuántos call sites externos quedan tras features 1-16?

**Bajo dirs activos (`apps/`, `modules/`, `shared/`, `tests/`)**: 2
archivos.

| Archivo | Línea | Símbolo legacy | ¿Adaptar o borrar? |
|---------|------:|----------------|--------------------|
| `tests/unit/test_architecture_cleanup.py` | 13 | `from repositories.postgres.uow import DatabaseUnitOfWork` | **Borrar el archivo entero** (R5). |
| `tests/unit/test_architecture_cleanup.py` | 14 | `from repositories.stores.pipeline_state_store import PipelineStateStore` | idem. |
| `tests/unit/test_architecture_cleanup.py` | 15 | `from repositories.stores.property_store import PropertyStore` | idem. |
| `tests/unit/test_tenancy.py` | 14 | `from repositories.postgres.uow import DatabaseUnitOfWork` | **Borrar el archivo entero** (R6) — `TenantResolver` legacy. |

**Bajo dirs frozen (`services/`, `application/`)**: 10 archivos,
mostrados arriba en §9. Ninguno está en el path obligatorio del
acceptance literal de feature 17 ("ningún archivo bajo `apps/`,
`modules/`, `shared/`, `tests/`"). Pero hay **un canal indirecto** que
sí entra en alcance porque rompe `python -m apps.api --check`:

- `apps/api/main.py:82` — `from services.transport.http.operations
  import build_readiness_report`. `build_readiness_report` se importa
  perezosamente dentro de `_check` y **abre 6 stores legacy**
  (`PropertyStore`, `PipelineStateStore`, `MediaRevisionRepository`,
  `OutboxEventRepository`, `WebhookDeliveryRepository`,
  `PropertyJobRepository`) en `_ensure_database_writable`
  (`operations.py:395-406`). Si `repositories/` se borra, el `_check`
  no resuelve imports y exit code ≠ 0.
- `apps/api/health_router.py:115` — mismo `build_readiness_report`,
  invocado por el `GET /health/details` (admin-only). Mismo problema.

Por tanto, **feature 17 debe romper esta cadena** para cumplir el
acceptance "exit 0" sin tocar `services/transport/http/operations.py`
internals (frozen). Opciones:

- **Opción α** — Migrar `services/transport/http/operations.py` a usar
  `shared.db.engine.verify_required_tables` + un `with
  DatabaseUnitOfWork(...)` para verificar 6 namespaces. Toca legacy
  pero sólo 11 LoC de imports/instanciaciones. El rule §2 permite "el
  legacy que deja de tener call sites tras esta feature se borra" —
  los 6 imports legacy de `operations.py` quedan sin call site al
  borrar `repositories/`, así que la migración es necesaria.
- **Opción β** — Mover `build_readiness_report` a
  `apps/api/readiness.py` (nuevo), reescrito sobre los repos modernos
  + `shared.db.engine`, y actualizar los 2 call sites en `apps/api/`
  para apuntar al nuevo módulo. `services/transport/http/operations.py`
  queda sin call sites tras feature 17 → feature 18 lo borra.
- **Decisión recomendada: Opción β.** Razones:
  1. Mantiene `services/transport/http/operations.py` intacto (frozen)
     hasta feature 18.
  2. Concentra el "permiso" de tocar legacy en `apps/api/` (in-scope
     de feature 17 por la naturaleza del acceptance: hay que
     desconectar `apps/api/main.py` del path legacy).
  3. El nuevo `apps/api/readiness.py` es código moderno reusable;
     feature 18 lo deja en su sitio definitivo.
  4. El propio `impl_9:130` (tabla "deuda explícita para feature 18")
     ya marcaba este punto como pendiente; feature 17 lo cierra al
     adelantarse a feature 18 en este aspecto puntual.

### C. ¿Hay tests que dependen específicamente de la API legacy de `repositories/`?

Sí, los 2 listados en §0.B. Ambos son **tests sobre infraestructura
legacy** (`DatabaseUnitOfWork` legacy + `TenantResolver` legacy de
`application/tenancy/`). Hay equivalentes modernos en:

- `tests/integration/test_worker_runtime.py` + `tests/integration/delivery/test_worker_dispatcher_flow.py`
  (cubren `shared.db.uow.DatabaseUnitOfWork` y los 4 use cases reales).
- `tests/integration/ingestion/test_wordpress_webhook_flow.py` (cubre
  resolución de tenant vía `uow.ingestion.sources.get_by_kind_external_id`).
- Cualquier test integration de features 2-7 (todos abren
  `DatabaseUnitOfWork` moderno).

Adaptar los 2 tests legacy al UoW moderno es trabajo redundante; **se
recomienda borrarlos** (R5, R6). Nota: ningún test bajo
`tests/integration/` importa de `repositories/` (verificado).

### D. `property_store_compat.py`: ¿qué hace? ¿qué lo consume?

Hace tres cosas (§8):

1. Centraliza 3 constantes de nombres de tabla (`reels`,
   `property_images`, `properties`) y la tupla
   `PROPERTY_REEL_SELECT_FIELDS` (32 columnas con alias *site_id,
   source_property_id, …* — la lista AS-aliased que `PropertyStore`
   usa para reconstruir su API legacy).
2. Define 3 dataclasses (`PropertySyncState`, `AgencyReelSummary`,
   `PropertyReelRecord`) que `PropertyStore` retorna.
3. Implementa `list_recent_reels_for_agency(connection, *, agency_id,
   limit)` — la query JOIN catalog × reels × media_revisions que el
   admin usaba para listar reels. Esta query **ya está duplicada en
   forma moderna** en
   `modules/reels/infrastructure/reel_query.py:ReelQuery.list_for_agency`
   (`uow.reels.queries.list_for_agency(...)`); el path moderno lo
   consume `modules/reels/application/use_cases/list_reels.py` (feature
   7). Consumidores hoy:
   - **Único caller**: `repositories/stores/property_store.py:9-21`
     (Grep `from modules.catalog.infrastructure.property_store_compat`
     → 1 hit). Cuando `property_store.py` se borre, este facade queda
     huérfano y se borra trivialmente.

Verificación: `Grep "AgencyReelSummary|PropertyReelRecord|build_property_reel_select_sql|list_recent_reels_for_agency|deserialize_text_tuple|relative_to_base|PropertySyncState|PROPERTY_REEL_SELECT_FIELDS"` muestra hits adicionales en
`services/media/reel_rendering/data.py`, `services/publishing/social_delivery/description.py` y `application/persistence.py`, pero esos importan **del mismo
`repositories/stores/property_store.py`**, no del compat. No hay otro
consumidor del compat module.

---

## 1. Mapeo legacy → moderno

Para cada archivo en `repositories/stores/`. Filas con "✅ sin call
sites en `apps|modules|shared|tests`" significan que el código activo
ya migró; sólo `services/`/`application/` (frozen) lo importan, y eso
muere con feature 18. Las firmas modernas vienen de `shared/db/uow.py`
+ los repos.

| Archivo legacy | Símbolo legacy | Reemplazo moderno | Diferencia de modelo |
|----------------|----------------|-------------------|----------------------|
| `repositories/stores/agency_store.py` | `AgencyRecord`, `AgencyStore.{get_by_id,get_by_slug,list_agencies,create_agency,update_agency,delete_agency}` | `uow.tenancy.agencies` (`AgencyRepository.{get,get_by_slug,list,upsert,delete}` — `modules/tenancy/infrastructure/agency_repository.py`). | Aggregate moderno: `Agency` dataclass en `modules/tenancy/domain`. ✅ sin call sites en dirs activos. |
| `repositories/stores/wordpress_source_store.py` | `WordPressSourceRecord`, `WordPressSourceDetailsRecord`, `WordPressSourceStore.{get_by_site_id,get_details_by_site_id,list_sources,list_sources_for_agency,create_source,update_source,delete_source}` | `uow.ingestion.sources` (`IngestionSourceRepository` con `kind="wordpress"` + `external_source_id`). | Schema legacy `wordpress_sources(site_id)` ya no existe (Alembic ya migró). Tabla viva: `ingestion_sources(kind, external_id, agency_id, …)`. Rename de columnas: `site_id` → `external_id`. ✅ sin call sites en dirs activos. |
| `repositories/stores/property_store.py` | `PropertyStore.{get_property_raw_payload,list_property_images,list_recent_for_agency,get_property_ids,get_property_sync_state,get_property_reel_record,save_property_data,save_property_images,save_downloaded_images,_save_property_record,_upsert_property_record,_replace_property_images}` | `uow.catalog.properties` (`PropertyRepository.{get_raw_payload,get_sync_state,get_property_ids,upsert_property}`) + `uow.catalog.images` (`PropertyImageRepository.{list_for_property,replace_images}`) + `uow.reels.queries` (`ReelQuery.{list_for_agency,get_reel_detail}`). | Renames: `site_id` → `external_source_id` (tabla `properties`), `wordpress_source_id` → `ingestion_source_id`, columna `raw_json` ahora `jsonb`. Get_property_reel_record (JOIN catalog × reels) lo cubre `ReelQuery` moderno. ✅ sin call sites en dirs activos. |
| `repositories/stores/pipeline_state_store.py` | `PropertyPipelineState`, `PipelineStateStore.{get_property_pipeline_state,save_property_pipeline_state,update_social_publish_status,update_workflow_state,save_local_artifacts}` | `uow.reels.states` (`ReelStateRepository.{get,save,update_publish_status,update_workflow_state,save_local_artifacts}`). | Tabla legacy `property_pipeline_state` → tabla moderna `reels`. JSON-TEXT columns (`content_snapshot_json`, `publish_target_snapshot_json`, `publish_details_json`) → `jsonb` (`content_snapshot`, `publish_target_snapshot`, `publish_details`). Rename: `site_id` → `external_source_id`, `wordpress_source_id` → `ingestion_source_id`, `last_published_location_id` → `last_published_provider_external_id`. Firma `save_local_artifacts` casi 1:1 (mismo set de kwargs). ✅ sin call sites en dirs activos. |
| `repositories/stores/media_revision_store.py` | `MediaRevisionRecord`, `MediaRevisionRepository.{save_media_revision,get_media_revision,list_media_revisions}` | `uow.reels.revisions` (`MediaRevisionRepository.{save_revision,get_revision,list_revisions}`). | Rename API: `save_media_revision` → `save_revision` (signature toma `MediaRevision` aggregate, no `MediaRevisionRecord` dataclass). Renames de columnas: `site_id` → `external_source_id`, `wordpress_source_id` → `ingestion_source_id`. ✅ sin call sites en dirs activos. |
| `repositories/stores/outbox_event_store.py` | `OutboxEventRecord`, `OutboxEventRepository.{add_event,mark_published,list_events}` | `uow.delivery.outbox` (`OutboxRepository.{add_event,mark_published,list_events}`). | Firmas casi 1:1; cambio kwarg: `site_id` → `external_source_id`, `wordpress_source_id` → `ingestion_source_id`. Payload `jsonb` (no string-JSON). ✅ sin call sites en dirs activos. |
| `repositories/stores/webhook_event_store.py` | `WebhookDeliveryRecord`, `WebhookDeliveryRepository.{create_event,update_event_status,get_event}` | `uow.delivery.webhook_events` (`WebhookEventRepository`). | Verificar firmas exactas (modern repo no enumerado en §6 explícitamente); `wc -l` 113 LoC. Renames consistentes. ✅ sin call sites en dirs activos. |
| `repositories/stores/job_queue_store.py` | `PropertyJobEnqueueRequest`, `QueuedPropertyJobRecord`, `PropertyJobRepository.{enqueue_job,supersede_queued_jobs,recover_expired_processing_jobs,claim_next_ready_job,renew_job_lease,mark_job_completed,mark_job_failed,schedule_retry,count_active_jobs,get_job,list_jobs_for_property}` | `uow.delivery.jobs` (`JobRepository`). | Tabla legacy `job_queue` → moderna `jobs`. Renames: `site_id` → `external_source_id`, `wordpress_source_id` → `ingestion_source_id`. El campo `gohighlevel_access_token_encrypted` (encrypted bytes) ahora se persiste vía `provider_secret_bundle` en el `Job` aggregate (cifrado por `shared.db.security.encrypt_text`). ✅ sin call sites en dirs activos. |
| `repositories/stores/scripted_video_artifact_store.py` | `ScriptedVideoArtifactRecord`, `ScriptedVideoArtifactRepository.{save_artifact,get_artifact,list_artifacts_for_property}` | `uow.reels.scripted_artifacts` (`ScriptedVideoArtifactRepository`). | Renames consistentes (`site_id` → `external_source_id`, `wordpress_source_id` → `ingestion_source_id`). ✅ sin call sites en dirs activos. |
| `repositories/stores/ghl_connection_store.py` | `GoHighLevelConnectionRecord`, `GoHighLevelConnectionStore.{get_by_agency_id,list_connections,upsert_for_agency,delete_by_agency_id,require_for_agency}` | `uow.publishing.connections` (`ProviderConnectionRepository` con `provider="gohighlevel"`). | Tabla legacy `ghl_connections` → moderna `provider_connections(provider, agency_id, external_account_id, secrets_encrypted)`. Tokens cifrados ahora vía `shared.db.security.encrypt_text` (no `repositories.postgres.security`). ✅ sin call sites en dirs activos. |
| `repositories/stores/reel_profile_store.py` | `ReelProfileRecord`, `ReelProfileStore.{get_by_agency_id,upsert_for_agency,delete_by_agency_id}` | Sustituido por **5 repos** en `uow.configuration.*` (`brand`, `defaults`, `automation`, `social_templates`, `music`). Feature 6 partió `reel_profiles` en 5 tablas tipadas (`agency_brand_settings`, `agency_reel_defaults`, `agency_automation_rules`, `agency_social_templates`, `agency_music_tracks`). | Tabla legacy `reel_profiles` ya no existe en migrations vivas. ✅ sin call sites en dirs activos (feature 6 lo retiró completamente del flujo). |

`repositories/postgres/`:

| Archivo legacy | Reemplazo moderno |
|----------------|-------------------|
| `repositories/postgres/base.py:Base` | `shared/db/base.py:Base` (verificar si existe — `shared/db/orm.py` ya tiene la `Base` Alembic; `Base` legacy probablemente importable desde `shared.db.orm`). |
| `repositories/postgres/engine.py` (`get_engine`, `resolve_database_binding`, `verify_required_tables`, `describe_database_binding`) | `shared/db/engine.py` (`shared` ya tiene `engine.py` per §6 de §11 — verificar exports moderno equivale). Si falta `verify_required_tables` o `describe_database_binding`, `apps/api/readiness.py` los reimplementa con `sqlalchemy.inspect`. |
| `repositories/postgres/repository.py:PostgresRepositoryBase, now_iso` | `shared/db/repository_base.py:ModuleRepository, utcnow` — base class para los repos modernos. |
| `repositories/postgres/security.py:encrypt_text, decrypt_text` | `shared/db/security.py:encrypt_text, decrypt_text` (idéntica; ya importada por `tests/support/postgres.py:17`). |
| `repositories/postgres/session.py` (`create_session`, `CompatConnection`, `CompatRow`, `CompatResult`) | `shared/db/session.py:create_session` (los `Compat*` no se reusan: los repos modernos usan `Session.execute(text(...), params)` directo). |
| `repositories/postgres/uow.py:DatabaseUnitOfWork` | `shared/db/uow.py:DatabaseUnitOfWork` (namespaced, descrito en §7). |
| `repositories/postgres/models/__init__.py` (12 ORM models) | `shared/db/orm.py` (Alembic source of truth). Los modelos legacy **ya no reflejan el schema vivo** (tienen columnas `wordpress_source_id`, `site_id`, JSON-TEXT — todas migradas). No hay path moderno equivalente porque ningún código activo los lee. |

---

## 2. Call sites externos a actualizar

Sólo bajo dirs activos (`apps/`, `modules/`, `shared/`, `tests/`). Fuera
del alcance literal del acceptance pero **necesario para la cadena de
import** (§0.B.α/β):

| # | Archivo | Línea | Símbolo legacy | Reemplazo moderno | Nota |
|---|---------|------:|----------------|-------------------|------|
| 1 | `tests/unit/test_architecture_cleanup.py` | 12-15 | `DatabaseJobDispatcher`, `DatabaseUnitOfWork` (legacy), `PipelineStateStore`, `PropertyStore` | (n/a) | **Borrar el archivo entero** (R5). Los 3 tests son tautologías sobre símbolos legacy. |
| 2 | `tests/unit/test_tenancy.py` | 12-14 | `TenantResolver` (legacy de `application/tenancy/`), `DatabaseUnitOfWork` (legacy) | (n/a) | **Borrar el archivo entero** (R6). `TenantResolver` muere con feature 18. La resolución moderna ya está cubierta por `tests/integration/ingestion/test_wordpress_webhook_flow.py`. |
| 3 | `apps/api/main.py` | 82 | `from services.transport.http.operations import build_readiness_report` | `from apps.api.readiness import build_readiness_report` (nuevo módulo, Opción β). | El import lazy dentro de `_check`. Cambia path; resto idéntico. |
| 4 | `apps/api/health_router.py` | 13, 50, 115 | docstrings + `from services.transport.http.operations import build_readiness_report` (lazy en línea 115) | docstrings actualizados + `from apps.api.readiness import build_readiness_report` | Idem. |

Imports indirectos a través de dirs frozen (no se modifican en feature
17, mueren con feature 18):

- `application/bootstrap/runtime.py:5` — `DatabaseUnitOfWork` legacy.
- `application/bootstrap/__init__.py:5` — idem.
- `application/persistence.py:6-16` — 11 imports.
- `application/scripted_render/{__init__,service}.py:18` —
  `ScriptedVideoArtifactRecord`.
- `application/dispatch/database_dispatcher.py:385` (lazy) —
  `PropertyJobEnqueueRequest`.
- `services/transport/http/operations.py:23-33` — 6 imports.
- `services/publishing/social_delivery/description.py:7` —
  `PropertyReelRecord`.
- `services/media/reel_rendering/data.py:7` — `PropertyReelRecord`,
  `PropertyStore`.
- `repositories/postgres/uow.py:5` — `application.persistence.UnitOfWork`.

**Cuando se borre `repositories/`, todos esos archivos romperán al
import**. La pregunta es: ¿alguien los importa desde dirs activos? Para
esos 10 archivos en frozen, los call sites externos (Greps ya
realizados):

- `application/bootstrap/runtime.py` (post-16): consumido por
  `tests/test_social_publishing.py:18` (legacy 1 746 LoC, frozen),
  `modules/reels/application/orchestrator.py:246` (lazy, **dirs
  activos**) y `modules/reels/application/use_cases/render_scripted_video.py:23`
  (lazy, **dirs activos**). Los dos lazy imports lo invocan en runtime.
  Si `application/bootstrap/runtime.py` rompe al cargar, los tests del
  worker que ejecutan `RenderScriptedVideoUseCase.execute` o el path
  scripted_render lazy fallan. **Mitigación R3**: en feature 17 hay
  que arreglar `application/bootstrap/runtime.py` para que ya no
  importe `repositories.postgres.uow`. Dos sub-opciones:
  - **R3.a**: cambiar `application/bootstrap/runtime.py:5` a `from
    shared.db.uow import DatabaseUnitOfWork`. Mínimo, 1 LoC. Toca
    legacy (1 línea).
  - **R3.b**: borrar `application/bootstrap/{__init__.py,runtime.py}`
    y mover los 2 lazy callers a `from shared.db.uow import
    DatabaseUnitOfWork` directamente:
    - `modules/reels/application/use_cases/render_scripted_video.py:23-31`
      reemplaza la fábrica por `lambda: DatabaseUnitOfWork(...)`. Pero
      aquí **el problema más profundo es que `ScriptedVideoRenderService`
      (legacy `application/scripted_render/service.py:109`) consume el
      UoW vía atributos `unit_of_work.wordpress_source_store`,
      `unit_of_work.property_repository`, `unit_of_work.scripted_video_store`
      que el moderno NO expone**. Migrar `ScriptedVideoRenderService`
      al UoW moderno es ~30+ LoC en frozen y rompe la regla "no toca
      legacy". Por eso R3.a es preferible.
  - **Decisión recomendada (R3): R3.a** — 1 LoC en
    `application/bootstrap/{runtime,__init__}.py`, cambiar `from
    repositories.postgres.uow import DatabaseUnitOfWork` por `from
    shared.db.uow import DatabaseUnitOfWork`. Ojo: el `DatabaseUnitOfWork`
    moderno **NO tiene los atributos legacy** (`wordpress_source_store`,
    `property_repository`, etc.) — el lazy que devuelve la fábrica se
    pasa luego a `ScriptedVideoRenderService` que sí los espera. Con
    R3.a el scripted-render lazy **no funcionará en runtime**. Pero
    eso **NO es regresión**, porque hoy:
    - El test que cubre `scripted_render` end-to-end es
      `tests/integration/delivery/test_worker_dispatcher_flow.py:test_scripted_render_handler_processes_job`,
      que **stubbea** `ScriptedVideoRenderService.render_from_manifest`
      (impl_16 §1). Nunca toca el UoW real.
    - El servidor real de scripted_render hoy está deprecado (feature
      18 borra todo `application/scripted_render/`).
    - Para feature 17, lo único que importa es que `apps.worker
      --check` y `apps.api --check` no estallen en imports. R3.a
      cumple eso (los imports de `application/bootstrap/runtime.py` y
      `application/bootstrap/__init__.py` resuelven cleanly contra
      `shared.db.uow`).
  - **Alternativa R3.c (más limpia, requiere validación con leader)**:
    borrar `application/bootstrap/{runtime,__init__}.py` y
    `application/scripted_render/{__init__,service}.py` enteros en
    feature 17 (sólo si el rule §2 lo permite cuando es legacy
    huérfano). Justificación: tras eliminar las 2 lazy paths en
    `modules/reels/application/`, esos 4 archivos quedan sin call
    sites en dirs activos. Sólo `tests/test_social_publishing.py:18`
    los consume desde tests, **pero ese test ya está en frozen
    (`tests/test_*` no es target de update)**. El path real es: el
    test legacy tira de `application.bootstrap.runtime.build_default_social_property_publisher`,
    que sólo construye `GoHighLevelPropertyPublisher` (no usa UoW).
    Si R3.a se aplica, ese símbolo sigue funcionando.

  → **Resolución para feature 17: R3.a**. Limpieza total queda para
  feature 18.

- `application/persistence.py`: consumido sólo por `application/...`
  (frozen). No bloquea feature 17 — pero al borrar `repositories/`,
  `application/persistence.py:6-16` rompe. Por la misma lógica que
  R3.a, hay que arreglarlo o aceptar que `application/` en general no
  carga. **Test relevante**:
  `tests/test_social_publishing.py:18` carga
  `application.bootstrap.runtime` que NO importa
  `application.persistence` (verificado: §11 del read del archivo
  post-16). `application.persistence` lo importa
  `application.tenancy.resolver`, `application.scripted_render.{__init__,service}`,
  `application.dispatch.database_dispatcher`. Ninguno de esos se carga
  desde `tests/test_social_publishing.py`. **Pero**:
  `tests/unit/test_tenancy.py` SÍ carga `application.tenancy.resolver`
  → carga `application.persistence` → estalla. Con R6 (borrar
  `tests/unit/test_tenancy.py`), no hay caller activo.
  `tests/unit/test_architecture_cleanup.py` carga
  `application.dispatch.database_dispatcher` → carga
  `application.persistence` → estalla. Con R5 (borrar el archivo), no
  hay caller activo.

  → Tras R5+R6, **`application/persistence.py` no se carga desde
  ningún test**. Su import-time `from repositories.stores...` no daña
  el test suite. Se queda como código muerto importable hasta feature 18.

  Pero hay otro punto: `tests/unit/test_architecture_cleanup.py:48-73`
  hace `path.read_text()` sobre `application/`, `domain/`,
  `repositories/`, `services/`, `settings/` — eso **lee
  archivos**, no `import`s. Si el archivo borra, falla con
  `FileNotFoundError`. Otra razón para R5.

- `services/transport/http/operations.py`: consumido por
  `apps/api/main.py:82` y `apps/api/health_router.py:115` (lazy,
  ambos dentro de `_check` / `GET /health/details`). Mitigación con
  Opción β (§0.B): mover `build_readiness_report` a
  `apps/api/readiness.py` y reapuntar los 2 call sites. Tras eso,
  `services/transport/http/operations.py` queda sin call sites en
  `apps/`, sólo lo consumían ahí. **Acción concreta**: nuevo archivo
  `apps/api/readiness.py` (~250-300 LoC) que reimplementa
  `build_readiness_report` usando `shared.db.uow.DatabaseUnitOfWork`
  + `shared.db.engine.verify_required_tables` (o inline con
  `sqlalchemy.inspect`). El método `_ensure_database_writable` se
  reescribe abriendo `with DatabaseUnitOfWork(...) as uow: pass` y
  consultando `uow.catalog.properties.get_property_ids()` o similar
  como smoke check. (Alternativa más fina: smoke
  `with DatabaseUnitOfWork(...)` y asumir que abrir el UoW valida
  todos los repos).

- `services/publishing/social_delivery/description.py:7` y
  `services/media/reel_rendering/data.py:7`: importan
  `PropertyReelRecord` (dataclass) de `repositories.stores.property_store`.
  Consumidores en dirs activos:
  - `description.py` lo consume `services/publishing/social_delivery/post_copy.py`
    + `tests/test_social_publishing.py` (frozen). No `apps/modules/shared`.
  - `data.py` lo consume `services/media/reel_rendering/{__init__,manifest}.py`.
    `__init__.py` re-exporta para `services/media/reel_rendering`.
    Lo consumen `services/media/reel_rendering/runtime.py`,
    `application/scripted_render/service.py`, `application/scripted_render/__init__.py`.
    No `apps/modules/shared`.
  → **No bloquean feature 17**. `tests/` modernos no tocan esos
  caminos (cubiertos por mocks en `test_worker_dispatcher_flow`).

  Sí, al borrar `repositories/`, ambos archivos rompen import, lo que
  rompe carga transitiva de `services/media/reel_rendering/__init__.py`
  cuando algún test moderno lo toque (Grep `from services.media.reel_rendering`
  en `apps|modules|shared|tests` → varios hits, p. ej.
  `modules/rendering/infrastructure/runtime.py`,
  `modules/rendering/infrastructure/ffmpeg/render_reel.py`, tests
  unit/integration de rendering). Esto es **peligroso**.

  Mitigación: `services/media/reel_rendering/data.py` redefine
  internamente `PropertyReelRecord` (es una dataclass-only; no
  necesita los repos). Cambio mínimo: en `services/media/reel_rendering/data.py:7`,
  sustituir el import por la definición inline (copiada de
  `repositories.stores.property_store.PropertyReelRecord`, que a su
  vez vive en `modules/catalog/infrastructure/property_store_compat.py:88-121`).
  Análogo en `services/publishing/social_delivery/description.py:7`.
  Como ambos archivos están en frozen, esto toca legacy — pero es la
  única forma de mantener `pytest -q` verde tras borrar
  `repositories/`. **Decisión recomendada (R7)**: mover/inline la
  dataclass `PropertyReelRecord` a `modules/catalog/domain/property.py`
  (ya existe) o a un nuevo `shared/legacy_records.py` y hacer que los
  2 archivos de `services/` la importen de ahí. Toca 2 LoC en frozen,
  cumple §2 (legacy sin call sites se borra → el import legacy se
  reemplaza). Otra opción: redefinir inline en cada uno (4-30 LoC en
  cada uno). **Implementer decide entre R7.inline y R7.modules-domain
  durante la implementación.**

  Verificación adicional: ¿qué tests cargan
  `services/media/reel_rendering/data.py` en árbol moderno? Grep
  `from services.media.reel_rendering`:
  - `modules/rendering/infrastructure/runtime.py`,
    `modules/rendering/infrastructure/ffmpeg/render_reel.py`, etc.
    importan **submódulos específicos** (no `data.py` ni el
    `__init__`).
  - **No hay test moderno que cargue `data.py`**. El path de
    `__init__.py` re-exporta `PropertyRenderData` (no
    `PropertyReelRecord`), lee Grep en `__init__.py`. Verificar la
    lista de re-exports de `services/media/reel_rendering/__init__.py`
    durante implementación.

- `application/scripted_render/{__init__,service}.py:18`: importa
  `ScriptedVideoArtifactRecord` (dataclass). Mismo patrón que R7:
  redefinir inline o mover a `modules/reels/domain` /
  `shared/legacy_records.py`. **Pero**: ese archivo se carga sólo
  desde el lazy de `RenderScriptedVideoUseCase.execute:24`, que es
  stubeado en `tests/integration/delivery/test_worker_dispatcher_flow.py`.
  → La carga real ocurre sólo en producción. Tras feature 17 con R3.a,
  si la lazy chain real intenta importar `application.scripted_render.service`,
  el import `from repositories.stores.scripted_video_artifact_store
  import ScriptedVideoArtifactRecord` rompe. **Pero el test stub
  evita la cadena**, así que `pytest -q` verde.
  → Aceptación literal "pytest -q termina verde" se cumple sin tocar
  `application/scripted_render/`. La cadena real `production scripted
  render` queda rota hasta feature 18 — pero ese path no está en uso
  porque **(impl_16 §1)** el handler real depende de la stub. **R8**:
  no tocar `application/scripted_render/` en feature 17. Aceptable.
  Si el leader prefiere mantener producción funcional, R7 extendido a
  inline `ScriptedVideoArtifactRecord` resolvería sin tocar lógica.

- `application/dispatch/database_dispatcher.py:385`: import lazy
  dentro de un método. Sólo se carga si `application.dispatch.database_dispatcher`
  se carga, y eso sólo lo carga `tests/unit/test_architecture_cleanup.py:12`.
  Con R5, no hay caller activo.

---

## 3. Cambios en `modules/catalog/infrastructure/`

- **Borrar** `modules/catalog/infrastructure/property_store_compat.py`
  (278 LoC). Su único caller es
  `repositories/stores/property_store.py`, que se borra en esta
  feature. Otra mención: REFACTOR_STATUS.md:178 lo cita; actualizar
  ese párrafo (el doc lo edita feature 18, pero no es bloqueante).
- Resto de `modules/catalog/infrastructure/` (`orm.py`,
  `property_repository.py`) intacto.

---

## 4. Tests

### Tests legacy a borrar

| Archivo | LoC | Razón | Cobertura moderna equivalente |
|---------|----:|-------|-------------------------------|
| `tests/unit/test_architecture_cleanup.py` | 78 | 3 tests sobre símbolos legacy (`DatabaseJobDispatcher`, `DatabaseUnitOfWork` legacy, `PipelineStateStore`, `PropertyStore`). El test de "Grep legacy patterns" ya no aplica (las roots `repositories/`, `application/`, `domain/`, `services/` se borran). | `tests/integration/delivery/test_worker_dispatcher_flow.py` cubre el dispatcher real moderno; `shared/db/uow.py` es trivialmente verificable abriendo cualquier UoW. |
| `tests/unit/test_tenancy.py` | 73 | 3 tests sobre `TenantResolver` legacy (`application/tenancy/resolver.py`). | `tests/integration/ingestion/test_wordpress_webhook_flow.py` (feature 4) ejercita la resolución de tenant moderna vía `uow.ingestion.sources.get_by_kind_external_id`. |

Total a borrar: 2 archivos, 151 LoC.

### Tests modernos que ya cubren lo retirado

- `tests/integration/delivery/test_worker_dispatcher_flow.py` (feature
  16, 397 LoC) — `claim → handler → outbox` end-to-end usando
  `shared.db.uow.DatabaseUnitOfWork` y los 4 use cases reales.
- `tests/integration/test_worker_runtime.py` (149 LoC) — dispatcher
  smoke con handlers mock.
- `tests/integration/ingestion/test_wordpress_webhook_flow.py` —
  `IngestionSourceRepository.get_by_kind_external_id`.
- `tests/integration/reels/test_*.py` — los 4 use cases (ingest/prepare/persist/publish)
  cubren `uow.reels.{states,revisions}` y `uow.catalog.{properties,images}`.
- `tests/integration/tenancy/test_admin_agencies_router.py`,
  `tests/integration/configuration/`, `tests/integration/publishing/`,
  `tests/integration/ingestion/` — cubren los namespaces UoW
  correspondientes.

### Tests nuevos que feature 17 introduce

- Si se aplica Opción β (§0.B), `tests/unit/apps_api/test_readiness.py`
  con casos: ready=true (DB writable, ffmpeg present, font present, …),
  ready=false (DB no migrada → `missing_tables` en context), ready=false
  (storage no writable). Patrón ya en `tests/unit/apps_api/`.
  **Estimación**: 80-150 LoC.
- Opcional: `tests/unit/test_repositories_dir_absent.py` — un único
  test que `assert not (APPLICATION_ROOT / "repositories").exists()`.
  Bloquea futuras regresiones. **Estimación**: 20 LoC.

---

## 5. Riesgos / acoplamientos

### R1 — `application/bootstrap/runtime.py:5` y `__init__.py:5`

Ambos importan `from repositories.postgres.uow import DatabaseUnitOfWork`.
Tras borrar `repositories/`, esos archivos rompen al importar. Aplicar
**R3.a** (cambiar 1 LoC en cada uno a `from shared.db.uow import
DatabaseUnitOfWork`). El moderno tiene firma `(database_locator,
base_dir)`-compatible (kwargs opcionales). El factory que devuelve
`build_runtime_unit_of_work_factory(workspace_dir, *, database_locator)`
sigue funcionando con el moderno. *Riesgo residual*: el lazy chain
`RenderScriptedVideoUseCase.execute → ScriptedVideoRenderService` usa
atributos `unit_of_work.wordpress_source_store`,
`unit_of_work.property_repository`, `unit_of_work.scripted_video_store`
que el moderno NO expone. **No estalla en pytest** (el test stub
salta), pero rompe producción. Aceptable hasta feature 18.

### R2 — `services/transport/http/operations.py` no se puede ejecutar

El `_check` de API hoy abre 6 stores legacy. Aplicar **Opción β**:
nuevo `apps/api/readiness.py` con la misma firma, cambiar 2 imports
en `apps/api/{main,health_router}.py`. *Riesgo*: la nueva
implementación debe replicar fielmente las claves del dict de retorno
(`ready`, `production_ready`, `checks`, `capabilities`, `errors`,
`warnings`, `failures`, `environment`) — los tests de
`tests/integration/apps_api/test_health_router.py` y
`tests/integration/apps_api/test_main_check.py` (si existen)
verifican algunas. Implementer debe leer esos tests antes de tocar.

### R3 — `services/media/reel_rendering/data.py` y `services/publishing/social_delivery/description.py` rompen import

Importan `PropertyReelRecord` de `repositories.stores.property_store`.
Aplicar **R7**: redefinir `PropertyReelRecord` inline en cada archivo
(es una dataclass cerrada, ~33 fields). 2 archivos en frozen, ~30 LoC
añadidos cada uno. Toca legacy pero el rule §2 lo permite porque el
import legacy se queda sin call site al borrar `repositories/`. La
cadena moderna no consume `data.py` ni `description.py` (verificado
con Grep), pero el `__init__.py` de `services/media/reel_rendering`
podría re-exportar. **Verificar** durante implementación.

### R4 — Borrar `modules/catalog/infrastructure/property_store_compat.py` antes de borrar `repositories/stores/property_store.py`

El compat es importado por property_store. Si el implementer borra el
compat antes que property_store, hay un breve estado intermedio
inconsistente (en sesión sin commits, no afecta git, pero puede
afectar pytest si se ejecuta a media migración). **Plan ordenado**:
borrar `repositories/` PRIMERO (un solo `rm -rf` recursivo), luego
borrar el compat. O al revés (borrar compat → property_store falla →
borrar property_store junto con el resto). **Estado intermedio NO
existe** porque ambas borradas están en la misma feature.

### R5 — Schema columns: ¿se persisten igual?

Renames críticos verificados (Alembic ya migró):
- `properties.site_id` → `properties.external_source_id`.
- `properties.wordpress_source_id` → `properties.ingestion_source_id`.
- `wordpress_sources` → `ingestion_sources(kind="wordpress")`.
- `property_pipeline_state` → `reels`.
- `job_queue` → `jobs`.
- `ghl_connections` → `provider_connections(provider="gohighlevel")`.
- `reel_profiles` → 5 tablas tipadas (`agency_brand_settings`,
  `agency_reel_defaults`, `agency_automation_rules`,
  `agency_social_templates`, `agency_music_tracks`).
- TEXT-JSON columns → `jsonb`.

`repositories/postgres/models/__init__.py` tiene los **mappings
legacy** (con nombres viejos). Como ningún código activo lee esos
mappings (`shared/db/orm.py` es el source-of-truth Alembic), borrarlos
no afecta. *Verificar*: que `verify_required_tables` con la lista de
`tests/support/postgres.ACTIVE_TABLES` (las 17 tablas modernas) no
falla post-feature.

### R6 — Diferencias de comportamiento store legacy vs repo moderno

Stores legacy heredan de `PostgresRepositoryBase`, que en `__exit__`
**hace su propio commit** (cuando `_owns_connection=True`,
`repository.py:31-35`). Modern repos NO commit — el commit es
responsabilidad del UoW. Esto se traduce en:

- Legacy: cada `with PropertyStore(...) as store:` hace un commit por
  defecto. Útil para smoke-test independiente, contraproducente en
  un `with DatabaseUnitOfWork(...)` (commit doble). El UoW legacy
  pasa `connection=self.connection` para evitar el doble commit
  (`uow.py:48-93`).
- Moderno: el UoW moderno hace 1 commit (`__exit__` happy path,
  `uow.py:172`). Repos no llaman `session.commit()` jamás.

Comportamiento **equivalente** desde el punto de vista de un caller
externo correcto, pero un test que abriera un `PropertyStore` directo
podría asumir auto-commit; tras la migración debe pasar por el UoW.
Los 2 tests legacy (R5, R6) los borramos, así que no aplica.

### R7 — `TenantResolver` legacy tras borrar `tests/unit/test_tenancy.py`

`application/tenancy/resolver.py` queda sin caller en dirs activos.
Sigue cargado por la cadena `application.bootstrap.runtime`? No —
verificado: `bootstrap/runtime.py` no importa `application.tenancy`.
**Sin riesgo**.

### R8 — `application/persistence.py` Protocol class

`application/persistence.UnitOfWork` Protocol declara los 11
atributos legacy. El UoW moderno **NO los expone**. Si algún call
site externo (en frozen) hace `assert isinstance(uow, UnitOfWork)`
(Protocol con runtime_checkable?), fallaría. Verificación rápida:
`Grep "isinstance.*UnitOfWork"` en repo:

- No hay hits (Protocol no es runtime_checkable). **Sin riesgo
  estructural**.

### R9 — `python -m apps.worker --check` exit 0

Worker `--check` (`apps/worker/main.py:54-74`) llama
`build_default_dispatcher(settings=settings)` que importa
`apps/worker/runtime.py` que importa `modules/reels/application/orchestrator.py`.
El orquestador post-16 (272 LoC) tiene un solo lazy import a
`application.bootstrap.runtime.build_default_social_property_publisher`
en `_build_default_social_property_publisher` (orchestrator.py:246).
Se invoca dentro de `__init__` de `_LocalArtifactsPublisher` (impl_16
§2-§5). **Si se invoca al construir el dispatcher en `--check`**,
estalla por la cadena `application.bootstrap.runtime → repositories.postgres.uow`.

Verificar con implementer:
- `apps/worker/runtime.py:259-279` registra `ReelPipeline()` en el
  dispatcher. ¿`ReelPipeline.__init__` invoca el lazy?
  Verificación adicional necesaria leyendo el `__init__` post-impl_16
  íntegro.

Si SÍ, R3.a no es suficiente — el `--check` rompe. Mitigación: el
import lazy ya está condicionado a "primer uso" (post-impl_16 hace el
lazy dentro de `_build_default_social_property_publisher` lambda
helper, no en `__init__`). **Si está bien diseñado, `--check` no
fuerza el lazy**. Implementer verifica.

### R10 — `tests/test_social_publishing.py` (legacy 1 746 LoC)

Carga `application.bootstrap.runtime.build_default_social_property_publisher`
en `:18`. Esa función vive en `application/bootstrap/runtime.py`. Tras
R3.a, el archivo importa `shared.db.uow.DatabaseUnitOfWork` correctamente
y `build_default_social_property_publisher` no usa el UoW (sólo
construye `GoHighLevelPropertyPublisher`). **Test sigue pasando**.
Sin riesgo.

### R11 — `repositories/postgres/security.py` y `tests/support/postgres.py`

`tests/support/postgres.py:17` ya importa `shared.db.security.encrypt_text`
(no la copia legacy). **Sin acción necesaria**.

---

## 6. Plan de implementación recomendado

### Pre-feature

Verificar 461 tests verdes (baseline post-16; `impl_16:393` lo
confirma).

### Orden de cambios

1. **Tocar `apps/api/`** (Opción β, §0.B):
   - Crear `apps/api/readiness.py` (~250-300 LoC, módulo nuevo). Reescritura
     de `services/transport/http/operations.build_readiness_report`
     usando `shared.db.{uow,engine,session}`.
   - Editar `apps/api/main.py:82` → `from apps.api.readiness import
     build_readiness_report`.
   - Editar `apps/api/health_router.py:13, 50, 115` → idem (docstrings
     + lazy import).
   - Crear `tests/unit/apps_api/test_readiness.py` (~80-150 LoC).
2. **Tocar `application/bootstrap/`** (R3.a, 1 LoC × 2):
   - `application/bootstrap/runtime.py:5` → `from shared.db.uow import
     DatabaseUnitOfWork`.
   - `application/bootstrap/__init__.py:5` → idem (mantener byte-igual).
3. **Tocar `services/`** (R7) — sólo si los tests modernos cargan los
   archivos:
   - `services/media/reel_rendering/data.py:7` → redefinir
     `PropertyReelRecord` inline.
   - `services/publishing/social_delivery/description.py:7` → idem.
   - **Saltarse paso si Grep confirma que ningún test moderno carga
     esos archivos** (probablemente skipable; el implementer
     verifica).
4. **Borrar tests legacy**:
   - `tests/unit/test_architecture_cleanup.py` (78 LoC).
   - `tests/unit/test_tenancy.py` (73 LoC).
5. **Borrar el compat module y `repositories/`**:
   - `modules/catalog/infrastructure/property_store_compat.py` (278 LoC).
   - `rm -rf repositories/` entero (3 610 LoC).
6. **Verificar acceptance**:
   - `Grep "from repositories\.|import repositories" apps modules
     shared tests` → 0 hits.
   - `pytest -q` verde.
   - `python -m apps.api --check` exit 0.
   - `python -m apps.worker --check` exit 0.
7. **Actualizar feature_list.json**: status feature 17 →
   `in_progress` (y luego `done` por cierre).

### Archivos creados (3-4)

- `apps/api/readiness.py` (~250-300 LoC).
- `tests/unit/apps_api/test_readiness.py` (~80-150 LoC).
- (Opcional) `tests/unit/test_repositories_dir_absent.py` (~20 LoC).
- `progress/impl_17_*.md` (no es código).

### Archivos modificados (2-4)

- `apps/api/main.py` (1 LoC).
- `apps/api/health_router.py` (1-3 LoC, docstrings + 1 import).
- `application/bootstrap/runtime.py` (1 LoC).
- `application/bootstrap/__init__.py` (1 LoC).
- (Opcional) `services/media/reel_rendering/data.py`,
  `services/publishing/social_delivery/description.py`.

### Archivos borrados (15)

- `repositories/postgres/__init__.py` (3).
- `repositories/postgres/base.py` (10).
- `repositories/postgres/engine.py` (97).
- `repositories/postgres/repository.py` (41).
- `repositories/postgres/security.py` (25).
- `repositories/postgres/session.py` (130).
- `repositories/postgres/uow.py` (140).
- `repositories/postgres/models/__init__.py` (366).
- `repositories/stores/__init__.py` (0).
- `repositories/stores/agency_store.py` (215).
- `repositories/stores/ghl_connection_store.py` (278).
- `repositories/stores/job_queue_store.py` (412).
- `repositories/stores/media_revision_store.py` (183).
- `repositories/stores/outbox_event_store.py` (217).
- `repositories/stores/pipeline_state_store.py` (431).
- `repositories/stores/property_store.py` (464).
- `repositories/stores/reel_profile_store.py` (347).
- `repositories/stores/scripted_video_artifact_store.py` (195).
- `repositories/stores/webhook_event_store.py` (143).
- `repositories/stores/wordpress_source_store.py` (279).
- `modules/catalog/infrastructure/property_store_compat.py` (278).
- `tests/unit/test_architecture_cleanup.py` (78).
- `tests/unit/test_tenancy.py` (73).

**Total LoC neto**: -4 117 LoC borrados, +330-470 LoC en
`apps/api/readiness.py` + tests + (opcional R7 inline) ≈ **-3 600 a
-3 800 LoC**.

### Tests esperados post-feature

- 461 → ~462-465 verdes (mantenidos los 461 actuales menos los 6 de
  los 2 archivos borrados, +3-7 nuevos en `test_readiness.py`).

---

## 7. Discrepancias detectadas

1. **"Migrar los call sites restantes de repositories/stores/ a
   uow.catalog.* y uow.reels.*"** (acceptance literal). En realidad,
   bajo `apps/`, `modules/`, `shared/`, `tests/` **NO hay call sites
   de `repositories/stores/`**. Los hits son sólo en frozen. Los 2
   tests bajo `tests/unit/` consumen `repositories.postgres.uow`
   (legacy `DatabaseUnitOfWork`) — no `repositories.stores.*`. La
   migración real se concentra en (a) borrar 2 tests legacy, (b)
   romper la cadena lazy `apps/api/main.py → services/transport/http/operations.py → repositories/`,
   (c) cambiar 1 LoC en `application/bootstrap/runtime.py` para que
   `repositories/` se pueda eliminar sin romper la cadena lazy del
   worker. La frase "uow.catalog.* y uow.reels.*" del acceptance
   literal es **misleading** — el cambio principal usa
   `shared.db.uow` en el `apps/api/readiness.py` nuevo y en
   `application/bootstrap/runtime.py`.

2. **`feature_list.json:340`** describe la feature como "migrar call
   sites" pero la realidad post-features-2-16 es que el grueso del
   trabajo es **demolición** (3 600+ LoC de borrados). El
   `phase_2_operating_rules.md:54-56` ya lo anticipaba: *"La feature
   17 deja de tener trabajo conforme las features 2-8 limpian a su
   paso."* — efectivamente, las features 2-7 borraron los call sites
   activos; feature 17 sólo cierra y purga.

3. **`apps/worker/main.py --check`** (acceptance) requiere que el
   import-time de `apps.worker.runtime` no fuerce el lazy de
   `application.bootstrap.runtime`. **Verificación pendiente** del
   implementer: que `ReelPipeline.__init__` (post-impl_16) **NO**
   llame a `_build_default_social_property_publisher` desde
   `__init__` (sólo desde `handle`). Si lo llama desde `__init__`,
   R3.a no basta y hay que hacer R3.b. Implementer debe leer
   `modules/reels/application/orchestrator.py` íntegro (272 LoC) y
   confirmar.

4. **`shared/db/engine.py`**: he asumido que existe y expone
   `verify_required_tables` (paralelo al legacy). El `wc -l` de
   `shared/db/` muestra `engine.py` pero no he leído su contenido.
   **Implementer verifica**: si no expone `verify_required_tables`,
   el `apps/api/readiness.py` lo reimplementa con `inspect(engine)`
   directo (5-10 LoC inline).

5. **`services/transport/http/operations.run_startup_checks`**: además
   de `build_readiness_report`, el archivo expone `run_startup_checks`,
   `cleanup_stale_staging_directories`, `ensure_runtime_is_supported`.
   `Grep run_startup_checks` no se realizó exhaustivamente —
   implementer confirma si `apps/api/main.py:174` u otros caminos
   activos lo invocan. Si sí, también debe migrar a
   `apps/api/readiness.py` o equivalente.

6. **`repositories/postgres/security.py` vs `shared/db/security.py`**:
   asumo que son **byte-iguales** (mismo Fernet, mismo `DATABASE_ENCRYPTION_KEY`).
   He leído ambos; firmas idénticas. Implementer debería hacer `diff`
   antes de borrar para confirmar (precaución).

7. **`repositories/postgres/models/__init__.py:366` vs
   `shared/db/orm.py`**: estos 12 ORM models son **legacy**, ya no
   reflejan el schema vivo. Borrarlos no afecta migraciones (Alembic
   lee `shared/db/orm.py`). Verificación rápida: `Grep
   "from repositories.postgres.models"` en repo → sólo 1 hit (el
   propio `engine.py:18` `from repositories.postgres import models as
   _models  # noqa: F401`). Cero call sites externos.

8. **`tests/test_social_publishing.py` (legacy 1 746 LoC)**: usa
   `application.bootstrap.runtime.build_default_social_property_publisher`.
   Tras R3.a, ese símbolo sigue funcionando (no usa el UoW). **No
   bloquea feature 17**. Pero su existencia (1 746 LoC frozen) es
   deuda enorme; feature 18 lo borra entero o lo migra. Out-of-scope.
