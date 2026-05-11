# Explore — Feature 4 `ingestion_routers`

> Read-only mapping for the implementer. Cites `path:line` for every claim.
> All paths are relative to the repo root `c:/Users/4pm/Desktop/4reels/4reels back/`.

---

## 1. Rutas y handlers en `services/transport/http/server.py`

### 1.a `/admin/agencies/{agency_id}/sources` — efectivo en server.py

Hoy la superficie agency-scoped son **DOS endpoints** (no CRUD completo):

| Verbo  | Path (resuelto)                                                      | Handler                                | Líneas       |
|--------|----------------------------------------------------------------------|----------------------------------------|--------------|
| POST   | `/v1/admin/agencies/{agency_id}/sources`                             | `upsert_admin_agency_source`           | `services/transport/http/server.py:2085-2156` |
| DELETE | `/v1/admin/agencies/{agency_id}/sources/{wordpress_source_id}`       | `delete_admin_agency_source`           | `services/transport/http/server.py:2158-2196` |

- Path real es construido con `f"{application.admin_access_policy.base_path}/agencies/{{agency_id}}/sources"`. `base_path = ADMIN_API_BASE_PATH = /v1/admin` (default; `services/transport/http/server.py:712-715`).
- Decoradores: `@app.post(...)` / `@app.delete(...)` con `tags=["Admin · Sources"]`.
- Dependencias FastAPI: `agency_id: str`, `payload: _AdminAgencySourceUpsertPayload`, `request: Request` (`services/transport/http/server.py:2096-2099`). `_get_runtime(request)` (línea 4012) recupera el `WordPressWebhookApplication` de `app.state`.
- El handler **POST** hace `_authorize_admin_request` (4197) → `runtime.get_agency(agency_id=...)` (1040) → `runtime.wordpress_source_admin_service.upsert_source(UpsertWordPressSourceRequest(...))` (2116) → serializa con `_serialize_wordpress_source_details` (4175). Devuelve `201` si creado, `200` si actualizado.
- El handler **DELETE** hace `_authorize_admin_request` → `runtime.delete_wordpress_source(wordpress_source_id=...)` (1291). Devuelve `404` con `code="ADMIN_SOURCE_NOT_FOUND"` si no existe.

> **Nota crítica para el implementer:** la feature description pide `create_source`, `list_sources`, `get_source`, `update_source`, `delete_source` como use cases pero la API actual solo expone:
> - `POST /admin/agencies/{agency_id}/sources` → upsert (no diferencia create/update — `WordPressSourceAdminService.upsert_source` decide internamente, `application/admin/wordpress_source_management.py:82`).
> - `DELETE /admin/agencies/{agency_id}/sources/{wordpress_source_id}`.
>
> El listado por agency está embebido en `GET /admin/agencies/{agency_id}` (`server.py:1996`), que es competencia de la **feature 3** (tenancy). El detalle individual no existe hoy.
>
> El implementer debe decidir entre:
> - Conservar exactamente la superficie actual (POST upsert + DELETE) y alinear los nombres de use cases (`upsert_source` + `delete_source`) — más fiel a behaviour-preservation.
> - Expandir a CRUD real (POST=create, GET list, GET detail, PUT update, DELETE) — añade superficie nueva y rompe acceptance criterion "server.py ya no expone /admin/agencies/{id}/sources".
>
> Recomendación leader: **escalar al leader** antes de implementar; la lectura literal de la feature description ("CRUD") choca con la realidad de server.py. La opción más segura es exponer al menos los cinco verbos como use cases pero mantener el router con upsert+delete (paridad con server.py) y dejar list/get/update como use cases sin route, listos para el frontend que los pida en Phase 3.

### 1.b Webhook — `application.path` resuelve a `/v1/ingest/wordpress/property`

| Verbo | Path                              | Handler                          | Líneas       |
|-------|-----------------------------------|----------------------------------|--------------|
| POST  | `/v1/ingest/wordpress/property`   | `receive_property_webhook`       | `services/transport/http/server.py:3488-3839` |

- Default de `WEBHOOK_PATH` en `.env.example:58` y `settings/webhook.py:7`. **No es `/webhooks/wordpress/property`** como dice el feature description — es `/v1/ingest/wordpress/property`. Confirmado por los integration tests (`tests/integration/test_http_transport.py:177, 206, 220, 245`).
- Decorador: `@app.post(application.path, tags=["Webhooks"])`.
- El handler recibe `request: Request` y solo lee headers + body raw (no usa Pydantic body model — el body es contrato externo de WordPress que parsea con `_parse_webhook_payload`, `server.py:3549`).
- Headers consumidos:
  - `runtime.site_id_header` (default `X-WP-Site-Id`, `server.py:3508`).
  - `runtime.timestamp_header` (default `X-WP-Timestamp`, `server.py:3509`).
  - `runtime.signature_header` (default `X-WP-Signature`, `server.py:3510`).
  - `Content-Type` y `Content-Length` (3512, 3522).
- Validación: content-type debe ser `application/json` (3513), `Content-Length` numérico ≤ `runtime.max_payload_bytes` (3522-3547).

---

## 2. Bridge actual al worker (webhook → job)

