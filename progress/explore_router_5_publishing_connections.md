# Explore — Feature 5 `publishing_connections_router`

Feature 5 (`feature_list.json:88-105`) extrae el CRUD de `provider_connections`
(hoy `provider='gohighlevel'`) desde el god-file
`services/transport/http/server.py` a
`modules/publishing/transport/http/connections_router.py` con use cases
`attach/list/get/update/detach_provider_connection`. Tokens cifrados con Fernet
vía `shared/db/security.py`. Cero plaintext en
`provider_connections.secrets_encrypted`.

Read-only mapping. No code edited.

---

## 1. Rutas y handlers en `services/transport/http/server.py`

Solo dos rutas viven literalmente bajo `/admin/agencies/{id}/ghl-connection`
hoy. Hay una tercera "/test" colateral. **No existe GET dedicado** — la lectura
se sirve embebida dentro del listado/detalle de agency. La feature pide
`get_provider_connection`, así que hay que **crear** ese GET.

| # | Método | Path | Handler | Líneas |
|---|---|---|---|---|
| 1 | PUT | `{admin_base}/agencies/{agency_id}/ghl-connection` | `upsert_admin_agency_ghl_connection` | `services/transport/http/server.py:2199-2258` |
| 2 | DELETE | `{admin_base}/agencies/{agency_id}/ghl-connection` | `delete_admin_agency_ghl_connection` | `services/transport/http/server.py:2260-2289` |
| 3 | POST | `{admin_base}/agencies/{agency_id}/ghl-connection/test` | `test_admin_agency_ghl_connection` | `services/transport/http/server.py:2291-2350` |

`{admin_base}` = `application.admin_access_policy.base_path` (`/v1/admin` por
defecto, `services/transport/http/server.py:2200`).

Dependencias compartidas por las tres rutas:

- `runtime = _get_runtime(request)` — fábrica del `WordPressWebhookApplication`
  inyectado en `request.state` (handler usa
  `services/transport/http/server.py:1445` como ejemplo).
- `_authorize_admin_request(request, runtime)` — bearer admin
  (`apps/api/admin_auth.py:59`, importado en
  `services/transport/http/server.py:87-92`).
- `_json_error(...)` — `apps/api/error_handlers.py` (importado en
  `services/transport/http/server.py:93`).
- `runtime.get_agency(agency_id=...)` para el 404
  (`services/transport/http/server.py:2220`).
- `runtime.upsert_ghl_connection(...)` (`services/transport/http/server.py:940-961`)
  → `unit_of_work.ghl_connection_store.upsert_for_agency(...)`.
- `runtime.delete_ghl_connection(agency_id=...)`
  (`services/transport/http/server.py:975-978`).
- `runtime.get_ghl_connection_by_agency(agency_id=...)` y
  `runtime.test_gohighlevel_connection(location_id=, access_token=)`
  (`services/transport/http/server.py:1296-1309`).
- Errores propagados: `ValidationError` y `ApplicationError` de
  `core.errors` (en server.py:68-74), que en el destino deberán mapear a
  `shared.errors.ValidationError` / `ApplicationError`
  (`shared/errors/__init__.py`).

Ojo: cualquier ruta que pueda devolver una `ProviderConnection` cruzada en otra
respuesta — no se extrae ahora pero quedan referencias para no romper:

- `GET /v1/admin/agencies` — `services/transport/http/server.py:1895-1921`
  (devuelve `ghl_connection.to_public_dict()` por agencia, línea 1917 a
  través de `_serialize_agency_summary`).
- `GET /v1/admin/agencies/{id}` —
  `services/transport/http/server.py:1971-2007` (línea 2004).
- `GET /v1/sessions/gohighlevel/tokens` —
  `services/transport/http/server.py:1461-1478` (lista global usando
  `record.to_public_dict()`).
