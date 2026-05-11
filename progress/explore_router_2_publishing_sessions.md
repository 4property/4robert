# Explore Report — Feature 2 `publishing_sessions_router`

> Objetivo: mapear todo lo necesario para extraer las rutas de sesiones
> GoHighLevel desde `services/transport/http/server.py` a
> `modules/publishing/transport/http/sessions_router.py`.

## Nota previa sobre el path

`feature_list.json:42` y la descripción mencionan `/mvp/gohighlevel/*`, pero
en el código actual el prefijo ya está renombrado: las rutas viven bajo
`/v1/sessions/gohighlevel/*` (ver `REFACTOR_STATUS.md:224` — la fila de
mapeo legacy → v1 confirma `/mvp/gohighlevel/*` → `/v1/sessions/gohighlevel/*`).
Una búsqueda explícita de `/mvp/gohighlevel` en el repo no devuelve handlers,
solo el feature_list y el status doc. **Por tanto la feature 2 mueve los 4
handlers `/v1/sessions/gohighlevel/*`.**

---

## 1. Rutas y handlers en `services/transport/http/server.py`

Las cuatro rutas viven dentro de la closure `create_fastapi_app(application=...)`
(definida en `services/transport/http/server.py:1390-1392`). El `app` y el
`runtime` se obtienen así:

- `app.state.runtime = application` (`server.py:1425`)
- `runtime = _get_runtime(request)` → `request.app.state.runtime` (`server.py:4012-4013`)

Resumen de los 4 handlers:

| # | Método | Path | Líneas (inicio decorador → fin handler) | Nombre función |
|---|--------|------|-----------------------------------------|----------------|
| 1 | GET    | `/v1/sessions/gohighlevel/tokens`  | `server.py:1461-1478` | `list_gohighlevel_session_connections` |
| 2 | POST   | `/v1/sessions/gohighlevel/context` | `server.py:1480-1550` | `resolve_gohighlevel_session_context` |
| 3 | POST   | `/v1/sessions/gohighlevel/session` | `server.py:1552-1588` | `create_gohighlevel_session` |
| 4 | POST   | `/v1/sessions/gohighlevel/test`    | `server.py:1590-1654` | `test_gohighlevel_session_connection` |

### Handler 1 — `GET /v1/sessions/gohighlevel/tokens` (`server.py:1461-1478`)

- Decorador: `@app.get("/v1/sessions/gohighlevel/tokens", tags=["Session · GoHighLevel"], summary=..., description=...)`
- Dependencias FastAPI: solo `request: Request` (no body, no query, no path params).
- Lógica (`server.py:1471-1478`):
  - `runtime = _get_runtime(request)`
  - `records = runtime.list_ghl_connections()` (delega en
    `WordPressWebhookApplication.list_ghl_connections` definido en
    `server.py:971-973`, que abre el UoW y llama
    `unit_of_work.ghl_connection_store.list_connections()`).
  - Devuelve `JSONResponse(200, {"count": len(items), "items": [r.to_public_dict() for r in records]})`.
- Body / query: ninguno. Response: `{count: int, items: list[dict]}`.

### Handler 2 — `POST /v1/sessions/gohighlevel/context` (`server.py:1480-1550`)

- Decorador: `@app.post("/v1/sessions/gohighlevel/context", tags=[...], summary=..., description=...)`
- Dependencias FastAPI: `payload: _GoHighLevelContextPayload` (body JSON) y
  `request: Request`.
- Lógica:
  - `runtime.decrypt_gohighlevel_user_context(encrypted_data=payload.encrypted_data)`
    (`server.py:1497-1500`) — wrapper sobre
    `DecodeGoHighLevelSessionUseCase` ya existente en `modules/publishing`.
  - Maneja `ValidationError` → `_json_error(400, ..., code=error.code, hint=...)` (`server.py:1501-1508`).
  - Maneja `ApplicationError` → `_json_error(503, ..., code="GHL_CONTEXT_DECRYPT_FAILED", hint=...)` (`server.py:1509-1516`).
  - `extract_gohighlevel_user_context_fields(user_data)` (`server.py:1518`).
  - Si no hay `location_id` → `_json_error(400, ..., code="GHL_CONTEXT_LOCATION_MISSING", details={...})` (`server.py:1519-1532`).
  - `log_persistent_event("sessions.gohighlevel_context_resolved", ...)`
    (`server.py:1534-1541`).
  - Respuesta 200: `{ok: True, source: "ghl-sso-decrypted", **resolved_context, user_data}`.

