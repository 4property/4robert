# Explore — Feature 7 `reels_admin_router`

> **Read-only**. No code changes. Mapeo para que el implementer extraiga el
> router `/admin/agencies/{id}/reels/*` a
> `modules/reels/transport/http/admin_reels_router.py`, con use cases finos
> `list_reels`, `get_reel_detail`, `regenerate_reel`.

---

## 0. Aclaración terminológica importante

`feature_list.json` (id=7, líneas 124-139) describe la feature como
"listado/detalle/**regeneración**". En el código actual NO existe ningún
endpoint cuyo verbo sea "regenerate" (`grep regenerat` en `services/transport/http/server.py`
devuelve cero matches). El handler que **encola un publish job re-usando la
payload ingerida** es `POST .../approve` (`services/transport/http/server.py:3241-3323`),
implementado por `WordPressWebhookApplication.enqueue_reel_publish`
(`services/transport/http/server.py:1118-1190`).

Interpretación recomendada para el implementer:

- `regenerate_reel` ≡ el flujo de "approve" actual: idempotente, **encola un
  job `kind=reel_publish`** desde la WordPress payload almacenada y NO ejecuta
  inline. Ya cumple la regla "solo encola job, no ejecuta inline" exigida por
  feature 7.
- En la práctica, `approve` y `reject` (handlers gemelos) se mueven juntos al
  router admin de reels. Si el leader solo quiere los tres explícitos
  (list/detail/regenerate), `reject` queda fuera de scope y se documenta como
  pendiente. **Recomendación**: mover los dos juntos para no dejar el router
  origen incoherente.

---

## 1. Rutas y handlers en `services/transport/http/server.py`

Todas viven dentro de `WordPressWebhookServer._configure_routes` (sección
"Admin · Content", banner en línea 2889-2893). El prefijo dinámico es
`f"{application.admin_access_policy.base_path}/agencies/{{agency_id}}/reels"`
y `admin_access_policy.base_path` resuelve a `/v1/admin` (defecto) — i.e.
los paths reales son `/v1/admin/agencies/{agency_id}/reels/*`.

Auth: **todos** los handlers llaman `_authorize_admin_request(request, runtime)`
al inicio (helper en `services/transport/http/server.py:4197-4202`).

Body: ninguno de los reel handlers acepta body.

### 1.1 `GET /v1/admin/agencies/{agency_id}/reels`

- **Líneas**: `services/transport/http/server.py:2894-2933`
- **Handler**: `list_admin_agency_reels`
- **Path params**: `agency_id: str`
- **Query params**: `limit: int` (default 50, parseado defensivamente, ver
  línea 2922-2925)
- **Deps runtime**: `runtime.get_agency`, `runtime.list_agency_reels`,
  `_serialize_agency_reel`
- **Output**: `{"items": [...], "count": N}`
- **404 codes**: `ADMIN_AGENCY_NOT_FOUND`
- **Use case mapeado**: `list_reels`

### 1.2 `GET /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}`

- **Líneas**: `services/transport/http/server.py:2935-2993`
- **Handler**: `get_admin_agency_reel`
- **Path params**: `agency_id: str`, `site_id: str`, `source_property_id: int`
- **Body**: ninguno
- **Deps runtime**: `runtime.get_agency`,
  `runtime.get_agency_reel_detail`, `runtime.resolve_reel_video_path`,
  `_serialize_agency_reel`
- **Output**: `{"reel": {...con has_video, video_url}}`
- **404 codes**: `ADMIN_AGENCY_NOT_FOUND`, `ADMIN_REEL_NOT_FOUND`
- **Use case mapeado**: `get_reel_detail`

### 1.3 `GET /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/video`

- **Líneas**: `services/transport/http/server.py:2995-3040`
- **Handler**: `stream_admin_agency_reel_video`
- **Path params**: idénticos a 1.2
- **Deps runtime**: `runtime.resolve_reel_video_path`,
  `_build_range_response` (que es `apps.api.range_response.build_range_response`)
- **404 code**: `ADMIN_REEL_VIDEO_NOT_FOUND`
- **No es un use case "puro"** — solo lectura de fichero. Puede vivir en el
  router como helper de transport (consume `apps.api.range_response`).

### 1.4 `GET /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/images`

- **Líneas**: `services/transport/http/server.py:3042-3110`
- **Handler**: `list_admin_agency_reel_images`
- **Deps runtime**: `runtime.get_agency`,
  `runtime.list_reel_property_images`, `runtime.resolve_property_image_path`
- **404 code**: `ADMIN_AGENCY_NOT_FOUND`
- Construye URLs `/v1/admin/agencies/{a}/reels/{s}/{p}/images/{pos}/file`.

### 1.5 `GET /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/images/{position}/file`

- **Líneas**: `services/transport/http/server.py:3112-3166`
- **Handler**: `stream_admin_agency_reel_image`
- **Deps runtime**: `runtime.resolve_property_image_path`,
  `_guess_image_mime_type` (`services/transport/http/server.py:4019-4031`),
  `StreamingResponse`