> El feature description dice "ya hace eso vía bridge". El bridge **es** `WebhookAcceptanceService.accept_delivery`. No hay un bridge separado; el handler HTTP llama al servicio de aceptación que escribe directamente en `webhook_events` y `jobs` (= `delivery.jobs`).

### 2.a Cadena exacta dentro del handler

`services/transport/http/server.py:3506-3839`:

1. Leer headers + body, validar content-type/length (3512-3547).
2. Resolver `site_id` desde header o desde el body (`_resolve_site_id`, 3554, definido en 4463-4488: lee `rest_domain`, fallback `site_id`, fallback `link`/`guid.rendered`).
3. Validar headers de seguridad (3566-3577).
4. `runtime.authenticate_with_details(...)` (3580, definido en 872-921).
5. Calcular `_extract_property_id(payload)` (3612, definido en 4418-4427).
6. `build_raw_payload_hash(raw_body)` (3613) — sha256 del body raw, ver `services/transport/http/security.py:8-9`.
7. `runtime.acceptance_service.tenant_resolver.resolve(site_id=site_id)` (3638). Resolver definido en `application/tenancy/resolver.py:25-58`. Lanza `ResourceNotFoundError(code="UNKNOWN_WORDPRESS_SITE")` si no existe.
8. `runtime.require_ghl_connection_for_agency(agency_id=...)` (3639) — lanza `ResourceNotFoundError(code="GHL_CONNECTION_NOT_FOUND")`.
9. `runtime.get_reel_profile(...)` (3642) — opcional; resuelve plataformas + `approval_required` + `social_templates`.
10. `runtime.accept_webhook_delivery(...)` (3664) → delega en `WebhookAcceptanceService.accept_delivery` (`services/transport/http/server.py:923-938` + `application/dispatch/webhook_acceptance.py:38-114`).

### 2.b Job kind y shape del payload encolado

- **Kind:** Hoy el legacy bridge usa `repositories/stores/job_queue_store.PropertyJobEnqueueRequest` (no incluye campo `kind`; el INSERT lo deja al default de la columna `jobs.kind`). El nuevo `modules/delivery/domain.JobEnqueueRequest` (modules/delivery/domain/job.py:16-31) **sí** lleva un campo `kind: str` y el repositorio nuevo (`modules/delivery/infrastructure/job_repository.py:107`) lo normaliza a `lower()` con default `'reel_publish'`. **El kind a usar es `reel_publish`** — se confirma porque `ARCHITECTURE.md:99` lista `reel_publish` y `scripted_render` como los dos discriminadores hoy, y el dispatcher route (`ARCHITECTURE.md:154`) `reel_publish → ReelPipeline`.
- **Shape de fila en `jobs` que escribe el bridge** (`application/dispatch/webhook_acceptance.py:62-104` vía `repositories/stores/job_queue_store.PropertyJobEnqueueRequest`, fields 31-45):
  - `job_id`, `event_id` (uuid4 nuevos, generados en `webhook_acceptance.py:49-50`).
  - `agency_id`, `wordpress_source_id` (de `tenant_resolver.resolve`, ahora `ingestion_source_id` en el nuevo schema).
  - `site_id` (`tenant.site_id`; en el nuevo schema = `external_source_id`).
  - `property_id` (`int | None`).
  - `received_at` (`datetime.now(timezone.utc).isoformat()`).
  - `raw_payload_hash` (sha256 del raw body).
  - `payload_json` = `json.dumps(payload, ensure_ascii=False, sort_keys=True)` (línea 51) — payload completo de WordPress.
  - `publish_context_json` = `json.dumps(publish_context.to_dict(include_access_token=False), ...)` (línea 56). El access token NO viaja en `publish_context_json`, viaja en su columna cifrada propia.
  - `gohighlevel_access_token` (legacy field) → en el nuevo schema se cifra dentro de `provider_secrets_encrypted` por `JobRepository.enqueue_job` (`modules/delivery/infrastructure/job_repository.py:116`).
  - `max_attempts`, `available_at`, `created_at`.
- **Atomicidad:** todo dentro de `with self.unit_of_work_factory() as unit_of_work` + `unit_of_work.begin_immediate()` (línea 63). Antes del INSERT, `supersede_queued_jobs` marca como `superseded` cualquier otro job en cola para la misma `(site_id, property_id)`, y el `webhook_event_store.update_event_status(..., status='superseded')` se aplica a los eventos de esos jobs (líneas 64-75). **Esta semántica de superseding hay que preservarla.**

### 2.c Modelos `delivery.jobs` que recibe la fila

- Nuevo (a usar tras el refactor): `modules/delivery/domain/job.py:16-31` (`JobEnqueueRequest`) + `modules/delivery/infrastructure/job_repository.py:84-122` (`JobRepository.enqueue_job`).
- Diferencias vs legacy (relevantes para el implementer):
  - `wordpress_source_id` → `ingestion_source_id` (renombrado, `ARCHITECTURE.md:108`).
  - `site_id` → `external_source_id` (renombrado, `ARCHITECTURE.md:107`).
  - `gohighlevel_access_token` → empaquetado dentro de `provider_secret_bundle` y cifrado en `provider_secrets_encrypted` BYTEA. Hoy el legacy guarda solo el access_token. El nuevo `JobRepository` espera un string opaco `provider_secret_bundle` que cifra con Fernet (`shared/db/security.encrypt_text`, `modules/delivery/infrastructure/job_repository.py:116`). El `ingest_wordpress_property` use case debe construir ese bundle (probablemente JSON con `{"access_token": "..."}`).
  - El nuevo `JobEnqueueRequest` toma `payload` y `publish_context` como `Mapping[str, Any]` (no JSON-string como en `PropertyJobEnqueueRequest`), porque `JobRepository.enqueue_job` los serializa internamente con `json.dumps` (lines 112-115).
