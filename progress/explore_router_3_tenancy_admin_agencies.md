# Explore Report — Feature 3: tenancy_admin_agencies_router

- **Feature id / name:** 3 — `tenancy_admin_agencies_router`
- **Modo:** read-only (este informe no modifica código).
- **Objetivo:** mover el CRUD `/admin/agencies` y `/admin/agencies/{id}` a
  `modules/tenancy/transport/http/admin_agencies_router.py` con cinco use cases
  bajo `modules/tenancy/application/use_cases/`.

> Todas las rutas se registran sobre el prefix dinámico
> `application.admin_access_policy.base_path` (= `ADMIN_API_BASE_PATH`,
> default `/v1/admin`). En la documentación FastAPI quedan como
> `/v1/admin/agencies` / `/v1/admin/agencies/{agency_id}`.

---

## 1. Rutas y handlers en `services/transport/http/server.py`

Archivo: `c:/Users/4pm/Desktop/4reels/4reels back/services/transport/http/server.py`
(4513 LoC).

| # | Método | Path completo                                                  | Handler                | Decor:line | Body L:F  | Body params               | Path params  | Query params | Deps inyectadas              |
|---|--------|----------------------------------------------------------------|------------------------|-----------|-----------|---------------------------|--------------|--------------|------------------------------|
| 1 | GET    | `${admin_base}/agencies`                                       | `list_admin_agencies`  | 1895      | 1905-1921 | —                         | —            | —            | `request: Request` (vía `_get_runtime`) |
| 2 | POST   | `${admin_base}/agencies`                                       | `create_admin_agency`  | 1923      | 1935-1969 | `_AdminAgencyCreatePayload` | —          | —            | `payload`, `request: Request` |
| 3 | GET    | `${admin_base}/agencies/{agency_id}`                           | `get_admin_agency`     | 1971      | 1982-2007 | —                         | `agency_id`  | —            | `agency_id: str`, `request: Request` |
| 4 | PATCH  | `${admin_base}/agencies/{agency_id}`                           | `update_admin_agency`  | 2009      | 2019-2053 | `_AdminAgencyUpdatePayload` | `agency_id` | —          | `agency_id`, `payload`, `request: Request` |
| 5 | DELETE | `${admin_base}/agencies/{agency_id}`                           | `delete_admin_agency`  | 2055      | 2066-2082 | —                         | `agency_id`  | —            | `agency_id`, `request: Request` |

Notas sobre el pegamento de handler:

- Todos llaman `runtime = _get_runtime(request)`
  (`server.py:4012`) y delegan auth a
  `_authorize_admin_request(request, runtime)`
  (`server.py:4197`, wrapper de 1 línea sobre
  `apps.api.admin_auth.authorize_admin_request`).
- Los handlers actuales toman el `runtime` (`WordPressWebhookApplication`)
  vía `request.app.state.runtime`. En el router nuevo se sustituye por una
  factory de UoW (`uow_factory`) inyectada también en `app.state`, p. ej.
  `request.app.state.uow_factory`, **o** vía dependencia FastAPI
  `Depends(get_unit_of_work)`. Hay precedente del segundo patrón en feature 2
  (sessions_router): no tocar `_get_runtime`, exponer la UoW directamente.
- POST 201 con `{"status": "created", "agency": ...}` (server.py:1966-1969).
- GET-list 200 con `{"items": [...], "count": N}` (server.py:1918-1921).
- GET-detail 200 con `{"agency": ..., "sources": [...], "ghl_connection": ..., "reel_profile": ...}` (server.py:1999-2007).
- PATCH 200 con `{"status": "updated", "agency": ...}` (server.py:2050-2053).
- DELETE 200 con `{"status": "deleted", "agency_id": ...}` (server.py:2079-2082).

Errores devueltos hoy:

- 401 / 503 / 404 vía `_authorize_admin_request` (admin auth).
- 404 `ADMIN_AGENCY_NOT_FOUND` cuando `runtime.get_agency()` o
  `runtime.delete_agency()` no encuentra fila (server.py:1990-1995, 2031-2036, 2073-2078).
- 500 `ADMIN_AGENCY_CREATE_FAILED` en `create_admin_agency` solo si
  `runtime.create_agency()` lanza `ApplicationError`
  (server.py:1957-1963). Hoy nunca lo lanza (el store no captura
  IntegrityError); la rama queda como salvavidas.