- **404 code**: `ADMIN_REEL_IMAGE_NOT_FOUND`

### 1.6 `GET /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/manifest`

- **Líneas**: `services/transport/http/server.py:3168-3239`
- **Handler**: `get_admin_agency_reel_manifest`
- **Deps runtime**: `runtime.get_agency`, `runtime.resolve_reel_manifest_path`,
  `runtime.workspace_dir`, lectura `path.read_text()` + `json.loads()`
- **404/500 codes**: `ADMIN_AGENCY_NOT_FOUND`,
  `ADMIN_REEL_MANIFEST_NOT_FOUND`, `ADMIN_REEL_MANIFEST_READ_FAILED`

### 1.7 `POST /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/approve` ← **mapea a `regenerate_reel`**

- **Líneas**: `services/transport/http/server.py:3241-3323`
- **Handler**: `approve_admin_agency_reel`
- **Path params**: `agency_id: str`, `site_id: str`, `source_property_id: int`
- **Body**: ninguno
- **Deps runtime**: `runtime.get_agency`, `runtime.update_reel_workflow`
  (cambia `workflow_state='approved'` + `publish_status='pending_publish'`),
  `runtime.enqueue_reel_publish`, `_serialize_agency_reel`
- **Comportamiento HOY**: **YA SOLO ENCOLA JOB, NO EJECUTA INLINE**.
  Concretamente:
  1. Marca el reel en `workflow_state=approved` (write síncrono via UoW).
  2. Llama `enqueue_reel_publish` que:
     - Lee `properties.raw_payload` (JSON).
     - Resuelve la GHL connection y el `reel_profile`.
     - Construye un `SocialPublishContext` con `approval_required=False`.
     - Llama `acceptance_service.accept_delivery(...)`, que internamente hace
       `unit_of_work.job_queue_store.enqueue_job(PropertyJobEnqueueRequest(...))`.
       Implementación canónica del kind: `reel_publish` (ver job_repository).
  3. Devuelve 200 con `{status: 'approved', publish_enqueued: true|false,
     event_id, job_id, reel}` o 404 si el reel no existe.
- **404 codes**: `ADMIN_AGENCY_NOT_FOUND`, `ADMIN_REEL_NOT_FOUND`
- **Idempotencia**: la cola garantiza supersede de jobs queued previos para el
  mismo `(site_id, property_id)` via
  `unit_of_work.job_queue_store.supersede_queued_jobs` (ver
  `application/dispatch/webhook_acceptance.py:64-75`).

### 1.8 `POST /v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/reject`

- **Líneas**: `services/transport/http/server.py:3325-3373`
- **Handler**: `reject_admin_agency_reel`
- Setea `workflow_state='rejected'`, `publish_status='rejected'`. **No
  encola nada**. Si el implementer quiere mantenerlo, vive cómodamente al
  lado de `regenerate_reel` como otro use case fino `reject_reel` (no está
  pedido en feature 7 explícitamente).

### Resumen de paths

| Método | Path                                                                                          | Líneas       |
|--------|-----------------------------------------------------------------------------------------------|--------------|
| GET    | `/v1/admin/agencies/{agency_id}/reels`                                                        | 2894-2933    |
| GET    | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}`                         | 2935-2993    |
| GET    | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/video`                   | 2995-3040    |
| GET    | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/images`                  | 3042-3110    |
| GET    | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/images/{position}/file`  | 3112-3166    |
| GET    | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/manifest`                | 3168-3239    |
| POST   | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/approve` (≡ regenerate)  | 3241-3323    |
| POST   | `/v1/admin/agencies/{agency_id}/reels/{site_id}/{source_property_id}/reject`                  | 3325-3373    |

---

## 2. Repositorios de reels

Toda la persistencia de la BC `reels` ya está en `modules/reels/infrastructure/`
y expuesta por el UoW (`shared/db/uow.py:84-88`):

- `modules.reels.infrastructure.reel_state_repository.ReelStateRepository`
  — aggregate `reels` (workflow_state, publish_status, render_status,
  current_revision_id, etc.). Métodos relevantes:
  - `get(*, external_source_id, source_property_id)` — `reel_state_repository.py:100-114`.
  - `update_workflow_state(...)` — `reel_state_repository.py:233-280`.
  - `update_publish_status(...)` — `reel_state_repository.py:183-231`.
  - `save_local_artifacts(...)` — `reel_state_repository.py:282-350`.

- `modules.reels.infrastructure.media_revision_repository.MediaRevisionRepository`
  — append-only `media_revisions`. `media_revision_repository.py:43+`.

- **`modules.reels.infrastructure.reel_query.ReelQuery`** — read-only JOIN
  reader sobre `properties + reels + media_revisions`. **Es la pieza clave
  para list/detail.** `modules/reels/infrastructure/reel_query.py:156-336`.
  - `list_recent_for_agency(*, agency_id, limit) -> tuple[AgencyReelSummary, ...]`
    — line `reel_query.py:160-232`. Devuelve la fila aplanada que el handler
    actual serializa por `_serialize_agency_reel`.
  - `get_property_reel_record(...) -> PropertyReelRecord | None` —
    line `reel_query.py:234-333` (no se usa hoy en server.py, pero vale para
    detail).