- `POST /v1/sessions/gohighlevel/session` y `/test` —
  `services/transport/http/server.py:1552-1640` (mismo runtime helper).
- `GET ../social-accounts` —
  `services/transport/http/server.py:3387-3445` (lee la connection para llamar
  GHL accounts).
- Webhook ingestion bridge —
  `services/transport/http/server.py:3637-3677` (lee la connection para
  inyectar el `access_token` en `SocialPublishContext`).

Estas rutas NO son parte de feature 5 — pero **siguen leyendo
`runtime.get_ghl_connection_by_agency` / `to_public_dict()`**, así que el
extract no puede romper esos getters mientras viva server.py (hasta feature 9).

---

## 2. Repositorio + tabla `provider_connections`

### Modelo SQLAlchemy

`shared/db/orm.py:100-129` `class ProviderConnectionORM(Base)` →
`__tablename__ = "provider_connections"` (línea 101).

Columnas relevantes:

- `id: String(36) primary_key` (línea 113).
- `agency_id: String(36) FK agencies.id ondelete=CASCADE` (línea 114-118).
- `provider: Text NOT NULL` (línea 119).
- `external_id: Text NOT NULL DEFAULT ''` (línea 120).
- `config_json: JSONB NOT NULL DEFAULT '{}'::jsonb` (línea 121-125) —
  campos en claro (`user_id`, `expires_at`, …).
- **`secrets_encrypted: LargeBinary NOT NULL`** (línea 126) — bytea Fernet.
- `status: Text NOT NULL DEFAULT 'active'` (línea 127).
- `created_at`, `updated_at` (línea 128-129).
- Constraint único `(agency_id, provider)` —
  `uq_provider_connections_agency_provider` (línea 103-105).
- Índice `(provider, external_id)` (línea 106-110).

### Repo NUEVO (módulo): `ProviderConnectionRepository`

`modules/publishing/infrastructure/provider_connection_repository.py:88-242`.
Recibe `Session` por `ModuleRepository` (`shared/db/repository_base.py`) y se
expone vía `uow.publishing.connections` (`shared/db/uow.py:73-74` y `141`).

API actual (no incluye DTO `WithSecrets` para el caso CRUD admin):

- `get_by_agency_and_provider(*, agency_id, provider)` →
  `ProviderConnection | None` — sin secretos
  (líneas 91-107). **Selecciona `secrets_encrypted` solo para derivar
  `has_secret: bool`**, NO descifra (`_row_to_connection`, línea 48-85,
  `with_secrets=False` rama).
- `get_with_secrets(*, agency_id, provider)` →
  `ProviderConnectionWithSecrets | None` (líneas 109-125). Aquí sí
  llama a `decrypt_text(bytes(secrets_raw))` (`provider_connection_repository.py:66`).
- `get_by_provider_external_id(*, provider, external_id)` (líneas 127-143)
  — sin secretos.
- `list_all()` → `tuple[ProviderConnection, ...]` ordenado por `updated_at DESC`
  (líneas 145-153) — sin secretos.
- `upsert(*, agency_id, provider, external_id, config=None, secrets=None,
  status='active')` → `ProviderConnection` (líneas 155-225). Aquí el
  cifrado: `secrets_payload = json.dumps(dict(secrets or {}), separators=(",",
  ":"))` y `secrets_encrypted = encrypt_text(secrets_payload) if
  secrets_payload != "{}" else b""` (líneas 170-171). Luego INSERT/UPDATE
  pasando `secrets_encrypted` ya cifrado (líneas 178-220).
- `delete(*, agency_id, provider)` → `bool` (líneas 227-239).

`_row_to_connection(row, with_secrets=False)` (líneas 48-85) construye
`ProviderConnection`/`ProviderConnectionWithSecrets`
(`modules/publishing/domain/provider_connection.py:20-43`). Notable: nunca
expone `secrets_encrypted` raw, solo `has_secret: bool` (línea 50).