- POST y PATCH no validan duplicación de `slug` activamente — la DB
  responderá con `IntegrityError`/`UniqueViolation` que actualmente
  burbujea hasta `register_error_handlers` (apps/api/error_handlers.py).
  El use case nuevo puede normalizar este caso a `ValidationError` con
  `code="ADMIN_AGENCY_SLUG_TAKEN"` (sugerido).

---

## 2. Repositorio existente

Hay **dos** repositorios, uno legacy (frozen) y uno nuevo:

### Nuevo (canónico para Phase 2)

`c:/Users/4pm/Desktop/4reels/4reels back/modules/tenancy/infrastructure/agency_repository.py`

- Clase `AgencyRepository(ModuleRepository)` — recibe `Session` SQLAlchemy
  vía el UoW. NO commitea por sí sola (UoW commitea en `__exit__`).
- Métodos públicos:
  - `get_by_id(agency_id: str) -> Agency | None` (l.40)
  - `get_by_slug(slug: str) -> Agency | None` (l.53)
  - `list_all() -> tuple[Agency, ...]` (l.66) — ordenado por `name ASC`
  - `create(*, agency_id, name, slug, timezone="UTC", status="active") -> None` (l.75)
  - `update(*, agency_id, name, slug, timezone, status) -> None` (l.101)
  - `delete(agency_id: str) -> bool` (l.125)
- Devuelve `modules.tenancy.domain.Agency` (dataclass frozen, slots —
  `modules/tenancy/domain/agency.py:12-21`).
- Expuesto en el UoW como `uow.tenancy.agencies`
  (`shared/db/uow.py:64`, `136`).

### Legacy (frozen, solo lectura)

`c:/Users/4pm/Desktop/4reels/4reels back/repositories/stores/agency_store.py`

- Clase `AgencyStore(PostgresRepositoryBase)` con métodos
  `get_by_id`, `get_by_slug`, `list_agencies`, `create_agency`,
  `update_agency`, `delete_agency` (líneas 38, 69, 100, 142, 172, 200).
- Devuelve `AgencyRecord` (dataclass legacy, l.18-26 — misma forma que
  `modules.tenancy.domain.Agency`).
- **No usar**. Queda solo para que la feature 17 lo borre.

> Diferencia de naming: en el repo nuevo los métodos son `list_all/create/update/delete`,
> en el legacy son `list_agencies/create_agency/update_agency/delete_agency`.
> El use case orquesta el repo nuevo; mantener naming corto en el repo es OK.

---

## 3. Use cases sugeridos

Ubicación: `modules/tenancy/application/use_cases/`.

### `create_agency.py` — `CreateAgencyUseCase`

- **Inputs (DTO `CreateAgencyInput`)**: `name: str`, `slug: str | None = None`,
  `timezone: str | None = None`, `status: str | None = None`.
- **Comportamiento (hoy inline en server.py:1944-1968):**
  - Genera `agency_id = str(uuid4())`.
  - Calcula `slug = slugify(payload.slug or payload.name) or slugify(f"agency-{uuid4().hex[:8]}")`.
    - El helper `_slugify_admin` (server.py:4168-4172) — regex
      `[^a-z0-9]+` → `-`, strip — debe migrar al use case (privado dentro
      del módulo, no exportable cross-module).
  - Defaults: `timezone="Europe/Dublin"`, `status="active"` (lower-cased).
  - Llama `uow.tenancy.agencies.create(agency_id=…, …)`.
  - Hace re-`get_by_id(agency_id)` para devolver la fila persistida.
- **Retorna**: `Agency` (dataclass del dominio).
- **Errores**: traducir `IntegrityError` (slug duplicado, FK) →
  `ValidationError(code="ADMIN_AGENCY_SLUG_TAKEN" | "ADMIN_AGENCY_CREATE_FAILED")`.
  La rama 500 actual (server.py:1958) cubre solo el caso `ApplicationError`
  ya tipado, así que es OK conservarla 1:1.

### `list_agencies.py` — `ListAgenciesUseCase`

- **Inputs**: ninguno.
- **Comportamiento (hoy inline en server.py:1911-1917):** llama
  `uow.tenancy.agencies.list_all()` y para cada agency carga sources +
  GHL + reel_profile.