### Handler 3 — `POST /v1/sessions/gohighlevel/session` (`server.py:1552-1588`)

- Decorador: `@app.post("/v1/sessions/gohighlevel/session", tags=[...], summary=..., description=...)`
- Dependencias FastAPI: `payload: _GoHighLevelSessionPayload` y `request: Request`.
- Lógica:
  - `record = runtime.get_ghl_connection_by_location(location_id=payload.location_id)`
    (`server.py:1568`; método en `server.py:967-969`, llama
    `unit_of_work.ghl_connection_store.get_by_location_id(location_id)`).
  - `connected = record is not None and bool(record.access_token.strip())`.
  - `log_persistent_event("sessions.gohighlevel_session_checked", ...)` (`server.py:1570-1577`).
  - Respuesta 200: `{ok: True, location_id, user_id, connected, has_token, agency_id}`.

### Handler 4 — `POST /v1/sessions/gohighlevel/test` (`server.py:1590-1654`)

- Decorador: `@app.post("/v1/sessions/gohighlevel/test", tags=[...], summary=..., description=...)`
- Dependencias FastAPI: `payload: _GoHighLevelLocationPayload` y `request: Request`.
- Lógica:
  - `record = runtime.get_ghl_connection_by_location(location_id=payload.location_id)` (`server.py:1606`).
  - Si no existe / token vacío → `_json_error(404, ..., code="GHL_CONNECTION_NOT_FOUND", hint=..., details={...})` (`server.py:1607-1614`).
  - `runtime.test_gohighlevel_connection(location_id=record.location_id, access_token=record.access_token)` (`server.py:1615-1619`; método en `server.py:1296-1309` — instancia un `GoHighLevelClient` legacy bajo `services/publishing/social_delivery/`).
  - Maneja `ApplicationError` → `_json_error(502, ..., code="GHL_CONNECTION_TEST_FAILED", hint=..., details={...})` (`server.py:1620-1627`).
  - `log_persistent_event("sessions.gohighlevel_connection_tested", ...)` (`server.py:1639-1645`).
  - Respuesta 200: `{ok: True, location_id, account_count, accounts: [{id, name, platform, account_type, is_expired}, ...]}`.

---

## 2. Use cases involucrados

### Ya existente

- `DecodeGoHighLevelSessionUseCase` en
  `modules/publishing/application/use_cases/decode_gohighlevel_session.py:16-83`.
- Función helper `extract_gohighlevel_user_context_fields(user_data)` en el
  mismo archivo (`decode_gohighlevel_session.py:86-105`).
- Hoy se invoca desde `services/transport/http/server.py:83-85` (import) y
  `server.py:1311-1314` (wrapper `runtime.decrypt_gohighlevel_user_context`).

### Use cases nuevos a crear

Los handlers 1, 3 y 4 contienen lógica que hoy vive como métodos en
`WordPressWebhookApplication`. Esos métodos abren UoW directamente y/o
hablan con clientes externos. Para alinear con el patrón
"router → use case → UoW" sugerido por la propia descripción de la feature
y por `docs/architecture.md`, se recomienda crear:

- **`list_provider_sessions`** (verbo `list`, recurso `provider_sessions`) —
  envuelve hoy `WordPressWebhookApplication.list_ghl_connections` (`server.py:971-973`)
  + `to_public_dict()`. Devolvería `(count, items)` listos para el handler 1.
- **`resolve_provider_session_by_location`** (verbo `resolve`, recurso
  `provider_session`) — envuelve `get_ghl_connection_by_location` (`server.py:967-969`).
  Lo usan los handlers 3 y 4.