- `modules.reels.infrastructure.scripted_video_artifact_repository.ScriptedVideoArtifactRepository` — irrelevante para feature 7.

**El UoW expone estos como**:

```
uow.reels.queries          # ReelQuery
uow.reels.states           # ReelStateRepository
uow.reels.revisions        # MediaRevisionRepository
uow.reels.scripted_artifacts
```

Y, fuera del módulo reels pero necesarios para los handlers:

- `uow.tenancy.agencies` — para verificar `agency_id` existe
  (`runtime.get_agency` actual).
- `uow.catalog.properties` — para `list_property_images` y
  `get_property_raw_payload` (ambos métodos están hoy en
  `unit_of_work.property_repository`, ver `services/transport/http/server.py:1138`,
  `:1198-1202`). Verificar en `modules/catalog/infrastructure/property_repository.py`
  que existen los equivalentes en el UoW nuevo.
- `uow.delivery.jobs` — `JobRepository.enqueue_job(JobEnqueueRequest)`,
  ver `modules/delivery/infrastructure/job_repository.py:84-127`.
- `uow.delivery.webhook_events` — para escribir el WebhookEvent paralelo (lo
  hace `WebhookAcceptanceService.accept_delivery`).
- `uow.publishing.connections` — para resolver la GHL connection en regenerate.
- `uow.configuration.defaults` o `automation` — para el reel_profile (hoy
  `runtime.get_reel_profile`).

> **Riesgo**: el handler hoy lee `unit_of_work.property_repository`
> (UoW legacy). El implementer tendrá que pasar a `uow.catalog.properties`
> y verificar que ese repo nuevo expone `get_property_raw_payload`,
> `list_property_images`, `list_recent_for_agency`. Ver §11 y §7.

---

## 3. Use cases sugeridos

Patrón canónico (ver `modules/reels/application/use_cases/render_scripted_video.py`
y `modules/publishing/application/use_cases/decode_gohighlevel_session.py`):
clase `<Verb><Resource>UseCase` con `__init__` recibiendo dependencias
inyectadas y `execute(...)` que abre/usa el UoW y devuelve un dataclass o
mapping. Sin SQLAlchemy, sin FastAPI.

### 3.1 `list_reels` — `modules/reels/application/use_cases/list_reels.py`

- **Inputs**:
  - `agency_id: str`
  - `limit: int` (default 50, clamp interno 1..500 ya en `ReelQuery`)
  - (futuro) sort/filter por `workflow_state`, `publish_status` —
    HOY no hay filtros. La query base sólo ordena por
    `r.updated_at DESC NULLS LAST, p.fetched_at DESC NULLS LAST` (línea
    `reel_query.py:191`). Se puede dejar abierto via parámetro opcional.
- **Output**: `tuple[AgencyReelSummary, ...]` (el dataclass ya existe en
  `modules/reels/infrastructure/reel_query.py:52-79`).
- **Implementación**: 1 línea —
  `uow.reels.queries.list_recent_for_agency(agency_id=..., limit=...)`.
- **Errores**: ninguno hoy. Si se quiere `ResourceNotFoundError` cuando
  `agency_id` no existe, el use case necesita acceso a `uow.tenancy.agencies`.
  La práctica actual (server.py:2913) es 404 explícito desde el transport
  ANTES de llamar al use case, así que `list_reels` puede asumir agency
  válida.
- **Nota arquitectónica**: `AgencyReelSummary` vive en `infrastructure/`
  pero por ARCHITECTURE.md (línea 60-68) los use cases pueden importarlo
  porque `application` puede usar `infrastructure` del **mismo** módulo.
  Si se quiere puro, mover el dataclass a `domain/reel_summary.py`. No es
  bloqueante para feature 7; recomiendo dejarlo donde está.

### 3.2 `get_reel_detail` — `modules/reels/application/use_cases/get_reel_detail.py`

- **Inputs**: `agency_id`, `site_id` (= `external_source_id` tras Phase 1),
  `source_property_id`.
- **Output**: dataclass `ReelDetail` con los campos de
  `AgencyReelSummary` + path resuelto del video (absoluto o `None`) + flag
  `has_video` + URL relativa para video. El uso de `video_url` lo construye
  hoy el transport en `server.py:2987-2992`; recomiendo dejar **el cómputo
  de URL en el transport** (no entra al use case) y devolver solo
  `video_path: Path | None`. Sigue la convención: el use case no conoce el
  prefijo HTTP.
- **Implementación**:
  1. `uow.reels.queries.list_recent_for_agency(agency_id, limit=500)` y
     filtrar por `(site_id, source_property_id)` — réplica del cuerpo de
     `WordPressWebhookApplication.get_agency_reel_detail`
     (`services/transport/http/server.py:1071-1090`).
     **Mejora**: añadir un método dedicado a `ReelQuery`,
     `get_for_property(*, agency_id, external_source_id, source_property_id)`,
     para no recorrer 500 filas. Es opcional para esta feature; el
     comportamiento actual es lo suficiente y mantiene el cambio mínimo.
  2. Resolver el path del video (lógica en `server.py:1092-1116`).