- **PROBLEMA cross-feature** (ver §6 y §8): hoy el handler hidrata
  `sources`, `ghl_connection` y `reel_profile`. Estos pertenecen a otros
  módulos (`ingestion`, `publishing`, `configuration`).
  - `runtime.list_sources_for_agency()` lee
    `wordpress_source_store.list_sources_for_agency` (legacy).
  - `runtime.get_ghl_connection_by_agency()` (server.py:963).
  - `runtime.get_reel_profile()` (server.py:984).
- **Retorna**: `tuple[AgencySummary, ...]` donde `AgencySummary` es un
  dataclass del use case con `agency` + counts/punteros, **no** los
  modelos cross-módulo. La hidratación de `sources` / `ghl_connection`
  / `reel_profile` debe quedar en el handler (que SÍ puede usar otras
  namespaces del UoW: `uow.tenancy`, `uow.ingestion`, `uow.publishing`,
  `uow.configuration`) o, mejor, dejar el use case `list_agencies`
  devolviendo solo `tuple[Agency, ...]` y que el handler haga la
  hidratación con varios use cases (`list_sources_for_agency` de
  ingestion, `get_provider_connection` de publishing, `get_reel_defaults`
  de configuration). Esta segunda opción respeta la regla de
  "un módulo no importa otro `application/`".
- **Recomendación firme:** `ListAgenciesUseCase.execute()` devuelve solo
  `tuple[Agency, ...]`. La función serializadora del router
  (`_serialize_agency_summary`) se queda en el router pero llama
  use cases de los otros módulos (que las features 4/5/6 crearán).
  Mientras esos use cases no existan (estamos en feature 3), el router
  puede temporalmente leer directamente de `uow.ingestion.sources`,
  `uow.publishing.connections`, `uow.configuration.brand` desde el
  handler — **eso lo permite la regla** (transport puede orquestar
  varios repos a través del UoW; lo prohibido es que el módulo importe
  el `application/` de otro). Documentarlo así en el impl report.

### `get_agency.py` — `GetAgencyUseCase`

- **Inputs**: `agency_id: str`.
- **Comportamiento (hoy inline en server.py:1988-2006):** llama
  `uow.tenancy.agencies.get_by_id(agency_id)`. Si `None` → lanzar
  `ResourceNotFoundError("The agency does not exist.", code="ADMIN_AGENCY_NOT_FOUND",
  context={"agency_id": agency_id})`. Esto deja el handler limpio (el
  exception handler global mapea 404 automáticamente).
- **Retorna**: `Agency`.
- La hidratación de `sources` / `ghl_connection` / `reel_profile` se trata
  igual que en `list_agencies` (ver arriba).

### `update_agency.py` — `UpdateAgencyUseCase`

- **Inputs (DTO `UpdateAgencyInput`)**: `agency_id: str`, `name: str | None`,
  `slug: str | None`, `timezone: str | None`, `status: str | None`.
- **Comportamiento (hoy inline en server.py:2029-2049):**
  - Carga la agency. Si no existe → `ResourceNotFoundError(... code="ADMIN_AGENCY_NOT_FOUND")`.
  - Aplica patch parcial. Reglas exactas a preservar:
    - `name = payload.name if payload.name is not None else current.name`
    - `slug = slugify(payload.slug or payload.name or current.slug)
        if payload.slug is not None or payload.name is not None
        else current.slug`
      (server.py:2041-2045).
    - `timezone = payload.timezone if payload.timezone is not None else current.timezone`
    - `status = (payload.status or current.status).lower()`
- **Retorna**: `Agency` actualizada (re-leída tras el `update`).
- **Errores**: igual que create — `IntegrityError` por slug colisión →
  `ValidationError(code="ADMIN_AGENCY_SLUG_TAKEN")`.

### `delete_agency.py` — `DeleteAgencyUseCase`

- **Inputs**: `agency_id: str`.
- **Comportamiento (hoy inline en server.py:2071-2078):** llama
  `uow.tenancy.agencies.delete(agency_id)`. Si devuelve `False` →
  `ResourceNotFoundError("The agency does not exist.", code="ADMIN_AGENCY_NOT_FOUND",
  context={"agency_id": agency_id})`.
- **Retorna**: `None` (idempotencia: el handler responde 200 con
  `{"status": "deleted", "agency_id": ...}`).