### Repo LEGACY: `GoHighLevelConnectionStore`

`repositories/stores/ghl_connection_store.py:88-278`. Está **prohibido tocar
por las reglas (`legacy_dirs_frozen`)** (`feature_list.json:11`). **Lo está
usando el server hoy** mediante `unit_of_work.ghl_connection_store`. La
feature 5 debe sustituir esa ruta del `WordPressWebhookApplication` por una
llamada a un use case que use `ProviderConnectionRepository` directamente.

Test path que aún importa el legacy: `tests/integration/test_http_transport.py:28`
(`from repositories.stores.ghl_connection_store import GoHighLevelConnectionStore`).
El nuevo test del feature 5 no debe depender de ese import.

---

## 3. `shared/db/security.py` (Fernet)

Path: `shared/db/security.py`.

Funciones públicas:

- `_fernet()` privado, `shared/db/security.py:15-16`. Construye `Fernet(
  DATABASE_ENCRYPTION_KEY.encode("utf-8"))`.
- `encrypt_text(value: str) -> bytes` —
  `shared/db/security.py:19-23`. Devuelve `b""` si vacío (no cifra
  cadena vacía).
- `decrypt_text(value: bytes | bytearray | memoryview | None) -> str` —
  `shared/db/security.py:26-29`. Devuelve `""` si entrada vacía/None.

`__all__ = ["decrypt_text", "encrypt_text"]` (línea 32).

Clave: `DATABASE_ENCRYPTION_KEY` se importa desde
`settings` (`shared/db/security.py:12`). No hay rotación implementada — una
sola clave activa.

Invocaciones existentes en el flujo de connections:

- `modules/publishing/infrastructure/provider_connection_repository.py:20`
  (import) y `:66` (decrypt en `_row_to_connection`) y `:171` (encrypt en
  `upsert`).
- `repositories/stores/ghl_connection_store.py:17` (import), `:69`
  (decrypt en `_secrets`), `:185` y `:205` (encrypt en
  `upsert_for_agency`).
- `tests/support/postgres.py:248` (encrypt al sembrar `provider_connections`).
- Duplicado legacy: `repositories/postgres/security.py` — copia byte-a-byte
  del módulo nuevo. **No usar; el destino canónico es `shared/db/security.py`.**

Ningún log/observability emite el contenido cifrado/descifrado hoy. El
`access_token` plaintext sí cruza redes en `runtime.test_gohighlevel_connection`
(server.py:1296-1309) hacia el adapter HTTP, pero nunca se loguea.

---

## 4. Use cases sugeridos

Cada use case recibe la `DatabaseUnitOfWork` (idealmente un factory) por
constructor, igual que `DecodeGoHighLevelSessionUseCase`. Vivirán en
`modules/publishing/application/use_cases/`. El cifrado/descifrado ocurre
**dentro del repositorio** (`upsert` / `_row_to_connection`), nunca en el
use case, así que el use case maneja **plaintext** local solo durante la
ejecución y nunca lo persiste.

### `attach_provider_connection`

- Inputs: `agency_id: str`, `provider: str = "gohighlevel"`,
  `external_id: str` (location_id), `secrets: Mapping[str, Any]`
  (`{access_token, refresh_token, expires_at}`),
  `config: Mapping[str, Any]` (`{user_id, expires_at}`),
  `status: str = "active"`.
- Output: `ProviderConnection` (sin secretos — `has_secret` ya True).
- Validación: agency existe (404 `ADMIN_AGENCY_NOT_FOUND`); `external_id` y
  `secrets["access_token"]` no vacíos (mapear a códigos
  `GHL_LOCATION_ID_REQUIRED`, `GHL_ACCESS_TOKEN_REQUIRED` para no romper
  contrato).
- Errores: `ValidationError` (`shared/errors`); colisión por unique
  `(agency_id, provider)` se resuelve con upsert (existente lo hace ya).