- **Detalle incluido HOY**: media revision actual (path media + path metadata
  + artifact_kind + created_at), workflow_state, publish_status, render_status,
  last_published_provider_external_id, current_revision_id,
  pipeline_(created_at|updated_at), property metadata (title, link, price,
  bedrooms, bathrooms, agente, featured_image_url, etc).
- **NO incluye HOY**: assets (las imágenes se consultan en otro endpoint),
  outbox events, manifest contents. Ver endpoints separados §1.4-1.6.

### 3.3 `regenerate_reel` — `modules/reels/application/use_cases/regenerate_reel.py`

> **CRITICAL**: solo encola job, no ejecuta inline. Coincide con lo que ya
> hace `enqueue_reel_publish` hoy.

- **Inputs**: `agency_id`, `site_id`, `source_property_id`.
- **Output**: dataclass `RegenerateReelResult` con: `event_id`, `job_id`,
  `accepted: bool`, `reason: str | None` (e.g.
  `"PUBLISH_PREREQUISITES_MISSING"` cuando no hay raw payload o no hay GHL
  connection). El reel actualizado lo recupera el transport del use case
  para serializarlo, o se incluye en el dataclass como `reel_summary`.
- **Job kind**: `reel_publish` (string literal — ver §4).
- **Payload exacto** (lo construye hoy `enqueue_reel_publish`,
  `server.py:1118-1190`):
  - `payload`: la WordPress `raw_payload` deserializada en dict (de
    `properties.raw_payload`).
  - `publish_context`: `SocialPublishContext` con
    - `provider="gohighlevel"`,
    - `location_id` y `access_token` de `provider_connections` (resuelto
      via `uow.publishing.connections.get_with_secrets`),
    - `platforms` desde `reel_profile.platforms`
      (fallback `SOCIAL_PUBLISHING_DEFAULT_PLATFORMS`),
    - `approval_required=False` (forzado: el "approve" significa
      "renderizar+publicar sin pedir más permiso"),
    - `social_templates`.
  - `raw_payload_hash`: `sha256(raw_payload.encode("utf-8")).hexdigest()`.
  - `max_attempts`: viene de `WORKER_JOB_MAX_ATTEMPTS` (settings).
  - `available_at`, `created_at`: `now()` ISO.
  - `agency_id`, `ingestion_source_id`: del `tenant_resolver` (HOY) o
    directamente de `properties.agency_id / ingestion_source_id` (mejor con
    UoW directo).
- **Idempotencia**:
  - Antes del INSERT en `jobs`,
    `JobRepository.supersede_queued_jobs(site_id, property_id, superseded_by_job_id)`
    marca todos los jobs `queued` previos para el mismo
    `(external_source_id, property_id)` como `superseded`. Comportamiento
    encarnado hoy en `application/dispatch/webhook_acceptance.py:64-75`. El
    implementer debe replicar este patrón usando `uow.delivery.jobs` (verificar
    en `modules/delivery/infrastructure/job_repository.py` que el método
    existe; si no, añadirlo).
  - **Pre-condición opcional**: marcar `workflow_state='approved'` y
    `publish_status='pending_publish'` antes de encolar (lo hace hoy
    `update_reel_workflow`). Recomiendo mantenerlo en el use case para que
    el estado sea consistente al primer poll del frontend.
- **Errores**:
  - `ResourceNotFoundError` si la agency o el reel no existen.
  - `ValidationError` (o `ApplicationError` con
    `code='PUBLISH_PREREQUISITES_MISSING'`, retornable a 422 / 200 según
    decisión) si falta raw_payload o falta la GHL connection. **HOY** el
    handler responde 200 con `publish_enqueued: false` y un `reason` (ver
    `server.py:3299-3313`). Mantener ese contrato para no romper el frontend.

---

## 4. Job kinds y `delivery.jobs`

### Catálogo de job kinds

No existe un enum/registro centralizado; los kinds aparecen como literales:

- `"reel_publish"` —
  - default en `JobRepository._row_to_job` (`modules/delivery/infrastructure/job_repository.py:50`),
  - y en el `INSERT` (`job_repository.py:107`),
  - registrado como handler del worker en
    `apps/worker/runtime.py:271-274`,
  - documentado en `ARCHITECTURE.md:99` y
    `modules/delivery/domain/job.py:4`.
- `"scripted_render"` — registrado en `apps/worker/runtime.py:275-278`,
  documentado en mismas líneas. Ámbito de feature 8, irrelevante aquí.

**Para `regenerate_reel` el kind es `reel_publish`.**

### Payload del kind `reel_publish` (lo que el worker espera)

Ver `apps/worker/runtime.py` (handler `ReelPipeline.handle`,
`modules/reels/application/orchestrator.py:23-31`) que llama a
`build_property_media_job(job)` y de ahí a
`build_default_job_handler` (legacy bridge en `application/bootstrap/runtime.py`).