- **Cascada**: confiar en FK ON DELETE CASCADE del schema (sources,
  ghl_connection, reel_profile, etc.). Documentado en server.py:2059-2064.

---

## 4. Payloads Pydantic

### Existentes en server.py (a migrar)

| Modelo                          | Path                       | Líneas     | Reutilizable? |
|---------------------------------|----------------------------|------------|---------------|
| `_AdminAgencyCreatePayload`     | `services/transport/http/server.py` | 167-186 | Sí — copiar a `modules/tenancy/transport/payloads/agencies.py` y renombrar a `AdminAgencyCreatePayload` (público) |
| `_AdminAgencyUpdatePayload`     | `services/transport/http/server.py` | 189-206 | Sí — copiar como `AdminAgencyUpdatePayload` |

Campos:

```python
class AdminAgencyCreatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, json_schema_extra={...})
    name: str = Field(min_length=1, ...)
    slug: str | None = None
    timezone: str | None = None
    status: str | None = None

class AdminAgencyUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, ...)
    name: str | None = None
    slug: str | None = None
    timezone: str | None = None
    status: str | None = None
```

### Response payloads

No hay modelos Pydantic de respuesta — el server hoy devuelve
`JSONResponse` con dicts ad-hoc construidos por
`_serialize_agency` (server.py:4132-4143) y
`_serialize_agency_summary` (server.py:4146-4162). Se pueden mantener
como helpers de serialización en el router (no es obligatorio crear
modelos response Pydantic — el patrón actual y la feature 2 los siguen
sin tipar la salida).

> El resto de payloads en server.py:209-... (`_AdminAgencySourceUpsertPayload`,
> `_AdminGhlConnectionUpsertPayload`, etc.) NO entran en feature 3 — los
> mueven features 4 y 5.

---

## 5. Helpers transversales que invocan los handlers

Todos están en `apps/api/`:

- `apps/api/admin_auth.py`:
  - `AdminAccessPolicy` (dataclass) — leído de `app.state.runtime.admin_access_policy`
    o, en el nuevo modelo, expuesto vía `app.state.admin_access_policy`.
  - `authorize_admin_request(request, policy)` — el handler nuevo lo
    llama y, si devuelve `JSONResponse`, lo retorna directamente.
- `apps/api/error_handlers.py`:
  - `json_error(status_code, message, *, code, hint, details)` — usado
    para los 404 y 500 inline. Si los use cases lanzan `ApplicationError`
    bien tipados, podemos delegar todo al handler global registrado en
    `register_error_handlers(app)` y eliminar los `_json_error()` inline.

### Helpers locales del server que se mueven

Estos están hoy en `server.py` y deben quedar como utilidades **privadas
del router** (no exportadas) o en el use case:

- `_slugify_admin` (server.py:4168-4172) — utilidad pura. **Migrar al
  módulo** como helper privado del use case
  (`modules/tenancy/application/use_cases/_slug.py` o inline en
  `create_agency.py` / `update_agency.py`).
- `_serialize_agency` (server.py:4132-4143) — privado del router.
- `_serialize_agency_summary` (server.py:4146-4162) — privado del router.
  Usa `_serialize_wordpress_source_details` (server.py:4175-4194) → ese
  helper se queda en server.py por ahora (lo necesita el router de
  ingestion en feature 4) o **se duplica temporalmente** en el router de
  tenancy hasta que feature 4 lo extraiga oficialmente. Recomendación:
  duplicar la función en `modules/tenancy/transport/http/_serializers.py`
  con un `# TODO Feature 4: importar desde modules/ingestion/transport`
  (los serializers son data-shape: ningún acoplamiento de lógica).

### Logging / observability

Los handlers actuales **no** llaman a `log_persistent_event` ni
`_log_admin_failure` — esa instrumentación existe en otros routes pero
en `/admin/agencies` no se aplica. El router nuevo puede mantener la
sobriedad actual (sin logs persistentes adicionales). El middleware de
logging (`apps/api/logging_middleware.register_logging_middleware`) ya
captura request/response a nivel app.

---

## 6. Imports cruzados peligrosos

**Verificación**: los handlers `list_admin_agencies`, `create_admin_agency`,
`get_admin_agency`, `update_admin_agency`, `delete_admin_agency` del
server.py:1895-2082 **NO importan** ni `from modules.<otro>.application`
ni `from modules.<otro>.infrastructure`. Solo invocan métodos del
`runtime` (`WordPressWebhookApplication`):