- **Webhook event row** vía `WebhookEventRepository.create_event` (`modules/delivery/infrastructure/webhook_event_repository.py:40`) — no existe versión legacy nueva; el implementer debe consumir el repo del módulo (`uow.delivery.webhook_events`).

---

## 3. Repositorio existente

- **Nuevo (vivo, ya cableado al UoW):** `modules/ingestion/infrastructure/ingestion_source_repository.py:62-242` (`IngestionSourceRepository`). Métodos:
  - `get_by_id(ingestion_source_id) -> IngestionSource | None`
  - `get_by_kind_external_id(kind, external_id) -> IngestionSource | None` ← clave para el webhook (`kind='wordpress'`, `external_id=site_id`).
  - `list_for_agency(agency_id) -> tuple[IngestionSourceWithAgency, ...]`
  - `list_all() -> tuple[IngestionSourceWithAgency, ...]`
  - `create(*, ingestion_source_id, agency_id, kind, external_id, name, config=None, secret="", status="active") -> None` — cifra `secret` con Fernet (línea 177).
  - `update(*, ingestion_source_id, name, config=None, status="active", secret=None) -> None` — `secret=None` no toca el blob.
  - `touch_last_event(ingestion_source_id) -> None`
  - `delete(ingestion_source_id) -> bool`
- **Surface UoW:** `uow.ingestion.sources` (`shared/db/uow.py:48, 67-69, 137-139`).
- **Domain:** `IngestionSource` y `IngestionSourceWithAgency` en `modules/ingestion/domain/ingestion_source.py:15-39`. `IngestionSourceWithAgency` no incluye `webhook_secret` ni `has_webhook_secret`-style flag — solo `has_secret: bool` en `IngestionSource`.
- **Legacy (todavía existe, lo usan los handlers actuales):** `repositories/stores/wordpress_source_store.WordPressSourceStore` (`repositories/stores/wordpress_source_store.py:125-272`). Métodos: `get_by_site_id`, `create_source`, `update_source`, `get_details_by_site_id`, `list_sources_for_agency`, `delete_source`, `list_sources`. **A retirar en feature 17** (acceptance: `repositories/` borrado).
- **Servicio orquestador legacy:** `application/admin/wordpress_source_management.WordPressSourceAdminService` (`application/admin/wordpress_source_management.py:42-301`, ~500 LoC) — es la lógica que el use case `create_source`/`update_source` debe absorber: validación de site_id, agency upsert side-effects, slug conflict detection, normalización host/url. **Mucho de esto es lógica de slug/agency-creation que NO pertenece a ingestion** — pertenece a tenancy. El implementer debe decidir el boundary: lo más limpio es dejar la creación implícita de agencias FUERA del use case nuevo (los tests muestran que el endpoint asume que la agency ya existe vía `runtime.get_agency`, ver `server.py:2106`).

---

## 4. Use cases sugeridos

> Inputs/outputs/errores propuestos, alineados con `shared/errors/` y la arquitectura.

### 4.a `create_source`
- **Input:** `agency_id: str, kind: str, external_id: str, name: str, config: Mapping[str, Any] = {}, secret: str = "", status: str = "active"`.
- **Output:** `IngestionSource` (re-leído tras crear) o `IngestionSourceWithAgency` si se quiere serializar con datos de agency.
- **Errores:**
  - `ValidationError(code="INGESTION_SOURCE_KIND_REQUIRED")` si `kind` vacío.
  - `ValidationError(code="INGESTION_SOURCE_EXTERNAL_ID_REQUIRED")` si `external_id` vacío.
  - `ResourceNotFoundError(code="ADMIN_AGENCY_NOT_FOUND")` si `uow.tenancy.agencies.get_by_id(agency_id) is None`.
  - `ValidationError(code="INGESTION_SOURCE_DUPLICATE")` si ya existe `(kind, external_id)`.
- **DB:** `uow.ingestion.sources.create(...)`. Genera `ingestion_source_id = str(uuid4())`.

### 4.b `list_sources`
- **Input:** `agency_id: str | None = None` (None = global = admin super list).
- **Output:** `tuple[IngestionSourceWithAgency, ...]`.
- **Errores:** `ResourceNotFoundError("ADMIN_AGENCY_NOT_FOUND")` si `agency_id` provisto pero no existe.
- **DB:** `uow.ingestion.sources.list_for_agency(agency_id)` o `list_all()`.

### 4.c `get_source`
- **Input:** `ingestion_source_id: str` (o alternativa `kind+external_id`).
- **Output:** `IngestionSource | None` (o lanza `ResourceNotFoundError("INGESTION_SOURCE_NOT_FOUND")`).
- **DB:** `uow.ingestion.sources.get_by_id(...)`.