- **`probe_provider_connection`** (verbo `probe`, recurso `provider_connection`) —
  envuelve `WordPressWebhookApplication.test_gohighlevel_connection`
  (`server.py:1296-1309`) que hoy crea `GoHighLevelClient` y
  `GoHighLevelSocialService` desde
  `services/publishing/social_delivery/`. Esta es lógica que **debe**
  migrar a `modules/publishing/infrastructure/` (cliente HTTP) +
  `modules/publishing/application/use_cases/probe_provider_connection.py`
  (use case). Hoy mismo el cliente es `services/publishing/social_delivery/gohighlevel_client.py`
  — **legacy frozen** según `feature_list.json:11`. El implementer
  debe decidir si:
  - (a) Reusar el cliente legacy temporalmente con import desde el use
    case nuevo (acoplamiento aceptable mientras la feature 5 no lo
    haya movido formalmente), o
  - (b) Bloquear esta feature hasta que 5 lo haya movido.

Recomendación: **(a)**. La descripción de la feature 2 dice "ya existe el
use case decode_gohighlevel_session, así que esta es la primera prueba
del patrón completo (router → use case → UoW)" — implica scope acotado,
no rehacer adaptadores HTTP.

### Nota sobre el verbo

Acotado a la nomenclatura "verbo + recurso por archivo" de
`docs/architecture.md:18`. Si el implementer prefiere otra granularidad
(p.ej. agrupar los 3 nuevos en un solo `manage_provider_sessions.py`)
debe escalar al leader.

---

## 3. Payloads Pydantic

Los tres modelos viven inline en `server.py` con prefijo `_` (clase privada
del módulo) y `model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, ...)`.

| Modelo | Líneas | Usado en handler |
|--------|--------|------------------|
| `_GoHighLevelSessionPayload`  | `server.py:587-608` | `POST /session`  |
| `_GoHighLevelLocationPayload` | `server.py:611-623` | `POST /test`     |
| `_GoHighLevelContextPayload`  | `server.py:626-642` | `POST /context`  |

Ninguno es reutilizado fuera de su handler. Todos son inline (clase top-level
del módulo `server.py`, pero sin reutilización cross-module).

**Migración a `modules/publishing/transport/payloads/sessions.py`:**

- Renombrar quitando el guion bajo (públicos): `GoHighLevelSessionPayload`,
  `GoHighLevelLocationPayload`, `GoHighLevelContextPayload`.
- El módulo destino `modules/publishing/transport/payloads/` **no existe
  todavía** — el implementer debe crearlo (tampoco hay
  `modules/publishing/transport/payloads/__init__.py`).
- Los tres modelos importan `pydantic.{AliasChoices, BaseModel, ConfigDict, Field}`.
  El `_GoHighLevelContextPayload` usa `AliasChoices("encrypted_data", "encryptedData")`
  (`server.py:640`) — preservar para no romper el frontend.
- Considerar añadir un response model público también (`SessionStatusResponse`,
  `ContextResolvedResponse`, `ConnectionTestResponse`) si el implementer
  quiere tipar la salida; hoy son dicts.

---

## 4. Helpers transversales que invoca

Importados en `server.py` desde `apps/api/`:

- `apps.api.error_handlers.json_error` (`server.py:93`, alias `_json_error`)
  — usado en handlers 2 (`server.py:1502, 1510, 1520`) y 4 (`server.py:1608, 1621`).
- `apps.api.admin_auth.format_client` (`server.py:91`, alias `_format_client`)
  — usado en handlers 2/3/4 (`server.py:1537, 1573, 1642`) para
  `log_persistent_event`.
- `register_error_handlers` (`server.py:93`) — se invoca en `app_factory.build_api_app`
  (`apps/api/app_factory.py:101`); el router nuevo lo hereda automáticamente.
- `register_logging_middleware` (`server.py:100`) — middleware global; el
  router nuevo lo hereda automáticamente.

Importado desde `core/` (legacy, pero todavía vigente para los handlers):

- `core.logging.log_persistent_event` (`server.py:80`) — usado en handlers
  2 (`1534`), 3 (`1570`) y 4 (`1639`).