- `runtime.list_agencies()` → `uow.agency_store.list_agencies()` (legacy).
- `runtime.list_sources_for_agency(agency_id=...)` → `uow.wordpress_source_store.list_sources_for_agency` (legacy).
- `runtime.get_ghl_connection_by_agency(agency_id=...)` → store legacy (ver server.py:963).
- `runtime.get_reel_profile(agency_id=...)` → store legacy (ver server.py:984).
- `runtime.get_agency(...)`, `create_agency(...)`, `update_agency(...)`, `delete_agency(...)` (server.py:1036-1058).

En el router nuevo se sustituyen por:

- `uow.tenancy.agencies.{get_by_id,list_all,create,update,delete}` (canónico).
- Para hidratar el detail en `get_admin_agency`: `uow.ingestion.sources`,
  `uow.publishing.connections`, `uow.configuration.{brand,defaults,automation,social_templates,music}`.
  - **Esto es legal** porque el `transport/` del módulo `tenancy` puede
    leer de cualquier **repositorio** del UoW (los repos son de
    `infrastructure/`, sí, pero la composición pasa por `shared/db/uow.py`,
    que es el punto neutral por contrato — ver
    `ARCHITECTURE.md:114-128` y `docs/architecture.md:28-31`).
  - **Lo prohibido** sería `from modules.publishing.application.use_cases…`
    o `from modules.ingestion.infrastructure…` directamente.

> Riesgo: si el implementer instintivamente importa de
> `modules/publishing/application/use_cases/get_provider_connection.py`
> (no existe aún), rompe la regla. Hay que dejar **escrito** que para
> feature 3 se accede a la hidratación cross-módulo **solo** vía
> namespaces del UoW.

---

## 7. Tests existentes que tocan estas rutas

Único archivo: `c:/Users/4pm/Desktop/4reels/4reels back/tests/integration/test_http_transport.py`.

| Test                                                | Línea | Qué cubre                                                       |
|-----------------------------------------------------|-------|-----------------------------------------------------------------|
| `test_admin_routes_require_bearer_token`            | 346   | `GET /v1/admin/agencies` sin `Authorization` → 401 + `ADMIN_AUTH_REQUIRED`. |
| `test_admin_routes_can_disable_auth_for_testing`    | 354   | `GET /v1/admin/agencies` con `disable_auth_for_testing=True` → 200 + count 0. |
| `test_admin_can_create_get_and_delete_an_agency`    | 369   | `POST /v1/admin/agencies` 201 → `GET /v1/admin/agencies/{id}` 200 → `DELETE /v1/admin/agencies/{id}` 200; valida con `AgencyStore` legacy. |

Este último test (l.395) usa
`from repositories.stores.agency_store import AgencyStore` (l.27). En
el test nuevo (`tests/integration/tenancy/test_admin_agencies_router.py`)
se debe sustituir por `DatabaseUnitOfWork(...).tenancy.agencies.get_by_id(...)`.

**Tests que ejercitan el repo de agencies directamente:** ninguno
encontrado bajo `tests/` para la versión nueva (`AgencyRepository`).
`grep` de `AgencyStore|AgencyRecord` solo aparece en
`tests/integration/test_http_transport.py:27,395` (legacy).
`AgencyRepository` no aparece referenciado en ningún test.

> El test `test_admin_can_create_get_and_delete_an_agency` debe seguir
> verde tras feature 3 (la URL no cambia). El nuevo
> `tests/integration/tenancy/test_admin_agencies_router.py` puede
> duplicarlo y ampliar la cobertura con: `PATCH` parcial,
> `GET` con detail eager-loaded de sources/ghl/profile, slug colisión,
> 404 en update/delete.

---

## 8. Acoplamiento cross-feature (4, 5, 6, 7) y prefix sharing

**Hallazgo:** en server.py cada handler se registra con su path completo
construido a partir de `f"{application.admin_access_policy.base_path}/agencies/..."`
(ver server.py:1896, 1924, 1972, 2010, 2056, 2086, 2200, 2361, 2465,
2578, 2684, 2801, 2895, 3376, 3450). **No hay APIRouter compartido**: cada
ruta es un decorador independiente sobre la misma `FastAPI` app.