- Cifrado: dentro de `repo.upsert(secrets=...)` (línea 171 del repo). El
  use case nunca toca `encrypt_text`.

Conviene exponer dos verbos separados a nivel API (POST attach + PUT update)
aunque el repo los unifique en `upsert`. Pueden compartir cuerpo de use case
si se prefiere mínimo cambio; la feature pide ambos como entradas distintas.

### `list_provider_connections`

- Inputs: `agency_id: str | None = None` (filtro opcional;
  hoy `list_all()` no filtra; añadir filtro o hacer `list_for_agency`).
- Output: `tuple[ProviderConnection, ...]` (sin secretos).
- Errores: ninguno explícito (lista vacía).
- Descifrado: NO se ejecuta (todas las salidas son `ProviderConnection`,
  `with_secrets=False`).

### `get_provider_connection`

- Inputs: `agency_id: str`, `provider: str = "gohighlevel"`.
- Output: `ProviderConnection | None`.
- Errores: el handler decide si devuelve 404 — alineado con
  `GHL_CONNECTION_NOT_FOUND` (server.py:2283).
- Descifrado: NO. Para no exponer secretos, este use case NUNCA debe
  delegar a `repo.get_with_secrets`. Mantener `with_secrets` solo para
  consumidores que decifran (worker en publish flow).

### `update_provider_connection`

- Inputs: idénticos a `attach`. Mismo `repo.upsert` (existing path en líneas
  201-220 del repo). Validar que el row existe antes (si la feature exige
  separar attach vs update).
- Output: `ProviderConnection`.
- Errores: 404 si no existe (mapear a `GHL_CONNECTION_NOT_FOUND`).
- Cifrado: en repo.

### `detach_provider_connection`

- Inputs: `agency_id: str`, `provider: str = "gohighlevel"`.
- Output: `bool` (deleted).
- Errores: el handler 404 si no existía
  (`provider_connection_repository.py:227-239`, línea 232 RETURNING `id`).
- No toca cifrado.

---

## 5. Payloads Pydantic

Lugar: `modules/publishing/transport/payloads/connections.py` (siguiendo el
patrón `payloads/sessions.py` que la feature 2 introducirá).

### Request — `AttachProviderConnectionRequest` / `UpdateProviderConnectionRequest`

Hoy en `services/transport/http/server.py:243-281`
`_AdminGhlConnectionUpsertPayload`:

- `location_id: str` min_length=1 (línea 266-270).
- `user_id: str | None` (línea 271).
- **`access_token: str` min_length=1, "Treated as a secret"** (línea
  272-275) — plaintext entrante.
- `refresh_token: str | None default=""` (línea 276).
- `expires_at: str | None default=""` (línea 277-280).
- `status: str | None default=None` (línea 281).
- `model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)`
  (línea 251-253).

Mapeo al payload nuevo:

```
{
  external_id: str,        # was location_id
  provider: str = "gohighlevel",
  config: {user_id, expires_at, ...},
  secrets: {access_token, refresh_token, expires_at},
  status: str = "active",
}
```

Para no romper el frontend que ya manda
`{location_id, user_id, access_token, refresh_token, expires_at, status}`, el
router debe aceptar el shape legacy y construir `secrets` y `config`
internamente (alias o adaptador). Documentar como "compat".

### Response

- **NUNCA echo `access_token` ni `refresh_token`.**
- Estructura objetivo:

```
{
  connection_id, agency_id, provider, external_id,
  config: {user_id, expires_at},
  status, has_secret, created_at, updated_at
}
```

Hoy el response usa
`record.to_public_dict()` (`repositories/stores/ghl_connection_store.py:33-45`)
que ya hace `has_access_token: bool(self.access_token.strip())`. **Pero
internamente el dataclass legacy `GoHighLevelConnectionRecord` carga
`access_token` plaintext en memoria**
(`repositories/stores/ghl_connection_store.py:21-31` y línea 269) — mantener
ese plaintext en el ámbito del proceso es el riesgo (ver §11).