- `shared.observability` ya expone `log_persistent_event` también (ver
  `apps/api/admin_auth.py:12-16`); el router nuevo debería importar de
  `shared.observability` en lugar de `core.logging`.

Helpers internos del server:

- `_get_runtime(request)` en `server.py:4012-4013` — devuelve
  `request.app.state.runtime`. El router nuevo necesita la misma utilidad
  (o el implementer reescribe los handlers para depender de un objeto más
  granular en `app.state` — p.ej. `app.state.publishing_runtime` con
  solo lo que la feature requiere).
- `_get_request_id(request)` en `server.py:4227-4231` — usado en los
  `log_persistent_event(...)` (`server.py:1536, 1572, 1641`). Solo lee
  `request.state.request_id` (lo siembra `register_logging_middleware`).
  Helper trivial; el implementer puede reimplementarlo en el router o en
  `apps/api/admin_auth.py` (donde ya hay `_request_id` privado en
  `apps/api/admin_auth.py:52-56`).

**No usa** `admin_auth.authorize_admin_request` ni `range_response.build_range_response`.
Estas rutas son **públicas** (no llevan bearer admin) — son las únicas que
usa el frontend embebido en HighLevel sin token. Esto es importante: no
añadir gate de admin auth al moverlas.

---

## 5. Imports cruzados peligrosos

El handler 4 (`POST /v1/sessions/gohighlevel/test`) llega vía
`runtime.test_gohighlevel_connection` (`server.py:1296-1309`) a:

- `services.publishing.social_delivery.gohighlevel_client.GoHighLevelClient`
  (`server.py:108`).
- `services.publishing.social_delivery.gohighlevel_social_service.GoHighLevelSocialService`
  (`server.py:109`).

Estas dos clases viven bajo `services/publishing/` que es **legacy frozen**
(`feature_list.json:11`). En el patrón objetivo deberían vivir bajo
`modules/publishing/infrastructure/`. Como la feature 2 NO incluye su
movida, hay tres opciones:

- (a) El use case nuevo (`probe_provider_connection`) importa directamente
  desde `services.publishing.social_delivery.*` (mantiene el acoplamiento
  legacy hasta que feature 5 o 9 lo desuba). **Implica** que un módulo
  (`modules/publishing/application`) importa de `services/` — está dentro
  de las reglas porque `services/` no es un `modules/<otro>/`.
- (b) Mover el adaptador a `modules/publishing/infrastructure/` como
  subtarea de esta feature. **Recomendado escalar al leader** porque es
  scope creep.
- (c) Diferir esta feature hasta que 5 esté hecha.

`server.py:84` ya importa desde
`modules.publishing.application.use_cases.decode_gohighlevel_session` —
ese import sí es limpio.

**No hay** imports a `modules/<otro>/application` o
`modules/<otro>/infrastructure` desde la zona de los 4 handlers.

---

## 6. Tests existentes que tocan estas rutas

Archivo: `tests/integration/test_http_transport.py`.

Tests que llaman directamente a `/v1/sessions/gohighlevel/*`:

| Línea | Nombre | Path bajo prueba |
|-------|--------|------------------|
| 261-281 | `test_gohighlevel_session_returns_agency_id_when_connection_is_saved` | `POST /v1/sessions/gohighlevel/session` |
| 283-297 | `test_gohighlevel_session_reports_disconnected_when_no_connection`    | `POST /v1/sessions/gohighlevel/session` |
| 299-329 | `test_gohighlevel_context_decrypts_custom_page_payload`               | `POST /v1/sessions/gohighlevel/context` |
| 331-342 | `test_gohighlevel_context_requires_shared_secret`                     | `POST /v1/sessions/gohighlevel/context` |

Cobertura faltante (no hay tests específicos):

- `GET /v1/sessions/gohighlevel/tokens` — sin test directo.
- `POST /v1/sessions/gohighlevel/test` — sin test directo (la lógica
  hermana del admin endpoint sí existe).