**Consecuencia para feature 3:**

- **Decisión esperada:** el router de feature 3
  (`modules/tenancy/transport/http/admin_agencies_router.py`) debe
  exponer un `APIRouter(prefix=ADMIN_API_BASE_PATH, tags=["Admin · Agencies"])`
  con las cinco rutas `/agencies`, `/agencies/{agency_id}`. **NO**
  intentar montar un sub-router compartido `/admin/agencies/{agency_id}`
  para que las features 4/5/6/7 lo cuelguen — cada feature monta su
  propio `APIRouter(prefix=ADMIN_API_BASE_PATH)` con sus paths
  completos (`/agencies/{agency_id}/sources`,
  `/agencies/{agency_id}/ghl-connection`, `/agencies/{agency_id}/brand`,
  `/agencies/{agency_id}/reels`, …). Esto refleja el patrón actual y
  evita decidir un contrato de prefix-sharing prematuro.
- **Conclusión:** feature 3 NO bloquea ni habilita a las siguientes:
  cada router se monta independiente vía `app_factory.py`. La únical
  pieza compartida es el path-base `ADMIN_API_BASE_PATH`, leído del
  setting.

**Punto a comunicar al implementer:** dejar la firma del módulo lista
para `register_router(app, *, admin_access_policy, uow_factory)` o
similar — el `app_factory` decide en qué orden registra los routers. No
crear dependencia entre módulos vía un `APIRouter(prefix="/admin/agencies/{agency_id}")`
compartido.

---

## 9. LoC estimado a mover

- **Handlers crudos (server.py:1895-2082)**: 188 LoC.
- **Payloads Pydantic (server.py:167-206)**: 40 LoC.
- **Helpers (`_slugify_admin`, `_serialize_agency`, `_serialize_agency_summary`)**:
  ~30 LoC en server.py:4132-4172.
- **Total a extraer**: ≈ **260 LoC** del server.py.

Distribución en destino (estimado):

| Archivo nuevo                                                        | LoC aprox |
|----------------------------------------------------------------------|----------:|
| `modules/tenancy/transport/http/admin_agencies_router.py`            | 180-220   |
| `modules/tenancy/transport/payloads/agencies.py`                     | 50-60     |
| `modules/tenancy/application/use_cases/create_agency.py`             | 50-70     |
| `modules/tenancy/application/use_cases/list_agencies.py`             | 25-35     |
| `modules/tenancy/application/use_cases/get_agency.py`                | 25-35     |
| `modules/tenancy/application/use_cases/update_agency.py`             | 60-80     |
| `modules/tenancy/application/use_cases/delete_agency.py`             | 25-35     |
| `tests/unit/tenancy/test_*` (5 use cases × ~70 LoC)                  | 350-400   |
| `tests/integration/tenancy/test_admin_agencies_router.py`            | 150-200   |

---

## 10. Riesgos / blockers conocidos

1. **El `WordPressWebhookServer` aún registra los routes de agencies
   inline.** Para esta feature el implementer debe
   borrar el bloque server.py:1895-2082 + los payloads server.py:167-206
   + los helpers server.py:4132-4172 que solo sirven a este router.
   `_serialize_wordpress_source_details` (server.py:4175-4194) sigue
   siendo necesario para el GET-detail (hidrata `sources`); duplicarlo
   en el router de tenancy temporalmente hasta feature 4 (riesgo
   bajo: serializer puro de campos string).

2. **`ListAgenciesUseCase` y `GetAgencyUseCase` necesitan datos
   cross-módulo (`sources`, `ghl_connection`, `reel_profile`).** Las
   features 4/5/6 todavía no han creado los use cases correspondientes.
   Solución acordada (§3, §6): el use case de tenancy solo devuelve
   la `Agency`; el **router** consulta los repos cross-módulo vía el
   UoW (legal por arquitectura). Esto permite eliminar el
   `WordPressWebhookApplication.list_sources_for_agency`/
   `get_ghl_connection_by_agency`/`get_reel_profile` en su tiempo
   (features 4-6) sin volver a tocar feature 3.