El nuevo `ProviderConnection`
(`modules/publishing/domain/provider_connection.py:20-30`) **no carga
plaintext nunca** (solo `has_secret: bool`). Migrar al dataclass nuevo cierra
ese gap.

Helpers:

- `serialize_provider_connection(record: ProviderConnection) -> dict`.
- Reutilizar (o crear) `to_public_dict` en el dataclass del módulo (no existe
  hoy en `ProviderConnection`).

---

## 6. Helpers transversales que invoca

- `apps/api/admin_auth.py:59` `authorize_admin_request(request, policy)` y
  `apps/api/admin_auth.py:24` `AdminAccessPolicy`.
- `apps/api/error_handlers.py` `json_error(...)` — formato JSON estándar.
- `shared.errors` — `ApplicationError`, `ValidationError`,
  `ResourceNotFoundError` (importadas hoy desde `core.errors` en server.py:68;
  ya hay equivalentes en `shared/errors/`).
- `shared.observability.log_persistent_event` (hoy aliased de `core.logging`
  en server.py:80).
- `shared.db.uow.DatabaseUnitOfWork` — wrapper que expone
  `uow.publishing.connections`.
- `modules.publishing.infrastructure.provider_connection_repository.ProviderConnectionRepository`
  (línea 88).
- `shared.db.security.encrypt_text` / `decrypt_text` (vía repo, no llamarlo
  directo desde transport ni use case).

---

## 7. Imports cruzados peligrosos

Solo el server.py legacy mezcla todo:

- `services/transport/http/server.py:20-29` importa de `application.*` y
  `core.*` — directorios congelados (`feature_list.json:11`). El nuevo
  router NO debe heredar esos imports.
- `services/transport/http/server.py:1296-1309` instancia
  `GoHighLevelClient` (de `services/publishing/social_delivery/gohighlevel_client.py`)
  y `GoHighLevelSocialService`. Esto es legacy `services/`. La ruta `/test`
  depende de ello; si feature 5 incluye `/test` (la feature lo describe como
  parte del CRUD de connections aunque no sea CRUD strict), tendrá que
  consumir el adapter desde `modules/publishing/infrastructure/adapters/...`
  o esperar a que se mueva el client.
- `modules/publishing/infrastructure/adapters/gohighlevel/multi_publish.py:16`,
  `retrying.py:8`, `single_publish.py:8`, `publisher.py:22-25` siguen
  importando `services.publishing.social_delivery.gohighlevel_client` /
  `_media_service` / `_social_service`. Es legacy compartido; no es
  competencia de feature 5 moverlo, pero el `/ghl-connection/test` lo toca.

Recomendación: la feature 5, según el acceptance, NO menciona `/test`
expresamente. Mantener `/test` viviendo en server.py un release más, o si
se traslada, importar `GoHighLevelSocialService` desde
`services.publishing.social_delivery.gohighlevel_social_service` (legacy
visible) — flag de deuda técnica.

---

## 8. Tests existentes

- `tests/integration/test_http_transport.py:28` —
  `from repositories.stores.ghl_connection_store import GoHighLevelConnectionStore`.
- `tests/integration/test_http_transport.py:36` —
  `from tests.support.postgres import seed_provider_connection`.
- `tests/integration/test_http_transport.py:162-211` —
  `test_webhook_resolves_agency_from_rest_domain_and_uses_stored_ghl_connection`
  (usa `seed_provider_connection`).
- `tests/integration/test_http_transport.py:213-242` —
  `test_webhook_rejects_when_agency_has_no_ghl_connection`.
- `tests/integration/test_http_transport.py:267-...` — un tercer caso que
  vuelve a sembrar la connection (línea 267).