### 4.d `update_source`
- **Input:** `ingestion_source_id: str, name: str, config: Mapping = {}, status: str = "active", secret: str | None = None` (None = no tocar el blob, "" = vaciar).
- **Output:** `IngestionSource` actualizada.
- **Errores:**
  - `ResourceNotFoundError("INGESTION_SOURCE_NOT_FOUND")`.
  - `ValidationError(...)` para name vacío / status inválido.
- **DB:** `uow.ingestion.sources.update(...)`.

### 4.e `delete_source`
- **Input:** `ingestion_source_id: str`.
- **Output:** `bool` (deleted) — o `None` y lanzar `ResourceNotFoundError` si no existe.
- **DB:** `uow.ingestion.sources.delete(...)`.

### 4.f `ingest_wordpress_property` — el caso crítico

Este use case sustituye a `WebhookAcceptanceService.accept_delivery` + las validaciones que hoy viven en `receive_property_webhook` (server.py:3506-3677). **Inputs/outputs/errores tienen que mantener el contrato externo intacto** porque el shape lo dicta WordPress y el frontend de admin.

- **Input:**
  - `site_id: str`
  - `payload: Mapping[str, Any]` (body parseado de WordPress).
  - `raw_body: bytes` (para construir `raw_payload_hash`).
  - `timestamp: str | None`, `signature: str | None`, `security_disabled: bool`, `site_secrets: Mapping[str, str]`, `timestamp_tolerance_seconds: int` — **alternativamente**, encapsular todo esto detrás de un `WebhookSignatureVerifier` inyectado y dejar el use case solo con `site_id`, `payload`, `raw_payload_hash`. La verificación HMAC vive más cerca de `transport/` que de `application/` (ver §6).
- **Validación que debe hacer:**
  1. Resolver tenant via `uow.ingestion.sources.get_by_kind_external_id(kind="wordpress", external_id=site_id)` y `uow.tenancy.agencies.get_by_id(source.agency_id)`. Lanza `ResourceNotFoundError(code="UNKNOWN_WORDPRESS_SITE")` si la fuente no existe / no está activa (espejo de `application/tenancy/resolver.py:47-53`).
  2. Lookup `uow.publishing.connections.get_with_secrets(agency_id=agency_id, provider="gohighlevel")` (espejo de `runtime.require_ghl_connection_for_agency`, server.py:980). Lanza `ResourceNotFoundError(code="GHL_CONNECTION_NOT_FOUND")`.
  3. Resolver reel profile (configuration namespace): plataformas, `approval_required`, `social_templates`. Si no hay profile → `SOCIAL_PUBLISHING_DEFAULT_PLATFORMS`.
  4. Extraer `property_id = _extract_property_id(payload)` (server.py:4418).
- **Encolado:**
  1. `uow.delivery.jobs.supersede_queued_jobs(external_source_id=site_id, property_id=property_id, superseded_by_job_id=new_job_id)` — preservar la cadena de superseding.
  2. Para cada event_id devuelto: `uow.delivery.webhook_events.update_event_status(event_id, status="superseded", error_message="Superseded by a newer queued job.")`.
  3. `uow.delivery.webhook_events.create_event(event_id=..., agency_id=..., wordpress_source_id=ingestion_source_id, site_id=..., property_id=..., received_at=..., raw_payload_hash=..., status="queued")` — Nota: `WebhookEventRepository` aún se llama `wordpress_source_id` en su API; verificar firma en `modules/delivery/infrastructure/webhook_event_repository.py:40`.
  4. `uow.delivery.jobs.enqueue_job(JobEnqueueRequest(kind="reel_publish", ...))` con `provider_secret_bundle = json.dumps({"access_token": ghl.access_token})` (o el shape que espere ReelPipeline en feature 16; verificar el contrato `provider_secret_bundle` antes de fijarlo).
- **Output:** `AcceptedWebhookDelivery` (event_id, job_id, agency_id, ingestion_source_id, site_id, property_id, tenant_auto_provisioned). Mantener este shape — es lo que devuelve la HTTP response y consume el frontend (`server.py:3829-3839`).
- **Errores explícitos que el router debe traducir a HTTP:**
  - `UNKNOWN_WORDPRESS_SITE` → 404
  - `GHL_TOKEN_NOT_FOUND` / `GHL_CONNECTION_NOT_FOUND` → 404
  - `ValidationError` → 400
  - Otro `ApplicationError` → 500
  - `Exception` genérica → 500 con código `WEBHOOK_ACCEPTANCE_FAILED`
  Esta tabla está hoy en `server.py:3678-3777` y debe replicarse en el router.

---

## 5. Payloads Pydantic

### 5.a Sources CRUD — modelo a portar

`_AdminAgencySourceUpsertPayload` (`services/transport/http/server.py:209-240`):
- `extra="forbid"`, `str_strip_whitespace=True`.
- `site_id: str` (min_length 1) — externo a la API; en el nuevo schema = `external_id`.
- `source_name: str` (min_length 1) — = `name` en el nuevo schema.
- `site_url: str | None`
- `normalized_host: str | None`
- `source_status: str | None`
- `webhook_secret: str | None` — **importante:** `model_fields_set` se usa (`server.py:2129`) para distinguir "no enviado" de "enviado vacío" → bandera `update_webhook_secret`. El equivalente nuevo: `secret: str | None = None` y la regla "None = no tocar".