El job carga:

- `payload` (jsonb): la WordPress payload original. El bridge la lee como
  `dict` y la convierte en `PropertyMediaJob`.
- `publish_context` (jsonb): se hidrata `SocialPublishContext` con el
  `provider_secret_bundle` mergeado como `access_token`
  (`orchestrator.py:38-41`).
- `external_source_id` (= site_id), `property_id` (= source_property_id).

**El implementer puede llamar `JobRepository.enqueue_job(JobEnqueueRequest(...))`
directamente** — no es estrictamente necesario pasar por
`WebhookAcceptanceService` salvo para reusar la lógica de supersede +
WebhookEvent. Decisión recomendada: el use case `regenerate_reel` replica
internamente el supersede + webhook_event_create + enqueue (3 escrituras en
una transacción del UoW), siguiendo la receta de `webhook_acceptance.py:62-104`
pero usando `uow.delivery.jobs / uow.delivery.webhook_events` (no los stores
legacy). Esto evita arrastrar `application/dispatch/webhook_acceptance.py` al
módulo reels.

---

## 5. Payloads Pydantic sugeridos

Ubicación: `modules/reels/transport/payloads/admin_reels.py` (siguiendo el
patrón de feature 1 y feature 2).

### 5.1 `ListReelsResponse`

```python
class ListReelsResponseItem(BaseModel):
    site_id: str
    source_property_id: int
    slug: str
    title: str | None
    link: str | None
    price: str | None
    property_status: str | None
    property_type_label: str | None
    property_area_label: str | None
    property_county_label: str | None
    bedrooms: int | None
    bathrooms: int | None
    featured_image_url: str | None
    agent_name: str | None
    workflow_state: str
    publish_status: str
    render_status: str
    last_published_location_id: str  # ojo: campo legacy renombrado, ver §11
    current_revision_id: str
    pipeline_updated_at: str
    pipeline_created_at: str
    fetched_at: str
    revision_media_path: str
    revision_metadata_path: str
    revision_artifact_kind: str
    revision_created_at: str

class ListReelsResponse(BaseModel):
    items: list[ListReelsResponseItem]
    count: int
```

> Replica `_serialize_agency_reel` (`server.py:4101-4129`).

### 5.2 `GetReelDetailResponse`

```python
class GetReelDetailResponse(BaseModel):
    reel: ListReelsResponseItem  # mismo shape, más:
    # los handlers actuales añaden:
    # has_video: bool
    # video_url: str | None
```

Decisión: añadir `has_video: bool` y `video_url: str | None` al item de detalle,
o crear `ReelDetailItem(ListReelsResponseItem)` con esos extras. La segunda
opción es más limpia.

### 5.3 `RegenerateReelRequest` (body) y `RegenerateReelResponse`

HOY `approve` no acepta body. Para futuro-proof:

```python
class RegenerateReelRequest(BaseModel):
    # vacío o flags opcionales, p.ej.:
    force: bool = False  # ignora el supersede check si True (no implementado hoy)

class RegenerateReelResponse(BaseModel):
    status: Literal["approved", "regenerated"]
    publish_enqueued: bool
    event_id: str | None = None
    job_id: str | None = None
    reason: str | None = None
    hint: str | None = None
    reel: ListReelsResponseItem
```

Mantener compatibilidad con la respuesta actual (status='approved',
publish_enqueued, event_id, job_id, reason, hint, reel).

---

## 6. Helpers transversales

Ya extraídos en feature 1, listos para reuso:

| Helper | Path | Símbolos |
|---|---|---|
| Admin auth | `apps/api/admin_auth.py` | `AdminAccessPolicy`, `authorize_admin_request`, `format_client`, `extract_bearer_token` |
| Error handlers | `apps/api/error_handlers.py` | `json_error`, `register_error_handlers` |
| Range response | `apps/api/range_response.py` | `build_range_response`, `DEFAULT_VIDEO_MEDIA_TYPE`, `VIDEO_STREAM_CHUNK_SIZE`, `DEFAULT_CACHE_CONTROL` |
| Logging middleware | `apps/api/logging_middleware.py` | `register_logging_middleware`, `decode_body_for_logging`, … |

El router de reels usa `authorize_admin_request`, `json_error` y
`build_range_response`. El helper `_guess_image_mime_type`
(`server.py:4019-4031`) **no está aún extraído**. Opciones:

1. Inlinearlo en `admin_reels_router.py` (sólo 13 LoC, single-use).
2. Subirlo a `apps/api/range_response.py` como `guess_image_mime_type` o a
   `apps/api/streaming.py` nuevo. **Recomendado** si el implementer prefiere
   no contaminar el router.

El stream "full file" para imágenes (`server.py:3154-3166`) NO usa
`build_range_response` (no honra Range). Decisión: mantener tal cual
(imágenes son <100 KB, no merece la pena). Inlinear en el router es OK.

---

## 7. Imports cruzados peligrosos

**Buena noticia**: ninguno de los 8 handlers de reels importa nada de
`application/pipeline/media_services.py`. La búsqueda