- `tests/integration/test_http_transport.py:426-447` —
  `test_admin_upserts_and_reads_ghl_connection_for_an_agency`. **Es el
  test directo del PUT `/v1/admin/agencies/{id}/ghl-connection`** que la
  feature 5 debe portar/replicar en
  `tests/integration/publishing/test_connections_router.py`. Usa
  `GoHighLevelConnectionStore` (legacy) para verificar persistencia — el
  test nuevo debería usar `ProviderConnectionRepository` o asserts a SQL
  vía el engine de prueba.
- `tests/support/postgres.py:25` lista `"provider_connections"` en
  `ACTIVE_TABLES`.
- `tests/support/postgres.py:212-255` `seed_provider_connection(...)` (helper
  reutilizable; usa `encrypt_text` línea 248).
- `tests/test_social_publishing.py` — no toca el router; usa `GoHighLevelClient`
  directamente como fake.
- No hay tests existentes que tarjeten directamente `shared/db/security.py`;
  se prueba indirectamente vía seeds y el repo legacy.

No hay carpeta `tests/integration/publishing/` ni `tests/unit/publishing/`
todavía.

---

## 9. Acoplamiento cross-feature (clave)

**Conflicto declarado: feature 2 (`publishing_sessions_router`) vive en el
mismo módulo `modules/publishing/`.** ¿Comparten algo?

### Tabla compartida

Sí, **misma tabla `provider_connections` y mismo repo nuevo
`ProviderConnectionRepository`** (`shared/db/uow.py:74,141`).

- Feature 2 (`/v1/sessions/gohighlevel/*`):
  - `GET /v1/sessions/gohighlevel/tokens` —
    `services/transport/http/server.py:1461-1478` — usa
    `runtime.list_ghl_connections()` (legacy store) que SELECT-ea
    `provider_connections WHERE provider='gohighlevel'`.
  - `POST /v1/sessions/gohighlevel/context` —
    `services/transport/http/server.py:1481-1550` — solo decifra el SSO
    payload, **no toca la tabla**.
  - `POST /v1/sessions/gohighlevel/session` —
    `services/transport/http/server.py:1552-1588` — usa
    `runtime.get_ghl_connection_by_location(location_id=...)` (línea 1568).
  - `POST /v1/sessions/gohighlevel/test` —
    `services/transport/http/server.py:1590-1640` — usa
    `runtime.get_ghl_connection_by_location` (línea 1606) y
    `runtime.test_gohighlevel_connection` (línea 1616).

### Cliente HTTP compartido

Sí. Tanto feature 2 (`/v1/sessions/gohighlevel/test`, server.py:1616) como
feature 5 (`/v1/admin/agencies/{id}/ghl-connection/test`, server.py:2319)
invocan el mismo `runtime.test_gohighlevel_connection` que dentro construye
`GoHighLevelClient + GoHighLevelSocialService`
(`services/transport/http/server.py:1296-1309`).

### Helpers compartidos

- `runtime.get_ghl_connection_by_location(location_id=...)` —
  `services/transport/http/server.py:967-969`. Solo lo usa feature 2.
- `runtime.get_ghl_connection_by_agency(agency_id=...)` —
  `services/transport/http/server.py:963-965`. Lo usa feature 5 + ingestion
  webhook (3639) + reels endpoints + social-accounts endpoint.
- `runtime.list_ghl_connections()` —
  `services/transport/http/server.py:971-973`. Lo usa feature 2.

### Decisión paralelo vs serial

**Pueden ir en paralelo** si:

1. Cada feature crea su propio router y use cases sin tocar al otro.
2. Ambas referencian el mismo `uow.publishing.connections` (existente,
   no requiere cambios concurrentes).
3. La eliminación de los métodos del runtime
   (`upsert_ghl_connection`/`list_ghl_connections`/...) y la del legacy
   `ghl_connection_store` queda para feature 9 (eliminar el server.py).
4. No tocan a la vez el mismo archivo: cada feature toca rutas distintas y
   crea routers distintos.