> El modelo se va a `modules/ingestion/transport/payloads/sources.py` (subdirectorio `transport/payloads/` para alinear con la convención de feature 2/3 — ver `feature_list.json:46`).
> Posibles nuevos: `IngestionSourceCreatePayload`, `IngestionSourceUpdatePayload`, `IngestionSourceListItem` (response model).

### 5.b Webhook body

**No hay BaseModel para el body del webhook** — y no debería haberlo, porque el contrato es externo y opaco (ver `server.py:3506` que solo recibe `request: Request` y parsea JSON manualmente con `_parse_webhook_payload`, server.py:4438-4460). Lo que sí hay:

- `_parse_webhook_payload(raw_body) -> tuple[dict | None, str | None]` (`server.py:4438`) — admite tanto un objeto JSON como un array de un solo objeto (`allow_single_item_array=True`).
- Campos consumidos del body: `id`, `slug`, `rest_domain`, `site_id`, `link`, `guid.rendered` (ver `_resolve_site_id` 4463-4488 y `_extract_property_id` 4418-4427).

> **Recomendación:** dejar el webhook router con `request: Request` parseando manual + tests cubriendo los shapes legítimos. Un Pydantic strict romperá payloads existentes de WordPress.

### 5.c Modelos de respuesta

Hoy se serializa con `_serialize_wordpress_source_details` (server.py:4175-4194). Replicar como `IngestionSourceResponse` Pydantic en `modules/ingestion/transport/payloads/sources.py` para que el router devuelva typed responses (opcional pero mejora OpenAPI).

---

## 6. Validación de seguridad del webhook

### 6.a Dónde se aplica hoy

`services/transport/http/server.py:3508-3611`:
- **Headers de seguridad** (3508-3510): `runtime.site_id_header` (default `X-WP-Site-Id`), `timestamp_header` (default `X-WP-Timestamp`), `signature_header` (default `X-WP-Signature`). Defaults configurables vía settings.
- **Allowlist de hosts:** `runtime.allowed_hosts` se aplica en el factory FastAPI vía `TrustedHostMiddleware` (no en este handler). Ver donde se construye `app` — buscar `TrustedHostMiddleware` en server.py si fuera necesario para feature 9.
- **Content-Type / Content-Length / max-size:** 3512-3547.
- **Missing security headers:** 3566-3577.
- **HMAC + timestamp tolerance:** `runtime.authenticate_with_details(...)` (3580, definido en 872-921).
  - Si `security_disabled=True` y hay `site_id`, devuelve `True` (sin firma).
  - Si no, busca `expected_secret = self.site_secrets.get(site_id)` (890) — fallback al diccionario en memoria. **Esto es legacy** — el nuevo flow debe leer el secret del repo (`uow.ingestion.sources.get_by_kind_external_id(...).secret_encrypted` desencriptado).
  - Llama `is_timestamp_fresh` y `is_signature_valid` de `services/transport/http/security.py:51-79`.

### 6.b Helpers a usar / a mover

- HMAC pure helpers: `services/transport/http/security.py:1-87` (`build_raw_payload_hash`, `build_signature`, `is_signature_valid`, `is_timestamp_fresh`).
- **El feature description dice "delegar a un helper de `apps/api/` o `shared/`".** Estos helpers son hojas (solo dependen de `hashlib`, `hmac`, `time`) — el destino lógico es **`shared/http/`** o **`shared/crypto/`** (ya existe `shared/crypto/`, ver `ARCHITECTURE.md:42-51` y `c:/Users/4pm/Desktop/4reels/4reels back/shared/`). Sugerencia: `shared/http/webhook_signature.py` con `verify_webhook_signature(*, secret, timestamp, raw_body, signature, tolerance_seconds, site_id="", location_id="", access_token="") -> tuple[bool, str | None, str | None]` (mantener la firma actual con location_id/access_token=`""` como defaults vacíos para preservar la compatibilidad de la firma HMAC con WordPress en producción).

> **Riesgo de compatibilidad:** la fórmula HMAC actual (`security.py:11-30`) incluye `location_id` y `access_token` en el mensaje firmado. Esto es legacy: WordPress firma con esos valores (que en el nuevo flow son `""`). Cualquier cambio aquí rompe firmas en producción. **Preservar bit-a-bit.**

---

## 7. Helpers transversales que invoca