```
grep "media_services" services/transport/http/server.py  →  0 matches
```

confirma que el handler hoy no toca el pipeline pesado. Toda la lógica
"pesada" se invoca a través del **dispatcher de jobs**, lo que respeta
exactamente la separación deseada por feature 7.

Lo que **sí** se importa hoy en server.py y debe limpiarse al mover el
router (ver §11):

- `from application.dispatch.webhook_acceptance import WebhookAcceptanceService`
  (`server.py:29`) — usado por `enqueue_reel_publish` para insertar el job. Se
  reemplaza por escrituras directas a `uow.delivery.jobs` +
  `uow.delivery.webhook_events` desde el use case `regenerate_reel`.
- `from application.bootstrap.runtime import build_default_job_dispatcher,
  build_runtime_unit_of_work_factory` (`server.py:22-25`) — el bootstrap del
  runtime. El router nuevo no lo necesita: usa `DatabaseUnitOfWork` directo.
- `from application.pipeline.interfaces import JobDispatcher` (`server.py:26`)
  — solo el constructor del server lo usa, no los handlers.
- `from application.tenancy.resolver import TenantResolver` (`server.py:27`)
  — usado por `WebhookAcceptanceService`. Reemplazo: leer `agency_id` e
  `ingestion_source_id` directamente de la fila `properties` via
  `uow.catalog.properties.get_for_property(...)`.
- `from application.types import SocialPublishContext` (`server.py:28`) —
  está hoy en `application/types.py`. **NO** se ha movido a un módulo. Para
  feature 7 vale seguir importándolo (es solo un dataclass), pero hay que
  documentar que ese símbolo es "compartido" entre publishing y reels.
  Sería ideal que viviera en `modules/publishing/domain/social_publish_context.py`,
  pero tocarlo aquí es scope-creep — anotarlo como deuda para feature 13.
- `from core.errors import ApplicationError, …` (`server.py:68-74`) — los
  routers nuevos importan de `shared.errors` (ya existe el shim en
  `shared/errors/__init__.py`).
- `from core.logging import …` (`server.py:75-82`) — los routers nuevos
  importan de `shared.observability`.

---

## 8. Tests existentes que tocan `/admin/agencies/{id}/reels*`

Cobertura actual MUY pobre:

- `tests/integration/test_http_transport.py:540-551` —
  `test_admin_reels_listing_is_empty_for_a_fresh_agency`. Verifica
  `GET /v1/admin/agencies/{agency_id}/reels` devuelve `{items:[], count:0}`
  para una agency recién sembrada.

**No hay tests** para detail, video, images, manifest, approve ni reject.

Propuesta de cobertura para feature 7 (acceptance: `tests/integration/reels/test_admin_reels_router.py`):

- list: vacío + con seed.
- detail: 404 agency, 404 reel, 200 con shape correcto, has_video=True/False.
- regenerate (= approve): 404 agency, 404 reel, 200+publish_enqueued=False
  cuando faltan prereqs (sin raw_payload o sin GHL), 200+publish_enqueued=True
  con seed completo, verificar fila en `jobs` con `kind='reel_publish'` y
  payload correcto, verificar supersede de jobs previos.
- (opcional) reject.
- video/images/manifest: pueden quedar como tests del transport puro
  (existencia de fichero en workspace temporal).

Tests unit en `tests/unit/reels/test_<use_case>.py`: stub el UoW, verificar
calls correctos y mapping a dataclasses.

---

## 9. Acoplamiento cross-feature

### Con features 10-13 (use cases del pipeline)

**Cero acoplamiento del handler con el código del pipeline.** El handler de
`regenerate_reel` solo escribe un job en `delivery.jobs`. Toda la lógica de
ingest/prepare/persist/publish corre **en el worker**, post-claim, así que
features 10-13 son ortogonales: el implementer de feature 7 NO debe importar
nada de `modules/reels/application/use_cases/{ingest_property_into_reel,
prepare_reel_assets, persist_local_artifacts, publish_reel}` (esos archivos
ni siquiera existen aún).

### Con feature 16 (worker ejecuta use cases reales)

HOY el job `reel_publish` lo consume `ReelPipeline.handle`
(`apps/worker/runtime.py:271-274`), que vía `build_default_job_handler` (en
`application/bootstrap/runtime.py`) cae en el **bridge legacy**
(`application/pipeline/media_services.py`, 1839 LoC). Cuando feature 16 se
cierre, el handler real será la composición de los use cases 10-13.
Mientras tanto, el job que enccola feature 7 lo consume el bridge legacy
sin diferencia de comportamiento — el contrato (kind, payload,
publish_context, raw_payload_hash) es el mismo.

**Implicación operativa**: feature 7 puede hacerse y cerrarse antes que
features 10-16. El consumer cambia debajo, el producer no.

### Con feature 9 (retire WordPressWebhookServer)

Hasta que feature 7 (y 2-8) se cierren, el server.py mantiene los handlers.
El leader debe asegurarse de **eliminar los handlers de reels en server.py**
en el mismo PR del implementer (acceptance `server.py ya no expone
/admin/agencies/{id}/reels/*`), o feature 9 fallará con duplicado.