**Conflictos reales (riesgo bajo, alineables):**

- Pueden chocar si ambas registran routers en `apps/api/app_factory.py`
  simultáneamente — merge fácil.
- Pueden chocar si ambas crean
  `modules/publishing/transport/http/__init__.py` o
  `modules/publishing/transport/payloads/__init__.py` — patch trivial.

Conclusión: **independientes, paralelizables**, con el aviso de coordinar
el `app_factory.py`.

---

## 10. LoC estimado a mover

| Bloque | Origen | Líneas |
|---|---|---|
| Pydantic `_AdminGhlConnectionUpsertPayload` | server.py:243-281 | ~39 |
| Handler PUT | server.py:2199-2258 | ~60 |
| Handler DELETE | server.py:2260-2289 | ~30 |
| Handler POST .../test | server.py:2291-2350 | ~60 |
| Métodos `runtime.upsert_ghl_connection`, `get_ghl_connection_by_agency`, `delete_ghl_connection`, `list_ghl_connections`, `require_ghl_connection_for_agency` (a use cases) | server.py:940-982 | ~43 |
| Método `runtime.test_gohighlevel_connection` (si se traslada) | server.py:1296-1309 | ~14 |
| **Total a borrar de server.py** | | **~250** |
| **Nuevo en `modules/publishing/transport/http/connections_router.py`** | | ~250-300 (router + payloads importados, similar a sessions) |
| **Nuevo en `modules/publishing/application/use_cases/*.py`** | 5 archivos | ~150-200 total |
| **Nuevo en `modules/publishing/transport/payloads/connections.py`** | | ~80 |
| Tests nuevos `tests/unit/publishing/` + `tests/integration/publishing/test_connections_router.py` | | ~200-300 |

Repo (`provider_connection_repository.py`) ya existe: 0 LoC nuevos en
infra a no ser que se añada `list_for_agency`. Si se añade un GET
dedicado, repo necesita un método dedicado o reutilizar `get_by_agency_and_provider`.

---

## 11. Riesgos / blockers

### A. Tokens en logs / traces / errors

- `services/transport/http/server.py:2247-2253` — bloque `except
  ApplicationError`. El mensaje del error puede contener `secrets` si una
  capa interna lo incluyera en `error.context`. Hoy no se ve, pero
  cualquier `context={"access_token": ...}` saldría al cliente. **Auditar
  los `context=` en cualquier raise dentro del path del use case.**
- `services/transport/http/server.py:2256-2258` — response body =
  `record.to_public_dict()`, que en el nuevo `ProviderConnection` NO
  expone secretos (`has_secret` solo). En el legacy
  `GoHighLevelConnectionRecord.to_public_dict`
  (`repositories/stores/ghl_connection_store.py:33-45`) tampoco. **Asegurar
  que el adaptador no devuelve `record` con `access_token`** sin pasar por
  el método.
- `apps/api/logging_middleware.py` `DEFAULT_SENSITIVE_BODY_FIELDS` — el
  request body cae bajo el middleware que ya redacta campos sensibles
  (`server.py:95`). Verificar que `access_token`, `refresh_token`,
  `secrets.access_token` están en la lista de redacción ANTES de loguear
  el request del PUT.
- `services/transport/http/server.py:1534-1541` y `:1570-1577` —
  `log_persistent_event` con `location_id`, `user_id` (no token). Seguir
  ese patrón en los nuevos eventos.
- `_format_client(request)` y `_get_request_id(request)` están bien — no
  fugan tokens.
- **No introducir** `logger.exception` con `context={"secrets": ...}` en
  los use cases nuevos.

### B. Doble path de cifrado

`shared/db/security.py` y `repositories/postgres/security.py` son idénticos
byte a byte. **El repo nuevo importa solo de `shared/db/security.py`** —
correcto; no introducir el legacy en los use cases.

### C. Ruta `/test` (POST)