- `apps/api/admin_auth.authorize_admin_request` (envuelto en `_authorize_admin_request`, server.py:4197).
- `apps/api/error_handlers.json_error` (importado como `_json_error`, server.py:93).
- `apps/api/logging_middleware.*` — para sanitizar logs.
- `shared/observability` (vía core/logging compat shim): `format_console_block`, `format_detail_line`, `format_context_line`, `log_persistent_event`.
- `shared/errors` (vía core/errors): `ApplicationError`, `ResourceNotFoundError`, `ValidationError`, `extract_error_details`.
- `services/transport/http/security.{build_raw_payload_hash, is_signature_valid, is_timestamp_fresh}` — a mover a `shared/http/` (ver §6.b).
- `application/types.SocialPublishContext` — usado para construir el publish_context que va al job. **No debería viajar tal cual** al nuevo modules/ingestion (un módulo no puede importar la application/ de otro). Se usa en `server.py:3669-3676`. El nuevo use case lo construye localmente con un dict / domain object propio del módulo `delivery` o `publishing` y serializa.
- `_get_runtime`, `_get_request_id`, `_format_client`, `_log_webhook_acceptance_failure`, `_build_acceptance_error_details` (server.py:4012, 4227, 91, 4234, 4211) — privados al server.py; replicar lógica en el router nuevo o subirlas a apps/api/* si vuelven a usarse en feature 5/6/7.

---

## 8. Imports cruzados peligrosos

- `services/transport/http/server.py:20-29`:
  ```
  from application.admin import UpsertWordPressSourceRequest, WordPressSourceAdminService
  from application.bootstrap.runtime import build_default_job_dispatcher, build_runtime_unit_of_work_factory
  from application.dispatch.webhook_acceptance import WebhookAcceptanceService
  from application.tenancy.resolver import TenantResolver
  from application.types import SocialPublishContext
  ```
  Todos son `application/` legacy, congelados (`feature_list.json:11`). El nuevo router NO debe importar de `application/`. Si necesita la lógica de superseding o de tenant-resolution, vive ahora dentro del use case `ingest_wordpress_property` consumiendo `uow.delivery.jobs.supersede_queued_jobs` y `uow.ingestion.sources.get_by_kind_external_id`.

- `services/transport/http/server.py:104-109`:
  ```
  from services.transport.http.operations import build_readiness_report, run_startup_checks
  from services.transport.http.openapi_docs import OpenApiDocsConfig, install_openapi_examples
  from services.transport.http.uvicorn_protocols import VerboseAutoHTTPProtocol
  from services.transport.http.security import build_raw_payload_hash, is_signature_valid, is_timestamp_fresh
  from services.publishing.social_delivery.gohighlevel_client import GoHighLevelClient
  from services.publishing.social_delivery.gohighlevel_social_service import GoHighLevelSocialService
  ```
  El router nuevo solo necesita `security.py` y debe re-ubicarlo a `shared/http/`. Los demás son tooling transversal que no toca la feature 4.

- **Reglas de aislamiento (`docs/architecture.md:21-27`):** el módulo `ingestion` puede importar `shared/` y `<otro>.domain`. **No puede** importar `<otro>.application` ni `<otro>.infrastructure`. Eso significa:
  - El use case `ingest_wordpress_property` puede leer `uow.publishing.connections.get_with_secrets(...)` (atravesar el UoW está OK — el UoW está en `shared/`).
  - El use case NO puede importar `from modules.publishing.application...` directamente.

---

## 9. Tests existentes

### 9.a Integration

`tests/integration/test_http_transport.py` cubre el webhook end-to-end:

| Test                                                                      | Líneas       |
|---------------------------------------------------------------------------|--------------|
| `test_webhook_resolves_agency_from_rest_domain_and_uses_stored_ghl_connection` | `tests/integration/test_http_transport.py:162-198` |
| `test_webhook_rejects_unknown_site`                                        | `tests/integration/test_http_transport.py:200-211` |
| `test_webhook_rejects_when_agency_has_no_ghl_connection`                   | `tests/integration/test_http_transport.py:213-229` |
| `test_webhook_acceptance_still_enqueues_when_dispatcher_reports_paused`    | `tests/integration/test_http_transport.py:231-257` |
| `test_admin_can_provision_a_wordpress_source_with_global_endpoint`         | `tests/integration/test_http_transport.py:400-422` (toca **el endpoint global** `/v1/admin/wordpress-sources/{site_id}` — no el agency-scoped — pero cubre la lógica de upsert que comparte servicio. **No hay test integration para `POST /admin/agencies/{id}/sources` ni `DELETE`** — el implementer debe crearlos) |

> Estos tests usan `seed_tenant`, `seed_provider_connection`, `temporary_postgres_schema`, `temporary_workspace` de `tests/support/postgres.py`. Importan `WordPressWebhookApplication` y `create_fastapi_app` (`server.py:34`). Cuando se cumpla la feature 9 esas factory functions se eliminan; en el medio (post-feature-4, pre-feature-9) los tests deberían adaptarse para construir el app via `apps/api/app_factory.build_api_app()` registrando los nuevos routers.

- Acceptance criterion del feature 4 (`feature_list.json:80`): `tests/integration/ingestion/test_wordpress_webhook_flow.py` — debe replicar al menos los cuatro tests de webhook anteriores (resolves+enqueue, unknown site, missing GHL, paused dispatcher).

### 9.b Worker

`tests/integration/test_worker_runtime.py` (148 LoC) — usa `webhook_event_store` y `wordpress_source_store` legacy para preparar fixtures. No invoca rutas HTTP. No bloquea esta feature pero cuando feature 17 retire `repositories/stores/`, este archivo cae.

### 9.c Unit existentes

- `tests/unit/apps_api/` (helpers; no tocan ingestion).
- `tests/unit/test_tenancy.py`, `test_architecture_cleanup.py`, `test_worker_runtime_adapter.py` — no relacionados.

> **No hay `tests/unit/ingestion/`** todavía. El implementer debe crearlo + `tests/integration/ingestion/test_wordpress_webhook_flow.py` (acceptance line `feature_list.json:80`).

---

## 10. Acoplamiento cross-feature

- **Feature 9** (`retire_wordpress_webhook_server`) **bloquea** retirar `services/transport/http/server.py`. Mientras 9 no esté done, server.py debe quedar **sin** las rutas extraídas (acceptance feature 4: "server.py ya no expone /admin/agencies/{id}/sources ni /webhooks/wordpress/property") pero el archivo sigue allí con el resto de rutas. El implementer debe **borrar** los handlers de server.py (líneas 2085-2196 y 3488-3839) y dejar el archivo compilando — tests que aún importen `WordPressWebhookApplication` o `create_fastapi_app` deben seguir pasando con las rutas restantes.
- **Feature 16** (`worker_real_use_cases_and_drop_noop_dispatcher`) consume el `kind="reel_publish"` que esta feature encola. El job payload shape (especialmente `provider_secret_bundle`) tiene que ser exactamente el que ReelPipeline espera consumir. Coordinar con el equipo de feature 16 antes de fijar el bundle.
- **Feature 3** (`tenancy_admin_agencies_router`) crea `AgencyRepository.create_agency`, `update_agency`, `delete_agency` que hoy NO existen en el módulo nuevo (`modules/tenancy/infrastructure/agency_repository.py:37-66` solo tiene `get_by_id/get_by_slug/list_all`). Si feature 4 corre **antes que** feature 3, el use case `create_source` no puede crear agencias on-the-fly. **Recomendación:** que `create_source` exija `agency_id` válido existente (no auto-crea) y devuelva 404 ADMIN_AGENCY_NOT_FOUND si la agency no existe. El comportamiento legacy de auto-crear agencia (vía `application/admin/wordpress_source_management.py:214-271`) debe quedar **fuera** del nuevo use case — ese path solo aplica a `PUT /v1/admin/wordpress-sources/{site_id}` (legacy global endpoint, no agency-scoped) y se retira en feature 9.
- **Feature 5** (`publishing_connections_router`) es lectura cross-module: `ingest_wordpress_property` debe leer `uow.publishing.connections.get_with_secrets` (que necesita estar disponible en `ProviderConnectionRepository`). Hoy el repo nuevo está vivo pero conviene confirmar que `get_with_secrets(agency_id, provider="gohighlevel")` existe — si no, feature 5 lo añade y feature 4 puede tener un blocker temporal. Verificar `modules/publishing/infrastructure/provider_connection_repository.py`.
- **Feature 17** (retire repositories/stores) — el use case nuevo no puede importar de `repositories/`. El `IngestionSourceRepository` nuevo ya cubre todas las operaciones; nada que esperar de la 17.

---

## 11. LoC estimado a mover

| Origen                                                                         | Líneas        | Bytes aprox |
|--------------------------------------------------------------------------------|---------------|-------------|
| `services/transport/http/server.py:209-240` (`_AdminAgencySourceUpsertPayload`) | ~32 LoC       | payload     |
| `services/transport/http/server.py:2085-2156` (POST sources)                   | 72 LoC        | router      |
| `services/transport/http/server.py:2158-2196` (DELETE sources)                 | 39 LoC        | router      |
| `services/transport/http/server.py:3488-3839` (POST webhook)                   | 352 LoC       | router      |
| Helpers a replicar/extraer (`_authorize_admin_request`, `_get_runtime`, `_format_client`, `_get_request_id`, `_log_webhook_acceptance_failure`, `_build_acceptance_error_details`, `_serialize_wordpress_source_details`, `_parse_webhook_payload`, `_resolve_site_id`, `_extract_property_id`, `_parse_content_length`, `_get_header_value`, `_hostname_from_value`) | ~190 LoC      | helpers/transport |
| Lógica nueva en use cases (`create_source`, `list_sources`, `get_source`, `update_source`, `delete_source`, `ingest_wordpress_property`) | ~250-300 LoC nueva | application |
| `services/transport/http/security.py` → `shared/http/webhook_signature.py`     | 87 LoC        | move        |

**Total a mover de server.py:** ~495 LoC + helpers compartidos. **Total de creación neta** (nuevos use cases + payloads + tests): ~600-800 LoC.

---

## 12. Riesgos / blockers

1. **Discrepancia path en feature description.** El description dice `/webhooks/wordpress/property` pero el path real (settings + tests) es `/v1/ingest/wordpress/property`. **Bloqueador:** confirmar con el leader si:
   - se mantiene el path actual (`WEBHOOK_PATH=/v1/ingest/wordpress/property`), o
   - se cambia a `/webhooks/wordpress/property` (rompe contrato con WordPress en producción y rompe los tests legacy).
   La interpretación más segura: el feature description usa una abreviatura informal y debe leerse como "el webhook actual"; el implementer debe preservar el path real `/v1/ingest/wordpress/property`.

2. **Discrepancia "CRUD" en sources.** La superficie real es POST upsert + DELETE, no CRUD completo. Ver §1.a. **Escalar al leader.**

3. **Cadena `webhook → job → worker` es crítica.** Si se rompe el `payload_json` o el `provider_secret_bundle` shape, la ReelPipeline (feature 16) no podrá consumir los jobs. Mitigación:
   - Mantener `payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)` byte-a-byte.
   - El bundle de secrets cambia de `gohighlevel_access_token` (string plano) en el legacy a `provider_secret_bundle` (string opaco que `JobRepository.enqueue_job` cifra). **Coordinar con feature 16 el shape del bundle** — propuesta inicial: `json.dumps({"access_token": ghl.access_token, "provider": "gohighlevel"})`.

4. **HMAC backward-compat.** El mensaje firmado incluye `location_id` y `access_token` (legacy artifact). Cualquier reescritura del helper en `shared/http/` debe preservar exactamente esa fórmula; los productores en producción (WordPress plugin) firman con esas exactas concatenaciones. Ver `services/transport/http/security.py:11-30`.

5. **Superseding semantics.** `WebhookAcceptanceService.accept_delivery` tiene una invariante: cuando llega un webhook nuevo para `(site_id, property_id)` con un job ya `queued`, marca todos los previos como `superseded` con `superseded_by_job_id` apuntando al nuevo. Si se pierde esto, jobs duplicados llegan al worker. La implementación nueva debe llamar a `uow.delivery.jobs.supersede_queued_jobs` y `uow.delivery.webhook_events.update_event_status` antes de enqueue.

6. **`webhook_events.wordpress_source_id` legacy column name.** El schema migración (`alembic/versions/20260501_0001_initial_schema.py`) renombra `wordpress_source_id` → `ingestion_source_id` en `jobs` (`ARCHITECTURE.md:108`) pero `webhook_events` puede aún llevar el nombre legacy en el repo nuevo (`modules/delivery/infrastructure/webhook_event_repository.py:40`). Verificar firma de `create_event` antes de fijar el contrato del use case.

7. **El TenantResolver legacy** (`application/tenancy/resolver.py:25-58`) tiene una rama `unsafe_test_source_provisioner` que auto-provisiona la fuente cuando `WEBHOOK_AUTO_PROVISION_UNKNOWN_SITES_FOR_TESTING=True` y `security_disabled=True`. Este path está cubierto por el flag `tenant_auto_provisioned` en `AcceptedWebhookDelivery`. El use case nuevo debe respetarlo (alguno de los tests integration podría depender de él) — al menos en el dev/test environment. No es estrictamente necesario reproducirlo en el use case si los tests integration nuevos no lo usan; ver el test `test_webhook_acceptance_still_enqueues_when_dispatcher_reports_paused` que NO lo usa.

8. **`apps/api/app_factory.py` actualmente delega TODO en `WordPressWebhookServer`** (`apps/api/app_factory.py:75-100`). El implementer debe modificarlo para registrar los nuevos routers `sources_router` y `wordpress_webhook_router` y remover las rutas correspondientes de server.py. La estrategia limpia es: en `build_api_app`, despues del `WordPressWebhookServer(...)`, hacer `server.app.include_router(sources_router)` y `server.app.include_router(wordpress_webhook_router)`. Esto no es la composición canónica de feature 9 (que hará `FastAPI()` directo) pero es el patrón intermedio.

9. **`runtime`-style globals.** Los nuevos routers no tienen `_get_runtime` — necesitan acceso a `unit_of_work_factory` (para los use cases) y al `dispatcher` (solo para `is_accepting_jobs()` que se loguea pero NO bloquea el enqueue, ver `server.py:3617-3635`). La opción más limpia: registrar el `unit_of_work_factory` y el `dispatcher` en `app.state` desde `app_factory.py` y dejar que cada router los lea via `request.app.state.unit_of_work_factory`. Los use cases reciben el factory por DI en su `__init__`.

10. **`is_accepting_jobs` está atado al dispatcher.** El `_NoopDispatcher` (`apps/api/app_factory.py:37-57`) sigue activo hasta feature 16. El router nuevo debe leer ese estado solo para logging/observabilidad — el enqueue procede igualmente (esto es parte del contrato actual). Confirmado por `test_webhook_acceptance_still_enqueues_when_dispatcher_reports_paused`.

---

## Resumen accionable para el implementer

- Crear:
  - `modules/ingestion/transport/http/sources_router.py` (POST upsert + DELETE).
  - `modules/ingestion/transport/http/wordpress_webhook_router.py` (POST webhook).
  - `modules/ingestion/transport/payloads/sources.py` (Pydantic input + response).
  - `modules/ingestion/application/use_cases/{create_source,list_sources,get_source,update_source,delete_source,ingest_wordpress_property}.py`.
  - `shared/http/webhook_signature.py` (mover desde `services/transport/http/security.py`).
  - `tests/unit/ingestion/...` y `tests/integration/ingestion/test_wordpress_webhook_flow.py`.
- Modificar:
  - `apps/api/app_factory.py` para registrar los dos routers.
  - `services/transport/http/server.py` para borrar handlers + payload model + helpers usados solo por ellos. El archivo debe seguir compilando y los tests legacy debe seguir pasando.
- Coordinar antes de implementar:
  - Contrato del `provider_secret_bundle` con feature 16.
  - Sí/no expandir el sources router a CRUD completo (vs paridad upsert+delete) con leader.
  - Path final del webhook (`/v1/ingest/wordpress/property` vs `/webhooks/wordpress/property`).