---

## 10. LoC estimado a mover

### En el handler (`services/transport/http/server.py`)

- Banner + 8 handlers (líneas 2889-3373) ≈ **485 LoC**.
- `_serialize_agency_reel` (líneas 4101-4129) ≈ **29 LoC**.
- `_guess_image_mime_type` (líneas 4019-4031) ≈ **13 LoC**.

### En el runtime (`WordPressWebhookApplication`)

Helpers que se promueven a use cases o a `ReelQuery`:

- `list_agency_reels` (líneas 1064-1069) ≈ **6 LoC** → use case `list_reels`.
- `get_agency_reel_detail` (líneas 1071-1090) ≈ **20 LoC** → use case
  `get_reel_detail`.
- `resolve_reel_video_path` (líneas 1092-1116) ≈ **25 LoC** → puede vivir en
  `get_reel_detail` o como helper de transport.
- `enqueue_reel_publish` (líneas 1118-1190) ≈ **73 LoC** → use case
  `regenerate_reel`.
- `list_reel_property_images` (líneas 1192-1202) ≈ **11 LoC** → puede
  quedar como llamada directa a `uow.catalog.images.list_for_property`.
- `resolve_property_image_path` (líneas 1204-1226) ≈ **23 LoC** → helper
  de transport.
- `resolve_reel_manifest_path` (líneas 1228-1250) ≈ **23 LoC** → helper de
  transport.
- `update_reel_workflow` (líneas 1252-1289) ≈ **38 LoC** → embebido en
  `regenerate_reel` (parte del approve) y otro futuro `reject_reel`.

### Total estimado

- Mover **485 + 219 ≈ 700 LoC** desde server.py / WordPressWebhookApplication.
- Crear **~250 LoC** en el router nuevo + **~180 LoC** en los 3 use cases
  (más liviano que el original porque pasa todo por UoW namespacado, sin
  atajos legacy).
- Tests: **~250-350 LoC** (acceptance pide unit + integration).

---

## 11. Riesgos / blockers

1. **La acceptance pide "regeneration" pero el código es "approve"**.
   Aclarar en el ticket del implementer que `regenerate_reel` ≡ el flujo
   approve actual, y decidir explícitamente si:
   (a) renombrar el endpoint a `/regenerate` y romper el frontend (NO),
   (b) mantener `/approve` como path y nombrar el use case
   `regenerate_reel` (recomendado),
   (c) añadir un endpoint nuevo `/regenerate` que comparta la lógica con
   `/approve`. **Recomendación**: (b).