No está en el acceptance criteria de feature 5, pero está pegada al CRUD por
path. Decisiones posibles:

1. Mover (junto con `runtime.test_gohighlevel_connection`) al router nuevo y
   crear `test_provider_connection` use case.
2. Dejarlo en server.py hasta feature 9.

Si se mueve, el use case necesita un cliente HTTP. Cliente vive en `services/`
(legacy), por lo que el use case lo importará temporalmente desde
`services/publishing/social_delivery/gohighlevel_social_service.py`. Eso
arrastra `services/`, en violación blanda con `legacy_dirs_frozen`.
**Recomendación: NO mover `/test` en esta feature**; dejarlo y borrarlo
en feature 9 — está fuera del scope literal.

### D. Persistencia de `access_token` plaintext en memoria

`GoHighLevelConnectionRecord` (legacy) lo carga (`ghl_connection_store.py:269`),
y los call sites del runtime (server.py:1156, 1175-1176, 3672) lo leen.
**Mientras feature 5 no migre TAMBIÉN al webhook ingestion bridge
(server.py:3639) y al `social-accounts` endpoint (server.py:3395),
seguirá habiendo `record.access_token` plaintext en RAM**. No es un blocker
para feature 5 — es un riesgo arquitectónico que se resuelve plenamente en
feature 9.

### E. Compatibilidad de payload

El frontend manda hoy
`{location_id, user_id, access_token, refresh_token, expires_at, status}`
(plano). Si el router nuevo cambia a
`{external_id, secrets: {...}, config: {...}}`, **el admin panel se rompe**.
Requisito: aceptar el shape legacy (alias) y construir `secrets` y `config`
en el adaptador, manteniendo el endpoint backward-compatible. Documentar.

### F. Ausencia de GET dedicado

La feature 5 lista `get_provider_connection` como use case requerido, pero
**hoy no hay GET para `/admin/agencies/{id}/ghl-connection`**. La feature
debe definir explícitamente:

- Crear el GET (200/404) en el router nuevo, o
- Dejar el use case sin ruta (solo se invoca desde
  `GET /admin/agencies/{id}` que se mueve en feature 3).

Recomendación: crear el GET nuevo — es trivial y estándar CRUD.

### G. Conflictos paralelos con feature 2

Coordinar `app_factory.py` y `modules/publishing/transport/http/__init__.py`.
Risk-bajo, lock por leader.

### H. Tests legacy a deprecar

`tests/integration/test_http_transport.py:426-447` debería marcarse
deprecated cuando feature 5 cierre, y borrarse en feature 9. Replicar su
intención (PUT + verificación SQL) en
`tests/integration/publishing/test_connections_router.py`, pero leyendo vía
`uow.publishing.connections.get_by_agency_and_provider` o vía SQL directo
(no via `GoHighLevelConnectionStore`).

---

## Apéndice — paths útiles de un vistazo

- `services/transport/http/server.py:2199-2350` — bloque de rutas a extraer.
- `services/transport/http/server.py:940-982` — métodos del runtime a
  trasladar a use cases.
- `services/transport/http/server.py:243-281` — payload Pydantic a portar.
- `modules/publishing/infrastructure/provider_connection_repository.py:88-242`
  — repo destino (sin cambios obligatorios).
- `modules/publishing/domain/provider_connection.py:1-43` — dataclass
  destino (no carga plaintext).
- `shared/db/security.py:19-29` — Fernet helpers.
- `shared/db/orm.py:100-129` — modelo ORM `provider_connections`.
- `shared/db/uow.py:73-74,140-142` — `uow.publishing.connections`.
- `apps/api/admin_auth.py:59` — `authorize_admin_request`.
- `apps/api/error_handlers.py:json_error`.
- `tests/support/postgres.py:212-255` — `seed_provider_connection` reusable.
- `feature_list.json:88-105` — acceptance criteria feature 5.