`DecodeGoHighLevelSessionUseCase` no tiene tests unitarios separados
(`grep DecodeGoHighLevelSessionUseCase` en `tests/` no encuentra archivos).
Su comportamiento solo se prueba indirectamente vía
`test_gohighlevel_context_*`.

El `_build_client` del fixture (`test_http_transport.py:97-129`) construye
`WordPressWebhookApplication` y llama `create_fastapi_app(application=runtime)`.
Esto se rompe el día que la feature 9 borre `WordPressWebhookServer`, pero
para esta feature 2 sigue vigente — los tests deben seguir pasando contra
el `app_factory` actual. La acceptance criteria pide además
`tests/integration/publishing/test_gohighlevel_session_router.py` (nuevo),
que probará el router aislado con TestClient sobre un `FastAPI()` mínimo.

**Red de seguridad antes de mover:** ejecutar
`pytest tests/integration/test_http_transport.py -k gohighlevel -q` antes
y después del cambio. Debe pasar igual.

---

## 7. Acoplamiento cross-feature

La feature 5 (`publishing_connections_router`) saca el CRUD admin
`/v1/admin/agencies/{id}/ghl-connection` (handlers en `server.py:2199-2349`,
ver sección dedicada en `server.py:2198`). Los puntos de acoplamiento con
la feature 2:

- **Mismo store**: ambos features pasan por
  `unit_of_work.ghl_connection_store` (feature 2:
  `list_connections`/`get_by_location_id`; feature 5:
  `upsert`/`delete_by_agency_id`/`get_by_agency_id`/`require_for_agency`,
  ver `server.py:951-982`). Ningún módulo de los nuevos importa al otro;
  cada uno abre su propio UoW. Sin acoplamiento de import, solo
  acoplamiento de tabla (`provider_connections`).
- **Mismo cliente HTTP**: ambos features llaman
  `runtime.test_gohighlevel_connection` (`server.py:1296-1309`). Feature 2
  lo usa en handler 4; feature 5 lo usa en `test_admin_agency_ghl_connection`
  (`server.py:2302-2349`, especialmente líneas `2319-2322`). El cliente es
  el mismo `GoHighLevelClient` en `services/publishing/social_delivery/`.
  Si la feature 5 mueve el cliente a `modules/publishing/infrastructure/`,
  la feature 2 (si se hace antes) tendrá que actualizar su import.
  Coordinación: **el implementer de la feature 2 debe asumir que el
  cliente sigue en `services/publishing/social_delivery/` y dejar TODO
  para que la feature 5 unifique**.
- **Mismo DTO de salida**: ambos features serializan `accounts` con la
  misma forma `{id, name, platform, account_type, is_expired}`
  (`server.py:1629-1638` vs `server.py:2331-2340`). Candidato a payload
  compartido en `modules/publishing/transport/payloads/connections.py`
  (lo crea feature 5) o duplicación temporal en
  `modules/publishing/transport/payloads/sessions.py` (lo crea feature 2).
  **Recomendado:** duplicar inicialmente; la feature 5 unifica al moverse.

Resumen: **acoplamiento real está solo en el cliente HTTP legacy y en el
DTO de accounts**. Ningún acoplamiento de Python imports entre los dos
routers.

---

## 8. LoC estimado a mover

| Bloque | Líneas en server.py | LoC aprox |
|--------|---------------------|-----------|
| Pydantic `_GoHighLevelSessionPayload`     | 587-608   | ~22 |
| Pydantic `_GoHighLevelLocationPayload`    | 611-623   | ~13 |
| Pydantic `_GoHighLevelContextPayload`     | 626-642   | ~17 |
| Handler 1 `list_gohighlevel_session_connections` | 1461-1478 | ~18 |
| Handler 2 `resolve_gohighlevel_session_context`  | 1480-1550 | ~71 |
| Handler 3 `create_gohighlevel_session`           | 1552-1588 | ~37 |
| Handler 4 `test_gohighlevel_session_connection`  | 1590-1654 | ~65 |

**Total a mover**: ~243 LoC fuera de server.py (4 handlers + 3 modelos).

Adicionalmente:

- ~30 LoC nuevos en `modules/publishing/application/use_cases/` (3 use
  cases ligeros — `list_provider_sessions`, `resolve_provider_session_by_location`,
  `probe_provider_connection`).
- ~50-80 LoC en el archivo nuevo `modules/publishing/transport/http/sessions_router.py`
  (router + import wiring + posibles helpers locales tipo `_request_id`).
- ~15 LoC modificados en `apps/api/app_factory.py` (registrar el nuevo router).
- ~80-120 LoC en `tests/integration/publishing/test_gohighlevel_session_router.py`
  (4 tests para los 4 endpoints, mayormente reutilizando seeds de
  `tests/support/postgres.py`).

Total feature ~400-500 LoC tocados/creados, ~250 movidos limpios.

---

## 9. Riesgos / blockers conocidos

1. **El cliente legacy `services/publishing/social_delivery/gohighlevel_client.py`
   queda sin migrar.** El handler 4 lo necesita. Hay que escalar al leader
   si la regla "código nuevo no entra en `services/`" debe interpretarse
   como "tampoco debe **importar** desde nuevos use cases bajo `modules/`".
   Mi recomendación pragmática: **importar desde el use case nuevo** y
   dejar TODO comment apuntando a feature 5/9.

2. **`log_persistent_event` se importa hoy desde `core.logging`
   (`server.py:80`) pero `apps/api/admin_auth.py` lo importa desde
   `shared.observability` (`apps/api/admin_auth.py:12-16`).** Para no
   reintroducir `core.logging` en `modules/publishing/`, el router nuevo
   debe usar `shared.observability.log_persistent_event`. Verificar que
   ambas funciones son idénticas; si no, escalar.

3. **El `WordPressWebhookApplication` sigue siendo el portador del
   `unit_of_work_factory` y del `gohighlevel_app_shared_secret`**
   (`server.py:678-718`). El use case nuevo necesita acceso a un UoW y
   al shared_secret. El patrón actual ya existente en
   `decode_gohighlevel_session.py:17` es **inyectar el shared_secret en el
   constructor del use case**. Para el UoW, hay que inyectar
   `shared.db.DatabaseUnitOfWork` (`ARCHITECTURE.md:115`). El router
   resuelve la dependencia de UoW por construcción (constructor del
   router) o por dependencia FastAPI; el implementer debe alinearse con
   el patrón de feature 1. **Alerta**: el código actual usa
   `unit_of_work.ghl_connection_store` (legacy) — `ARCHITECTURE.md:125`
   propone `uow.publishing.connections.get_with_secrets(...)`. Verificar
   si el repo namespacado ya está implementado o si hay que seguir con
   `ghl_connection_store` por compatibilidad.

4. **El test fixture `tests/integration/test_http_transport.py` aún
   llama `create_fastapi_app(application=...)`** (`test_http_transport.py:129`).
   Cuando los handlers se muevan, los tests existentes deben seguir
   pasando — `app_factory.build_api_app()` debe componer `WordPressWebhookServer`
   **más** el nuevo router, de modo que el `FastAPI()` resultante
   exponga ambas familias durante la transición. Si el implementer
   decide que `create_fastapi_app` ya no monte estas rutas, los 4 tests
   listados en sección 6 fallarán salvo que el `_build_client` del
   fixture también monte el router nuevo. **Coordinar con el approach
   del implementer.**

5. **El renombrado `/mvp/gohighlevel/*` → `/v1/sessions/gohighlevel/*`
   ya ocurrió** (ver REFACTOR_STATUS.md:224). La feature 2 NO renombra
   nada — solo mueve archivos. Si el implementer interpreta literalmente
   `feature_list.json:42` ("/mvp/gohighlevel/*"), buscará rutas que no
   existen. Confirmar con el leader que el target real es
   `/v1/sessions/gohighlevel/*`.

6. **No hay tests para `GET /tokens` ni para `POST /test`.** El
   acceptance criteria pide
   `tests/integration/publishing/test_gohighlevel_session_router.py` —
   el implementer debe **añadir tests para esos dos endpoints también**,
   no solo migrar los 4 existentes.