2. **`/reject` está fuera de scope explícito.** Si se mueve, el router
   queda completo; si no, hay un handler de reels huérfano en server.py
   (lo que viola la acceptance "server.py ya no expone
   /admin/agencies/{id}/reels/*"). **Recomendación**: incluir `reject` con
   un use case `reject_reel` minimal; documentarlo como "extra justificado"
   en `progress/impl_7_…md`.

3. **`enqueue_reel_publish` depende de la `WordPressWebhookApplication`
   helpers `get_ghl_connection_by_agency` y `get_reel_profile`**
   (`server.py:1155-1158`). Esos helpers están en el runtime legacy. Hay
   dos opciones:
   - Llamar directo a `uow.publishing.connections.get_with_secrets(agency_id, provider="gohighlevel")`
     y a `uow.configuration.defaults.get_for_agency(agency_id)`. Confirmar
     con el implementer que esos repos exponen lo necesario (mirar
     `modules/publishing/infrastructure/provider_connection_repository.py`
     y `modules/configuration/infrastructure/defaults_repository.py`).
   - Bloquear feature 7 hasta que feature 5 (publishing connections router)
     y feature 6 (configuration routers) materialicen los use cases
     `get_provider_connection` y `get_<defaults>`. **No hace falta**: las
     features 5 y 6 mueven *transport*, los repos del UoW ya existen y se
     pueden llamar directos desde el use case `regenerate_reel`.

4. **`SocialPublishContext` vive en `application/types.py` (legacy)**. El use
   case `regenerate_reel` lo importa o construye un dict equivalente. Si se
   importa, queda una dependencia del módulo reels hacia `application/`
   (legacy frozen). Mejor construir el dict del `publish_context_json`
   inline en el use case y dejar la conversión a `SocialPublishContext` en
   el bridge consumer del worker. Trabajo de feature 13.

5. **`PropertyRepository.get_property_raw_payload` y
   `list_property_images`**. Confirmar que están en
   `modules/catalog/infrastructure/property_repository.py` y expuestos por
   `uow.catalog.properties` / `uow.catalog.images`. Si no, el implementer
   debe portar esos métodos (es ámbito catalog, no reels — coordinar con
   feature 17 "retire repositories/stores").

6. **`update_reel_workflow` usa `unit_of_work.pipeline_state_repository`**
   (legacy). Reemplazo natural: `uow.reels.states.update_workflow_state` y
   `uow.reels.states.update_publish_status`
   (`modules/reels/infrastructure/reel_state_repository.py:233-280`,
   `:183-231`). Las firmas son compatibles (toman
   `external_source_id, source_property_id`), confirmar que el
   `agency_id` y `ingestion_source_id` pasados existen en el row preexistente
   o se obtienen del repo de catálogo.

7. **`AgencyReelSummary.last_published_provider_external_id` vs
   `_serialize_agency_reel.last_published_location_id`**. El dataclass
   moderno usa `last_published_provider_external_id` (después del rename
   de Phase 1) pero el serializer sigue exponiendo
   `last_published_location_id` (`server.py:4120`). El implementer debe
   decidir: mantener el alias en la response (no romper frontend) o
   alinearlo. **Recomendación**: mantener el alias; es Phase 3 quien hará
   el rename de la URL surface.

8. **`reel_query.list_recent_for_agency` usa
   `external_source_id` como nombre de columna**, pero el handler hoy lo
   serializa como `site_id` (ver `_serialize_agency_reel`, `server.py:4103`,
   `_REEL_SELECT_COLUMNS` en reel_query.py expone
   `p.external_source_id AS external_source_id`). El use case debe seguir
   ese mismo aliasing al construir el payload Pydantic.

9. **No hay tests previos sobre el camino "approve → encolar"**. Cobertura
   nueva en `tests/integration/reels/` será necesaria desde cero.

10. **Cuidado con el `__init__.py` de `modules/reels/transport/http/`** —
    está vacío hoy (ver §0 listing). El implementer debe registrar el
    nuevo router en `apps/api/app_factory.py` o crear una función
    `register_admin_reels_router(app)` siguiendo el patrón que
    establezca feature 2 (publishing sessions router).

---

## Apéndice A — Mapping rápido para el implementer

| Hoy (legacy)                                                        | Mañana                                                                                       |
|---------------------------------------------------------------------|----------------------------------------------------------------------------------------------|
| `runtime.list_agency_reels(agency_id, limit)`                       | `ListReelsUseCase.execute(agency_id, limit)` → `uow.reels.queries.list_recent_for_agency`    |
| `runtime.get_agency_reel_detail(agency_id, site_id, source_property_id)` | `GetReelDetailUseCase.execute(...)` → `uow.reels.queries.list_recent_for_agency` filtrado     |
| `runtime.resolve_reel_video_path(...)`                              | helper de transport `_resolve_reel_video_path(uow, workspace_dir, ...)`                      |
| `runtime.list_reel_property_images(...)`                            | `uow.catalog.images.list_for_property(external_source_id, source_property_id)` (verificar)   |
| `runtime.resolve_property_image_path(...)`                          | helper de transport                                                                          |
| `runtime.resolve_reel_manifest_path(...)`                           | helper de transport                                                                          |
| `runtime.update_reel_workflow(...)`                                 | `uow.reels.states.update_workflow_state(...)` + `update_publish_status(...)`                  |
| `runtime.enqueue_reel_publish(...)`                                 | `RegenerateReelUseCase.execute(...)` → directo en `uow.delivery.jobs.enqueue_job` + `webhook_events.create_event` + `supersede_queued_jobs` |
| `runtime.get_agency`                                                | `uow.tenancy.agencies.get_by_id(agency_id)` (verificar firma)                                 |
| `runtime.get_ghl_connection_by_agency(agency_id)`                   | `uow.publishing.connections.get_with_secrets(agency_id=..., provider="gohighlevel")`          |
| `runtime.get_reel_profile(agency_id)`                               | `uow.configuration.defaults.get_for_agency(agency_id)` (verificar nombre real del método)     |
| `_authorize_admin_request(request, runtime)` (server.py:4197)       | `authorize_admin_request(request, admin_access_policy)` (apps/api/admin_auth.py)              |
| `_json_error(...)` (importado de apps.api.error_handlers como alias)| `json_error(...)` directo                                                                     |
| `_build_range_response(...)` (alias)                                | `build_range_response(...)` directo                                                           |
| `_serialize_agency_reel(item)`                                      | `ListReelsResponseItem.model_validate({...})` o helper en `modules/reels/transport/payloads/` |

---

## Apéndice B — Endpoints en orden de complejidad

1. **GET list** — el más simple, una llamada a `ReelQuery`.
2. **GET detail** — list filtrada + `resolve_reel_video_path`.
3. **GET video** — `resolve_reel_video_path` + `build_range_response`. Sin
   use case.
4. **GET images** — list de imágenes + check fichero local. Sin use case
   real (lectura plana del repo de catalog).
5. **GET image file** — `resolve_property_image_path` + `_guess_image_mime_type`
   + StreamingResponse. Sin use case.
6. **GET manifest** — `resolve_reel_manifest_path` + leer JSON del disco. Sin
   use case.
7. **POST approve** ≡ regenerate — el más rico: el único con use case
   "gordo" (`regenerate_reel`).
8. **POST reject** — minimal: 2 escrituras al estado, sin job. (Fuera de
   scope explícito; ver §11.)