3. **El test legacy `test_admin_can_create_get_and_delete_an_agency`
   (`tests/integration/test_http_transport.py:369`) importa
   `from repositories.stores.agency_store import AgencyStore`
   (l.27).** Hay que dejar ese test verde pasada feature 3 — el path
   `/v1/admin/agencies/{id}` no cambia, pero la verificación final con
   `AgencyStore.get_by_id` debe seguir funcionando porque
   `repositories/stores/` está frozen, no eliminado, hasta feature 17.
   No requiere ediciones.

4. **`runtime.create_agency()` no maneja colisión de slug.** Riesgo de
   regresión nula: hoy un slug duplicado → 500 sin mapeo. Tras feature 3,
   si el use case no captura `IntegrityError`, el comportamiento es
   idéntico (handler global de errors lo mapea a 500 con `error: ...`).
   Sugerencia opcional: capturar `IntegrityError` y lanzar
   `ValidationError(code="ADMIN_AGENCY_SLUG_TAKEN")` para devolver 400
   con un código accionable. **No es regresión** dejarlo como hoy.

5. **El handler `update_admin_agency` re-deriva el slug desde `name`
   incluso si el cliente solo cambia `timezone`.** Re-leer la lógica de
   server.py:2041-2045: solo se re-deriva el slug si
   `payload.slug is not None or payload.name is not None`. Preservar
   este matiz en `UpdateAgencyUseCase` — es fácil de romper si el
   implementer normaliza con `payload.slug or current.slug`.

6. **El router nuevo necesita acceso a `AdminAccessPolicy` y a un
   `uow_factory`.** El patrón actual los expone vía
   `request.app.state.runtime`. La feature 1 dejó listo
   `apps/api/admin_auth.AdminAccessPolicy` como objeto independiente; el
   `app_factory` puede pasar la policy + UoW factory directamente
   (`app.state.admin_access_policy`, `app.state.uow_factory`) y el router
   los lee con un helper `Depends(...)`. Preferir esto sobre seguir
   pasando el `runtime` god-object — alineado con el spirit de Phase 2.

7. **Mientras feature 9 no cierre, server.py sigue activo.** El bloque
   eliminado debe quedar verdaderamente borrado; si por accidente
   queda registrado por server.py + por el router nuevo, FastAPI lanza
   una `RuntimeError` por path duplicado al startup. Verificar tras la
   extracción con `python -m apps.api --check`.

---

## Anexo — punteros rápidos

| Asunto                                       | Path:line                                                                          |
|----------------------------------------------|------------------------------------------------------------------------------------|
| Handler GET list                             | `services/transport/http/server.py:1895-1921`                                      |
| Handler POST create                          | `services/transport/http/server.py:1923-1969`                                      |
| Handler GET detail                           | `services/transport/http/server.py:1971-2007`                                      |
| Handler PATCH update                         | `services/transport/http/server.py:2009-2053`                                      |
| Handler DELETE                               | `services/transport/http/server.py:2055-2082`                                      |
| Payload create                               | `services/transport/http/server.py:167-186`                                        |
| Payload update                               | `services/transport/http/server.py:189-206`                                        |
| Slug helper                                  | `services/transport/http/server.py:4165-4172`                                      |
| Serializer agency                            | `services/transport/http/server.py:4132-4143`                                      |
| Serializer agency summary                    | `services/transport/http/server.py:4146-4162`                                      |
| Serializer wordpress source                  | `services/transport/http/server.py:4175-4194`                                      |
| Runtime CRUD methods                         | `services/transport/http/server.py:1036-1058`                                      |
| `_get_runtime`                               | `services/transport/http/server.py:4012-4013`                                      |
| `_authorize_admin_request` wrapper           | `services/transport/http/server.py:4197-4201`                                      |
| Repo nuevo (canónico)                        | `modules/tenancy/infrastructure/agency_repository.py:37-133`                       |
| Domain Agency                                | `modules/tenancy/domain/agency.py:12-21`                                           |
| UoW namespace `tenancy.agencies`             | `shared/db/uow.py:62-65,136`                                                       |
| Repo legacy (frozen)                         | `repositories/stores/agency_store.py:29-213`                                       |
| Helper admin auth                            | `apps/api/admin_auth.py:23-169`                                                    |
| Helper json_error                            | `apps/api/error_handlers.py:21-37`                                                 |
| Setting `ADMIN_API_BASE_PATH` (default)      | `settings/app.py:216-219` (`/v1/admin`)                                            |
| Tests existentes                             | `tests/integration/test_http_transport.py:346,354,369`                             |
